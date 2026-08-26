# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.release_control import (
    MILESTONES,
    STAGES,
    ReleaseControlError,
    acquire_promotion_lock,
    advance_attempt,
    append_cas_event,
    build_promotion_plan,
    candidate_identity,
    finalize_cells,
    make_record,
    new_attempt,
    read_json,
    reconcile_publication,
    record_target_burn,
    recovery_envelope,
    require_lock_owner,
    resolve_burn_with_patch,
    retain_two_store_evidence,
    sha256_json,
    tool_main,
    validate_approval,
    validate_cumulative_milestones,
    validate_lkg_invalidation,
    validate_predecessor,
    validate_promotion_plan,
    validate_role_assignments,
    validate_task_state_observation,
    write_immutable_json,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "release"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
SCENARIO_REGISTRY = json.loads(
    (ROOT / "docs/status/release-scenarios.json").read_text(encoding="utf-8")
)
SCENARIOS = SCENARIO_REGISTRY["scenarios"]


def _fixture(relative: str) -> dict[str, object]:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def _test_signature(actor_id: str, subject_digest: str) -> dict[str, object]:
    return {
        "actor_id": actor_id,
        "algorithm": "test-sha256-v1",
        "provider": "test-fixture",
        "signature": sha256_json({"actor_id": actor_id, "subject_digest": subject_digest}),
        "subject_digest": subject_digest,
        "synthetic": True,
    }


def test_mp2_007_a01_cumulative_release_system() -> None:
    validate_cumulative_milestones(MILESTONES)
    with pytest.raises(ReleaseControlError, match="cumulative"):
        validate_cumulative_milestones(MILESTONES[:-1])

    for milestone in MILESTONES:
        attempt = new_attempt(
            milestone=milestone,
            version=f"{milestone}.0",
            candidate_digest=DIGEST_A,
            predecessor_digest=DIGEST_B,
        )
        for stage in STAGES:
            attempt = advance_attempt(attempt, stage=stage, result="PASS", evidence_digest=DIGEST_A)
        assert [event["stage"] for event in attempt["events"]] == list(STAGES)


def test_mp2_007_a02_signed_roles_and_task_state() -> None:
    roles = _fixture("valid/synthetic-role-assignments.json")
    actors = validate_role_assignments(roles, live=False)
    assert actors["authorized_executor_id"] == "fixture-executor"
    with pytest.raises(ReleaseControlError, match="synthetic role"):
        validate_role_assignments(roles, live=True)
    assert _fixture("valid/fake-linear-snapshot.json")["data"] == {
        "state": "In Progress",
        "task_id": "MET-154",
        "tool": "fake-linear",
    }
    task_data = {
        "assignee_id": "fixture-executor",
        "issue_id": "MET-154",
        "state": "In Progress",
        "task_id": "MP2-007",
    }
    task_digest = sha256_json(task_data)
    task_state = make_record(
        "release-task-state-observation",
        task_data,
        invocation_id="fixture-task-state-001",
        sequence=1,
        synthetic=True,
        signatures=[_test_signature("fixture-executor", task_digest)],
    )
    validate_task_state_observation(task_state, actors, live=False)
    with pytest.raises(ReleaseControlError, match="synthetic task state"):
        validate_task_state_observation(task_state, actors, live=True)


def test_mp2_007_a03_tag_independent_staging() -> None:
    attempt = new_attempt(
        milestone="v0.4",
        version="v0.4.0",
        candidate_digest=DIGEST_A,
        predecessor_digest=DIGEST_B,
    )
    assert "tag" not in attempt
    unauthorized = _fixture("invalid/unauthorized-tag.json")
    assert unauthorized["tag_is_authority"] is True
    assert sha256_json(attempt) == sha256_json(dict(reversed(list(attempt.items()))))


def test_mp2_007_a04_target_burn_and_patch_resolution() -> None:
    burn = record_target_burn(
        target="pypi",
        milestone="v0.4",
        version="v0.4.0",
        reason="name occupied with mismatched bytes",
        observation_digest=DIGEST_A,
    )
    resolution = resolve_burn_with_patch(burn, "v0.4.1")
    assert resolution["resolution"] == "NEW_PATCH_REQUIRED"
    with pytest.raises(ReleaseControlError, match="new patch"):
        resolve_burn_with_patch(burn, "v0.4.0")
    with pytest.raises(ReleaseControlError, match="same milestone"):
        resolve_burn_with_patch(burn, "v0.5.0")


