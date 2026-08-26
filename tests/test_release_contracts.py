# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from metriplane.release_control import (
    MILESTONES,
    TOOL_CONTRACTS,
    ReleaseControlError,
    build_release_readiness_record,
    make_record,
    sha256_json,
    signature_subject_digest,
    tool_main,
    validate_record,
    validate_release_retention_receipts,
    validate_role_assignments,
    write_immutable_json,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
STATUS = ROOT / "docs" / "status"

SCHEMA_KINDS = {
    "linear-release-snapshot",
    "provider-run-termination",
    "release-approval-decision",
    "release-approval",
    "release-artifact-manifest",
    "release-attempt-coordination",
    "release-attempt-index",
    "release-attempt",
    "release-burn-lineage",
    "release-candidate-identity",
    "release-capability-delta",
    "release-cell-result",
    "release-delta-test-map",
    "release-environment-observation",
    "release-evidence-chain",
    "release-evidence-manifest",
    "release-evidence-store-preflight",
    "release-evidence-store",
    "release-gate-input",
    "release-gate-instance",
    "release-impact-manifest",
    "release-index-recovery",
    "release-last-known-good",
    "release-postpublication-conflict",
    "release-predecessor",
    "release-prepromotion-controls",
    "release-prepublication-blocker-attempt",
    "release-promotion-lock",
    "release-promotion-plan",
    "release-promotion",
    "release-protected-input",
    "release-publication-observations",
    "release-publication-reconciliation",
    "release-qualification-plan",
    "release-qualification",
    "release-readiness",
    "release-retention-receipts",
    "release-role-assignments",
    "release-run-status-snapshot",
    "release-scenario-catalog",
    "release-source-freeze",
    "release-stage-invocation",
    "release-staging-attempt",
    "release-target-burn",
    "release-target-observations",
    "release-target-resolution",
    "release-task-state-observation",
    "release-task-state-policy",
    "release-warning-summary",
}

TOOL_NAMES = {
    "aggregate_release_attempt.py",
    "build_publication_reconciliation.py",
    "build_release_artifacts.py",
    "build_release_delta_test_map.py",
    "build_release_evidence_manifest.py",
    "build_release_qualification.py",
    "capture_linear_release_snapshot.py",
    "capture_release_run_statuses.py",
    "capture_release_target_observations.py",
    "capture_release_task_state_observation.py",
    "check_release_delta.py",
    "check_release_readiness.py",
    "collect_publication_observations.py",
    "execute_release_qualification.py",
    "export_release_attempt_index.py",
    "export_release_burn_lineage.py",
    "finalize_release_attempt_cells.py",
    "finalize_release_candidate_identity.py",
    "finalize_release_gate_instance.py",
    "freeze_release_source.py",
    "plan_release_qualification.py",
    "prepare_release_gate_input.py",
    "prepare_release_impact_manifest.py",
    "promote_release_candidate.py",
    "record_postpublication_conflict.py",
    "record_release_approval.py",
    "record_release_blocker_attempt.py",
    "record_release_index_recovery.py",
    "record_release_role_assignments.py",
    "record_release_staging_attempt.py",
    "record_release_target_burn.py",
    "resolve_release_predecessor.py",
    "resolve_release_target.py",
    "retain_release_evidence.py",
    "update_last_known_good.py",
    "update_release_attempt_index.py",
    "update_release_evidence_chain.py",
    "validate_linear_release_snapshot.py",
    "validate_publication_reconciliation.py",
    "validate_release_approval.py",
    "validate_release_artifact_manifest.py",
    "validate_release_attempt.py",
    "validate_release_attempt_index.py",
    "validate_release_candidate_identity.py",
    "validate_release_evidence_chain.py",
    "validate_release_evidence_manifest.py",
    "validate_release_evidence_stores.py",
    "validate_release_gate_input.py",
    "validate_release_gate_instance.py",
    "validate_release_predecessor.py",
    "validate_release_prepromotion_controls.py",
    "validate_release_qualification.py",
    "validate_release_qualification_plan.py",
    "validate_release_retention.py",
    "validate_release_role_assignments.py",
    "validate_release_source_freeze.py",
    "validate_release_target_resolution.py",
    "validate_release_task_state_observation.py",
}


def _schema_path(kind: str) -> Path:
    return SCHEMAS / f"metriplane.{kind}.v1.schema.json"


def _assert_closed_objects(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" in value:
            assert value.get("additionalProperties") is False
        for child in value.values():
            _assert_closed_objects(child)
    elif isinstance(value, list):
        for child in value:
            _assert_closed_objects(child)


def test_release_contract_graph_is_closed() -> None:
    observed = {
        path.name.removeprefix("metriplane.").removesuffix(".v1.schema.json")
        for path in SCHEMAS.glob("metriplane.*release*.v1.schema.json")
    } | {
        "provider-run-termination"
        if (SCHEMAS / "metriplane.provider-run-termination.v1.schema.json").is_file()
        else ""
    }
    observed.discard("")
    assert observed == SCHEMA_KINDS
    assert len(observed) == 49

    for kind in sorted(SCHEMA_KINDS):
        schema = json.loads(_schema_path(kind).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(_schema_path(kind).name)
        assert schema["properties"]["record_type"] == {"const": kind}
        _assert_closed_objects(schema)


def test_all_stable_release_tool_paths_are_present() -> None:
    assert len(TOOL_NAMES) == 58
    assert set(TOOL_CONTRACTS) == TOOL_NAMES
    missing = sorted(name for name in TOOL_NAMES if not (ROOT / "tools" / name).is_file())
    assert missing == []
    for name in TOOL_NAMES - {"build_release_artifacts.py"}:
        text = (ROOT / "tools" / name).read_text(encoding="utf-8")
        assert "from metriplane.release_control import tool_main" in text
    artifact_adapter = (ROOT / "tools/build_release_artifacts.py").read_text(encoding="utf-8")
    assert "from tools.release_artifacts import" in artifact_adapter
    assert "create_manifest" in artifact_adapter
    assert "inspect_sdist" in artifact_adapter


def _contract_argv(name: str, output: Path, *, form_index: int = 0) -> list[str]:
    contract = TOOL_CONTRACTS[name]
    form = contract.forms[form_index]
    constrained = {flag: min(values) for flag, values in form.equals}
    argv: list[str] = []
    for flag in sorted(form.required):
        argv.append(f"--{flag}")
        if flag in contract.boolean:
            continue
        if flag == contract.output_flag:
            argv.append(str(output))
        elif flag in constrained:
            argv.append(constrained[flag])
        elif flag in contract.choices:
            argv.append(contract.choices[flag][0])
        elif flag in contract.integer:
            argv.append("1")
        else:
            argv.append("fixture-value")
    return argv


def _remove_argument(argv: list[str], flag: str, *, boolean: bool) -> list[str]:
    mutated = list(argv)
    index = mutated.index(f"--{flag}")
    del mutated[index]
    if not boolean:
        del mutated[index]
    return mutated


def _tool_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT)
    return environment


def _passing_qualification(*, status: str = "PASS") -> dict[str, Any]:
    data = {
        "attempt_digests": ["1" * 64],
        "attempt_index_receipt_digests": ["2" * 64],
        "attempt_retention_receipt_digests": ["3" * 64],
        "candidate_digest": "4" * 64,
        "executed_cell_ids": ["cell-1"],
        "expected_cell_ids": ["cell-1"],
        "plan_digest": "5" * 64,
        "qualification_digest": "6" * 64,
        "result": "PASS",
        "terminal_results": [{"cell_id": "cell-1", "result": "PASS", "result_digest": "7" * 64}],
        "unexpected_outcomes": [],
        "warning_summary_digest": "8" * 64,
    }
    return make_record(
        "release-qualification",
        data,
        invocation_id=f"qualification-{status.lower()}-fixture",
        sequence=1,
        synthetic=True,
        status=status,
    )


def test_live_signature_shape_and_forged_fixture_digest_are_not_authority() -> None:
    data = {
        "author_id": "author",
        "authorized_executor_id": "executor",
        "non_author_reviewer_id": "reviewer",
        "publisher_id": "publisher",
        "task_id": "MP2-007",
    }
    live_unsigned = make_record(
        "release-role-assignments",
        data,
        invocation_id="live-signature-shape-fixture",
        sequence=1,
        synthetic=False,
    )
    live_subject = signature_subject_digest(live_unsigned)
    live = make_record(
        "release-role-assignments",
        data,
        invocation_id="live-signature-shape-fixture",
        sequence=1,
        synthetic=False,
        signatures=[
            {
                "actor_id": "executor",
                "algorithm": "provider-attestation-v1",
                "provider": "github",
                "signature": "fabricated-provider-value",
                "subject_digest": live_subject,
                "synthetic": False,
            }
        ],
    )
    with pytest.raises(ReleaseControlError, match="verification is not implemented"):
        validate_role_assignments(live, live=True)

    forged_unsigned = make_record(
        "release-role-assignments",
        data,
        invocation_id="forged-test-signature-fixture",
        sequence=1,
        synthetic=True,
    )
    forged_subject = signature_subject_digest(forged_unsigned)
    forged = make_record(
        "release-role-assignments",
        data,
        invocation_id="forged-test-signature-fixture",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "executor",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": "0" * 64,
                "subject_digest": forged_subject,
                "synthetic": True,
            }
        ],
    )
    with pytest.raises(ReleaseControlError, match="authentication failed"):
        validate_role_assignments(forged, live=False)


