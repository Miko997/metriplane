# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Capture hosted repository capabilities separately from protection settings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _run_json(command: list[str]) -> dict[str, Any] | list[Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, (dict, list)):
        raise TypeError("provider response must be a JSON object or array")
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def normalize_capture(
    *,
    repository: str,
    captured_at: str,
    repository_payload: dict[str, Any],
    rulesets_payload: list[dict[str, Any]],
    merge_queue_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    default_branch = repository_payload["default_branch"]
    active = [
        item
        for item in rulesets_payload
        if item.get("enforcement") == "active"
        and "~DEFAULT_BRANCH" in item.get("conditions", {}).get("ref_name", {}).get("include", [])
    ]
    if len(active) != 1:
        raise ValueError(f"expected one active default-branch ruleset, found {len(active)}")
    ruleset = active[0]
    queue = merge_queue_payload.get("data", {}).get("repository", {}).get("mergeQueue")
    supports_queue = queue is not None
    selected_mode = "enforced_merge_queue" if supports_queue else "serialized_strict_up_to_date"
    source_digests = {
        "merge_queue": _sha(merge_queue_payload),
        "repository": _sha(repository_payload),
        "rulesets": _sha(rulesets_payload),
    }
    capability = {
        "captured_at": captured_at,
        "default_branch": default_branch,
        "repository": repository,
        "schema_version": 1,
        "selected_mode": selected_mode,
        "source_digests": source_digests,
        "supports_merge_queue": supports_queue,
    }

    rule_types = {rule["type"] for rule in ruleset.get("rules", [])}
    status_rule = next(
        (rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"),
        None,
    )
    if status_rule is None:
        raise ValueError("active ruleset lacks required status checks")
    parameters = status_rule["parameters"]
    settings = {
        # Rulesets can constrain refs without proving an exclusive human actor.
        "actor_exclusivity_enforced": False,
        "captured_at": captured_at,
        "default_branch": default_branch,
        "deletion_blocked": "deletion" in rule_types,
        "merge_queue_enabled": supports_queue,
        "non_fast_forward_blocked": "non_fast_forward" in rule_types,
        "pull_request_required": "pull_request" in rule_types,
        "repository": repository,
        "required_status_checks": sorted(
            item["context"] for item in parameters["required_status_checks"]
        ),
        "ruleset_enforcement": ruleset["enforcement"],
        "ruleset_id": ruleset["id"],
        "schema_version": 1,
        "source_digests": source_digests,
        "strict_up_to_date": parameters["strict_required_status_checks_policy"],
    }
    return capability, settings


def capture(repository: str, captured_at: str, gh: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be owner/name")
    owner, name = repository.split("/", 1)
    query = (
        "query="
        f'query {{ repository(owner:"{owner}", name:"{name}") '
        "{ mergeQueue { id url } } }"
    )
    repository_payload = _run_json([str(gh), "api", f"repos/{repository}"])
    ruleset_summaries = _run_json([str(gh), "api", f"repos/{repository}/rulesets"])
    if not isinstance(ruleset_summaries, list):
        raise TypeError("ruleset listing must be a JSON array")
    rulesets_payload: list[dict[str, Any]] = []
    for item in ruleset_summaries:
        if not isinstance(item, dict):
            raise TypeError("ruleset summary must be a JSON object")
        detail = _run_json([str(gh), "api", f"repos/{repository}/rulesets/{item['id']}"])
        if not isinstance(detail, dict):
            raise TypeError("ruleset detail must be a JSON object")
        rulesets_payload.append(detail)
    merge_queue_payload = _run_json(
        [
            str(gh),
            "api",
            "graphql",
            "-f",
            query,
        ]
    )
    assert isinstance(repository_payload, dict)
    assert isinstance(merge_queue_payload, dict)
    return normalize_capture(
        repository=repository,
        captured_at=captured_at,
        repository_payload=repository_payload,
        rulesets_payload=rulesets_payload,
        merge_queue_payload=merge_queue_payload,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--gh", type=Path, default=Path("/usr/bin/gh"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    capability, settings = capture(args.repository, args.captured_at, args.gh)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "repository-protection-capability.json": capability,
        "repository-protection-settings.json": settings,
    }
    for name, value in outputs.items():
        path = args.output_dir / name
        path.write_bytes(_canonical(value))
        if hashlib.sha256(path.read_bytes()).hexdigest() != _sha(value):
            raise SystemExit(f"capture read-back failed: {path}")
    print(json.dumps({name: _sha(value) for name, value in outputs.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
