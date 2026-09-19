# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from tools.cross_adapter_gate import (
    RESULT_SCHEMA_VERSION,
    GateError,
    _bind_root_build_info,
    _canonical_root_build_info,
    _component_matrix,
    _expected_result_keys,
    _fixture_matrix,
    _run_command,
    _validate_result_semantics,
    _validate_result_shape,
    _verify_root_wheel_build_info,
    load_registry,
    summarize,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
REQUIRES_JSONSCHEMA = pytest.mark.skipif(
    importlib.util.find_spec("jsonschema") is None,
    reason="result-schema tests run in the locked cross-adapter gate environment",
)


def test_root_build_info_binding_is_exact_and_fail_closed(tmp_path: Path) -> None:
    destination = tmp_path / "metriplane" / "build-info.json"
    destination.parent.mkdir()
    unbound = (
        b'{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        b'"source_dirty":null,"source_tree":null,"status":"unbound"}'
    )
    destination.write_bytes(unbound)

    _bind_root_build_info(tmp_path, "a" * 40, "b" * 40)

    assert destination.read_bytes() == (
        b'{"schema_version":"metriplane.build-info.v1","source_commit":"'
        + (b"a" * 40)
        + b'","source_dirty":false,"source_tree":"'
        + (b"b" * 40)
        + b'","status":"bound"}'
    )

    for source_sha, source_tree, placeholder, error in (
        ("invalid", "b" * 40, unbound, "identity is malformed"),
        ("a" * 40, "invalid", unbound, "identity is malformed"),
        ("a" * 40, "b" * 40, b"{}", "placeholder is not canonical and unbound"),
    ):
        destination.write_bytes(placeholder)
        with pytest.raises(GateError, match=error):
            _bind_root_build_info(tmp_path, source_sha, source_tree)


def test_root_wheel_build_info_verification_rejects_every_identity_drift(
    tmp_path: Path,
) -> None:
    source_sha = "a" * 40
    source_tree = "b" * 40
    expected = _canonical_root_build_info(source_sha, source_tree)

    def write_wheel(name: str, records: list[bytes]) -> Path:
        path = tmp_path / name
        with zipfile.ZipFile(path, mode="w") as archive:
            for record in records:
                archive.writestr("metriplane/build-info.json", record)
        return path

    valid = write_wheel("valid.whl", [expected])
    with zipfile.ZipFile(valid) as archive:
        _verify_root_wheel_build_info(archive, source_sha, source_tree)

    invalid = {
        "missing.whl": [],
        "malformed.whl": [b"{}"],
        "wrong-commit.whl": [_canonical_root_build_info("c" * 40, source_tree)],
        "wrong-tree.whl": [_canonical_root_build_info(source_sha, "d" * 40)],
    }
    for name, records in invalid.items():
        path = write_wheel(name, records)
        with zipfile.ZipFile(path) as archive, pytest.raises(GateError):
            _verify_root_wheel_build_info(archive, source_sha, source_tree)

    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicate = write_wheel("duplicate.whl", [expected, expected])
    with (
        zipfile.ZipFile(duplicate) as archive,
        pytest.raises(GateError, match="exactly one build-info"),
    ):
        _verify_root_wheel_build_info(archive, source_sha, source_tree)


def _commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _needs(*, result: str = "success", level: str = "pr") -> str:
    return json.dumps(
        {
            "registry": {"result": result, "outputs": {"level": level}},
            "sdk": {"result": "success"},
            "adapters": {"result": "success"},
            "fixtures": {"result": "success"},
            "shared-contract": {"result": "success"},
            "root-wheel": {"result": "success"},
        }
    )