def test_signature_cannot_be_reused_after_decision_status_changes() -> None:
    data = {
        "author_id": "author",
        "authorized_executor_id": "executor",
        "non_author_reviewer_id": "reviewer",
        "publisher_id": "publisher",
        "task_id": "MP2-007",
    }
    blocked = make_record(
        "release-role-assignments",
        data,
        invocation_id="blocked-role-decision-fixture",
        sequence=1,
        synthetic=True,
        status="BLOCKED",
    )
    subject = signature_subject_digest(blocked)
    signed_blocked = make_record(
        "release-role-assignments",
        data,
        invocation_id="blocked-role-decision-fixture",
        sequence=1,
        synthetic=True,
        status="BLOCKED",
        signatures=[
            {
                "actor_id": "executor",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": sha256_json({"actor_id": "executor", "subject_digest": subject}),
                "subject_digest": subject,
                "synthetic": True,
            }
        ],
    )
    mutated = json.loads(json.dumps(signed_blocked))
    mutated["status"] = "PASS"
    unsigned = dict(mutated)
    unsigned.pop("record_id")
    mutated["record_id"] = sha256_json(unsigned)
    with pytest.raises(ReleaseControlError, match="decision envelope"):
        validate_role_assignments(mutated, live=False)


def test_role_assignment_cli_enforces_run_milestone_conflicts_and_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = {
        "author_id": "author",
        "authorized_executor_id": "executor",
        "milestone": "v0.4",
        "non_author_reviewer_id": "reviewer",
        "publisher_id": "publisher",
        "run_id": "111",
        "task_id": "MP2-007",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_until": "2099-01-01T00:00:00Z",
    }
    unsigned = make_record(
        "release-role-assignments",
        data,
        invocation_id="bound-role-assignment-fixture",
        sequence=1,
        synthetic=True,
    )
    subject = signature_subject_digest(unsigned)
    record = make_record(
        "release-role-assignments",
        data,
        invocation_id="bound-role-assignment-fixture",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "executor",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": sha256_json({"actor_id": "executor", "subject_digest": subject}),
                "subject_digest": subject,
                "synthetic": True,
            }
        ],
    )
    path = tmp_path / "role-assignments.json"
    write_immutable_json(path, record)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")

    def argv(*, milestone: str = "v0.4", run_id: str = "111") -> list[str]:
        return [
            "--record",
            str(path),
            "--milestone",
            milestone,
            "--run-id",
            run_id,
            "--check-conflicts",
            "--check-freshness",
        ]

    assert tool_main("validate_release_role_assignments.py", argv()) == 0
    assert tool_main("validate_release_role_assignments.py", argv(milestone="v1.0")) == 3
    assert tool_main("validate_release_role_assignments.py", argv(run_id="999999")) == 3

    for label, changed_data, expected_error in (
        (
            "conflict",
            {**data, "non_author_reviewer_id": "executor"},
            "actor conflict",
        ),
        (
            "stale",
            {
                **data,
                "valid_from": "2020-01-01T00:00:00Z",
                "valid_until": "2021-01-01T00:00:00Z",
            },
            "validity window",
        ),
    ):
        unsigned_changed = make_record(
            "release-role-assignments",
            changed_data,
            invocation_id=f"bound-role-assignment-{label}",
            sequence=1,
            synthetic=True,
        )
        changed_subject = signature_subject_digest(unsigned_changed)
        changed = make_record(
            "release-role-assignments",
            changed_data,
            invocation_id=f"bound-role-assignment-{label}",
            sequence=1,
            synthetic=True,
            signatures=[
                {
                    "actor_id": "executor",
                    "algorithm": "test-sha256-v1",
                    "provider": "test-fixture",
                    "signature": sha256_json(
                        {"actor_id": "executor", "subject_digest": changed_subject}
                    ),
                    "subject_digest": changed_subject,
                    "synthetic": True,
                }
            ],
        )
        with pytest.raises(ReleaseControlError, match=expected_error):
            validate_role_assignments(
                changed,
                live=False,
                expected_milestone="v0.4",
                expected_run_id="111",
                check_conflicts=True,
                check_freshness=True,
            )


def test_live_retention_claims_block_without_real_store_readback(tmp_path: Path) -> None:
    receipts = make_record(
        "release-retention-receipts",
        {},
        invocation_id="live-retention-claims-fixture",
        sequence=1,
        synthetic=False,
    )
    with pytest.raises(ReleaseControlError, match="two-store read-back verification"):
        validate_release_retention_receipts(
            receipts,
            inputs=[],
            manifest=None,
            invocation_root=tmp_path,
            through_stage="fabricated-stage",
            live=True,
        )


def test_live_subject_records_require_authenticated_authority(tmp_path: Path) -> None:
    live_qualification = make_record(
        "release-qualification",
        _passing_qualification()["data"],
        invocation_id="live-qualification-without-authority",
        sequence=1,
        synthetic=False,
    )
    live_reconciliation = make_record(
        "release-publication-reconciliation",
        {},
        invocation_id="live-reconciliation-without-authority",
        sequence=1,
        synthetic=False,
    )
    for name, record in (
        ("validate_release_qualification.py", live_qualification),
        ("validate_publication_reconciliation.py", live_reconciliation),
    ):
        path = tmp_path / f"{name}.json"
        write_immutable_json(path, record)
        assert tool_main(name, ["--record", str(path)]) == 3


def test_malformed_record_status_blocks_without_type_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = make_record(
        "release-gate-input",
        {},
        invocation_id="malformed-status-fixture",
        sequence=1,
        synthetic=True,
    )
    record["status"] = []
    path = tmp_path / "malformed-status.json"
    write_immutable_json(path, record)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    assert tool_main("validate_release_gate_input.py", ["--record", str(path)]) == 3


