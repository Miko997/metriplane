# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "metriplane.functional-inventory.v1.schema.json"
INVENTORY_PATH = ROOT / "docs" / "status" / "functional-inventory.json"
PROFILES_PATH = ROOT / "docs" / "status" / "support-profiles.json"
BASELINE_PATH = ROOT / "docs" / "status" / "baseline-snapshot.v1.json"
BASELINE_TOOL_PATH = ROOT / "tools" / "baseline_snapshot.py"

MATERIALIZATION_SHA256 = "f5f8ad40229d5e77f40c6de6c7176b303264dfc8754192f631389d687e181192"
BASELINE_SHA256 = "0753e370d8f61df201de98ac838cec9cb9e279f616bd10eab547a6f9511575b3"
BASE_COMMIT = "2969636357140598d742bd0befed034a25463251"
BASE_TREE = "09c4ccd6c418ba9a1b99f0f91c39d0162a544bfa"
RETAINED_EVIDENCE_ROOT_ENV = "METRIPLANE_MP2_010_MATERIALIZATION_ROOT"

CRITERION_EVIDENCE_PATHS = {
    "MP2-010.A01": "evidence/01-result.json",
    "MP2-010.A02": "evidence/02-result.json",
}
CRITERION_FAMILIES = {
    "MP2-010.A01": ("BASELINE", "POSITIVE", "NEGATIVE", "DETERMINISM", "TRACE", "CLEAN"),
    "MP2-010.A02": (
        "BASELINE",
        "POSITIVE",
        "NEGATIVE",
        "DETERMINISM",
        "TRACE",
        "CLEAN",
        "INSTALLED",
    ),
}
EVIDENCE_ARTIFACT_PATHS = (
    "docs/status/functional-inventory.json",
    "docs/status/support-profiles.json",
    "schemas/metriplane.functional-inventory.v1.schema.json",
    "tests/test_functional_inventory.py",
)

INVENTORY_DOWNSTREAM_TASK_IDS = (
    "MP2-011",
    "MP2-012",
    "MP2-013",
    "MP2-014",
    "MP2-015",
    "MP2-016",
    "MP2-017",
    "MP2-018",
)
PROFILE_DOWNSTREAM_TASK_IDS = ("MP2-007", *INVENTORY_DOWNSTREAM_TASK_IDS)

OBLIGATION_IDS = (
    "MP2-010.OBL.ACTIVE_FIELDS_REQUIRED",
    "MP2-010.OBL.BASELINE_INTEGRITY",
    "MP2-010.OBL.CLEAN",
    "MP2-010.OBL.INSTALLED_ENTRY_POINTS",
    "MP2-010.OBL.ROW_MODEL_NEGATIVE",
    "MP2-010.OBL.ROW_MODEL_POSITIVE",
    "MP2-010.OBL.SCHEMA_VALIDATION",
    "MP2-010.OBL.THREE_RUN_DETERMINISM",
    "MP2-010.OBL.TRACE_CLOSURE",
)

EXPECTED_ROWS: dict[str, dict[str, Any]] = {
    "MP2-010.BASELINE.CLI_ROOTS": {
        "claim_classification": "bounded_seed",
        "claim_statement": (
            "The two installed root help surfaces are frozen; MP2-011 owns complete "
            "leaf-action discovery."
        ),
        "consumer_task_ids": ("MP2-011", *INVENTORY_DOWNSTREAM_TASK_IDS[3:]),
        "kind": "cli_root",
        "limitation_ids": ("CLI_ROOT_ONLY",),
        "name": "Installed root console-script help surfaces",
        "pointer": "/commands_and_help/entries",
        "profile": "bootstrap.lock-derived-root-suite",
        "test": "MP2-010.OBL.INSTALLED_ENTRY_POINTS",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_installed_console_scripts_match_frozen_cli_seed",
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
        ),
    },
    "MP2-010.BASELINE.HTTP_ROUTES": {
        "claim_classification": "bounded_seed",
        "claim_statement": (
            "Terminal route declarations and forwarding provenance are frozen; MP2-012 owns "
            "complete route, service, page, and action semantics."
        ),
        "consumer_task_ids": ("MP2-012", *INVENTORY_DOWNSTREAM_TASK_IDS[3:]),
        "kind": "http_route_declarations",
        "limitation_ids": (
            "ROUTE_DECLARATIONS_ONLY",
            "ROUTE_OVERACCEPTANCE_UNCHARACTERIZED",
        ),
        "name": "Terminal HTTP and WebSocket declaration seed",
        "pointer": "/http_routes/entries",
        "profile": "baseline.static-source-census",
        "test": "MP2-010.OBL.BASELINE_INTEGRITY",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
            "tests/test_functional_inventory.py::test_trace_graph_is_closed",
        ),
    },
    "MP2-010.BASELINE.RESOURCES": {
        "claim_classification": "bounded_seed",
        "claim_statement": (
            "The bounded repository and package-data resource seed is frozen; MP2-013 owns "
            "complete semantic resource classification."
        ),
        "consumer_task_ids": ("MP2-013", *INVENTORY_DOWNSTREAM_TASK_IDS[3:]),
        "kind": "resource_seed",
        "limitation_ids": ("RESOURCE_SEED_ONLY",),
        "name": "Tracked resource seed",
        "pointer": "/resources/entries",
        "profile": "baseline.static-source-census",
        "test": "MP2-010.OBL.BASELINE_INTEGRITY",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
            "tests/test_functional_inventory.py::test_trace_graph_is_closed",
        ),
    },
    "MP2-010.BASELINE.SCHEMAS": {
        "claim_classification": "bounded_seed",
        "claim_statement": (
            "Tracked JSON Schemas are frozen; MP2-013 owns generated model-schema and public "
            "contract classification."
        ),
        "consumer_task_ids": ("MP2-013", *INVENTORY_DOWNSTREAM_TASK_IDS[3:]),
        "kind": "schema_seed",
        "limitation_ids": ("GENERATED_MODEL_SCHEMAS_DEFERRED",),
        "name": "Tracked JSON Schema seed",
        "pointer": "/schemas/entries",
        "profile": "baseline.static-source-census",
        "test": "MP2-010.OBL.SCHEMA_VALIDATION",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
            "tests/test_functional_inventory.py::test_schema_and_committed_registries_validate",
        ),
    },
    "MP2-010.BASELINE.TESTS": {
        "claim_classification": "frozen_baseline",
        "claim_statement": (
            "The ordered root pytest collection is frozen as an active stop-the-line baseline; "
            "MP2-014 imports its obligation lineage."
        ),
        "consumer_task_ids": INVENTORY_DOWNSTREAM_TASK_IDS[3:],
        "kind": "test_census",
        "limitation_ids": (),
        "name": "Ordered root pytest collection",
        "pointer": "/tests/collection/node_ids",
        "profile": "bootstrap.lock-derived-root-suite",
        "test": "MP2-010.OBL.BASELINE_INTEGRITY",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
            "tests/test_functional_inventory.py::test_trace_graph_is_closed",
        ),
    },
    "MP2-010.BASELINE.WORKFLOWS": {
        "claim_classification": "bounded_seed",
        "claim_statement": (
            "Maintained workflow files and authored job IDs are frozen; MP2-013 owns complete "
            "workflow and job classification."
        ),
        "consumer_task_ids": ("MP2-013", *INVENTORY_DOWNSTREAM_TASK_IDS[3:]),
        "kind": "workflow_seed",
        "limitation_ids": (),
        "name": "Maintained workflow and job seed",
        "pointer": "/workflows_and_jobs/entries",
        "profile": "baseline.static-source-census",
        "test": "MP2-010.OBL.BASELINE_INTEGRITY",
        "validator_ids": (
            "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
            "tests/test_functional_inventory.py::test_trace_graph_is_closed",
        ),
    },
}

