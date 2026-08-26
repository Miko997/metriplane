# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Select and observe exact GitHub Actions attempts for protected-main terminals."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, TypedDict, cast


class ObservationError(ValueError):
    """Provider evidence is malformed and cannot authorize a green result."""


class Obligation(TypedDict):
    id: str
    result: str


class SelectedRun(TypedDict):
    conclusion: str
    head_branch: str
    head_sha: str
    id: int
    key: str
    run_attempt: int
    status: str
    terminal: str
    workflow: str


class Selection(TypedDict):
    conclusion: str
    obligations: list[Obligation]
    ready: bool
    runs: list[SelectedRun]


class Observation(TypedDict):
    conclusion: str
    obligations: list[Obligation]
    ready: bool


REQUIRED_WORKFLOWS = {
    "metriplane": ("Metriplane / required", "CI"),
    "documentation": ("Documentation / required", "Documentation"),
    "security": ("Security / required", "CodeQL"),
}

RUN_STATUSES = frozenset({"completed", "in_progress", "pending", "queued", "requested", "waiting"})
RUN_CONCLUSIONS = frozenset(
    {
        "action_required",
        "cancelled",
        "failure",
        "neutral",
        "skipped",
        "stale",
        "startup_failure",
        "success",
        "timed_out",
    }
)


def _validate_run_result(run: dict[str, Any], *, workflow: str) -> tuple[str, str | None]:
    status = run.get("status")
    conclusion = run.get("conclusion")
    if not isinstance(status, str) or status not in RUN_STATUSES:
        raise ObservationError(f"{workflow}: provider run status is invalid")
    if conclusion is not None and (
        not isinstance(conclusion, str) or conclusion not in RUN_CONCLUSIONS
    ):
        raise ObservationError(f"{workflow}: provider run conclusion is invalid")
    if (status == "completed") != (conclusion is not None):
        raise ObservationError(f"{workflow}: provider run status and conclusion disagree")
    return status, conclusion


def provider_run_order(run: dict[str, Any], *, workflow: str) -> tuple[datetime, int, int]:
    """Return validated provider chronology and exact attempt identity."""
    run_id = run.get("id")
    attempt = run.get("run_attempt")
    updated_at = run.get("updated_at")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise ObservationError(f"{workflow}: provider run ID is invalid")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        raise ObservationError(f"{workflow}: provider run attempt is invalid")
    if not isinstance(updated_at, str):
        raise ObservationError(f"{workflow}: provider run update time is invalid")
    try:
        parsed = datetime.fromisoformat(updated_at)
    except ValueError as exc:
        raise ObservationError(f"{workflow}: provider run update time is invalid") from exc
    if parsed.tzinfo is None:
        raise ObservationError(f"{workflow}: provider run update time has no timezone")
    _validate_run_result(run, workflow=workflow)
    return parsed.astimezone(UTC), run_id, attempt


def select_latest_provider_run(runs: list[dict[str, Any]], *, workflow: str) -> dict[str, Any]:
    """Select one unambiguous latest attempt and reject repeated identities."""
    ordered: list[tuple[datetime, dict[str, Any]]] = []
    identities: set[tuple[int, int]] = set()
    attempts_by_run_id: dict[int, list[tuple[int, datetime]]] = {}
    for run in runs:
        updated_at, run_id, attempt = provider_run_order(run, workflow=workflow)
        identity = (run_id, attempt)
        if identity in identities:
            raise ObservationError(f"{workflow}: provider repeated a run attempt identity")
        identities.add(identity)
        attempts_by_run_id.setdefault(run_id, []).append((attempt, updated_at))
        ordered.append((updated_at, run))
    for attempts in attempts_by_run_id.values():
        attempts.sort()
        for (_lower_attempt, lower_updated_at), (_higher_attempt, higher_updated_at) in pairwise(
            attempts
        ):
            if higher_updated_at <= lower_updated_at:
                raise ObservationError(f"{workflow}: provider run attempt chronology is invalid")
    latest_at = max(updated_at for updated_at, _run in ordered)
    latest = [run for updated_at, run in ordered if updated_at == latest_at]
    if len(latest) != 1:
        raise ObservationError(f"{workflow}: latest provider run chronology is ambiguous")
    return latest[0]