def test_subject_validators_reject_blocked_records_and_missing_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked_path = tmp_path / "blocked-qualification.json"
    write_immutable_json(blocked_path, _passing_qualification(status="BLOCKED"))
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    assert tool_main("validate_release_qualification.py", ["--record", str(blocked_path)]) == 3
    generic = make_record(
        "release-gate-input",
        {},
        invocation_id="unimplemented-gate-input-validator-fixture",
        sequence=1,
        synthetic=True,
    )
    generic_path = tmp_path / "gate-input.json"
    write_immutable_json(generic_path, generic)
    assert tool_main("validate_release_gate_input.py", ["--record", str(generic_path)]) == 3

    qualification_path = tmp_path / "qualification.json"
    qualification = _passing_qualification()
    write_immutable_json(qualification_path, qualification)
    assert (
        tool_main(
            "validate_release_qualification.py",
            ["--record", str(qualification_path)],
        )
        == 3
    )
    approval = make_record(
        "release-approval",
        {
            "author_id": "author",
            "candidate_digest": qualification["data"]["candidate_digest"],
            "conflicts": [],
            "decision": "APPROVED",
            "reviewer_id": "reviewer",
        },
        invocation_id="approval-missing-dependency-fixture",
        sequence=1,
        synthetic=True,
    )
    approval_path = tmp_path / "approval.json"
    write_immutable_json(approval_path, approval)
    assert (
        tool_main(
            "validate_release_approval.py",
            [
                "--gate-instance",
                str(tmp_path / "missing-gate.json"),
                "--qualification",
                str(qualification_path),
                "--no-prepublication-rubric",
                "--record",
                str(approval_path),
            ],
        )
        == 3
    )

    reconciliation = make_record(
        "release-publication-reconciliation",
        {
            "approval_digest": "1" * 64,
            "burn_required": True,
            "candidate_digest": "2" * 64,
            "evidence_manifest_digest": "3" * 64,
            "expected_artifacts": ["metriplane.whl"],
            "lock_receipt_digest": "4" * 64,
            "milestone": "v0.4",
            "observations_digest": "5" * 64,
            "partial_targets": ["pypi"],
            "promotion_digest": "6" * 64,
            "qualification_digest": "7" * 64,
            "reconciliation_digest": "8" * 64,
            "result": "FAIL",
            "staged_retention_receipts_digest": "9" * 64,
            "targets": ["pypi"],
        },
        invocation_id="failed-reconciliation-fixture",
        sequence=1,
        synthetic=True,
    )
    reconciliation_path = tmp_path / "failed-reconciliation.json"
    write_immutable_json(reconciliation_path, reconciliation)
    assert (
        tool_main(
            "validate_publication_reconciliation.py",
            ["--record", str(reconciliation_path)],
        )
        == 3
    )
    unbacked_reconciliation = make_record(
        "release-publication-reconciliation",
        {
            "approval_digest": "1" * 64,
            "burn_required": False,
            "candidate_digest": "2" * 64,
            "evidence_manifest_digest": "3" * 64,
            "expected_artifacts": [
                {
                    "media_type": "application/vnd.pypa.wheel+zip",
                    "path": "metriplane-0.4.0-py3-none-any.whl",
                    "sha256": "a" * 64,
                    "size": 10,
                },
                {
                    "media_type": "application/gzip",
                    "path": "metriplane-0.4.0.tar.gz",
                    "sha256": "b" * 64,
                    "size": 11,
                },
            ],
            "lock_receipt_digest": "4" * 64,
            "milestone": "v0.4",
            "observations_digest": "5" * 64,
            "partial_targets": [],
            "promotion_digest": "6" * 64,
            "qualification_digest": "7" * 64,
            "reconciliation_digest": "8" * 64,
            "result": "RECONCILED",
            "staged_retention_receipts_digest": "9" * 64,
            "targets": [{"conflict_digest": None, "exact_match": True, "target_id": "pypi"}],
        },
        invocation_id="unbacked-reconciliation-fixture",
        sequence=1,
        synthetic=True,
    )
    unbacked_path = tmp_path / "unbacked-reconciliation.json"
    write_immutable_json(unbacked_path, unbacked_reconciliation)
    assert (
        tool_main(
            "validate_publication_reconciliation.py",
            ["--record", str(unbacked_path)],
        )
        == 3
    )

    predecessor = make_record(
        "release-predecessor",
        {
            "candidate_milestone": "v0.4",
            "closed_decision_digest": "a" * 64,
            "lkg_digest": "b" * 64,
            "version": "v0.3.0",
        },
        invocation_id="candidate-predecessor-fixture",
        sequence=1,
        synthetic=True,
    )
    predecessor_path = tmp_path / "candidate-predecessor.json"
    write_immutable_json(predecessor_path, predecessor)
    candidate = make_record(
        "release-candidate-identity",
        {
            "artifact_manifest_digest": "1" * 64,
            "artifact_set_digest": "2" * 64,
            "build_invocation_id": "candidate-build-fixture",
            "candidate_digest": "3" * 64,
            "evaluation_adoption_digest": None,
            "evaluation_adoption_mode": "none",
            "gate_input_digest": "4" * 64,
            "milestone": "v0.4",
            "package_version": "v0.4.0",
            "predecessor_digest": sha256_json(predecessor),
            "release_tag": "v0.4.0",
            "source_freeze_digest": "5" * 64,
        },
        invocation_id="candidate-missing-directory-fixture",
        sequence=1,
        synthetic=True,
    )
    candidate_path = tmp_path / "candidate.json"
    write_immutable_json(candidate_path, candidate)
    assert (
        tool_main(
            "validate_release_candidate_identity.py",
            [
                "--record",
                str(candidate_path),
                "--predecessor",
                str(predecessor_path),
                "--no-evaluation-adoption",
                "--candidate-dir",
                str(tmp_path / "missing-candidate-dir"),
            ],
        )
        == 3
    )


