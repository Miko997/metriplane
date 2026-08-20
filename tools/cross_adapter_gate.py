# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Authoritative, fail-closed cross-adapter compatibility gate.

The registry is reviewed input.  This tool never derives or updates an oracle
from the output under test.  It validates discovery, executes isolated package
and portable-fixture checks, emits one machine result per check, and rejects
missing or stale results in the stable summary job.
"""

from __future__ import annotations

import argparse
import ast
import copy
import fnmatch
import hashlib
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Final

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REGISTRY_PATH: Final = Path("tests/adapter_conformance/registry.json")
REGISTRY_SCHEMA_PATH: Final = Path("tests/adapter_conformance/registry.schema.json")
RESULT_SCHEMA_PATH: Final = Path("tests/adapter_conformance/result.schema.json")
MUTATIONS_PATH: Final = Path("tests/adapter_conformance/mutations.json")
GATE_PROJECT_PATH: Final = Path("tests/adapter_conformance/pyproject.toml")
GATE_LOCK_PATH: Final = Path("tests/adapter_conformance/uv.lock")
RESULT_SCHEMA_VERSION: Final = "metriplane.cross_adapter_result.v1"
REGISTRY_SCHEMA_VERSION: Final = "metriplane.cross_adapter_registry.v1"
MUTATION_SCHEMA_VERSION: Final = "metriplane.cross_adapter_mutation_catalog.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PYTEST_PASSED = re.compile(r"(?P<count>\d+) passed")
_PYTEST_SKIPPED = re.compile(r"(?P<count>\d+) skipped")
_PYTEST_COLLECTED = re.compile(r"(?P<count>\d+) (?:tests? )?collected")
_ABSOLUTE_LEAKS = (
    re.compile(rb"/(?:home|Users)/[^/\s\x00]+/"),
    re.compile(rb"[A-Za-z]:\\Users\\[^\\\s\x00]+\\"),
)
_REQUIRED_JOB_IDS: Final = frozenset(
    {"registry", "sdk", "adapters", "fixtures", "shared-contract", "root-wheel"}
)


class GateError(ValueError):
    """A deterministic registry, execution, or result-record failure."""


def repository_root(start: Path | None = None) -> Path:
    """Return the checkout root without depending on the caller's cwd."""

    candidate = (start or Path(__file__)).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for parent in (candidate, *candidate.parents):
        if (parent / "pyproject.toml").is_file() and (parent / "metriplane").is_dir():
            return parent
    raise GateError(f"cannot locate repository root from {candidate}")


