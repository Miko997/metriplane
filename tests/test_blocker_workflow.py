# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_blockers.py"
SCHEMA_PATH = ROOT / "schemas" / "metriplane.blockers.v1.schema.json"
REGISTRY_PATH = ROOT / "docs" / "status" / "blockers.json"
DOC_PATH = ROOT / "docs" / "maintainers" / "blocker-workflow.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-gates.yml"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "metriplane_blocker_checker_under_test", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _registry(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "metriplane.blockers.v1",
        "policy_version": "MP2-006.v1",
        "blockers": blockers,
    }


def _base_blocker(identifier: str = "MPBLK-0001") -> dict[str, Any]:
    return {
        "id": identifier,
        "title": "Synthetic governed blocker",
        "owner": "release-maintainers",
        "reported_by_actor_id": "linear:reporter",
        "opened_at": "2026-08-25T10:00:00Z",
        "initial_severity": "P0",
        "severity": "P0",
        "initial_security": False,
        "security": False,
        "status": "open",
        "source": "synthetic:test",
        "acceptance_ids": ["MP2-006.A01", "MP2-006.A02"],
        "downgrade": None,
        "closure": None,
    }


def _evidence(repo: Path, name: str, kind: str) -> dict[str, str]:
    path = repo / "proof" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{kind}:{name}\n", encoding="utf-8")
    return {
        "path": path.relative_to(repo).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "kind": kind,
        "producer_actor_id": "github:producer",
    }


def _valid_downgrade(repo: Path) -> dict[str, Any]:
    blocker = _base_blocker()
    blocker["severity"] = "P2"
    downgrade = {
        "from_severity": "P0",
        "to_severity": "P2",
        "from_security": False,
        "to_security": False,
        "changed_by_actor_id": "github:author",
        "changed_at": "2026-08-25T11:00:00Z",
        "reproduction_evidence": [_evidence(repo, "reproduction.txt", "reproduction")],
        "control_evidence": [_evidence(repo, "control.txt", "control")],
        "approval": {
            "provider": "github",
            "reviewer_actor_id": "github:independent-reviewer",
            "reviewer_display_name": "Independent Reviewer",
            "approved_at": "2026-08-25T12:00:00Z",
            "decision": "approved",
            "subject_sha256": "0" * 64,
        },
    }
    downgrade["approval"]["subject_sha256"] = tool._sha256(
        tool._downgrade_subject(blocker["id"], downgrade)
    )
    blocker["downgrade"] = downgrade
    return blocker


def _valid_closure(repo: Path) -> dict[str, Any]:
    blocker = _base_blocker()
    blocker["status"] = "closed"
    closure = {
        "closed_by_actor_id": "github:author",
        "closed_at": "2026-08-25T13:00:00Z",
        "resolution_evidence": [_evidence(repo, "resolution.txt", "resolution")],
        "control_evidence": [_evidence(repo, "closure-control.txt", "control")],
        "approval": {
            "provider": "linear",
            "reviewer_actor_id": "linear:independent-reviewer",
            "reviewer_display_name": "Independent Reviewer",
            "approved_at": "2026-08-25T14:00:00Z",
            "decision": "approved",
            "subject_sha256": "0" * 64,
        },
    }
    closure["approval"]["subject_sha256"] = tool._sha256(
        tool._closure_subject(blocker["id"], closure)
    )
    blocker["closure"] = closure
    return blocker


