# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "metriplane.functional-inventory.v1.schema.json"
INVENTORY_PATH = ROOT / "docs" / "status" / "functional-inventory.json"
PROFILES_PATH = ROOT / "docs" / "status" / "support-profiles.json"
BASELINE_PATH = ROOT / "docs" / "status" / "baseline-snapshot.v1.json"
BASELINE_TOOL_PATH = ROOT / "tools" / "baseline_snapshot.py"

MATERIALIZATION_SHA256 = "7b04a54b40a2ebe57a76920ee2e6d838baf8c28d316b47500389b9a993f39648"
BASELINE_SHA256 = "0753e370d8f61df201de98ac838cec9cb9e279f616bd10eab547a6f9511575b3"
BASE_COMMIT = "2969636357140598d742bd0befed034a25463251"
BASE_TREE = "09c4ccd6c418ba9a1b99f0f91c39d0162a544bfa"

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

EXPECTED_ROWS = {
    "MP2-010.BASELINE.CLI_ROOTS": (
        "/commands_and_help/entries",
        2,
        "ce816d16ee650b9b038c8e09982f45a14c11d51cab4a03f79118ec3eba6bd104",
        "bootstrap.lock-derived-root-suite",
        ("CLI_ROOT_ONLY",),
    ),
    "MP2-010.BASELINE.HTTP_ROUTES": (
        "/http_routes/entries",
        48,
        "c278c306fe36d7251da0a04d710fe02d8d90758c911c325e4c827a0b41e7abaf",
        "baseline.static-source-census",
        ("ROUTE_DECLARATIONS_ONLY", "ROUTE_OVERACCEPTANCE_UNCHARACTERIZED"),
    ),
    "MP2-010.BASELINE.RESOURCES": (
        "/resources/entries",
        256,
        "c165504cf119027624e11a39a3c0f969a0975d51585f590f740b2fa8b15d7d94",
        "baseline.static-source-census",
        ("RESOURCE_SEED_ONLY",),
    ),
    "MP2-010.BASELINE.SCHEMAS": (
        "/schemas/entries",
        6,
        "68069c30fce592538fe7b181396df64deac35abd48751bdaf5b1a5242bbfbaf6",
        "baseline.static-source-census",
        ("GENERATED_MODEL_SCHEMAS_DEFERRED",),
    ),
    "MP2-010.BASELINE.TESTS": (
        "/tests/collection/node_ids",
        1194,
        "ba68bcaa580c7e392a435ddedd254a6487d8032db3e1e23ad0e6793c5e2a4469",
        "bootstrap.lock-derived-root-suite",
        (),
    ),
    "MP2-010.BASELINE.WORKFLOWS": (
        "/workflows_and_jobs/entries",
        15,
        "76a647b24cba2203386722406fdd6626757fabcb79390dc1afb8fc20f36bc93c",
        "baseline.static-source-census",
        (),
    ),
}

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


