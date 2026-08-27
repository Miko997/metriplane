# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.check_required_terminal import (
    TerminalValidationError,
    validate_policy,
    validate_terminal,
)
from tools.observe_main_health import REQUIRED_WORKFLOWS

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "status" / "required-terminals.json"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA = "a" * 40


def _results() -> dict[str, dict[str, str]]:
    return {
        "linux": {"result": "success", "sha": SHA},
        "macos": {"result": "success", "sha": SHA},
    }


def _copy_workflow_producers(policy: dict[str, Any], workflow_root: Path) -> None:
    for terminal in policy["terminals"]:
        producers = [terminal.get("producer")]
        transition = terminal.get("transition")
        if isinstance(transition, dict):
            producers.append(transition.get("producer"))
        for producer in producers:
            if isinstance(producer, str) and producer.startswith(".github/workflows/"):
                source = ROOT / producer
                shutil.copyfile(source, workflow_root / source.name)


def test_exact_aggregate_succeeds() -> None:
    result = validate_terminal(
        terminal="Metriplane / required",
        expected_sha=SHA,
        expected_dependencies=["linux", "macos"],
        results=_results(),
    )
    assert result["result"] == "success"
    assert result["sha"] == SHA


def test_aggregate_cli_has_no_third_party_import_requirement() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "tools" / "check_required_terminal.py"),
            "aggregate",
            "--terminal",
            "Metriplane / required",
            "--expected-sha",
            SHA,
            "--expected-dependency",
            "linux",
            "--expected-dependency",
            "macos",
            "--results-json",
            json.dumps(_results()),
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


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


def test_terminal_inventory_has_app_owned_main_health_and_release_handoff() -> None:
    policy = validate_policy(POLICY, WORKFLOWS)
    active = [item for item in policy["terminals"] if item["state"] == "active"]
    reserved = [item for item in policy["terminals"] if item["state"] == "reserved"]
    assert [item["name"] for item in active] == [
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
    ]
    assert active[-1]["producer"] == "github-app:metriplane-main-health-publisher"
    assert "transition" not in active[-1]
    assert reserved == [
        {
            "name": "Release / required",
            "owner": "MP2-007",
            "producer": None,
            "state": "reserved",
        }
    ]


def test_terminal_inventory_rejects_a_substituted_app_producer(tmp_path: Path) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    main_health = next(
        item for item in policy["terminals"] if item["name"] == "Main health / required"
    )
    main_health["producer"] = "github-app:substituted-publisher"
    changed = tmp_path / "required-terminals.json"
    changed.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="governed MP2-004"):
        validate_policy(changed, WORKFLOWS)


def test_terminal_inventory_rejects_retired_transition_metadata(tmp_path: Path) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    main_health = next(
        item for item in policy["terminals"] if item["name"] == "Main health / required"
    )
    main_health["transition"] = {
        "actions_integration_id": 15368,
        "approval_variable": "MET77_APPROVED_HEAD_SHA",
        "base_sha": "9d5b4ffa5236521423196a84acc6a613f7f13108",
        "producer": ".github/workflows/main-health.yml",
        "pull_request": 86,
    }
    changed = tmp_path / "required-terminals.json"
    changed.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(TerminalValidationError, match="transition is not permitted"):
        validate_policy(changed, WORKFLOWS)


@pytest.mark.parametrize("suffix", (".yml", ".yaml"))
def test_duplicate_or_premature_producer_is_rejected(tmp_path: Path, suffix: str) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    _copy_workflow_producers(policy, workflow_root)
    duplicate = workflow_root / f"duplicate{suffix}"
    duplicate.write_text(
        "name: duplicate\njobs:\n  required:\n    name: Main health / required\n",
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="sole producer"):
        validate_policy(POLICY, workflow_root)
    duplicate.write_text(
        "name: early\njobs:\n  required:\n    name: Release / required\n",
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="producer-free"):
        validate_policy(POLICY, workflow_root)