EXPECTED_PROFILES: dict[str, dict[str, Any]] = {
    "baseline.static-source-census": {
        "claim_classification": "observed_not_supported",
        "claim_statement": (
            "Static source census at the frozen MP2-000 commit; this profile makes no runtime "
            "platform support claim."
        ),
        "kind": "static_source",
        "limitation_ids": (),
        "pointer": "/captured_source",
        "test": "MP2-010.OBL.BASELINE_INTEGRITY",
    },
    "bootstrap.lock-derived-root-suite": {
        "claim_classification": "observed_not_supported",
        "claim_statement": (
            "One observed lock-derived bootstrap cell; it proves the frozen installed help and "
            "root suite only and is not a supported-environment row."
        ),
        "kind": "observed_environment",
        "limitation_ids": ("BOOTSTRAP_ENVIRONMENT_NOT_MEASURED",),
        "pointer": "/environment",
        "test": "MP2-010.OBL.INSTALLED_ENTRY_POINTS",
    },
}

BASELINE_ROW_IDS = tuple(sorted(EXPECTED_ROWS))
BASELINE_PROFILE_IDS = tuple(sorted(EXPECTED_PROFILES))

EXPECTED_VALIDATORS = {
    "tests/test_functional_inventory.py::test_installed_console_scripts_match_frozen_cli_seed",
    "tests/test_functional_inventory.py::test_inventory_is_exact_projection_of_frozen_baseline",
    "tests/test_functional_inventory.py::test_schema_and_committed_registries_validate",
    "tests/test_functional_inventory.py::test_trace_graph_is_closed",
}


def _load_baseline_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "metriplane_baseline_snapshot_for_inventory_tests", BASELINE_TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline_tool = _load_baseline_tool()


def obligation(identifier: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return cast(
        Callable[[Callable[..., Any]], Callable[..., Any]],
        pytest.mark.parametrize("_obligation", [pytest.param(identifier, id=identifier)]),
    )


def _canonical_bytes(value: Any) -> bytes:
    return cast(bytes, baseline_tool._canonical_bytes(value))


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _read_canonical(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        baseline_tool._strict_json(path.read_bytes(), require_canonical=True),
    )


def _documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        _read_canonical(SCHEMA_PATH),
        _read_canonical(INVENTORY_PATH),
        _read_canonical(PROFILES_PATH),
        _read_canonical(BASELINE_PATH),
    )