def test_qualification_validator_resolves_the_retained_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_digest = "c" * 64
    candidate = make_record(
        "release-candidate-identity",
        {"candidate_digest": candidate_digest},
        invocation_id="resolved-qualification-candidate",
        sequence=1,
        synthetic=True,
    )
    write_immutable_json(tmp_path / "candidate-identity.json", candidate)
    plan = make_record(
        "release-qualification-plan",
        {
            "attempt_count": 1,
            "candidate_digest": candidate_digest,
            "candidate_manifest_digest": "1" * 64,
            "cells": [
                {
                    "cell_id": "cell-1",
                    "environment_id": "ubuntu-py312",
                    "obligation_ids": ["MP2-007.A07"],
                    "profile_id": "default",
                    "scenario_ids": ["qualification-pass"],
                }
            ],
            "delta_digest": "2" * 64,
            "delta_test_map_digest": "3" * 64,
            "expected_terminal_result": "PASS",
            "gate_instance_digest": "4" * 64,
            "milestone": "v0.4",
            "plan_digest": "5" * 64,
            "predecessor_digest": "6" * 64,
            "readiness_digest": "7" * 64,
            "scenario_catalog_digest": "8" * 64,
        },
        invocation_id="resolved-qualification-plan",
        sequence=1,
        synthetic=True,
    )
    plan_digest = write_immutable_json(tmp_path / "qualification-plan.json", plan)
    index_receipt = make_record(
        "release-attempt-index",
        {},
        invocation_id="resolved-qualification-index",
        sequence=1,
        synthetic=True,
    )
    index_digest = write_immutable_json(tmp_path / "attempt-index-receipt.json", index_receipt)
    retention_receipt = make_record(
        "release-retention-receipts",
        {},
        invocation_id="resolved-qualification-retention",
        sequence=1,
        synthetic=True,
    )
    retention_digest = write_immutable_json(
        tmp_path / "attempt-retention-receipts.json", retention_receipt
    )
    cell = make_record(
        "release-cell-result",
        {
            "artifact_digest": "9" * 64,
            "attempt_id": "001",
            "candidate_digest": candidate_digest,
            "cell_id": "cell-1",
            "completed_at": "2026-08-25T12:01:00Z",
            "counts": {
                "deselected": 0,
                "failed": 0,
                "passed": 1,
                "retried": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
            },
            "environment_id": "ubuntu-py312",
            "junit_digest": "a" * 64,
            "obligation_ids": ["MP2-007.A07"],
            "plan_digest": plan_digest,
            "profile_id": "default",
            "result": "PASS",
            "runner_identity": "fixture-runner",
            "scenario_ids": ["qualification-pass"],
            "started_at": "2026-08-25T12:00:00Z",
            "stderr_digest": "b" * 64,
            "stdout_digest": "d" * 64,
            "unexpected_outcomes": [],
        },
        invocation_id="resolved-qualification-cell",
        sequence=1,
        synthetic=True,
    )
    cell_path = tmp_path / "cell-result.json"
    cell_digest = write_immutable_json(cell_path, cell)
    warning = make_record(
        "release-warning-summary",
        {
            "attempt_digest": "e" * 64,
            "candidate_digest": candidate_digest,
            "deselection_count": 0,
            "policy_digest": "f" * 64,
            "result": "PASS",
            "retry_count": 0,
            "skip_count": 0,
            "summary_digest": "1" * 64,
            "unexpected_warning_count": 0,
            "warnings": [],
            "xfail_count": 0,
            "xpass_count": 0,
        },
        invocation_id="resolved-qualification-warning",
        sequence=1,
        synthetic=True,
    )
    warning_digest = write_immutable_json(tmp_path / "warning-summary.json", warning)
    attempt = make_record(
        "release-attempt",
        {
            "attempt_id": "001",
            "candidate_digest": candidate_digest,
            "cells": [{"cell_id": "cell-1", "result": "PASS", "result_digest": cell_digest}],
            "coordination_digest": "2" * 64,
            "index_receipt_digest": index_digest,
            "milestone": "v0.4",
            "qualification_plan_digest": plan_digest,
            "result": "PASS",
            "retention_receipts_digest": retention_digest,
            "warning_summary_digest": warning_digest,
        },
        invocation_id="resolved-qualification-attempt",
        sequence=1,
        synthetic=True,
    )
    attempt_digest = write_immutable_json(tmp_path / "attempt-summary.json", attempt)
    qualification = make_record(
        "release-qualification",
        {
            "attempt_digests": [attempt_digest],
            "attempt_index_receipt_digests": [index_digest],
            "attempt_retention_receipt_digests": [retention_digest],
            "candidate_digest": candidate_digest,
            "executed_cell_ids": ["cell-1"],
            "expected_cell_ids": ["cell-1"],
            "plan_digest": plan_digest,
            "qualification_digest": "3" * 64,
            "result": "PASS",
            "terminal_results": [
                {"cell_id": "cell-1", "result": "PASS", "result_digest": cell_digest}
            ],
            "unexpected_outcomes": [],
            "warning_summary_digest": warning_digest,
        },
        invocation_id="resolved-qualification",
        sequence=1,
        synthetic=True,
    )
    qualification_path = tmp_path / "qualification.json"
    write_immutable_json(qualification_path, qualification)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    argv = ["--record", str(qualification_path)]
    assert tool_main("validate_release_qualification.py", argv) == 0

    dirty_warning = make_record(
        "release-warning-summary",
        {**warning["data"], "skip_count": 9},
        invocation_id="resolved-qualification-dirty-attempt-warning",
        sequence=1,
        synthetic=True,
    )
    dirty_warning_digest = write_immutable_json(
        tmp_path / "dirty-attempt-warning-summary.json", dirty_warning
    )
    dirty_attempt = make_record(
        "release-attempt",
        {**attempt["data"], "warning_summary_digest": dirty_warning_digest},
        invocation_id="resolved-qualification-dirty-attempt",
        sequence=1,
        synthetic=True,
    )
    dirty_attempt_digest = write_immutable_json(
        tmp_path / "dirty-attempt-summary.json", dirty_attempt
    )
    laundering_qualification = make_record(
        "release-qualification",
        {**qualification["data"], "attempt_digests": [dirty_attempt_digest]},
        invocation_id="resolved-qualification-dirty-attempt-laundering",
        sequence=1,
        synthetic=True,
    )
    laundering_path = tmp_path / "dirty-attempt-qualification.json"
    write_immutable_json(laundering_path, laundering_qualification)
    assert tool_main("validate_release_qualification.py", ["--record", str(laundering_path)]) == 3

    hidden_warning = make_record(
        "release-warning-summary",
        {**warning["data"], "warnings": [{"message": "unaccounted warning"}]},
        invocation_id="resolved-qualification-hidden-attempt-warning",
        sequence=1,
        synthetic=True,
    )
    hidden_warning_digest = write_immutable_json(
        tmp_path / "hidden-attempt-warning-summary.json", hidden_warning
    )
    hidden_warning_attempt = make_record(
        "release-attempt",
        {**attempt["data"], "warning_summary_digest": hidden_warning_digest},
        invocation_id="resolved-qualification-hidden-warning-attempt",
        sequence=1,
        synthetic=True,
    )
    hidden_warning_attempt_digest = write_immutable_json(
        tmp_path / "hidden-warning-attempt-summary.json", hidden_warning_attempt
    )
    hidden_warning_qualification = make_record(
        "release-qualification",
        {**qualification["data"], "attempt_digests": [hidden_warning_attempt_digest]},
        invocation_id="resolved-qualification-hidden-warning-laundering",
        sequence=1,
        synthetic=True,
    )
    hidden_warning_path = tmp_path / "hidden-warning-qualification.json"
    write_immutable_json(hidden_warning_path, hidden_warning_qualification)
    assert (
        tool_main(
            "validate_release_qualification.py",
            ["--record", str(hidden_warning_path)],
        )
        == 3
    )

    cell_path.unlink()
    assert tool_main("validate_release_qualification.py", argv) == 3