def test_mp2_007_a05_actual_predecessor_resolution() -> None:
    predecessor = _fixture("valid/v0.3.0-predecessor.json")
    validate_predecessor(predecessor, first_milestone=True)
    changed = dict(predecessor)
    changed["data"] = dict(predecessor["data"], version="v0.2.0")
    changed["payload_digest"] = sha256_json(changed["data"])
    unsigned = dict(changed)
    del unsigned["record_id"]
    changed["record_id"] = sha256_json(unsigned)
    with pytest.raises(ReleaseControlError, match="actual v0.3.0"):
        validate_predecessor(changed, first_milestone=True)


def test_mp2_007_a06_build_once_candidate_identity() -> None:
    first = candidate_identity(
        source_digest=DIGEST_A,
        artifacts={"metriplane.whl": DIGEST_A, "metriplane.tar.gz": DIGEST_B},
        build_invocation_id="build-once-001",
    )
    second = candidate_identity(
        source_digest=DIGEST_A,
        artifacts={"metriplane.tar.gz": DIGEST_B, "metriplane.whl": DIGEST_A},
        build_invocation_id="build-once-001",
    )
    assert first == second
    rebuilt = candidate_identity(
        source_digest=DIGEST_A,
        artifacts={"metriplane.whl": DIGEST_A, "metriplane.tar.gz": DIGEST_B},
        build_invocation_id="build-twice-002",
    )
    assert rebuilt["candidate_digest"] != first["candidate_digest"]


def test_mp2_007_a07_terminal_matrix_two_store_index(tmp_path: Path) -> None:
    environment_registry = json.loads(
        (ROOT / "docs/status/supported-environments.json").read_text(encoding="utf-8")
    )
    required_cells = [row["id"] for row in environment_registry["environments"] if row["required"]]
    cells = finalize_cells(
        required_cells,
        {cell: {"evidence_digest": DIGEST_A, "result": "PASS"} for cell in required_cells},
    )
    assert cells["ready"] is True
    record = make_record(
        "release-qualification",
        {"cells": [item["cell"] for item in cells["cells"]]},
        invocation_id="two-store-001",
        sequence=1,
        synthetic=True,
    )
    receipt = retain_two_store_evidence(
        record,
        store_a=tmp_path / "a",
        store_b=tmp_path / "b",
        index_journal=tmp_path / "index",
        expected_index_epoch=0,
    )
    assert len(receipt["receipts"]) == 2
    assert receipt["index"]["epoch"] == 1
    reconstructed = retain_two_store_evidence(
        record,
        store_a=tmp_path / "a",
        store_b=tmp_path / "b",
        index_journal=tmp_path / "index",
        expected_index_epoch=0,
    )
    assert reconstructed == receipt


def test_mp2_007_a08_non_author_approval_boundary() -> None:
    role_record = _fixture("valid/synthetic-role-assignments.json")
    roles = validate_role_assignments(role_record, live=False)
    approval = _fixture("valid/synthetic-approval.json")
    validate_approval(approval, roles, live=False)
    with pytest.raises(ReleaseControlError, match="synthetic approval"):
        validate_approval(approval, roles, live=True)
    self_approved = _fixture("invalid/self-approved-live.json")
    live_roles = dict(roles, author_id="fixture-author", non_author_reviewer_id="fixture-reviewer")
    with pytest.raises(ReleaseControlError, match="non-author"):
        validate_approval(self_approved, live_roles, live=True)
    with pytest.raises(SystemExit, match="synthetic role"):
        tool_main(
            "validate_release_role_assignments.py",
            [
                "--input",
                str(FIXTURES / "valid/synthetic-role-assignments.json"),
                "--mode",
                "live",
            ],
        )