def _reject_constant(value: str) -> None:
    raise GateError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_tree(value: Any, *, location: str = "<root>") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise GateError(f"non-finite JSON number is forbidden at {location}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_nonfinite_tree(item, location=f"{location}/{index}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_nonfinite_tree(item, location=f"{location}/{key}")


def _load_json(path: Path) -> Any:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
        _reject_nonfinite_tree(value)
        return value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot load strict JSON {path}: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GateError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _commit(repo: Path) -> str:
    value = os.environ.get("CANDIDATE_SHA") or _git(repo, "rev-parse", "HEAD")
    if _SHA40.fullmatch(value) is None:
        raise GateError(f"repository commit must be a full SHA: {value!r}")
    return value


def load_registry(repo: Path | str | None = None) -> dict[str, Any]:
    """Load the authoritative registry with duplicate-key and finite-value checks."""

    root = repository_root(Path(repo)) if repo is not None else repository_root()
    value = _load_json(root / REGISTRY_PATH)
    if not isinstance(value, dict):
        raise GateError("cross-adapter registry must be a JSON object")
    return value


def load_mutation_catalog(repo: Path | str | None = None) -> dict[str, Any]:
    root = repository_root(Path(repo)) if repo is not None else repository_root()
    value = _load_json(root / MUTATIONS_PATH)
    if not isinstance(value, dict):
        raise GateError("mutation catalog must be a JSON object")
    return value


def fixture_variants(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return copied variant records annotated with their family identity."""

    values: list[dict[str, Any]] = []
    for family in registry.get("fixtures", []):
        for variant in family.get("variants", []):
            item = copy.deepcopy(variant)
            item["family_id"] = family["family_id"]
            item["family_classification"] = family["classification"]
            item["adapter_id"] = family["adapter_id"]
            values.append(item)
    return values


def _unique(values: Iterable[str], label: str) -> set[str]:
    sequence = list(values)
    if len(sequence) != len(set(sequence)):
        raise GateError(f"duplicate {label}: {sequence}")
    return set(sequence)


def _path(repo: Path, value: str, label: str, *, directory: bool | None = None) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or "\\" in value:
        raise GateError(f"unsafe registry {label} path: {value!r}")
    candidate = repo.joinpath(*pure.parts)
    if not candidate.exists():
        raise GateError(f"registered {label} does not exist: {value}")
    if directory is True and not candidate.is_dir():
        raise GateError(f"registered {label} is not a directory: {value}")
    if directory is False and not candidate.is_file():
        raise GateError(f"registered {label} is not a file: {value}")
    return candidate


def _validate_with_jsonschema(repo: Path, value: Any, schema_path: Path) -> None:
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError as exc:
        raise GateError("jsonschema is required for this validation mode") from exc
    schema = _load_json(repo / schema_path)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.exceptions.SchemaError as exc:
        raise GateError(f"invalid JSON Schema {schema_path}: {exc.message}") from exc
    except jsonschema.exceptions.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise GateError(f"{schema_path.name} rejected {location}: {exc.message}") from exc


def _manual_registry_shape(registry: Mapping[str, Any]) -> None:
    expected_top = {
        "schema_version",
        "audited_base_commit",
        "shared_infrastructure",
        "adapters",
        "fixtures",
        "unsupported_families",
        "discovery_policy",
    }
    if set(registry) != expected_top:
        raise GateError(
            f"registry top-level keys differ: missing={sorted(expected_top - set(registry))}, "
            f"extra={sorted(set(registry) - expected_top)}"
        )
    if registry["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise GateError(f"unsupported registry schema: {registry['schema_version']!r}")
    if _SHA40.fullmatch(str(registry["audited_base_commit"])) is None:
        raise GateError("audited_base_commit must be a full Git SHA")
    for key in ("shared_infrastructure", "adapters", "fixtures"):
        if not isinstance(registry[key], list) or not registry[key]:
            raise GateError(f"registry {key} must be a nonempty list")
    if not isinstance(registry["unsupported_families"], list):
        raise GateError("registry unsupported_families must be a list")

    shared = registry["shared_infrastructure"]
    adapters = registry["adapters"]
    families = registry["fixtures"]
    _unique((item["component_id"] for item in [*shared, *adapters]), "component ID")
    _unique((item["adapter_id"] for item in adapters), "adapter ID")
    _unique((item["family_id"] for item in families), "fixture family ID")
    variants = fixture_variants(registry)
    _unique((item["variant_id"] for item in variants), "fixture variant ID")
    _unique((item["fixture_id"] for item in variants), "fixture ID")
    if len(shared) != 1 or shared[0]["component_id"] != "source-adapter-sdk":
        raise GateError("Source Adapter SDK must be the single shared infrastructure record")
    if {item["component_id"] for item in adapters} != {
        "maniskill-pickcube",
        "robomimic-lowdim",
        "ros2-mcap",
        "massrobotics-amr",
    }:
        raise GateError("registry must contain exactly the four current concrete adapters")
    if {item["family_id"] for item in families} != {
        "minimal",
        "maniskill_pickcube",
        "robomimic_lowdim",
        "ros2_mcap",
        "massrobotics_amr",
    }:
        raise GateError("registry must contain exactly the five current portable families")
    if len(variants) != 9:
        raise GateError(
            f"registry must contain the current nine fixture variants, got {len(variants)}"
        )

    known_variant_ids = {item["variant_id"] for item in variants}
    fixture_ids = {item["fixture_id"] for item in variants}
    for adapter in adapters:
        if not set(adapter["portable_fixture_variants"]) <= known_variant_ids:
            raise GateError(f"{adapter['component_id']} references an unknown portable variant")
        expected = adapter["expected_results"]
        if {expected["incident_fixture_id"], expected["control_fixture_id"]} - fixture_ids:
            raise GateError(
                f"{adapter['component_id']} expected results reference unknown fixtures"
            )
        if adapter["source_conversion_requires_network"]:
            raise GateError(
                f"always-on source conversion may not require network: {adapter['component_id']}"
            )
        if not adapter["common_mutation_groups"] or not adapter["adapter_specific_mutation_groups"]:
            raise GateError(f"mutation ownership is incomplete for {adapter['component_id']}")
    for component in [*shared, *adapters]:
        if not set(component["full_suite_python_versions"]) <= set(component["python_versions"]):
            raise GateError(
                f"full-suite Python versions exceed package coverage for "
                f"{component['component_id']}"
            )
        format_policy = component["format_policy"]
        if format_policy["mode"] == "checked_in":
            if format_policy["expected_reformatted_files"]:
                raise GateError(
                    f"checked-in format policy cannot expect rewrites: {component['component_id']}"
                )
            if component["commands"]["format"] != "uv run --frozen ruff format --check .":
                raise GateError(f"checked-in format command drift for {component['component_id']}")
        else:
            if component["component_id"] != "maniskill-pickcube":
                raise GateError("only the frozen ManiSkill proof may use format migration")
            if component["commands"]["format"] != "cross-adapter-gate:frozen-format-migration":
                raise GateError("ManiSkill format migration command drift")
            expected_paths = format_policy["expected_reformatted_files"]
            if not expected_paths:
                raise GateError("frozen format migration requires explicit changed files")
            package_path = PurePosixPath(component["package_path"])
            for value in expected_paths:
                candidate = PurePosixPath(value)
                if candidate.suffix != ".py" or not candidate.is_relative_to(package_path):
                    raise GateError(f"unsafe frozen format migration path: {value}")

    minimal = next(item for item in families if item["family_id"] == "minimal")
    if [item["kind"] for item in minimal["variants"]] != ["baseline"]:
        raise GateError("minimal must remain a standalone contract baseline")
    for family in families:
        if family["family_id"] == "minimal":
            continue
        if {item["kind"] for item in family["variants"]} != {"incident", "control"}:
            raise GateError(f"{family['family_id']} must have incident and control variants")
    unsupported = {item["family_id"]: item for item in registry["unsupported_families"]}
    if set(unsupported) != {"calvin"} or unsupported["calvin"]["status"] != "NO-GO":
        raise GateError("CALVIN must remain the explicit non-executable NO-GO record")


def _validate_mutations(repo: Path, registry: Mapping[str, Any]) -> dict[str, Any]:
    catalog = load_mutation_catalog(repo)
    if set(catalog) != {"schema_version", "mutations", "metamorphic_tests"}:
        raise GateError("mutation catalog has missing or unexpected top-level keys")
    if catalog["schema_version"] != MUTATION_SCHEMA_VERSION:
        raise GateError("unsupported mutation catalog schema")
    mutations = catalog["mutations"]
    if not isinstance(mutations, list) or not mutations:
        raise GateError("mutation catalog must contain mutations")
    required = {
        "mutation_id",
        "group",
        "applies_to",
        "mutation",
        "rejecting_component",
        "failure_stage",
        "error_category",
        "atlas_must_remain_uncalled",
        "coverage_paths",
    }
    _unique((item["mutation_id"] for item in mutations), "mutation ID")
    groups = {item["group"] for item in mutations}
    required_groups = {
        "json_structural",
        "identity",
        "time",
        "coordinates",
        "rights",
        "trust_layers",
        "filesystem",
        "maniskill_trajectory",
        "robomimic_hdf5",
        "ros2_mcap_streams",
        "ros2_tf",
        "massrobotics_clock",
        "massrobotics_datum",
        "massrobotics_complete_snapshot",
    }
    if not required_groups <= groups:
        raise GateError(f"mutation groups are missing: {sorted(required_groups - groups)}")
    for item in mutations:
        if set(item) != required:
            raise GateError(f"mutation {item.get('mutation_id')} has missing or extra fields")
        if not isinstance(item["atlas_must_remain_uncalled"], bool):
            raise GateError(f"mutation {item['mutation_id']} has invalid Atlas boundary")
        if not item["coverage_paths"]:
            raise GateError(f"mutation {item['mutation_id']} has no executable coverage")
        for value in item["coverage_paths"]:
            _path(repo, value, f"mutation coverage for {item['mutation_id']}")
    metamorphic = catalog["metamorphic_tests"]
    if not isinstance(metamorphic, list) or len(metamorphic) < 7:
        raise GateError("metamorphic catalog is incomplete")
    metamorphic_required = {
        "applies_to",
        "coverage_paths",
        "permitted_changes",
        "required_invariants",
        "test_id",
    }
    metamorphic_ids = _unique((item["test_id"] for item in metamorphic), "metamorphic test ID")
    expected_metamorphic = {
        "domain_pack_separation",
        "excluded_source_field_invariance",
        "expected_outcome_independence",
        "regression_sensitivity",
        "relevant_state_sensitivity",
        "relocation",
        "tamper_detection",
    }
    if metamorphic_ids != expected_metamorphic:
        raise GateError(
            "metamorphic catalog differs: "
            f"missing={sorted(expected_metamorphic - metamorphic_ids)}, "
            f"unexpected={sorted(metamorphic_ids - expected_metamorphic)}"
        )
    for item in metamorphic:
        if set(item) != metamorphic_required:
            raise GateError(f"metamorphic test {item.get('test_id')} has missing or extra fields")
        if not item["coverage_paths"] or not item["required_invariants"]:
            raise GateError(f"metamorphic test {item['test_id']} has no executable coverage")
        for value in item["coverage_paths"]:
            _path(repo, value, f"metamorphic coverage for {item['test_id']}")
    adapter_groups = {
        group
        for adapter in registry["adapters"]
        for group in [
            *adapter["common_mutation_groups"],
            *adapter["adapter_specific_mutation_groups"],
        ]
    }
    if not adapter_groups <= groups | {"excluded_field_invariance"}:
        raise GateError(
            f"registry references unknown mutation groups: {sorted(adapter_groups - groups)}"
        )
    return catalog


def _pyproject_identity(package: Path) -> tuple[str, str, str, dict[str, str]]:
    value = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
    project = value.get("project", {})
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        raise GateError(f"invalid project.scripts in {package / 'pyproject.toml'}")
    return (
        str(project.get("name", "")),
        str(project.get("version", "")),
        str(project.get("requires-python", "")),
        {str(key): str(item) for key, item in scripts.items()},
    )


def _verify_fixture_registry_entry(repo: Path, variant: Mapping[str, Any]) -> None:
    root = _path(repo, str(variant["path"]), "fixture variant", directory=True)
    manifest = _load_json(root / "source-manifest.json")
    expected_outcome = _load_json(root / "expected-outcome.json")
    if manifest["fixture"]["fixture_id"] != variant["fixture_id"]:
        raise GateError(f"fixture ID drift for {variant['variant_id']}")
    if expected_outcome["fixture_id"] != variant["fixture_id"]:
        raise GateError(f"expected outcome ID drift for {variant['variant_id']}")
    if (
        expected_outcome.get("role") != "test_metadata_only"
        or expected_outcome.get("atlas_input") is not False
    ):
        raise GateError(f"expected outcome became an input for {variant['variant_id']}")
    session = root / manifest["normalized_artifacts"]["session"]["path"]
    if _sha256(session) != variant["session_sha256"]:
        raise GateError(f"session identity drift for {variant['variant_id']}")
    checksum_path = root / manifest["normalized_artifacts"]["checksums_path"]
    if _sha256(checksum_path) != variant["fixture_fingerprint"]:
        raise GateError(f"fixture fingerprint drift for {variant['variant_id']}")
    expected = variant["expected"]
    if expected_outcome["frame_count"] != expected["frame_count"]:
        raise GateError(f"frame oracle drift for {variant['variant_id']}")
    if expected_outcome["event_count"] != len(expected["events"]):
        raise GateError(f"event oracle drift for {variant['variant_id']}")
    for field in ("deviation_count", "incident_count"):
        if expected_outcome[field] != expected[field]:
            raise GateError(f"{field} oracle drift for {variant['variant_id']}")
    if expected_outcome["event_types"] != [item["event_type"] for item in expected["events"]]:
        raise GateError(f"event sequence oracle drift for {variant['variant_id']}")
    if expected_outcome["incident_types"] != expected["incident_types"]:
        raise GateError(f"incident type oracle drift for {variant['variant_id']}")


def discover_repository(repo: Path | str, registry: Mapping[str, Any]) -> dict[str, Any]:
    """Require exact registry-to-repository coverage and return inventory counts."""

    root = repository_root(Path(repo))
    policy = registry["discovery_policy"]
    adapter_root = _path(root, policy["adapter_root"], "adapter root", directory=True)
    fixture_root = _path(root, policy["fixture_root"], "fixture root", directory=True)
    proof_root = _path(root, policy["proof_root"], "proof root", directory=True)

    registered_components = [*registry["shared_infrastructure"], *registry["adapters"]]
    registered_package_paths = {item["package_path"] for item in registered_components}
    discovered_package_paths = {
        path.relative_to(root).as_posix() for path in adapter_root.iterdir() if path.is_dir()
    }
    if discovered_package_paths != registered_package_paths:
        raise GateError(
            "adapter discovery mismatch: "
            f"unregistered={sorted(discovered_package_paths - registered_package_paths)}, "
            f"missing={sorted(registered_package_paths - discovered_package_paths)}"
        )

    registered_family_paths = {item["family_path"] for item in registry["fixtures"]}
    discovered_family_paths = {
        path.relative_to(root).as_posix() for path in fixture_root.iterdir() if path.is_dir()
    }
    if discovered_family_paths != registered_family_paths:
        raise GateError(
            "fixture discovery mismatch: "
            f"unregistered={sorted(discovered_family_paths - registered_family_paths)}, "
            f"missing={sorted(registered_family_paths - discovered_family_paths)}"
        )

    registered_proof_roots: set[str] = set()
    for adapter in registry["adapters"]:
        proof = adapter["proof"]
        if proof.get("status") == "not_applicable":
            continue
        for value in proof["paths"]:
            candidate = _path(root, value, f"proof for {adapter['component_id']}")
            try:
                relative = candidate.relative_to(proof_root)
            except ValueError:
                continue
            registered_proof_roots.add(relative.parts[0])
    discovered_proof_roots = {path.name for path in proof_root.iterdir() if path.is_dir()}
    if discovered_proof_roots != registered_proof_roots:
        raise GateError(
            "proof discovery mismatch: "
            f"unregistered={sorted(discovered_proof_roots - registered_proof_roots)}, "
            f"missing={sorted(registered_proof_roots - discovered_proof_roots)}"
        )

    for component in registered_components:
        package = _path(root, component["package_path"], "package", directory=True)
        for value in component["format_policy"]["expected_reformatted_files"]:
            _path(root, value, "frozen format migration file", directory=False)
        name, version, requires_python, scripts = _pyproject_identity(package)
        if (name, version) != (component["package_name"], component["package_version"]):
            raise GateError(f"package identity drift for {component['component_id']}")
        pyproject = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))
        if pyproject["project"].get("license") != component["package_license_expression"]:
            raise GateError(f"package licence drift for {component['component_id']}")
        if requires_python != ">=3.12,<3.14":
            raise GateError(
                f"Python support drift for {component['component_id']}: {requires_python}"
            )
        module_root = package / "src" / component["module_name"]
        if not module_root.is_dir():
            raise GateError(f"module missing for {component['component_id']}: {module_root}")
        cli = component["cli_name"]
        if cli is None and scripts:
            raise GateError(f"unexpected CLI entry point for {component['component_id']}")
        if cli is not None and cli not in scripts:
            raise GateError(f"registered CLI missing for {component['component_id']}: {cli}")
        if not (package / "uv.lock").is_file():
            raise GateError(f"lock file missing for {component['component_id']}")

    variants = fixture_variants(registry)
    for variant in variants:
        _verify_fixture_registry_entry(root, variant)
    variant_by_id = {item["variant_id"]: item for item in variants}
    for adapter in registry["adapters"]:
        _path(root, adapter["dedicated_workflow"]["path"], "dedicated workflow", directory=False)
        source = adapter["source_fixture_path"]
        if isinstance(source, str):
            _path(root, source, f"source fixture for {adapter['component_id']}")
            if not adapter["commands"]["conversion"] or not adapter["commands"]["finalization"]:
                raise GateError(
                    f"local source conversion commands missing for {adapter['component_id']}"
                )
        elif adapter["commands"]["conversion"] or adapter["commands"]["finalization"]:
            raise GateError(
                f"reference-only source unexpectedly has conversion commands: "
                f"{adapter['component_id']}"
            )
        commit = adapter["source_conversion_commit"]
        _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        for notice in adapter["required_notices"]:
            _path(root, notice, f"notice for {adapter['component_id']}")
        expected_variant_ids = {
            item["variant_id"] for item in variants if item["adapter_id"] == adapter["adapter_id"]
        }
        if set(adapter["portable_fixture_variants"]) != expected_variant_ids:
            raise GateError(f"portable variant registration drift for {adapter['component_id']}")
        expected_fixture_ids = {
            variant_by_id[item]["fixture_id"] for item in adapter["portable_fixture_variants"]
        }
        if set(adapter["expected_results"].values()) != expected_fixture_ids:
            raise GateError(f"expected fixture registration drift for {adapter['component_id']}")

    matrix = _load_json(_path(root, policy["matrix_path"], "source-family matrix", directory=False))
    rows = {item["row_id"]: item for item in matrix["rows"]}
    allowed_matrix_statuses = {
        *policy["matrix_verified_statuses"],
        *policy["matrix_nonverified_statuses"],
    }
    unexpected_statuses = {
        row_id: row["deterministic_conversion_status"]["status"]
        for row_id, row in rows.items()
        if row["deterministic_conversion_status"]["status"] not in allowed_matrix_statuses
    }
    if unexpected_statuses:
        raise GateError(f"unregistered matrix evidence statuses: {unexpected_statuses}")
    matrix_adapter_rows = {item["matrix_row_id"] for item in registry["adapters"]}
    if not matrix_adapter_rows <= set(rows):
        raise GateError(
            f"registered adapters missing matrix rows: {sorted(matrix_adapter_rows - set(rows))}"
        )
    verified_rows = {
        row_id
        for row_id, row in rows.items()
        if row["deterministic_conversion_status"]["status"] in policy["matrix_verified_statuses"]
    }
    if not verified_rows <= matrix_adapter_rows:
        raise GateError(
            f"matrix has executable verified rows with no adapter: {sorted(verified_rows - matrix_adapter_rows)}"
        )
    for adapter in registry["adapters"]:
        row = rows[adapter["matrix_row_id"]]
        consistency = adapter["matrix_consistency"]
        status = row["deterministic_conversion_status"]["status"]
        if consistency["status"] == "consistent":
            if status not in policy["matrix_verified_statuses"]:
                raise GateError(
                    f"matrix row for {adapter['component_id']} lost verified evidence status"
                )
        elif (
            row["decision"] != consistency["matrix_decision"]
            or status != consistency["deterministic_conversion_status"]
        ):
            raise GateError(f"documented matrix gap drift for {adapter['component_id']}")
    unsupported_rows = {item["matrix_row_id"]: item for item in registry["unsupported_families"]}
    for row_id, item in unsupported_rows.items():
        if rows.get(row_id, {}).get("decision") != item["status"]:
            raise GateError(f"unsupported family decision drift for {row_id}")
        evidence = _path(root, item["evidence_path"], f"unsupported evidence for {row_id}")
        if _sha256(evidence) != item["evidence_sha256"]:
            raise GateError(f"unsupported evidence identity drift for {row_id}")
        if list(root.glob(item["forbidden_adapter_glob"])):
            raise GateError(f"unsupported family silently gained an adapter: {row_id}")
        if list(root.glob(item["forbidden_fixture_glob"])):
            raise GateError(f"unsupported family silently gained a fixture: {row_id}")

    return {
        "component_count": len(registered_components),
        "adapter_count": len(registry["adapters"]),
        "fixture_family_count": len(registry["fixtures"]),
        "fixture_variant_count": len(variants),
        "proof_count": len(discovered_proof_roots),
        "verified_matrix_rows": sorted(verified_rows),
    }


def validate_registry(
    repo: Path | str,
    registry: Mapping[str, Any],
    *,
    require_jsonschema: bool = False,
) -> dict[str, Any]:
    """Validate the strict registry, mutation ownership, and live discovery."""

    root = repository_root(Path(repo))
    _path(root, GATE_PROJECT_PATH.as_posix(), "gate project", directory=False)
    _path(root, GATE_LOCK_PATH.as_posix(), "gate lock", directory=False)
    _manual_registry_shape(registry)
    if require_jsonschema:
        _validate_with_jsonschema(root, registry, REGISTRY_SCHEMA_PATH)
    _validate_mutations(root, registry)
    return discover_repository(root, registry)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            value = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
        except (json.JSONDecodeError, GateError) as exc:
            raise GateError(f"invalid JSONL {path}:{number}: {exc}") from exc
        if not isinstance(value, dict):
            raise GateError(f"JSONL row must be an object: {path}:{number}")
        _reject_nonfinite_tree(value, location=f"{path}:{number}")
        rows.append(value)
    return rows


def assert_fixture_contract(
    repo: Path | str,
    variant: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove shared normalized/trust/completeness invariants for one fixture."""

    root = repository_root(Path(repo))
    fixture_root = _path(root, str(variant["path"]), "fixture variant", directory=True)
    from metriplane.external_sources.contract import validate_external_fixture_bundle

    validated = validate_external_fixture_bundle(fixture_root)
    manifest = _load_json(fixture_root / "source-manifest.json")
    expected_outcome = _load_json(fixture_root / "expected-outcome.json")
    session_path = fixture_root / manifest["normalized_artifacts"]["session"]["path"]
    rows = _jsonl(session_path)
    frame_ids = [row.get("frame_id") for row in rows]
    times = [row.get("ts") for row in rows]
    frame_ids_ordered = frame_ids == list(range(len(rows)))
    numeric_times = [
        float(value)
        for value in times
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    ]
    times_finite_monotonic = len(numeric_times) == len(times) and numeric_times == sorted(
        numeric_times
    )
    object_counts = {len(row.get("objects", [])) for row in rows}
    expected_objects = int(variant["expected"]["objects_per_frame"])
    object_ids_valid_unique = True
    for row in rows:
        ids = [item.get("id") for item in row.get("objects", [])]
        object_ids_valid_unique &= all(isinstance(value, str) and value.strip() for value in ids)
        object_ids_valid_unique &= len(ids) == len(set(ids))
    events_empty = all(row.get("events") == [] for row in rows)
    trust = manifest["trust_layers"]
    trust_layers_separated = (
        trust.get("source_annotations_can_drive_incidents") is False
        and trust.get("expected_outcome_is_atlas_input") is False
        and trust.get("operator_configured_rules") == "domain_pack_only"
        and trust.get("metriplane_derived_results") == "atlas_outputs_only"
    )
    normalization = manifest["normalization"]
    declarations = all(key in normalization for key in ("clock", "coordinates", "completeness"))
    declarations &= normalization["completeness"].get("frame_semantics") == "complete_snapshot"
    declarations &= normalization.get("authoritative_object_collection") == "objects"
    expected_outcome_test_only = (
        expected_outcome.get("role") == "test_metadata_only"
        and expected_outcome.get("atlas_input") is False
        and manifest["evaluation"].get("expected_outcome_is_input") is False
        and manifest["normalized_artifacts"]["expected_outcome"].get("atlas_input") is False
    )
    checks = {
        "fixture_id": manifest["fixture"]["fixture_id"],
        "kind": variant["kind"],
        "frame_count": len(rows),
        "objects_per_frame": next(iter(object_counts)) if len(object_counts) == 1 else -1,
        "schema_version": manifest["normalization"]["frame_state_model_version"],
        "frame_ids_ordered": frame_ids_ordered,
        "times_finite_monotonic": times_finite_monotonic,
        "object_ids_valid_unique": object_ids_valid_unique,
        "events_empty": events_empty,
        "trust_layers_separated": trust_layers_separated,
        "clock_coordinate_completeness_declarations": declarations,
        "checksums_valid": validated is not None,
        "expected_outcome_test_only": expected_outcome_test_only,
    }
    expected = variant["expected"]
    if checks["fixture_id"] != variant["fixture_id"]:
        raise GateError(f"fixture ID mismatch for {variant['variant_id']}")
    if checks["frame_count"] != expected["frame_count"]:
        raise GateError(f"frame count mismatch for {variant['variant_id']}")
    if checks["objects_per_frame"] != expected_objects:
        raise GateError(f"complete-snapshot object count mismatch for {variant['variant_id']}")
    boolean_checks = {key: value for key, value in checks.items() if isinstance(value, bool)}
    failures = [key for key, value in boolean_checks.items() if not value]
    if failures:
        raise GateError(f"fixture contract failed for {variant['variant_id']}: {failures}")
    return checks


def _platform_name() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name == "linux":
        return "linux"
    raise GateError(f"unsupported gate operating system: {platform.system()}")


def _python_version() -> str:
    return platform.python_version()


def _level() -> str:
    value = os.environ.get("CROSS_ADAPTER_LEVEL", "pr")
    if value not in {"pr", "exhaustive"}:
        raise GateError(f"unsupported validation level: {value}")
    return value


def _empty_result(
    repo: Path,
    *,
    component_id: str,
    component_type: str,
    adapter_id: str | None = None,
    package_name: str | None = None,
    package_version: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "repository_commit": _commit(repo),
        "component_id": component_id,
        "adapter_id": adapter_id,
        "component_type": component_type,
        "package_name": package_name,
        "package_version": package_version,
        "python_version": _python_version(),
        "operating_system": _platform_name(),
        "level": _level(),
        "commands": [],
        "tests": {"collected": 0, "passed": 0, "skipped": 0, "skip_reasons": []},
        "fixture_variants": [],
        "normalized_frame_counts": {},
        "event_counts": {},
        "deviation_counts": {},
        "incident_counts": {},
        "incident_bundle_presence": {},
        "bundle_verification": {},
        "regression_presence": {},
        "regression_execution": {},
        "conversion_equivalence": "not_applicable",
        "atlas_equivalence": "not_applicable",
        "contract_result": "not_applicable",
        "determinism_result": "not_applicable",
        "negative_tests_result": "not_applicable",
        "source_provenance_identities": {},
        "package_content_result": "not_applicable",
        "rights_result": "not_applicable",
        "privacy_result": "not_applicable",
        "duration_seconds": 0.0,
        "final_result": "fail",
    }


def _result_name(result: Mapping[str, Any]) -> str:
    component = re.sub(r"[^a-z0-9._-]+", "-", str(result["component_id"]).lower())
    python = ".".join(str(result["python_version"]).split(".")[:2])
    return f"{component}-{result['operating_system']}-py{python}.json"


def _validate_result_shape(result: Mapping[str, Any]) -> None:
    schema = _load_json(repository_root() / RESULT_SCHEMA_PATH)
    required = set(schema["required"])
    if set(result) != required:
        raise GateError(
            f"result fields differ: missing={sorted(required - set(result))}, "
            f"extra={sorted(set(result) - required)}"
        )
    _validate_with_jsonschema(repository_root(), result, RESULT_SCHEMA_PATH)
    if result["schema_version"] != RESULT_SCHEMA_VERSION:
        raise GateError("result schema version mismatch")
    if _SHA40.fullmatch(str(result["repository_commit"])) is None:
        raise GateError("result repository_commit is not a full SHA")
    if result["final_result"] not in {"pass", "fail"}:
        raise GateError("invalid final_result")
    if not isinstance(result["commands"], list):
        raise GateError("result commands must be a list")
    if float(result["duration_seconds"]) < 0:
        raise GateError("negative result duration")


def _validate_result_semantics(repo: Path, result: Mapping[str, Any]) -> None:
    if result["final_result"] != "pass":
        return
    commands = result["commands"]
    if not commands or any(item["exit_code"] != 0 for item in commands):
        raise GateError("passing result requires at least one successful command")
    tests = result["tests"]
    if tests["passed"] + tests["skipped"] != tests["collected"]:
        raise GateError("passing result test counts do not reconcile")
    component_type = result["component_type"]
    registry = load_registry(repo)
    registered_components = {
        item["component_id"]: item
        for item in [*registry["shared_infrastructure"], *registry["adapters"]]
    }
    registered_variants = {item["variant_id"]: item for item in fixture_variants(registry)}
    if component_type in {"shared_infrastructure", "source_adapter"}:
        component = registered_components.get(result["component_id"])
        if component is None or component["component_type"] != component_type:
            raise GateError("result component identity is not registered for its type")
        if (
            result["package_name"] != component["package_name"]
            or result["package_version"] != component["package_version"]
            or result["adapter_id"] != component.get("adapter_id")
        ):
            raise GateError("result package or adapter identity differs from the registry")
    elif component_type == "portable_fixture":
        variant = registered_variants.get(result["component_id"])
        if variant is None or result["adapter_id"] != variant["adapter_id"]:
            raise GateError("portable-fixture result identity differs from the registry")
        if result["package_name"] != "metriplane" or result["package_version"] is not None:
            raise GateError("portable-fixture package identity is invalid")
    elif component_type == "shared_contract":
        if (
            result["component_id"] != "shared-contract-and-mutations"
            or result["adapter_id"] is not None
            or result["package_name"] != "metriplane"
            or result["package_version"] is not None
        ):
            raise GateError("shared-contract result identity is invalid")
    elif component_type == "root_wheel":
        if (
            result["component_id"] != "root-wheel-clean-room"
            or result["adapter_id"] is not None
            or result["package_name"] != "metriplane"
            or result["package_version"] is not None
        ):
            raise GateError("root-wheel result identity is invalid")
    full_suite_evidence = True
    if component_type in {"shared_infrastructure", "source_adapter"}:
        component = registered_components[result["component_id"]]
        python_minor = ".".join(str(result["python_version"]).split(".")[:2])
        full_suite_evidence = python_minor in component["full_suite_python_versions"]
    if (
        full_suite_evidence
        and component_type
        in {
            "shared_infrastructure",
            "source_adapter",
            "shared_contract",
        }
        and (tests["collected"] == 0 or tests["passed"] == 0)
    ):
        raise GateError(f"passing {component_type} result requires executed tests")
    required_pass: dict[str, tuple[str, ...]] = {
        "shared_infrastructure": (
            "contract_result",
            "determinism_result",
            "negative_tests_result",
            "package_content_result",
            "rights_result",
            "privacy_result",
        ),
        "source_adapter": (
            "contract_result",
            "determinism_result",
            "negative_tests_result",
            "package_content_result",
            "rights_result",
            "privacy_result",
        ),
        "portable_fixture": (
            "contract_result",
            "determinism_result",
            "conversion_equivalence",
            "atlas_equivalence",
            "rights_result",
            "privacy_result",
        ),
        "shared_contract": (
            "contract_result",
            "determinism_result",
            "negative_tests_result",
            "rights_result",
            "privacy_result",
        ),
        "root_wheel": (
            "contract_result",
            "atlas_equivalence",
            "package_content_result",
            "rights_result",
            "privacy_result",
        ),
    }
    failures = [name for name in required_pass[component_type] if result[name] != "pass"]
    if not full_suite_evidence and component_type in {
        "shared_infrastructure",
        "source_adapter",
    }:
        failures = [
            name
            for name in required_pass[component_type]
            if name not in {"contract_result", "determinism_result", "negative_tests_result"}
            and result[name] != "pass"
        ]
        for name in ("contract_result", "determinism_result", "negative_tests_result"):
            if result[name] != "not_applicable":
                raise GateError(f"package-only compatibility result must mark {name} N/A")
    if failures:
        raise GateError(f"passing {component_type} result has non-passing evidence: {failures}")
    if component_type == "source_adapter":
        adapters = {item["adapter_id"]: item for item in registry["adapters"]}
        adapter = adapters.get(result["adapter_id"])
        if adapter is None:
            raise GateError("source-adapter result has unknown adapter_id")
        local_source = isinstance(adapter["source_fixture_path"], str)
        conversion_supported = (
            ".".join(str(result["python_version"]).split(".")[:2])
            in adapter["source_conversion_python_versions"]
            and ("ubuntu" if result["operating_system"] == "linux" else "macos")
            in adapter["source_conversion_operating_systems"]
        )
        expected_conversion = "pass" if local_source and conversion_supported else "not_executed"
        if result["conversion_equivalence"] != expected_conversion:
            raise GateError(
                f"source conversion status for {adapter['component_id']} must be "
                f"{expected_conversion}"
            )
    elif component_type == "shared_infrastructure":
        if result["adapter_id"] is not None or result["conversion_equivalence"] != "not_applicable":
            raise GateError("shared infrastructure has invalid adapter/conversion status")
    elif component_type == "portable_fixture":
        if result["fixture_variants"] != [result["component_id"]]:
            raise GateError("fixture result must identify exactly its own variant")
        for field in (
            "normalized_frame_counts",
            "event_counts",
            "deviation_counts",
            "incident_counts",
            "incident_bundle_presence",
            "bundle_verification",
            "regression_presence",
            "regression_execution",
        ):
            if set(result[field]) != {result["component_id"]}:
                raise GateError(f"fixture result has incomplete {field}")
        _validate_recorded_fixture_results(result, [registered_variants[result["component_id"]]])
    elif component_type == "root_wheel":
        expected_variants = {item["variant_id"] for item in fixture_variants(registry)}
        if set(result["fixture_variants"]) != expected_variants:
            raise GateError("root-wheel result did not exercise every portable fixture")
        for field in (
            "normalized_frame_counts",
            "event_counts",
            "deviation_counts",
            "incident_counts",
            "incident_bundle_presence",
            "bundle_verification",
            "regression_presence",
            "regression_execution",
        ):
            if set(result[field]) != expected_variants:
                raise GateError(f"root-wheel result has incomplete {field}")
        _validate_recorded_fixture_results(result, list(registered_variants.values()))


def _validate_recorded_fixture_results(
    result: Mapping[str, Any], variants: Sequence[Mapping[str, Any]]
) -> None:
    for variant in variants:
        variant_id = variant["variant_id"]
        expected = variant["expected"]
        expected_values = {
            "normalized_frame_counts": expected["frame_count"],
            "event_counts": len(expected["events"]),
            "deviation_counts": expected["deviation_count"],
            "incident_counts": expected["incident_count"],
            "incident_bundle_presence": expected["evidence_bundle"] == "produced",
            "bundle_verification": expected["bundle_verification"],
            "regression_presence": expected["generated_regression"] == "produced",
            "regression_execution": expected["regression_execution"],
        }
        for field, expected_value in expected_values.items():
            if result[field][variant_id] != expected_value:
                raise GateError(
                    f"recorded {field} drift for {variant_id}: "
                    f"{result[field][variant_id]!r} != {expected_value!r}"
                )


def _write_result(results_dir: Path, result: dict[str, Any]) -> Path:
    _validate_result_shape(result)
    _validate_result_semantics(repository_root(), result)
    results_dir.mkdir(parents=True, exist_ok=True)
    if any(results_dir.iterdir()):
        raise GateError(f"result directory must be empty: {results_dir}")
    output = results_dir / _result_name(result)
    output.write_bytes(_canonical_bytes(result))
    return output


def _operation(command: str, started: float) -> dict[str, Any]:
    return {
        "command": command,
        "exit_code": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
    }


def _run_command(
    command: str, *, cwd: Path, env: Mapping[str, str] | None = None
) -> tuple[dict[str, Any], str]:
    started = time.monotonic()
    process = subprocess.run(
        ["bash", "-c", command],
        cwd=cwd,
        env={**os.environ, **dict(env or {})},
        check=False,
        capture_output=True,
        text=True,
    )
    duration = round(time.monotonic() - started, 6)
    combined = "\n".join(item for item in (process.stdout, process.stderr) if item)
    display_command = command.replace(str(repository_root()), "<checkout>")
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        display_command = display_command.replace(runner_temp, "<runner-temp>")
    display_command = re.sub(
        r"(?<![A-Za-z0-9])/(?:tmp|var/folders)/[^\s'\";|&()<>]+",
        "<temp>",
        display_command,
    )
    record = {
        "command": display_command,
        "exit_code": process.returncode,
        "duration_seconds": duration,
    }
    if process.returncode != 0:
        tail = "\n".join(combined.splitlines()[-80:])
        raise GateError(f"command failed ({process.returncode}) in {cwd}: {command}\n{tail}")
    return record, combined


def _pytest_counts(output: str) -> tuple[int, int, int]:
    passed = sum(int(match.group("count")) for match in _PYTEST_PASSED.finditer(output))
    skipped = sum(int(match.group("count")) for match in _PYTEST_SKIPPED.finditer(output))
    collected_matches = [int(match.group("count")) for match in _PYTEST_COLLECTED.finditer(output)]
    collected = collected_matches[-1] if collected_matches else passed + skipped
    collected = max(collected, passed + skipped)
    return collected, passed, skipped


def _forbidden_referenced_digests(repo: Path, registry: Mapping[str, Any]) -> set[str]:
    """Return source identities whose registered rights forbid original-byte inclusion."""

    digests: set[str] = set()
    for variant in fixture_variants(registry):
        manifest = _load_json(repo / variant["path"] / "source-manifest.json")
        rights = {item["rights_id"]: item for item in manifest["rights"]["source_artifacts"]}
        for artifact in manifest["source_artifacts"]:
            declaration = rights[artifact["rights_id"]]
            if artifact["presence"] == "referenced" and declaration["redistribution"] != "allowed":
                digests.add(artifact["sha256"])
    register = repo / "examples/external_sources/massrobotics_amr/source-reference-register.json"
    if register.is_file():
        for artifact in _load_json(register)["artifacts"]:
            digest = artifact.get("raw_sha256")
            if isinstance(digest, str):
                digests.add(digest)
    return digests


def _assert_safe_archive_member(name: str) -> PurePosixPath:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or "\\" in name:
        raise GateError(f"unsafe distribution archive member: {name}")
    return pure


def _scan_distribution_bytes(
    *, repo: Path, name: str, data: bytes, forbidden_digests: set[str]
) -> None:
    if str(repo.resolve()).encode("utf-8") in data or any(
        pattern.search(data) for pattern in _ABSOLUTE_LEAKS
    ):
        raise GateError(f"machine-local path in distribution member: {name}")
    if hashlib.sha256(data).hexdigest() in forbidden_digests:
        raise GateError(f"reference-only upstream bytes in distribution member: {name}")


def _inspect_adapter_distributions(
    repo: Path, component: Mapping[str, Any], dist: Path
) -> tuple[Path, Path]:
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise GateError(f"expected one wheel for {component['component_id']}, got {len(wheels)}")
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(sdists) != 1:
        raise GateError(f"expected one sdist for {component['component_id']}, got {len(sdists)}")
    registry = load_registry(repo)
    sibling_modules = {item["module_name"] for item in registry["adapters"]}
    sibling_modules.add("metriplane_source_adapter_sdk")
    allowed = {component["module_name"]}
    forbidden_suffixes = (".mcap", ".h5", ".hdf5", ".zip", ".pdf")
    forbidden_digests = _forbidden_referenced_digests(repo, registry)
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        if not any(name.startswith(f"{component['module_name']}/") for name in names):
            raise GateError(f"wheel is missing module {component['module_name']}")
        for name in names:
            pure = _assert_safe_archive_member(name)
            if name.lower().endswith(forbidden_suffixes):
                raise GateError(f"forbidden adapter wheel payload: {name}")
            first = pure.parts[0] if pure.parts else ""
            if first in sibling_modules - allowed:
                raise GateError(f"adapter wheel includes sibling implementation: {name}")
            if first == "metriplane" or name.startswith("adapters/"):
                raise GateError(f"adapter wheel includes root implementation: {name}")
            if not name.endswith("/"):
                _scan_distribution_bytes(
                    repo=repo,
                    name=name,
                    data=archive.read(name),
                    forbidden_digests=forbidden_digests,
                )
        for pattern in component.get("expected_wheel_contents", []):
            if not any(fnmatch.fnmatch(name, pattern) for name in names):
                raise GateError(f"adapter wheel missing registered content pattern: {pattern}")
        for pattern in component.get("forbidden_wheel_contents", []):
            matches = [name for name in names if fnmatch.fnmatch(name, pattern)]
            if matches:
                raise GateError(f"adapter wheel contains forbidden {pattern}: {matches}")
        metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise GateError("adapter wheel metadata is missing")
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        if metadata["Name"] != component["package_name"]:
            raise GateError("adapter wheel package name drift")
        if metadata["Version"] != component["package_version"]:
            raise GateError("adapter wheel version drift")
        if metadata["License-Expression"] != component["package_license_expression"]:
            raise GateError("adapter wheel licence expression drift")
        pyproject = tomllib.loads(
            (repo / component["package_path"] / "pyproject.toml").read_text(encoding="utf-8")
        )
        runtime = {
            canonicalize_name(Requirement(value).name)
            for value in pyproject["project"].get("dependencies", [])
        }
        optional_test = {
            canonicalize_name(Requirement(value).name)
            for value in pyproject["project"].get("optional-dependencies", {}).get("test", [])
        }
        metadata_requirements = [
            Requirement(value) for value in metadata.get_all("Requires-Dist", [])
        ]
        actual_runtime = {
            canonicalize_name(value.name)
            for value in metadata_requirements
            if value.marker is None or "extra" not in str(value.marker)
        }
        if actual_runtime != runtime:
            raise GateError(
                f"adapter wheel runtime dependencies drifted: {actual_runtime} != {runtime}"
            )
        for requirement in metadata_requirements:
            name = canonicalize_name(requirement.name)
            if name in optional_test and (
                requirement.marker is None or 'extra == "test"' not in str(requirement.marker)
            ):
                raise GateError(f"test-only dependency became runtime metadata: {name}")
        forbidden_dependencies = {
            "metriplane",
            *(
                canonicalize_name(item["package_name"])
                for item in registry["adapters"]
                if item["component_id"] != component["component_id"]
            ),
        }
        if actual_runtime & forbidden_dependencies:
            raise GateError(
                f"adapter wheel has forbidden root/sibling dependencies: "
                f"{sorted(actual_runtime & forbidden_dependencies)}"
            )
        sdk_name = "metriplane-source-adapter-sdk"
        if bool(component.get("source_adapter_sdk_required")) != (sdk_name in actual_runtime):
            raise GateError("adapter SDK runtime dependency declaration drift")
    with tarfile.open(sdists[0], mode="r:gz") as archive:
        for member in archive.getmembers():
            _assert_safe_archive_member(member.name)
            if member.issym() or member.islnk():
                raise GateError(f"link in adapter sdist: {member.name}")
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise GateError(f"cannot read adapter sdist member: {member.name}")
                _scan_distribution_bytes(
                    repo=repo,
                    name=member.name,
                    data=extracted.read(),
                    forbidden_digests=forbidden_digests,
                )
    return wheels[0], sdists[0]


def _clean_install_component(
    repo: Path,
    component: Mapping[str, Any],
    wheel: Path,
    temporary: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    venv = temporary / "installed-wheel"
    command = f"{shlex.quote(sys.executable)} -m venv {shlex.quote(str(venv))}"
    record, _ = _run_command(command, cwd=temporary)
    records.append(record)
    install_inputs = [wheel]
    if component.get("source_adapter_sdk_required"):
        sdk_dist = temporary / "sdk-dist"
        sdk_dist.mkdir()
        sdk = repo / "adapters/source_adapter_sdk"
        command = f"uv build --wheel --out-dir {shlex.quote(str(sdk_dist))}"
        record, _ = _run_command(command, cwd=sdk)
        records.append(record)
        sdk_wheels = sorted(sdk_dist.glob("*.whl"))
        if len(sdk_wheels) != 1:
            raise GateError("clean adapter install expected one SDK wheel")
        install_inputs.append(sdk_wheels[0])
    python = _venv_program(venv, "python")
    quoted_inputs = " ".join(shlex.quote(str(path)) for path in install_inputs)
    command = f"uv pip install --python {shlex.quote(str(python))} {quoted_inputs}"
    record, _ = _run_command(command, cwd=temporary)
    records.append(record)
    command = f"uv pip check --python {shlex.quote(str(python))}"
    record, _ = _run_command(command, cwd=temporary)
    records.append(record)
    program = f"import {component['module_name']}"
    command = f"{shlex.quote(str(python))} -c {shlex.quote(program)}"
    record, _ = _run_command(command, cwd=temporary, env={"PYTHONPATH": ""})
    records.append(record)
    if component["cli_name"] is not None:
        cli = _venv_program(venv, component["cli_name"])
        command = f"{shlex.quote(str(cli))} --help"
        record, _ = _run_command(command, cwd=temporary, env={"PYTHONPATH": ""})
        records.append(record)
    return records


def _python_tree_identity(root: Path) -> dict[str, tuple[str, str]]:
    """Return byte and syntax identities for every Python file below ``root``."""

    identities: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*.py")):
        if any(
            part in {".venv", "__pycache__", "build", "dist"}
            for part in path.relative_to(root).parts
        ):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            syntax = ast.dump(ast.parse(path.read_text(encoding="utf-8")), include_attributes=False)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise GateError(f"cannot parse format-policy input {relative}: {exc}") from exc
        identities[relative] = (_sha256(path), syntax)
    if not identities:
        raise GateError(f"format policy found no Python files under {root}")
    return identities


def _check_frozen_format_migration(
    package: Path, policy: Mapping[str, Any], temporary_root: Path
) -> list[dict[str, Any]]:
    """Apply Ruff only to a copy of proof-frozen code and prove syntax preservation."""

    before_source = _python_tree_identity(package)
    copy_root = temporary_root / "format-migration"
    shutil.copytree(
        package,
        copy_root,
        ignore=shutil.ignore_patterns(
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
        ),
    )
    before_copy = _python_tree_identity(copy_root)
    if before_copy != before_source:
        raise GateError("frozen format migration copy differs before formatting")
    ruff = _venv_program(package / ".venv", "ruff")
    if not ruff.is_file():
        raise GateError("frozen format migration requires the locked adapter Ruff binary")
    records: list[dict[str, Any]] = []
    command = f"{shlex.quote(str(ruff))} format {shlex.quote(str(copy_root))}"
    record, _ = _run_command(command, cwd=package)
    records.append(record)
    after_copy = _python_tree_identity(copy_root)
    if set(after_copy) != set(before_copy):
        raise GateError("formatter added or removed Python files in the migration copy")
    changed = {
        (package / path).relative_to(repository_root()).as_posix()
        for path in before_copy
        if before_copy[path][0] != after_copy[path][0]
    }
    expected = set(policy["expected_reformatted_files"])
    if changed != expected:
        raise GateError(
            "frozen format migration set drift: "
            f"missing={sorted(expected - changed)}, unexpected={sorted(changed - expected)}"
        )
    syntax_changes = [path for path in before_copy if before_copy[path][1] != after_copy[path][1]]
    if syntax_changes:
        raise GateError(f"formatter changed Python syntax identities: {syntax_changes}")
    command = f"{shlex.quote(str(ruff))} format --check {shlex.quote(str(copy_root))}"
    record, _ = _run_command(command, cwd=package)
    records.append(record)
    if _python_tree_identity(package) != before_source:
        raise GateError("frozen format migration modified the proof-owned package")
    return records


def check_component(repo: Path, component_id: str, results_dir: Path) -> Path:
    registry = load_registry(repo)
    validate_registry(repo, registry)
    components = {
        item["component_id"]: item
        for item in [*registry["shared_infrastructure"], *registry["adapters"]]
    }
    if component_id not in components:
        raise GateError(f"unknown registered component: {component_id}")
    component = components[component_id]
    started = time.monotonic()
    result = _empty_result(
        repo,
        component_id=component_id,
        component_type=component["component_type"],
        adapter_id=component.get("adapter_id"),
        package_name=component["package_name"],
        package_version=component["package_version"],
    )
    package = repo / component["package_path"]
    command_results: list[dict[str, Any]] = []
    test_output = ""
    skip_reasons: list[str] = []
    distribution_identities: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory(prefix=f"cross-adapter-{component_id}-") as temporary:
            temporary_root = Path(temporary)
            dist = temporary_root / "dist"
            dist.mkdir()
            commands = component["commands"]
            python_minor = ".".join(_python_version().split(".")[:2])
            full_suite_supported = python_minor in component["full_suite_python_versions"]
            ordered = (
                "sync",
                "unit_tests",
                "lint",
                "format",
                "build",
                "import_check",
                "cli_help",
                "source_inspection",
            )
            for name in ordered:
                if not full_suite_supported and name in {"unit_tests", "source_inspection"}:
                    skip_reasons.append(
                        f"{name}: full source suite is registered only for "
                        f"{component['full_suite_python_versions']}"
                    )
                    continue
                command = commands[name]
                if command is None:
                    if name in {"type_check", "source_inspection"}:
                        skip_reasons.append(f"{name}: not defined by this isolated package")
                    continue
                if name == "format" and component["format_policy"]["mode"] == "frozen_migration":
                    command_results.extend(
                        _check_frozen_format_migration(
                            package,
                            component["format_policy"],
                            temporary_root,
                        )
                    )
                    continue
                rendered = command.format(
                    adapter_commit=component.get("source_conversion_commit", ""),
                    dist=shlex.quote(str(dist)),
                    repo=shlex.quote(str(repo)),
                    temp=shlex.quote(str(temporary_root)),
                )
                command_env = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
                if component_id in {"ros2-mcap", "massrobotics-amr"}:
                    command_env["PYTHONPATH"] = str(repo) if name == "unit_tests" else ""
                if component_id in {"ros2-mcap", "massrobotics-amr"} and name == "unit_tests":
                    command_env["CROSS_ADAPTER_ROOT_TEST_PYTHON"] = sys.executable
                record, output = _run_command(
                    rendered,
                    cwd=package,
                    env=command_env,
                )
                command_results.append(record)
                if name == "unit_tests":
                    test_output = output
            if commands["type_check"] is None:
                skip_reasons.append(
                    "type_check: package has no supported static type-check command"
                )
            else:
                record, _ = _run_command(commands["type_check"], cwd=package)
                command_results.append(record)
            conversion_supported = (
                component.get("source_fixture_path") is not None
                and isinstance(component.get("source_fixture_path"), str)
                and ".".join(_python_version().split(".")[:2])
                in component.get("source_conversion_python_versions", [])
                and ("ubuntu" if _platform_name() == "linux" else "macos")
                in component.get("source_conversion_operating_systems", [])
            )
            conversion_executed = False
            if conversion_supported:
                commit = component["source_conversion_commit"]
                conversion_paths = [component["package_path"]]
                if component.get("source_adapter_sdk_required"):
                    conversion_paths.append("adapters/source_adapter_sdk")
                for conversion_path in conversion_paths:
                    frozen_tree = _git(repo, "rev-parse", f"{commit}:{conversion_path}")
                    current_tree = _git(repo, "rev-parse", f"HEAD:{conversion_path}")
                    if frozen_tree != current_tree:
                        raise GateError(
                            f"source conversion baseline tree drift for "
                            f"{component['component_id']}: {conversion_path}"
                        )
                frozen_checkout = temporary_root / "frozen-checkout"
                add_worktree = (
                    f"git worktree add --detach {shlex.quote(str(frozen_checkout))} "
                    f"{shlex.quote(commit)}"
                )
                record, _ = _run_command(add_worktree, cwd=repo)
                command_results.append(record)
                try:
                    frozen_package = frozen_checkout / component["package_path"]
                    for name in ("conversion", "finalization"):
                        command = commands[name]
                        if command is None:
                            raise GateError(f"missing {name} command for local source conversion")
                        rendered = command.format(
                            adapter_commit=commit,
                            dist=shlex.quote(str(dist)),
                            repo=shlex.quote(str(repo)),
                            temp=shlex.quote(str(temporary_root)),
                        )
                        record, _ = _run_command(
                            rendered,
                            cwd=frozen_package,
                            env={
                                "PYTHONPATH": "",
                                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                            },
                        )
                        command_results.append(record)
                finally:
                    remove_worktree = (
                        f"git worktree remove --force {shlex.quote(str(frozen_checkout))}"
                    )
                    record, _ = _run_command(remove_worktree, cwd=repo)
                    command_results.append(record)
                conversion_executed = True
            elif component["component_type"] == "source_adapter":
                skip_reasons.append(
                    "source_conversion: source or frozen conversion environment is unavailable"
                )
            wheel, sdist = _inspect_adapter_distributions(repo, component, dist)
            distribution_identities = {
                "dependency_lock_sha256": _sha256(package / "uv.lock"),
                "wheel_sha256": _sha256(wheel),
                "sdist_sha256": _sha256(sdist),
            }
            command_results.extend(_clean_install_component(repo, component, wheel, temporary_root))
        collected, passed, skipped = _pytest_counts(test_output)
        result["commands"] = command_results
        result["tests"] = {
            "collected": collected,
            "passed": passed,
            "skipped": skipped,
            "skip_reasons": skip_reasons,
        }
        if component["component_type"] == "source_adapter":
            result["conversion_equivalence"] = "pass" if conversion_executed else "not_executed"
        result["contract_result"] = "pass" if full_suite_supported else "not_applicable"
        result["determinism_result"] = "pass" if full_suite_supported else "not_applicable"
        result["negative_tests_result"] = "pass" if full_suite_supported else "not_applicable"
        result["source_provenance_identities"] = distribution_identities
        result["package_content_result"] = "pass"
        result["rights_result"] = "pass"
        result["privacy_result"] = "pass"
        result["final_result"] = "pass"
    finally:
        result["duration_seconds"] = round(time.monotonic() - started, 6)
    return _write_result(results_dir, result)


def _semantic_run(root: Path) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name in (
        "state_segment.jsonl",
        "physical_event_log.jsonl",
        "deviations.jsonl",
        "incidents.jsonl",
    ):
        value[name] = _jsonl(root / name)
    for name in ("process_trace.json", "reality_graph.json"):
        path = root / name
        value[name] = _load_json(path) if path.is_file() else None
    regressions = []
    for path in sorted((root / "regression_tests").glob("*.yaml")):
        regressions.append(
            "\n".join(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("source_bundle:")
            )
        )
    value["regressions"] = regressions
    bundles = []
    for path in sorted((root / "evidence_bundles").glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            bundles.append(
                {
                    name: hashlib.sha256(archive.read(name)).hexdigest()
                    for name in sorted(archive.namelist())
                }
            )
    value["bundle_members"] = bundles
    return value


def _scan_private_paths(root: Path, *, checkout: Path) -> None:
    checkout_bytes = str(checkout.resolve()).encode("utf-8")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise GateError(f"symlink in generated result: {path}")
        if not path.is_file():
            continue
        data = path.read_bytes()
        if checkout_bytes in data:
            raise GateError(f"checkout path leaked into durable artifact: {path}")
        if any(pattern.search(data) for pattern in _ABSOLUTE_LEAKS):
            raise GateError(f"machine-local user path leaked into durable artifact: {path}")
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    pure = PurePosixPath(name)
                    if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                        raise GateError(f"unsafe ZIP member in {path}: {name}")
                    member = archive.read(name)
                    if checkout_bytes in member or any(
                        pattern.search(member) for pattern in _ABSOLUTE_LEAKS
                    ):
                        raise GateError(f"private path leaked into ZIP member {path}:{name}")


def _assert_run_expected(output: Path, summary: Any, variant: Mapping[str, Any]) -> None:
    expected = variant["expected"]
    actual_counts = (
        summary.frame_count,
        summary.event_count,
        summary.deviation_count,
        summary.incident_count,
    )
    expected_counts = (
        expected["frame_count"],
        len(expected["events"]),
        expected["deviation_count"],
        expected["incident_count"],
    )
    if actual_counts != expected_counts:
        raise GateError(
            f"Atlas count drift for {variant['variant_id']}: {actual_counts} != {expected_counts}"
        )
    events = _jsonl(output / "physical_event_log.jsonl")
    actual_events = [
        {"frame_id": item["frame_id"], "ts": item["ts"], "event_type": item["event_type"]}
        for item in events
    ]
    if actual_events != expected["events"]:
        raise GateError(f"Atlas event sequence drift for {variant['variant_id']}: {actual_events}")
    incidents = _jsonl(output / "incidents.jsonl")
    if [item["incident_type"] for item in incidents] != expected["incident_types"]:
        raise GateError(f"Atlas incident type drift for {variant['variant_id']}")
    bundle_expected = expected["evidence_bundle"] == "produced"
    regression_expected = expected["generated_regression"] == "produced"
    if bool(summary.evidence_bundles) != bundle_expected:
        raise GateError(f"evidence bundle presence drift for {variant['variant_id']}")
    if bool(summary.generated_regressions) != regression_expected:
        raise GateError(f"regression presence drift for {variant['variant_id']}")
    if bundle_expected and not all(item.verified for item in summary.evidence_bundles):
        raise GateError(f"evidence bundle verification failed for {variant['variant_id']}")
    if regression_expected and not all(item.passed for item in summary.generated_regressions):
        raise GateError(f"generated regression failed for {variant['variant_id']}")
    if (
        not bundle_expected
        and (output / "evidence_bundles").exists()
        and list((output / "evidence_bundles").iterdir())
    ):
        raise GateError(f"control manufactured an evidence bundle: {variant['variant_id']}")
    if (
        not regression_expected
        and (output / "regression_tests").exists()
        and list((output / "regression_tests").iterdir())
    ):
        raise GateError(f"control manufactured a regression: {variant['variant_id']}")


def check_fixture(
    repo: Path,
    variant_id: str,
    results_dir: Path,
    *,
    repetitions: int,
) -> Path:
    if repetitions < 2:
        raise GateError("fixture determinism requires at least two Atlas runs")
    registry = load_registry(repo)
    validate_registry(repo, registry)
    variants = {item["variant_id"]: item for item in fixture_variants(registry)}
    if variant_id not in variants:
        raise GateError(f"unknown registered fixture variant: {variant_id}")
    variant = variants[variant_id]
    started = time.monotonic()
    result = _empty_result(
        repo,
        component_id=variant_id,
        component_type="portable_fixture",
        adapter_id=variant["adapter_id"],
        package_name="metriplane",
        package_version=None,
    )
    from metriplane.external_sources.execution import (
        run_external_fixture,
        validate_external_fixture,
    )

    with tempfile.TemporaryDirectory(prefix=f"cross-adapter-{variant_id}-") as temporary:
        temporary_root = Path(temporary)
        relocated = temporary_root / "input" / variant_id
        relocated.parent.mkdir(parents=True)
        shutil.copytree(repo / variant["path"], relocated)
        contract = assert_fixture_contract(repo, variant)
        operation_started = time.monotonic()
        validation = validate_external_fixture(relocated)
        if not validation.passed:
            raise GateError(f"relocated fixture validation failed: {validation.errors}")
        result["commands"].append(
            _operation(
                f"python-api external.validate <relocated-fixture:{variant_id}>",
                operation_started,
            )
        )
        semantics: list[dict[str, Any]] = []
        summaries = []
        for index in range(repetitions):
            output = temporary_root / "runs" / str(index)
            operation_started = time.monotonic()
            summary = run_external_fixture(
                relocated,
                output,
                run_id=f"cross_adapter_{re.sub('[^a-z0-9_]', '_', variant_id)}",
            )
            if not summary.passed:
                raise GateError(f"fixture run failed for {variant_id}: {summary.errors}")
            _assert_run_expected(output, summary, variant)
            _scan_private_paths(output, checkout=repo)
            summaries.append(summary)
            semantics.append(_semantic_run(output))
            result["commands"].append(
                _operation(
                    f"python-api external.run <relocated-fixture:{variant_id}> "
                    f"<output:{index + 1}>",
                    operation_started,
                )
            )
        reference = _canonical_bytes(semantics[0])
        if any(_canonical_bytes(item) != reference for item in semantics[1:]):
            raise GateError(f"Atlas technical outputs are not deterministic for {variant_id}")
        summary = summaries[0]
        report = _load_json(relocated / "normalization-report.json")
        conversion = report["conversion_reproducibility"]
        result["fixture_variants"] = [variant_id]
        result["normalized_frame_counts"] = {variant_id: summary.frame_count}
        result["event_counts"] = {variant_id: summary.event_count}
        result["deviation_counts"] = {variant_id: summary.deviation_count}
        result["incident_counts"] = {variant_id: summary.incident_count}
        bundles_present = bool(summary.evidence_bundles)
        regressions_present = bool(summary.generated_regressions)
        result["incident_bundle_presence"] = {variant_id: bundles_present}
        result["bundle_verification"] = {
            variant_id: (
                "pass"
                if bundles_present and all(item.verified for item in summary.evidence_bundles)
                else "not_applicable"
            )
        }
        result["regression_presence"] = {variant_id: regressions_present}
        result["regression_execution"] = {
            variant_id: (
                "pass"
                if regressions_present
                and all(item.passed for item in summary.generated_regressions)
                else "not_applicable"
            )
        }
        result["conversion_equivalence"] = (
            "pass"
            if conversion.get("status") == "demonstrated" and conversion.get("equivalent") is True
            else "not_executed"
        )
        result["atlas_equivalence"] = "pass"
        result["contract_result"] = "pass"
        result["determinism_result"] = "pass"
        result["source_provenance_identities"] = {
            "fixture_fingerprint_sha256": variant["fixture_fingerprint"],
            "manifest_sha256": _sha256(relocated / "source-manifest.json"),
            "session_sha256": variant["session_sha256"],
            "contract_schema_version": "metriplane.external_source_contract.v1",
            "frame_state_model_version": str(contract["schema_version"]),
        }
        result["rights_result"] = "pass"
        result["privacy_result"] = "pass"
        result["final_result"] = "pass"
    result["duration_seconds"] = round(time.monotonic() - started, 6)
    return _write_result(results_dir, result)


def _component_matrix(registry: Mapping[str, Any], kind: str, level: str) -> dict[str, Any]:
    components = registry["shared_infrastructure"] if kind == "sdk" else registry["adapters"]
    combinations: list[dict[str, str]] = []
    for component in components:
        if level == "pr":
            combinations.append(
                {
                    "component_id": component["component_id"],
                    "python_version": "3.12",
                    "os": "ubuntu-latest",
                }
            )
            continue
        for os_name in component["operating_systems"]:
            runner = "ubuntu-latest" if os_name == "ubuntu" else "macos-latest"
            for python in component["python_versions"]:
                combinations.append(
                    {
                        "component_id": component["component_id"],
                        "python_version": python,
                        "os": runner,
                    }
                )
    return {"include": combinations}


def _fixture_matrix(registry: Mapping[str, Any], level: str) -> dict[str, Any]:
    variants = fixture_variants(registry)
    environments = [("ubuntu-latest", "3.12")]
    if level == "exhaustive":
        environments = [
            ("ubuntu-latest", "3.12"),
            ("ubuntu-latest", "3.13"),
            ("macos-latest", "3.12"),
            ("macos-latest", "3.13"),
        ]
    return {
        "include": [
            {"variant_id": item["variant_id"], "os": os_name, "python_version": python}
            for item in variants
            for os_name, python in environments
        ]
    }


def emit_matrix(repo: Path, *, kind: str, level: str, github_output: Path | None) -> str:
    registry = load_registry(repo)
    validate_registry(repo, registry)
    if kind not in {"sdk", "adapters", "fixtures"}:
        raise GateError(f"unsupported matrix kind: {kind}")
    if level not in {"pr", "exhaustive"}:
        raise GateError(f"unsupported matrix level: {level}")
    value = (
        _fixture_matrix(registry, level)
        if kind == "fixtures"
        else _component_matrix(registry, kind, level)
    )
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if github_output is not None:
        with github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"matrix={encoded}\n")
    return encoded


def check_shared(repo: Path, results_dir: Path) -> Path:
    started = time.monotonic()
    registry = load_registry(repo)
    inventory = validate_registry(repo, registry)
    result = _empty_result(
        repo,
        component_id="shared-contract-and-mutations",
        component_type="shared_contract",
        package_name="metriplane",
        package_version=None,
    )
    python = shlex.quote(sys.executable)
    commands = [
        (
            f"{python} -m pytest -q "
            "tests/adapter_conformance "
            "tests/external_sources "
            "tests/test_atlas_core.py::test_atlas_regression_replays_mutated_state_segment"
        ),
        f"{python} tools/build_external_source_family_matrix.py --validate-only --require-jsonschema",
        f"{python} tools/build_external_source_family_matrix.py --validate-only --require-jsonschema",
        (
            f"{python} -m reuse lint-file .github/workflows/cross-adapter-compatibility.yml "
            "docs/specs/cross-adapter-compatibility-gate-v1.md "
            "docs/specs/cross-adapter-validation-audit-v1.md "
            "tests/adapter_conformance/*.json tests/adapter_conformance/*.py "
            "tests/adapter_conformance/pyproject.toml tests/adapter_conformance/uv.lock "
            "tools/cross_adapter_gate.py tools/cross_adapter_pytest.py"
        ),
    ]
    outputs: list[str] = []
    for command in commands:
        command_result, output = _run_command(
            command,
            cwd=repo,
            env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        )
        result["commands"].append(command_result)
        outputs.append(output)
    if outputs[1] != outputs[2]:
        raise GateError("source-family matrix validation output is not deterministic")
    collected, passed, skipped = _pytest_counts(outputs[0])
    result["tests"] = {
        "collected": collected,
        "passed": passed,
        "skipped": skipped,
        "skip_reasons": [],
    }
    result["source_provenance_identities"] = {
        "registry_sha256": _sha256(repo / REGISTRY_PATH),
        "registry_schema_sha256": _sha256(repo / REGISTRY_SCHEMA_PATH),
        "mutation_catalog_sha256": _sha256(repo / MUTATIONS_PATH),
        "gate_project_sha256": _sha256(repo / GATE_PROJECT_PATH),
        "gate_lock_sha256": _sha256(repo / GATE_LOCK_PATH),
        "registered_adapters": str(inventory["adapter_count"]),
        "registered_fixture_variants": str(inventory["fixture_variant_count"]),
    }
    result["rights_result"] = "pass"
    result["privacy_result"] = "pass"
    result["contract_result"] = "pass"
    result["determinism_result"] = "pass"
    result["negative_tests_result"] = "pass"
    result["final_result"] = "pass"
    result["duration_seconds"] = round(time.monotonic() - started, 6)
    return _write_result(results_dir, result)


def _root_wheel_contents(repo: Path, wheel: Path, registry: Mapping[str, Any]) -> None:
    adapter_modules = {item["module_name"] for item in registry["adapters"]}
    prohibited_dependencies = {
        "mani-skill",
        "maniskill",
        "robomimic",
        "robosuite",
        "mcap",
        "mcap-ros2-support",
        "h5py",
        "huggingface-hub",
        "metriplane-source-adapter-sdk",
    }
    prohibited_suffixes = (".mcap", ".h5", ".hdf5", ".pdf")
    forbidden_digests = _forbidden_referenced_digests(repo, registry)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                raise GateError(f"unsafe root wheel member: {name}")
            if name.startswith("adapters/") or (pure.parts and pure.parts[0] in adapter_modules):
                raise GateError(f"root wheel contains isolated adapter code: {name}")
            if name.lower().endswith(prohibited_suffixes):
                raise GateError(f"root wheel contains source payload: {name}")
            if not name.endswith("/"):
                _scan_distribution_bytes(
                    repo=repo,
                    name=name,
                    data=archive.read(name),
                    forbidden_digests=forbidden_digests,
                )
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8").lower()
        if any(f"requires-dist: {name}" in metadata for name in prohibited_dependencies):
            raise GateError("root wheel gained a source-adapter/runtime framework dependency")


def _venv_program(venv: Path, name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv / directory / f"{name}{suffix}"


def check_root_wheel(repo: Path, results_dir: Path) -> Path:
    started = time.monotonic()
    registry = load_registry(repo)
    validate_registry(repo, registry)
    result = _empty_result(
        repo,
        component_id="root-wheel-clean-room",
        component_type="root_wheel",
        package_name="metriplane",
        package_version=None,
    )
    with tempfile.TemporaryDirectory(prefix="cross-adapter-root-wheel-") as temporary:
        root = Path(temporary)
        source = root / "source"
        shutil.copytree(
            repo,
            source,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "build",
                "dist",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                ".mypy_cache",
            ),
        )
        dist = root / "dist"
        dist.mkdir()
        build_command = (
            f"{shlex.quote(sys.executable)} -m build --wheel "
            f"--outdir {shlex.quote(str(dist))} {shlex.quote(str(source))}"
        )
        command_result, _ = _run_command(build_command, cwd=root)
        result["commands"].append(command_result)
        wheels = sorted(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise GateError(f"expected one root wheel, got {len(wheels)}")
        wheel = wheels[0]
        _root_wheel_contents(repo, wheel, registry)
        result["source_provenance_identities"] = {
            "dependency_lock_sha256": _sha256(repo / "uv.lock"),
            "wheel_sha256": _sha256(wheel),
        }
        venv = root / "venv"
        create = f"{shlex.quote(sys.executable)} -m venv {shlex.quote(str(venv))}"
        command_result, _ = _run_command(create, cwd=root)
        result["commands"].append(command_result)
        python = _venv_program(venv, "python")
        install = f"uv pip install --python {shlex.quote(str(python))} {shlex.quote(str(wheel))}"
        command_result, _ = _run_command(install, cwd=root)
        result["commands"].append(command_result)
        cli = _venv_program(venv, "metriplane")
        input_root = root / "relocated-input"
        run_root = root / "runs"
        variants = fixture_variants(registry)
        for variant in variants:
            relocated = input_root / variant["variant_id"]
            relocated.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(repo / variant["path"], relocated)
            validate_command = (
                f"{shlex.quote(str(cli))} external validate {shlex.quote(str(relocated))} --json"
            )
            command_result, _ = _run_command(
                validate_command,
                cwd=root,
                env={"PYTHONPATH": "", "METRIPLANE_GIT_COMMIT": _commit(repo)},
            )
            result["commands"].append(command_result)
            output = run_root / variant["variant_id"]
            run_command = (
                f"{shlex.quote(str(cli))} external run {shlex.quote(str(relocated))} "
                f"--out {shlex.quote(str(output))} --run-id clean_room_{variant['variant_id'].replace('-', '_')} --json"
            )
            command_result, _ = _run_command(
                run_command,
                cwd=root,
                env={"PYTHONPATH": "", "METRIPLANE_GIT_COMMIT": _commit(repo)},
            )
            result["commands"].append(command_result)
            events = _jsonl(output / "physical_event_log.jsonl")
            deviations = _jsonl(output / "deviations.jsonl")
            incidents = _jsonl(output / "incidents.jsonl")
            frames = _jsonl(output / "state_segment.jsonl")
            expected = variant["expected"]
            actual_events = [
                {"frame_id": item["frame_id"], "ts": item["ts"], "event_type": item["event_type"]}
                for item in events
            ]
            if actual_events != expected["events"]:
                raise GateError(f"installed-wheel event drift for {variant['variant_id']}")
            if (
                len(frames) != expected["frame_count"]
                or len(deviations) != expected["deviation_count"]
                or len(incidents) != expected["incident_count"]
            ):
                raise GateError(f"installed-wheel count drift for {variant['variant_id']}")
            bundles = sorted((output / "evidence_bundles").glob("*.zip"))
            regressions = sorted((output / "regression_tests").glob("*.yaml"))
            bundle_expected = expected["evidence_bundle"] == "produced"
            regression_expected = expected["generated_regression"] == "produced"
            if bool(bundles) != bundle_expected or bool(regressions) != regression_expected:
                raise GateError(f"installed-wheel artifact drift for {variant['variant_id']}")
            for bundle in bundles:
                verify_command = (
                    f"{shlex.quote(str(cli))} atlas bundle verify {shlex.quote(str(bundle))}"
                )
                command_result, _ = _run_command(verify_command, cwd=root, env={"PYTHONPATH": ""})
                result["commands"].append(command_result)
            for regression in regressions:
                regression_command = (
                    f"{shlex.quote(str(cli))} atlas test {shlex.quote(str(regression))} --json"
                )
                command_result, _ = _run_command(
                    regression_command, cwd=root, env={"PYTHONPATH": ""}
                )
                result["commands"].append(command_result)
            result["fixture_variants"].append(variant["variant_id"])
            result["normalized_frame_counts"][variant["variant_id"]] = len(frames)
            result["event_counts"][variant["variant_id"]] = len(events)
            result["deviation_counts"][variant["variant_id"]] = len(deviations)
            result["incident_counts"][variant["variant_id"]] = len(incidents)
            result["incident_bundle_presence"][variant["variant_id"]] = bool(bundles)
            result["bundle_verification"][variant["variant_id"]] = (
                "pass" if bundles else "not_applicable"
            )
            result["regression_presence"][variant["variant_id"]] = bool(regressions)
            result["regression_execution"][variant["variant_id"]] = (
                "pass" if regressions else "not_applicable"
            )
        isolation_program = (
            "import importlib.util,sys; bad="
            + repr(sorted(item["module_name"] for item in registry["adapters"]))
            + "; found=[x for x in bad if importlib.util.find_spec(x)]; "
            + "sys.exit('adapter modules installed: '+repr(found) if found else 0)"
        )
        isolation_command = f"{shlex.quote(str(python))} -c {shlex.quote(isolation_program)}"
        command_result, _ = _run_command(isolation_command, cwd=root, env={"PYTHONPATH": ""})
        result["commands"].append(command_result)
        _scan_private_paths(run_root, checkout=repo)
    result["package_content_result"] = "pass"
    result["rights_result"] = "pass"
    result["privacy_result"] = "pass"
    result["atlas_equivalence"] = "pass"
    result["contract_result"] = "pass"
    result["final_result"] = "pass"
    result["duration_seconds"] = round(time.monotonic() - started, 6)
    return _write_result(results_dir, result)


def _expected_result_keys(registry: Mapping[str, Any], level: str) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for kind in ("sdk", "adapters"):
        matrix = _component_matrix(registry, kind, level)
        for item in matrix["include"]:
            os_name = "linux" if item["os"] == "ubuntu-latest" else "macos"
            keys.add((item["component_id"], os_name, item["python_version"]))
    for item in _fixture_matrix(registry, level)["include"]:
        os_name = "linux" if item["os"] == "ubuntu-latest" else "macos"
        keys.add((item["variant_id"], os_name, item["python_version"]))
    root_environments = [("linux", "3.12")]
    if level == "exhaustive":
        root_environments = [
            ("linux", "3.12"),
            ("linux", "3.13"),
            ("macos", "3.12"),
            ("macos", "3.13"),
        ]
    keys.update(("root-wheel-clean-room", os_name, python) for os_name, python in root_environments)
    keys.add(("shared-contract-and-mutations", "linux", "3.12"))
    return keys


def _needs_level(needs: Mapping[str, Any]) -> str:
    registry = needs.get("registry", {})
    outputs = registry.get("outputs", {}) if isinstance(registry, dict) else {}
    value = outputs.get("level", "pr") if isinstance(outputs, dict) else "pr"
    if value not in {"pr", "exhaustive"}:
        raise GateError(f"summary received invalid validation level: {value!r}")
    return value


def summarize(
    repo: Path,
    results_dir: Path,
    *,
    expected_commit: str,
    needs_json: str,
    summary_markdown: Path | None,
) -> dict[str, Any]:
    if _SHA40.fullmatch(expected_commit) is None:
        raise GateError("summary expected commit must be a full SHA")
    try:
        needs = json.loads(needs_json)
    except json.JSONDecodeError as exc:
        raise GateError(f"invalid needs JSON: {exc}") from exc
    if not isinstance(needs, dict):
        raise GateError("needs JSON must be an object")
    if set(needs) != _REQUIRED_JOB_IDS:
        raise GateError(
            f"required job set mismatch: missing={sorted(_REQUIRED_JOB_IDS - set(needs))}, "
            f"unexpected={sorted(set(needs) - _REQUIRED_JOB_IDS)}"
        )
    bad_needs: dict[str, Any] = {}
    for key, value in needs.items():
        if not isinstance(value, dict):
            bad_needs[key] = "malformed"
        elif value.get("result") != "success":
            bad_needs[key] = value.get("result", "missing")
    if bad_needs:
        raise GateError(f"required jobs did not succeed: {bad_needs}")
    registry = load_registry(repo)
    validate_registry(repo, registry)
    level = _needs_level(needs)
    expected_keys = _expected_result_keys(registry, level)
    if not results_dir.is_dir():
        raise GateError(f"machine result directory is missing: {results_dir}")
    paths = sorted(results_dir.rglob("*.json"))
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in paths:
        value = _load_json(path)
        if not isinstance(value, dict):
            raise GateError(f"result record is not an object: {path}")
        _validate_result_shape(value)
        _validate_result_semantics(repo, value)
        if value["repository_commit"] != expected_commit:
            raise GateError(f"stale result commit in {path.name}: {value['repository_commit']}")
        if value["final_result"] != "pass":
            raise GateError(f"failed result record: {path.name}")
        if value["level"] != level:
            raise GateError(f"result level mismatch in {path.name}")
        python = ".".join(value["python_version"].split(".")[:2])
        key = (value["component_id"], value["operating_system"], python)
        if key in seen:
            raise GateError(f"duplicate machine result for {key}")
        seen.add(key)
        records.append(value)
    if seen != expected_keys:
        raise GateError(
            f"machine result set mismatch: missing={sorted(expected_keys - seen)}, "
            f"unexpected={sorted(seen - expected_keys)}"
        )
    expected_adapters = {item["component_id"] for item in registry["adapters"]}
    executed_adapters = {
        item["component_id"] for item in records if item["component_type"] == "source_adapter"
    }
    if executed_adapters != expected_adapters:
        raise GateError("executed adapter count does not match registry count")
    expected_variants = {item["variant_id"] for item in fixture_variants(registry)}
    executed_variants = {
        variant
        for item in records
        if item["component_type"] == "portable_fixture"
        for variant in item["fixture_variants"]
    }
    if executed_variants != expected_variants:
        raise GateError("not every registered fixture variant produced a result record")
    total_duration = round(sum(float(item["duration_seconds"]) for item in records), 3)
    summary = {
        "schema_version": "metriplane.cross_adapter_summary.v1",
        "repository_commit": expected_commit,
        "level": level,
        "record_count": len(records),
        "adapter_count": len(executed_adapters),
        "fixture_variant_count": len(executed_variants),
        "total_recorded_duration_seconds": total_duration,
        "result": "pass",
    }
    if summary_markdown is not None:
        rows = [
            "## Cross-adapter compatibility gate",
            "",
            f"Commit: `{expected_commit}` · level: `{level}` · records: {len(records)}",
            "",
            "| Component | Package | Source conversion | Contract | Atlas | Determinism | Negative tests | Packaging | Rights | Result |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for item in sorted(
            records,
            key=lambda value: (
                value["component_type"],
                value["component_id"],
                value["operating_system"],
                value["python_version"],
            ),
        ):
            rows.append(
                f"| `{item['component_id']}` ({item['operating_system']}, "
                f"py{item['python_version']}) | {item['package_name'] or 'N/A'} | "
                f"{item['conversion_equivalence']} | {item['contract_result']} | "
                f"{item['atlas_equivalence']} | {item['determinism_result']} | "
                f"{item['negative_tests_result']} | {item['package_content_result']} | "
                f"{item['rights_result']} | **{item['final_result']}** |"
            )
        summary_markdown.parent.mkdir(parents=True, exist_ok=True)
        with summary_markdown.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")
    return summary


def propose_baseline_update(repo: Path, variant_id: str, output: Path) -> Path:
    """Write a review candidate without modifying registry or existing files."""

    if output.exists():
        raise GateError(f"baseline candidate destination already exists: {output}")
    registry = load_registry(repo)
    validate_registry(repo, registry)
    variants = {item["variant_id"]: item for item in fixture_variants(registry)}
    if variant_id not in variants:
        raise GateError(f"unknown fixture variant: {variant_id}")
    variant = variants[variant_id]
    from metriplane.external_sources.execution import run_external_fixture

    with tempfile.TemporaryDirectory(prefix="cross-adapter-baseline-candidate-") as temporary:
        run_root = Path(temporary) / "run"
        summary = run_external_fixture(
            repo / variant["path"],
            run_root,
            run_id=f"baseline_candidate_{variant_id.replace('-', '_')}",
        )
        if not summary.passed:
            raise GateError(f"candidate fixture run failed: {summary.errors}")
        events = _jsonl(run_root / "physical_event_log.jsonl")
        incidents = _jsonl(run_root / "incidents.jsonl")
        candidate = {
            "variant_id": variant_id,
            "review_required": True,
            "observed_commit": _commit(repo),
            "observed": {
                "frame_count": summary.frame_count,
                "events": [
                    {
                        "frame_id": item["frame_id"],
                        "ts": item["ts"],
                        "event_type": item["event_type"],
                    }
                    for item in events
                ],
                "deviation_count": summary.deviation_count,
                "incident_count": summary.incident_count,
                "incident_types": [item["incident_type"] for item in incidents],
                "bundle_count": len(summary.evidence_bundles),
                "regression_count": len(summary.generated_regressions),
            },
            "registered": variant["expected"],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(candidate))
    return output


def check_all(repo: Path, *, level: str, results_dir: Path) -> list[Path]:
    if results_dir.exists() and any(results_dir.iterdir()):
        raise GateError(f"top-level results directory must be empty: {results_dir}")
    results_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CROSS_ADAPTER_LEVEL"] = level
    registry = load_registry(repo)
    validate_registry(repo, registry)
    outputs: list[Path] = []
    outputs.append(check_shared(repo, results_dir / "shared"))
    for component in [*registry["shared_infrastructure"], *registry["adapters"]]:
        outputs.append(
            check_component(
                repo, component["component_id"], results_dir / component["component_id"]
            )
        )
    repetitions = 3 if level == "pr" else 5
    for variant in fixture_variants(registry):
        outputs.append(
            check_fixture(
                repo,
                variant["variant_id"],
                results_dir / variant["variant_id"],
                repetitions=repetitions,
            )
        )
    outputs.append(check_root_wheel(repo, results_dir / "root-wheel"))
    if level == "pr":
        summarize(
            repo,
            results_dir,
            expected_commit=_commit(repo),
            needs_json=_successful_needs_json(level),
            summary_markdown=None,
        )
    return outputs


def _successful_needs_json(level: str) -> str:
    needs: dict[str, dict[str, Any]] = {job: {"result": "success"} for job in _REQUIRED_JOB_IDS}
    needs["registry"]["outputs"] = {"level": level}
    return json.dumps(needs, separators=(",", ":"), sort_keys=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fail-closed Metriplane cross-adapter compatibility gate."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-registry")
    validate.add_argument("--require-jsonschema", action="store_true")

    matrix = commands.add_parser("matrix")
    matrix.add_argument("--kind", choices=("sdk", "adapters", "fixtures"), required=True)
    matrix.add_argument("--level", choices=("pr", "exhaustive"), required=True)
    matrix.add_argument("--github-output", type=Path)

    component = commands.add_parser("check-component")
    component.add_argument("--component-id", required=True)
    component.add_argument("--results-dir", type=Path, required=True)

    fixture = commands.add_parser("check-fixture")
    fixture.add_argument("--variant-id", required=True)
    fixture.add_argument("--results-dir", type=Path, required=True)
    fixture.add_argument("--repetitions", type=int, default=3)

    shared = commands.add_parser("check-shared")
    shared.add_argument("--results-dir", type=Path, required=True)

    wheel = commands.add_parser("check-root-wheel")
    wheel.add_argument("--results-dir", type=Path, required=True)

    summary = commands.add_parser("summarize")
    summary.add_argument("--results-dir", type=Path, required=True)
    summary.add_argument("--expected-commit", required=True)
    summary.add_argument(
        "--needs-json",
        default=_successful_needs_json("pr"),
        help="GitHub needs context; defaults to a complete local PR-level success set",
    )
    summary.add_argument("--summary-markdown", type=Path)

    check = commands.add_parser("check")
    check.add_argument("--level", choices=("pr", "exhaustive"), required=True)
    check.add_argument("--results-dir", type=Path, required=True)

    propose = commands.add_parser("propose-baseline-update")
    propose.add_argument("--variant-id", required=True)
    propose.add_argument("--out", type=Path, required=True)
    return parser


def _write_failed_command_result(repo: Path, args: argparse.Namespace) -> None:
    results_dir = getattr(args, "results_dir", None)
    if not isinstance(results_dir, Path) or (results_dir.exists() and any(results_dir.iterdir())):
        return
    command = str(getattr(args, "command", "gate"))
    component_id = {
        "check-component": str(getattr(args, "component_id", "unknown-component")),
        "check-fixture": str(getattr(args, "variant_id", "unknown-fixture")),
        "check-shared": "shared-contract-and-mutations",
        "check-root-wheel": "root-wheel-clean-room",
    }.get(command)
    component_type = {
        "check-component": "source_adapter",
        "check-fixture": "portable_fixture",
        "check-shared": "shared_contract",
        "check-root-wheel": "root_wheel",
    }.get(command)
    if component_id is None or component_type is None:
        return
    if command == "check-component" and component_id == "source-adapter-sdk":
        component_type = "shared_infrastructure"
    result = _empty_result(
        repo,
        component_id=component_id,
        component_type=component_type,
    )
    result["source_provenance_identities"] = {"failure_category": "gate_error"}
    _write_result(results_dir, result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    repo = repository_root()
    try:
        if args.command == "validate-registry":
            value = validate_registry(
                repo,
                load_registry(repo),
                require_jsonschema=bool(args.require_jsonschema),
            )
            print(json.dumps({"pass": True, **value}, sort_keys=True))
            return 0
        if args.command == "matrix":
            print(
                emit_matrix(
                    repo,
                    kind=args.kind,
                    level=args.level,
                    github_output=args.github_output,
                )
            )
            return 0
        if args.command == "check-component":
            print(check_component(repo, args.component_id, args.results_dir))
            return 0
        if args.command == "check-fixture":
            print(
                check_fixture(
                    repo,
                    args.variant_id,
                    args.results_dir,
                    repetitions=args.repetitions,
                )
            )
            return 0
        if args.command == "check-shared":
            print(check_shared(repo, args.results_dir))
            return 0
        if args.command == "check-root-wheel":
            print(check_root_wheel(repo, args.results_dir))
            return 0
        if args.command == "summarize":
            value = summarize(
                repo,
                args.results_dir,
                expected_commit=args.expected_commit,
                needs_json=args.needs_json,
                summary_markdown=args.summary_markdown,
            )
            print(json.dumps(value, sort_keys=True))
            return 0
        if args.command == "check":
            paths = check_all(repo, level=args.level, results_dir=args.results_dir)
            print(json.dumps({"pass": True, "results": [str(path) for path in paths]}))
            return 0
        if args.command == "propose-baseline-update":
            print(propose_baseline_update(repo, args.variant_id, args.out))
            return 0
        raise GateError(f"unsupported command: {args.command}")
    except GateError as exc:
        _write_failed_command_result(repo, args)
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