def _record(
    component_id: str,
    os_name: str,
    python: str,
    *,
    commit: str,
    level: str = "pr",
) -> dict[str, Any]:
    registry = load_registry(REPOSITORY_ROOT)
    adapters = {item["component_id"]: item for item in registry["adapters"]}
    variants = {
        variant["variant_id"]: {**variant, "adapter_id": family["adapter_id"]}
        for family in registry["fixtures"]
        for variant in family["variants"]
    }
    if component_id == "source-adapter-sdk":
        component_type = "shared_infrastructure"
    elif component_id in adapters:
        component_type = "source_adapter"
    elif component_id in variants:
        component_type = "portable_fixture"
    elif component_id == "root-wheel-clean-room":
        component_type = "root_wheel"
    else:
        component_type = "shared_contract"
    adapter_id = None
    if component_type == "source_adapter":
        adapter_id = adapters[component_id]["adapter_id"]
    elif component_type == "portable_fixture":
        adapter_id = variants[component_id]["adapter_id"]
    record: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "repository_commit": commit,
        "component_id": component_id,
        "adapter_id": adapter_id,
        "component_type": component_type,
        "package_name": "metriplane",
        "package_version": None,
        "python_version": f"{python}.0",
        "operating_system": os_name,
        "level": level,
        "commands": [{"command": "test command", "exit_code": 0, "duration_seconds": 0.0}],
        "tests": {"collected": 1, "passed": 1, "skipped": 0, "skip_reasons": []},
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
        "contract_result": "pass",
        "determinism_result": "pass",
        "negative_tests_result": "pass",
        "source_provenance_identities": {},
        "package_content_result": "not_applicable",
        "rights_result": "not_applicable",
        "privacy_result": "not_applicable",
        "duration_seconds": 0.0,
        "final_result": "pass",
    }
    if component_type in {"shared_infrastructure", "source_adapter"}:
        component = (
            adapters[component_id]
            if component_type == "source_adapter"
            else registry["shared_infrastructure"][0]
        )
        record["package_name"] = component["package_name"]
        record["package_version"] = component["package_version"]
        record["package_content_result"] = "pass"
        record["rights_result"] = "pass"
        record["privacy_result"] = "pass"
    if component_type == "source_adapter":
        local = isinstance(adapters[component_id]["source_fixture_path"], str)
        conversion_supported = python in adapters[component_id]["source_conversion_python_versions"]
        record["conversion_equivalence"] = (
            "pass" if local and conversion_supported else "not_executed"
        )
        if python not in adapters[component_id]["full_suite_python_versions"]:
            record["tests"] = {
                "collected": 0,
                "passed": 0,
                "skipped": 0,
                "skip_reasons": ["full source suite is not registered for this Python version"],
            }
            record["contract_result"] = "not_applicable"
            record["determinism_result"] = "not_applicable"
            record["negative_tests_result"] = "not_applicable"
    if component_type == "portable_fixture":
        variant = variants[component_id]
        expected = variant["expected"]
        record["tests"] = {"collected": 0, "passed": 0, "skipped": 0, "skip_reasons": []}
        record["fixture_variants"] = [component_id]
        record["normalized_frame_counts"] = {component_id: expected["frame_count"]}
        record["event_counts"] = {component_id: len(expected["events"])}
        record["deviation_counts"] = {component_id: expected["deviation_count"]}
        record["incident_counts"] = {component_id: expected["incident_count"]}
        record["incident_bundle_presence"] = {
            component_id: expected["evidence_bundle"] == "produced"
        }
        record["bundle_verification"] = {component_id: expected["bundle_verification"]}
        record["regression_presence"] = {
            component_id: expected["generated_regression"] == "produced"
        }
        record["regression_execution"] = {component_id: expected["regression_execution"]}
        record["conversion_equivalence"] = "pass"
        record["atlas_equivalence"] = "pass"
        record["negative_tests_result"] = "not_applicable"
        record["rights_result"] = "pass"
        record["privacy_result"] = "pass"
    if component_type == "shared_contract":
        record["rights_result"] = "pass"
        record["privacy_result"] = "pass"
    if component_type == "root_wheel":
        record["tests"] = {"collected": 0, "passed": 0, "skipped": 0, "skip_reasons": []}
        record["fixture_variants"] = sorted(variants)
        for variant_id, variant in variants.items():
            expected = variant["expected"]
            record["normalized_frame_counts"][variant_id] = expected["frame_count"]
            record["event_counts"][variant_id] = len(expected["events"])
            record["deviation_counts"][variant_id] = expected["deviation_count"]
            record["incident_counts"][variant_id] = expected["incident_count"]
            record["incident_bundle_presence"][variant_id] = (
                expected["evidence_bundle"] == "produced"
            )
            record["bundle_verification"][variant_id] = expected["bundle_verification"]
            record["regression_presence"][variant_id] = (
                expected["generated_regression"] == "produced"
            )
            record["regression_execution"][variant_id] = expected["regression_execution"]
        record["atlas_equivalence"] = "pass"
        record["contract_result"] = "pass"
        record["determinism_result"] = "not_applicable"
        record["negative_tests_result"] = "not_applicable"
        record["package_content_result"] = "pass"
        record["rights_result"] = "pass"
        record["privacy_result"] = "pass"
    return record