def _governed_provider_runs(
    runs: list[dict[str, Any]], *, workflow: str, sha: str
) -> list[dict[str, Any]]:
    """Return exact push runs plus every attempt sharing their stable run IDs."""
    expected_scope = {
        "event": "push",
        "head_branch": "main",
        "head_sha": sha,
        "name": workflow,
    }
    exact = [
        run
        for run in runs
        if all(run.get(field) == expected for field, expected in expected_scope.items())
    ]
    governed_ids = {
        run_id
        for run in exact
        if isinstance((run_id := run.get("id")), int)
        and not isinstance(run_id, bool)
        and run_id > 0
    }
    governed = [
        run
        for run in runs
        if run in exact
        or (
            isinstance((run_id := run.get("id")), int)
            and not isinstance(run_id, bool)
            and run_id in governed_ids
        )
    ]
    for run in governed:
        for field, expected in expected_scope.items():
            if run.get(field) != expected:
                raise ObservationError(
                    f"{workflow}: provider run field {field!r} does not bind protected main"
                )
    return governed


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"cannot read provider evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ObservationError(f"provider evidence must be an object: {path}")
    return cast(dict[str, Any], value)


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ObservationError(f"cannot read provider evidence {path}: {exc}") from exc
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ObservationError(f"{path}:{line_number}: invalid provider JSON") from exc
        if not isinstance(value, dict):
            raise ObservationError(f"{path}:{line_number}: provider record must be an object")
        values.append(cast(dict[str, Any], value))
    return values


def _selected_run(
    *,
    key: str,
    terminal: str,
    workflow: str,
    provider_run: dict[str, Any],
    sha: str,
) -> SelectedRun:
    required_fields = {
        "id": int,
        "run_attempt": int,
        "status": str,
        "head_branch": str,
        "head_sha": str,
    }
    for field, expected_type in required_fields.items():
        value = provider_run.get(field)
        if not isinstance(value, expected_type) or isinstance(value, bool):
            raise ObservationError(f"{workflow}: provider run field {field!r} is invalid")
    _validate_run_result(provider_run, workflow=workflow)
    if provider_run["head_branch"] != "main" or provider_run["head_sha"] != sha:
        raise ObservationError(f"{workflow}: provider run does not bind exact protected main SHA")
    conclusion = provider_run.get("conclusion")
    if conclusion is not None and not isinstance(conclusion, str):
        raise ObservationError(f"{workflow}: provider run conclusion is invalid")
    return {
        "conclusion": conclusion if isinstance(conclusion, str) else "failure",
        "head_branch": provider_run["head_branch"],
        "head_sha": provider_run["head_sha"],
        "id": provider_run["id"],
        "key": key,
        "run_attempt": provider_run["run_attempt"],
        "status": provider_run["status"],
        "terminal": terminal,
        "workflow": workflow,
    }


def select_runs(
    *,
    workflow_runs: list[dict[str, Any]],
    run_id: int,
    run_attempt: int,
    run_conclusion: str,
    sha: str,
) -> Selection:
    """Select the triggering CI attempt and latest exact documentation/security runs."""
    trigger = {
        "conclusion": run_conclusion,
        "head_branch": "main",
        "head_sha": sha,
        "id": run_id,
        "run_attempt": run_attempt,
        "status": "completed",
    }
    metriplane_terminal, ci_workflow = REQUIRED_WORKFLOWS["metriplane"]
    selected = [
        _selected_run(
            key="metriplane",
            terminal=metriplane_terminal,
            workflow=ci_workflow,
            provider_run=trigger,
            sha=sha,
        )
    ]
    ready = True

    for key in ("documentation", "security"):
        terminal, workflow = REQUIRED_WORKFLOWS[key]
        candidates = _governed_provider_runs(workflow_runs, workflow=workflow, sha=sha)
        if not candidates:
            ready = False
            continue
        latest = select_latest_provider_run(candidates, workflow=workflow)
        run = _selected_run(
            key=key,
            terminal=terminal,
            workflow=workflow,
            provider_run=latest,
            sha=sha,
        )
        selected.append(run)
        if run["status"] != "completed":
            ready = False

    selected_by_terminal = {item["terminal"]: item for item in selected}
    obligations = []
    for terminal, _workflow in REQUIRED_WORKFLOWS.values():
        selected_item = selected_by_terminal.get(terminal)
        result = (
            "success"
            if selected_item is not None and selected_item["conclusion"] == "success"
            else "failure"
        )
        obligations.append(Obligation(id=terminal, result=result))
    conclusion = (
        "success"
        if ready and all(item["result"] == "success" for item in obligations)
        else "failure"
    )
    return {"conclusion": conclusion, "obligations": obligations, "ready": ready, "runs": selected}


