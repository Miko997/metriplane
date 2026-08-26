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

from tools import main_health_broker as broker

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
APP_INTEGRATION_ID = 4722589
APP_BROKER_RULESET_NAMES = {
    "Protect main",
    "Protect main health admission",
    "Protect main health state",
    "Restrict main health state writers",
    "Restrict main updates to broker",
}
EXACT_INTEGRATIONS = [
    {"context": "Metriplane / required", "integration_id": 15368},
    {"context": "Documentation / required", "integration_id": 15368},
    {"context": "Security / required", "integration_id": 15368},
    {"context": "Main health / required", "integration_id": APP_INTEGRATION_ID},
]
APP_BYPASS = [
    {
        "actor_id": APP_INTEGRATION_ID,
        "actor_type": "Integration",
        "bypass_mode": "always",
    }
]


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


def _run_json_objects(command: list[str]) -> list[dict[str, Any]]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    values: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError("paginated provider item must be a JSON object")
        values.append(value)
    return values


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _status_integrations(ruleset: dict[str, Any]) -> list[dict[str, Any]]:
    status_rules = [
        rule for rule in ruleset.get("rules", []) if rule.get("type") == "required_status_checks"
    ]
    if len(status_rules) != 1:
        raise ValueError(f"{ruleset.get('name')}: expected one required-status-check rule")
    values = status_rules[0].get("parameters", {}).get("required_status_checks")
    if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
        raise ValueError(f"{ruleset.get('name')}: required status checks are malformed")
    return [
        {"context": item.get("context"), "integration_id": item.get("integration_id")}
        for item in values
    ]


def _broker_settings(
    *,
    active_by_name: dict[str, dict[str, Any]],
    captured_at: str,
    default_branch: str,
    repository: str,
    source_digests: dict[str, str],
    supports_queue: bool,
) -> dict[str, Any]:
    core = active_by_name["Protect main"]
    admission = active_by_name["Protect main health admission"]
    state_protection = active_by_name["Protect main health state"]
    main_update = active_by_name["Restrict main updates to broker"]
    state_writer = active_by_name["Restrict main health state writers"]
    core_types = {rule.get("type") for rule in core.get("rules", [])}
    state_types = {rule.get("type") for rule in state_protection.get("rules", [])}
    integrations = _status_integrations(core) + _status_integrations(admission)
    expected_contexts = {item["context"] for item in EXACT_INTEGRATIONS}
    normalized_integrations = [
        observed
        for expected in EXACT_INTEGRATIONS
        for observed in integrations
        if observed["context"] == expected["context"]
    ]
    normalized_integrations.extend(
        sorted(
            (item for item in integrations if item["context"] not in expected_contexts),
            key=lambda item: str(item["context"]),
        )
    )
    governed = (core, admission, state_protection, main_update, state_writer)
    human_bypass_actors = [
        actor
        for ruleset in governed
        for actor in ruleset.get("bypass_actors", [])
        if actor not in APP_BYPASS
    ]
    state_ref = "refs/heads/metriplane-main-health-state"
    default_ref = {"exclude": [], "include": ["~DEFAULT_BRANCH"]}
    expected_rulesets = {
        "Protect main": broker._core_ruleset(),
        "Protect main health admission": broker._admission_ruleset(),
        "Protect main health state": broker._state_protection_ruleset(state_ref.rsplit("/", 1)[1]),
        "Restrict main health state writers": broker._app_update_ruleset(
            name="Restrict main health state writers", include=[state_ref]
        ),
        "Restrict main updates to broker": broker._app_update_ruleset(
            name="Restrict main updates to broker", include=["~DEFAULT_BRANCH"]
        ),
    }
    exact_governed_bodies = all(
        broker._ruleset_view(active_by_name[name]) == expected
        for name, expected in expected_rulesets.items()
    )
    actor_exclusivity = (
        exact_governed_bodies
        and core.get("bypass_actors") == []
        and admission.get("bypass_actors") == []
        and state_protection.get("bypass_actors") == []
        and core.get("conditions", {}).get("ref_name") == default_ref
        and admission.get("conditions", {}).get("ref_name") == default_ref
        and main_update.get("bypass_actors") == APP_BYPASS
        and state_writer.get("bypass_actors") == APP_BYPASS
        and main_update.get("rules") == [{"type": "update"}]
        and state_writer.get("rules") == [{"type": "update"}]
        and main_update.get("conditions", {}).get("ref_name") == default_ref
        and state_writer.get("conditions", {}).get("ref_name")
        == {"exclude": [], "include": [state_ref]}
        and state_protection.get("conditions", {}).get("ref_name")
        == {"exclude": [], "include": [state_ref]}
        and state_types == {"deletion", "non_fast_forward"}
    )
    core_status = next(
        rule for rule in core["rules"] if rule.get("type") == "required_status_checks"
    )
    admission_status = next(
        rule for rule in admission["rules"] if rule.get("type") == "required_status_checks"
    )
    strict = all(
        rule.get("parameters", {}).get("strict_required_status_checks_policy") is True
        for rule in (core_status, admission_status)
    )
    return {
        "activation_state": "active",
        "actor_exclusivity_enforced": actor_exclusivity,
        "broker_integration_id": APP_INTEGRATION_ID,
        "captured_at": captured_at,
        "default_branch": default_branch,
        "deletion_blocked": "deletion" in core_types,
        "human_bypass_actors": human_bypass_actors,
        "merge_queue_enabled": supports_queue,
        "non_fast_forward_blocked": "non_fast_forward" in core_types,
        "pull_request_required": "pull_request" in core_types,
        "repository": repository,
        "required_status_check_integrations": normalized_integrations,
        "required_status_checks": [item["context"] for item in normalized_integrations],
        "ruleset_enforcement": "active",
        "ruleset_id": core["id"],
        "schema_version": 1,
        "source_digests": source_digests,
        "strict_up_to_date": strict,
        "trusted_admin_boundary": True,
    }