@pytest.mark.parametrize(
    "job_name",
    (
        "    name: ${{ matrix.terminal }}\n",
        "    name: >-\n      ${{\n        matrix.terminal\n      }}\n",
        "    name: \"${{ contains('x}}', 'x') && matrix.terminal }}\"\n",
    ),
)
def test_dynamic_job_name_that_can_render_a_terminal_is_rejected(
    tmp_path: Path, job_name: str
) -> None:
    workflow_root = tmp_path / "workflows"
    workflow_root.mkdir()
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    _copy_workflow_producers(policy, workflow_root)
    (workflow_root / "dynamic.yaml").write_text(
        "name: dynamic\njobs:\n  required:\n" + job_name,
        encoding="utf-8",
    )
    with pytest.raises(TerminalValidationError, match="dynamic job name"):
        validate_policy(POLICY, workflow_root)


def test_actions_have_three_canonical_aggregates_and_no_main_health_terminal() -> None:
    expected = {
        "ci.yml": "Metriplane / required",
        "docs.yml": "Documentation / required",
        "codeql.yml": "Security / required",
    }
    for filename, terminal in expected.items():
        workflow = yaml.safe_load((WORKFLOWS / filename).read_text(encoding="utf-8"))
        producers = [job for job in workflow["jobs"].values() if job.get("name") == terminal]
        assert len(producers) == 1
        assert "always()" in str(producers[0].get("if", ""))
        assert "outputs.source_sha" in str(producers[0])

    main_health_producers: list[str] = []
    for workflow_path in WORKFLOWS.glob("*.y*ml"):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if any(
            job.get("name") == "Main health / required" for job in workflow.get("jobs", {}).values()
        ):
            main_health_producers.append(workflow_path.name)
    assert main_health_producers == []

    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    ci_trigger = ci.get("on", ci.get(True))
    assert ci_trigger["push"] == {"branches": ["main"]}

    docs = yaml.safe_load((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    trigger = docs.get("on", docs.get(True))
    assert trigger["pull_request"] is None
    assert "paths" not in trigger["push"]
    assert REQUIRED_WORKFLOWS == {
        "metriplane": ("Metriplane / required", "CI"),
        "documentation": ("Documentation / required", "Documentation"),
        "security": ("Security / required", "CodeQL"),
    }


def test_main_health_workflow_is_read_only_deep_observation() -> None:
    workflow_path = WORKFLOWS / "main-health.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    trigger = workflow.get("on", workflow.get(True))
    assert trigger == {
        "repository_dispatch": {"types": ["main-health-nightly", "main-health-weekly"]},
        "schedule": [{"cron": "23 3 * * 1-6"}, {"cron": "23 3 * * 0"}],
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "main-health-deep",
        "queue": "max",
        "cancel-in-progress": False,
    }
    assert set(workflow["jobs"]) == {"nightly", "weekly"}
    assert {workflow["jobs"][name]["name"] for name in ("nightly", "weekly")} == {
        "Main health deep / nightly",
        "Main health deep / weekly",
    }
    for name in ("nightly", "weekly"):
        job = workflow["jobs"][name]
        checkout = job["steps"][0]
        assert checkout["with"] == {
            "fetch-depth": 0,
            "persist-credentials": False,
            "ref": "${{ github.sha }}",
        }
        assert job["steps"][1] == {
            "name": "Verify exact provider SHA",
            "run": 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"',
        }
        assert job["timeout-minutes"] == 60
    text = workflow_path.read_text(encoding="utf-8")
    assert "Main health / required" not in text
    assert "check_met77_transition.py" not in text
    assert "PR_BODY" not in text
    assert "PR_TITLE" not in text
    assert "Independent exact-SHA review" not in text
    assert "MAIN_HEALTH_APP_PRIVATE_KEY" not in text
    assert "create-github-app-token" not in text
    assert "checks: write" not in text
    assert not (WORKFLOWS / "main-health-lease.yml").exists()


@pytest.mark.skipif(shutil.which("bash") is None, reason="Main Health runs on Bash runners")
def test_main_health_shell_steps_are_valid_bash() -> None:
    workflow = yaml.safe_load((WORKFLOWS / "main-health.yml").read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            script = step.get("run")
            if script is None:
                continue
            completed = subprocess.run(
                ["bash", "-n"],
                input=script,
                check=False,
                capture_output=True,
                text=True,
            )
            assert completed.returncode == 0, completed.stderr


def test_policy_validation_does_not_mutate_input() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    original = copy.deepcopy(policy)
    validate_policy(POLICY, WORKFLOWS)
    assert policy == original