def test_mp2_007_a09_fenced_promotion_lock_and_recovery(tmp_path: Path) -> None:
    plan = build_promotion_plan(
        candidate_digest=DIGEST_A,
        approval_digest=DIGEST_B,
        controls_digest=DIGEST_A,
        target_state_digest=DIGEST_B,
        attempt_index_epoch=7,
        publisher_id="publisher-a",
        publisher_actions=["publish-testpypi", "publish-pypi"],
        expires_at=200,
    )
    validate_promotion_plan(
        plan,
        now=100,
        candidate_digest=DIGEST_A,
        approval_digest=DIGEST_B,
        publisher_id="publisher-a",
    )
    with pytest.raises(ReleaseControlError, match="expired"):
        validate_promotion_plan(
            plan,
            now=200,
            candidate_digest=DIGEST_A,
            approval_digest=DIGEST_B,
            publisher_id="publisher-a",
        )
    journal = tmp_path / "lock"
    lock = acquire_promotion_lock(
        journal,
        owner="publisher-a",
        expected_epoch=0,
        now=100,
        lease_seconds=10,
    )
    require_lock_owner(journal, owner="publisher-a", epoch=1, now=105)
    with pytest.raises(ReleaseControlError, match="still leased"):
        acquire_promotion_lock(
            journal,
            owner="publisher-b",
            expected_epoch=1,
            now=105,
            lease_seconds=10,
        )
    recovered = acquire_promotion_lock(
        journal,
        owner="publisher-b",
        expected_epoch=1,
        now=111,
        lease_seconds=10,
        dead_owner_proof=DIGEST_A,
    )
    assert (lock["epoch"], recovered["epoch"]) == (1, 2)
    with pytest.raises(ReleaseControlError, match="stale"):
        require_lock_owner(journal, owner="publisher-a", epoch=1, now=112)


def test_mp2_007_a10_exact_byte_reconciliation() -> None:
    candidate = {"sdist": DIGEST_A, "wheel": DIGEST_B}
    exact = {
        "sdist": {"digest": DIGEST_A, "state": "IMMUTABLE"},
        "wheel": {"digest": DIGEST_B, "state": "IMMUTABLE"},
    }
    assert reconcile_publication(candidate, exact) == {"conflicts": [], "ok": True}
    mismatch = _fixture("invalid/artifact-mismatch.json")
    assert reconcile_publication(mismatch["candidate"], mismatch["observed"])["ok"] is False
    partial = _fixture("invalid/partial-publication.json")
    assert reconcile_publication(partial["candidate"], partial["observed"])["ok"] is False


def test_mp2_007_a11_retention_chain_lkg_and_invalidation(tmp_path: Path) -> None:
    chain = tmp_path / "chain"
    lkg = tmp_path / "lkg"
    pointer = tmp_path / "pointer"
    first = append_cas_event(
        chain,
        {"candidate_digest": DIGEST_A, "milestone": "v0.4"},
        expected_epoch=0,
    )
    transition = append_cas_event(
        lkg,
        {"candidate_digest": DIGEST_A, "milestone": "v0.4", "state": "LKG"},
        expected_epoch=0,
    )
    envelope = append_cas_event(
        pointer,
        {"chain_epoch": first["epoch"], "lkg_epoch": transition["epoch"]},
        expected_epoch=0,
    )
    role_record = _fixture("valid/synthetic-role-assignments.json")
    roles = validate_role_assignments(role_record, live=False)
    invalidation_data = {
        "author_id": roles["author_id"],
        "candidate_digest": DIGEST_A,
        "decision": "INVALIDATED",
        "reason": "product contradiction",
        "reviewer_id": roles["non_author_reviewer_id"],
    }
    invalidation_digest = sha256_json(invalidation_data)
    invalidation_record = make_record(
        "release-approval-decision",
        invalidation_data,
        invocation_id="fixture-invalidation-001",
        sequence=1,
        synthetic=True,
        status="INVALIDATED",
        signatures=[_test_signature(roles["non_author_reviewer_id"], invalidation_digest)],
    )
    validate_lkg_invalidation(
        invalidation_record,
        roles,
        live=False,
        candidate_digest=DIGEST_A,
    )
    with pytest.raises(ReleaseControlError, match="synthetic invalidation"):
        validate_lkg_invalidation(
            invalidation_record,
            roles,
            live=True,
            candidate_digest=DIGEST_A,
        )
    invalidation = append_cas_event(
        lkg,
        {"decision_digest": invalidation_record["record_id"], "state": "INVALIDATED"},
        expected_epoch=1,
    )
    assert (envelope["epoch"], invalidation["epoch"]) == (1, 2)


