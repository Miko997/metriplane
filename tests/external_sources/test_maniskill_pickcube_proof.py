# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import pytest
import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROOF_ROOT = REPOSITORY_ROOT / "proofs" / "maniskill-pickcube-v1"
ARTIFACT_ROOT = PROOF_ROOT / "artifacts"
FIXTURE_ROOT = REPOSITORY_ROOT / "examples" / "external_sources" / "maniskill_pickcube"
INCIDENT_FIXTURE = FIXTURE_ROOT / "incident"
CONTROL_FIXTURE = FIXTURE_ROOT / "control"
SCHEMA_PATH = PROOF_ROOT / "proof-record.schema.json"
RECORD_PATH = PROOF_ROOT / "proof-record.json"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "maniskill-proof.yml"

PROOF_TAG = "maniskill-pickcube-proof-v1"
BASELINE_COMMIT = "1549d0a05e03db51efc0ee08edb7d9db66196b4e"
ADAPTER_COMMIT = "95d1134d9fb9273318c552c507952f1c5c26877e"
CONVERSION_COMMIT = "a4a4f9272ad64b1564035874b605ceb687b63ed8"
GENERATION_COMMIT = "652ad9353c0223507a938f0e8d990dd6f1c771ad"
DATASET_REVISION = "d674485bbffdd533914e52d272fdda34c0515608"
SHARED_SESSION_SHA256 = "7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df"
MAPPING_SHA256 = "9127535a2e8eb3091aeac82f335e001f81c3a9e5098272881f7969c6eeecbee7"
CONTRACT_SCHEMA_SHA256 = "b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4"
FIXTURE_FINGERPRINTS = {
    "incident": "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2",
    "control": "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e",
}
FIXTURE_IDS = {
    "incident": "maniskill-pickcube-episode-0-planar-incident-v1",
    "control": "maniskill-pickcube-episode-0-planar-control-v1",
}
EXPECTED_COUNTS = {
    "incident": {
        "frame_count": 75,
        "event_count": 4,
        "deviation_count": 1,
        "incident_count": 1,
    },
    "control": {
        "frame_count": 75,
        "event_count": 3,
        "deviation_count": 0,
        "incident_count": 0,
    },
}
TARGET_POLYGON = [
    [0.016815734803676603, -0.01198131799697876],
    [0.03681573480367661, -0.01198131799697876],
    [0.03681573480367661, 0.00801868200302124],
    [0.016815734803676603, 0.00801868200302124],
]

