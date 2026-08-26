# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tools import capture_repository_protection as capture_tool
from tools import main_health_broker as broker
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


def test_app_broker_mode_is_truthfully_planned_until_live_activation() -> None:
    policy, capability, settings = _capture()
    result = validate_capture(policy, capability, settings)
    assert result["selected_mode"] == "app_brokered_strict_up_to_date"
    assert result["verdict"] == "PLANNED"
    assert policy["claims_actor_exclusivity"] is True
    assert settings["actor_exclusivity_enforced"] is True
    assert settings["human_bypass_actors"] == []
    capability["repository"] = "attacker/foreign"
    settings["repository"] = "attacker/foreign"
    with pytest.raises(ProtectionError, match="repositories differ"):
        validate_capture(policy, capability, settings)


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("capability", "selected_mode", "serialized_strict_up_to_date"),
        ("settings", "strict_up_to_date", False),
        ("settings", "required_status_checks", ["Metriplane / required"]),
        ("policy", "claims_actor_exclusivity", False),
        ("settings", "broker_integration_id", 999),
        ("settings", "human_bypass_actors", [{"actor_id": 5}]),
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
    assert first[1]["actor_exclusivity_enforced"] is False


def test_paginated_ruleset_capture_parses_every_provider_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout='{"id":1}\n{"id":2}\n',
        stderr="",
    )
    monkeypatch.setattr(capture_tool.subprocess, "run", lambda *_args, **_kwargs: completed)
    assert capture_tool._run_json_objects(["gh"]) == [{"id": 1}, {"id": 2}]


def test_normalization_recognizes_exact_five_ruleset_broker() -> None:
    state_branch = "metriplane-main-health-state"
    rulesets = [
        {"id": 1, **broker._core_ruleset()},
        {"id": 2, **broker._admission_ruleset()},
        {
            "id": 3,
            **broker._app_update_ruleset(
                name="Restrict main updates to broker", include=["~DEFAULT_BRANCH"]
            ),
        },
        {"id": 4, **broker._state_protection_ruleset(state_branch)},
        {
            "id": 5,
            **broker._app_update_ruleset(
                name="Restrict main health state writers",
                include=[f"refs/heads/{state_branch}"],
            ),
        },
    ]
    capability, settings = normalize_capture(
        repository="Miko997/metriplane",
        captured_at="2026-08-26T12:00:00Z",
        repository_payload={"default_branch": "main"},
        rulesets_payload=rulesets,
        merge_queue_payload={"data": {"repository": {"mergeQueue": None}}},
    )
    assert capability["selected_mode"] == "app_brokered_strict_up_to_date"
    assert settings["activation_state"] == "active"
    assert settings["actor_exclusivity_enforced"] is True
    assert settings["required_status_check_integrations"] == [
        {"context": "Metriplane / required", "integration_id": 15368},
        {"context": "Documentation / required", "integration_id": 15368},
        {"context": "Security / required", "integration_id": 15368},
        {"context": "Main health / required", "integration_id": 4722589},
    ]
    assert validate_capture(_capture()[0], capability, settings)["verdict"] == "PASS"

    drifted = copy.deepcopy(rulesets)
    drifted[0]["rules"].append({"type": "required_linear_history"})
    _capability, drifted_settings = normalize_capture(
        repository="Miko997/metriplane",
        captured_at="2026-08-26T12:00:00Z",
        repository_payload={"default_branch": "main"},
        rulesets_payload=drifted,
        merge_queue_payload={"data": {"repository": {"mergeQueue": None}}},
    )
    assert drifted_settings["actor_exclusivity_enforced"] is False

    partial = rulesets[:-1]
    with pytest.raises(ValueError, match="activation is partial"):
        normalize_capture(
            repository="Miko997/metriplane",
            captured_at="2026-08-26T12:00:00Z",
            repository_payload={"default_branch": "main"},
            rulesets_payload=partial,
            merge_queue_payload={"data": {"repository": {"mergeQueue": None}}},
        )

    extra = [
        *rulesets,
        {"enforcement": "active", "id": 6, "name": "Unexpected", "target": "branch"},
    ]
    with pytest.raises(ValueError, match="inventory is not exact"):
        normalize_capture(
            repository="Miko997/metriplane",
            captured_at="2026-08-26T12:00:00Z",
            repository_payload={"default_branch": "main"},
            rulesets_payload=extra,
            merge_queue_payload={"data": {"repository": {"mergeQueue": None}}},
        )


def _merge_proof() -> tuple[dict[str, object], ...]:
    base = "c" * 40
    pr = {
        "base": {"ref": "main", "sha": base},
        "head": {"repo": {"full_name": "Miko997/metriplane"}, "sha": HEAD},
        "merge_commit_sha": SHA,
        "merged": True,
        "state": "closed",
    }
    head = {"sha": HEAD, "commit": {"tree": {"sha": "f" * 40}}}
    commit = {
        "sha": SHA,
        "parents": [{"sha": base}, {"sha": HEAD}],
        "commit": {"tree": {"sha": "f" * 40}},
    }
    integrations = {
        "Metriplane / required": 15368,
        "Documentation / required": 15368,
        "Security / required": 15368,
        "Main health / required": 4722589,
    }
    checks = {
        "check_runs": [
            {
                "app": {"id": integrations[name]},
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


@pytest.mark.parametrize(
    "failure", ["missing", "cancelled", "skipped", "stale", "wrong-integration", "wrong-main"]
)
def test_merge_proof_faults_fail_closed(failure: str) -> None:
    pr, head, commit, checks, main = _merge_proof()
    if failure == "missing":
        checks["check_runs"].pop()
    elif failure in {"cancelled", "skipped"}:
        checks["check_runs"][0]["conclusion"] = failure
    elif failure == "stale":
        checks["check_runs"][0]["head_sha"] = "d" * 40
    elif failure == "wrong-integration":
        checks["check_runs"][0]["app"]["id"] = 999
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
        assert set(schema["required"]) <= set(example)
        _internal_validate(example, schema)