def _run(repo: Path, value: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    registry = repo / "registry.json"
    _write_json(registry, _registry([]) if value is None else value)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = tool.main(
            [
                "--registry",
                str(registry),
                "--schema",
                str(SCHEMA_PATH),
                "--repo-root",
                str(repo),
                "--json",
            ]
        )
    return cast(int, result), cast(dict[str, Any], json.loads(stdout.getvalue()))


def test_production_registry_is_valid_and_nonblocking() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = tool.main(
            [
                "--registry",
                str(REGISTRY_PATH),
                "--schema",
                str(SCHEMA_PATH),
                "--repo-root",
                str(ROOT),
                "--json",
            ]
        )
    report = json.loads(stdout.getvalue())
    assert result == 0
    assert report["valid"] is True
    assert report["release_blocked"] is False
    assert report["blocking_ids"] == []


def test_open_p0_p1_and_security_block_release(tmp_path: Path) -> None:
    cases = [("P0", False), ("P1", False), ("P2", True)]
    for severity, security in cases:
        blocker = _base_blocker()
        blocker["initial_severity"] = severity
        blocker["severity"] = severity
        blocker["initial_security"] = security
        blocker["security"] = security
        result, report = _run(tmp_path, _registry([blocker]))
        assert result == 1
        assert report["valid"] is True
        assert report["blocking_ids"] == ["MPBLK-0001"]


def test_open_p2_nonsecurity_does_not_block_release(tmp_path: Path) -> None:
    blocker = _base_blocker()
    blocker["initial_severity"] = "P2"
    blocker["severity"] = "P2"
    result, report = _run(tmp_path, _registry([blocker]))
    assert result == 0
    assert report["release_blocked"] is False


def test_closed_blocker_requires_resolution_control_and_independent_approval(
    tmp_path: Path,
) -> None:
    missing_closure = _base_blocker()
    missing_closure["status"] = "closed"
    result, report = _run(tmp_path, _registry([missing_closure]))
    assert result == 2
    assert any("closure record" in error for error in report["errors"])

    missing_control = _valid_closure(tmp_path)
    missing_control["closure"]["control_evidence"] = []
    result, _ = _run(tmp_path, _registry([missing_control]))
    assert result == 2

    self_approved = _valid_closure(tmp_path)
    self_approved["closure"]["approval"]["reviewer_actor_id"] = "github:author"
    result, report = _run(tmp_path, _registry([self_approved]))
    assert result == 2
    assert any("independent" in error for error in report["errors"])


def test_valid_synthetic_closure_passes(tmp_path: Path) -> None:
    result, report = _run(tmp_path, _registry([_valid_closure(tmp_path)]))
    assert result == 0
    assert report["valid"] is True


def test_downgrade_requires_reproduction_and_control_evidence(tmp_path: Path) -> None:
    for field in ("reproduction_evidence", "control_evidence"):
        blocker = _valid_downgrade(tmp_path)
        blocker["downgrade"][field] = []
        result, report = _run(tmp_path, _registry([blocker]))
        assert result == 2
        assert report["valid"] is False


def test_downgrade_requires_non_author_approval(tmp_path: Path) -> None:
    for conflicted_actor in ("github:author", "linear:reporter"):
        blocker = _valid_downgrade(tmp_path)
        blocker["downgrade"]["approval"]["reviewer_actor_id"] = conflicted_actor
        result, report = _run(tmp_path, _registry([blocker]))
        assert result == 2
        assert any("independent" in error for error in report["errors"])


def test_valid_synthetic_downgrade_passes(tmp_path: Path) -> None:
    result, report = _run(tmp_path, _registry([_valid_downgrade(tmp_path)]))
    assert result == 0
    assert report["valid"] is True


def test_evidence_paths_fail_closed_on_escape_symlink_and_hash_mismatch(tmp_path: Path) -> None:
    escaped = _valid_downgrade(tmp_path)
    escaped["downgrade"]["reproduction_evidence"][0]["path"] = "../outside.txt"
    result, report = _run(tmp_path, _registry([escaped]))
    assert result == 2
    assert any("repository-relative" in error for error in report["errors"])

    noncanonical = _valid_downgrade(tmp_path)
    original_path = noncanonical["downgrade"]["reproduction_evidence"][0]["path"]
    noncanonical["downgrade"]["reproduction_evidence"][0]["path"] = original_path.replace(
        "/", "//", 1
    )
    result, report = _run(tmp_path, _registry([noncanonical]))
    assert result == 2
    assert any("repository-relative" in error for error in report["errors"])

    linked = _valid_downgrade(tmp_path)
    evidence_path = tmp_path / linked["downgrade"]["reproduction_evidence"][0]["path"]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    evidence_path.unlink()
    evidence_path.symlink_to(outside)
    result, report = _run(tmp_path, _registry([linked]))
    assert result == 2
    assert any("symlink" in error for error in report["errors"])

    mismatched = _valid_downgrade(tmp_path)
    mismatched["downgrade"]["control_evidence"][0]["sha256"] = "f" * 64
    result, report = _run(tmp_path, _registry([mismatched]))
    assert result == 2
    assert any("SHA-256 mismatch" in error for error in report["errors"])


def test_report_is_deterministic_and_machine_readable(tmp_path: Path) -> None:
    blocker = _base_blocker()
    first = _run(tmp_path, _registry([blocker]))
    second = _run(tmp_path, _registry([blocker]))
    assert first == second
    assert first[1]["schema_version"] == "metriplane.blocker-check.v1"
    assert json.dumps(first[1], sort_keys=True, separators=(",", ":"))


def test_schema_checker_docs_trace_and_workflow_are_connected() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    docs = DOC_PATH.read_text(encoding="utf-8")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    checker = TOOL_PATH.read_text(encoding="utf-8")
    assert schema["$id"] in checker
    for acceptance_id in ("MP2-006.A01", "MP2-006.A02"):
        assert acceptance_id in docs
    for path in (
        "schemas/metriplane.blockers.v1.schema.json",
        "docs/status/blockers.json",
        "tools/check_blockers.py",
        "tests/test_blocker_workflow.py",
    ):
        assert path in docs
        assert path in workflow


def test_production_registry_has_no_live_downgrade_or_closure() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert all(blocker["downgrade"] is None for blocker in registry["blockers"])
    assert all(blocker["closure"] is None for blocker in registry["blockers"])


def test_schema_is_closed_and_checker_rejects_unknown_fields(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    for name in ("approval", "blocker", "closure", "downgrade", "evidence"):
        assert schema["$defs"][name]["additionalProperties"] is False
        assert set(schema["$defs"][name]["required"]) == set(schema["$defs"][name]["properties"])
    value = _registry([])
    value["unknown"] = True
    result, report = _run(tmp_path, value)
    assert result == 2
    assert report["valid"] is False


def test_checker_rejects_duplicate_and_unsorted_ids(tmp_path: Path) -> None:
    first = _base_blocker("MPBLK-0002")
    first["initial_severity"] = first["severity"] = "P2"
    second = copy.deepcopy(first)
    second["id"] = "MPBLK-0001"
    result, report = _run(tmp_path, _registry([first, second]))
    assert result == 2
    assert any("sorted" in error for error in report["errors"])

    second["id"] = "MPBLK-0002"
    result, report = _run(tmp_path, _registry([first, second]))
    assert result == 2
    assert any("duplicate" in error for error in report["errors"])


def test_status_transition_must_match_records(tmp_path: Path) -> None:
    closure_without_status = _valid_closure(tmp_path)
    closure_without_status["status"] = "controlled"
    result, report = _run(tmp_path, _registry([closure_without_status]))
    assert result == 2
    assert any("requires closed status" in error for error in report["errors"])

    wrong_transition = _valid_downgrade(tmp_path)
    wrong_transition["downgrade"]["to_severity"] = "P1"
    result, report = _run(tmp_path, _registry([wrong_transition]))
    assert result == 2
    assert any("does not match" in error for error in report["errors"])


def test_criterion_result_evidence_contract_is_exact(tmp_path: Path) -> None:
    clear_result, clear = _run(tmp_path)
    blocked_result, blocked = _run(tmp_path, _registry([_base_blocker()]))
    invalid = _registry([])
    invalid["unknown"] = True
    invalid_result, invalid_report = _run(tmp_path, invalid)
    expected_keys = {
        "schema_version",
        "registry",
        "valid",
        "release_blocked",
        "blocking_ids",
        "error_count",
        "errors",
    }
    assert set(clear) == expected_keys
    assert set(blocked) == expected_keys
    assert set(invalid_report) == expected_keys
    assert (clear_result, blocked_result, invalid_result) == (0, 1, 2)