def test_mp2_007_a12_immutable_recovery_and_new_invocations(tmp_path: Path) -> None:
    recovery = recovery_envelope(
        operation="attempt-index",
        invocation_id="recovery-001",
        sequence=1,
        committed_digest=DIGEST_A,
        failure="killed after CAS before receipt",
    )
    path = tmp_path / "recovery-001.json"
    write_immutable_json(path, recovery)
    with pytest.raises(ReleaseControlError, match="overwrite"):
        write_immutable_json(path, recovery)
    successor = recovery_envelope(
        operation="attempt-index",
        invocation_id="recovery-002",
        sequence=2,
        committed_digest=DIGEST_A,
        failure="receipt reconstruction",
    )
    assert successor["recovery_digest"] != recovery["recovery_digest"]
    write_immutable_json(tmp_path / "recovery-002.json", successor)

    journal = tmp_path / "kill-after-cas"
    committed = append_cas_event(
        journal, {"operation": "publish", "value": DIGEST_A}, expected_epoch=0
    )
    reconstructed = append_cas_event(
        journal, {"operation": "publish", "value": DIGEST_A}, expected_epoch=0
    )
    assert reconstructed == committed
    with pytest.raises(ReleaseControlError, match="compare-and-swap"):
        append_cas_event(journal, {"operation": "publish", "value": DIGEST_B}, expected_epoch=0)

    record = make_record(
        "release-evidence-manifest",
        {"evidence_digest": DIGEST_A},
        invocation_id="recovery-retention-001",
        sequence=1,
        synthetic=True,
    )
    store_b = tmp_path / "conflicting-store"
    conflicting_path = store_b / f"{record['record_id']}.json"
    write_immutable_json(conflicting_path, {"conflict": True})
    recovery_path = tmp_path / "retention-recovery.json"
    with pytest.raises(ReleaseControlError, match="conflicting retained bytes"):
        retain_two_store_evidence(
            record,
            store_a=tmp_path / "partial-store",
            store_b=store_b,
            index_journal=tmp_path / "failed-index",
            expected_index_epoch=0,
            recovery_output=recovery_path,
            recovery_invocation_id="recovery-retention-002",
            recovery_sequence=2,
        )
    assert read_json(recovery_path)["committed_digest"] is not None


def test_mp2_007_a13_complete_mutation_suite_and_mp2_018_fence() -> None:
    readiness = json.loads(
        (ROOT / "docs/status/release-readiness.json").read_text(encoding="utf-8")
    )
    assert readiness["framework"] == "BLOCKED_NOT_READY"
    assert readiness["live_release"] == "BLOCKED_NOT_READY"
    assert readiness["evidence_resolution"] == {
        "allow_synthetic": False,
        "allow_temporary_ci_artifact_as_retention": False,
        "required_result_count": 13,
        "resolved_result_count": 0,
        "status": "BLOCKED_NOT_READY",
    }
    assert {blocker["code"] for blocker in readiness["blockers"]} == {
        "MP2_007_RESULT_EVIDENCE_ABSENT",
        "LIVE_NON_AUTHOR_APPROVAL_REQUIRED",
        "EXTERNAL_TWO_STORE_READBACK_AND_CAS_PROOF_REQUIRED",
        "HOSTED_PROTECTION_AND_REAL_MERGE_PROOF_REQUIRED",
        "MP2_018_POPULATED_INVENTORY_REQUIRED",
    }
    obligations = json.loads(
        (ROOT / "docs/status/release-test-obligations.json").read_text(encoding="utf-8")
    )
    assert obligations["evidence_resolution"]["status"] == "BLOCKED_NOT_READY"
    assert all(row["result_state"] == "ABSENT" for row in obligations["obligations"])
    assert all(not (ROOT / row["result"]).exists() for row in obligations["obligations"])
    assert {item["expected"] for item in SCENARIOS} == {
        "BLOCKED",
        "BURN",
        "CANCELLED",
        "FAIL",
        "PASS",
        "RECOVER",
        "SKIPPED",
    }