def observe_jobs(
    *,
    selection: Selection,
    jobs_by_key: dict[str, list[dict[str, Any]]],
    repository: str,
) -> Observation:
    """Require one exact terminal job from every selected workflow-run attempt."""
    results: dict[str, str] = {}
    ready = selection["ready"]
    for run in selection["runs"]:
        jobs = jobs_by_key.get(run["key"], [])
        exact_jobs = [job for job in jobs if job.get("name") == run["terminal"]]
        if not exact_jobs:
            ready = False
            results[run["terminal"]] = "failure"
            continue
        if len(exact_jobs) != 1:
            results[run["terminal"]] = "failure"
            continue
        job = exact_jobs[0]
        expected_run_url = f"https://api.github.com/repos/{repository}/actions/runs/{run['id']}"
        job_id = job.get("id")
        expected_check_url = (
            f"https://api.github.com/repos/{repository}/check-runs/{job_id}"
            if isinstance(job_id, int) and not isinstance(job_id, bool)
            else None
        )
        provider_exact = (
            job.get("run_id") == run["id"]
            and job.get("run_attempt") == run["run_attempt"]
            and job.get("run_url") == expected_run_url
            and expected_check_url is not None
            and job.get("check_run_url") == expected_check_url
            and job.get("workflow_name") == run["workflow"]
            and job.get("head_branch") == run["head_branch"]
            and job.get("head_sha") == run["head_sha"]
        )
        if job.get("status") != "completed":
            ready = False
        results[run["terminal"]] = (
            "success"
            if provider_exact
            and run["status"] == "completed"
            and run["conclusion"] == "success"
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
            else "failure"
        )

    obligations = [
        Obligation(id=terminal, result=results.get(terminal, "failure"))
        for terminal, _workflow in REQUIRED_WORKFLOWS.values()
    ]
    if len(results) != len(REQUIRED_WORKFLOWS):
        ready = False
    conclusion = (
        "success"
        if ready and all(item["result"] == "success" for item in obligations)
        else "failure"
    )
    return {"conclusion": conclusion, "obligations": obligations, "ready": ready}


def invalidate_selection(selection: Selection) -> Observation:
    """Convert a changed provider selection into valid fail-closed evidence."""
    return {
        "conclusion": "failure",
        "obligations": [
            Obligation(id=terminal, result="failure")
            for terminal, _workflow in REQUIRED_WORKFLOWS.values()
        ],
        "ready": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select")
    select.add_argument("--workflow-runs", type=Path, required=True)
    select.add_argument("--run-id", type=int, required=True)
    select.add_argument("--run-attempt", type=int, required=True)
    select.add_argument("--run-conclusion", required=True)
    select.add_argument("--sha", required=True)

    observe = subparsers.add_parser("observe")
    observe.add_argument("--selection", type=Path, required=True)
    observe.add_argument("--jobs-root", type=Path, required=True)
    observe.add_argument("--repository", required=True)

    invalidate = subparsers.add_parser("invalidate")
    invalidate.add_argument("--selection", type=Path, required=True)
    return parser


def _validate_sha(sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ObservationError("SHA must be 40 lowercase hex digits")


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "select":
            _validate_sha(args.sha)
            result: Selection | Observation = select_runs(
                workflow_runs=_load_json_lines(args.workflow_runs),
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                run_conclusion=args.run_conclusion,
                sha=args.sha,
            )
        elif args.command == "observe":
            selection = cast(Selection, _load_object(args.selection))
            jobs_by_key = {
                key: _load_json_lines(args.jobs_root / f"{key}.jsonl") for key in REQUIRED_WORKFLOWS
            }
            result = observe_jobs(
                selection=selection,
                jobs_by_key=jobs_by_key,
                repository=args.repository,
            )
        else:
            result = invalidate_selection(cast(Selection, _load_object(args.selection)))
    except (KeyError, TypeError, ObservationError) as exc:
        raise SystemExit(f"main-health observation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
