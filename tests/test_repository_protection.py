# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.baseline_snapshot import _internal_validate
from tools.capture_repository_protection import normalize_capture
from tools.check_repository_protection import (
    ProtectionError,
    validate_capture,
    validate_merge_proof,
)

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "status"
SHA = "a" * 40
HEAD = "b" * 40


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _capture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    policy = _read(STATUS / "repository-protection-policy.json")
    capability = _read(STATUS / "examples" / "repository-protection-capability.json")
    settings = _read(STATUS / "examples" / "repository-protection-settings.json")
    return policy, capability, settings


def test_limited_mode_capture_validates_without_actor_exclusivity_claim() -> None:
    policy, capability, settings = _capture()
    result = validate_capture(policy, capability, settings)
    assert result["selected_mode"] == "serialized_strict_up_to_date"
    assert policy["claims_actor_exclusivity"] is False
    assert settings["actor_exclusivity_enforced"] is False
    capability["repository"] = "attacker/foreign"
    settings["repository"] = "attacker/foreign"
    with pytest.raises(ProtectionError, match="repositories differ"):
        validate_capture(policy, capability, settings)


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("capability", "selected_mode", "enforced_merge_queue"),
        ("settings", "strict_up_to_date", False),
        ("settings", "required_status_checks", ["Metriplane / required"]),
        ("policy", "claims_actor_exclusivity", True),
    ],
)
def test_capture_drift_fails_closed(target: str, key: str, value: object) -> None:
    policy, capability, settings = _capture()
    values = {"policy": policy, "capability": capability, "settings": settings}
    values[target][key] = value
    with pytest.raises(ProtectionError):
        validate_capture(policy, capability, settings)


def test_normalization_is_deterministic_and_selects_available_mode() -> None:
    repository = {"default_branch": "main"}
    ruleset = {
        "id": 1,
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [{"context": "required"}],
                },
            },
        ],
    }
    queue = {"data": {"repository": {"mergeQueue": None}}}
    first = normalize_capture(
        repository="owner/repo",
        captured_at="2026-08-25T00:00:00Z",
        repository_payload=repository,
        rulesets_payload=[ruleset],
        merge_queue_payload=queue,
    )
    second = normalize_capture(
        repository="owner/repo",
        captured_at="2026-08-25T00:00:00Z",
        repository_payload=copy.deepcopy(repository),
        rulesets_payload=[copy.deepcopy(ruleset)],
        merge_queue_payload=copy.deepcopy(queue),
    )
    assert first == second
    assert first[0]["selected_mode"] == "serialized_strict_up_to_date"


def _merge_proof() -> tuple[dict[str, object], ...]:
    pr = {
        "head": {"sha": HEAD},
        "merge_commit_sha": SHA,
        "merged": True,
        "state": "closed",
    }
    head = {"sha": HEAD, "commit": {"tree": {"sha": "f" * 40}}}
    commit = {
        "sha": SHA,
        "parents": [{"sha": "c" * 40}, {"sha": HEAD}],
        "commit": {"tree": {"sha": "f" * 40}},
    }
    checks = {
        "check_runs": [
            {
                "id": run_id,
                "name": name,
                "head_sha": HEAD,
                "status": "completed",
                "conclusion": "success",
                "completed_at": "2026-08-25T00:00:00Z",
            }
            for run_id, name in enumerate(
                [
                    "Metriplane / required",
                    "Documentation / required",
                    "Security / required",
                    "Main health / required",
                ],
                start=1,
            )
        ]
    }
    main = {"object": {"sha": SHA}}
    return pr, head, commit, checks, main


def test_real_merge_proof_requires_exact_current_sha_and_success() -> None:
    pr, head, commit, checks, main = _merge_proof()
    result = validate_merge_proof(
        policy=_capture()[0],
        pull_request=pr,
        head_commit=head,
        merge_commit=commit,
        check_runs=checks,
        main_ref=main,
    )
    assert result["verdict"] == "PASS"
    head["commit"]["tree"]["sha"] = "0" * 40
    with pytest.raises(ProtectionError, match="tree differs"):
        validate_merge_proof(
            policy=_capture()[0],
            pull_request=pr,
            head_commit=head,
            merge_commit=commit,
            check_runs=checks,
            main_ref=main,
        )


@pytest.mark.parametrize("failure", ["missing", "cancelled", "skipped", "stale", "wrong-main"])
def test_merge_proof_faults_fail_closed(failure: str) -> None:
    pr, head, commit, checks, main = _merge_proof()
    if failure == "missing":
        checks["check_runs"].pop()
    elif failure in {"cancelled", "skipped"}:
        checks["check_runs"][0]["conclusion"] = failure
    elif failure == "stale":
        checks["check_runs"][0]["head_sha"] = "d" * 40
    else:
        main["object"]["sha"] = "e" * 40
    with pytest.raises(ProtectionError):
        validate_merge_proof(
            policy=_capture()[0],
            pull_request=pr,
            head_commit=head,
            merge_commit=commit,
            check_runs=checks,
            main_ref=main,
        )


def test_schema_and_example_families_are_complete_json() -> None:
    names = {"repository-protection-capability", "repository-protection-settings"}
    for name in names:
        schema = _read(STATUS / "schemas" / f"{name}.schema.json")
        example = _read(STATUS / "examples" / f"{name}.json")
        assert schema["$schema"].endswith("2020-12/schema")
        assert set(schema["required"]) == set(example)
        _internal_validate(example, schema)