def _rejects(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    with pytest.raises(baseline_tool.SnapshotError) as captured:
        baseline_tool._internal_validate(instance, schema)
    assert captured.value.code == "SCHEMA_VALIDATION_FAILED"


@obligation("MP2-010.OBL.SCHEMA_VALIDATION")
def test_schema_and_committed_registries_validate(_obligation: str) -> None:
    schema, inventory, profiles, _baseline = _documents()
    baseline_tool._check_schema_definition(schema, schema)
    baseline_tool._internal_validate(inventory, schema)
    baseline_tool._internal_validate(profiles, schema)


@obligation("MP2-010.OBL.BASELINE_INTEGRITY")
def test_inventory_is_exact_projection_of_frozen_baseline(_obligation: str) -> None:
    _schema, inventory, _profiles, baseline = _documents()
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

    rows = inventory["rows"]
    assert [row["id"] for row in rows] == sorted(EXPECTED_ROWS)
    for row in rows:
        pointer, count, digest, profile, limitation_ids = EXPECTED_ROWS[row["id"]]
        source_value = _resolve_pointer(baseline, pointer)
        assert row["source"] == {
            "count": count,
            "digest_sha256": digest,
            "json_pointer": pointer,
            "path": "docs/status/baseline-snapshot.v1.json",
        }
        assert len(source_value) == count
        assert _sha(source_value) == digest
        assert row["profile"] == profile
        assert tuple(row["claim"]["limitation_ids"]) == limitation_ids


@obligation("MP2-010.OBL.ROW_MODEL_POSITIVE")
def test_row_model_accepts_a_typed_retired_row(_obligation: str) -> None:
    schema, inventory, _profiles, _baseline = _documents()
    retired = copy.deepcopy(inventory)
    retired["rows"] = [copy.deepcopy(retired["rows"][0])]
    retired["rows"][0].update({"status": "retired", "owner": "", "profile": "", "test": ""})
    retired["rows_sha256"] = _sha(retired["rows"])
    baseline_tool._internal_validate(retired, schema)


@pytest.mark.parametrize("field", ["owner", "profile", "status", "test"])
@obligation("MP2-010.OBL.ACTIVE_FIELDS_REQUIRED")
def test_active_rows_require_owner_profile_status_and_test(_obligation: str, field: str) -> None:
    schema, inventory, _profiles, _baseline = _documents()
    invalid = copy.deepcopy(inventory)
    invalid["rows"][0][field] = ""
    invalid["rows_sha256"] = _sha(invalid["rows"])
    _rejects(invalid, schema)


@pytest.mark.parametrize("field", ["owner", "status", "test"])
@obligation("MP2-010.OBL.ACTIVE_FIELDS_REQUIRED")
def test_active_profiles_require_owner_status_and_test(_obligation: str, field: str) -> None:
    schema, _inventory, profiles, _baseline = _documents()
    invalid = copy.deepcopy(profiles)
    invalid["profiles"][0][field] = ""
    invalid["profiles_sha256"] = _sha(invalid["profiles"])
    _rejects(invalid, schema)


@obligation("MP2-010.OBL.ROW_MODEL_NEGATIVE")
def test_row_model_rejects_unknown_fields(_obligation: str) -> None:
    schema, inventory, _profiles, _baseline = _documents()
    invalid = copy.deepcopy(inventory)
    invalid["rows"][0]["unreviewed_surface"] = True
    invalid["rows_sha256"] = _sha(invalid["rows"])
    _rejects(invalid, schema)


@obligation("MP2-010.OBL.THREE_RUN_DETERMINISM")
def test_three_run_determinism(_obligation: str) -> None:
    schema, inventory, profiles, _baseline = _documents()
    for document, digest_key, values_key in (
        (inventory, "rows_sha256", "rows"),
        (profiles, "profiles_sha256", "profiles"),
    ):
        projections = [_canonical_bytes(document) for _ in range(3)]
        assert projections[0] == projections[1] == projections[2]
        assert document[digest_key] == _sha(document[values_key])
        baseline_tool._internal_validate(document, schema)


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_profile_references_are_closed(_obligation: str) -> None:
    _schema, inventory, profiles, baseline = _documents()
    profile_rows = profiles["profiles"]
    profile_ids = {row["id"] for row in profile_rows}
    assert [row["id"] for row in profile_rows] == sorted(profile_ids)
    assert {row["profile"] for row in inventory["rows"]} <= profile_ids

    limitation_ids = {row["limitation_id"] for row in baseline["limitations"]}
    for row in [*inventory["rows"], *profile_rows]:
        assert set(row["claim"]["limitation_ids"]) <= limitation_ids
        if row["status"] == "active":
            assert all(row[field].strip() for field in ("owner", "status", "test"))
            if "profile" in row:
                assert row["profile"].strip()

    for row in profile_rows:
        source_value = _resolve_pointer(baseline, row["source"]["json_pointer"])
        assert row["source"]["path"] == "docs/status/baseline-snapshot.v1.json"
        assert row["source"]["digest_sha256"] == _sha(source_value)


@obligation("MP2-010.OBL.TRACE_CLOSURE")
def test_trace_graph_is_closed(_obligation: str) -> None:
    _schema, inventory, profiles, _baseline = _documents()
    traces = (inventory["trace"], profiles["trace"])
    for trace in traces:
        assert trace["task"] == "MP2-010"
        assert trace["issue"] == "MET-71"
        assert trace["materialization_sha256"] == MATERIALIZATION_SHA256
        assert trace["criterion_ids"] == ["MP2-010.A01", "MP2-010.A02"]
        assert tuple(trace["obligation_ids"]) == OBLIGATION_IDS

    validator_ids = {validator for row in inventory["rows"] for validator in row["validator_ids"]}
    assert validator_ids == EXPECTED_VALIDATORS
    for row in inventory["rows"]:
        assert row["owner"] == "MP2-010"
        assert row["consumer_task_ids"]
        assert row["validator_ids"]
        assert row["trace_criterion_ids"] == ["MP2-010.A01", "MP2-010.A02"]


@obligation("MP2-010.OBL.INSTALLED_ENTRY_POINTS")
def test_installed_console_scripts_match_frozen_cli_seed(_obligation: str) -> None:
    _schema, inventory, _profiles, baseline = _documents()
    cli_row = next(row for row in inventory["rows"] if row["kind"] == "cli_root")
    baseline_entries = _resolve_pointer(baseline, cli_row["source"]["json_pointer"])
    expected = {row["command"]: row["entry_point"] for row in baseline_entries}

    distribution = importlib.metadata.distribution("metriplane")
    installed = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts" and entry.name in expected
    }
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert installed == expected
    assert pyproject["project"]["scripts"] == expected


@obligation("MP2-010.OBL.CLEAN")
def test_declared_obligation_set_is_exact(_obligation: str) -> None:
    _schema, inventory, profiles, _baseline = _documents()
    assert tuple(inventory["trace"]["obligation_ids"]) == OBLIGATION_IDS
    assert tuple(profiles["trace"]["obligation_ids"]) == OBLIGATION_IDS
    assert len(OBLIGATION_IDS) == len(set(OBLIGATION_IDS))