def test_reconciliation_validator_resolves_exact_observed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_digest = "c" * 64
    artifacts = [
        {
            "media_type": "application/vnd.pypa.wheel+zip",
            "path": "metriplane-0.4.0-py3-none-any.whl",
            "sha256": "b" * 64,
            "size": 10,
        },
        {
            "media_type": "application/gzip",
            "path": "metriplane-0.4.0.tar.gz",
            "sha256": "a" * 64,
            "size": 11,
        },
    ]

    def retain(name: str, record_type: str, data: dict[str, Any]) -> tuple[Path, str]:
        record = make_record(
            record_type,
            data,
            invocation_id=f"resolved-reconciliation-{name}",
            sequence=1,
            synthetic=True,
        )
        path = tmp_path / f"{name}.json"
        return path, write_immutable_json(path, record)

    _qualification_path, qualification_digest = retain(
        "qualification",
        "release-qualification",
        {**_passing_qualification()["data"], "candidate_digest": candidate_digest},
    )
    _approval_path, approval_digest = retain(
        "approval",
        "release-approval",
        {
            "author_id": "fixture-author",
            "candidate_digest": candidate_digest,
            "conflicts": [],
            "decision": "APPROVED",
            "reviewer_id": "fixture-reviewer",
        },
    )
    _lock_path, lock_digest = retain(
        "promotion-lock-receipt",
        "release-promotion-lock",
        {
            "acquired_index_head": "1" * 64,
            "approval_digest": approval_digest,
            "attempt_index_checkpoint_digest": "2" * 64,
            "backend_id": "attempt-index",
            "candidate_digest": candidate_digest,
            "controls_digest": "3" * 64,
            "dead_owner_proof_digest": None,
            "epoch": 1,
            "expected_index_head": "1" * 64,
            "lease_expires_at": "2026-08-25T12:10:00Z",
            "lease_started_at": "2026-08-25T12:00:00Z",
            "lock_token": "fixture-lock-token",
            "mutation_started": True,
            "operation_id": "fixture-promotion-operation",
            "owner": "fixture-publisher",
            "promotion_plan_digest": "4" * 64,
            "recovery_authorization_digest": None,
            "state": "COMMITTED",
            "target_state_digest": "5" * 64,
        },
    )
    promotion_path, promotion_digest = retain(
        "promotion",
        "release-promotion",
        {
            "actions": [
                {
                    "action": "publish",
                    "observed_digest": "6" * 64,
                    "result": "PASS",
                    "target_id": target_id,
                }
                for target_id in ["github-release", "pypi", "testpypi"]
            ],
            "candidate_digest": candidate_digest,
            "completed_at": "2026-08-25T12:02:00Z",
            "lock_receipt_digest": lock_digest,
            "mode": "execute",
            "mutation_started": True,
            "operation_id": "fixture-promotion-operation",
            "promotion_plan_digest": "4" * 64,
            "publisher_id": "fixture-publisher",
            "record_kind": "promotion_execution",
            "result": "PUBLISHED",
            "started_at": "2026-08-25T12:01:00Z",
            "target_state_digest": "5" * 64,
        },
    )
    observed_artifacts = [
        {
            "expected_digest": artifact["sha256"],
            "name": artifact["path"],
            "observed_digest": artifact["sha256"],
            "size": artifact["size"],
        }
        for artifact in artifacts
    ]
    required_target_ids = ["github-release", "pypi", "testpypi"]
    _observations_path, observations_digest = retain(
        "publication-observations",
        "release-publication-observations",
        {
            "all_targets_observed": True,
            "candidate_digest": candidate_digest,
            "lock_receipt_digest": lock_digest,
            "promotion_digest": promotion_digest,
            "targets": [
                {
                    "artifacts": observed_artifacts,
                    "availability": "present",
                    "immutability": "immutable",
                    "provider_receipt_digest": "7" * 64,
                    "raw_result_digest": "8" * 64,
                    "target_id": target_id,
                    "uri": f"https://example.invalid/{target_id}",
                }
                for target_id in required_target_ids
            ],
            "artifact_manifest_digest": "9" * 64,
            "observation_digest": "a" * 64,
            "observed_at": "2026-08-25T12:03:00Z",
        },
    )
    _manifest_path, manifest_digest = retain(
        "evidence-manifest",
        "release-evidence-manifest",
        {
            "candidate_digest": candidate_digest,
            "entries": [
                {
                    "media_type": artifact["media_type"],
                    "path": artifact["path"],
                    "role": "release-artifact",
                    "sha256": artifact["sha256"],
                    "size": artifact["size"],
                }
                for artifact in artifacts
            ],
            "invocation_journal_digests": ["b" * 64],
            "manifest_digest": "c" * 64,
            "phase": "qualified-publication",
            "scope_id": "v0.4.0",
            "scope_kind": "release-candidate",
        },
    )
    _retention_path, retention_digest = retain(
        "retention-receipts",
        "release-retention-receipts",
        {
            "all_content_equal": True,
            "input_digest": manifest_digest,
            "phase": "qualified-publication",
            "receipt_set_digest": "e" * 64,
            "retained_at": "2026-08-25T12:04:00Z",
            "stores": [
                {
                    "content_digest": manifest_digest,
                    "hold_receipt_digest": hold,
                    "independence_group": group,
                    "namespace": "release-fixture",
                    "object_key": f"candidate/{store_id}",
                    "put_receipt_digest": put,
                    "read_back_digest": manifest_digest,
                    "store_id": store_id,
                }
                for store_id, group, hold, put in (
                    ("payload-store-a", "group-a", "1" * 64, "2" * 64),
                    ("payload-store-b", "group-b", "3" * 64, "4" * 64),
                )
            ],
        },
    )
    reconciliation = make_record(
        "release-publication-reconciliation",
        {
            "approval_digest": approval_digest,
            "burn_required": False,
            "candidate_digest": candidate_digest,
            "evidence_manifest_digest": manifest_digest,
            "expected_artifacts": artifacts,
            "lock_receipt_digest": lock_digest,
            "milestone": "v0.4",
            "observations_digest": observations_digest,
            "partial_targets": [],
            "promotion_digest": promotion_digest,
            "qualification_digest": qualification_digest,
            "reconciliation_digest": "d" * 64,
            "result": "RECONCILED",
            "staged_retention_receipts_digest": retention_digest,
            "targets": [
                {"conflict_digest": None, "exact_match": True, "target_id": target_id}
                for target_id in required_target_ids
            ],
        },
        invocation_id="resolved-reconciliation",
        sequence=1,
        synthetic=True,
    )
    reconciliation_path = tmp_path / "publication-reconciliation.json"
    write_immutable_json(reconciliation_path, reconciliation)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    argv = ["--record", str(reconciliation_path)]
    assert tool_main("validate_publication_reconciliation.py", argv) == 0

    _subset_path, subset_observations_digest = retain(
        "publication-observations-subset",
        "release-publication-observations",
        {
            **json.loads((tmp_path / "publication-observations.json").read_text())["data"],
            "targets": [
                {
                    "artifacts": observed_artifacts,
                    "availability": "present",
                    "immutability": "immutable",
                    "provider_receipt_digest": "7" * 64,
                    "raw_result_digest": "8" * 64,
                    "target_id": "pypi",
                    "uri": "https://example.invalid/pypi",
                }
            ],
        },
    )
    subset_reconciliation = make_record(
        "release-publication-reconciliation",
        {
            **reconciliation["data"],
            "observations_digest": subset_observations_digest,
            "targets": [{"conflict_digest": None, "exact_match": True, "target_id": "pypi"}],
        },
        invocation_id="resolved-reconciliation-subset",
        sequence=1,
        synthetic=True,
    )
    subset_reconciliation_path = tmp_path / "publication-reconciliation-subset.json"
    write_immutable_json(subset_reconciliation_path, subset_reconciliation)
    assert (
        tool_main(
            "validate_publication_reconciliation.py",
            ["--record", str(subset_reconciliation_path)],
        )
        == 3
    )

    _malformed_qualification_path, malformed_qualification_digest = retain(
        "qualification-malformed-cell-id",
        "release-qualification",
        {
            **json.loads((tmp_path / "qualification.json").read_text())["data"],
            "executed_cell_ids": [{"not": "a cell id"}],
            "expected_cell_ids": [{"not": "a cell id"}],
        },
    )
    malformed_reconciliation = make_record(
        "release-publication-reconciliation",
        {**reconciliation["data"], "qualification_digest": malformed_qualification_digest},
        invocation_id="resolved-reconciliation-malformed-qualification",
        sequence=1,
        synthetic=True,
    )
    malformed_reconciliation_path = tmp_path / "malformed-qualification-reconciliation.json"
    write_immutable_json(malformed_reconciliation_path, malformed_reconciliation)
    assert (
        tool_main(
            "validate_publication_reconciliation.py",
            ["--record", str(malformed_reconciliation_path)],
        )
        == 3
    )

    promotion_path.unlink()
    assert tool_main("validate_publication_reconciliation.py", argv) == 3


@pytest.mark.parametrize("name", sorted(TOOL_NAMES))
def test_every_release_tool_exposes_its_declarative_contract(name: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / name), "--help"],
        cwd=ROOT,
        env=_tool_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    contract = TOOL_CONTRACTS[name]
    for flag in sorted(contract.flags):
        assert f"--{flag}" in completed.stdout
    for flag, values in contract.choices.items():
        assert f"--{flag}" in completed.stdout
        for value in values:
            assert value in completed.stdout

    if not contract.delegated_adapter:
        assert "--output" not in completed.stdout
    if name.startswith("validate_") and contract.record_flag == "record":
        assert "--record" in completed.stdout
        if "input" not in contract.flags:
            assert "--input" not in completed.stdout


@pytest.mark.parametrize("name", sorted(TOOL_NAMES))
def test_every_release_tool_rejects_unknown_and_missing_arguments(
    name: str, tmp_path: Path
) -> None:
    contract = TOOL_CONTRACTS[name]
    argv = _contract_argv(name, tmp_path / f"{name}.json")
    command = [sys.executable, str(ROOT / "tools" / name)]

    unknown = subprocess.run(
        [*command, *argv, "--not-a-section-9b-flag"],
        cwd=ROOT,
        env=_tool_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert unknown.returncode == 2
    assert "unrecognized arguments" in unknown.stderr

    removed_flag = min(contract.forms[0].required)
    missing = subprocess.run(
        [
            *command,
            *_remove_argument(argv, removed_flag, boolean=removed_flag in contract.boolean),
        ],
        cwd=ROOT,
        env=_tool_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2

    if not contract.delegated_adapter:
        value_flag = min(
            flag for flag in contract.forms[0].required if flag not in contract.boolean
        )
        blank = list(argv)
        blank[blank.index(f"--{value_flag}") + 1] = ""
        empty_value = subprocess.run(
            [*command, *blank],
            cwd=ROOT,
            env=_tool_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert empty_value.returncode == 2
        assert "cannot be empty" in empty_value.stderr or "invalid choice" in empty_value.stderr


@pytest.mark.parametrize(
    "name",
    sorted(
        name
        for name, contract in TOOL_CONTRACTS.items()
        if len(contract.forms) > 1 and not contract.delegated_adapter
    ),
)
def test_release_tool_forms_reject_cross_mode_flags(name: str, tmp_path: Path) -> None:
    contract = TOOL_CONTRACTS[name]
    first_form = contract.forms[0]
    foreign_flag = next(
        flag
        for form in contract.forms[1:]
        for flag in sorted(form.required)
        if flag not in first_form.required and flag not in contract.optional
    )
    argv = _contract_argv(name, tmp_path / f"{name}.json")
    argv.append(f"--{foreign_flag}")
    if foreign_flag not in contract.boolean:
        if foreign_flag in contract.choices:
            argv.append(contract.choices[foreign_flag][0])
        elif foreign_flag in contract.integer:
            argv.append("1")
        else:
            argv.append("fixture-value")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / name), *argv],
        cwd=ROOT,
        env=_tool_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "do not satisfy any documented" in completed.stderr


@pytest.mark.parametrize(
    "name", sorted(name for name, contract in TOOL_CONTRACTS.items() if contract.choices)
)
def test_every_documented_release_choice_is_enforced(name: str, tmp_path: Path) -> None:
    contract = TOOL_CONTRACTS[name]
    flag = min(contract.choices)
    form_index = next(index for index, form in enumerate(contract.forms) if flag in form.required)
    argv = _contract_argv(name, tmp_path / f"{name}.json", form_index=form_index)
    marker = f"--{flag}"
    index = argv.index(marker)
    argv[index + 1] = "not-a-documented-choice"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / name), *argv],
        cwd=ROOT,
        env=_tool_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr


