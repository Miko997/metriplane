# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from tools.check_required_terminal import (
    TerminalValidationError,
    validate_policy,
    validate_terminal,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "status" / "required-terminals.json"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA = "a" * 40


def _results() -> dict[str, dict[str, str]]:
    return {
        "linux": {"result": "success", "sha": SHA},
        "macos": {"result": "success", "sha": SHA},
    }


def test_exact_aggregate_succeeds() -> None:
    result = validate_terminal(
        terminal="Metriplane / required",
        expected_sha=SHA,
        expected_dependencies=["linux", "macos"],
        results=_results(),
    )
    assert result["result"] == "success"
    assert result["sha"] == SHA


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "stale"])
def test_non_success_dependency_fails_closed(conclusion: str) -> None:
    results = _results()
    results["linux"]["result"] = conclusion
    with pytest.raises(TerminalValidationError, match="expected success"):
        validate_terminal(
            terminal="Metriplane / required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=results,
        )


def test_missing_extra_and_wrong_sha_fail_closed() -> None:
    missing = _results()
    missing.pop("linux")
    with pytest.raises(TerminalValidationError, match="dependency set mismatch"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=missing,
        )
    extra = _results() | {"windows": {"result": "success", "sha": SHA}}
    with pytest.raises(TerminalValidationError, match="dependency set mismatch"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=extra,
        )
    wrong_sha = _results()
    wrong_sha["macos"]["sha"] = "b" * 40
    with pytest.raises(TerminalValidationError, match="wrong SHA"):
        validate_terminal(
            terminal="required",
            expected_sha=SHA,
            expected_dependencies=["linux", "macos"],
            results=wrong_sha,
        )


def test_terminal_inventory_has_four_sole_producers_and_release_handoff() -> None:
    policy = validate_policy(POLICY, WORKFLOWS)
    active = [item for item in policy["terminals"] if item["state"] == "active"]
    reserved = [item for item in policy["terminals"] if item["state"] == "reserved"]
    assert [item["name"] for item in active] == [
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
    ]
    assert reserved == [
        {
            "name": "Release / required",
            "owner": "MP2-007",
            "producer": None,
            "state": "reserved",
        }
    ]


def test_duplicate_or_premature_producer_is_rejected(tmp_path: Path) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    for terminal in policy["terminals"]:
        if terminal["producer"]:
            source = ROOT / terminal["producer"]
            shutil.copyfile(source, workflow_root / source.name)
    duplicate = workflow_root / "duplicate.yml"
    duplicate.write_text("name: duplicate\n# Metriplane / required\n", encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="sole producer"):
        validate_policy(POLICY, workflow_root)
    duplicate.write_text("name: early\n# Release / required\n", encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="producer-free"):
        validate_policy(POLICY, workflow_root)


def test_workflows_have_always_run_exact_aggregate_jobs() -> None:
    expected = {
        "ci.yml": "Metriplane / required",
        "docs.yml": "Documentation / required",
        "codeql.yml": "Security / required",
        "main-health.yml": "Main health / required",
    }
    for filename, terminal in expected.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        producers = [job for job in jobs.values() if job.get("name") == terminal]
        assert len(producers) == 1
        assert "always()" in str(producers[0].get("if", "")) or filename == "main-health.yml"
        aggregate = str(producers[0])
        assert "outputs.source_sha" in aggregate or "outputs.measured_sha" in aggregate

    docs = yaml.safe_load((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    trigger = docs.get("on", docs.get(True))
    assert trigger["pull_request"] is None
    assert "paths" not in trigger["push"]

    health = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    health_trigger = health.get("on", health.get(True))
    assert "edited" in health_trigger["pull_request"]["types"]
    assert health["jobs"]["candidate-health"]["permissions"] == {"contents": "read"}
    assert health["jobs"]["scheduled-deep"]["permissions"] == {"contents": "read"}
    assert health["jobs"]["persist-health"]["permissions"] == {"contents": "write"}
    assert "stop_the_line.py ingest" not in "\n".join(
        step.get("run", "") for step in health["jobs"]["candidate-health"]["steps"]
    )
    writer = "\n".join(step.get("run", "") for step in health["jobs"]["persist-health"]["steps"])
    assert "stop_the_line.py ingest" in writer
    assert "git rev-parse origin/main" in writer
    assert "stop_the_line.py candidate" in "\n".join(
        step.get("run", "") for step in health["jobs"]["candidate-health"]["steps"]
    )
    assert health["jobs"]["persist-health"]["needs"] == "scheduled-deep"

    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    ci_trigger = ci.get("on", ci.get(True))
    assert "edited" in ci_trigger["pull_request"]["types"]
    for job_name in ("test", "macos-regressions", "linux-python313"):
        assert ci["jobs"][job_name]["outputs"]["source_sha"]
    assert "metriplane-main-health-state" in (WORKFLOWS / "main-health.yml").read_text(
        encoding="utf-8"
    )


def test_policy_validation_does_not_mutate_input() -> None:
    before = json.loads(POLICY.read_text(encoding="utf-8"))
    snapshot = copy.deepcopy(before)
    validate_policy(POLICY, WORKFLOWS)
    assert before == snapshot
