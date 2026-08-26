# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.observe_main_health import (
    REQUIRED_WORKFLOWS,
    Selection,
    invalidate_selection,
    observe_jobs,
    select_runs,
)

REPOSITORY = "Miko997/metriplane"
SHA = "a" * 40
CI_RUN_ID = 101
CI_ATTEMPT = 2
RUN_IDS = {"documentation": 102, "security": 103}
WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "main-health.yml"


def _provider_run(key: str, *, attempt: int = 1, **changes: Any) -> dict[str, Any]:
    _terminal, workflow = REQUIRED_WORKFLOWS[key]
    value: dict[str, Any] = {
        "conclusion": "success",
        "event": "push",
        "head_branch": "main",
        "head_sha": SHA,
        "id": RUN_IDS[key],
        "name": workflow,
        "run_attempt": attempt,
        "status": "completed",
    }
    value.update(changes)
    return value


def _selection(runs: list[dict[str, Any]] | None = None, *, ci: str = "success") -> Selection:
    if runs is None:
        runs = [_provider_run("documentation"), _provider_run("security")]
    return select_runs(
        workflow_runs=runs,
        run_id=CI_RUN_ID,
        run_attempt=CI_ATTEMPT,
        run_conclusion=ci,
        sha=SHA,
    )


def _provider_jobs(selection: Selection) -> dict[str, list[dict[str, Any]]]:
    jobs: dict[str, list[dict[str, Any]]] = {}
    for run in selection["runs"]:
        jobs[run["key"]] = [
            {
                "check_run_url": (
                    f"https://api.github.com/repos/{REPOSITORY}/check-runs/{200 + run['id']}"
                ),
                "conclusion": "success",
                "head_branch": "main",
                "head_sha": SHA,
                "id": 200 + run["id"],
                "name": run["terminal"],
                "run_attempt": run["run_attempt"],
                "run_id": run["id"],
                "run_url": (f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run['id']}"),
                "status": "completed",
                "workflow_name": run["workflow"],
            }
        ]
    return jobs


def test_main_health_shell_steps_are_syntax_valid() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            script = step.get("run")
            if script is None or step.get("shell", "bash") != "bash":
                continue
            result = subprocess.run(
                [bash, "-n"],
                input=script,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"{step.get('name')}: {result.stderr}"


def test_exact_provider_attempt_observation_succeeds() -> None:
    selection = _selection()
    assert observe_jobs(
        selection=selection,
        jobs_by_key=_provider_jobs(selection),
        repository=REPOSITORY,
    ) == {
        "conclusion": "success",
        "obligations": [
            {"id": terminal, "result": "success"}
            for terminal, _workflow in REQUIRED_WORKFLOWS.values()
        ],
        "ready": True,
    }


@pytest.mark.parametrize("missing", ("documentation", "security"))
def test_missing_workflow_run_remains_pending_and_fail_closed(missing: str) -> None:
    runs = [_provider_run(key) for key in ("documentation", "security") if key != missing]
    result = _selection(runs)
    assert result["ready"] is False
    assert result["conclusion"] == "failure"


def test_latest_provider_attempt_must_complete() -> None:
    runs = [
        _provider_run("documentation", attempt=1),
        _provider_run("documentation", attempt=2, status="in_progress", conclusion=None),
        _provider_run("security"),
    ]
    result = _selection(runs)
    documentation = next(item for item in result["runs"] if item["key"] == "documentation")
    assert documentation["run_attempt"] == 2
    assert result["ready"] is False
    assert result["conclusion"] == "failure"


def test_failed_workflow_attempt_cannot_be_masked_by_successful_terminal_job() -> None:
    runs = [_provider_run("documentation", conclusion="failure"), _provider_run("security")]
    selection = _selection(runs)
    result = observe_jobs(
        selection=selection,
        jobs_by_key=_provider_jobs(selection),
        repository=REPOSITORY,
    )
    assert result["ready"] is True
    assert result["conclusion"] == "failure"


def test_pending_terminal_job_remains_pending_and_fail_closed() -> None:
    selection = _selection()
    jobs = _provider_jobs(selection)
    jobs["metriplane"][0].update({"status": "in_progress", "conclusion": None})
    result = observe_jobs(selection=selection, jobs_by_key=jobs, repository=REPOSITORY)
    assert result["ready"] is False
    assert result["conclusion"] == "failure"


def test_missing_terminal_job_remains_pending_and_fail_closed() -> None:
    selection = _selection()
    jobs = _provider_jobs(selection)
    jobs["security"] = []
    result = observe_jobs(selection=selection, jobs_by_key=jobs, repository=REPOSITORY)
    assert result["ready"] is False
    assert result["conclusion"] == "failure"


def test_duplicate_runtime_terminal_fails_immediately() -> None:
    selection = _selection()
    jobs = _provider_jobs(selection)
    duplicate = copy.deepcopy(jobs["documentation"][0])
    duplicate["id"] += 1000
    duplicate["check_run_url"] = duplicate["check_run_url"].rsplit("/", 1)[0] + "/9999"
    jobs["documentation"].append(duplicate)
    result = observe_jobs(selection=selection, jobs_by_key=jobs, repository=REPOSITORY)
    assert result["ready"] is True
    assert result["conclusion"] == "failure"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", 999),
        ("run_attempt", 999),
        ("workflow_name", "Dependabot Updates"),
        ("head_branch", "dependabot/pip/ruff"),
        ("head_sha", "b" * 40),
        ("run_url", "https://api.github.com/repos/someone/fork/actions/runs/101"),
        ("check_run_url", "https://api.github.com/repos/someone/fork/check-runs/301"),
        ("check_run_url", f"https://api.github.com/repos/{REPOSITORY}/check-runs/999"),
    ],
)
def test_wrong_job_provider_identity_fails_closed(field: str, value: object) -> None:
    selection = _selection()
    jobs = _provider_jobs(selection)
    jobs["metriplane"][0][field] = value
    result = observe_jobs(selection=selection, jobs_by_key=jobs, repository=REPOSITORY)
    assert result["ready"] is True
    assert result["conclusion"] == "failure"


def test_triggering_ci_attempt_is_bound_exactly() -> None:
    selection = _selection()
    jobs = _provider_jobs(selection)
    jobs["metriplane"][0]["run_attempt"] = CI_ATTEMPT - 1
    result = observe_jobs(selection=selection, jobs_by_key=jobs, repository=REPOSITORY)
    assert result["conclusion"] == "failure"


def test_changed_selection_becomes_structurally_valid_failure() -> None:
    result = invalidate_selection(_selection())
    assert result == {
        "conclusion": "failure",
        "obligations": [
            {"id": terminal, "result": "failure"}
            for terminal, _workflow in REQUIRED_WORKFLOWS.values()
        ],
        "ready": False,
    }