@pytest.mark.parametrize(
    "name",
    sorted(
        name
        for name, contract in TOOL_CONTRACTS.items()
        if contract.fixture_producer and not contract.delegated_adapter
    ),
)
def test_every_shared_producer_is_deterministic_and_no_overwrite(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / f"{name}.json"
    argv = _contract_argv(name, output)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")

    assert tool_main(name, argv) == 0
    first_bytes = output.read_bytes()
    assert tool_main(name, argv) == 3
    assert output.read_bytes() == first_bytes


def test_provider_release_tool_is_blocked_without_real_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = "capture_release_target_observations.py"
    output = tmp_path / "observations.json"
    assert tool_main(name, _contract_argv(name, output)) == 3
    assert not output.exists()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED_NOT_READY"
    assert "authority" in result["reason"]


def test_release_artifact_adapter_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "tools/build_release_artifacts.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "--manifest" in completed.stdout


def test_release_artifact_validator_binds_every_publishable_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    wheel = artifacts / "metriplane-0.4.0-py3-none-any.whl"
    sdist = artifacts / "metriplane-0.4.0.tar.gz"
    wheel.write_bytes(b"wheel-bytes")
    sdist.write_bytes(b"sdist-bytes")
    rows = [
        {
            "media_type": "application/vnd.pypa.wheel+zip",
            "path": wheel.name,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "size": wheel.stat().st_size,
        },
        {
            "media_type": "application/gzip",
            "path": sdist.name,
            "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
            "size": sdist.stat().st_size,
        },
    ]
    manifest = make_record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": sha256_json(rows),
            "artifacts": rows,
            "build_invocation_id": "artifact-build-fixture",
            "build_recipe_digest": "a" * 64,
            "milestone": "v0.4",
            "source_digest": "b" * 64,
            "source_freeze_digest": "c" * 64,
            "target_resolution_digest": "d" * 64,
        },
        invocation_id="artifact-manifest-fixture",
        sequence=1,
        synthetic=True,
    )
    manifest_path = tmp_path / "artifact-manifest.json"
    write_immutable_json(manifest_path, manifest)
    argv = [
        "--record",
        str(manifest_path),
        "--artifacts",
        str(artifacts),
        "--read-hash",
    ]
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    assert tool_main("validate_release_artifact_manifest.py", argv) == 0
    blocked_manifest = make_record(
        "release-artifact-manifest",
        manifest["data"],
        invocation_id="artifact-manifest-blocked-fixture",
        sequence=1,
        synthetic=True,
        status="BLOCKED",
    )
    blocked_manifest_path = tmp_path / "artifact-manifest-blocked.json"
    write_immutable_json(blocked_manifest_path, blocked_manifest)
    argv[1] = str(blocked_manifest_path)
    assert tool_main("validate_release_artifact_manifest.py", argv) == 3
    argv[1] = str(manifest_path)
    wheel.write_bytes(b"rebuilt-wheel")
    assert tool_main("validate_release_artifact_manifest.py", argv) == 3


def test_release_retention_validator_reads_two_independent_store_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    retained = make_record(
        "release-qualification",
        {"candidate_digest": "a" * 64},
        invocation_id="retained-input-fixture",
        sequence=1,
        synthetic=True,
    )
    retained_path = tmp_path / "retained.json"
    input_digest = write_immutable_json(retained_path, retained)
    stores = [
        {
            "content_digest": input_digest,
            "hold_receipt_digest": "a" * 64,
            "independence_group": "provider-a",
            "namespace": "release-a",
            "object_key": "candidate/input.json",
            "put_receipt_digest": "b" * 64,
            "read_back_digest": input_digest,
            "store_id": "payload-store-a",
        },
        {
            "content_digest": input_digest,
            "hold_receipt_digest": "c" * 64,
            "independence_group": "provider-b",
            "namespace": "release-b",
            "object_key": "candidate/input.json",
            "put_receipt_digest": "d" * 64,
            "read_back_digest": input_digest,
            "store_id": "payload-store-b",
        },
    ]
    receipt = make_record(
        "release-retention-receipts",
        {
            "all_content_equal": True,
            "input_digest": input_digest,
            "phase": "prepublication",
            "receipt_set_digest": sha256_json(stores),
            "retained_at": "2026-08-27T00:00:00Z",
            "stores": stores,
        },
        invocation_id="retention-receipts-fixture",
        sequence=1,
        synthetic=True,
    )
    receipt_path = tmp_path / "receipts.json"
    write_immutable_json(receipt_path, receipt)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    assert (
        tool_main(
            "validate_release_retention.py",
            ["--input", str(retained_path), "--receipts", str(receipt_path), "--read-back"],
        )
        == 0
    )

    wrong_stores = [dict(row) for row in stores]
    wrong_stores[1]["read_back_digest"] = "e" * 64
    wrong_receipt = make_record(
        "release-retention-receipts",
        {
            "all_content_equal": True,
            "input_digest": input_digest,
            "phase": "prepublication",
            "receipt_set_digest": sha256_json(wrong_stores),
            "retained_at": "2026-08-27T00:00:00Z",
            "stores": wrong_stores,
        },
        invocation_id="retention-receipts-mismatch",
        sequence=1,
        synthetic=True,
    )
    wrong_path = tmp_path / "wrong-receipts.json"
    write_immutable_json(wrong_path, wrong_receipt)
    assert (
        tool_main(
            "validate_release_retention.py",
            ["--input", str(retained_path), "--receipts", str(wrong_path), "--read-back"],
        )
        == 3
    )