def normalize_capture(
    *,
    repository: str,
    captured_at: str,
    repository_payload: dict[str, Any],
    rulesets_payload: list[dict[str, Any]],
    merge_queue_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    default_branch = repository_payload["default_branch"]
    active = [item for item in rulesets_payload if item.get("enforcement") == "active"]
    names = [item.get("name") for item in active]
    if len(names) != len(set(names)):
        raise ValueError("active ruleset names are duplicated")
    active_by_name = {
        str(item["name"]): item for item in active if isinstance(item.get("name"), str)
    }
    broker_names = APP_BROKER_RULESET_NAMES & set(active_by_name)
    broker_specific_names = APP_BROKER_RULESET_NAMES - {"Protect main"}
    if broker_specific_names & broker_names and broker_names != APP_BROKER_RULESET_NAMES:
        raise ValueError("App-broker ruleset activation is partial")
    active_branch = [item for item in active if item.get("target") == "branch"]
    active_branch_names = {
        str(item["name"]) for item in active_branch if isinstance(item.get("name"), str)
    }
    if broker_names == APP_BROKER_RULESET_NAMES and (
        len(active_branch) != len(broker_names) or active_branch_names != broker_names
    ):
        raise ValueError("App-broker active branch-ruleset inventory is not exact")
    default_rulesets = [
        item
        for item in active
        if "~DEFAULT_BRANCH" in item.get("conditions", {}).get("ref_name", {}).get("include", [])
    ]
    queue = merge_queue_payload.get("data", {}).get("repository", {}).get("mergeQueue")
    supports_queue = queue is not None
    if supports_queue:
        selected_mode = "enforced_merge_queue"
    elif broker_names == APP_BROKER_RULESET_NAMES:
        selected_mode = "app_brokered_strict_up_to_date"
    else:
        if len(default_rulesets) != 1:
            raise ValueError(
                f"expected one legacy active default-branch ruleset, found {len(default_rulesets)}"
            )
        selected_mode = "serialized_strict_up_to_date"
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

    if selected_mode == "app_brokered_strict_up_to_date":
        return capability, _broker_settings(
            active_by_name=active_by_name,
            captured_at=captured_at,
            default_branch=default_branch,
            repository=repository,
            source_digests=source_digests,
            supports_queue=supports_queue,
        )

    if len(default_rulesets) != 1:
        raise ValueError("merge-queue capture requires one active default-branch ruleset")
    ruleset = default_rulesets[0]
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
    ruleset_summaries = _run_json_objects(
        [
            str(gh),
            "api",
            "--paginate",
            f"repos/{repository}/rulesets?includes_parents=true&per_page=100",
            "--jq",
            ".[]",
        ]
    )
    rulesets_payload: list[dict[str, Any]] = []
    for item in ruleset_summaries:
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
