# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Offline validation for hosted protection captures and real merge proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXACT_TERMINALS = [
    "Metriplane / required",
    "Documentation / required",
    "Security / required",
    "Main health / required",
]


class ProtectionError(ValueError):
    """Captured protection or merge evidence is incomplete or contradictory."""


def validate_capture(
    policy: dict[str, Any],
    capability: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    if (
        capability["repository"] != settings["repository"]
        or capability["repository"] != policy["repository"]
    ):
        raise ProtectionError("capability, settings, and policy repositories differ")
    if capability["source_digests"] != settings["source_digests"]:
        raise ProtectionError("capability and settings do not share one capture")
    if capability["captured_at"] != settings["captured_at"]:
        raise ProtectionError("capability and settings capture times differ")
    mode = capability["selected_mode"]
    expected_mode = (
        "enforced_merge_queue"
        if capability["supports_merge_queue"]
        else "serialized_strict_up_to_date"
    )
    if mode != expected_mode or mode != policy["selected_mode"]:
        raise ProtectionError("selected mode contradicts captured capability or policy")
    if settings["ruleset_enforcement"] != "active":
        raise ProtectionError("default-branch ruleset is not active")
    for field in (
        "deletion_blocked",
        "non_fast_forward_blocked",
        "pull_request_required",
        "strict_up_to_date",
    ):
        if settings[field] is not True:
            raise ProtectionError(f"required protection is disabled: {field}")
    if mode == "serialized_strict_up_to_date" and (
        policy["claims_actor_exclusivity"] or settings["actor_exclusivity_enforced"]
    ):
        raise ProtectionError("limited mode cannot claim actor-exclusive merge or tags")
    if policy["required_terminals"] != EXACT_TERMINALS:
        raise ProtectionError("policy terminal set is not the exact MP2-004 set")
    if sorted(settings["required_status_checks"]) != sorted(policy["required_terminals"]):
        raise ProtectionError("hosted required checks are not the exact MP2-004 terminal set")
    return {
        "captured_at": capability["captured_at"],
        "repository": capability["repository"],
        "schema_version": 1,
        "selected_mode": mode,
        "verdict": "PASS",
    }


def validate_merge_proof(
    *,
    policy: dict[str, Any],
    pull_request: dict[str, Any],
    head_commit: dict[str, Any],
    merge_commit: dict[str, Any],
    check_runs: dict[str, Any],
    main_ref: dict[str, Any],
) -> dict[str, Any]:
    required_checks = policy["required_terminals"]
    if required_checks != EXACT_TERMINALS:
        raise ProtectionError("merge proof policy does not name the exact MP2-004 terminals")
    merge_sha = pull_request["merge_commit_sha"]
    head_sha = pull_request["head"]["sha"]
    if pull_request["merged"] is not True or pull_request["state"] != "closed":
        raise ProtectionError("pull request was not merged")
    if merge_commit["sha"] != merge_sha or main_ref["object"]["sha"] != merge_sha:
        raise ProtectionError("merge proof does not bind current main")
    raw_parents = merge_commit.get("parents", merge_commit["commit"].get("parents"))
    parents = [parent["sha"] if isinstance(parent, dict) else parent for parent in raw_parents]
    if len(parents) != 2 or parents[1] != head_sha:
        raise ProtectionError("merge commit does not bind the reviewed head")
    if head_commit["sha"] != head_sha:
        raise ProtectionError("reviewed head commit identity is wrong")
    merge_tree = merge_commit["commit"]["tree"]
    merge_tree_sha = merge_tree["sha"] if isinstance(merge_tree, dict) else merge_tree
    if head_commit["commit"]["tree"]["sha"] != merge_tree_sha:
        raise ProtectionError("merge commit tree differs from the reviewed head tree")
    if not required_checks or len(required_checks) != len(set(required_checks)):
        raise ProtectionError("required check inventory is empty or duplicated")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for run in check_runs["check_runs"]:
        by_name.setdefault(run["name"], []).append(run)
    for name in required_checks:
        runs = by_name.get(name, [])
        matching = [run for run in runs if run["head_sha"] == head_sha]
        if not matching:
            raise ProtectionError(f"{name}: missing or stale check")
        run = max(matching, key=lambda item: (item.get("completed_at") or "", item["id"]))
        if run["status"] != "completed" or run["conclusion"] != "success":
            raise ProtectionError(f"{name}: non-success conclusion {run['conclusion']!r}")
    return {
        "head_sha": head_sha,
        "merge_sha": merge_sha,
        "required_checks": required_checks,
        "schema_version": 1,
        "verdict": "PASS",
    }


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProtectionError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    for name in ("policy", "capability", "settings"):
        capture.add_argument(f"--{name}", type=Path, required=True)

    merge = subparsers.add_parser("merge-proof")
    merge.add_argument("--policy", type=Path, required=True)
    merge.add_argument("--pull-request", type=Path, required=True)
    merge.add_argument("--head-commit", type=Path, required=True)
    merge.add_argument("--merge-commit", type=Path, required=True)
    merge.add_argument("--check-runs", type=Path, required=True)
    merge.add_argument("--main-ref", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            result = validate_capture(
                _read(args.policy), _read(args.capability), _read(args.settings)
            )
        else:
            result = validate_merge_proof(
                policy=_read(args.policy),
                pull_request=_read(args.pull_request),
                head_commit=_read(args.head_commit),
                merge_commit=_read(args.merge_commit),
                check_runs=_read(args.check_runs),
                main_ref=_read(args.main_ref),
            )
    except (KeyError, TypeError, json.JSONDecodeError, ProtectionError) as exc:
        raise SystemExit(f"repository protection validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