def test_release_readiness_can_reach_ready_only_from_cross_bound_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "a" * 64
    registry = {
        "blockers": [],
        "evidence_resolution": {"status": "READY"},
        "framework": "READY",
        "live_release": "READY",
    }
    predecessor = make_record(
        "release-predecessor",
        {
            "candidate_milestone": "v0.4",
            "closed_decision_digest": "b" * 64,
            "lkg_digest": "c" * 64,
            "version": "v0.3.0",
        },
        invocation_id="readiness-predecessor",
        sequence=1,
        synthetic=True,
    )
    linear = make_record(
        "linear-release-snapshot",
        {
            "required_bom_ids": ["MET-154"],
            "required_bom_snapshot_digest": sha256_json(["MET-154"]),
            "state": "In Progress",
            "task_id": "MET-154",
            "tool": "linear",
        },
        invocation_id="readiness-linear-snapshot",
        sequence=1,
        synthetic=True,
    )
    gate_input = make_record(
        "release-gate-input",
        {
            "environment_registry_digest": "7" * 64,
            "evidence_store_registry_digest": "c" * 64,
            "expected_predecessor_milestone": "v0.3",
            "gate_input_digest": "4" * 64,
            "linear_snapshot_digest": sha256_json(linear),
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "readiness_registry_digest": sha256_json(registry),
            "role_assignments_digest": "6" * 64,
            "run_id": "readiness-run",
            "scenario_registry_digest": "a" * 64,
            "target_burn_digest": "b" * 64,
            "target_burn_index_receipt_digest": None,
            "target_registry_digest": "1" * 64,
            "target_resolution_digest": "2" * 64,
            "task_state_policy_digest": "2" * 64,
        },
        invocation_id="readiness-gate-input",
        sequence=1,
        synthetic=True,
    )
    source_freeze = make_record(
        "release-source-freeze",
        {
            "build_recipe_digest": "e" * 64,
            "dirty": False,
            "freeze_digest": "f" * 64,
            "frozen_at": "2026-08-25T12:00:00Z",
            "gate_input_digest": sha256_json(gate_input),
            "milestone": "v0.4",
            "registry_inputs": [
                {
                    "path": "docs/status/release-readiness.json",
                    "schema_id": "release-readiness",
                    "sha256": sha256_json(registry),
                }
            ],
            "release_notes_digest": "3" * 64,
            "source_sha": "1" * 40,
            "source_tree": "2" * 40,
            "version_metadata_digest": "4" * 64,
            "workflow_inputs": [
                {
                    "path": ".github/workflows/release-required.yml",
                    "schema_id": "github-workflow",
                    "sha256": "5" * 64,
                }
            ],
        },
        invocation_id="readiness-source-freeze",
        sequence=1,
        synthetic=True,
    )
    impact_manifest = make_record(
        "release-impact-manifest",
        {
            "author_id": "readiness-author",
            "base_sha": "0" * 40,
            "changes": [],
            "head_sha": "1" * 40,
            "manifest_digest": "6" * 64,
            "milestone": "v0.4",
            "release_tag": "v0.4.0",
            "source_freeze_digest": sha256_json(source_freeze),
            "target_resolution_digest": "2" * 64,
            "unclassified_paths": [],
        },
        invocation_id="readiness-impact-manifest",
        sequence=1,
        synthetic=True,
    )
    artifact_rows = [
        {
            "media_type": "application/vnd.pypa.wheel+zip",
            "path": "metriplane-0.4.0-py3-none-any.whl",
            "sha256": "d" * 64,
            "size": 10,
        },
        {
            "media_type": "application/gzip",
            "path": "metriplane-0.4.0.tar.gz",
            "sha256": "e" * 64,
            "size": 11,
        },
    ]
    artifact_set_digest = sha256_json(artifact_rows)
    artifact = make_record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": artifact_set_digest,
            "artifacts": artifact_rows,
            "build_invocation_id": "readiness-artifact-build",
            "build_recipe_digest": "e" * 64,
            "milestone": "v0.4",
            "source_digest": "f" * 64,
            "source_freeze_digest": sha256_json(source_freeze),
            "target_resolution_digest": "2" * 64,
        },
        invocation_id="readiness-artifact-manifest",
        sequence=1,
        synthetic=True,
    )
    candidate = make_record(
        "release-candidate-identity",
        {
            "artifact_manifest_digest": sha256_json(artifact),
            "artifact_set_digest": artifact_set_digest,
            "build_invocation_id": "readiness-artifact-build",
            "candidate_digest": "3" * 64,
            "evaluation_adoption_digest": None,
            "evaluation_adoption_mode": "none",
            "gate_input_digest": sha256_json(gate_input),
            "milestone": "v0.4",
            "package_version": "v0.4.0",
            "predecessor_digest": sha256_json(predecessor),
            "release_tag": "v0.4.0",
            "source_freeze_digest": sha256_json(source_freeze),
        },
        invocation_id="readiness-candidate",
        sequence=1,
        synthetic=True,
    )
    delta = make_record(
        "release-capability-delta",
        {
            "added": [],
            "candidate_sha": "1" * 40,
            "changed": [
                {
                    "after_digest": "7" * 64,
                    "before_digest": "6" * 64,
                    "capability_id": "release-framework",
                }
            ],
            "delta_digest": "5" * 64,
            "impact_manifest_digest": sha256_json(impact_manifest),
            "milestone": "v0.4",
            "predecessor_digest": sha256_json(predecessor),
            "removed": [],
        },
        invocation_id="readiness-delta",
        sequence=1,
        synthetic=True,
    )
    delta_map = make_record(
        "release-delta-test-map",
        {
            "delta_digest": "5" * 64,
            "environment_registry_digest": "7" * 64,
            "impact_manifest_digest": sha256_json(impact_manifest),
            "map_digest": "8" * 64,
            "mappings": [
                {
                    "capability_id": "release-framework",
                    "environment_ids": ["ubuntu-24.04-py312"],
                    "obligation_ids": ["MP2-007.A01"],
                    "scenario_ids": ["hard-runner-loss"],
                }
            ],
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "scenario_registry_digest": "a" * 64,
            "unmapped_capabilities": [],
        },
        invocation_id="readiness-delta-map",
        sequence=1,
        synthetic=True,
    )
    gate = make_record(
        "release-gate-instance",
        {
            "candidate_digest": "3" * 64,
            "candidate_identity_digest": sha256_json(candidate),
            "environment_registry_digest": "7" * 64,
            "evidence_store_preflight_digest": "b" * 64,
            "evidence_store_registry_digest": "c" * 64,
            "frozen_source_sha": "1" * 40,
            "gate_input_digest": sha256_json(gate_input),
            "instance_digest": digest,
            "linear_snapshot_digest": sha256_json(linear),
            "main_health_digest": "d" * 64,
            "main_health_history_digest": "e" * 64,
            "milestone": "v0.4",
            "obligation_registry_digest": "9" * 64,
            "package_version": "v0.4.0",
            "predecessor_digest": sha256_json(predecessor),
            "release_tag": "v0.4.0",
            "repository_protection_digest": "f" * 64,
            "run_id": "readiness-run",
            "scenario_registry_digest": "a" * 64,
            "target_registry_digest": "1" * 64,
            "task_state_policy_digest": "2" * 64,
        },
        invocation_id="readiness-gate",
        sequence=1,
        synthetic=True,
    )
    records = {
        "artifact-manifest": artifact,
        "candidate-identity": candidate,
        "delta-test-map": delta_map,
        "delta": delta,
        "gate-input": gate_input,
        "gate-instance": gate,
        "impact-manifest": impact_manifest,
        "linear-snapshot": linear,
        "predecessor": predecessor,
        "source-freeze": source_freeze,
    }
    paths: dict[str, Path] = {}
    for name, record in records.items():
        path = tmp_path / f"{name}.json"
        write_immutable_json(path, record)
        paths[name] = path
    status = tmp_path / "docs/status"
    status.mkdir(parents=True)
    (status / "release-readiness.json").write_text(json.dumps(registry), encoding="utf-8")
    argv = [
        "--gate-instance",
        str(paths["gate-instance"]),
        "--candidate-identity",
        str(paths["candidate-identity"]),
        "--predecessor",
        str(paths["predecessor"]),
        "--linear-snapshot",
        str(paths["linear-snapshot"]),
        "--artifact-manifest",
        str(paths["artifact-manifest"]),
        "--delta",
        str(paths["delta"]),
        "--delta-test-map",
        str(paths["delta-test-map"]),
        "--out",
        str(tmp_path / "ready.json"),
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    assert tool_main("check_release_readiness.py", argv) == 0
    assert json.loads((tmp_path / "ready.json").read_text())["data"]["disposition"] == "READY"

    mutation_cases: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for label, field, value in (
        ("gate-input", "gate_input_digest", "f" * 64),
        ("package-version", "package_version", "v0.4.1"),
        ("release-tag", "release_tag", "v0.4.1"),
        ("artifact-set", "artifact_set_digest", "e" * 64),
        ("build-invocation", "build_invocation_id", "different-artifact-build"),
        ("source-freeze", "source_freeze_digest", "9" * 64),
    ):
        changed_candidate = make_record(
            "release-candidate-identity",
            {**candidate["data"], field: value},
            invocation_id=f"readiness-{label}-candidate",
            sequence=1,
            synthetic=True,
        )
        changed_gate = make_record(
            "release-gate-instance",
            {
                **gate["data"],
                "candidate_identity_digest": sha256_json(changed_candidate),
            },
            invocation_id=f"readiness-{label}-gate",
            sequence=1,
            synthetic=True,
        )
        mutation_cases.append((label, changed_gate, changed_candidate, delta_map))
    for label, field, value in (
        ("impact-manifest", "impact_manifest_digest", "7" * 64),
        ("malformed-mappings", "mappings", None),
        (
            "mismatched-mappings",
            "mappings",
            [
                {
                    "capability_id": "different-capability",
                    "environment_ids": ["ubuntu-24.04-py312"],
                    "obligation_ids": ["MP2-007.A01"],
                    "scenario_ids": ["hard-runner-loss"],
                }
            ],
        ),
        ("unmapped", "unmapped_capabilities", ["unmapped-capability"]),
    ):
        changed_map = make_record(
            "release-delta-test-map",
            {**delta_map["data"], field: value},
            invocation_id=f"readiness-{label}-map",
            sequence=1,
            synthetic=True,
        )
        mutation_cases.append((label, gate, candidate, changed_map))
    for _label, changed_gate, changed_candidate, changed_map in mutation_cases:
        with pytest.raises(ReleaseControlError, match="readiness"):
            build_release_readiness_record(
                gate_input=gate_input,
                gate_instance=changed_gate,
                candidate_identity_record=changed_candidate,
                predecessor=predecessor,
                linear_snapshot=linear,
                source_freeze=source_freeze,
                impact_manifest=impact_manifest,
                artifact_manifest=artifact,
                delta=delta,
                delta_test_map=changed_map,
                readiness_registry=registry,
            )

    changed_candidate = make_record(
        "release-candidate-identity",
        {
            **candidate["data"],
            "package_version": "v0.4.1",
            "release_tag": "v0.4.1",
        },
        invocation_id="readiness-coordinated-version-candidate",
        sequence=1,
        synthetic=True,
    )
    changed_impact = make_record(
        "release-impact-manifest",
        {**impact_manifest["data"], "release_tag": "v0.4.1"},
        invocation_id="readiness-coordinated-version-impact",
        sequence=1,
        synthetic=True,
    )
    changed_delta = make_record(
        "release-capability-delta",
        {**delta["data"], "impact_manifest_digest": sha256_json(changed_impact)},
        invocation_id="readiness-coordinated-version-delta",
        sequence=1,
        synthetic=True,
    )
    changed_map = make_record(
        "release-delta-test-map",
        {**delta_map["data"], "impact_manifest_digest": sha256_json(changed_impact)},
        invocation_id="readiness-coordinated-version-map",
        sequence=1,
        synthetic=True,
    )
    changed_gate = make_record(
        "release-gate-instance",
        {
            **gate["data"],
            "candidate_identity_digest": sha256_json(changed_candidate),
            "package_version": "v0.4.1",
            "release_tag": "v0.4.1",
        },
        invocation_id="readiness-coordinated-version-gate",
        sequence=1,
        synthetic=True,
    )
    with pytest.raises(ReleaseControlError, match="artifact filenames"):
        build_release_readiness_record(
            gate_input=gate_input,
            gate_instance=changed_gate,
            candidate_identity_record=changed_candidate,
            predecessor=predecessor,
            linear_snapshot=linear,
            source_freeze=source_freeze,
            impact_manifest=changed_impact,
            artifact_manifest=artifact,
            delta=changed_delta,
            delta_test_map=changed_map,
            readiness_registry=registry,
        )

    for field, value in (
        ("state", "Done"),
        ("task_id", "MET-999"),
        ("tool", "fabricated"),
    ):
        changed_linear = make_record(
            "linear-release-snapshot",
            {**linear["data"], field: value},
            invocation_id=f"readiness-invalid-linear-{field}",
            sequence=1,
            synthetic=True,
        )
        with pytest.raises(ReleaseControlError, match="Linear"):
            build_release_readiness_record(
                gate_input=gate_input,
                gate_instance=gate,
                candidate_identity_record=candidate,
                predecessor=predecessor,
                linear_snapshot=changed_linear,
                source_freeze=source_freeze,
                impact_manifest=impact_manifest,
                artifact_manifest=artifact,
                delta=delta,
                delta_test_map=delta_map,
                readiness_registry=registry,
            )

    registry["blockers"] = [{"code": "MISSING_LIVE_EVIDENCE"}]
    registry["framework"] = "BLOCKED_NOT_READY"
    (status / "release-readiness.json").write_text(json.dumps(registry), encoding="utf-8")
    argv[-1] = str(tmp_path / "blocked.json")
    assert tool_main("check_release_readiness.py", argv) == 3
    assert not (tmp_path / "blocked.json").exists()


def test_release_fixtures_are_exact_and_valid_fixtures_are_digest_bound() -> None:
    expected = {
        "invalid/artifact-mismatch.json",
        "invalid/partial-publication.json",
        "invalid/self-approved-live.json",
        "invalid/stale-lock.json",
        "invalid/synthetic-live-approval.json",
        "invalid/unauthorized-tag.json",
        "invalid/unknown-terminal.json",
        "valid/fake-linear-snapshot.json",
        "valid/fake-provider-termination.json",
        "valid/fake-target-observations.json",
        "valid/synthetic-approval.json",
        "valid/synthetic-role-assignments.json",
        "valid/v0.3.0-predecessor.json",
    }
    root = ROOT / "tests/fixtures/release"
    observed = {path.relative_to(root).as_posix() for path in root.rglob("*.json")}
    assert observed == expected
    for path in sorted((root / "valid").glob("*.json")):
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        validate_record(record)
        schema = json.loads(_schema_path(record["record_type"]).read_text(encoding="utf-8"))
        assert schema["properties"]["record_type"]["const"] == record["record_type"]
        assert set(record) == set(schema["required"])


def test_cumulative_registry_and_obligation_membership_are_exact() -> None:
    targets = json.loads((STATUS / "release-targets.json").read_text(encoding="utf-8"))
    assert tuple(item["id"] for item in targets["milestones"]) == MILESTONES
    assert all(
        item["required_targets"] == ["github-release", "pypi", "testpypi"]
        for item in targets["milestones"]
    )

    obligations = json.loads((STATUS / "release-test-obligations.json").read_text(encoding="utf-8"))
    rows = obligations["obligations"]
    assert [row["id"] for row in rows] == [f"MP2-007.A{number:02d}" for number in range(1, 14)]
    assert all(row["families"] for row in rows)
    assert all("::test_mp2_007_" in row["node_id"] for row in rows)
    assert all(
        row["result"].endswith(f"/{number:02d}-result.json") for number, row in enumerate(rows, 1)
    )
    assert "tests/test_release_contracts.py" in " ".join(obligations["commands"])
    assert "tests/test_release_workflow.py" in " ".join(obligations["commands"])


def test_framework_readiness_cannot_claim_live_release_ready() -> None:
    readiness = json.loads((STATUS / "release-readiness.json").read_text(encoding="utf-8"))
    stores = json.loads((STATUS / "release-evidence-stores.json").read_text(encoding="utf-8"))
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
        "EXTERNAL_TWO_STORE_READBACK_AND_CAS_PROOF_REQUIRED",
        "HOSTED_PROTECTION_AND_REAL_MERGE_PROOF_REQUIRED",
        "LIVE_NON_AUTHOR_APPROVAL_REQUIRED",
        "MP2_007_RESULT_EVIDENCE_ABSENT",
        "MP2_018_POPULATED_INVENTORY_REQUIRED",
    }
    assert stores["live_status"] == "BLOCKED_NOT_READY"
    assert all(store["live_binding"] is None for store in stores["stores"])
    assert stores["attempt_index"]["backend"] is None


def test_v030_genesis_is_the_exact_observed_predecessor() -> None:
    genesis = json.loads((ROOT / "docs/releases/v0.3.0-genesis.json").read_text(encoding="utf-8"))
    assert genesis == {
        "annotated_tag_object": "ef808e9834e1b5ba1a310888e8955b3121977963",
        "authority": "historical-observation",
        "commit": "e8ee6c63deaee47bd450c5d6c7523d5bd699852a",
        "schema_version": "metriplane.release-genesis.v1",
        "synthetic": False,
        "tree": "931257abdb16dcd54522d7947c67443ed8ff6683",
        "version": "v0.3.0",
    }