def test_release_scenario_catalog_is_closed() -> None:
    assert SCENARIO_REGISTRY["stages"] == list(STAGES)
    assert SCENARIO_REGISTRY["phases"] == [
        "qualification",
        "publication_reconciliation",
        "postpublication",
    ]
    assert set(SCENARIO_REGISTRY["terminal_results"]) == {
        "PASS",
        "FAIL",
        "BLOCKED",
        "CANCELLED",
        "SKIPPED",
        "RECOVER",
        "BURN",
    }
    assert len({scenario["id"] for scenario in SCENARIOS}) == len(SCENARIOS)
    assert {stage for scenario in SCENARIOS for stage in scenario["covers_stages"]} == set(STAGES)
    assert {scenario["phase"] for scenario in SCENARIOS} == set(SCENARIO_REGISTRY["phases"])
    assert {
        "hard-runner-loss",
        "runner-service-retry",
        "staging-cancelled",
        "required-cell-skipped",
        "kill-after-cas",
        "capability-limited-tag-burn",
    } <= {scenario["id"] for scenario in SCENARIOS}
    for scenario in SCENARIOS:
        assert scenario["test_node_id"] == (
            "tests/release/test_local_fake_release.py::"
            f"test_declared_release_scenario_contract[{scenario['id']}]"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario["id"])
def test_declared_release_scenario_contract(scenario: dict[str, object]) -> None:
    expected = scenario["expected"]
    stages = scenario["covers_stages"]
    assert isinstance(stages, list) and stages

    if expected == "BURN":
        burn = record_target_burn(
            target="fixture-target",
            milestone="v0.4",
            version="v0.4.0",
            reason=str(scenario["fault"]),
            observation_digest=DIGEST_A,
        )
        assert resolve_burn_with_patch(burn, "v0.4.1")["resolution"] == "NEW_PATCH_REQUIRED"
        return

    if expected == "RECOVER":
        first = recovery_envelope(
            operation=str(scenario["id"]),
            invocation_id="scenario-recovery-001",
            sequence=1,
            committed_digest=DIGEST_A,
            failure=str(scenario["fault"]),
        )
        retry = recovery_envelope(
            operation=str(scenario["id"]),
            invocation_id="scenario-recovery-002",
            sequence=2,
            committed_digest=DIGEST_A,
            failure="receipt reconstruction",
        )
        assert first["committed_digest"] == retry["committed_digest"]
        assert first["recovery_digest"] != retry["recovery_digest"]
        return

    attempt = new_attempt(
        milestone="v0.4",
        version="v0.4.0",
        candidate_digest=DIGEST_A,
        predecessor_digest=DIGEST_B,
    )
    if scenario["id"] in {"complete-fake-release", "signed-lkg-invalidation"}:
        for stage in STAGES:
            attempt = advance_attempt(attempt, stage=stage, result="PASS", evidence_digest=DIGEST_A)
        assert attempt["events"][-1]["result"] == "PASS"
        return

    stage = str(stages[0])
    for prior_stage in STAGES[: STAGES.index(stage)]:
        attempt = advance_attempt(
            attempt, stage=prior_stage, result="PASS", evidence_digest=DIGEST_A
        )
    attempt = advance_attempt(attempt, stage=stage, result=str(expected), evidence_digest=DIGEST_A)
    assert attempt["events"][-1] == {
        "evidence_digest": DIGEST_A,
        "result": expected,
        "stage": stage,
    }
    with pytest.raises(ReleaseControlError, match="cannot advance"):
        next_index = len(attempt["events"])
        next_stage = STAGES[next_index] if next_index < len(STAGES) else STAGES[-1]
        advance_attempt(attempt, stage=next_stage, result="PASS", evidence_digest=DIGEST_A)


def test_failure_terminalizes_attempt() -> None:
    attempt = new_attempt(
        milestone="v0.4",
        version="v0.4.0",
        candidate_digest=DIGEST_A,
        predecessor_digest=DIGEST_B,
    )
    attempt = advance_attempt(attempt, stage="roles", result="BLOCKED", evidence_digest=DIGEST_A)
    with pytest.raises(ReleaseControlError, match="cannot advance"):
        advance_attempt(attempt, stage="task-state", result="PASS", evidence_digest=DIGEST_A)


def test_cas_rejects_concurrent_writer(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    append_cas_event(journal, {"writer": "a"}, expected_epoch=0)
    with pytest.raises(ReleaseControlError, match="compare-and-swap"):
        append_cas_event(journal, {"writer": "b"}, expected_epoch=0)
    assert read_json(journal / "00000001.json") == {"epoch": 1, "writer": "a"}