REQUIRED_PROOF_FILES = {
    "README.md",
    "proof-record.json",
    "proof-record.schema.json",
    "REPRODUCE.md",
    "CLAIMS.md",
    "READINESS.md",
    "NOTICE.md",
    "EVALUATOR.md",
    "evaluator-report-template.md",
    "CITATION.cff",
    "SHA256SUMS",
    "reproduce.py",
    "artifacts/incident-validation.json",
    "artifacts/control-validation.json",
    "artifacts/incident-run-summary.json",
    "artifacts/control-run-summary.json",
    "artifacts/incident-evidence.zip",
    "artifacts/incident-regression.yaml",
    "artifacts/incident-regression-result.json",
    "artifacts/equivalence-summary.json",
    "artifacts/environment-matrix.json",
}
REPRESENTATIVE_ARTIFACTS = {item for item in REQUIRED_PROOF_FILES if item.startswith("artifacts/")}
FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PRIVATE_PATH = re.compile(
    rb"(?:/(?:home|Users|workspace)/[^/\s\"'<>]+(?:/|(?=[\s\"'<>]|$))|"
    rb"/private/tmp/[A-Za-z0-9._/-]+|/var/folders/[A-Za-z0-9._/-]+|"
    rb"(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/])"
)
RAW_SOURCE_SUFFIXES = {
    ".glb",
    ".h5",
    ".hdf5",
    ".mp4",
    ".mov",
    ".obj",
    ".pt",
    ".pth",
    ".png",
    ".safetensors",
    ".urdf",
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    assert isinstance(value, dict), path
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(isinstance(row, dict) for row in rows), path
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_pointer(root: Mapping[str, Any], pointer: str) -> Any:
    assert pointer.startswith("#/"), pointer
    value: Any = root
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        assert isinstance(value, Mapping), pointer
        value = value[part]
    return value


def _instance_matches_type(instance: object, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    raise AssertionError(f"unsupported JSON Schema type in proof schema: {expected}")


def _validate_schema_subset(
    instance: Any,
    schema: Any,
    root_schema: Mapping[str, Any],
    *,
    location: str = "$",
) -> list[str]:
    """Validate the closed proof schema without adding a runtime dependency.

    CI also runs the official Draft 2020-12 implementation. This local validator
    intentionally supports every keyword used by the checked-in proof schema so
    the ordinary locked test environment still rejects a malformed record.
    """

    if schema is True:
        return []
    if schema is False:
        return [f"{location}: schema is false"]
    assert isinstance(schema, Mapping), (location, schema)
    if "$ref" in schema:
        target = _json_pointer(root_schema, str(schema["$ref"]))
        return _validate_schema_subset(instance, target, root_schema, location=location)

    errors: list[str] = []
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        branches = schema[keyword]
        assert isinstance(branches, list)
        results = [
            _validate_schema_subset(instance, branch, root_schema, location=location)
            for branch in branches
        ]
        matches = sum(not result for result in results)
        if keyword == "allOf":
            errors.extend(item for result in results for item in result)
        elif keyword == "anyOf" and matches == 0:
            errors.append(f"{location}: did not match anyOf")
        elif keyword == "oneOf" and matches != 1:
            errors.append(f"{location}: matched {matches} oneOf branches")
    if errors:
        return errors

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{location}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{location}: {instance!r} is not in enum")
    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]
    if isinstance(expected_types, list) and not any(
        _instance_matches_type(instance, str(expected)) for expected in expected_types
    ):
        errors.append(f"{location}: expected type {expected_types}, got {type(instance).__name__}")
        return errors

    if isinstance(instance, dict):
        required = schema.get("required", [])
        assert isinstance(required, list)
        for key in required:
            if key not in instance:
                errors.append(f"{location}: missing required property {key!r}")
        properties = schema.get("properties", {})
        assert isinstance(properties, Mapping)
        for key, value in instance.items():
            child_location = f"{location}.{key}"
            if key in properties:
                errors.extend(
                    _validate_schema_subset(
                        value,
                        properties[key],
                        root_schema,
                        location=child_location,
                    )
                )
            elif schema.get("additionalProperties") is False:
                errors.append(f"{location}: unknown property {key!r}")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                errors.extend(
                    _validate_schema_subset(
                        value,
                        schema["additionalProperties"],
                        root_schema,
                        location=child_location,
                    )
                )

    if isinstance(instance, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(instance) < minimum:
            errors.append(f"{location}: fewer than {minimum} items")
        if isinstance(maximum, int) and len(instance) > maximum:
            errors.append(f"{location}: more than {maximum} items")
        if schema.get("uniqueItems") is True:
            canonical = [json.dumps(item, sort_keys=True) for item in instance]
            if len(canonical) != len(set(canonical)):
                errors.append(f"{location}: items are not unique")
        prefix_items = schema.get("prefixItems", [])
        assert isinstance(prefix_items, list)
        for index, child_schema in enumerate(prefix_items):
            if index < len(instance):
                errors.extend(
                    _validate_schema_subset(
                        instance[index],
                        child_schema,
                        root_schema,
                        location=f"{location}[{index}]",
                    )
                )
        items = schema.get("items")
        if items is not None:
            for index in range(len(prefix_items), len(instance)):
                errors.extend(
                    _validate_schema_subset(
                        instance[index],
                        items,
                        root_schema,
                        location=f"{location}[{index}]",
                    )
                )

    if isinstance(instance, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(instance) < minimum:
            errors.append(f"{location}: shorter than {minimum}")
        if isinstance(maximum, int) and len(instance) > maximum:
            errors.append(f"{location}: longer than {maximum}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            errors.append(f"{location}: does not match {pattern!r}")
        if schema.get("format") == "date":
            try:
                date.fromisoformat(instance)
            except ValueError:
                errors.append(f"{location}: invalid RFC 3339 full-date")
        if schema.get("format") == "uri":
            parsed = urlparse(instance)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{location}: invalid absolute HTTP(S) URI")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and instance < minimum:
            errors.append(f"{location}: below minimum {minimum}")
        if isinstance(maximum, (int, float)) and instance > maximum:
            errors.append(f"{location}: above maximum {maximum}")
    return errors


def _walk_schema_objects(schema: object, location: str = "$schema") -> Iterable[str]:
    if isinstance(schema, dict):
        if (schema.get("type") == "object" or "properties" in schema) and schema.get(
            "additionalProperties"
        ) is not False:
            yield location
        for key, value in schema.items():
            yield from _walk_schema_objects(value, f"{location}.{key}")
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            yield from _walk_schema_objects(value, f"{location}[{index}]")


def _parse_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines, path
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (\S(?:.*\S)?)", line)
        assert match is not None, f"invalid SHA256SUMS line: {line!r}"
        digest, relative = match.groups()
        assert relative not in values, f"duplicate SHA256SUMS path: {relative}"
        pure = PurePosixPath(relative)
        assert not pure.is_absolute() and ".." not in pure.parts, relative
        assert "\\" not in relative, relative
        values[relative] = digest
    assert list(values) == sorted(values), "SHA256SUMS must be byte-order sorted by path"
    return values


def _artifact_map(record: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = record["artifacts"]
    assert isinstance(artifacts, list)
    values: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        assert isinstance(item, Mapping)
        path = item["path"]
        assert isinstance(path, str)
        assert path not in values, path
        values[path] = item
    return values


def _assert_safe_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist()]
        assert names == sorted(names), "representative evidence ZIP inventory must be sorted"
        for info in archive.infolist():
            pure = PurePosixPath(info.filename)
            assert not pure.is_absolute() and ".." not in pure.parts, info.filename
            assert "\\" not in info.filename, info.filename
            assert pure.suffix.lower() not in RAW_SOURCE_SUFFIXES, info.filename
            if not info.is_dir():
                assert PRIVATE_PATH.search(archive.read(info)) is None, info.filename


def test_proof_structure_is_complete_and_contains_no_generated_cache() -> None:
    actual = {
        path.relative_to(PROOF_ROOT).as_posix() for path in PROOF_ROOT.rglob("*") if path.is_file()
    }
    assert REQUIRED_PROOF_FILES <= actual
    assert not any("__pycache__" in PurePosixPath(path).parts for path in actual)
    assert not any(path.endswith((".pyc", ".pyo")) for path in actual)
    assert not any(path.is_symlink() for path in PROOF_ROOT.rglob("*"))
    assert (REPOSITORY_ROOT / "tools" / "build_maniskill_pickcube_proof.py").is_file()
    assert WORKFLOW_PATH.is_file()


def test_readme_has_the_required_public_landing_page_order() -> None:
    text = (PROOF_ROOT / "README.md").read_text(encoding="utf-8").lower()
    headings = [
        "what this is",
        "exact bounded claim",
        "source-to-result flow",
        "exact source identity",
        "episode and state accounting",
        "trust-layer table",
        "position-only normalization",
        "incident/control comparison",
        "published result summary",
        "fast portable reproduction",
        "full source conversion reproduction",
        "artifact and checksum table",
        "rights and attribution",
        "allowed claims",
        "unsupported claims",
        "current readiness decision",
        "canonical citation",
        "stable tagged url",
    ]
    positions = [text.index(value) for value in headings]
    assert positions == sorted(positions)
    assert "pinned maniskill hdf5 + json" in text
    assert "isolated maniskill adapter" in text
    assert "position-only portable fixture" in text
    assert "evidence verification + regression" in text


def test_proof_record_schema_is_closed_draft_2020_12_and_tag_stable() -> None:
    schema = _read_json(SCHEMA_PATH)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert f"/{PROOF_TAG}/proofs/maniskill-pickcube-v1/" in schema["$id"]
    assert "/main/" not in schema["$id"]
    assert list(_walk_schema_objects(schema)) == []


def test_proof_record_validates_and_unknown_fields_are_rejected() -> None:
    schema = _read_json(SCHEMA_PATH)
    record = _read_json(RECORD_PATH)
    errors = _validate_schema_subset(record, schema, schema)
    assert errors == []

    mutated = copy.deepcopy(record)
    mutated["unexpected_publication_field"] = True
    errors = _validate_schema_subset(mutated, schema, schema)
    assert any("unknown property" in error for error in errors)

    nested = copy.deepcopy(record)
    nested["proof_identity"]["unexpected_identity_field"] = True
    errors = _validate_schema_subset(nested, schema, schema)
    assert any("unknown property" in error for error in errors)


def test_proof_record_identity_and_candidate_publication_boundary() -> None:
    record = _read_json(RECORD_PATH)
    identity = record["proof_identity"]
    assert identity == {
        "proof_id": "maniskill-pickcube-v1",
        "proof_version": 1,
        "status": "candidate",
        "publication_date": "2026-08-12",
        "canonical_repository": "https://github.com/Miko997/metriplane",
        "canonical_tag": PROOF_TAG,
        "canonical_commit": None,
        "implementation_merge_commit": BASELINE_COMMIT,
        "candidate_commit": record["contract"]["metriplane_git_commit"],
        "proof_publication_commit": None,
        "proof_landing_page_path": "proofs/maniskill-pickcube-v1/README.md",
        "proposed_canonical_url": (
            f"https://github.com/Miko997/metriplane/tree/{PROOF_TAG}/proofs/maniskill-pickcube-v1"
        ),
        "canonical_url": None,
    }
    assert FULL_COMMIT.fullmatch(identity["candidate_commit"])


def test_fixture_identity_source_and_frozen_rules_match_the_record() -> None:
    record = _read_json(RECORD_PATH)
    fixtures = record["fixtures"]
    assert fixtures["shared_session_sha256"] == SHARED_SESSION_SHA256
    assert fixtures["mapping_sha256"] == MAPPING_SHA256
    assert record["adapter"]["commit"] == ADAPTER_COMMIT
    assert record["contract"]["contract_schema_sha256"] == CONTRACT_SCHEMA_SHA256
    assert record["source"]["dataset_revision"] == DATASET_REVISION
    assert record["source"]["conversion_commit"] == CONVERSION_COMMIT
    assert record["source"]["source_generation_commit"] == GENERATION_COMMIT
    assert record["source"]["episode_id"] == 0
    assert record["source"]["hdf5_group"] == "traj_0"
    assert record["source"]["transition_count"] == 74
    assert record["source"]["stored_state_count"] == 75
    assert record["source"]["rl_horizon"] == 50
    assert record["normalization"]["object_ids"] == ["cube_1", "robot_tcp_1"]
    assert record["operator_rules"]["target_polygon"] == TARGET_POLYGON
    assert record["operator_rules"]["incident_wait_s"] == 0.2
    assert record["operator_rules"]["control_wait_s"] == 0.3

    assert (INCIDENT_FIXTURE / "session.jsonl").read_bytes() == (
        CONTROL_FIXTURE / "session.jsonl"
    ).read_bytes()
    assert _sha256(INCIDENT_FIXTURE / "session.jsonl") == SHARED_SESSION_SHA256
    assert (INCIDENT_FIXTURE / "entity-mapping.json").read_bytes() == (
        CONTROL_FIXTURE / "entity-mapping.json"
    ).read_bytes()
    assert _sha256(INCIDENT_FIXTURE / "entity-mapping.json") == MAPPING_SHA256

    expected_inventory: set[str] | None = None
    for variant, root in (("incident", INCIDENT_FIXTURE), ("control", CONTROL_FIXTURE)):
        manifest = _read_json(root / "source-manifest.json")
        fixture_record = fixtures[variant]
        assert manifest["adapter"]["commit"] == ADAPTER_COMMIT
        assert manifest["selection"]["episode_id"] == "0"
        session = manifest["normalized_artifacts"]["session"]
        assert session["frame_count"] == 75
        assert session["frame_state_model_version"] == "1.0"
        assert session["media_type"] == "application/x-ndjson"
        assert session["path"] == "session.jsonl"
        assert session["sha256"] == SHARED_SESSION_SHA256
        assert fixture_record["fixture_id"] == FIXTURE_IDS[variant]
        assert fixture_record["manifest_sha256"] == _sha256(root / "source-manifest.json")
        assert fixture_record["fingerprint_sha256"] == FIXTURE_FINGERPRINTS[variant]
        assert _sha256(root / "CHECKSUMS.sha256") == FIXTURE_FINGERPRINTS[variant]
        actual_files = sorted(
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        )
        assert fixture_record["inventory_count"] == len(actual_files) == 14
        if expected_inventory is None:
            expected_inventory = set(actual_files)
        else:
            assert set(actual_files) == expected_inventory
        rows = _read_jsonl(root / "session.jsonl")
        assert len(rows) == 75
        assert [row["frame_id"] for row in rows] == list(range(75))

    assert expected_inventory is not None
    assert set(fixtures["exact_inventory"]) == expected_inventory


def test_source_artifact_identities_agree_with_both_fixture_manifests() -> None:
    record = _read_json(RECORD_PATH)
    source_artifacts = {item["artifact_id"]: item for item in record["source"]["artifacts"]}
    assert set(source_artifacts) == {
        "pickcube_archive",
        "pickcube_trajectory_hdf5",
        "pickcube_trajectory_metadata",
    }
    for root in (INCIDENT_FIXTURE, CONTROL_FIXTURE):
        manifest = _read_json(root / "source-manifest.json")
        declared = {item["artifact_id"]: item for item in manifest["source_artifacts"]}
        assert set(declared) == set(source_artifacts)
        for artifact_id, expected in source_artifacts.items():
            observed = declared[artifact_id]
            assert observed["sha256"] == expected["sha256"]
            assert (
                manifest["extensions"]["org.maniskill.pick_cube"]["source_byte_sizes"][artifact_id]
                == expected["bytes"]
            )
            assert "path" not in observed
            assert observed["presence"] == "referenced"
            assert observed["uri"].endswith(expected["path"])


def test_representative_results_match_record_counts_and_honest_control() -> None:
    record = _read_json(RECORD_PATH)
    incident_validation = _read_json(ARTIFACT_ROOT / "incident-validation.json")
    control_validation = _read_json(ARTIFACT_ROOT / "control-validation.json")
    assert incident_validation["pass"] is True
    assert control_validation["pass"] is True
    assert incident_validation["frame_count"] == control_validation["frame_count"] == 75
    assert incident_validation["session_sha256"] == SHARED_SESSION_SHA256
    assert control_validation["session_sha256"] == SHARED_SESSION_SHA256

    for variant in ("incident", "control"):
        summary = _read_json(ARTIFACT_ROOT / f"{variant}-run-summary.json")
        expected = EXPECTED_COUNTS[variant]
        assert summary["pass"] is True
        assert {key: summary[key] for key in expected} == expected
        assert record["results"][f"{variant}_run"]["counts"] == expected

    assert record["results"]["incident_run"] == {
        **record["results"]["incident_run"],
        "bundle_verified": True,
        "regression_passed": True,
        "bundle_count": 1,
        "regression_count": 1,
    }
    assert record["results"]["control_run"] == {
        **record["results"]["control_run"],
        "bundle_verified": False,
        "regression_passed": False,
        "bundle_count": 0,
        "regression_count": 0,
    }
    assert not (ARTIFACT_ROOT / "control-evidence.zip").exists()
    assert not (ARTIFACT_ROOT / "control-regression.yaml").exists()


def test_representative_evidence_and_regression_execute_after_move(
    tmp_path: Path,
) -> None:
    bundle = ARTIFACT_ROOT / "incident-evidence.zip"
    regression = ARTIFACT_ROOT / "incident-regression.yaml"
    assert verify_bundle(bundle)["pass"] is True
    assert run_regression(regression)["pass"] is True
    recorded = _read_json(ARTIFACT_ROOT / "incident-regression-result.json")
    assert recorded["pass"] is True

    moved = tmp_path / "moved-proof-artifacts"
    moved.mkdir()
    moved_bundle = moved / bundle.name
    moved_regression = moved / regression.name
    moved_bundle.write_bytes(bundle.read_bytes())
    moved_regression.write_bytes(regression.read_bytes())
    assert verify_bundle(moved_bundle)["pass"] is True
    assert run_regression(moved_regression)["pass"] is True


def test_equivalence_and_environment_matrix_have_required_jobs() -> None:
    record = _read_json(RECORD_PATH)
    equivalence = _read_json(ARTIFACT_ROOT / "equivalence-summary.json")
    assert equivalence["conversion"]["equivalent"] is True
    assert equivalence["conversion"]["compared_artifact_count"] == 28
    assert len(equivalence["conversion"]["run_ids"]) == 3
    for variant in ("incident", "control"):
        assert equivalence["evaluation"][variant]["equivalent"] is True
        assert equivalence["evaluation"][variant]["run_count"] == 3

    matrix = _read_json(ARTIFACT_ROOT / "environment-matrix.json")
    evidence_run_id = 31576927627
    evidence_run_url = "https://github.com/Miko997/metriplane/actions/runs/31576927627"
    assert matrix["complete"] is True
    assert matrix["evidence_head_commit"] == ("488ef555732012b302db6795ba5796b8fa8e7f10")
    assert FULL_COMMIT.fullmatch(matrix["evidence_head_commit"])
    assert type(matrix["evidence_workflow_run_id"]) is int
    assert matrix["evidence_workflow_run_id"] == evidence_run_id
    assert matrix["evidence_workflow_run_url"] == evidence_run_url

    jobs = matrix["jobs"]
    identities = {(job["operating_system"], job["python_version"]): job for job in jobs}
    expected_environments = {
        ("Ubuntu", "3.12"): {
            "architecture": "x86_64",
            "operating_system_version": "24.04.4",
            "python_patch_version": "3.12.13",
            "runner_image": "ubuntu-24.04",
            "runner_image_version": "20260810.271.1",
        },
        ("Ubuntu", "3.13"): {
            "architecture": "x86_64",
            "operating_system_version": "24.04.4",
            "python_patch_version": "3.13.15",
            "runner_image": "ubuntu-24.04",
            "runner_image_version": "20260810.271.1",
        },
        ("macOS", "3.12"): {
            "architecture": "arm64",
            "operating_system_version": "26.5.2",
            "python_patch_version": "3.12.10",
            "runner_image": "macos-26-arm64",
            "runner_image_version": "20260728.0273.1",
        },
        ("macOS", "3.13"): {
            "architecture": "arm64",
            "operating_system_version": "26.5.2",
            "python_patch_version": "3.13.14",
            "runner_image": "macos-26-arm64",
            "runner_image_version": "20260728.0273.1",
        },
    }
    assert set(identities) == set(expected_environments)
    for job in jobs:
        identity = (job["operating_system"], job["python_version"])
        for field, expected in expected_environments[identity].items():
            assert job[field] == expected
        assert job["level"] == "portable_fixture_evaluation"
        assert job["simulator_dependencies"] == []
        assert job["status"] == "pass"
        assert type(job["github_job_id"]) is int
        assert job["github_job_id"] > 0
        assert job["workflow_url"] == (f"{evidence_run_url}/job/{job['github_job_id']}")
        assert SHA256.fullmatch(job["reproduction_result_sha256"])
    matrix_record = record["results"]["environment_matrix"]
    assert matrix_record["path"] == "artifacts/environment-matrix.json"
    assert matrix_record["required_jobs"] == 4
    assert matrix_record["complete"] is True


def test_sha256sum_inventory_and_proof_record_artifact_hashes() -> None:
    record = _read_json(RECORD_PATH)
    checksums = _parse_checksums(PROOF_ROOT / "SHA256SUMS")
    actual = {
        path.relative_to(PROOF_ROOT).as_posix()
        for path in PROOF_ROOT.rglob("*")
        if path.is_file()
        and path.name != "SHA256SUMS"
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    assert set(checksums) == actual
    for relative, expected in checksums.items():
        assert _sha256(PROOF_ROOT / relative) == expected, relative

    artifacts = _artifact_map(record)
    assert set(artifacts) == REPRESENTATIVE_ARTIFACTS | {"proof-record.schema.json"}
    for relative, item in artifacts.items():
        path = PROOF_ROOT / relative
        assert path.is_file(), relative
        assert item["sha256"] == _sha256(path)
        assert item["sha256"] == checksums[relative]
        assert item["media_type"]
        assert item["purpose"]
        assert item["license_classification"]


def test_publication_files_and_artifacts_contain_no_machine_local_path() -> None:
    for relative in sorted(REPRESENTATIVE_ARTIFACTS | {"proof-record.json"}):
        path = PROOF_ROOT / relative
        raw = path.read_bytes()
        assert PRIVATE_PATH.search(raw) is None, relative
        assert b"/tmp/" not in raw, relative
        if path.suffix == ".zip":
            _assert_safe_archive(path)


def test_raw_source_assets_are_absent_and_evidence_is_the_only_zip() -> None:
    for path in PROOF_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PROOF_ROOT).as_posix()
        assert path.suffix.lower() not in RAW_SOURCE_SUFFIXES, relative
        if path.suffix.lower() == ".zip":
            assert relative == "artifacts/incident-evidence.zip"
            _assert_safe_archive(path)
    lower_names = {path.name.lower() for path in PROOF_ROOT.rglob("*") if path.is_file()}
    assert "trajectory.h5" not in lower_names
    assert "trajectory.json" not in lower_names
    assert "pickcube-v1.zip" not in lower_names


def test_claim_and_source_neutral_wording_red_team() -> None:
    public_text = "\n".join(
        (PROOF_ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "REPRODUCE.md", "NOTICE.md", "EVALUATOR.md")
    ).lower()
    marketing = (
        "groundbreaking",
        "production-grade",
        "validated by maniskill",
        "universal compatibility",
        "industry-ready",
        "state of the art",
        "official integration",
    )
    assert all(term not in public_text for term in marketing)
    assert "owner-generated public technical proof" in public_text
    assert "independent reproduction" in public_text
    assert "not independent" in public_text or "does not" in public_text

    artifact_bytes = b"\n".join(
        (PROOF_ROOT / relative).read_bytes()
        for relative in sorted(REPRESENTATIVE_ARTIFACTS - {"artifacts/incident-evidence.zip"})
    ).lower()
    for unsupported_assumption in (
        b"camera-calibrated",
        b"camera tracked",
        b"fiducial-tagged",
        b"validated by maniskill",
    ):
        assert unsupported_assumption not in artifact_bytes

    claims = _read_json(RECORD_PATH)["claims"]
    assert claims["evidence_classification"] == "owner_generated_public_technical_proof"
    assert claims["independent_reproduction"] is False
    prohibited = " ".join(claims["prohibited"]).lower()
    for required in (
        "official pickcube",
        "grasp",
        "orientation",
        "physical accuracy",
        "simulator realism",
        "sim-to-real",
        "safety",
        "production readiness",
        "general maniskill",
        "endorsement",
        "independent",
        "industry use",
    ):
        assert required in prohibited


def test_citation_metadata_is_valid_bounded_and_tag_specific() -> None:
    citation = yaml.safe_load((PROOF_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert isinstance(citation, dict)
    assert citation["cff-version"] == "1.2.0"
    assert citation["title"] == "Metriplane ManiSkill PickCube External Fixture Proof"
    assert str(citation["version"]) == "1"
    assert str(citation["date-released"]) == "2026-08-12"
    authors = citation["authors"]
    assert any(
        author.get("given-names") == "Miko" and author.get("family-names") == "Parkkinen"
        for author in authors
    )
    serialized = json.dumps(citation, sort_keys=True).lower()
    assert PROOF_TAG in serialized
    assert "rrid:scr_028813" in serialized
    assert "doi" not in citation
    assert "proofs/maniskill-pickcube-v1" in serialized


def test_readiness_is_not_ready_and_owner_approval_is_not_impersonated() -> None:
    readiness = (PROOF_ROOT / "READINESS.md").read_text(encoding="utf-8")
    decision_lines = [
        line.strip().strip("*# ")
        for line in readiness.splitlines()
        if line.strip().strip("*# ") in {"READY", "NOT READY"}
    ]
    assert decision_lines == ["NOT READY"]
    lowered = readiness.lower()
    assert "owner approval" in lowered
    assert "pending" in lowered or "not approved" in lowered
    assert "tag" in lowered and "not" in lowered


def test_reproduce_script_is_standard_library_and_public_cli_only() -> None:
    path = PROOF_ROOT / "reproduce.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])
    assert imports <= {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "platform",
        "re",
        "shutil",
        "subprocess",
        "sys",
        "typing",
        "zipfile",
    }
    assert "from metriplane" not in source
    assert "import metriplane" not in source
    assert "expected-outcome.json" not in source
    assert "urllib" not in source and "requests" not in source
    assert re.search(r'"external",\s*"validate"', source)
    assert re.search(r'"external",\s*"run"', source)
    assert re.search(r'"atlas",\s*"bundle",\s*"verify"', source)
    assert re.search(r'"atlas",\s*"test"', source)
    assert "maniskill_pickcube_incident_proof" in source
    assert "maniskill_pickcube_control_proof" in source


def test_reproduce_failure_writes_a_sanitized_machine_readable_result(
    tmp_path: Path,
) -> None:
    record = _read_json(RECORD_PATH)
    out = tmp_path / "failed-reproduction"
    missing_command = tmp_path / "PRIVATE_MISSING_METRIPLANE"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROOF_ROOT / "reproduce.py"),
            "--repo-root",
            str(REPOSITORY_ROOT),
            "--out",
            str(out),
            "--metriplane-commit",
            record["proof_identity"]["candidate_commit"],
            "--metriplane-command",
            str(missing_command),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    result = _read_json(out / "reproduction-result.json")
    assert result["pass"] is False
    assert result["level"] == "portable_fixture_evaluation"
    assert result["metriplane_git_commit"] == record["proof_identity"]["candidate_commit"]
    assert len(result["errors"]) == 1
    serialized = json.dumps(result, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "PRIVATE_MISSING_METRIPLANE" not in serialized
    assert "<metriplane-command>" in serialized


def test_referenced_metriplane_commits_are_full_and_reachable_in_git() -> None:
    record = _read_json(RECORD_PATH)
    commits = {
        BASELINE_COMMIT,
        ADAPTER_COMMIT,
        record["proof_identity"]["candidate_commit"],
        record["contract"]["metriplane_git_commit"],
    }
    optional = (
        record["proof_identity"]["canonical_commit"],
        record["proof_identity"]["proof_publication_commit"],
    )
    commits.update(commit for commit in optional if commit is not None)
    for commit in commits:
        assert FULL_COMMIT.fullmatch(commit), commit

    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert shallow.returncode == 0, shallow.stderr
    if shallow.stdout.strip() == "true":
        pytest.skip("commit reachability is enforced by the full-history proof workflow")

    for commit in commits:
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, (commit, completed.stderr)


def test_dedicated_workflow_has_structure_red_team_and_four_portable_jobs() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert set(jobs) == {"proof-structure", "artifact-red-team", "portable-proof"}
    portable = jobs["portable-proof"]
    matrix = portable["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-latest", "macos-latest"]
    assert matrix["python-version"] == ["3.12", "3.13"]
    assert re.search(r"python -m build\s+.*--outdir", text, re.DOTALL)
    assert "twine check --strict" in text
    assert 'pip install --no-cache-dir "$wheel_path"' in text
    assert "reproduce.py" in text
    assert "--metriplane-commit" in text
    assert "METRIPLANE_GIT_COMMIT" in text
    assert "moved-portable-proof-output" in text
    assert "Control output contains a fabricated" in text
    assert "jsonschema" in text and "cffconvert" in text and "reuse lint-file" in text
    assert "tools/build_maniskill_pickcube_proof.py" in text
    assert "diff --recursive --brief" in text
    assert 'record["proof_identity"]["candidate_commit"]' in text
    assert "fetch-depth: 0" in text
    assert 'git archive --format=tar "$candidate_commit"' in text
    assert 'git merge-base --is-ancestor "$candidate_commit" HEAD' in text
    assert "CANDIDATE_COMMIT" in text
    assert 'exact_commit="$(git rev-parse HEAD)"' not in text

    action_uses = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", text)
    assert action_uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", use) for use in action_uses)
    assert "branches:\n      - main" in text
    assert f"tags:\n      - {PROOF_TAG}" in text
    assert '"proofs/maniskill-pickcube-v1/**"' in text