def _write_complete_results(root: Path, *, commit: str, level: str = "pr") -> list[Path]:
    registry = load_registry(REPOSITORY_ROOT)
    paths = []
    for index, (component_id, os_name, python) in enumerate(
        sorted(_expected_result_keys(registry, level))
    ):
        record = _record(
            component_id,
            os_name,
            python,
            commit=commit,
            level=level,
        )
        path = root / f"{index:03d}-{component_id}-{os_name}-py{python}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        paths.append(path)
    return paths


def test_pr_and_exhaustive_matrices_have_exact_registry_cardinality() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    adapter_rows = _component_matrix(registry, "adapters", "exhaustive")["include"]
    maniskill_rows = [row for row in adapter_rows if row["component_id"] == "maniskill-pickcube"]
    exhaustive_keys = _expected_result_keys(registry, "exhaustive")

    assert maniskill_rows == [
        {
            "component_id": "maniskill-pickcube",
            "python_version": "3.12",
            "os": "ubuntu-latest",
        }
    ]
    assert ("root-wheel-clean-room", "linux", "3.13") in exhaustive_keys
    assert ("root-wheel-clean-room", "macos", "3.13") in exhaustive_keys
    assert len(_expected_result_keys(registry, "pr")) == 16
    assert len(exhaustive_keys) == 52
    assert len(_fixture_matrix(registry, "pr")["include"]) == 9
    assert len(_fixture_matrix(registry, "exhaustive")["include"]) == 36


@REQUIRES_JSONSCHEMA
def test_result_shape_rejects_missing_or_extra_fields() -> None:
    record = _record("minimal-baseline", "linux", "3.12", commit=_commit())
    _validate_result_shape(record)

    missing = dict(record)
    del missing["final_result"]
    with pytest.raises(ValueError, match="result fields differ"):
        _validate_result_shape(missing)

    extra = {**record, "unreviewed": True}
    with pytest.raises(ValueError, match="result fields differ"):
        _validate_result_shape(extra)


@REQUIRES_JSONSCHEMA
def test_result_schema_and_semantics_reject_vacuous_pass_records() -> None:
    record = _record("minimal-baseline", "linux", "3.12", commit=_commit())
    invalid_count = json.loads(json.dumps(record))
    invalid_count["tests"]["collected"] = -1
    with pytest.raises(ValueError, match="rejected"):
        _validate_result_shape(invalid_count)

    vacuous = json.loads(json.dumps(record))
    vacuous["commands"] = []
    vacuous["contract_result"] = "not_applicable"
    with pytest.raises(ValueError, match="requires at least one successful command"):
        _validate_result_semantics(REPOSITORY_ROOT, vacuous)