def _read_json(path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        baseline_tool._strict_json(path.read_bytes(), require_canonical=False),
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_object(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _assert_final_criterion_evidence(
    materialization_root: Path,
    *,
    artifact_root: Path,
    expected_base_commit: str,
    expected_commit: str,
    expected_tree: str,
    expected_materialization: str,
) -> None:
    materialization_root = materialization_root.resolve(strict=True)
    artifact_root = artifact_root.resolve(strict=True)
    assert materialization_root.name == expected_materialization
    assert materialization_root.parent.name == expected_base_commit

    canonical_input_path = (materialization_root / "canonical-input.json").resolve(strict=True)
    assert canonical_input_path.parent == materialization_root
    assert _sha256_file(canonical_input_path) == expected_materialization
    canonical_input = _read_json(canonical_input_path)
    assert canonical_input["task"] == "MP2-010"
    assert canonical_input["issue"]["identifier"] == "MET-71"
    assert canonical_input["base"]["commit"] == expected_base_commit

    mappings = {mapping["criterion"]: mapping for mapping in canonical_input["criterion_mappings"]}
    assert set(mappings) == set(CRITERION_EVIDENCE_PATHS)

    expected_artifacts = {}
    for relative_path in EVIDENCE_ARTIFACT_PATHS:
        artifact_path = (artifact_root / relative_path).resolve(strict=True)
        assert artifact_path.is_relative_to(artifact_root)
        expected_artifacts[relative_path] = _sha256_file(artifact_path)

    records = {}
    for criterion, relative_path in CRITERION_EVIDENCE_PATHS.items():
        mapping = mappings[criterion]
        assert mapping["required_evidence"] == relative_path
        assert mapping["required_verdict"] == "PASS"
        assert tuple(mapping["families"]) == CRITERION_FAMILIES[criterion]

        evidence_path = (materialization_root / relative_path).resolve(strict=True)
        assert evidence_path.is_relative_to(materialization_root)
        record = _read_json(evidence_path)
        assert record["schema_version"] == "metriplane.criterion-evidence.v1"
        assert record["task"] == "MP2-010"
        assert record["issue"] == "MET-71"
        assert record["criterion"] == criterion
        assert record["base_commit"] == expected_base_commit
        assert record["commit"] == expected_commit
        assert record["tree"] == expected_tree
        assert record["materialization_sha256"] == expected_materialization
        assert tuple(record["families"]) == CRITERION_FAMILIES[criterion]
        assert record["artifacts"] == expected_artifacts
        assert record["pr"]["head"] == expected_commit
        assert record["pr"]["state"] == "OPEN"
        assert record["pr"]["ci"]["verdict"] == "GREEN"
        assert record["exit_code"] == 0
        assert record["verdict"] == "PASS"
        records[criterion] = record

    assert records["MP2-010.A01"]["artifacts"] == records["MP2-010.A02"]["artifacts"]


def _synthetic_evidence_materialization(
    tmp_path: Path,
) -> tuple[Path, Path, str, str, str]:
    artifact_root = tmp_path / "repo"
    for index, relative_path in enumerate(EVIDENCE_ARTIFACT_PATHS):
        artifact_path = artifact_root / relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(f"artifact-{index}\n".encode())

    canonical_input = {
        "base": {"commit": BASE_COMMIT},
        "criterion_mappings": [
            {
                "criterion": criterion,
                "families": list(CRITERION_FAMILIES[criterion]),
                "required_evidence": relative_path,
                "required_verdict": "PASS",
            }
            for criterion, relative_path in CRITERION_EVIDENCE_PATHS.items()
        ],
        "issue": {"identifier": "MET-71"},
        "task": "MP2-010",
    }
    canonical_input_bytes = _canonical_bytes(canonical_input)
    materialization = hashlib.sha256(canonical_input_bytes).hexdigest()
    materialization_root = tmp_path / BASE_COMMIT / materialization
    evidence_root = materialization_root / "evidence"
    evidence_root.mkdir(parents=True)
    (materialization_root / "canonical-input.json").write_bytes(canonical_input_bytes)

    commit = "1" * 40
    tree = "2" * 40
    artifacts = {
        relative_path: _sha256_file(artifact_root / relative_path)
        for relative_path in EVIDENCE_ARTIFACT_PATHS
    }
    for criterion, relative_path in CRITERION_EVIDENCE_PATHS.items():
        record = {
            "artifacts": artifacts,
            "base_commit": BASE_COMMIT,
            "commit": commit,
            "criterion": criterion,
            "exit_code": 0,
            "families": list(CRITERION_FAMILIES[criterion]),
            "issue": "MET-71",
            "materialization_sha256": materialization,
            "pr": {
                "ci": {"verdict": "GREEN"},
                "head": commit,
                "state": "OPEN",
            },
            "schema_version": "metriplane.criterion-evidence.v1",
            "task": "MP2-010",
            "tree": tree,
            "verdict": "PASS",
        }
        (materialization_root / relative_path).write_bytes(_canonical_bytes(record))
    return materialization_root, artifact_root, commit, tree, materialization


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    assert pointer.startswith("/")
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def _trace(downstream_task_ids: tuple[str, ...]) -> dict[str, Any]:
    return {
        "criterion_ids": ["MP2-010.A01", "MP2-010.A02"],
        "downstream_task_ids": list(downstream_task_ids),
        "issue": "MET-71",
        "materialization_sha256": MATERIALIZATION_SHA256,
        "obligation_ids": list(OBLIGATION_IDS),
        "task": "MP2-010",
    }


def _ordered_by_id(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(copy.deepcopy(list(items)), key=lambda item: item["id"])


def _baseline_rows(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for identifier, spec in sorted(EXPECTED_ROWS.items()):
        source_value = _resolve_pointer(baseline, spec["pointer"])
        rows.append(
            {
                "claim": {
                    "classification": spec["claim_classification"],
                    "limitation_ids": list(spec["limitation_ids"]),
                    "statement": spec["claim_statement"],
                },
                "consumer_task_ids": list(spec["consumer_task_ids"]),
                "id": identifier,
                "kind": spec["kind"],
                "name": spec["name"],
                "owner": "MP2-010",
                "profile": spec["profile"],
                "source": {
                    "count": len(source_value),
                    "digest_sha256": _sha(source_value),
                    "json_pointer": spec["pointer"],
                    "path": "docs/status/baseline-snapshot.v1.json",
                },
                "status": "active",
                "test": spec["test"],
                "trace_criterion_ids": ["MP2-010.A01", "MP2-010.A02"],
                "validator_ids": list(spec["validator_ids"]),
            }
        )

    return rows


def _rebuild_inventory(
    baseline: dict[str, Any], extension_rows: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    rows = _ordered_by_id([*_baseline_rows(baseline), *extension_rows])
    return {
        "baseline": {
            "materialized_base_commit": BASE_COMMIT,
            "materialized_base_tree": BASE_TREE,
            "source_commit": baseline["captured_source"]["commit"],
            "source_path": "docs/status/baseline-snapshot.v1.json",
            "source_schema_version": baseline["schema_version"],
            "source_sha256": _sha(baseline),
            "source_tree": baseline["captured_source"]["tree"],
        },
        "registry_id": "metriplane.functional-inventory.baseline.v0.3",
        "rows": rows,
        "rows_sha256": _sha(rows),
        "schema_path": "schemas/metriplane.functional-inventory.v1.schema.json",
        "schema_version": "metriplane.functional-inventory.v1",
        "support_profiles_path": "docs/status/support-profiles.json",
        "trace": _trace(INVENTORY_DOWNSTREAM_TASK_IDS),
    }


def _baseline_profiles(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = []
    for identifier, spec in sorted(EXPECTED_PROFILES.items()):
        source_value = _resolve_pointer(baseline, spec["pointer"])
        profiles.append(
            {
                "claim": {
                    "classification": spec["claim_classification"],
                    "limitation_ids": list(spec["limitation_ids"]),
                    "statement": spec["claim_statement"],
                },
                "id": identifier,
                "kind": spec["kind"],
                "owner": "MP2-010",
                "source": {
                    "digest_sha256": _sha(source_value),
                    "json_pointer": spec["pointer"],
                    "path": "docs/status/baseline-snapshot.v1.json",
                },
                "status": "active",
                "support_disposition": "not_measured",
                "test": spec["test"],
            }
        )

    return profiles


def _rebuild_profiles(
    baseline: dict[str, Any], extension_profiles: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    profiles = _ordered_by_id([*_baseline_profiles(baseline), *extension_profiles])
    return {
        "profiles": profiles,
        "profiles_sha256": _sha(profiles),
        "schema_path": "schemas/metriplane.functional-inventory.v1.schema.json",
        "schema_version": "metriplane.support-profiles.v1",
        "trace": _trace(PROFILE_DOWNSTREAM_TASK_IDS),
    }


def _extension_rows(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in inventory["rows"] if row["id"] not in BASELINE_ROW_IDS]


def _extension_profiles(profiles: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        profile for profile in profiles["profiles"] if profile["id"] not in BASELINE_PROFILE_IDS
    ]


def _rejects(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    with pytest.raises(baseline_tool.SnapshotError) as captured:
        baseline_tool._internal_validate(instance, schema)
    assert captured.value.code == "SCHEMA_VALIDATION_FAILED"


def _task_id(reference: str) -> str:
    task, separator, _suffix = reference.partition(".")
    assert separator
    return task


def _assert_registry_pair(
    schema: dict[str, Any],
    inventory: dict[str, Any],
    profiles: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    baseline_tool._internal_validate(inventory, schema)
    baseline_tool._internal_validate(profiles, schema)

    rows = inventory["rows"]
    profile_rows = profiles["profiles"]
    row_ids = [row["id"] for row in rows]
    profile_ids = [profile["id"] for profile in profile_rows]
    all_ids = [*row_ids, *profile_ids]
    assert row_ids == sorted(row_ids)
    assert profile_ids == sorted(profile_ids)
    assert len(all_ids) == len(set(all_ids))
    assert inventory["rows_sha256"] == _sha(rows)
    assert profiles["profiles_sha256"] == _sha(profile_rows)

    baseline_rows = [row for row in rows if row["id"] in BASELINE_ROW_IDS]
    baseline_profiles = [
        profile for profile in profile_rows if profile["id"] in BASELINE_PROFILE_IDS
    ]
    assert _canonical_bytes(baseline_rows) == _canonical_bytes(_baseline_rows(baseline))
    assert _canonical_bytes(baseline_profiles) == _canonical_bytes(_baseline_profiles(baseline))
    assert (
        tuple(identifier for identifier in row_ids if identifier.startswith("MP2-010.BASELINE."))
        == BASELINE_ROW_IDS
    )

    profiles_by_id = {profile["id"]: profile for profile in profile_rows}
    for row in rows:
        profile_id = row["profile"]
        if profile_id:
            assert profile_id in profiles_by_id
            if row["status"] in {"active", "deprecated"}:
                assert profiles_by_id[profile_id]["status"] == "active"
        else:
            assert row["status"] == "retired"

        task = _task_id(row["id"])
        if row["owner"]:
            assert row["owner"] == task
        if row["test"]:
            assert _task_id(row["test"]) == task
        assert all(_task_id(criterion) == task for criterion in row["trace_criterion_ids"])

    for profile in profile_rows:
        if profile["test"]:
            assert _task_id(profile["test"]) == profile["owner"]

    for trace in (inventory["trace"], profiles["trace"]):
        task = trace["task"]
        assert all(_task_id(criterion) == task for criterion in trace["criterion_ids"])
        assert all(_task_id(identifier) == task for identifier in trace["obligation_ids"])


@obligation("MP2-010.OBL.SCHEMA_VALIDATION")
def test_schema_and_committed_registries_validate(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()
    baseline_tool._check_schema_definition(schema, schema)
    _assert_registry_pair(schema, inventory, profiles, baseline)


@obligation("MP2-010.OBL.BASELINE_INTEGRITY")
def test_inventory_is_exact_projection_of_frozen_baseline(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()
    assert hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest() == BASELINE_SHA256
    assert inventory["baseline"] == {
        "materialized_base_commit": BASE_COMMIT,
        "materialized_base_tree": BASE_TREE,
        "source_commit": baseline["captured_source"]["commit"],
        "source_path": "docs/status/baseline-snapshot.v1.json",
        "source_schema_version": baseline["schema_version"],
        "source_sha256": BASELINE_SHA256,
        "source_tree": baseline["captured_source"]["tree"],
    }

    _assert_registry_pair(schema, inventory, profiles, baseline)
    rows = [row for row in inventory["rows"] if row["id"] in BASELINE_ROW_IDS]
    profile_rows = [
        profile for profile in profiles["profiles"] if profile["id"] in BASELINE_PROFILE_IDS
    ]
    assert [row["id"] for row in rows] == list(BASELINE_ROW_IDS)
    assert [profile["id"] for profile in profile_rows] == list(BASELINE_PROFILE_IDS)
    for row in rows:
        spec = EXPECTED_ROWS[row["id"]]
        source_value = _resolve_pointer(baseline, spec["pointer"])
        assert row["source"] == {
            "count": len(source_value),
            "digest_sha256": _sha(source_value),
            "json_pointer": spec["pointer"],
            "path": "docs/status/baseline-snapshot.v1.json",
        }
        assert row["profile"] == spec["profile"]
        assert tuple(row["claim"]["limitation_ids"]) == spec["limitation_ids"]

    for profile in profile_rows:
        source_value = _resolve_pointer(baseline, EXPECTED_PROFILES[profile["id"]]["pointer"])
        assert profile["source"]["digest_sha256"] == _sha(source_value)


@obligation("MP2-010.OBL.ROW_MODEL_POSITIVE")
def test_retired_and_deprecated_rows_follow_full_registry_lifecycle(
    _obligation: str,
) -> None:
    schema, inventory, profiles, baseline = _documents()

    retired_inventory = copy.deepcopy(inventory)
    retired_row = copy.deepcopy(retired_inventory["rows"][0])
    retired_row.update(
        {
            "id": "MP2-011.RETIRED.CLI_ROOT",
            "owner": "",
            "profile": "",
            "status": "retired",
            "test": "",
            "trace_criterion_ids": ["MP2-011.A01"],
        }
    )
    retired_inventory["rows"].append(retired_row)
    retired_inventory["rows"].sort(key=lambda row: row["id"])
    retired_inventory["rows_sha256"] = _sha(retired_inventory["rows"])
    _assert_registry_pair(schema, retired_inventory, profiles, baseline)

    deprecated_inventory = copy.deepcopy(inventory)
    deprecated_row = copy.deepcopy(deprecated_inventory["rows"][0])
    deprecated_row.update(
        {
            "id": "MP2-011.DEPRECATED.CLI_ROOT",
            "owner": "MP2-011",
            "status": "deprecated",
            "test": "MP2-011.OBL.DEPRECATED_CLI_ROOT",
            "trace_criterion_ids": ["MP2-011.A01"],
        }
    )
    deprecated_inventory["rows"].append(deprecated_row)
    deprecated_inventory["rows"].sort(key=lambda row: row["id"])
    deprecated_inventory["rows_sha256"] = _sha(deprecated_inventory["rows"])
    _assert_registry_pair(schema, deprecated_inventory, profiles, baseline)


@obligation("MP2-010.OBL.ROW_MODEL_NEGATIVE")
def test_retired_and_deprecated_profile_closure_fails_closed(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()

    retired_with_missing_profile = copy.deepcopy(inventory)
    retired_row = copy.deepcopy(retired_with_missing_profile["rows"][0])
    retired_row.update(
        {
            "id": "MP2-011.RETIRED.CLI_ROOT",
            "owner": "",
            "profile": "missing.profile",
            "status": "retired",
            "test": "",
            "trace_criterion_ids": ["MP2-011.A01"],
        }
    )
    retired_with_missing_profile["rows"].append(retired_row)
    retired_with_missing_profile["rows"].sort(key=lambda row: row["id"])
    retired_with_missing_profile["rows_sha256"] = _sha(retired_with_missing_profile["rows"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, retired_with_missing_profile, profiles, baseline)

    deprecated_without_profile = copy.deepcopy(inventory)
    deprecated_row = copy.deepcopy(deprecated_without_profile["rows"][0])
    deprecated_row.update(
        {
            "id": "MP2-011.DEPRECATED.CLI_ROOT",
            "owner": "MP2-011",
            "profile": "",
            "status": "deprecated",
            "test": "MP2-011.OBL.DEPRECATED_CLI_ROOT",
            "trace_criterion_ids": ["MP2-011.A01"],
        }
    )
    deprecated_without_profile["rows"].append(deprecated_row)
    deprecated_without_profile["rows"].sort(key=lambda row: row["id"])
    deprecated_without_profile["rows_sha256"] = _sha(deprecated_without_profile["rows"])
    with pytest.raises(baseline_tool.SnapshotError):
        _assert_registry_pair(schema, deprecated_without_profile, profiles, baseline)


@pytest.mark.parametrize("status", ["active", "deprecated"])
@obligation("MP2-010.OBL.ROW_MODEL_NEGATIVE")
def test_maintained_rows_cannot_reference_a_retired_profile(_obligation: str, status: str) -> None:
    schema, inventory, profiles, baseline = _documents()

    profiles_with_retired = copy.deepcopy(profiles)
    retired_profile = copy.deepcopy(profiles_with_retired["profiles"][0])
    retired_profile.update(
        {
            "id": "retired.runtime.profile",
            "owner": "",
            "status": "retired",
            "test": "",
        }
    )
    profiles_with_retired["profiles"].append(retired_profile)
    profiles_with_retired["profiles"].sort(key=lambda profile: profile["id"])
    profiles_with_retired["profiles_sha256"] = _sha(profiles_with_retired["profiles"])

    inventory_with_reference = copy.deepcopy(inventory)
    maintained_row = copy.deepcopy(inventory_with_reference["rows"][0])
    maintained_row.update(
        {
            "id": "MP2-011.MAINTAINED.CLI_ROOT",
            "owner": "MP2-011",
            "profile": retired_profile["id"],
            "status": status,
            "test": "MP2-011.OBL.MAINTAINED_CLI_ROOT",
            "trace_criterion_ids": ["MP2-011.A01"],
        }
    )
    inventory_with_reference["rows"].append(maintained_row)
    inventory_with_reference["rows"].sort(key=lambda row: row["id"])
    inventory_with_reference["rows_sha256"] = _sha(inventory_with_reference["rows"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, inventory_with_reference, profiles_with_retired, baseline)


@obligation("MP2-010.OBL.ROW_MODEL_POSITIVE")
def test_committed_like_downstream_extensions_preserve_registry_invariants(
    _obligation: str,
) -> None:
    schema, _inventory, _profiles, baseline = _documents()
    measured_profile = {
        "claim": {
            "classification": "supported",
            "limitation_ids": [],
            "statement": "Measured installed Python 3.12 profile for downstream inventory validation.",
        },
        "id": "linux.python312.installed",
        "kind": "measured_environment",
        "owner": "MP2-011",
        "source": {
            "locator": "python:3.12",
            "path": "uv.lock",
            "type": "installed_discovery",
        },
        "status": "active",
        "support_disposition": "measured",
        "test": "MP2-011.OBL.PROFILE",
    }
    browser_profile = {
        "claim": {
            "classification": "compatibility",
            "limitation_ids": [],
            "statement": "Measured Chromium profile for downstream UI inventory validation.",
        },
        "id": "linux.chromium.measured",
        "kind": "measured_browser",
        "owner": "MP2-012",
        "source": {
            "locator": "chromium",
            "path": "tests/ui_coverage",
            "type": "installed_discovery",
        },
        "status": "active",
        "support_disposition": "measured",
        "test": "MP2-012.OBL.PROFILE",
    }
    rows = [
        {
            "claim": {
                "classification": "supported",
                "limitation_ids": [],
                "statement": "Installed leaf command discovered by MP2-011.",
            },
            "consumer_task_ids": ["MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018"],
            "id": "MP2-011.CLI.COMMAND.DOCTOR",
            "kind": "cli_command",
            "name": "metriplane doctor",
            "owner": "MP2-011",
            "profile": measured_profile["id"],
            "source": {
                "locator": "console_scripts:metriplane doctor",
                "path": "metriplane",
                "type": "installed_discovery",
            },
            "status": "active",
            "test": "MP2-011.OBL.COMMAND_DISCOVERY",
            "trace_criterion_ids": ["MP2-011.A01", "MP2-011.A02"],
            "validator_ids": ["tests/test_cli_inventory.py::test_leaf_commands_are_complete"],
        },
        {
            "claim": {
                "classification": "compatibility",
                "limitation_ids": [],
                "statement": "Maintained UI action discovered by MP2-012.",
            },
            "consumer_task_ids": ["MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018"],
            "id": "MP2-012.UI.ACTION.RUN_START",
            "kind": "ui_action",
            "name": "Start run",
            "owner": "MP2-012",
            "profile": browser_profile["id"],
            "source": {
                "locator": "button[data-command-id=run-start]",
                "path": "web/dashboard/command-center.html",
                "type": "repository_discovery",
            },
            "status": "active",
            "test": "MP2-012.OBL.UI_ACTION_DISCOVERY",
            "trace_criterion_ids": ["MP2-012.A01", "MP2-012.A02"],
            "validator_ids": ["tests/ui_coverage/test_inventory.py::test_actions_are_complete"],
        },
        {
            "claim": {
                "classification": "supported",
                "limitation_ids": [],
                "statement": "Public model export discovered by MP2-013.",
            },
            "consumer_task_ids": ["MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018"],
            "id": "MP2-013.PUBLIC_API.OBJECT_STATE",
            "kind": "public_api",
            "name": "metriplane.schema.ObjectStateModel",
            "owner": "MP2-013",
            "profile": measured_profile["id"],
            "source": {
                "digest_sha256": _sha("metriplane.schema.ObjectStateModel"),
                "locator": "ObjectStateModel",
                "path": "metriplane/schema.py",
                "type": "repository_discovery",
            },
            "status": "active",
            "test": "MP2-013.OBL.PUBLIC_API_DISCOVERY",
            "trace_criterion_ids": ["MP2-013.A01", "MP2-013.A02"],
            "validator_ids": ["tests/test_public_api_inventory.py::test_exports_are_complete"],
        },
    ]

    extension_profiles = [measured_profile, browser_profile]
    representative_inventory = _rebuild_inventory(baseline, reversed(rows))
    representative_profiles = _rebuild_profiles(baseline, reversed(extension_profiles))
    _assert_registry_pair(schema, representative_inventory, representative_profiles, baseline)

    expected_row_ids = [*BASELINE_ROW_IDS]
    expected_row_ids.extend(cast(str, row["id"]) for row in rows)
    expected_row_ids.sort()
    expected_profile_ids = [*BASELINE_PROFILE_IDS]
    expected_profile_ids.extend(cast(str, profile["id"]) for profile in extension_profiles)
    expected_profile_ids.sort()
    assert [row["id"] for row in representative_inventory["rows"]] == expected_row_ids
    assert [profile["id"] for profile in representative_profiles["profiles"]] == (
        expected_profile_ids
    )
    assert {row["profile"] for row in representative_inventory["rows"]} <= {
        profile["id"] for profile in representative_profiles["profiles"]
    }

    inventory_projections = [
        _canonical_bytes(_rebuild_inventory(copy.deepcopy(baseline), order))
        for order in (rows, list(reversed(rows)), rows[1:] + rows[:1])
    ]
    profile_projections = [
        _canonical_bytes(_rebuild_profiles(copy.deepcopy(baseline), order))
        for order in (
            extension_profiles,
            list(reversed(extension_profiles)),
            extension_profiles[1:] + extension_profiles[:1],
        )
    ]
    assert len(set(inventory_projections)) == 1
    assert len(set(profile_projections)) == 1


@pytest.mark.parametrize("value", ["", " ", "\t"])
@pytest.mark.parametrize("field", ["owner", "profile", "test"])
@obligation("MP2-010.OBL.ACTIVE_FIELDS_REQUIRED")
def test_active_rows_reject_blank_owner_profile_and_test(
    _obligation: str, field: str, value: str
) -> None:
    schema, inventory, _profiles, _baseline = _documents()
    invalid = copy.deepcopy(inventory)
    invalid["rows"][0][field] = value
    invalid["rows_sha256"] = _sha(invalid["rows"])
    _rejects(invalid, schema)


@pytest.mark.parametrize("value", ["", " ", "\t"])
@pytest.mark.parametrize("field", ["owner", "test"])
@obligation("MP2-010.OBL.ACTIVE_FIELDS_REQUIRED")
def test_active_profiles_reject_blank_owner_and_test(
    _obligation: str, field: str, value: str
) -> None:
    schema, _inventory, profiles, _baseline = _documents()
    invalid = copy.deepcopy(profiles)
    invalid["profiles"][0][field] = value
    invalid["profiles_sha256"] = _sha(invalid["profiles"])
    _rejects(invalid, schema)


@obligation("MP2-010.OBL.ACTIVE_FIELDS_REQUIRED")
def test_active_rows_and_profiles_require_valid_status(_obligation: str) -> None:
    schema, inventory, profiles, _baseline = _documents()
    invalid_inventory = copy.deepcopy(inventory)
    invalid_inventory["rows"][0]["status"] = ""
    invalid_inventory["rows_sha256"] = _sha(invalid_inventory["rows"])
    _rejects(invalid_inventory, schema)

    invalid_profiles = copy.deepcopy(profiles)
    invalid_profiles["profiles"][0]["status"] = ""
    invalid_profiles["profiles_sha256"] = _sha(invalid_profiles["profiles"])
    _rejects(invalid_profiles, schema)


@obligation("MP2-010.OBL.ROW_MODEL_NEGATIVE")
def test_row_model_rejects_unknown_fields(_obligation: str) -> None:
    schema, inventory, _profiles, _baseline = _documents()
    invalid = copy.deepcopy(inventory)
    invalid["rows"][0]["unreviewed_surface"] = True
    invalid["rows_sha256"] = _sha(invalid["rows"])
    _rejects(invalid, schema)


@obligation("MP2-010.OBL.ROW_MODEL_NEGATIVE")
def test_registry_pair_rejects_duplicate_stable_ids(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()

    duplicate_rows = copy.deepcopy(inventory)
    duplicate_row = copy.deepcopy(duplicate_rows["rows"][0])
    duplicate_row["name"] = "Different row with the same stable ID"
    duplicate_rows["rows"].append(duplicate_row)
    duplicate_rows["rows"].sort(key=lambda row: row["id"])
    duplicate_rows["rows_sha256"] = _sha(duplicate_rows["rows"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, duplicate_rows, profiles, baseline)

    duplicate_profiles = copy.deepcopy(profiles)
    duplicate_profile = copy.deepcopy(duplicate_profiles["profiles"][0])
    duplicate_profile["claim"]["statement"] = "Different profile with the same stable ID."
    duplicate_profiles["profiles"].append(duplicate_profile)
    duplicate_profiles["profiles"].sort(key=lambda profile: profile["id"])
    duplicate_profiles["profiles_sha256"] = _sha(duplicate_profiles["profiles"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, inventory, duplicate_profiles, baseline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "MP2-012"),
        ("test", "MP2-012.OBL.WRONG_TASK"),
        ("trace_criterion_ids", ["MP2-013.A01"]),
    ],
)
@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_row_lineage_is_derived_from_each_stable_id(
    _obligation: str, field: str, value: str | list[str]
) -> None:
    schema, inventory, profiles, baseline = _documents()
    invalid = copy.deepcopy(inventory)
    extension = copy.deepcopy(invalid["rows"][0])
    extension["id"] = "MP2-011.CLI.COMMAND.DOCTOR"
    extension["owner"] = "MP2-011"
    extension["test"] = "MP2-011.OBL.COMMAND_DISCOVERY"
    extension["trace_criterion_ids"] = ["MP2-011.A01"]
    extension[field] = value
    invalid["rows"].append(extension)
    invalid["rows"].sort(key=lambda row: row["id"])
    invalid["rows_sha256"] = _sha(invalid["rows"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, invalid, profiles, baseline)


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_profile_and_registry_trace_lineage_is_generic(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()

    invalid_profile = copy.deepcopy(profiles)
    extension_profile = copy.deepcopy(invalid_profile["profiles"][0])
    extension_profile["id"] = "linux.python312.installed"
    extension_profile["owner"] = "MP2-011"
    extension_profile["test"] = "MP2-012.OBL.WRONG_TASK"
    invalid_profile["profiles"].append(extension_profile)
    invalid_profile["profiles"].sort(key=lambda profile: profile["id"])
    invalid_profile["profiles_sha256"] = _sha(invalid_profile["profiles"])
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, inventory, invalid_profile, baseline)

    invalid_trace = copy.deepcopy(inventory)
    invalid_trace["trace"]["task"] = "MP2-011"
    with pytest.raises(AssertionError):
        _assert_registry_pair(schema, invalid_trace, profiles, baseline)


@obligation("MP2-010.OBL.THREE_RUN_DETERMINISM")
def test_three_run_determinism(_obligation: str) -> None:
    schema, inventory, profiles, _baseline = _documents()
    baseline_row_projections = []
    baseline_profile_projections = []
    inventory_projections = []
    profile_projections = []
    for _run in range(3):
        baseline = _read_canonical(BASELINE_PATH)
        committed_inventory = _read_canonical(INVENTORY_PATH)
        committed_profiles = _read_canonical(PROFILES_PATH)
        rebuilt_inventory = _rebuild_inventory(baseline, _extension_rows(committed_inventory))
        rebuilt_profiles = _rebuild_profiles(baseline, _extension_profiles(committed_profiles))
        _assert_registry_pair(schema, rebuilt_inventory, rebuilt_profiles, baseline)
        baseline_row_projections.append(_canonical_bytes(_baseline_rows(baseline)))
        baseline_profile_projections.append(_canonical_bytes(_baseline_profiles(baseline)))
        inventory_projections.append(_canonical_bytes(rebuilt_inventory))
        profile_projections.append(_canonical_bytes(rebuilt_profiles))

    assert len(set(baseline_row_projections)) == 1
    assert len(set(baseline_profile_projections)) == 1
    assert len({*inventory_projections}) == 1
    assert len({*profile_projections}) == 1
    assert inventory_projections[0] == INVENTORY_PATH.read_bytes()
    assert profile_projections[0] == PROFILES_PATH.read_bytes()
    assert inventory["rows_sha256"] == _sha(inventory["rows"])
    assert profiles["profiles_sha256"] == _sha(profiles["profiles"])


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_profile_references_are_closed(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()
    _assert_registry_pair(schema, inventory, profiles, baseline)
    profile_rows = profiles["profiles"]
    profile_ids = {row["id"] for row in profile_rows}
    assert [row["id"] for row in profile_rows] == sorted(profile_ids)
    assert {row["profile"] for row in inventory["rows"] if row["profile"]} <= profile_ids

    limitation_ids = {row["limitation_id"] for row in baseline["limitations"]}
    for row in [*inventory["rows"], *profile_rows]:
        maintained_statuses = {"active", "deprecated"} if "profile" in row else {"active"}
        if row["status"] in maintained_statuses:
            assert all(row[field].strip() for field in ("owner", "status", "test"))
            if "profile" in row:
                assert row["profile"].strip()

    baseline_items = [
        *[row for row in inventory["rows"] if row["id"] in BASELINE_ROW_IDS],
        *[row for row in profile_rows if row["id"] in BASELINE_PROFILE_IDS],
    ]
    for row in baseline_items:
        assert set(row["claim"]["limitation_ids"]) <= limitation_ids
        source_value = _resolve_pointer(baseline, row["source"]["json_pointer"])
        assert row["source"]["path"] == "docs/status/baseline-snapshot.v1.json"
        assert row["source"]["digest_sha256"] == _sha(source_value)


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_trace_graph_is_closed(_obligation: str) -> None:
    schema, inventory, profiles, baseline = _documents()
    _assert_registry_pair(schema, inventory, profiles, baseline)
    trace_expectations = (
        (inventory["trace"], INVENTORY_DOWNSTREAM_TASK_IDS),
        (profiles["trace"], PROFILE_DOWNSTREAM_TASK_IDS),
    )
    for trace, expected_downstream in trace_expectations:
        assert trace["task"] == "MP2-010"
        assert trace["issue"] == "MET-71"
        assert trace["materialization_sha256"] == MATERIALIZATION_SHA256
        assert trace["criterion_ids"] == ["MP2-010.A01", "MP2-010.A02"]
        assert tuple(trace["obligation_ids"]) == OBLIGATION_IDS
        assert tuple(trace["downstream_task_ids"]) == expected_downstream

    baseline_rows = [row for row in inventory["rows"] if row["id"] in BASELINE_ROW_IDS]
    validator_ids = {validator for row in baseline_rows for validator in row["validator_ids"]}
    assert validator_ids == EXPECTED_VALIDATORS
    for row in baseline_rows:
        assert row["owner"] == "MP2-010"
        assert "MP2-017" in row["consumer_task_ids"]
        assert row["validator_ids"]
        assert row["trace_criterion_ids"] == ["MP2-010.A01", "MP2-010.A02"]


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_final_criterion_evidence_bindings(_obligation: str) -> None:
    raw_root = os.environ.get(RETAINED_EVIDENCE_ROOT_ENV)
    if raw_root is None:
        pytest.skip(f"requires governed retained evidence profile via {RETAINED_EVIDENCE_ROOT_ENV}")

    _assert_final_criterion_evidence(
        Path(raw_root),
        artifact_root=ROOT,
        expected_base_commit=BASE_COMMIT,
        expected_commit=_git_object("rev-parse", "HEAD"),
        expected_tree=_git_object("rev-parse", "HEAD^{tree}"),
        expected_materialization=MATERIALIZATION_SHA256,
    )


def test_criterion_evidence_resolver_accepts_complete_bindings(tmp_path: Path) -> None:
    materialization_root, artifact_root, commit, tree, materialization = (
        _synthetic_evidence_materialization(tmp_path)
    )
    _assert_final_criterion_evidence(
        materialization_root,
        artifact_root=artifact_root,
        expected_base_commit=BASE_COMMIT,
        expected_commit=commit,
        expected_tree=tree,
        expected_materialization=materialization,
    )


def test_criterion_evidence_resolver_requires_both_records(tmp_path: Path) -> None:
    materialization_root, artifact_root, commit, tree, materialization = (
        _synthetic_evidence_materialization(tmp_path)
    )
    (materialization_root / CRITERION_EVIDENCE_PATHS["MP2-010.A02"]).unlink()
    with pytest.raises(FileNotFoundError):
        _assert_final_criterion_evidence(
            materialization_root,
            artifact_root=artifact_root,
            expected_base_commit=BASE_COMMIT,
            expected_commit=commit,
            expected_tree=tree,
            expected_materialization=materialization,
        )


@pytest.mark.parametrize("binding", ["commit", "tree", "materialization", "artifact"])
def test_criterion_evidence_resolver_rejects_changed_bindings(tmp_path: Path, binding: str) -> None:
    materialization_root, artifact_root, commit, tree, materialization = (
        _synthetic_evidence_materialization(tmp_path)
    )
    expected_commit = commit
    expected_tree = tree
    expected_materialization = materialization
    if binding == "commit":
        expected_commit = "3" * 40
    elif binding == "tree":
        expected_tree = "4" * 40
    elif binding == "materialization":
        expected_materialization = "5" * 64
    else:
        (artifact_root / EVIDENCE_ARTIFACT_PATHS[0]).write_bytes(b"changed\n")

    with pytest.raises(AssertionError):
        _assert_final_criterion_evidence(
            materialization_root,
            artifact_root=artifact_root,
            expected_base_commit=BASE_COMMIT,
            expected_commit=expected_commit,
            expected_tree=expected_tree,
            expected_materialization=expected_materialization,
        )


def _console_scripts(entry_points: Iterable[Any]) -> dict[str, str]:
    return {
        str(entry.name): str(entry.value)
        for entry in entry_points
        if entry.group == "console_scripts"
    }


def _distribution_metadata_path(distribution: importlib.metadata.Distribution) -> Path:
    raw_path = getattr(distribution, "_path", None)
    assert isinstance(raw_path, (str, os.PathLike))
    return Path(raw_path).resolve(strict=True)


def _assert_distribution_origin(
    distribution: importlib.metadata.Distribution,
    site_packages: Path,
    expected_dist_info: Path,
) -> None:
    origin = _distribution_metadata_path(distribution)
    assert origin == expected_dist_info
    assert origin.parent == site_packages
    assert origin.name.endswith(".dist-info")


def _assert_non_editable_provenance(
    direct_url: dict[str, Any], expected_kind: str, expected_url: str
) -> None:
    assert expected_kind in {"local", "sdist", "wheel"}
    assert direct_url.get("dir_info", {}).get("editable") is not True
    assert direct_url.get("url") == expected_url
    if expected_kind == "local":
        assert isinstance(direct_url.get("dir_info"), dict)
        return

    assert isinstance(direct_url.get("archive_info"), dict)
    expected_suffix = ".whl" if expected_kind == "wheel" else ".tar.gz"
    assert expected_url.endswith(expected_suffix)


def _discover_isolated_distribution(
    site_packages: Path, expected_dist_info: Path
) -> importlib.metadata.Distribution:
    distributions = [
        distribution
        for distribution in importlib.metadata.distributions(path=[str(site_packages)])
        if str(distribution.metadata["Name"]).lower().replace("_", "-") == "metriplane"
    ]
    assert len(distributions) == 1
    distribution = distributions[0]
    _assert_distribution_origin(distribution, site_packages, expected_dist_info)
    return distribution


def _isolated_install_paths() -> tuple[Path, Path]:
    prefix = Path(sys.prefix).resolve(strict=True)
    site_packages_candidates = sorted((prefix / "lib").glob("python*/site-packages"))
    assert len(site_packages_candidates) == 1
    site_packages = site_packages_candidates[0].resolve(strict=True)
    dist_info_candidates = sorted(site_packages.glob("metriplane-*.dist-info"))
    assert len(dist_info_candidates) == 1
    return site_packages, dist_info_candidates[0].resolve(strict=True)


INSTALLED_METADATA_PROBE = r"""
import importlib.metadata
import json
import os
from pathlib import Path
import sys

site_packages = Path(os.environ["METRIPLANE_ISOLATED_SITE_PACKAGES"]).resolve(strict=True)
expected_dist_info = Path(os.environ["METRIPLANE_EXPECTED_DIST_INFO"]).resolve(strict=True)
forbidden_checkout = Path(os.environ["METRIPLANE_FORBIDDEN_CHECKOUT"]).resolve(strict=True)
expected_artifact_kind = os.environ["METRIPLANE_EXPECT_ARTIFACT_KIND"]
expected_artifact_url = os.environ["METRIPLANE_EXPECT_ARTIFACT_URL"]

resolved_sys_path = [Path(entry).resolve() for entry in sys.path if entry]
assert all(
    path != forbidden_checkout and forbidden_checkout not in path.parents
    for path in resolved_sys_path
)
assert [path for path in resolved_sys_path if path.name == "site-packages"] == [
    site_packages
]

distributions = [
    distribution
    for distribution in importlib.metadata.distributions(path=[str(site_packages)])
    if str(distribution.metadata["Name"]).lower().replace("_", "-") == "metriplane"
]
assert len(distributions) == 1
distribution = distributions[0]
origin = Path(distribution._path).resolve(strict=True)
assert origin == expected_dist_info
assert origin.parent == site_packages
assert origin.name.endswith(".dist-info")
direct_url = json.loads((origin / "direct_url.json").read_text("utf-8"))
assert expected_artifact_kind in {"sdist", "wheel"}
assert direct_url.get("dir_info", {}).get("editable") is not True
assert direct_url.get("url") == expected_artifact_url
assert isinstance(direct_url.get("archive_info"), dict)
expected_suffix = ".whl" if expected_artifact_kind == "wheel" else ".tar.gz"
assert expected_artifact_url.endswith(expected_suffix)

scripts = {
    entry.name: entry.value
    for entry in distribution.entry_points
    if entry.group == "console_scripts"
}
print(json.dumps({
    "artifact_kind": expected_artifact_kind,
    "artifact_url": expected_artifact_url,
    "origin": str(origin),
    "scripts": scripts,
}, sort_keys=True))
"""


def _frozen_console_scripts() -> dict[str, str]:
    _schema, inventory, _profiles, baseline = _documents()
    cli_row = next(row for row in inventory["rows"] if row["kind"] == "cli_root")
    baseline_entries = _resolve_pointer(baseline, cli_row["source"]["json_pointer"])
    return {row["command"]: row["entry_point"] for row in baseline_entries}


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_declared_console_scripts_match_frozen_cli_seed(_obligation: str) -> None:
    expected = _frozen_console_scripts()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert pyproject["project"]["scripts"] == expected


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_installed_console_scripts_match_frozen_cli_seed(_obligation: str, tmp_path: Path) -> None:
    if os.environ.get("METRIPLANE_TEST_PROFILE") != "installed":
        pytest.skip("requires the governed non-editable installed test profile")

    expected = _frozen_console_scripts()
    site_packages, expected_dist_info = _isolated_install_paths()
    distribution = _discover_isolated_distribution(site_packages, expected_dist_info)
    expected_artifact_kind = os.environ["METRIPLANE_EXPECT_ARTIFACT_KIND"]
    expected_artifact_url = os.environ["METRIPLANE_EXPECT_ARTIFACT_URL"]
    forbidden_checkout = Path(os.environ["METRIPLANE_FORBIDDEN_CHECKOUT"]).resolve(strict=True)
    assert expected_artifact_kind in {"sdist", "wheel"}
    direct_url = json.loads((expected_dist_info / "direct_url.json").read_text("utf-8"))
    _assert_non_editable_provenance(direct_url, expected_artifact_kind, expected_artifact_url)
    assert _console_scripts(distribution.entry_points) == expected

    probe_environment = {
        "METRIPLANE_EXPECT_ARTIFACT_KIND": expected_artifact_kind,
        "METRIPLANE_EXPECT_ARTIFACT_URL": expected_artifact_url,
        "METRIPLANE_EXPECTED_DIST_INFO": str(expected_dist_info),
        "METRIPLANE_FORBIDDEN_CHECKOUT": str(forbidden_checkout),
        "METRIPLANE_ISOLATED_SITE_PACKAGES": str(site_packages),
        "PYTHONHASHSEED": "0",
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-c", INSTALLED_METADATA_PROBE],
        cwd=tmp_path,
        env=probe_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    probe_result = json.loads(completed.stdout)
    assert probe_result == {
        "artifact_kind": expected_artifact_kind,
        "artifact_url": expected_artifact_url,
        "origin": str(expected_dist_info),
        "scripts": expected,
    }


@pytest.mark.parametrize(
    ("direct_url", "kind", "url"),
    [
        (
            {"archive_info": {"hash": "sha256=wheel"}, "url": "file:///tmp/metriplane.whl"},
            "wheel",
            "file:///tmp/metriplane.whl",
        ),
        (
            {
                "archive_info": {"hash": "sha256=sdist"},
                "url": "file:///tmp/metriplane.tar.gz",
            },
            "sdist",
            "file:///tmp/metriplane.tar.gz",
        ),
        (
            {"dir_info": {"editable": False}, "url": "file:///tmp/metriplane-source"},
            "local",
            "file:///tmp/metriplane-source",
        ),
    ],
)
@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_non_editable_installed_provenance_is_supported(
    _obligation: str, direct_url: dict[str, Any], kind: str, url: str
) -> None:
    _assert_non_editable_provenance(direct_url, kind, url)


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_editable_or_wrong_artifact_provenance_fails_closed(_obligation: str) -> None:
    editable = {
        "dir_info": {"editable": True},
        "url": "file:///tmp/metriplane-source",
    }
    with pytest.raises(AssertionError):
        _assert_non_editable_provenance(editable, "local", "file:///tmp/metriplane-source")

    wheel = {
        "archive_info": {"hash": "sha256=wheel"},
        "url": "file:///tmp/metriplane.whl",
    }
    with pytest.raises(AssertionError):
        _assert_non_editable_provenance(wheel, "wheel", "file:///tmp/different-metriplane.whl")


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_unconstrained_distribution_reproduces_worktree_shadowing(
    _obligation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "checkout"
    site_packages = tmp_path / "isolated-site-packages"
    egg_info = worktree / "metriplane.egg-info"
    dist_info = site_packages / "metriplane-0.3.0.dist-info"
    egg_info.mkdir(parents=True)
    dist_info.mkdir(parents=True)
    metadata = "Metadata-Version: 2.1\nName: metriplane\nVersion: 0.3.0\n"
    (egg_info / "PKG-INFO").write_text(metadata, encoding="utf-8")
    (dist_info / "METADATA").write_text(metadata, encoding="utf-8")

    monkeypatch.setattr(sys, "path", [str(worktree), str(site_packages), *sys.path])
    unconstrained = importlib.metadata.distribution("metriplane")
    assert _distribution_metadata_path(unconstrained) == egg_info
    with pytest.raises(AssertionError):
        _assert_distribution_origin(unconstrained, site_packages, dist_info)

    isolated = _discover_isolated_distribution(site_packages, dist_info)
    assert _distribution_metadata_path(isolated) == dist_info


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_console_script_projection_preserves_unexpected_entries(_obligation: str) -> None:
    projected = _console_scripts(
        [
            SimpleNamespace(
                group="console_scripts",
                name="metriplane",
                value="metriplane.cli:main",
            ),
            SimpleNamespace(
                group="console_scripts",
                name="unexpected-command",
                value="unexpected.module:main",
            ),
        ]
    )
    assert projected == {
        "metriplane": "metriplane.cli:main",
        "unexpected-command": "unexpected.module:main",
    }


@obligation("MP2-010.OBL.CLEAN")
def test_declared_obligation_set_is_exact(_obligation: str) -> None:
    _schema, inventory, profiles, _baseline = _documents()
    assert tuple(inventory["trace"]["obligation_ids"]) == OBLIGATION_IDS
    assert tuple(profiles["trace"]["obligation_ids"]) == OBLIGATION_IDS
    assert len(OBLIGATION_IDS) == len(set(OBLIGATION_IDS))
