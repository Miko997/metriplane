# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate an aggregate required terminal without accepting partial success."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SUCCESS = "success"


class TerminalValidationError(ValueError):
    """The aggregate cannot truthfully report success."""


def validate_terminal(
    *,
    terminal: str,
    expected_sha: str,
    expected_dependencies: list[str],
    results: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Return a deterministic success record or raise on any mismatch."""
    if len(expected_dependencies) != len(set(expected_dependencies)):
        raise TerminalValidationError("expected dependencies contain duplicates")
    expected = set(expected_dependencies)
    actual = set(results)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise TerminalValidationError(
            f"dependency set mismatch; missing={missing!r}; extra={extra!r}"
        )
    failures: list[str] = []
    for name in expected_dependencies:
        result = results[name]
        if set(result) != {"result", "sha"}:
            failures.append(f"{name}: invalid result shape")
            continue
        if result["sha"] != expected_sha:
            failures.append(f"{name}: wrong SHA {result['sha']!r}, expected {expected_sha!r}")
        if result["result"] != SUCCESS:
            failures.append(f"{name}: result is {result['result']!r}, expected success")
    if failures:
        raise TerminalValidationError("; ".join(failures))
    return {
        "dependencies": expected_dependencies,
        "result": SUCCESS,
        "schema_version": 1,
        "sha": expected_sha,
        "terminal": terminal,
    }


def validate_policy(path: Path, workflow_root: Path) -> dict[str, Any]:
    """Validate sole producers and the future Release handoff."""
    try:
        import yaml
    except ImportError as exc:
        raise TerminalValidationError("policy validation requires PyYAML") from exc

    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise TerminalValidationError("terminal policy must be a JSON object")
    terminals = policy["terminals"]
    expected_names = {
        "Metriplane / required",
        "Documentation / required",
        "Security / required",
        "Main health / required",
        "Release / required",
    }
    expected_active_producers = {
        "Metriplane / required": ".github/workflows/ci.yml",
        "Documentation / required": ".github/workflows/docs.yml",
        "Security / required": ".github/workflows/codeql.yml",
        "Main health / required": "github-app:metriplane-main-health-publisher",
    }
    if {item["name"] for item in terminals} != expected_names:
        raise TerminalValidationError("terminal inventory is incomplete or contains extras")

    workflow_job_names: dict[str, list[str]] = {}
    workflow_paths = sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")))
    for workflow_path in workflow_paths:
        try:
            document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TerminalValidationError(f"{workflow_path.name}: invalid workflow YAML") from exc
        if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
            raise TerminalValidationError(f"{workflow_path.name}: workflow jobs must be an object")
        workflow_job_names[workflow_path.name] = [
            job["name"]
            for job in document["jobs"].values()
            if isinstance(job, dict) and isinstance(job.get("name"), str)
        ]
    for workflow_name, job_names in workflow_job_names.items():
        for job_name in job_names:
            if "${{" not in job_name:
                continue
            expression_start = job_name.find("${{")
            expression_end = job_name.rfind("}}")
            if expression_end < expression_start:
                raise TerminalValidationError(f"{workflow_name}: malformed dynamic job name")
            prefix = job_name[:expression_start]
            suffix = job_name[expression_end + 2 :]
            ambiguous = [
                name
                for name in expected_names
                if name.startswith(prefix)
                and name.endswith(suffix)
                and len(name) >= len(prefix) + len(suffix)
            ]
            if ambiguous:
                raise TerminalValidationError(
                    f"{workflow_name}: dynamic job name may produce protected terminal(s) "
                    f"{ambiguous!r}"
                )
    for terminal in terminals:
        producers = [
            name for name, job_names in workflow_job_names.items() if terminal["name"] in job_names
        ]
        if terminal["state"] == "active":
            producer = terminal["producer"]
            expected_producer = expected_active_producers.get(terminal["name"])
            if expected_producer is None:
                raise TerminalValidationError("Release / required must remain reserved")
            if terminal["owner"] != "MP2-004" or producer != expected_producer:
                raise TerminalValidationError(
                    f"{terminal['name']}: owner or producer is not the governed MP2-004 value"
                )
            if producer == "github-app:metriplane-main-health-publisher":
                expected_producers: list[str] = []
            else:
                assert isinstance(producer, str)
                expected_producers = [Path(producer).name]
            if producers != expected_producers:
                raise TerminalValidationError(
                    f"{terminal['name']}: expected sole producer {producer!r}, found {producers!r}"
                )
        elif terminal["state"] == "reserved":
            if terminal["name"] != "Release / required":
                raise TerminalValidationError("only Release / required may be reserved")
            if terminal["owner"] != "MP2-007" or producers:
                raise TerminalValidationError(
                    "Release / required must be producer-free and reserved for MP2-007"
                )
        else:
            raise TerminalValidationError(f"{terminal['name']}: terminal state is invalid")
    return dict(policy)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--terminal", required=True)
    aggregate.add_argument("--expected-sha", required=True)
    aggregate.add_argument("--expected-dependency", action="append", default=[])
    aggregate.add_argument("--results-json", required=True)

    policy = subparsers.add_parser("policy")
    policy.add_argument("--policy", type=Path, required=True)
    policy.add_argument("--workflow-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.command == "aggregate":
            result = validate_terminal(
                terminal=args.terminal,
                expected_sha=args.expected_sha,
                expected_dependencies=args.expected_dependency,
                results=json.loads(args.results_json),
            )
        else:
            result = validate_policy(args.policy, args.workflow_root)
    except (KeyError, TypeError, json.JSONDecodeError, TerminalValidationError) as exc:
        raise SystemExit(f"required terminal validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