@REQUIRES_JSONSCHEMA
def test_package_only_python_result_cannot_claim_unexecuted_contract_evidence() -> None:
    record = _record("massrobotics-amr", "linux", "3.13", commit=_commit())
    _validate_result_shape(record)
    _validate_result_semantics(REPOSITORY_ROOT, record)

    overstated = json.loads(json.dumps(record))
    overstated["contract_result"] = "pass"
    with pytest.raises(ValueError, match="must mark contract_result N/A"):
        _validate_result_semantics(REPOSITORY_ROOT, overstated)


@pytest.mark.parametrize(
    "temporary_root",
    ["/tmp/cross-adapter-test", "/private/var/folders/cross-adapter-test"],
)
def test_command_redaction_preserves_shell_structure(temporary_root: str) -> None:
    command = f"true {temporary_root}/one; true {temporary_root}/two"
    record, _ = _run_command(command, cwd=REPOSITORY_ROOT)

    assert record["command"] == "true <temp>; true <temp>"


@REQUIRES_JSONSCHEMA
def test_summary_accepts_only_the_complete_exact_commit_result_set(tmp_path: Path) -> None:
    commit = _commit()
    results = tmp_path / "nested" / "results"
    results.mkdir(parents=True)
    _write_complete_results(results, commit=commit)
    markdown = tmp_path / "summary.md"

    summary = summarize(
        REPOSITORY_ROOT,
        tmp_path,
        expected_commit=commit,
        needs_json=_needs(),
        summary_markdown=markdown,
    )

    assert summary["result"] == "pass"
    assert summary["record_count"] == 16
    assert summary["adapter_count"] == 4
    assert summary["fixture_variant_count"] == 9
    text = markdown.read_text(encoding="utf-8")
    assert commit in text
    assert "minimal-baseline" in text


@REQUIRES_JSONSCHEMA
@pytest.mark.parametrize(
    "status",
    ["failure", "cancelled", "skipped", "neutral", "timed_out", "missing"],
)
def test_summary_rejects_every_non_success_job_result(tmp_path: Path, status: str) -> None:
    commit = _commit()
    _write_complete_results(tmp_path, commit=commit)

    with pytest.raises(ValueError, match="required jobs did not succeed"):
        summarize(
            REPOSITORY_ROOT,
            tmp_path,
            expected_commit=commit,
            needs_json=_needs(result=status),
            summary_markdown=None,
        )


@REQUIRES_JSONSCHEMA
def test_summary_rejects_a_missing_required_job(tmp_path: Path) -> None:
    commit = _commit()
    _write_complete_results(tmp_path, commit=commit)
    needs = json.loads(_needs())
    del needs["fixtures"]

    with pytest.raises(ValueError, match="required job set mismatch"):
        summarize(
            REPOSITORY_ROOT,
            tmp_path,
            expected_commit=commit,
            needs_json=json.dumps(needs),
            summary_markdown=None,
        )


@REQUIRES_JSONSCHEMA
def test_summary_rejects_missing_stale_duplicate_and_failed_records(tmp_path: Path) -> None:
    commit = _commit()
    paths = _write_complete_results(tmp_path, commit=commit)
    paths[0].unlink()
    with pytest.raises(ValueError, match="machine result set mismatch"):
        summarize(
            REPOSITORY_ROOT,
            tmp_path,
            expected_commit=commit,
            needs_json=_needs(),
            summary_markdown=None,
        )

    paths = _write_complete_results(tmp_path, commit=commit)
    stale = json.loads(paths[0].read_text(encoding="utf-8"))
    stale["repository_commit"] = "0" * 40
    paths[0].write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="stale result commit"):
        summarize(
            REPOSITORY_ROOT,
            tmp_path,
            expected_commit=commit,
            needs_json=_needs(),
            summary_markdown=None,
        )

    stale["repository_commit"] = commit
    stale["final_result"] = "fail"
    paths[0].write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(ValueError, match="failed result record"):
        summarize(
            REPOSITORY_ROOT,
            tmp_path,
            expected_commit=commit,
            needs_json=_needs(),
            summary_markdown=None,
        )
