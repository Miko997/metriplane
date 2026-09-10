# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Gate input boundary tests; complete graph/producer cases join this owned file."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import signal
import shutil
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from metriplane import release_control as release


@pytest.mark.parametrize(
    "tool",
    [
        "build_publication_reconciliation.py",
        "capture_release_target_observations.py",
        "check_release_readiness.py",
        "collect_publication_observations.py",
        "export_release_attempt_index.py",
        "execute_release_qualification.py",
        "plan_release_qualification.py",
        "record_release_approval.py",
        "record_postpublication_conflict.py",
        "record_release_role_assignments.py",
        "resolve_release_predecessor.py",
        "retain_release_evidence.py",
        "update_release_attempt_index.py",
        "validate_release_evidence_stores.py",
        "validate_publication_reconciliation.py",
        "validate_release_approval.py",
        "validate_release_gate_instance.py",
        "validate_release_predecessor.py",
        "validate_release_qualification.py",
        "validate_release_qualification_plan.py",
        "validate_release_retention.py",
        "validate_release_role_assignments.py",
    ],
)
def test_implemented_release_route_has_actual_public_adapter(tool: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / tool), "--help"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "section 9.B" in completed.stdout


def _qualification_plan_command_fixture(
    tmp_path: Path, *, mutation: str | None = None
) -> tuple[Path, list[str]]:
    root = tmp_path / "qualification-plan-run"
    root.mkdir()
    scenario_raw = release.canonical_json({"scenarios": [{"id": "SCN-1"}]})
    manifest = release.make_record(
        "release-artifact-manifest",
        {"milestone": "v0.4"},
        invocation_id="fixture-artifact-manifest",
        sequence=1,
        synthetic=True,
    )
    predecessor = release.make_record(
        "release-predecessor",
        {"candidate_milestone": "v0.4"},
        invocation_id="fixture-predecessor",
        sequence=1,
        synthetic=True,
    )
    delta = release.make_record(
        "release-capability-delta",
        {"delta_digest": "1" * 64},
        invocation_id="fixture-delta",
        sequence=1,
        synthetic=True,
    )
    delta_map_data = {
        "delta_digest": delta["data"]["delta_digest"],
        "map_digest": "2" * 64,
        "mappings": [
            {
                "environment_ids": ["linux-py312"],
                "obligation_ids": ["OBL-1"],
                "scenario_ids": ["SCN-1"],
            }
        ],
        "unmapped_capabilities": [],
    }
    if mutation == "unmapped-cell":
        delta_map_data["mappings"][0]["scenario_ids"] = ["SCN-substituted"]
    elif mutation == "malformed-mapping":
        delta_map_data["mappings"][0]["environment_ids"] = "linux-py312"
    delta_map = release.make_record(
        "release-delta-test-map",
        delta_map_data,
        invocation_id="fixture-delta-map",
        sequence=1,
        synthetic=True,
    )
    catalog_data = {
        "release_slots": [{"milestone": "v0.4", "qualification_attempts_required": 2}],
        "execution_units": [
            {
                "unit_id": "v0.4:qualification:linux-py312:SCN-1",
                "slot_milestone": "v0.4",
                "phase": "qualification",
                "environment_id": "linux-py312",
                "profile_id": "release",
                "scenario_id": "SCN-1",
                "obligation_ids": ["OBL-1"],
                "prerequisite_unit_ids": [],
                "qualification_unit_terminal_on_verified_expectation": "PASS",
            }
        ],
        "scenario_registry_digest": release.sha256_bytes(scenario_raw),
        "unresolved_declarations": [],
    }
    if mutation == "unresolved-catalog":
        catalog_data["unresolved_declarations"] = [{"id": "missing-executor"}]
    catalog_data["catalog_digest"] = release.sha256_json(catalog_data)
    catalog = release.make_record(
        "release-scenario-catalog",
        catalog_data,
        invocation_id="fixture-scenario-catalog",
        sequence=1,
        synthetic=True,
    )
    candidate = release.make_record(
        "release-candidate-identity",
        {
            "artifact_manifest_digest": release.sha256_json(manifest),
            "candidate_digest": "3" * 64,
            "milestone": "v0.4",
        },
        invocation_id="fixture-candidate",
        sequence=1,
        synthetic=True,
    )
    gate = release.make_record(
        "release-gate-instance",
        {
            "candidate_digest": candidate["data"]["candidate_digest"],
            "instance_digest": "4" * 64,
            "milestone": "v0.4",
            "predecessor_digest": release.sha256_json(predecessor),
            "scenario_catalog_digest": release.sha256_json(catalog),
        },
        invocation_id="fixture-gate",
        sequence=1,
        synthetic=True,
    )
    readiness = release.make_record(
        "release-readiness",
        {
            "candidate_digest": candidate["data"]["candidate_digest"],
            "delta_digest": delta["data"]["delta_digest"],
            "delta_test_map_digest": delta_map["data"]["map_digest"],
            "disposition": "READY",
            "gate_instance_digest": gate["data"]["instance_digest"],
            "predecessor_digest": release.sha256_json(predecessor),
            "unresolved_blockers": [],
        },
        invocation_id="fixture-readiness",
        sequence=1,
        synthetic=True,
    )
    records = {
        "artifact-manifest.json": manifest,
        "candidate-identity.json": candidate,
        "delta-test-map.json": delta_map,
        "delta.json": delta,
        "gate-instance.json": gate,
        "predecessor.json": predecessor,
        "readiness.json": readiness,
        "scenario-catalog.json": catalog,
    }
    if mutation == "stale-manifest":
        records["artifact-manifest.json"] = release.make_record(
            "release-artifact-manifest",
            {"milestone": "v0.4", "substituted": True},
            invocation_id="fixture-artifact-manifest-substituted",
            sequence=1,
            synthetic=True,
        )
    for name, record in records.items():
        (root / name).write_bytes(release.canonical_json(record))
    (root / "scenarios.json").write_bytes(
        b'{"scenarios":[{"id":"substituted"}]}'
        if mutation == "raw-scenario-substitution"
        else scenario_raw
    )
    argv = [
        "--gate-instance",
        str(root / "gate-instance.json"),
        "--candidate-identity",
        str(root / "candidate-identity.json"),
        "--predecessor",
        str(root / "predecessor.json"),
        "--readiness",
        str(root / "readiness.json"),
        "--delta",
        str(root / "delta.json"),
        "--delta-test-map",
        str(root / "delta-test-map.json"),
        "--scenarios",
        str(root / "scenarios.json"),
        "--candidate-manifest",
        str(root / "artifact-manifest.json"),
        "--out",
        str(root / "qualification-plan.json"),
        "--invocation-dir",
        str(root / "invocations/plan-release-qualification/001"),
    ]
    return root, argv


def _run_release_tool(tool: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
    repository = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["METRIPLANE_RELEASE_FIXTURE_MODE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(repository), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, str(repository / "tools" / tool), *argv],
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_qualification_plan_public_command_produces_consumable_complete_plan(
    tmp_path: Path,
) -> None:
    root, argv = _qualification_plan_command_fixture(tmp_path)
    completed = _run_release_tool("plan_release_qualification.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    plan_path = root / "qualification-plan.json"
    plan = release.read_json(plan_path)
    assert plan["data"]["attempt_count"] == 2
    assert [cell["cell_id"] for cell in plan["data"]["cells"]] == [
        "v0.4:qualification:linux-py312:SCN-1"
    ]
    validator = _run_release_tool(
        "validate_release_qualification_plan.py",
        [
            "--record",
            str(plan_path),
            "--gate-instance",
            str(root / "gate-instance.json"),
            "--invocation-dir",
            str(root / "invocations/validate-release-qualification-plan/001"),
        ],
    )
    assert validator.returncode == 0, validator.stderr or validator.stdout
    original = plan_path.read_bytes()
    retry_argv = list(argv)
    retry_argv[-1] = str(root / "invocations/plan-release-qualification/002")
    retry = _run_release_tool("plan_release_qualification.py", retry_argv)
    assert retry.returncode != 0
    assert plan_path.read_bytes() == original


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed-mapping",
        "raw-scenario-substitution",
        "stale-manifest",
        "unmapped-cell",
        "unresolved-catalog",
    ],
)
def test_qualification_plan_public_command_rejects_substituted_or_incomplete_inputs(
    tmp_path: Path, mutation: str
) -> None:
    root, argv = _qualification_plan_command_fixture(tmp_path, mutation=mutation)
    completed = _run_release_tool("plan_release_qualification.py", argv)
    assert completed.returncode != 0
    assert not (root / "qualification-plan.json").exists()


def test_public_approval_command_materializes_and_validates_signed_non_author_decision(
    tmp_path: Path,
) -> None:
    roles = release.make_record(
        "release-role-assignments",
        {
            "author_id": "fixture-author",
            "authorized_executor_id": "fixture-operator",
            "milestone": "v0.4",
            "non_author_reviewer_id": "fixture-reviewer",
            "publisher_id": "fixture-publisher",
            "run_id": "fixture-approval-run",
            "task_id": "MP2-007",
        },
        invocation_id="fixture-approval-roles",
        sequence=1,
        synthetic=True,
    )
    actors = release.validate_role_assignments(
        roles,
        live=False,
    )
    candidate_digest = "7" * 64
    root = tmp_path / "approval-run"
    root.mkdir()
    gate = release.make_record(
        "release-gate-instance",
        {
            "candidate_digest": candidate_digest,
            "milestone": "v0.4",
            "run_id": roles["data"]["run_id"],
        },
        invocation_id="fixture-approval-gate",
        sequence=1,
        synthetic=True,
    )
    qualification = release.make_record(
        "release-qualification",
        {"candidate_digest": candidate_digest},
        invocation_id="fixture-approval-qualification",
        sequence=1,
        synthetic=True,
    )
    decision_data = {
        "approval_kind": "non_author_release_decision",
        "author_id": actors["author_id"][1],
        "authority_policy_digest": "8" * 64,
        "candidate_digest": candidate_digest,
        "conflicts": [],
        "decision": "APPROVED",
        "expires_at": "2026-01-01T01:00:00Z",
        "issued_at": "2026-01-01T00:00:00Z",
        "milestone": "v0.4",
        "qualification_digest": release.sha256_json(qualification),
        "reviewer_id": actors["non_author_reviewer_id"][1],
        "rubric_result_digest": None,
        "signing_method": "provider-attestation-v1",
    }
    unsigned = release.make_record(
        "release-approval-decision",
        decision_data,
        invocation_id="fixture-signed-approval-decision",
        sequence=1,
        synthetic=True,
    )
    subject_digest = release.signature_subject_digest(unsigned)
    signature = {
        "actor_id": actors["non_author_reviewer_id"][1],
        "algorithm": "test-sha256-v1",
        "provider": "test-fixture",
        "signature": release.sha256_json(
            {"actor_id": actors["non_author_reviewer_id"][1], "subject_digest": subject_digest}
        ),
        "subject_digest": subject_digest,
        "synthetic": True,
    }
    decision = release.make_record(
        "release-approval-decision",
        decision_data,
        invocation_id="fixture-signed-approval-decision",
        sequence=1,
        synthetic=True,
        signatures=[signature],
    )
    for name, record in {
        "approval-decision.json": decision,
        "gate-instance.json": gate,
        "qualification.json": qualification,
        "role-assignments.json": roles,
    }.items():
        (root / name).write_bytes(release.canonical_json(record))
    argv = [
        "--gate-instance",
        str(root / "gate-instance.json"),
        "--qualification",
        str(root / "qualification.json"),
        "--role-assignments",
        str(root / "role-assignments.json"),
        "--no-prepublication-rubric",
        "--signed-decision",
        str(root / "approval-decision.json"),
        "--out",
        str(root / "approval.json"),
        "--invocation-dir",
        str(root / "invocations/record-release-approval/001"),
    ]
    substituted = release.make_record(
        "release-qualification",
        {"candidate_digest": "9" * 64},
        invocation_id="fixture-substituted-qualification",
        sequence=1,
        synthetic=True,
    )
    (root / "qualification.json").write_bytes(release.canonical_json(substituted))
    rejected = _run_release_tool("record_release_approval.py", argv)
    assert rejected.returncode != 0
    assert not (root / "approval.json").exists()

    (root / "qualification.json").write_bytes(release.canonical_json(qualification))
    retry_argv = [
        value.replace("record-release-approval/001", "record-release-approval/002")
        for value in argv
    ]
    completed = _run_release_tool("record_release_approval.py", retry_argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    approval = release.read_json(root / "approval.json")
    assert approval["signatures"] == []
    release.validate_release_approval_record(
        approval,
        approval_decision=decision,
        gate_instance=gate,
        qualification=qualification,
        role_assignments=roles,
        no_prepublication_rubric=True,
        live=False,
    )
    original = (root / "approval.json").read_bytes()
    duplicate_argv = [
        value.replace("record-release-approval/002", "record-release-approval/003")
        for value in retry_argv
    ]
    duplicate = _run_release_tool("record_release_approval.py", duplicate_argv)
    assert duplicate.returncode != 0
    assert (root / "approval.json").read_bytes() == original


def _promotion_plan_command_fixture(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "promotion-run"
    root.mkdir()
    candidate_digest = "7" * 64
    genesis_raw = b'{"schema_version":"metriplane.release-attempt-index-genesis.v1"}\n'
    roles = release.make_record(
        "release-role-assignments",
        {
            "author_id": "fixture-author",
            "authorized_executor_id": "fixture-operator",
            "infrastructure_owner": {"actor_id": "fixture-infrastructure-owner"},
            "milestone": "v0.4",
            "non_author_reviewer_id": "fixture-reviewer",
            "publisher_id": "fixture-publisher",
            "run_id": "fixture-promotion-run",
            "task_id": "MP2-007",
        },
        invocation_id="fixture-promotion-roles",
        sequence=1,
        synthetic=True,
    )
    gate = release.make_record(
        "release-gate-instance",
        {
            "candidate_digest": candidate_digest,
            "milestone": "v0.4",
            "run_id": "fixture-promotion-run",
        },
        invocation_id="fixture-promotion-gate",
        sequence=1,
        synthetic=True,
    )
    qualification = release.make_record(
        "release-qualification",
        {"candidate_digest": candidate_digest},
        invocation_id="fixture-promotion-qualification",
        sequence=1,
        synthetic=True,
    )
    decision_data = {
        "approval_kind": "non_author_release_decision",
        "author_id": "fixture-author",
        "authority_policy_digest": "8" * 64,
        "candidate_digest": candidate_digest,
        "conflicts": [],
        "decision": "APPROVED",
        "expires_at": "2099-01-01T01:00:00Z",
        "issued_at": "2026-01-01T00:00:00Z",
        "milestone": "v0.4",
        "qualification_digest": release.sha256_json(qualification),
        "reviewer_id": "fixture-reviewer",
        "rubric_result_digest": None,
        "signing_method": "provider-attestation-v1",
    }
    unsigned = release.make_record(
        "release-approval-decision",
        decision_data,
        invocation_id="fixture-promotion-decision",
        sequence=1,
        synthetic=True,
    )
    subject = release.signature_subject_digest(unsigned)
    decision = release.make_record(
        "release-approval-decision",
        decision_data,
        invocation_id="fixture-promotion-decision",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "fixture-reviewer",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": release.sha256_json(
                    {"actor_id": "fixture-reviewer", "subject_digest": subject}
                ),
                "subject_digest": subject,
                "synthetic": True,
            }
        ],
    )
    approval_data = {
        "approval_decision_digest": release.sha256_json(decision),
        "author_id": "fixture-author",
        "candidate_digest": candidate_digest,
        "conflicts": [],
        "decision": "APPROVED",
        "gate_instance_digest": release.sha256_json(gate),
        "qualification_digest": release.sha256_json(qualification),
        "reviewer_id": "fixture-reviewer",
        "rubric_result_digest": None,
    }
    snapshot = release.make_record(
        "linear-release-snapshot",
        {"state": "open_running"},
        invocation_id="fixture-promotion-snapshot",
        sequence=1,
        synthetic=True,
    )
    artifact_bytes = {
        "metriplane-0.4.1-py3-none-any.whl": b"fixture-wheel",
        "metriplane-0.4.1.tar.gz": b"fixture-sdist",
    }
    artifact_rows = [
        {
            "media_type": (
                "application/vnd.pypa.wheel+zip" if name.endswith(".whl") else "application/gzip"
            ),
            "path": name,
            "sha256": release.sha256_bytes(raw),
            "size": len(raw),
        }
        for name, raw in sorted(artifact_bytes.items())
    ]
    artifact_manifest = release.make_record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": release.sha256_json(artifact_rows),
            "artifacts": artifact_rows,
            "build_invocation_id": "fixture-promotion-build",
            "build_recipe_digest": "1" * 64,
            "invocation_root_locator": "invocations",
            "milestone": "v0.4",
            "producer_intent_digest": "2" * 64,
            "source_digest": "3" * 64,
            "source_freeze_digest": "4" * 64,
            "target_resolution_digest": "5" * 64,
        },
        invocation_id="fixture-promotion-artifacts",
        sequence=1,
        synthetic=True,
    )
    records = {
        "approval-decision.json": decision,
        "approval.json": release.make_record(
            "release-approval",
            approval_data,
            invocation_id="fixture-promotion-approval",
            sequence=1,
            synthetic=True,
        ),
        "artifact-manifest.json": artifact_manifest,
        "attempt-index-checkpoint.json": release.make_record(
            "release-attempt-index",
            {
                "generation": 4,
                "genesis_digest": release.sha256_bytes(genesis_raw),
                "head": "4" * 64,
            },
            invocation_id="fixture-promotion-index",
            sequence=1,
            synthetic=True,
        ),
        "candidate-identity.json": release.make_record(
            "release-candidate-identity",
            {
                "artifact_manifest_digest": release.sha256_json(artifact_manifest),
                "artifact_set_digest": artifact_manifest["data"]["artifact_set_digest"],
                "build_invocation_id": artifact_manifest["data"]["build_invocation_id"],
                "candidate_digest": candidate_digest,
                "milestone": "v0.4",
                "package_version": "0.4.1",
                "release_tag": "v0.4.1",
                "source_freeze_digest": artifact_manifest["data"]["source_freeze_digest"],
            },
            invocation_id="fixture-promotion-candidate",
            sequence=1,
            synthetic=True,
        ),
        "gate-instance.json": gate,
        "prepromotion-linear-snapshot.json": snapshot,
        "qualification.json": qualification,
        "role-assignments.json": roles,
    }
    records["prepromotion-controls.json"] = release.make_record(
        "release-prepromotion-controls",
        {
            "candidate_digest": candidate_digest,
            "captured_at": "2026-01-01T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "linear_snapshot_digest": release.sha256_json(snapshot),
            "task_state": "open_running",
            "target_state_digest": "5" * 64,
        },
        invocation_id="fixture-promotion-controls",
        sequence=1,
        synthetic=True,
    )
    for name, record in records.items():
        (root / name).write_bytes(release.canonical_json(record))
    (root / "artifacts").mkdir()
    for name, raw in artifact_bytes.items():
        (root / "artifacts" / name).write_bytes(raw)
    (root / "release-attempt-index-genesis.json").write_bytes(genesis_raw)
    (root / "targets.json").write_bytes(
        (Path(__file__).resolve().parents[1] / "docs/status/release-targets.json").read_bytes()
    )
    argv = ["--dry-run"]
    for flag, name in (
        ("gate-instance", "gate-instance.json"),
        ("candidate-identity", "candidate-identity.json"),
        ("qualification", "qualification.json"),
        ("approval", "approval.json"),
        ("prepromotion-controls", "prepromotion-controls.json"),
        ("prepromotion-linear-snapshot", "prepromotion-linear-snapshot.json"),
        ("attempt-index-checkpoint", "attempt-index-checkpoint.json"),
        ("artifact-manifest", "artifact-manifest.json"),
        ("targets", "targets.json"),
    ):
        argv.extend(["--" + flag, str(root / name)])
    argv.extend(
        [
            "--out",
            str(root / "promotion-plan.json"),
            "--invocation-dir",
            str(root / "invocations/promote-release-candidate/001"),
        ]
    )
    return root, argv


def test_public_promotion_dry_run_binds_exact_authority_checkpoint_and_targets(
    tmp_path: Path,
) -> None:
    root, argv = _promotion_plan_command_fixture(tmp_path)
    completed = _run_release_tool("promote_release_candidate.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    record = release.read_json(root / "promotion-plan.json")
    release.validate_record(record, "release-promotion-plan")
    plan = record["data"]
    assert plan["attempt_index_epoch"] == 4
    assert plan["attempt_index_head"] == "4" * 64
    assert plan["publisher_id"] == "fixture-publisher"
    assert plan["publisher_actions"] == [
        "publish:github-release",
        "publish:pypi",
        "publish:testpypi",
    ]
    release.validate_promotion_plan(
        plan,
        now=0,
        candidate_digest="7" * 64,
        approval_digest=release.sha256_json(release.read_json(root / "approval.json")),
        publisher_id="fixture-publisher",
        controls_digest=release.sha256_json(release.read_json(root / "prepromotion-controls.json")),
        target_state_digest="5" * 64,
        attempt_index_checkpoint_digest=release.sha256_json(
            release.read_json(root / "attempt-index-checkpoint.json")
        ),
        attempt_index_head="4" * 64,
    )


def test_public_promotion_dry_run_rejects_substituted_checkpoint_without_output(
    tmp_path: Path,
) -> None:
    root, argv = _promotion_plan_command_fixture(tmp_path)
    checkpoint = release.read_json(root / "attempt-index-checkpoint.json")
    checkpoint["data"]["head"] = "9" * 64
    (root / "attempt-index-checkpoint.json").write_bytes(release.canonical_json(checkpoint))
    completed = _run_release_tool("promote_release_candidate.py", argv)
    assert completed.returncode != 0
    assert not (root / "promotion-plan.json").exists()


def test_public_promotion_terminal_replay_rejects_reserved_input_drift(tmp_path: Path) -> None:
    root, argv = _promotion_plan_command_fixture(tmp_path)
    completed = _run_release_tool("promote_release_candidate.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    targets = json.loads((root / "targets.json").read_text())
    targets["owner"] = "substituted-owner"
    (root / "targets.json").write_text(json.dumps(targets, sort_keys=True))
    context = release._validate_intent(root / "invocations/promote-release-candidate/001")
    with pytest.raises(release.ReleaseControlError, match="reserved input bytes changed"):
        release._validate_bound_invocation(context)


def test_public_promotion_terminal_replay_survives_run_relocation(tmp_path: Path) -> None:
    original_parent = tmp_path / "original-parent"
    original_parent.mkdir()
    original, argv = _promotion_plan_command_fixture(original_parent)
    completed = _run_release_tool("promote_release_candidate.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    moved = tmp_path / "moved-parent" / original.name
    moved.parent.mkdir()
    original.rename(moved)
    context = release._validate_intent(moved / "invocations/promote-release-candidate/001")
    terminal = release.read_json(context.directory / "invocation.json")
    release._validate_bound_invocation(
        context,
        outputs=terminal["data"]["outputs"],
        output_root=moved,
    )


def _promotion_execute_argv(root: Path, *, sequence: int = 2) -> list[str]:
    snapshot = release.read_json(root / "prepromotion-linear-snapshot.json")
    records = {
        "frozen-linear-snapshot.json": snapshot,
        "task-state-observation.json": release.make_record(
            "release-task-state-observation",
            {
                "observed_at": "2026-09-10T00:00:00Z",
                "project_id": "fixture-project",
                "snapshot_digest": release.sha256_json(snapshot),
                "state": "open_running",
                "task_id": "fixture-task",
            },
            invocation_id="fixture-promotion-task-state",
            sequence=1,
            synthetic=True,
        ),
        "retention-receipts.json": release.make_record(
            "release-retention-receipts",
            {"candidate_digest": "7" * 64},
            invocation_id="fixture-promotion-retention",
            sequence=1,
            synthetic=True,
        ),
    }
    for name, value in records.items():
        (root / name).write_bytes(release.canonical_json(value))
    (root / "readiness-registry.json").write_text(
        '{"schema_version":"metriplane.release-readiness-registry.v1"}\n'
    )
    (root / "task-state-policy.json").write_text(
        '{"schema_version":"metriplane.release-task-state-policy.v1"}\n'
    )
    (root / "release-attempt-index-genesis.json").write_text(
        '{"schema_version":"metriplane.release-attempt-index-genesis.v1"}\n'
    )
    argv = ["--execute"]
    for flag, name in (
        ("plan", "promotion-plan.json"),
        ("prepromotion-controls", "prepromotion-controls.json"),
        ("prepromotion-linear-snapshot", "prepromotion-linear-snapshot.json"),
        ("readiness-registry", "readiness-registry.json"),
        ("frozen-linear-snapshot", "frozen-linear-snapshot.json"),
        ("attempt-index-checkpoint", "attempt-index-checkpoint.json"),
        ("attempt-index-genesis", "release-attempt-index-genesis.json"),
        ("task-state-observation", "task-state-observation.json"),
        ("task-state-policy", "task-state-policy.json"),
        ("retention-receipts", "retention-receipts.json"),
    ):
        argv.extend(["--" + flag, str(root / name)])
    argv.extend(
        [
            "--attempt-index-backend",
            "attempt-index",
            "--expected-head",
            "4" * 64,
            "--operation-id",
            f"fixture-promotion-{sequence}",
            "--project-id",
            "fixture-project",
            "--task-id",
            "fixture-task",
            "--require-live-state",
            "open_running",
            "--provider-auth-from-approved-environment",
            "--require-live-full-release-bom-closed-except-current-decision",
            "--require-live-exact-reciprocal-relations",
            "--require-live-exact-milestone-assignments",
            "--full-project-refetch-before-lock-and-before-first-mutation",
            "--require-fresh-through-first-mutation",
            "--bind-live-refetch-in-lock-receipt",
            "--lock-receipt-out",
            str(root / f"promotion-lock-{sequence}.json"),
            "--out",
            str(root / f"promotion-{sequence}.json"),
            "--invocation-dir",
            str(root / f"invocations/promote-release-candidate/{sequence:03d}"),
        ]
    )
    return argv


def test_public_promotion_execute_fences_competing_writer_and_retains_exact_receipts(
    tmp_path: Path,
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    planned = _run_release_tool("promote_release_candidate.py", plan_argv)
    assert planned.returncode == 0, planned.stderr or planned.stdout
    first = _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root))
    assert first.returncode == 0, first.stderr or first.stdout
    lock = release.read_json(root / "promotion-lock-2.json")
    promotion = release.read_json(root / "promotion-2.json")
    release.validate_record(lock, "release-promotion-lock")
    release.validate_record(promotion, "release-promotion")
    assert promotion["synthetic"] is True
    assert promotion["data"]["lock_receipt_digest"] == release.sha256_json(lock)
    competing = _run_release_tool(
        "promote_release_candidate.py", _promotion_execute_argv(root, sequence=3)
    )
    assert competing.returncode != 0
    assert not (root / "promotion-lock-3.json").exists()
    assert not (root / "promotion-3.json").exists()


def test_publication_observation_command_reads_exact_fixture_bytes(tmp_path: Path) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    argv = [
        "--promotion",
        str(root / "promotion-2.json"),
        "--promotion-lock-receipt",
        str(root / "promotion-lock-2.json"),
        "--artifact-manifest",
        str(root / "artifact-manifest.json"),
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "publication-observations.json"),
        "--invocation-dir",
        str(root / "invocations/collect-publication-observations/001"),
    ]
    completed = _run_release_tool("collect_publication_observations.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    record = release.read_json(root / "publication-observations.json")
    release.validate_record(record, "release-publication-observations")
    assert record["synthetic"] is True
    assert [row["target_id"] for row in record["data"]["targets"]] == [
        "github-release",
        "pypi",
        "testpypi",
    ]


def _replaced_terminal_outputs(
    context: release.ReleaseInvocation, output: Path
) -> list[dict[str, str]]:
    terminal = release.read_json(context.directory / "invocation.json")
    return [
        {**row, "sha256": release.sha256_bytes(output.read_bytes())}
        if row["path"] == output.relative_to(context.root).as_posix()
        else row
        for row in terminal["data"]["outputs"]
    ]


def test_publication_observation_terminal_replay_rejects_forged_success(
    tmp_path: Path,
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    argv = [
        "--promotion",
        str(root / "promotion-2.json"),
        "--promotion-lock-receipt",
        str(root / "promotion-lock-2.json"),
        "--artifact-manifest",
        str(root / "artifact-manifest.json"),
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "publication-observations.json"),
        "--invocation-dir",
        str(root / "invocations/collect-publication-observations/001"),
    ]
    assert _run_release_tool("collect_publication_observations.py", argv).returncode == 0
    output = root / "publication-observations.json"
    forged = release.read_json(output)
    forged["data"]["all_targets_observed"] = False
    forged = release.make_record(
        "release-publication-observations",
        forged["data"],
        invocation_id=forged["invocation_id"],
        sequence=forged["sequence"],
        synthetic=True,
    )
    output.chmod(0o600)
    output.write_bytes(release.canonical_json(forged))
    context = release._validate_intent(root / "invocations/collect-publication-observations/001")
    with pytest.raises(release.ReleaseControlError, match="output semantics differ"):
        release._validate_bound_invocation(
            context, outputs=_replaced_terminal_outputs(context, output)
        )


def test_public_promotion_terminal_replay_rejects_forged_empty_action_success(
    tmp_path: Path,
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    output = root / "promotion-2.json"
    forged = release.read_json(output)
    forged["data"]["actions"] = []
    forged = release.make_record(
        "release-promotion",
        forged["data"],
        invocation_id=forged["invocation_id"],
        sequence=forged["sequence"],
        synthetic=True,
    )
    output.chmod(0o600)
    output.write_bytes(release.canonical_json(forged))
    context = release._validate_intent(root / "invocations/promote-release-candidate/002")
    terminal = release.read_json(context.directory / "invocation.json")
    outputs = [
        {**row, "sha256": release.sha256_bytes(output.read_bytes())}
        if row["path"] == "promotion-2.json"
        else row
        for row in terminal["data"]["outputs"]
    ]
    with pytest.raises(release.ReleaseControlError, match="output semantics differ"):
        release._validate_bound_invocation(context, outputs=outputs)


def test_publication_observation_rejects_changed_artifact(tmp_path: Path) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    (root / "artifacts/metriplane-0.4.1.tar.gz").write_bytes(b"substituted")
    argv = [
        "--promotion",
        str(root / "promotion-2.json"),
        "--promotion-lock-receipt",
        str(root / "promotion-lock-2.json"),
        "--artifact-manifest",
        str(root / "artifact-manifest.json"),
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "publication-observations.json"),
        "--invocation-dir",
        str(root / "invocations/collect-publication-observations/001"),
    ]
    completed = _run_release_tool("collect_publication_observations.py", argv)
    assert completed.returncode != 0
    assert not (root / "publication-observations.json").exists()


def test_interrupted_publication_observation_cannot_create_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_AFTER_PUBLICATION_READBACK", "1")
    argv = [
        "--promotion",
        str(root / "promotion-2.json"),
        "--promotion-lock-receipt",
        str(root / "promotion-lock-2.json"),
        "--artifact-manifest",
        str(root / "artifact-manifest.json"),
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "publication-observations.json"),
        "--invocation-dir",
        str(root / "invocations/collect-publication-observations/001"),
    ]
    completed = _run_release_tool("collect_publication_observations.py", argv)
    assert completed.returncode != 0
    assert not (root / "publication-observations.json").exists()


def _publication_reconciliation_command_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, list[str]]:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        == 0
    )
    observation_argv = [
        "--promotion",
        str(root / "promotion-2.json"),
        "--promotion-lock-receipt",
        str(root / "promotion-lock-2.json"),
        "--artifact-manifest",
        str(root / "artifact-manifest.json"),
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "publication-observations.json"),
        "--invocation-dir",
        str(root / "invocations/collect-publication-observations/001"),
    ]
    assert (
        _run_release_tool("collect_publication_observations.py", observation_argv).returncode == 0
    )
    evidence = root / "reconciliation-evidence"
    evidence.mkdir()
    for source, destination in (
        ("candidate-identity.json", "candidate-identity.json"),
        ("artifact-manifest.json", "artifact-manifest.json"),
        ("qualification.json", "qualification.json"),
        ("approval.json", "approval.json"),
        ("promotion-lock-2.json", "promotion-lock.json"),
        ("promotion-2.json", "promotion.json"),
        ("publication-observations.json", "observations.json"),
    ):
        shutil.copyfile(root / source, evidence / destination)
    candidate = release.read_json(evidence / "candidate-identity.json")["data"]
    artifacts = release.read_json(evidence / "artifact-manifest.json")["data"]["artifacts"]
    entries = [{**row, "role": "release-artifact"} for row in artifacts]
    manifest = release.make_record(
        "release-evidence-manifest",
        {
            "candidate_digest": candidate["candidate_digest"],
            "entries": entries,
            "phase": "qualified-publication",
        },
        invocation_id="fixture-qualified-publication-manifest",
        sequence=1,
        synthetic=True,
    )
    retention = release.make_record(
        "release-retention-receipts",
        {
            "candidate_digest": candidate["candidate_digest"],
            "input_digest": release.sha256_bytes(release.canonical_json(manifest)),
            "phase": "prepublication",
        },
        invocation_id="fixture-qualified-publication-retention",
        sequence=1,
        synthetic=True,
    )
    (evidence / "evidence-manifest.json").write_bytes(release.canonical_json(manifest))
    (evidence / "retention.json").write_bytes(release.canonical_json(retention))
    argv = [
        "--qualification",
        str(evidence / "qualification.json"),
        "--approval",
        str(evidence / "approval.json"),
        "--promotion-lock-receipt",
        str(evidence / "promotion-lock.json"),
        "--observations",
        str(evidence / "observations.json"),
        "--evidence-manifest",
        str(evidence / "evidence-manifest.json"),
        "--retention-receipts",
        str(evidence / "retention.json"),
        "--out",
        str(evidence / "reconciliation.json"),
        "--invocation-dir",
        str(evidence / "invocations/build-publication-reconciliation/001"),
    ]
    return root, evidence, argv


def test_publication_reconciliation_command_closes_exact_fixture_bytes(tmp_path: Path) -> None:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    completed = _run_release_tool("build_publication_reconciliation.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    record = release.read_json(evidence / "reconciliation.json")
    release.validate_record(record, "release-publication-reconciliation")
    assert record["data"]["result"] == "RECONCILED"
    assert record["data"]["burn_required"] is False
    assert [row["target_id"] for row in record["data"]["targets"]] == [
        "github-release",
        "pypi",
        "testpypi",
    ]


def test_publication_reconciliation_terminal_replay_rejects_forged_success(
    tmp_path: Path,
) -> None:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    assert _run_release_tool("build_publication_reconciliation.py", argv).returncode == 0
    output = evidence / "reconciliation.json"
    forged = release.read_json(output)
    forged["data"]["targets"][0]["exact_match"] = False
    unsigned = dict(forged["data"])
    unsigned.pop("reconciliation_digest")
    forged["data"]["reconciliation_digest"] = release.sha256_json(unsigned)
    forged = release.make_record(
        "release-publication-reconciliation",
        forged["data"],
        invocation_id=forged["invocation_id"],
        sequence=forged["sequence"],
        synthetic=True,
    )
    output.chmod(0o600)
    output.write_bytes(release.canonical_json(forged))
    context = release._validate_intent(
        evidence / "invocations/build-publication-reconciliation/001"
    )
    with pytest.raises(release.ReleaseControlError, match="output semantics differ"):
        release._validate_bound_invocation(
            context, outputs=_replaced_terminal_outputs(context, output)
        )


def test_publication_reconciliation_rejects_substituted_observation(tmp_path: Path) -> None:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    observations = release.read_json(evidence / "observations.json")
    observations["data"]["targets"][0]["artifacts"][0]["observed_digest"] = "f" * 64
    observations = release.make_record(
        "release-publication-observations",
        observations["data"],
        invocation_id=observations["invocation_id"],
        sequence=observations["sequence"],
        synthetic=True,
    )
    (evidence / "observations.json").write_bytes(release.canonical_json(observations))
    completed = _run_release_tool("build_publication_reconciliation.py", argv)
    assert completed.returncode != 0
    assert not (evidence / "reconciliation.json").exists()


def _fixture_impact_classification(
    candidate: dict[str, Any], failed: release.ReleaseInvocation, *, stage: str
) -> dict[str, Any]:
    terminal = release._validate_terminal(failed)
    data = {
        "authority_policy_digest": "a" * 64,
        "authorized_role": "infrastructure_owner",
        "conflicts": ["fixture postpublication operation failed"],
        "decision": "NO_LKG_INVALIDATION",
        "expires_at": "2099-01-01T00:00:00Z",
        "input_kind": "impact_classification",
        "issued_at": "2026-01-01T00:00:00Z",
        "provider_event": {"actor_id": "fixture-infrastructure-owner"},
        "signer_identity": "fixture-infrastructure-owner",
        "signing_method": "provider-attestation-v1",
        "subject_digests": [
            {"subject": "candidate_identity", "sha256": release.sha256_json(candidate)},
            {"subject": "failed_invocation", "sha256": release.sha256_json(terminal)},
            {"subject": "failed_stage", "sha256": release.sha256_json({"stage": stage})},
        ],
    }
    unsigned = release.make_record(
        "release-protected-input",
        data,
        invocation_id="fixture-impact-classification",
        sequence=1,
        synthetic=True,
    )
    subject = release.signature_subject_digest(unsigned)
    return release.make_record(
        "release-protected-input",
        data,
        invocation_id="fixture-impact-classification",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "fixture-infrastructure-owner",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": release.sha256_json(
                    {
                        "actor_id": "fixture-infrastructure-owner",
                        "subject_digest": subject,
                    }
                ),
                "subject_digest": subject,
                "synthetic": True,
            }
        ],
    )


def test_postpublication_conflict_binds_actual_failed_reconciliation_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_RECONCILIATION", "1")
    interrupted = _run_release_tool("build_publication_reconciliation.py", argv)
    assert interrupted.returncode != 0
    assert not (evidence / "reconciliation.json").exists()
    monkeypatch.delenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_RECONCILIATION")
    failed = release._validate_intent(evidence / "invocations/build-publication-reconciliation/001")
    candidate = release.read_json(evidence / "candidate-identity.json")
    classification = _fixture_impact_classification(
        candidate, failed, stage="publication-reconciliation"
    )
    classification_path = evidence / "impact-classification.json"
    classification_path.write_bytes(release.canonical_json(classification))
    conflict_path = evidence / "postpublication-conflicts/001/conflict.json"
    conflict_path.parent.mkdir(parents=True)
    conflict_argv = [
        "--stage",
        "publication-reconciliation",
        "--candidate-identity",
        str(evidence / "candidate-identity.json"),
        "--failed-invocation-dir",
        str(failed.directory),
        "--no-lkg-invalidation",
        str(classification_path),
        "--no-assurance-round",
        "--out",
        str(conflict_path),
        "--invocation-dir",
        str(evidence / "invocations/record-postpublication-conflict/001"),
    ]
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_CONFLICT_FINALIZATION", "1")
    interrupted_conflict = _run_release_tool("record_postpublication_conflict.py", conflict_argv)
    assert interrupted_conflict.returncode != 0
    assert not conflict_path.exists()
    monkeypatch.delenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_CONFLICT_FINALIZATION")
    conflict_path = evidence / "postpublication-conflicts/002/conflict.json"
    conflict_path.parent.mkdir(parents=True)
    conflict_argv = [
        value.replace("postpublication-conflicts/001", "postpublication-conflicts/002").replace(
            "record-postpublication-conflict/001", "record-postpublication-conflict/002"
        )
        for value in conflict_argv
    ]
    completed = _run_release_tool("record_postpublication_conflict.py", conflict_argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    conflict = release.read_json(conflict_path)
    assert conflict["status"] == "FAIL"
    assert conflict["data"]["failed_invocation_digest"] == release.sha256_json(
        release._validate_terminal(failed)
    )
    original = conflict_path.read_bytes()
    forged = copy.deepcopy(conflict)
    forged["data"]["failed_invocation_digest"] = "e" * 64
    unsigned = dict(forged["data"])
    unsigned.pop("conflict_digest")
    forged["data"]["conflict_digest"] = release.sha256_json(unsigned)
    forged = release.make_record(
        "release-postpublication-conflict",
        forged["data"],
        invocation_id=forged["invocation_id"],
        sequence=forged["sequence"],
        synthetic=True,
        status="FAIL",
    )
    conflict_path.chmod(0o600)
    conflict_path.write_bytes(release.canonical_json(forged))
    conflict_context = release._validate_intent(
        evidence / "invocations/record-postpublication-conflict/002"
    )
    with pytest.raises(release.ReleaseControlError, match="output semantics differ"):
        release._validate_bound_invocation(
            conflict_context,
            outputs=_replaced_terminal_outputs(conflict_context, conflict_path),
        )
    conflict_path.write_bytes(original)
    duplicate = _run_release_tool(
        "record_postpublication_conflict.py",
        [
            value.replace(
                "record-postpublication-conflict/002", "record-postpublication-conflict/003"
            )
            for value in conflict_argv
        ],
    )
    assert duplicate.returncode != 0
    assert conflict_path.read_bytes() == original


def test_postpublication_conflict_rejects_passing_operation_even_when_relabelled(
    tmp_path: Path,
) -> None:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    assert _run_release_tool("build_publication_reconciliation.py", argv).returncode == 0
    completed_context = release._validate_intent(
        evidence / "invocations/build-publication-reconciliation/001"
    )
    candidate = release.read_json(evidence / "candidate-identity.json")
    classification = _fixture_impact_classification(
        candidate, completed_context, stage="publication-reconciliation"
    )
    classification_path = evidence / "impact-classification.json"
    classification_path.write_bytes(release.canonical_json(classification))
    conflict_path = evidence / "postpublication-conflicts/001/conflict.json"
    conflict_path.parent.mkdir(parents=True)
    argv = [
        "--stage",
        "publication-observations",
        "--candidate-identity",
        str(evidence / "candidate-identity.json"),
        "--failed-invocation-dir",
        str(completed_context.directory),
        "--no-lkg-invalidation",
        str(classification_path),
        "--no-assurance-round",
        "--out",
        str(conflict_path),
        "--invocation-dir",
        str(evidence / "invocations/record-postpublication-conflict/001"),
    ]
    rejected = _run_release_tool("record_postpublication_conflict.py", argv)
    assert rejected.returncode != 0
    assert not conflict_path.exists()


def _postpublication_conflict_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    _root, evidence, argv = _publication_reconciliation_command_fixture(tmp_path)
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_RECONCILIATION", "1")
    assert _run_release_tool("build_publication_reconciliation.py", argv).returncode != 0
    monkeypatch.delenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_RECONCILIATION")
    failed = release._validate_intent(evidence / "invocations/build-publication-reconciliation/001")
    candidate = release.read_json(evidence / "candidate-identity.json")
    classification = _fixture_impact_classification(
        candidate, failed, stage="publication-reconciliation"
    )
    classification_path = evidence / "impact-classification.json"
    classification_path.write_bytes(release.canonical_json(classification))
    conflict_path = evidence / "postpublication-conflicts/001/conflict.json"
    conflict_path.parent.mkdir(parents=True)
    completed = _run_release_tool(
        "record_postpublication_conflict.py",
        [
            "--stage",
            "publication-reconciliation",
            "--candidate-identity",
            str(evidence / "candidate-identity.json"),
            "--failed-invocation-dir",
            str(failed.directory),
            "--no-lkg-invalidation",
            str(classification_path),
            "--no-assurance-round",
            "--out",
            str(conflict_path),
            "--invocation-dir",
            str(evidence / "invocations/record-postpublication-conflict/001"),
        ],
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return evidence, conflict_path


def test_postpublication_conflict_manifest_actual_command_closes_subject_and_journals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, conflict_path = _postpublication_conflict_fixture(tmp_path, monkeypatch)
    manifest_path = conflict_path.parent / "evidence-manifest.json"
    argv = [
        "--phase",
        "postpublication-conflict",
        "--candidate-dir",
        str(evidence),
        "--no-assurance-round",
        "--input",
        str(conflict_path),
        "--invocation-root",
        str(evidence / "invocations"),
        "--exclude-current-invocation",
        "--require-lkg-disposition-and-applicable-invalidation-receipt",
        "--out",
        str(manifest_path),
        "--invocation-dir",
        str(evidence / "invocations/build-release-evidence-manifest/001"),
    ]
    completed = _run_release_tool("build_release_evidence_manifest.py", argv)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    manifest = release.read_json(manifest_path)
    release.validate_release_producer_journal(
        manifest, manifest_path, producer="build_release_evidence_manifest.py"
    )
    entries = manifest["data"]["entries"]
    assert any(row["path"] == conflict_path.relative_to(evidence).as_posix() for row in entries)
    assert release.sha256_json(
        release.read_json(
            evidence / "invocations/build-publication-reconciliation/001/invocation.json"
        )
    ) in set(manifest["data"]["invocation_journal_digests"])
    validated = _run_release_tool(
        "validate_release_evidence_manifest.py",
        [
            "--record",
            str(manifest_path),
            "--require-lkg-disposition-and-applicable-invalidation-receipt",
            "--invocation-dir",
            str(evidence / "invocations/validate-release-evidence-manifest/001"),
        ],
    )
    assert validated.returncode == 0, validated.stderr or validated.stdout


def test_postpublication_conflict_manifest_validator_replays_after_relocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, conflict_path = _postpublication_conflict_fixture(tmp_path, monkeypatch)
    manifest_path = conflict_path.parent / "evidence-manifest.json"
    argv = [
        "--phase",
        "postpublication-conflict",
        "--candidate-dir",
        str(evidence),
        "--no-assurance-round",
        "--input",
        str(conflict_path),
        "--invocation-root",
        str(evidence / "invocations"),
        "--exclude-current-invocation",
        "--require-lkg-disposition-and-applicable-invalidation-receipt",
        "--out",
        str(manifest_path),
        "--invocation-dir",
        str(evidence / "invocations/build-release-evidence-manifest/001"),
    ]
    assert _run_release_tool("build_release_evidence_manifest.py", argv).returncode == 0
    relocated = tmp_path / "relocated-candidate"
    evidence.rename(relocated)
    relocated_manifest = relocated / manifest_path.relative_to(evidence)
    validated = _run_release_tool(
        "validate_release_evidence_manifest.py",
        [
            "--record",
            str(relocated_manifest),
            "--require-lkg-disposition-and-applicable-invalidation-receipt",
            "--invocation-dir",
            str(relocated / "invocations/validate-release-evidence-manifest/001"),
        ],
    )
    assert validated.returncode == 0, validated.stderr or validated.stdout


@pytest.mark.parametrize("mutation", ["missing-input", "substituted-input", "changed-journal"])
def test_postpublication_conflict_manifest_validation_rejects_broken_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    evidence, conflict_path = _postpublication_conflict_fixture(tmp_path, monkeypatch)
    manifest_path = conflict_path.parent / "evidence-manifest.json"
    argv = [
        "--phase",
        "postpublication-conflict",
        "--candidate-dir",
        str(evidence),
        "--no-assurance-round",
        "--input",
        str(conflict_path),
        "--invocation-root",
        str(evidence / "invocations"),
        "--exclude-current-invocation",
        "--require-lkg-disposition-and-applicable-invalidation-receipt",
        "--out",
        str(manifest_path),
        "--invocation-dir",
        str(evidence / "invocations/build-release-evidence-manifest/001"),
    ]
    assert _run_release_tool("build_release_evidence_manifest.py", argv).returncode == 0
    if mutation == "missing-input":
        (evidence / "impact-classification.json").unlink()
    elif mutation == "substituted-input":
        candidate = evidence / "candidate-identity.json"
        candidate.chmod(0o600)
        candidate.write_bytes(candidate.read_bytes() + b" ")
    else:
        journal = evidence / "invocations/build-publication-reconciliation/001/stdout"
        journal.chmod(0o600)
        journal.write_bytes(b"substituted journal\n")
    validated = _run_release_tool(
        "validate_release_evidence_manifest.py",
        [
            "--record",
            str(manifest_path),
            "--require-lkg-disposition-and-applicable-invalidation-receipt",
            "--invocation-dir",
            str(evidence / "invocations/validate-release-evidence-manifest/001"),
        ],
    )
    assert validated.returncode != 0


def test_postpublication_conflict_manifest_interruption_retries_without_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, conflict_path = _postpublication_conflict_fixture(tmp_path, monkeypatch)
    manifest_path = conflict_path.parent / "evidence-manifest.json"
    argv = [
        "--phase",
        "postpublication-conflict",
        "--candidate-dir",
        str(evidence),
        "--no-assurance-round",
        "--input",
        str(conflict_path),
        "--invocation-root",
        str(evidence / "invocations"),
        "--exclude-current-invocation",
        "--require-lkg-disposition-and-applicable-invalidation-receipt",
        "--out",
        str(manifest_path),
        "--invocation-dir",
        str(evidence / "invocations/build-release-evidence-manifest/001"),
    ]
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_CONFLICT_MANIFEST", "1")
    assert _run_release_tool("build_release_evidence_manifest.py", argv).returncode != 0
    assert not manifest_path.exists()
    monkeypatch.delenv("METRIPLANE_RELEASE_TEST_INTERRUPT_BEFORE_CONFLICT_MANIFEST")
    retry = [
        value.replace("build-release-evidence-manifest/001", "build-release-evidence-manifest/002")
        for value in argv
    ]
    completed = _run_release_tool("build_release_evidence_manifest.py", retry)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    first = release._validate_terminal(
        release._validate_intent(evidence / "invocations/build-release-evidence-manifest/001")
    )
    assert first["status"] == "BLOCKED"
    assert first["data"]["outputs"] == []


def _write_fixture_native_seed(
    root: Path, tool: str, argv: list[str], responses: dict[str, bytes]
) -> None:
    stage = release._invocation_stage(tool)
    sequence = int(Path(argv[argv.index("--invocation-dir") + 1]).name)
    seed_root = root / f"inputs/fixture-native/{stage}/{sequence:03d}"
    members = []
    for member_id, raw in responses.items():
        path = seed_root / "raw" / f"{member_id}.bin"
        _seed_staging_put(path, raw)
        members.append(
            {
                "member_id": member_id,
                "path": "raw/" + member_id + ".bin",
                "schema_id": "application/octet-stream",
                "bytes": len(raw),
                "sha256": release.sha256_bytes(raw),
            }
        )
    seed = {
        "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
        "synthetic": True,
        "tool": tool,
        "command_digest": release.sha256_json(
            {"tool": tool, "argv": [tool, *argv], "working_directory": str(Path.cwd())}
        ),
        "members": members,
        "data": {"response_member_ids": list(responses)},
    }
    _seed_staging_put(seed_root / "seed.json", json.dumps(seed, indent=2).encode() + b"\n")


def test_postpublication_conflict_retention_and_index_actual_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, conflict_path = _postpublication_conflict_fixture(tmp_path, monkeypatch)
    manifest_path = conflict_path.parent / "evidence-manifest.json"
    manifest_argv = [
        "--phase",
        "postpublication-conflict",
        "--candidate-dir",
        str(evidence),
        "--no-assurance-round",
        "--input",
        str(conflict_path),
        "--invocation-root",
        str(evidence / "invocations"),
        "--exclude-current-invocation",
        "--require-lkg-disposition-and-applicable-invalidation-receipt",
        "--out",
        str(manifest_path),
        "--invocation-dir",
        str(evidence / "invocations/build-release-evidence-manifest/001"),
    ]
    assert _run_release_tool("build_release_evidence_manifest.py", manifest_argv).returncode == 0

    registry, control_files, controls = _fixture_native_registry_bundle()
    stores_raw = release.canonical_json(registry)
    stores_path = evidence / "inputs/stores.json"
    _seed_staging_put(stores_path, stores_raw)
    for name, raw in control_files.items():
        _seed_staging_put(evidence / "inputs" / name, raw)
    retention_path = conflict_path.parent / "retention-receipts.json"
    retention_argv = [
        "--manifest",
        str(manifest_path),
        "--stores",
        str(stores_path),
        "--phase",
        "postpublication-conflict",
        "--out",
        str(retention_path),
        "--invocation-dir",
        str(evidence / "invocations/retain-release-evidence/001"),
    ]
    _subject, operations = release._release_fixture_retention_expectations(
        {
            "manifest": str(manifest_path),
            "stores": str(stores_path),
            "phase": "postpublication-conflict",
        },
        original_inputs=[],
        original_manifest=manifest_path.read_bytes(),
        registry_raw=stores_raw,
        expected_registry_digest=release.sha256_bytes(stores_raw),
        fixture_run_id=evidence.name,
        backend_controls=controls,
    )
    retained = manifest_path.read_bytes()
    retention_responses = {}
    for index, operation in enumerate(operations):
        retention_responses[f"effect-{index}"] = (
            retained
            if operation["kind"] == "retention.read"
            else release.canonical_json(
                {
                    **operation["request"],
                    "effect": (
                        "immutable_put"
                        if operation["kind"] == "retention.put"
                        else "governance_hold"
                    ),
                    "administration_identity": operation["request"]["administration_identity"],
                }
            )
        )
    _write_fixture_native_seed(
        evidence, "retain_release_evidence.py", retention_argv, retention_responses
    )
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    retained_result = _run_release_tool("retain_release_evidence.py", retention_argv)
    assert retained_result.returncode == 0, retained_result.stderr or retained_result.stdout
    assert manifest_path.stat().st_nlink == 1

    genesis_raw = _fixture_native_genesis_raw()
    genesis_path = evidence / "inputs/genesis.json"
    _seed_staging_put(genesis_path, genesis_raw)
    genesis_digest = release.sha256_bytes(genesis_raw)
    candidate = release.read_json(evidence / "candidate-identity.json")["data"]
    operation_id = "fixture-postpublication-conflict-index"
    scope = {
        "kind": "release_candidate",
        "scope_id": candidate["candidate_digest"],
        "stage": "postpublication-conflict",
        "sequence": 1,
        "release_tag": candidate["release_tag"],
        "candidate_id": candidate["candidate_digest"],
    }
    entry = {
        "schema_version": "metriplane.release-attempt-index-entry.v1",
        "backend_id": "attempt-index",
        "genesis_digest": genesis_digest,
        "generation": 1,
        "previous_head": None,
        "operation_id": operation_id,
        "token": "opaque-postpublication-conflict-token",
        "milestone": candidate["milestone"],
        "scope": scope,
        "entry_manifest_digest": release.sha256_json(release.read_json(manifest_path)),
        "entry_receipts_digest": release.sha256_json(release.read_json(retention_path)),
    }
    response = release.canonical_json(
        {
            "backend_id": "attempt-index",
            "genesis_digest": genesis_digest,
            "operation_id": operation_id,
            "expected_head": genesis_digest,
            "entry": entry,
            "committed_head": release.sha256_json(entry),
            "read_back_digest": release.sha256_json(entry),
            "disposition": "committed",
        }
    )
    index_path = conflict_path.parent / "index-receipt.json"
    index_argv = [
        "--entry-manifest",
        str(manifest_path),
        "--entry-receipts",
        str(retention_path),
        "--scope-kind",
        "release_candidate",
        "--scope-id",
        candidate["candidate_digest"],
        "--release-tag",
        candidate["release_tag"],
        "--candidate-id",
        candidate["candidate_digest"],
        "--stage",
        "postpublication-conflict",
        "--sequence",
        "1",
        "--index-backend",
        "attempt-index",
        "--expected-head",
        genesis_digest,
        "--operation-id",
        operation_id,
        "--out",
        str(index_path),
        "--invocation-dir",
        str(evidence / "invocations/update-release-attempt-index/001"),
    ]
    _write_fixture_native_seed(
        evidence, "update_release_attempt_index.py", index_argv, {"cas": response}
    )
    indexed = _run_release_tool("update_release_attempt_index.py", index_argv)
    assert indexed.returncode == 0, indexed.stderr or indexed.stdout
    receipt = release.read_json(index_path)
    assert receipt["data"]["stage"] == "postpublication-conflict"
    assert receipt["data"]["entry_manifest_digest"] == release.sha256_json(
        release.read_json(manifest_path)
    )


def test_public_promotion_interruption_after_lock_cannot_create_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_AFTER_PROMOTION_LOCK", "1")
    interrupted = _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root))
    assert interrupted.returncode != 0
    assert list((root / "fixture-promotion-lock").glob("*.json"))
    assert not (root / "promotion-lock-2.json").exists()
    assert not (root / "promotion-2.json").exists()


def test_public_promotion_rejects_expired_plan_before_acquiring_lock(tmp_path: Path) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    plan_record = release.read_json(root / "promotion-plan.json")
    plan_data = plan_record["data"]
    plan_data["expires_at"] = 1
    unsigned = dict(plan_data)
    unsigned.pop("plan_digest")
    plan_data["plan_digest"] = release.sha256_json(unsigned)
    (root / "promotion-plan.json").chmod(0o600)
    (root / "promotion-plan.json").write_bytes(release.canonical_json(plan_record))
    rejected = _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root))
    assert rejected.returncode != 0
    assert not (root / "fixture-promotion-lock").exists()
    assert not (root / "promotion-lock-2.json").exists()
    assert not (root / "promotion-2.json").exists()


def test_public_promotion_revalidates_lock_before_every_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_REVOKE_PROMOTION_LOCK", "1")
    rejected = _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root))
    assert rejected.returncode != 0
    assert not (root / "promotion-lock-2.json").exists()
    assert not (root / "promotion-2.json").exists()


def test_public_promotion_recovery_requires_expired_exact_lock_and_signed_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, plan_argv = _promotion_plan_command_fixture(tmp_path)
    assert _run_release_tool("promote_release_candidate.py", plan_argv).returncode == 0
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_PROMOTION_LEASE_SECONDS", "1")
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_INTERRUPT_AFTER_PROMOTION_LOCK", "1")
    assert (
        _run_release_tool("promote_release_candidate.py", _promotion_execute_argv(root)).returncode
        != 0
    )
    monkeypatch.delenv("METRIPLANE_RELEASE_TEST_INTERRUPT_AFTER_PROMOTION_LOCK")
    active_path = root / "active-promotion-lock-00000001.json"
    active = release.read_json(active_path)
    termination = release.make_record(
        "provider-run-termination",
        {"operation_id": "fixture-promotion-2", "terminated": True},
        invocation_id="fixture-promotion-termination",
        sequence=1,
        synthetic=True,
    )
    authorization_data = {
        "active_lock_digest": release.sha256_json(active),
        "decision": "RECOVER",
        "infrastructure_owner_id": "fixture-infrastructure-owner",
        "promotion_operation_id": "fixture-promotion-2",
        "recovery_operation_id": "fixture-promotion-recovery-3",
        "targets_digest": release.sha256_bytes((root / "targets.json").read_bytes()),
    }
    (root / "provider-run-termination.json").write_bytes(release.canonical_json(termination))
    time.sleep(1.1)
    argv = [
        "--recover-abandoned-lock",
        "--attempt-index-backend",
        "attempt-index",
        "--attempt-index-genesis",
        str(root / "release-attempt-index-genesis.json"),
        "--promotion-operation-id",
        "fixture-promotion-2",
        "--recovery-operation-id",
        "fixture-promotion-recovery-3",
        "--expected-active-head",
        "4" * 64,
        "--active-lock-record",
        str(active_path),
        "--provider-run-termination",
        str(root / "provider-run-termination.json"),
        "--signed-infrastructure-owner-recovery",
        str(root / "infrastructure-owner-recovery.json"),
        "--prelock-target-observations-from-lock",
        "--refetch-all-targets",
        "--targets",
        str(root / "targets.json"),
        "--out",
        str(root / "promotion-recovery.json"),
        "--invocation-dir",
        str(root / "invocations/promote-release-candidate/003"),
    ]
    substituted_data = {**authorization_data, "infrastructure_owner_id": "fixture-unassigned-owner"}
    substituted_unsigned = release.make_record(
        "release-infrastructure-owner-recovery",
        substituted_data,
        invocation_id="fixture-substituted-recovery-authorization",
        sequence=1,
        synthetic=True,
    )
    substituted_subject = release.signature_subject_digest(substituted_unsigned)
    substituted = release.make_record(
        "release-infrastructure-owner-recovery",
        substituted_data,
        invocation_id="fixture-substituted-recovery-authorization",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "fixture-unassigned-owner",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": release.sha256_json(
                    {
                        "actor_id": "fixture-unassigned-owner",
                        "subject_digest": substituted_subject,
                    }
                ),
                "subject_digest": substituted_subject,
                "synthetic": True,
            }
        ],
    )
    (root / "infrastructure-owner-recovery.json").write_bytes(release.canonical_json(substituted))
    rejected = _run_release_tool("promote_release_candidate.py", argv)
    assert rejected.returncode != 0
    assert not (root / "fixture-promotion-lock/00000002.json").exists()
    assert not (root / "promotion-recovery.json").exists()

    authorization_data["recovery_operation_id"] = "fixture-promotion-recovery-4"
    unsigned = release.make_record(
        "release-infrastructure-owner-recovery",
        authorization_data,
        invocation_id="fixture-promotion-recovery-authorization-4",
        sequence=1,
        synthetic=True,
    )
    subject = release.signature_subject_digest(unsigned)
    authorization = release.make_record(
        "release-infrastructure-owner-recovery",
        authorization_data,
        invocation_id="fixture-promotion-recovery-authorization-4",
        sequence=1,
        synthetic=True,
        signatures=[
            {
                "actor_id": "fixture-infrastructure-owner",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "signature": release.sha256_json(
                    {"actor_id": "fixture-infrastructure-owner", "subject_digest": subject}
                ),
                "subject_digest": subject,
                "synthetic": True,
            }
        ],
    )
    (root / "infrastructure-owner-recovery.json").write_bytes(release.canonical_json(authorization))
    argv = [
        value.replace("fixture-promotion-recovery-3", "fixture-promotion-recovery-4").replace(
            "promote-release-candidate/003", "promote-release-candidate/004"
        )
        for value in argv
    ]
    recovered = _run_release_tool("promote_release_candidate.py", argv)
    assert recovered.returncode == 0, recovered.stderr or recovered.stdout
    record = release.read_json(root / "promotion-recovery.json")
    release.validate_record(record, "release-promotion-lock-recovery")
    assert record["data"]["active_lock_digest"] == release.sha256_json(active)
    assert release.read_json(root / "fixture-promotion-lock/00000002.json")["state"] == "RELEASED"
    with pytest.raises(release.ReleaseControlError, match="epoch is stale"):
        release.require_lock_owner(
            root / "fixture-promotion-lock",
            owner="fixture-publisher",
            epoch=1,
            now=int(time.time()),
        )
    monkeypatch.setenv("METRIPLANE_RELEASE_TEST_PROMOTION_LEASE_SECONDS", "300")
    retried = _run_release_tool(
        "promote_release_candidate.py", _promotion_execute_argv(root, sequence=5)
    )
    assert retried.returncode == 0, retried.stderr or retried.stdout
    assert (root / "active-promotion-lock-00000003.json").is_file()


@pytest.mark.parametrize(
    ("tool", "form_number"),
    [
        ("resolve_release_predecessor.py", 0),
        ("resolve_release_predecessor.py", 1),
        ("validate_release_predecessor.py", 0),
        ("validate_release_predecessor.py", 1),
    ],
)
def test_v04_predecessor_contract_exposes_genesis_and_reconciled_lkg_forms(
    tool: str, form_number: int
) -> None:
    contract = release.TOOL_CONTRACTS[tool]
    form = contract.forms[form_number]
    equals = dict(form.equals)
    argv = [tool]
    for flag in sorted(form.required):
        argv.append("--" + flag)
        if flag not in contract.boolean:
            argv.append(sorted(equals.get(flag, {"synthetic-input"}))[0])
    arguments = release._release_original_arguments(tool, argv)
    assert arguments["milestone"] == "v0.4"
    assert {"release-context", "predecessor-policy"} <= arguments.keys()
    if tool == "resolve_release_predecessor.py":
        assert "prerequisite-proofs" in arguments
    genesis_flag = (
        "genesis-only" if tool == "resolve_release_predecessor.py" else "validate-genesis-only"
    )
    lkg_flag = "require-prior-lkg" if tool == "resolve_release_predecessor.py" else "read-back-lkg"
    assert (genesis_flag in arguments) is (form_number == 0)
    assert (lkg_flag in arguments) is (form_number == 1)


def test_v04_predecessor_contract_rejects_mixed_genesis_and_lkg_authority() -> None:
    contract = release.TOOL_CONTRACTS["resolve_release_predecessor.py"]
    form = contract.forms[0]
    equals = dict(form.equals)
    argv = ["resolve_release_predecessor.py"]
    for flag in sorted(form.required):
        argv.append("--" + flag)
        if flag not in contract.boolean:
            argv.append(sorted(equals.get(flag, {"synthetic-input"}))[0])
    argv.extend(["--require-prior-lkg", "--require-prior-decision-closed", "--project-id", "p"])
    with pytest.raises(release.ReleaseControlError, match="exactly one complete command form"):
        release._release_original_arguments("resolve_release_predecessor.py", argv)


def test_canonical_release_geneses_are_closed_and_cross_bound() -> None:
    root = Path(__file__).resolve().parents[1] / "docs/releases"
    release_genesis = json.loads((root / "v0.3.0-genesis.json").read_bytes())
    chain_genesis = json.loads((root / "release-evidence-chain-genesis.json").read_bytes())
    attempt_genesis = json.loads((root / "release-attempt-index-genesis.json").read_bytes())
    assert release_genesis == {
        "annotated_tag_object": "ef808e4b9bb7b47b550ce2bef2cd941984731239",
        "authority": "historical-observation",
        "commit": "e8ee6c63deaee47bd450c5d6c7523d5bd699852a",
        "schema_version": "metriplane.release-genesis.v1",
        "synthetic": False,
        "tree": "93125794437408f2ff157a82024e1c7809136941",
        "version": "v0.3.0",
    }
    assert chain_genesis == {
        "predecessor": None,
        "release": "v0.3.0",
        "release_genesis_digest": release.sha256_json(release_genesis),
        "schema_version": "metriplane.release-evidence-chain-genesis.v1",
        "sequence": 0,
    }
    assert attempt_genesis == {
        "cas_required": True,
        "entries": [],
        "epoch": 0,
        "no_overwrite": True,
        "schema_version": "metriplane.release-attempt-index-genesis.v1",
    }


def _gate_input_plan_fixture(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, new_burn: bool = False, relative: bool = False
) -> tuple[release.ReleaseInvocation, dict[str, str]]:
    """Actual Git-bound common intent over synthetic transport, with no native authority."""
    argv, expected = _gate_declared_capture_fixture(root, new_burn=new_burn)
    repository = root.parent if relative else root.with_name(root.name + "-source")
    repository.mkdir(parents=True, exist_ok=True)
    assert not (repository / ".git").exists(), "fixture repository must be fresh"
    arguments = release._release_original_arguments(argv[0], argv)
    for flag, field in release._RELEASE_GATE_SOURCE_FIELDS.items():
        path = repository / release._SOURCE_REGISTRY_INPUTS[field]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(arguments[flag]).read_bytes())
    # Only the seven source blobs are tracked; all synthetic run/fault evidence is external to Git.
    (repository / ".gitignore").write_text("*\n")
    _gate_reservation_git(repository, "init", "-q")
    _gate_reservation_git(
        repository, "add", "-f", ".gitignore", *release._SOURCE_REGISTRY_INPUTS.values()
    )
    _gate_reservation_git(
        repository, "commit", "-qm", "Explicit synthetic transport fixture; no native authority"
    )
    monkeypatch.chdir(repository)
    if relative:
        argv = [
            str(Path(value).relative_to(repository)) if value.startswith(str(root)) else value
            for value in argv
        ]
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    held = release._release_gate_prepare_inputs(argv[1:], root / "invocations/gate-input/001")
    context = release.begin_release_invocation(
        argv[0],
        argv[1:],
        root / "invocations/gate-input/001",
        input_paths=[
            (root / name, "metriplane." + kind + ".v1")
            for name, kind, _, _, _ in held.captured.rows
        ],
        planned_outputs=[(root / name, kind) for name, kind in release._RELEASE_GATE_OUTPUT_PLAN],
        _gate_inputs=held,
    )
    assert dict(held.registry_digests) == expected
    return context, expected


@pytest.mark.parametrize("new_burn", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_gate_input_plan_replays_original_closure_after_relocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_burn: bool, relative: bool
) -> None:
    historical = tmp_path / "historical"
    historical.mkdir()
    context, expected = _gate_input_plan_fixture(
        historical, monkeypatch, new_burn=new_burn, relative=relative
    )
    original_intent = (context.directory / "intent.json").read_bytes()
    current = tmp_path / "nested/current"
    current.parent.mkdir()
    historical.rename(current)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    actual_reader = release._release_held_path

    def no_historical_read(path: Path, **kwargs: Any) -> Any:
        assert not path.is_relative_to(historical)
        return actual_reader(path, **kwargs)

    monkeypatch.setattr(release, "_release_held_path", no_historical_read)
    moved = release.ReleaseInvocation(
        current / "invocations/gate-input/001", current, context.intent
    )
    result = release._release_gate_input_plan_replay(moved, expected_registry_digests=expected)
    assert result["historical_root"] == historical
    assert result["target_control_origin"] == "inputs/target-resolution.json"
    assert result["captured"].root == current
    assert result["original_arguments"] == release._release_original_arguments(
        context.intent["tool"], context.intent["argv"]
    )
    assert (moved.directory / "intent.json").read_bytes() == original_intent
    assert not historical.exists()
    assert not (current / "gate-input.json").exists()
    assert not (current / "scenario-catalog.json").exists()
    assert not (moved.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-input",
        "extra-input",
        "wrong-type",
        "wrong-hash",
        "relative-inventory",
        "outside-inventory",
        "wrong-target-argument",
        "outside-direct",
        "different-direct-suffix",
        "wrong-output",
        "missing-catalog-plan",
        "extra-output",
        "wrong-output-type",
        "wrong-original-stage",
        "wrong-original-sequence",
        "mutable-context",
        "changed-sidecar",
        "noncanonical-input-path",
        "wrong-current-root",
        "wrong-registry",
    ],
)
def test_gate_input_plan_rejects_changed_original_correspondence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, expected = _gate_input_plan_fixture(tmp_path, monkeypatch)
    intent = copy.deepcopy(context.intent)
    arguments = intent["argv"]

    def flag(name: str, value: str) -> None:
        arguments[arguments.index("--" + name) + 1] = value

    if mutation == "missing-input":
        intent["inputs"].pop()
    elif mutation == "extra-input":
        path = tmp_path / "inputs/extra.json"
        path.write_bytes(b"unowned extra")
        intent["inputs"].append(
            {
                "path": str(path),
                "schema_id": "metriplane.prerequisite-original.v1",
                "sha256": release.sha256_bytes(path.read_bytes()),
            }
        )
        intent["inputs"].sort(key=lambda row: row["path"])
    elif mutation == "wrong-type":
        intent["inputs"][0]["schema_id"] = "metriplane.unowned.v1"
    elif mutation == "wrong-hash":
        intent["inputs"][0]["sha256"] = "0" * 64
    elif mutation == "relative-inventory":
        intent["inputs"][0]["path"] = "inputs/relative.json"
    elif mutation == "outside-inventory":
        intent["inputs"][0]["path"] = str(tmp_path.parent / "outside.json")
    elif mutation == "wrong-target-argument":
        flag("target-resolution", str(tmp_path / "inputs/target-resolution.json"))
    elif mutation == "outside-direct":
        flag("obligations", str(tmp_path.parent / "obligations.json"))
    elif mutation == "different-direct-suffix":
        path = tmp_path / "inputs/second-obligations.json"
        path.write_bytes((tmp_path / "inputs/obligations.json").read_bytes())
        flag("obligations", str(path))
    elif mutation == "wrong-output":
        flag("out", str(tmp_path / "other-gate.json"))
    elif mutation == "missing-catalog-plan":
        intent["planned_outputs"].pop()
    elif mutation == "extra-output":
        intent["planned_outputs"].append(
            {"path": "zzz.json", "schema_id": "metriplane.release-gate-input.v1"}
        )
    elif mutation == "wrong-output-type":
        intent["planned_outputs"][1]["schema_id"] = "metriplane.release-gate-input.v1"
    elif mutation == "wrong-original-stage":
        flag("invocation-dir", str(tmp_path / "invocations/other/001"))
    elif mutation == "wrong-original-sequence":
        flag("invocation-dir", str(tmp_path / "invocations/gate-input/002"))
    elif mutation == "mutable-context":
        context.intent["tool_version"] += "-forged"
    elif mutation == "changed-sidecar":
        (tmp_path / "inputs/obligations.json").write_bytes(b"{}")
    elif mutation == "noncanonical-input-path":
        flag("obligations", str(tmp_path / "inputs") + "/../inputs/obligations.json")
    elif mutation == "wrong-current-root":
        context = release.ReleaseInvocation(context.directory, tmp_path.parent, context.intent)
    elif mutation == "wrong-registry":
        expected["obligations"] = "0" * 64
    if mutation not in {
        "mutable-context",
        "changed-sidecar",
        "wrong-current-root",
        "wrong-registry",
    }:
        intent["invocation_id"] = release._intent_identity(intent)
        (context.directory / "intent.json").chmod(0o600)
        (context.directory / "intent.json").write_bytes(release.canonical_json(intent))
        context = release.ReleaseInvocation(context.directory, context.root, intent)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_input_plan_replay(context, expected_registry_digests=expected)


@pytest.mark.parametrize("mutation", ["redirect", "omit", "wrong-type", "changed-bytes"])
def test_gate_input_plan_checks_original_membership_before_read_and_hash_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, expected = _gate_input_plan_fixture(tmp_path, monkeypatch)
    intent = copy.deepcopy(context.intent)
    original_path = tmp_path / "inputs/obligations.json"
    selected = original_path
    if mutation == "redirect":
        selected = tmp_path / "inputs/copied-obligations.json"
        selected.write_bytes(original_path.read_bytes())
        intent["argv"][intent["argv"].index("--obligations") + 1] = str(selected)
    elif mutation == "omit":
        intent["inputs"] = [row for row in intent["inputs"] if row["path"] != str(selected)]
    elif mutation == "wrong-type":
        for row in intent["inputs"]:
            if row["path"] == str(selected):
                row["schema_id"] = "metriplane.wrong-semantic-owner.v1"
    else:
        selected.write_bytes(original_path.read_bytes() + b" ")
    intent["invocation_id"] = release._intent_identity(intent)
    (context.directory / "intent.json").chmod(0o600)
    (context.directory / "intent.json").write_bytes(release.canonical_json(intent))
    context = release.ReleaseInvocation(context.directory, context.root, intent)
    original_reader, original_parser = release._release_held_path, release._source_json
    opened, parsed = [], []

    def reader(path: Path, **kwargs: Any) -> Any:
        if path == selected:
            opened.append(path)
        return original_reader(path, **kwargs)

    def parser(raw: bytes, label: str) -> Any:
        if label == "gate direct obligations":
            parsed.append(label)
        return original_parser(raw, label)

    monkeypatch.setattr(release, "_release_held_path", reader)
    monkeypatch.setattr(release, "_source_json", parser)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_input_plan_replay(context, expected_registry_digests=expected)
    assert not parsed
    assert opened == ([selected] if mutation == "changed-bytes" else [])


def test_gate_input_plan_rejects_substituted_root_before_any_member_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    root = tmp_path / "original-root"
    root.mkdir()
    context, expected = _gate_input_plan_fixture(root, monkeypatch)
    original_capture, original_reader = (
        release._release_gate_declared_input_capture,
        release._release_held_path,
    )
    swapped = False
    member_reads = []

    def substitute(captured_root: Path, argv: list[str], **kwargs: Any) -> Any:
        nonlocal swapped
        parked = tmp_path / "parked-original"
        root.rename(parked)
        shutil.copytree(parked, root)
        swapped = True
        return original_capture(captured_root, argv, **kwargs)

    def reader(path: Path, **kwargs: Any) -> Any:
        if swapped and not kwargs.get("directory", False):
            member_reads.append(path)
        return original_reader(path, **kwargs)

    monkeypatch.setattr(release, "_release_gate_declared_input_capture", substitute)
    monkeypatch.setattr(release, "_release_held_path", reader)
    with pytest.raises(release.ReleaseControlError, match="substituted"):
        release._release_gate_input_plan_replay(context, expected_registry_digests=expected)
    assert swapped and not member_reads


@pytest.mark.parametrize("replace", ["root", "inputs"])
def test_gate_input_plan_preserves_all_ancestor_pins_through_final_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace: str
) -> None:
    import shutil

    root = tmp_path / "original-root"
    root.mkdir()
    context, expected = _gate_input_plan_fixture(root, monkeypatch)
    original_capture = release._ReleaseCapturedFiles.capture
    original_read = os.read
    swapped = False
    byte_reads = []

    def substitute(
        cls: type[release._ReleaseCapturedFiles],
        captured_root: Path,
        declared: Any,
        **kwargs: Any,
    ) -> release._ReleaseCapturedFiles:
        nonlocal swapped
        target = root if replace == "root" else root / "inputs"
        parked = tmp_path / "parked-original"
        target.rename(parked)
        shutil.copytree(parked, target)
        swapped = True
        return original_capture(captured_root, declared, **kwargs)

    def read(descriptor: int, size: int) -> bytes:
        if swapped:
            byte_reads.append(descriptor)
        return original_read(descriptor, size)

    monkeypatch.setattr(release._ReleaseCapturedFiles, "capture", classmethod(substitute))
    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_input_plan_replay(context, expected_registry_digests=expected)
    assert swapped and byte_reads == []


def _gate_declared_capture_fixture(
    tmp_path: Path, *, new_burn: bool = False
) -> tuple[list[str], dict[str, str]]:
    """Complete declared transport carrier only; deliberately invalid native journal authority."""
    root = tmp_path
    inputs = root / "inputs"
    inputs.mkdir()
    source = Path(__file__).resolve().parents[1]

    def ref(path: Path, raw: bytes, *, container: Path = inputs) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {
            "path": path.relative_to(container).as_posix(),
            "bytes": len(raw),
            "sha256": release.sha256_bytes(raw),
        }

    def raw_authority(value: dict[str, Any]) -> None:
        path = inputs / value["path"]
        raw = ("explicit transport fixture: " + value["path"]).encode()
        value.update(ref(path, raw))

    files = {
        "readiness-registry": "release-readiness",
        "obligations": "release-test-obligations",
        "scenarios": "release-scenarios",
        "environments": "supported-environments",
        "targets": "release-targets",
        "evidence-stores": "release-evidence-stores",
        "task-state-policy": "release-task-state-policy",
    }
    digests = {}
    for flag, name in files.items():
        data = json.loads((source / "docs/status" / (name + ".json")).read_bytes())
        if flag == "readiness-registry":
            raw_authority(data["catalog_binding"]["source"])
            raw_authority(data["linear_capture_policy"]["provider_transport_binding"])
            for field in ["provider_issue_bindings", "release_contexts"]:
                for row in data[field]:
                    raw_authority(row["assignment_authority"])
        if flag in {"obligations", "scenarios", "environments"}:
            for row in data["authority_sources"]:
                raw_authority(row["raw_file"])
        if flag == "environments":
            for row in data["environments"]:
                for item in [
                    *row["authority"],
                    *row["runtime"]["toolchain_sources"],
                    row["runtime"]["lock_source"],
                ]:
                    if isinstance(item, dict) and item.get("source_bytes") is not None:
                        raw_authority(item["source_bytes"])
        raw = release.canonical_json(data)
        ref(inputs / (flag + ".json"), raw)
        digests[flag] = release.sha256_bytes(raw)
    context, _ = _context_policy_fixture()
    baseline = context["data"]["comparison_baseline"]
    for field in ["tag_observation", "release_observation"]:
        raw_authority(baseline[field])
    for row in baseline["artifacts"]:
        raw_authority(row["readback"])
    context = release.make_record(
        "release-context",
        context["data"],
        invocation_id="fixture-capture-context",
        sequence=1,
        synthetic=True,
    )
    context_ref = ref(inputs / "release-context.json", release.canonical_json(context))
    policy, _ = _predecessor_policy_fixture()
    policy["selection_authority"]["readiness_registry"] = ref(
        inputs / "readiness-registry.json", (inputs / "readiness-registry.json").read_bytes()
    )
    for row in policy["expected_predecessor_subject"]["artifacts"]:
        raw_authority(row["readback"])
    raw_authority(policy["expected_predecessor_decision"]["authority"]["raw_registry"])
    ref(inputs / "predecessor-policy.json", release.canonical_json(policy))
    argv = [
        "prepare_release_gate_input.py",
        "--milestone",
        "v0.4",
        "--expected-predecessor-milestone",
        "v0.4",
        "--invocation-dir",
        str(root / "invocations/gate-input/001"),
        "--out",
        str(root / "gate-input.json"),
    ]
    for flag in [*files, "release-context", "predecessor-policy", "prerequisite-proofs"]:
        argv.extend(["--" + flag, str(inputs / (flag + ".json"))])
    proofs, originals = [], []
    # Context is shared by the direct input and an imported producer input; no duplicate file.
    originals.append(context_ref)
    for flag, producer in [
        ("linear-snapshot", "capture_linear_release_snapshot.py"),
        ("role-assignments", "record_release_role_assignments.py"),
        ("target-burn", "record_release_target_burn.py"),
        ("target-resolution", "resolve_release_target.py"),
        *(([("target-burn-index-receipt", "update_release_attempt_index.py")]) if new_burn else []),
    ]:
        kind, record_kind, companion = release._RELEASE_GATE_PREREQUISITES[producer]
        record = release.make_record(
            kind,
            {} if record_kind is None else {"kind": record_kind},
            invocation_id="fixture-carrier-" + flag,
            sequence=1,
            synthetic=True,
        )
        path = inputs / (flag + ".json")
        record_ref = ref(path, release.canonical_json(record), container=inputs)
        originals.append(record_ref)
        intent = ref(
            inputs / "original" / flag / "intent.json",
            b"intentionally invalid original intent; transport test only",
            container=inputs,
        )
        terminal = ref(
            inputs / "original" / flag / "invocation.json",
            b"intentionally invalid original terminal; transport test only",
            container=inputs,
        )
        originals.extend([intent, terminal])
        row = {
            "producer": producer,
            "stage": release._invocation_stage(producer),
            "record_type": kind,
            "record_kind": record_kind,
            "record": record_ref,
            "record_digest": release.sha256_json(record),
            "original_run_root": "inputs/original",
            "producer_intent": intent,
            "producer_terminal": terminal,
            "companion_validations": [],
        }
        if companion:
            ci = ref(
                inputs / "original" / flag / "companion-intent.json",
                b"invalid companion transport",
                container=inputs,
            )
            ct = ref(
                inputs / "original" / flag / "companion-terminal.json",
                b"invalid companion transport",
                container=inputs,
            )
            originals.extend([ci, ct])
            row["companion_validations"] = [
                {
                    "tool": companion,
                    "stage": release._invocation_stage(companion),
                    "intent": ci,
                    "terminal": ct,
                }
            ]
        proofs.append(row)
        if flag == "target-resolution":
            (root / "target-resolution.json").write_bytes(path.read_bytes())
            argv.extend(["--" + flag, str(root / "target-resolution.json")])
        else:
            argv.extend(["--" + flag, str(path)])
    bundle = {
        "schema_version": "metriplane.release-prerequisite-proofs.v1",
        "release_context_digest": release.sha256_json(context),
        "proofs": proofs,
        "captured_original_files": originals,
    }
    ref(inputs / "prerequisite-proofs.json", release.canonical_json(bundle))
    if not new_burn:
        argv.append("--no-new-burn")
    return argv, digests


@pytest.mark.parametrize("new_burn", [False, True])
def test_gate_declared_capture_binds_all_explicit_files_before_effects(
    tmp_path: Path, new_burn: bool
) -> None:
    argv, expected = _gate_declared_capture_fixture(tmp_path, new_burn=new_burn)
    result = release._release_gate_declared_input_capture(
        tmp_path, argv, expected_registry_digests=expected
    )
    capture = result["captured"]
    assert not (tmp_path / "invocations").exists()
    assert not (tmp_path / "gate-input.json").exists()
    assert not (tmp_path / "scenario-catalog.json").exists()
    assert result["target_control_origin"] == "inputs/target-resolution.json"
    assert capture.read("target-resolution.json", kind="release-target-resolution") == capture.read(
        "inputs/target-resolution.json", kind="prerequisite-original"
    )
    assert capture.read("inputs/release-context.json", kind="prerequisite-original")
    assert dict(result["semantic_roles"])["inputs/release-context.json"] == ("release-context",)
    semantic = result["semantic_captured"]
    assert semantic.read("inputs/release-context.json", kind="release-context") == capture.read(
        "inputs/release-context.json", kind="prerequisite-original"
    )
    assert {(row[0], *row[2:]) for row in semantic.rows} == {
        (row[0], *row[2:]) for row in capture.rows
    }
    with pytest.raises(release.ReleaseControlError):
        capture.read("inputs/release-context.json", kind="release-context")
    semantic.revalidate()
    capture.revalidate()
    # Opaque intentionally invalid journals cannot qualify the imported authority merely by capture.
    bundle_path = tmp_path / "inputs/prerequisite-proofs.json"
    with pytest.raises(release.ReleaseControlError):
        release._release_prerequisite_origin_rows(
            json.loads(bundle_path.read_bytes()),
            bundle_path=bundle_path,
            captured=capture,
            expected_context_digest=json.loads(bundle_path.read_bytes())["release_context_digest"],
            before="2026-09-08T00:00:00Z",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "outside-input",
        "alternate-output",
        "alternate-target-path",
        "invalid-invocation",
        "unknown-flag",
        "missing-registry-digest",
        "wrong-registry-digest",
        "changed-raw-authority",
        "unsafe-original-path",
        "noninteger-size",
        "duplicate-original",
        "unlisted-original",
        "current-context-substitution",
        "copied-direct-cli",
        "changed-fixed-target",
        "duplicate-target-origin",
        "incompatible-semantic-role",
        "unbound-trust",
    ],
)
def test_gate_declared_capture_rejects_incomplete_or_ambiguous_plan(
    tmp_path: Path, mutation: str
) -> None:
    argv, expected = _gate_declared_capture_fixture(tmp_path)
    bundle_path = tmp_path / "inputs/prerequisite-proofs.json"
    bundle = json.loads(bundle_path.read_bytes())
    if mutation == "outside-input":
        argv[argv.index("--obligations") + 1] = str(tmp_path / "outside.json")
    elif mutation == "alternate-output":
        argv[argv.index("--out") + 1] = str(tmp_path / "different-gate.json")
    elif mutation == "alternate-target-path":
        argv[argv.index("--target-resolution") + 1] = str(
            tmp_path / "inputs/target-resolution.json"
        )
    elif mutation == "invalid-invocation":
        argv[argv.index("--invocation-dir") + 1] = str(tmp_path / "invocations/gate-input/0001")
    elif mutation == "unknown-flag":
        argv.extend(["--unknown", "value"])
    elif mutation == "missing-registry-digest":
        del expected["scenarios"]
    elif mutation == "wrong-registry-digest":
        expected["scenarios"] = "f" * 64
    elif mutation == "changed-raw-authority":
        (tmp_path / "inputs/authority/09_RELEASE_READINESS_MAP.json").write_bytes(
            b"changed declared bytes"
        )
    elif mutation == "unsafe-original-path":
        bundle["captured_original_files"][0]["path"] = "../target-resolution.json"
    elif mutation == "noninteger-size":
        bundle["captured_original_files"][0]["bytes"] = float(
            bundle["captured_original_files"][0]["bytes"]
        )
    elif mutation == "duplicate-original":
        bundle["captured_original_files"].append(bundle["captured_original_files"][0])
    elif mutation == "unlisted-original":
        bundle["captured_original_files"].pop(1)
    elif mutation == "current-context-substitution":
        bundle["release_context_digest"] = "f" * 64
    elif mutation == "copied-direct-cli":
        original = tmp_path / "inputs/linear-snapshot.json"
        (tmp_path / "inputs/copied-linear.json").write_bytes(original.read_bytes())
        argv[argv.index("--linear-snapshot") + 1] = str(tmp_path / "inputs/copied-linear.json")
    elif mutation == "changed-fixed-target":
        (tmp_path / "target-resolution.json").write_bytes(
            (tmp_path / "target-resolution.json").read_bytes() + b" "
        )
    elif mutation == "duplicate-target-origin":
        row = copy.deepcopy(
            next(r for r in bundle["proofs"] if r["record_type"] == "release-target-resolution")
        )
        row["record"]["path"] = "duplicate-target.json"
        (tmp_path / "inputs/duplicate-target.json").write_bytes(
            (tmp_path / "inputs/target-resolution.json").read_bytes()
        )
        bundle["proofs"].append(row)
        bundle["captured_original_files"].append(row["record"])
    elif mutation == "incompatible-semantic-role":
        argv[argv.index("--scenarios") + 1] = argv[argv.index("--obligations") + 1]
    else:
        argv.extend(["--authority-policy-digest", "f" * 64])
    bundle_path.write_bytes(release.canonical_json(bundle))
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_declared_input_capture(
            tmp_path, argv, expected_registry_digests=expected
        )
    assert not (tmp_path / "invocations").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-readiness-field",
        "malformed-original-refs",
        "wrong-context-type",
        "context-hardlink",
        "source-symlink",
        "extra-root-target-producer",
        "missing-gate-context-flag",
    ],
)
def test_gate_declared_capture_rejects_malformed_inputs_before_reservation(
    tmp_path: Path, mutation: str
) -> None:
    argv, expected = _gate_declared_capture_fixture(tmp_path)
    if mutation == "missing-readiness-field":
        path = tmp_path / "inputs/readiness-registry.json"
        data = json.loads(path.read_bytes())
        del data["catalog_binding"]
        path.write_bytes(release.canonical_json(data))
        expected["readiness-registry"] = release.sha256_bytes(path.read_bytes())
    elif mutation == "malformed-original-refs":
        path = tmp_path / "inputs/prerequisite-proofs.json"
        data = json.loads(path.read_bytes())
        data["captured_original_files"] = {"not": "a list"}
        path.write_bytes(release.canonical_json(data))
    elif mutation == "wrong-context-type":
        path = tmp_path / "inputs/release-context.json"
        record = json.loads(path.read_bytes())
        path.write_bytes(
            release.canonical_json(
                release.make_record(
                    "release-protected-input",
                    record["data"],
                    invocation_id="fixture-wrong-type",
                    sequence=1,
                    synthetic=True,
                )
            )
        )
    elif mutation == "context-hardlink":
        os.link(tmp_path / "inputs/release-context.json", tmp_path / "context-alias.json")
    elif mutation == "source-symlink":
        path = tmp_path / "inputs/authority/09_RELEASE_READINESS_MAP.json"
        target = path.with_name("actual-authority.json")
        path.rename(target)
        path.symlink_to(target.name)
    elif mutation == "extra-root-target-producer":
        argv[argv.index("--out") + 1] = str(tmp_path / "target-resolution.json")
    else:
        index = argv.index("--release-context")
        del argv[index : index + 2]
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_declared_input_capture(
            tmp_path, argv, expected_registry_digests=expected
        )
    assert not (tmp_path / "invocations").exists()


def test_gate_declared_capture_detects_same_byte_file_replacement_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv, expected = _gate_declared_capture_fixture(tmp_path)
    original = release._ReleaseCapturedFiles.capture.__func__

    def substitute(cls: Any, root: Path, declared: Any, **kwargs: Any) -> Any:
        path = root / "inputs/readiness-registry.json"
        temporary = root / "inputs/substitute.json"
        temporary.write_bytes(path.read_bytes())
        temporary.replace(path)
        return original(cls, root, declared, **kwargs)

    monkeypatch.setattr(release._ReleaseCapturedFiles, "capture", classmethod(substitute))
    with pytest.raises(release.ReleaseControlError, match="changed before byte access"):
        release._release_gate_declared_input_capture(
            tmp_path, argv, expected_registry_digests=expected
        )


def test_gate_declared_capture_detects_intermediate_parent_replacement_with_same_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv, expected = _gate_declared_capture_fixture(tmp_path)
    original = release._ReleaseCapturedFiles.capture.__func__

    def substitute(cls: Any, root: Path, declared: Any, **kwargs: Any) -> Any:
        parent = root / "inputs/authority/configuration/.github"
        leaf = parent / "workflows"
        leaf.rename(root / "held-workflows")
        parent.rename(root / "retained-original-parent")
        parent.mkdir()
        (root / "held-workflows").rename(leaf)
        return original(cls, root, declared, **kwargs)

    monkeypatch.setattr(release._ReleaseCapturedFiles, "capture", classmethod(substitute))
    with pytest.raises(release.ReleaseControlError, match="ancestor changed before member access"):
        release._release_gate_declared_input_capture(
            tmp_path, argv, expected_registry_digests=expected
        )


@pytest.mark.parametrize("flag", ["obligations", "scenarios", "environments"])
@pytest.mark.parametrize("launch", ["argv", "workflow_job", "supplied_attestation"])
def test_gate_declared_capture_enumerates_configured_recipe_and_backend_raw_fields(
    tmp_path: Path, flag: str, launch: str
) -> None:
    """Exercise declared-byte closure only; configured fixtures do not authorize execution."""
    import hashlib

    argv, expected = _gate_declared_capture_fixture(tmp_path)
    inputs = tmp_path / "inputs"
    wanted: dict[str, str] = {}

    def ref(name: str, kind: str) -> dict[str, Any]:
        raw = ("explicit configured transport fixture: " + name).encode()
        path = inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        wanted["inputs/" + name] = kind
        return {"path": name, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}

    def source(name: str) -> dict[str, Any]:
        original = ref("configured/" + name, "configuration-source")
        raw = (inputs / original["path"]).read_bytes()
        return {
            "binding": "candidate_source_blob",
            "repository": "Miko997/metriplane",
            "path": name,
            "git_mode": "100644",
            "git_blob": hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
            ).hexdigest(),
            "source_bytes": original,
        }

    def owner(name: str) -> dict[str, Any]:
        return {
            "kind": "python_entry",
            "source_path": name,
            "symbol": "run",
            "source": source(name),
        }

    recipe: dict[str, Any] = {
        "owner": owner("recipe-owner.py"),
        "required_operation_owner": owner("operation.py"),
        "terminal_owner": "metriplane/release_control.py",
        "effect_class": "existing_release_mutation",
        "input_slots": [
            {
                "name": "python_executable",
                "kind": "executable",
                "binding_owner": "environment_observation",
                "must_exist_before_execution": True,
            }
        ],
        "input_sidecars": [ref("configured/recipe-input.json", "execution-sidecar")],
        "resources": [
            {
                "id": "fixture-resource",
                "kind": "fixture",
                "profile_id": "fixture-profile",
                "authority": [
                    {
                        "source_id": "fixture-authority",
                        "json_pointer": "",
                        "canonical_subject_digest": "a" * 64,
                    }
                ],
                "binding": {
                    "state": "CONFIGURED",
                    "configuration": ref("configured/resource.json", "resource-configuration"),
                },
            }
        ],
        "timeout_seconds": 10,
        "expected_process_exits": [0],
        "expected_outputs": [
            {
                "id": "output",
                "root": "execution_output_root",
                "path": "result.json",
                "media_type": "application/json",
                "schema_source_id": None,
                "minimum_bytes": 1,
                "validator_owner": owner("output-validator.py"),
                "required": True,
            }
        ],
        "thresholds": [],
        "cleanliness": {
            key: "FAIL"
            for key in [
                "unexpected_warnings",
                "unexpected_skip",
                "unexpected_xfail",
                "unrecorded_retry",
                "process_or_file_leak",
            ]
        },
    }
    if launch == "workflow_job":
        recipe["launch"] = {
            "kind": launch,
            "workflow_source": source("workflow.yml"),
            "job_id": "fixture-job",
            "matrix": [],
            "dispatch_owner": owner("dispatch.py"),
        }
    elif launch == "supplied_attestation":
        recipe["launch"] = {
            "kind": launch,
            "input_slot": "attestation_record",
            "validator_owner": owner("attestation-validator.py"),
            "required_role": "non_author_reviewer",
        }
        recipe["owner"] = {
            "kind": "supplied_attestation",
            "validator_source_path": "recipe-owner.py",
            "validator_symbol": "run",
            "source": source("recipe-owner.py"),
            "required_role": "non_author_reviewer",
        }
        recipe["input_slots"].append(
            {
                "name": "attestation_record",
                "kind": "signed_release_record",
                "binding_owner": "common_invocation",
                "must_exist_before_execution": True,
                "expected_record_type": "release-approval-decision",
                "record_schema_source_id": "fixture-authority",
                "required_role": "non_author_reviewer",
                "subject_binding": "EXISTING_RECORD_VALIDATOR_CURRENT_EXECUTION_CONTEXT",
                "authority_binding": "VALIDATED_ROLES_AND_INDEPENDENTLY_PINNED_EXISTING_KEYRING_POLICY",
            }
        )
    else:
        recipe["launch"] = {
            "kind": "argv",
            "argv": [{"kind": "binding", "name": "python_executable"}],
            "cwd": "checkout_root",
            "environment": [],
            "unset_environment": [],
            "shell": False,
        }
    path = inputs / (flag + ".json")
    data = json.loads(path.read_bytes())
    data["executors"] = [
        {
            "id": "fixture-executor",
            "phase": "qualification",
            "authority": [
                {
                    "source_id": "fixture-authority",
                    "json_pointer": "",
                    "canonical_subject_digest": "a" * 64,
                }
            ],
            "binding": {"state": "CONFIGURED", "recipe": recipe},
        }
    ]
    path.write_bytes(release.canonical_json(data))
    expected[flag] = release.sha256_bytes(path.read_bytes())
    if flag == "environments":
        data["environments"][0]["profile_id"] = "fixture-configured-profile"
        data["environments"][0]["platform"].update(architecture="x64", os_release="fixture-linux")
        data["environments"][0]["execution"] = {
            "state": "CONFIGURED",
            "owner": owner("environment-owner.py"),
            "configuration_sources": data["environments"][0]["authority"],
            "executor_ids": ["fixture-executor"],
        }
        path.write_bytes(release.canonical_json(data))
        expected[flag] = release.sha256_bytes(path.read_bytes())
    stores_path = inputs / "evidence-stores.json"
    stores = json.loads(stores_path.read_bytes())
    for backend in stores["backends"]:
        backend["binding_status"] = "BOUND_CONFIGURED"
        backend["live_binding"] = {
            "adapter_id": "explicit-fixture-no-deployed-authority",
            **{
                key: ref(
                    "configured/" + backend["backend_id"] + "-" + key + ".json",
                    "backend-binding-original",
                )
                for key in [
                    "public_configuration",
                    "owner_binding_authority",
                    "provider_resource_identity",
                    "administration_identity",
                    "durability_retention_policy",
                    "namespace_policy",
                ]
            },
        }
    stores_path.write_bytes(release.canonical_json(stores))
    expected["evidence-stores"] = release.sha256_bytes(stores_path.read_bytes())
    result = release._release_gate_declared_input_capture(
        tmp_path, argv, expected_registry_digests=expected
    )
    semantic = result["semantic_captured"]
    for name, kind in wanted.items():
        assert semantic.read(name, kind=kind) == (tmp_path / name).read_bytes()
    assert set(wanted) <= {row[0] for row in semantic.rows}
    missing = next(name for name in wanted if "recipe-input" in name)
    (tmp_path / missing).unlink()
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_declared_input_capture(
            tmp_path, argv, expected_registry_digests=expected
        )


def _original_role_byte_fixture(
    tmp_path: Path, mutation: str = "none"
) -> tuple[Path, dict[str, Any]]:
    """Synthetic envelope/byte mechanics only; the opaque policy/provenance grant no authority."""
    context, _ = _context_policy_fixture()
    provenance = {
        key: ("fixture original provenance: " + key).encode()
        for key in ("operator", "non_author_reviewer", "infrastructure_owner", "publisher")
    }
    policy_raw = b"explicit fixture policy; no native delegation proof"
    keyring_digest = "a" * 64
    authority_digest = release.release_authority_policy_digest(keyring_digest)
    assignments: dict[str, Any] = {
        "author_id": "fixture-author",
        "author_provider": "github",
        "authorized_executor_id": "fixture-operator",
        "non_author_reviewer_id": "fixture-non_author_reviewer",
        "publisher_id": "fixture-publisher",
        "task_id": "MP2-007",
        "milestone": "v0.4",
        "run_id": "fixture-run",
        "valid_from": "2020-01-01T00:00:00Z",
        "valid_until": "2020-01-02T00:00:00Z",
        "authority_policy_digest": authority_digest,
        "provider_attestation_keyring_digest": keyring_digest,
        "release_context_digest": release.sha256_json(context),
        "signing_method": "provider-attestation-v1",
        "independent_assurance": {"applicability": "not_applicable"},
    }
    for key, raw in provenance.items():
        assignments[key] = {
            "actor_id": "fixture-" + key,
            "backup_actor_id": "fixture-backup-" + key,
            "provider": "github",
            "role": "release_operator" if key == "operator" else key,
            "conflict_free": True,
            "provenance_digest": release.sha256_bytes(raw),
        }

    def ref(name: str, raw: bytes) -> dict[str, Any]:
        return {"path": name, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}

    context_raw = release.canonical_json(context)
    data = {
        "input_kind": "role_assignment",
        "assignment_kind": "protected_release_roles",
        "decision": "ASSIGNED",
        "authorized_role": "release_operator",
        "conflicts": [],
        "signer_identity": "fixture-operator",
        "signing_method": "provider-attestation-v1",
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2020-01-02T00:00:00Z",
        "authority_policy_digest": authority_digest,
        "provider_attestation_keyring_digest": keyring_digest,
        "assignments": assignments,
        "assignment_payload_digest": release.sha256_json(assignments),
        "release_context": ref("context.json", context_raw),
        "assignment_policy_registry": ref("policy.bin", policy_raw),
        "role_provenance_files": {
            **{key: ref(key + ".bin", raw) for key, raw in provenance.items()},
            "independent_assurance": None,
        },
        "subject_digests": [],
    }
    arguments: dict[str, Any] = {
        "context_path": tmp_path / "context.json",
        "expected_context_digest": release.sha256_json(context),
        "expected_run_id": "fixture-run",
        "expected_milestone": "v0.4",
        "expected_assignment_policy_digest": release.sha256_bytes(policy_raw),
        "expected_authority_policy_digest": authority_digest,
        "expected_keyring_digest": keyring_digest,
        "use_interval": ("2020-01-01T01:00:00Z", "2020-01-01T02:00:00Z"),
        "live": False,
    }
    if mutation == "reviewer-conflict":
        assignments["non_author_reviewer_id"] = assignments["author_id"]
        assignments["non_author_reviewer"]["actor_id"] = assignments["author_id"]
    elif mutation == "backup-conflict":
        assignments["publisher"]["backup_actor_id"] = assignments["operator"]["actor_id"]
    elif mutation == "payload-context":
        assignments["release_context_digest"] = "f" * 64
    elif mutation == "payload-keyring":
        assignments["provider_attestation_keyring_digest"] = "f" * 64
    elif mutation == "payload-policy":
        assignments["authority_policy_digest"] = "f" * 64
    elif mutation == "payload-run":
        assignments["run_id"] = "different-run"
    elif mutation == "payload-milestone":
        assignments["milestone"] = "v0.5"
    elif mutation == "provenance-binding":
        assignments["publisher"]["provenance_digest"] = "f" * 64
    elif mutation == "past-assignment":
        assignments["valid_until"] = "2020-01-01T02:00:00Z"
    elif mutation == "future-assignment":
        assignments["valid_from"] = "2020-01-01T01:00:01Z"
    elif mutation == "past-authorization":
        data["expires_at"] = "2020-01-01T02:00:00Z"
    elif mutation == "future-authorization":
        data["issued_at"] = "2020-01-01T01:00:01Z"
    elif mutation == "reversed-action":
        arguments["use_interval"] = tuple(reversed(arguments["use_interval"]))
    elif mutation == "missing-assurance":
        arguments["expected_milestone"] = assignments["milestone"] = context["data"][
            "framework_milestone"
        ] = "v0.9"
        context = release.make_record(
            "release-context",
            context["data"],
            invocation_id="fixture-context",
            sequence=1,
            synthetic=True,
        )
        context_raw = release.canonical_json(context)
        data["release_context"] = ref("context.json", context_raw)
        arguments["expected_context_digest"] = assignments["release_context_digest"] = (
            release.sha256_json(context)
        )
    elif mutation == "unneeded-assurance":
        data["role_provenance_files"]["independent_assurance"] = data["role_provenance_files"][
            "publisher"
        ]
    elif mutation == "extra-producer-field":
        data["producer_intent_digest"] = "f" * 64
    elif mutation == "wrong-signer":
        data["signer_identity"] = "fixture-different-signer"
    elif mutation == "expected-policy":
        arguments["expected_assignment_policy_digest"] = "f" * 64
    elif mutation == "expected-context":
        arguments["expected_context_digest"] = "f" * 64
    elif mutation == "wrong-context-path":
        arguments["context_path"] = tmp_path / "identical-context.json"
    elif mutation == "unsafe-provenance":
        data["role_provenance_files"]["publisher"]["path"] = "../publisher.bin"
    elif mutation == "noninteger-bytes":
        data["role_provenance_files"]["publisher"]["bytes"] = float(len(provenance["publisher"]))
    elif mutation == "live-fixture":
        arguments["live"] = True
    data["assignment_payload_digest"] = release.sha256_json(assignments)
    data["subject_digests"] = [
        {"subject": "assignment_payload", "sha256": release.sha256_json(assignments)},
        {"subject": "release_context", "sha256": release.sha256_json(context)},
        {"subject": "assignment_policy_registry", "sha256": release.sha256_bytes(policy_raw)},
    ]
    if mutation == "subject-order":
        data["subject_digests"].reverse()
    elif mutation == "subject-context-payload":
        data["subject_digests"][1]["sha256"] = context["payload_digest"]
    record = release.make_record(
        "release-protected-input",
        data,
        invocation_id="fixture-role-input",
        sequence=1,
        synthetic=True,
    )
    subject = release.signature_subject_digest(record)
    signature = {
        "actor_id": "fixture-operator",
        "provider": "test-fixture",
        "algorithm": "test-sha256-v1",
        "synthetic": True,
        "subject_digest": subject,
        "signature": release.sha256_json(
            {"actor_id": "fixture-operator", "subject_digest": subject}
        ),
    }
    if mutation == "copied-signature":
        old = release.make_record(
            "release-role-assignments",
            assignments,
            invocation_id="fixture-role-input",
            sequence=1,
            synthetic=True,
        )
        signature["subject_digest"] = release.signature_subject_digest(old)
        signature["signature"] = release.sha256_json(
            {"actor_id": "fixture-operator", "subject_digest": signature["subject_digest"]}
        )
    record = release.make_record(
        "release-protected-input",
        data,
        invocation_id="fixture-role-input",
        sequence=1,
        synthetic=True,
        signatures=[] if mutation == "missing-signature" else [signature],
    )
    (tmp_path / "protected.json").write_bytes(release.canonical_json(record))
    (tmp_path / "context.json").write_bytes(context_raw)
    (tmp_path / "policy.bin").write_bytes(policy_raw)
    declared = [
        ("protected.json", "prerequisite-original"),
        ("context.json", "prerequisite-original"),
        ("policy.bin", "prerequisite-original"),
    ]
    for key, raw in provenance.items():
        (tmp_path / (key + ".bin")).write_bytes(raw)
        declared.append((key + ".bin", "prerequisite-original"))
    arguments["captured"] = release._ReleaseCapturedFiles.capture(
        tmp_path, declared, forbidden=[], allowed_kinds=frozenset(kind for _, kind in declared)
    )
    return tmp_path / "protected.json", arguments


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize(
    "flag,kind",
    [
        ("signed-assignments", "metriplane.release-protected-input.v1"),
        ("release-context", "metriplane.release-context.v1"),
        ("policy", "metriplane.prerequisite-original.v1"),
    ],
)
def test_native_original_consumed_file_binds_actual_intent_after_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool, flag: str, kind: str
) -> None:
    root = tmp_path / "historical"
    root.mkdir()
    protected, options = _original_role_byte_fixture(root)
    tool = "record_release_role_assignments.py"
    directory = root / "invocations" / release._invocation_stage(tool) / "001"
    files = {
        "signed-assignments": protected,
        "release-context": options["context_path"],
        "policy": root / "policy.bin",
    }
    argv = ["--milestone", "v0.4", "--run-id", "fixture-run"]
    for name, path in {**files, "invocation-dir": directory, "out": root / "roles.json"}.items():
        argv.extend(["--" + name, str(path.relative_to(tmp_path) if relative else path)])
    if relative:
        monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    schema_ids = {
        "signed-assignments": "metriplane.release-protected-input.v1",
        "release-context": "metriplane.release-context.v1",
        "policy": "metriplane.prerequisite-original.v1",
    }
    context = release.begin_release_invocation(
        tool,
        argv,
        directory,
        input_paths=[(p, schema_ids[n]) for n, p in files.items()],
        planned_outputs=[(root / "roles.json", "metriplane.release-role-assignments.v1")],
    )
    declarations = [(row[0], row[1]) for row in options["captured"].rows]
    declarations.append(
        ((directory / "intent.json").relative_to(root).as_posix(), "prerequisite-original")
    )
    current = tmp_path / "current"
    root.rename(current)
    capture = release._ReleaseCapturedFiles.capture(
        current, declarations, forbidden=[], allowed_kinds=frozenset({"prerequisite-original"})
    )
    actual_reader = release._release_held_path
    selected_reads = []
    selected_path = current / files[flag].relative_to(root)

    def no_old_read(path: Path, **kwargs: Any) -> Any:
        assert not path.is_relative_to(root)
        if path == selected_path:
            selected_reads.append(path)
        return actual_reader(path, **kwargs)

    monkeypatch.setattr(release, "_release_held_path", no_old_read)
    selected, raw = release._release_original_consumed_file(
        context.intent,
        current_root=current,
        captured=capture,
        expected_tool=tool,
        flag=flag,
        expected_schema_id=kind,
    )
    assert selected == current / files[flag].relative_to(root)
    assert raw == selected.read_bytes()
    for invalid in [
        {"expected_schema_id": "metriplane.wrong.v1"},
        {"flag": "missing-input"},
        {"expected_tool": "capture_linear_release_snapshot.py"},
        {"current_root": tmp_path},
    ]:
        kwargs: dict[str, Any] = {
            "current_root": current,
            "captured": capture,
            "expected_tool": tool,
            "flag": flag,
            "expected_schema_id": kind,
            **invalid,
        }
        with pytest.raises(release.ReleaseControlError):
            release._release_original_consumed_file(context.intent, **kwargs)
    forged = copy.deepcopy(context.intent)
    forged["argv"][forged["argv"].index("--" + flag) + 1] += "-different"
    with pytest.raises(release.ReleaseControlError, match="differs from its captured original"):
        release._release_original_consumed_file(
            forged,
            current_root=current,
            captured=capture,
            expected_tool=tool,
            flag=flag,
            expected_schema_id=kind,
        )
    assert not (current / "roles.json").exists()
    assert not (current / directory.relative_to(root) / "invocation.json").exists()
    assert selected_reads == [selected_path]


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "changed-operator",
        "changed-backup",
        "changed-author",
        "changed-context",
        "changed-run",
        "changed-policy",
        "changed-validity",
        "missing-field",
        "extra-field",
        "protected-payload-digest",
        "different-protected-path",
        "different-protected-bytes",
        "copied-original-signatures",
        "new-output-signature",
        "different-producer-intent",
        "different-invocation",
        "different-sequence",
        "boolean-sequence",
        "wrong-locator",
        "wrong-kind",
        "different-mode",
        "not-passing",
        "expired-use",
    ],
)
def test_recorded_roles_copy_only_original_authenticated_assignment_bytes(
    tmp_path: Path, mutation: str
) -> None:
    protected, arguments = _original_role_byte_fixture(tmp_path)
    original_bytes = protected.read_bytes()
    original = json.loads(original_bytes)
    data = {
        **copy.deepcopy(original["data"]["assignments"]),
        "kind": "recorded_assignments",
        "original_protected_input": {
            "path": protected.name,
            "bytes": len(original_bytes),
            "sha256": release.sha256_bytes(original_bytes),
        },
        "original_protected_input_digest": release.sha256_json(original),
        "producer_intent_digest": "b" * 64,
        "invocation_root_locator": "invocations",
    }
    arguments.update(
        protected_path=protected,
        expected_producer_intent_digest="b" * 64,
        expected_invocation_id="fixture-recorded-role",
        expected_sequence=1,
    )
    signatures = []
    extra = []
    if mutation == "changed-operator":
        data["operator"]["actor_id"] = data["authorized_executor_id"] = "another-operator"
    elif mutation == "changed-backup":
        data["publisher"]["backup_actor_id"] = "another-backup"
    elif mutation == "changed-author":
        data["author_id"] = "another-author"
    elif mutation == "changed-context":
        data["release_context_digest"] = "f" * 64
    elif mutation == "changed-run":
        data["run_id"] = "another-run"
    elif mutation == "changed-policy":
        data["authority_policy_digest"] = "f" * 64
    elif mutation == "changed-validity":
        data["valid_until"] = "2030-01-02T00:00:00Z"
    elif mutation == "missing-field":
        del data["author_id"]
    elif mutation == "extra-field":
        data["native_delegation_verified"] = True
    elif mutation == "protected-payload-digest":
        data["original_protected_input_digest"] = original["payload_digest"]
    elif mutation == "different-protected-path":
        copy_path = tmp_path / "second-protected.json"
        copy_path.write_bytes(original_bytes)
        data["original_protected_input"]["path"] = copy_path.name
        extra.append(copy_path.name)
    elif mutation == "different-protected-bytes":
        data["original_protected_input"]["sha256"] = "f" * 64
    elif mutation == "copied-original-signatures":
        signatures = original["signatures"]
    elif mutation == "new-output-signature":
        # A new test signature also cannot replace the untouched original signature owner.
        provisional = release.make_record(
            "release-role-assignments",
            data,
            invocation_id="fixture-recorded-role",
            sequence=1,
            synthetic=True,
        )
        subject = release.signature_subject_digest(provisional)
        signatures = [
            {
                "actor_id": "fixture-operator",
                "provider": "test-fixture",
                "algorithm": "test-sha256-v1",
                "synthetic": True,
                "subject_digest": subject,
                "signature": release.sha256_json(
                    {"actor_id": "fixture-operator", "subject_digest": subject}
                ),
            }
        ]
    elif mutation == "different-producer-intent":
        data["producer_intent_digest"] = "f" * 64
    elif mutation == "different-invocation":
        arguments["expected_invocation_id"] = "different-producer"
    elif mutation == "different-sequence":
        arguments["expected_sequence"] = 2
    elif mutation == "boolean-sequence":
        arguments["expected_sequence"] = True
    elif mutation == "wrong-locator":
        data["invocation_root_locator"] = "other-invocations"
    elif mutation == "wrong-kind":
        data["kind"] = "independently-approved"
    elif mutation == "expired-use":
        arguments["use_interval"] = ("2020-01-02T00:00:00Z", "2020-01-02T00:00:00Z")
    record = release.make_record(
        "release-role-assignments",
        data,
        invocation_id="fixture-recorded-role",
        sequence=1,
        synthetic=mutation != "different-mode",
        signatures=signatures,
        status="FAIL" if mutation == "not-passing" else "PASS",
    )
    record_path = tmp_path / "roles.json"
    record_path.write_bytes(release.canonical_json(record))
    arguments["captured"] = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [(row[0], row[1]) for row in arguments["captured"].rows]
        + [(name, "prerequisite-original") for name in [record_path.name, *extra]],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    if mutation == "none":
        replay = release._release_recorded_role_byte_replay(record_path, **arguments)
        assert replay["recorded_assignments"] == record
        assert replay["record"] == original
        assert record["signatures"] == []
        # Actual independent delegation and original recorder/companion journals are absent.
        # This pure byte result is not a verified-derived context or live release authority.
        assert replay["assignment_policy_bytes"].startswith(b"explicit fixture policy;")
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_recorded_role_byte_replay(record_path, **arguments)
    assert protected.read_bytes() == original_bytes


def test_original_role_byte_replay_preserves_historical_signature_and_raw_provenance(
    tmp_path: Path,
) -> None:
    path, arguments = _original_role_byte_fixture(tmp_path)
    original = path.read_bytes()
    result = release._release_original_role_byte_replay(path, **arguments)
    assert result["record"] == json.loads(original)
    assert path.read_bytes() == original
    assert result["actors"]["authorized_executor_id"] == ("github", "fixture-operator")
    assert (
        result["assignment_policy_bytes"] == b"explicit fixture policy; no native delegation proof"
    )
    assert set(result["original_provenance"]) == {
        "operator",
        "non_author_reviewer",
        "infrastructure_owner",
        "publisher",
    }
    # The genuine original action was in 2020; replay must not move that use to today's clock.
    assert "authorized" not in result


@pytest.mark.parametrize(
    "mutation",
    [
        "reviewer-conflict",
        "backup-conflict",
        "payload-context",
        "payload-keyring",
        "payload-policy",
        "payload-run",
        "payload-milestone",
        "provenance-binding",
        "past-assignment",
        "future-assignment",
        "past-authorization",
        "future-authorization",
        "reversed-action",
        "missing-assurance",
        "unneeded-assurance",
        "extra-producer-field",
        "wrong-signer",
        "expected-policy",
        "expected-context",
        "wrong-context-path",
        "unsafe-provenance",
        "noninteger-bytes",
        "live-fixture",
        "subject-order",
        "subject-context-payload",
        "copied-signature",
        "missing-signature",
    ],
)
def test_original_role_byte_replay_rejects_wrong_original_binding(
    tmp_path: Path, mutation: str
) -> None:
    path, arguments = _original_role_byte_fixture(tmp_path, mutation)
    with pytest.raises(release.ReleaseControlError):
        release._release_original_role_byte_replay(path, **arguments)


def test_original_role_byte_replay_rechecks_captured_provenance(tmp_path: Path) -> None:
    path, arguments = _original_role_byte_fixture(tmp_path)
    (tmp_path / "publisher.bin").write_bytes(b"changed original provider bytes")
    with pytest.raises(release.ReleaseControlError, match="changed after capture"):
        release._release_original_role_byte_replay(path, **arguments)


def test_original_role_payload_extraction_preserves_legacy_envelope_owner() -> None:
    data = {
        "author_id": "fixture-author",
        "authorized_executor_id": "fixture-executor",
        "non_author_reviewer_id": "fixture-reviewer",
        "publisher_id": "fixture-publisher",
        "task_id": "MP2-007",
    }
    old = release.make_record(
        "release-role-assignments", data, invocation_id="fixture-legacy", sequence=1, synthetic=True
    )
    assert release.validate_role_assignments(old, live=False)["authorized_executor_id"] == (
        "test-fixture",
        "fixture-executor",
    )
    protected = release.make_record(
        "release-protected-input", data, invocation_id="fixture-legacy", sequence=1, synthetic=True
    )
    with pytest.raises(release.ReleaseControlError):
        release.validate_role_assignments(protected, live=False)


@pytest.mark.parametrize(
    "mode",
    [
        "original-bootstrap",
        "bootstrap-issue_id",
        "bootstrap-team_id",
        "bootstrap-project_id",
        "bootstrap-catalog-task",
        "preceding-line",
        "future-completion-policy",
    ],
)
def test_predecessor_policy_preserves_explicit_original_and_future_selection_requirements(
    mode: str,
) -> None:
    policy, arguments = _predecessor_policy_fixture()
    registry = json.loads(arguments["readiness_registry_raw"])
    context = registry["release_contexts"][0]
    subject = policy["expected_predecessor_subject"]
    if mode == "original-bootstrap" or mode.startswith("bootstrap-"):
        slot = next(row for row in registry["release_gate_slots"] if row["version"] == "v0.4")
        context["roadmap_catalog_task_id"] = slot["release_decision_task"]
        context["decision"] = copy.deepcopy(
            next(
                row["identity"]
                for row in registry["provider_issue_bindings"]
                if row["issue_identifier"] == slot["linear_release_decision_issue"]
            )
        )
        if mode == "bootstrap-catalog-task":
            next(
                row
                for row in registry["provider_issue_bindings"]
                if row["issue_identifier"] == slot["linear_release_decision_issue"]
            )["catalog_task_id"] = "MP2-019"
        elif mode.startswith("bootstrap-"):
            context["decision"][mode.removeprefix("bootstrap-")] = (
                "00000000-0000-0000-0000-000000000777"
            )
        context["target_policy"].update(
            initial_normalized_package_version="0.4.0", initial_release_tag="v0.4.0"
        )
        policy["lineage_mode"] = "ORIGINAL_BOOTSTRAP"
        subject.update(
            framework_milestone=None, normalized_package_version="0.3.0", release_tag="v0.3.0"
        )
        policy["expected_predecessor_decision"] = None
        policy["proof_requirements"] = {
            key: key == "original_genesis" for key in policy["proof_requirements"]
        }
    elif mode == "preceding-line":
        context["framework_milestone"] = "v0.5"
        context["target_policy"].update(
            initial_normalized_package_version="0.5.0", initial_release_tag="v0.5.0"
        )
    else:
        context["framework_milestone"] = "v1.0"
        context["target_policy"].update(
            initial_normalized_package_version="1.0.0", initial_release_tag="v1.0.0"
        )
        subject.update(
            framework_milestone="v0.9", normalized_package_version="0.9.0", release_tag="v0.9.0"
        )
        policy["proof_requirements"]["indexed_release_completion"] = True
    for row in subject["artifacts"]:
        row["filename"] = row["filename"].replace(
            "0.4.0.post0", subject["normalized_package_version"]
        )
    policy["target_policy"], policy["framework_milestone"] = (
        context["target_policy"],
        context["framework_milestone"],
    )
    arguments["readiness_registry_raw"] = release.canonical_json(registry)
    arguments["expected_readiness_digest"] = release.sha256_bytes(
        arguments["readiness_registry_raw"]
    )
    policy["selection_authority"]["context_policy_digest"] = release.sha256_json(context)
    policy["selection_authority"]["readiness_registry"].update(
        bytes=len(arguments["readiness_registry_raw"]),
        sha256=arguments["expected_readiness_digest"],
    )
    raw = release.canonical_json(policy)
    if mode.startswith("bootstrap-"):
        with pytest.raises(release.ReleaseControlError, match="actual initial framework context"):
            release._release_predecessor_policy_projection(
                raw, expected_digest=release.sha256_bytes(raw), **arguments
            )
        return
    result = release._release_predecessor_policy_projection(
        raw, expected_digest=release.sha256_bytes(raw), **arguments
    )
    assert result["proof_requirements"] == policy["proof_requirements"]
    if mode == "future-completion-policy":
        assert result["proof_requirements"]["indexed_release_completion"] is True
    # Only the raw policy is validated; no accepted predecessor or bootstrap/LKG is produced.


def _predecessor_policy_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    context, arguments = _context_policy_fixture()
    registry = json.loads(arguments["readiness_registry_raw"])
    selected = registry["release_contexts"][0]
    baseline = context["data"]["comparison_baseline"]
    historical_identity = {
        **selected["decision"],
        "issue_identifier": "MET-800",
        "issue_id": "00000000-0000-0000-0000-000000000800",
    }
    keys = {
        "original_genesis",
        "qualification",
        "exact_byte_reconciliation",
        "final_two_store_retention",
        "success_chain_ancestry_and_current_head",
        "cas_lkg_transition_and_current_state",
        "pointer_envelope_two_store_retention_and_index",
        "original_signed_closed_decision_and_durable_root",
        "complete_later_invalidation_conflict_recovery_walk",
        "indexed_release_completion",
    }
    policy = {
        "schema_version": "metriplane.release-predecessor-policy.v1",
        "owner": "MP2-007",
        "repository": "Miko997/metriplane",
        "readiness_context_id": selected["context_id"],
        "framework_milestone": "v0.4",
        "target_policy": selected["target_policy"],
        "lineage_mode": "RECONCILED_LKG",
        "expected_predecessor_subject": {
            key: baseline[key]
            for key in (
                "normalized_package_version",
                "release_tag",
                "source_commit",
                "source_tree",
                "tag_object",
                "artifacts",
            )
        },
        "selection_authority": {
            "readiness_registry": {
                "path": "policies/readiness.json",
                "bytes": len(arguments["readiness_registry_raw"]),
                "sha256": arguments["expected_readiness_digest"],
            },
            "context_row_pointer": "/release_contexts/0",
            "context_policy_digest": release.sha256_json(selected),
        },
        "proof_requirements": {
            key: key not in {"original_genesis", "indexed_release_completion"} for key in keys
        },
        "expected_predecessor_decision": {
            "identity": historical_identity,
            "authority": {
                "raw_registry": {
                    "path": "original/historical-policy.json",
                    "bytes": 100,
                    "sha256": "c" * 64,
                },
                "json_pointer": "/original_decision",
                "canonical_row_digest": "d" * 64,
            },
        },
    }
    policy["expected_predecessor_subject"]["framework_milestone"] = "v0.4"
    return policy, {
        key: arguments[key]
        for key in ("readiness_registry_raw", "expected_readiness_digest", "expected_context_id")
    }


def test_predecessor_policy_keeps_same_framework_history_separate_from_comparison_metadata() -> (
    None
):
    policy, arguments = _predecessor_policy_fixture()
    raw = release.canonical_json(policy)
    result = release._release_predecessor_policy_projection(
        raw, expected_digest=release.sha256_bytes(raw), **arguments
    )
    assert result["lineage_mode"] == "RECONCILED_LKG"
    assert result["proof_requirements"]["original_signed_closed_decision_and_durable_root"] is True
    assert result["expected_predecessor_decision"]["identity"]["issue_identifier"] == "MET-800"


@pytest.mark.parametrize(
    "mutation",
    [
        "bootstrap-patch",
        "wrong-context",
        "raw-alias",
        "context-row-alias",
        "wrong-row-digest",
        "reference-size-alias",
        "reference-digest",
        "target-post",
        "conflict-pair",
        "future-predecessor",
        "older-line-skip",
        "missing-decision",
        "wrong-owner",
        "wrong-lineage",
        "subject-list",
        "historical-path",
        "historical-pointer-escape",
        "historical-pointer-trailing-escape",
        "historical-current-uuid",
        "historical-current-identifier",
        "historical-current-complete",
        "requirement-alias",
    ],
)
def test_predecessor_policy_rejects_selection_and_authority_substitution(mutation: str) -> None:
    policy, arguments = _predecessor_policy_fixture()
    if mutation == "bootstrap-patch":
        policy["lineage_mode"] = "ORIGINAL_BOOTSTRAP"
        subject = policy["expected_predecessor_subject"]
        subject.update(
            framework_milestone=None, normalized_package_version="0.3.0", release_tag="v0.3.0"
        )
        for row in subject["artifacts"]:
            row["filename"] = row["filename"].replace("0.4.0.post0", "0.3.0")
        policy["expected_predecessor_decision"] = None
        policy["proof_requirements"] = {
            key: key == "original_genesis" for key in policy["proof_requirements"]
        }
    elif mutation == "wrong-context":
        arguments["expected_context_id"] = "different-context"
    elif mutation == "raw-alias":
        arguments["readiness_registry_raw"] += b" "
    elif mutation == "context-row-alias":
        policy["selection_authority"]["context_row_pointer"] = "/release_contexts/00"
    elif mutation == "wrong-row-digest":
        policy["selection_authority"]["context_policy_digest"] = "f" * 64
    elif mutation == "reference-size-alias":
        policy["selection_authority"]["readiness_registry"]["bytes"] = float(
            policy["selection_authority"]["readiness_registry"]["bytes"]
        )
    elif mutation == "reference-digest":
        policy["selection_authority"]["readiness_registry"]["sha256"] = "f" * 64
    elif mutation == "target-post":
        policy["target_policy"].update(
            initial_normalized_package_version="0.4.1.post1", initial_release_tag="v0.4.1.post1"
        )
    elif mutation == "conflict-pair":
        policy["target_policy"]["conflict_disposition"] = "DURABLE_BURN_THEN_SAME_MILESTONE_PATCH"
    elif mutation == "future-predecessor":
        subject = policy["expected_predecessor_subject"]
        subject.update(normalized_package_version="0.4.2", release_tag="v0.4.2")
        for row in subject["artifacts"]:
            row["filename"] = row["filename"].replace("0.4.0.post0", "0.4.2")
    elif mutation == "older-line-skip":
        policy["expected_predecessor_subject"]["framework_milestone"] = "v0.8"
    elif mutation == "missing-decision":
        policy["expected_predecessor_decision"] = None
    elif mutation == "wrong-owner":
        policy["owner"] = "some-other-task"
    elif mutation == "wrong-lineage":
        policy["lineage_mode"] = "NO_HISTORY_FOUND"
    elif mutation == "subject-list":
        policy["expected_predecessor_subject"]["framework_milestone"] = []
    elif mutation == "historical-path":
        policy["expected_predecessor_decision"]["authority"]["raw_registry"]["path"] = (
            "../different-policy"
        )
    elif mutation.startswith("historical-pointer-"):
        policy["expected_predecessor_decision"]["authority"]["json_pointer"] = (
            "/original~2decision" if mutation == "historical-pointer-escape" else "/original~"
        )
    elif mutation.startswith("historical-current-"):
        current = json.loads(arguments["readiness_registry_raw"])["release_contexts"][0]["decision"]
        identity = policy["expected_predecessor_decision"]["identity"]
        if mutation == "historical-current-complete":
            identity.update(current)
        else:
            key = "issue_id" if mutation.endswith("uuid") else "issue_identifier"
            identity[key] = current[key]
    else:
        policy["proof_requirements"]["qualification"] = 1
    raw = release.canonical_json(policy)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_policy_projection(
            raw, expected_digest=release.sha256_bytes(raw), **arguments
        )


@pytest.mark.parametrize("pointer", ["/original~0decision", "/original~1decision", "/"])
def test_predecessor_policy_preserves_valid_unresolved_historical_pointer(pointer: str) -> None:
    policy, arguments = _predecessor_policy_fixture()
    policy["expected_predecessor_decision"]["authority"]["json_pointer"] = pointer
    raw = release.canonical_json(policy)
    result = release._release_predecessor_policy_projection(
        raw, expected_digest=release.sha256_bytes(raw), **arguments
    )
    assert result["expected_predecessor_decision"]["authority"]["json_pointer"] == pointer


@pytest.mark.parametrize(
    "requirement",
    [
        "qualification",
        "exact_byte_reconciliation",
        "final_two_store_retention",
        "success_chain_ancestry_and_current_head",
        "cas_lkg_transition_and_current_state",
        "pointer_envelope_two_store_retention_and_index",
        "original_signed_closed_decision_and_durable_root",
        "complete_later_invalidation_conflict_recovery_walk",
    ],
)
def test_predecessor_policy_cannot_waive_any_original_history_requirement(requirement: str) -> None:
    policy, arguments = _predecessor_policy_fixture()
    policy["proof_requirements"][requirement] = False
    raw = release.canonical_json(policy)
    with pytest.raises(release.ReleaseControlError, match="weakens original proof"):
        release._release_predecessor_policy_projection(
            raw, expected_digest=release.sha256_bytes(raw), **arguments
        )


def _baseline_readback_fixture(
    tmp_path: Path, mutation: str = "none"
) -> tuple[Path, release._ReleaseCapturedFiles]:
    """Original-wire/byte replay fixture; tiny synthetic payloads are not package qualification."""
    context, _ = _context_policy_fixture()
    baseline = context["data"]["comparison_baseline"]
    tag = {
        "data": {
            "repository": {
                "nameWithOwner": "Miko997/metriplane",
                "ref": {
                    "name": baseline["release_tag"],
                    "prefix": "refs/tags/",
                    "target": {
                        "__typename": "Tag",
                        "oid": baseline["tag_object"],
                        "name": baseline["release_tag"],
                        "target": {
                            "__typename": "Commit",
                            "oid": baseline["source_commit"],
                            "tree": {"oid": baseline["source_tree"]},
                        },
                    },
                },
            }
        }
    }
    published = {
        "id": 1,
        "url": "https://api.github.com/repos/Miko997/metriplane/releases/1",
        "html_url": "https://github.com/Miko997/metriplane/releases/tag/" + baseline["release_tag"],
        "tag_name": baseline["release_tag"],
        "draft": False,
        "prerelease": False,
        "published_at": "2026-01-01T00:00:00Z",
        "assets": [],
    }
    files = {}
    for row in baseline["artifacts"]:
        raw = ("Synthetic byte subject " + row["kind"]).encode()
        row["bytes"], row["sha256"] = len(raw), release.sha256_bytes(raw)
        row["readback"] = {
            "path": "artifacts/" + row["kind"],
            "bytes": len(raw),
            "sha256": release.sha256_bytes(raw),
        }
        files[row["readback"]["path"]] = raw
        published["assets"].append(
            {
                "name": row["filename"],
                "state": "uploaded",
                "size": len(raw),
                "digest": "sha256:" + release.sha256_bytes(raw),
                "browser_download_url": "https://github.com/Miko997/metriplane/releases/download/"
                + baseline["release_tag"]
                + "/"
                + row["filename"],
            }
        )
    ref = tag["data"]["repository"]["ref"]
    if mutation == "wrong-repository":
        tag["data"]["repository"]["nameWithOwner"] = "unrelated/metriplane"
    elif mutation == "branch-ref":
        ref["prefix"] = "refs/heads/"
    elif mutation == "wrong-tag":
        ref["name"] = "v0.4.0.post1"
    elif mutation == "lightweight-tag":
        ref["target"]["__typename"] = "Commit"
    elif mutation == "tag-oid":
        ref["target"]["oid"] = "f" * 40
    elif mutation == "commit-oid":
        ref["target"]["target"]["oid"] = "f" * 40
    elif mutation == "tree-oid":
        ref["target"]["target"]["tree"]["oid"] = "f" * 40
    elif mutation == "graphql-error":
        tag["errors"] = [{"message": "partial result"}]
    elif mutation == "missing-tag":
        tag["data"]["repository"]["ref"] = None
    elif mutation == "draft":
        published["draft"] = True
    elif mutation == "prerelease":
        published["prerelease"] = True
    elif mutation == "release-repository":
        published["url"] = "https://api.github.com/repos/other/repository/releases/1"
    elif mutation == "release-tag":
        published["tag_name"] = "v0.4.0.post1"
    elif mutation == "missing-distribution":
        published["assets"].pop()
    elif mutation == "duplicate-distribution":
        published["assets"].append(published["assets"][0])
    elif mutation == "extra-distribution":
        published["assets"].append(
            {**published["assets"][0], "name": "metriplane-0.4.0.post0-cp313-none-any.whl"}
        )
    elif mutation == "asset-digest":
        published["assets"][0]["digest"] = "sha256:" + "f" * 64
    elif mutation == "asset-size-alias":
        published["assets"][0]["size"] = float(published["assets"][0]["size"])
    elif mutation == "asset-state":
        published["assets"][0]["state"] = "new"
    elif mutation == "asset-url":
        published["assets"][0]["browser_download_url"] += "?other=true"
    elif mutation == "payload-tamper":
        files[baseline["artifacts"][0]["readback"]["path"]] += b"changed"
    for key, value in [("tag_observation", tag), ("release_observation", published)]:
        raw = release.canonical_json(value)
        files[baseline[key]["path"]] = raw
        baseline[key].update(bytes=len(raw), sha256=release.sha256_bytes(raw))
    context["data"]["context_digest"] = release.sha256_json(
        {key: value for key, value in context["data"].items() if key != "context_digest"}
    )
    context = release.make_record(
        "release-context",
        context["data"],
        invocation_id="synthetic-context",
        sequence=1,
        synthetic=True,
    )
    root = tmp_path / "comparison-bundle"
    root.mkdir()
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
    path = root / "context.json"
    path.write_bytes(release.canonical_json(context))
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [
            (
                name,
                "distribution-original"
                if name in {row["readback"]["path"] for row in baseline["artifacts"]}
                else "comparison-original",
            )
            for name in files
        ]
        + [(path.name, "release-context")],
        allowed_kinds=frozenset(
            {"comparison-original", "distribution-original", "release-context"}
        ),
        forbidden=[],
    )
    return path, captured


def test_baseline_readback_replays_annotated_tag_commit_tree_and_exact_original_payloads(
    tmp_path: Path,
) -> None:
    path, captured = _baseline_readback_fixture(tmp_path)
    result = release._release_comparison_baseline_readback(path, captured=captured)
    assert result["source_commit"] == "1" * 40
    assert result["source_tree"] == "2" * 40
    assert result["tag_object"] == "3" * 40
    assert {row["kind"] for row in result["artifacts"]} == {"wheel", "sdist"}


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-repository",
        "branch-ref",
        "wrong-tag",
        "lightweight-tag",
        "tag-oid",
        "commit-oid",
        "tree-oid",
        "graphql-error",
        "missing-tag",
        "draft",
        "prerelease",
        "release-repository",
        "release-tag",
        "missing-distribution",
        "duplicate-distribution",
        "extra-distribution",
        "asset-digest",
        "asset-size-alias",
        "asset-state",
        "asset-url",
        "payload-tamper",
    ],
)
def test_baseline_readback_rejects_fabricated_provider_bindings_or_different_bytes(
    tmp_path: Path, mutation: str
) -> None:
    path, captured = _baseline_readback_fixture(tmp_path, mutation)
    with pytest.raises(release.ReleaseControlError):
        release._release_comparison_baseline_readback(path, captured=captured)


def _context_policy_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure policy fixture; original provider/package/authority replay is tested separately."""
    linear_data, _, original, _ = _linear_wire_fixture()
    registry = json.loads(original["readiness_registry_raw"])
    selected = registry["release_contexts"][0]
    selected["predecessor_requirement"] = (
        "VALIDATE_ORIGINAL_GENESIS_OR_RECONCILED_LKG_GRAPH_UNDER_BOUND_POLICY"
    )
    selected["target_policy"] = {
        "resolution_mode": "owner_approved_exact_target",
        "conflict_disposition": "BLOCKED_REQUIRES_NEW_OWNER_RELEASE_IDENTITY",
        "initial_normalized_package_version": "0.4.1",
        "initial_release_tag": "v0.4.1",
    }
    selected["comparison_baseline_policy"] = {
        "normalized_package_version": "0.4.0.post0",
        "release_tag": "v0.4.0.post0",
        "source_commit": "1" * 40,
        "source_tree": "2" * 40,
        "wheel_sha256": "a" * 64,
        "sdist_sha256": "b" * 64,
    }
    registry_raw = release.canonical_json(registry)
    predecessor_raw = b'{"synthetic_policy_subject":"not an original LKG proof"}'
    linear_data["readiness_registry_digest"] = release.sha256_bytes(registry_raw)
    linear_data["snapshot_digest"] = release.sha256_json(linear_data)
    linear = release.make_record(
        "linear-release-snapshot",
        linear_data,
        invocation_id="synthetic-context-input",
        sequence=1,
        synthetic=True,
    )
    artifacts = [
        {
            "kind": kind,
            "filename": "metriplane-0.4.0.post0" + suffix,
            "bytes": 123,
            "sha256": digest,
            "readback": {"path": "artifacts/" + kind, "bytes": 123, "sha256": digest},
        }
        for kind, suffix, digest in [
            ("wheel", "-py3-none-any.whl", "a" * 64),
            ("sdist", ".tar.gz", "b" * 64),
        ]
    ]
    baseline = {
        key: selected["comparison_baseline_policy"][key]
        for key in ("normalized_package_version", "release_tag", "source_commit", "source_tree")
    }
    baseline.update(
        artifacts=artifacts,
        tag_object="3" * 40,
        tag_observation={"path": "provider/tag.json", "bytes": 1, "sha256": "c" * 64},
        release_observation={"path": "provider/release.json", "bytes": 1, "sha256": "d" * 64},
    )
    data = {
        key: selected[key]
        for key in (
            "context_id",
            "decision",
            "direct_gate_issues",
            "framework_milestone",
            "predecessor_requirement",
            "provider_milestone",
            "roadmap_catalog_task_id",
            "target_policy",
        )
    }
    data.update(
        comparison_baseline=baseline,
        context_policy_digest=release.sha256_json(selected),
        cumulative_bom_snapshot_digest=linear_data["required_bom_snapshot_digest"],
        linear_snapshot_digest=release.sha256_json(linear),
        predecessor_policy_digest=release.sha256_bytes(predecessor_raw),
        readiness_registry_digest=release.sha256_bytes(registry_raw),
    )
    data["context_digest"] = release.sha256_json(data)
    context = release.make_record(
        "release-context", data, invocation_id="synthetic-context", sequence=1, synthetic=True
    )
    return context, {
        "readiness_registry_raw": registry_raw,
        "expected_readiness_digest": release.sha256_bytes(registry_raw),
        "predecessor_policy_raw": predecessor_raw,
        "expected_predecessor_policy_digest": release.sha256_bytes(predecessor_raw),
        "expected_context_id": selected["context_id"],
        "linear_snapshot": linear,
    }


def _reseal_context_policy_fixture(
    context: dict[str, Any], arguments: dict[str, Any], *, amend_selected_policy: bool = False
) -> dict[str, Any]:
    data = context["data"]
    if amend_selected_policy:
        registry = json.loads(arguments["readiness_registry_raw"])
        selected = registry["release_contexts"][0]
        for key in (
            "decision",
            "direct_gate_issues",
            "framework_milestone",
            "predecessor_requirement",
            "provider_milestone",
            "roadmap_catalog_task_id",
            "target_policy",
        ):
            selected[key] = data[key]
        for key in ("normalized_package_version", "release_tag", "source_commit", "source_tree"):
            selected["comparison_baseline_policy"][key] = data["comparison_baseline"][key]
        arguments["readiness_registry_raw"] = release.canonical_json(registry)
        arguments["expected_readiness_digest"] = release.sha256_bytes(
            arguments["readiness_registry_raw"]
        )
        data["readiness_registry_digest"] = arguments["expected_readiness_digest"]
        data["context_policy_digest"] = release.sha256_json(selected)
        frozen = arguments["linear_snapshot"]["data"]
        frozen["readiness_registry_digest"] = data["readiness_registry_digest"]
        frozen["snapshot_digest"] = release.sha256_json(
            {key: value for key, value in frozen.items() if key != "snapshot_digest"}
        )
        arguments["linear_snapshot"] = release.make_record(
            "linear-release-snapshot",
            frozen,
            invocation_id="synthetic-context-input",
            sequence=1,
            synthetic=True,
        )
        data["linear_snapshot_digest"] = release.sha256_json(arguments["linear_snapshot"])
    data["context_digest"] = release.sha256_json(
        {key: value for key, value in data.items() if key != "context_digest"}
    )
    return release.make_record(
        "release-context", data, invocation_id="synthetic-context", sequence=1, synthetic=True
    )


def test_context_policy_preserves_exact_target_and_historical_comparison_without_lkg_credit() -> (
    None
):
    context, arguments = _context_policy_fixture()
    result = release._release_context_policy_projection(context, **arguments)
    assert result["target_policy"]["initial_normalized_package_version"] == "0.4.1"
    assert result["comparison_baseline"]["normalized_package_version"] == "0.4.0.post0"
    assert (
        result["predecessor_requirement"]
        == "VALIDATE_ORIGINAL_GENESIS_OR_RECONCILED_LKG_GRAPH_UNDER_BOUND_POLICY"
    )


def test_context_policy_generic_patch_does_not_treat_initial_seed_as_future_resolved_target() -> (
    None
):
    context, arguments = _context_policy_fixture()
    context["data"]["target_policy"].update(
        resolution_mode="next_unused_same_milestone_patch",
        conflict_disposition="DURABLE_BURN_THEN_SAME_MILESTONE_PATCH",
        initial_normalized_package_version="0.4.0",
        initial_release_tag="v0.4.0",
    )
    context = _reseal_context_policy_fixture(context, arguments, amend_selected_policy=True)
    result = release._release_context_policy_projection(context, **arguments)
    assert result["target_policy"]["initial_normalized_package_version"] == "0.4.0"
    # Final selected target versus this baseline is checked after actual resolution.
    assert result["comparison_baseline"]["normalized_package_version"] == "0.4.0.post0"


@pytest.mark.parametrize(
    "mutation",
    [
        "context-id",
        "raw-readiness",
        "raw-predecessor",
        "policy-digest",
        "snapshot-digest",
        "bom-ids-digest",
        "synthetic-mode",
        "duplicate-gate",
        "target-post",
        "conflict-pair",
        "target-milestone",
        "baseline-future",
        "baseline-leading-zero",
        "artifact-missing",
        "artifact-duplicate",
        "artifact-path",
        "artifact-version",
        "artifact-readback-digest",
        "artifact-bytes-alias",
        "tag-oid",
        "observation-path",
        "observation-zero",
        "future-cycle-field",
    ],
)
def test_context_policy_rejects_drift_aliases_and_incomplete_comparison(mutation: str) -> None:
    context, arguments = _context_policy_fixture()
    data, amend = context["data"], False
    if mutation == "context-id":
        arguments["expected_context_id"] = "unbound-context"
    elif mutation in {"raw-readiness", "raw-predecessor"}:
        arguments[
            "readiness_registry_raw" if mutation == "raw-readiness" else "predecessor_policy_raw"
        ] += b" "
    elif mutation == "policy-digest":
        data["context_policy_digest"] = "f" * 64
    elif mutation == "snapshot-digest":
        data["linear_snapshot_digest"] = arguments["linear_snapshot"]["payload_digest"]
    elif mutation == "bom-ids-digest":
        data["cumulative_bom_snapshot_digest"] = release.sha256_json(
            arguments["linear_snapshot"]["data"]["required_bom_ids"]
        )
    elif mutation == "synthetic-mode":
        arguments["linear_snapshot"] = release.make_record(
            "linear-release-snapshot",
            arguments["linear_snapshot"]["data"],
            invocation_id="synthetic-context-input",
            sequence=1,
            synthetic=False,
        )
        data["linear_snapshot_digest"] = release.sha256_json(arguments["linear_snapshot"])
    elif mutation == "duplicate-gate":
        data["direct_gate_issues"].append(data["direct_gate_issues"][0])
        amend = True
    elif mutation in {"target-post", "conflict-pair", "target-milestone"}:
        target = data["target_policy"]
        amend = True
        if mutation == "target-post":
            target.update(
                initial_normalized_package_version="0.4.1.post1", initial_release_tag="v0.4.1.post1"
            )
        elif mutation == "conflict-pair":
            target["conflict_disposition"] = "DURABLE_BURN_THEN_SAME_MILESTONE_PATCH"
        else:
            target.update(initial_normalized_package_version="0.5.1", initial_release_tag="v0.5.1")
    elif mutation in {"baseline-future", "baseline-leading-zero"}:
        version = "0.4.2" if mutation == "baseline-future" else "0.4.00.post0"
        data["comparison_baseline"].update(
            normalized_package_version=version, release_tag="v" + version
        )
        amend = True
    elif mutation in {"artifact-missing", "artifact-duplicate"}:
        data["comparison_baseline"]["artifacts"] = data["comparison_baseline"]["artifacts"][:1]
        if mutation == "artifact-duplicate":
            data["comparison_baseline"]["artifacts"] *= 2
    elif mutation.startswith("artifact-"):
        artifact = data["comparison_baseline"]["artifacts"][0]
        if mutation == "artifact-path":
            artifact["filename"] = "../" + artifact["filename"]
        elif mutation == "artifact-version":
            artifact["filename"] = "metriplane-0.4.9-py3-none-any.whl"
        elif mutation == "artifact-readback-digest":
            artifact["readback"]["sha256"] = "f" * 64
        else:
            artifact["readback"]["bytes"] = 123.0
    elif mutation == "tag-oid":
        data["comparison_baseline"]["tag_object"] = "a" * 39 + "\n"
    elif mutation.startswith("observation-"):
        ref = data["comparison_baseline"]["tag_observation"]
        if mutation == "observation-path":
            ref["path"] = "../escape"
        else:
            ref["bytes"] = 0
    else:
        data["target_resolution_digest"] = "f" * 64
    context = _reseal_context_policy_fixture(context, arguments, amend_selected_policy=amend)
    with pytest.raises(release.ReleaseControlError):
        release._release_context_policy_projection(context, **arguments)


@pytest.mark.parametrize("mutation", ["extended-wrapper", "one-refreshed-observation"])
def test_linear_original_wire_cannot_refresh_old_observations_with_wrapper_time(
    tmp_path: Path, mutation: str
) -> None:
    data, payloads, kwargs, _ = _linear_wire_fixture()
    data["capture_completed_at"] = "2026-01-04T00:02:00Z"
    kwargs["observed_at"] = "2026-01-04T00:03:00Z"
    if mutation == "one-refreshed-observation":
        member = payloads["synthetic-r2-detail-SYN-1"]
        member["observation"]["started_at"] = member["observation"]["completed_at"] = (
            "2026-01-04T00:02:00Z"
        )
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    with pytest.raises(release.ReleaseControlError, match="second-round observation is stale"):
        release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)


def test_linear_original_wire_reports_a_fully_captured_unbound_extra_project_task(
    tmp_path: Path,
) -> None:
    from uuid import UUID

    data, payloads, kwargs, _ = _linear_wire_fixture()
    new_id = str(UUID(int=96))
    for number in (1, 2):
        member = copy.deepcopy(payloads[f"synthetic-r{number}-detail-SYN-2"])
        member["observation"]["id"] = f"synthetic-r{number}-detail-SYN-96"
        member["observation"]["arguments"]["id"] = "SYN-96"
        member["payload"].update(id="SYN-96", uuid=new_id, status="Backlog", statusType="backlog")
        payloads[member["observation"]["id"]] = member
        page = next(
            row
            for row in payloads.values()
            if row["observation"]["round"] == number
            and row["observation"]["tool"].endswith("list_issues")
            and row["payload"]["hasNextPage"]
        )
        page["payload"]["issues"].append(
            {key: member["payload"][key] for key in release._RELEASE_LINEAR_INDEX_FIELDS}
        )
        states = next(
            row
            for row in payloads.values()
            if row["observation"]["round"] == number
            and row["observation"]["tool"].endswith("list_issue_statuses")
        )
        # Separate round lists, so identical logical dictionary additions are not aliases.
        states["payload"] = [
            *states["payload"],
            {"id": str(UUID(int=20004)), "name": "Backlog", "type": "backlog"},
        ]
    args = {
        "root_project_ids": frozenset(data["coverage"]["root_project_ids"]),
        "root_issue_ids": frozenset(data["coverage"]["blocking_closure_issue_ids"]),
    }
    rounds = [
        release._release_linear_round_projection(payloads, round_number=number, **args)
        for number in (1, 2)
    ]
    assert rounds[0]["semantic"] == rounds[1]["semantic"]
    assert len(rounds[1]["issues"]) == 96
    for key in ("issues", "team_statuses", "project_milestones"):
        data[key] = rounds[1][key]
    data["project_scans"] = rounds[0]["project_scans"] + rounds[1]["project_scans"]
    data["coverage"]["blocking_closure_issue_ids"] = rounds[1]["blocking_closure_issue_ids"]
    data["stabilization"]["round_1_projection_digest"] = rounds[0]["projection_digest"]
    data["stabilization"]["round_2_projection_digest"] = rounds[1]["projection_digest"]
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    with pytest.raises(release.ReleaseControlError, match="explicit policy bindings: SYN-96"):
        release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)


def test_linear_original_wire_boundary_lookups_do_not_recursively_capture_unrelated_graph() -> None:
    from uuid import UUID

    data, payloads, _, _ = _linear_wire_fixture()
    external_project = str(UUID(int=40001))
    subject = payloads["synthetic-r2-detail-SYN-1"]
    subject["payload"]["relations"]["relatedTo"] = [{"id": "SYN-96"}]
    for number in (96, 97):
        member = copy.deepcopy(payloads["synthetic-r2-detail-SYN-2"])
        member["observation"]["id"] = f"synthetic-r2-detail-SYN-{number}"
        member["observation"]["arguments"]["id"] = f"SYN-{number}"
        member["payload"].update(
            id=f"SYN-{number}", uuid=str(UUID(int=number)), projectId=external_project
        )
        member["payload"]["relations"]["relatedTo"] = [{"id": f"SYN-{number + 1}"}]
        payloads[member["observation"]["id"]] = member
    dictionary = copy.deepcopy(
        next(
            member
            for member in payloads.values()
            if member["observation"]["round"] == 2
            and member["observation"]["tool"].endswith("list_milestones")
        )
    )
    dictionary["observation"]["id"] = "synthetic-external-milestones"
    dictionary["observation"]["arguments"]["project"] = external_project
    dictionary["payload"] = {"milestones": []}
    payloads[dictionary["observation"]["id"]] = dictionary
    arguments = {
        "round_number": 2,
        "root_project_ids": frozenset(data["coverage"]["root_project_ids"]),
        "root_issue_ids": frozenset(data["coverage"]["blocking_closure_issue_ids"]),
    }
    result = release._release_linear_round_projection(payloads, **arguments)
    assert len(result["issues"]) == 96
    assert len(result["blocking_closure_issue_ids"]) == 95
    assert result["relation_endpoint_issue_ids"] == [str(UUID(int=96))]
    assert [
        row["issue_identifier"] for row in result["semantic"]["boundary_identity_readbacks"]
    ] == ["SYN-97"]
    assert "SYN-98" not in {row["identity"]["issue_identifier"] for row in result["issues"]}
    registry, bom_arguments = _linear_bom_fixture()
    boundary_row = next(
        row for row in result["issues"] if row["identity"]["issue_identifier"] == "SYN-96"
    )
    binding = {
        **registry["provider_issue_bindings"][0],
        "identity": boundary_row["identity"],
        "issue_identifier": "SYN-96",
        "catalog_task_id": None,
        "expected_milestone": None,
    }
    registry["provider_issue_bindings"].append(binding)
    bom_arguments["issues"] = result["issues"]
    bom = release._release_linear_bom_projection(registry, **bom_arguments)
    assert "SYN-96" not in bom["required_bom_ids"]
    assert "SYN-96" in bom["unresolved_bindings"]
    payloads["synthetic-r2-detail-SYN-97"]["payload"]["projectId"] = data["coverage"][
        "root_project_ids"
    ][0]
    with pytest.raises(
        release.ReleaseControlError, match="absent from its governed full project index"
    ):
        release._release_linear_round_projection(payloads, **arguments)
    payloads["synthetic-r2-detail-SYN-97"]["payload"]["projectId"] = external_project
    del payloads["synthetic-r2-detail-SYN-97"]
    with pytest.raises(release.ReleaseControlError, match="endpoint identity"):
        release._release_linear_round_projection(payloads, **arguments)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-response",
        "nonfinite-inner",
        "duplicate-inner",
        "numeric-round",
        "wrong-round-type",
        "numeric-limit",
        "wrong-content",
        "extra-content",
        "unsafe-response",
    ],
)
def test_linear_original_wire_transport_faults(tmp_path: Path, mutation: str) -> None:
    data, payloads, _, _ = _linear_wire_fixture()
    first = next(iter(payloads.values()))
    if mutation in {"nonfinite-inner", "duplicate-inner"}:
        inner = '{"x":NaN}' if mutation == "nonfinite-inner" else '{"x":1,"x":2}'
        first["raw_override"] = release.canonical_json(
            {"content": [{"type": "text", "text": inner}], "isError": False}
        )
    elif mutation in {"numeric-round", "wrong-round-type"}:
        first["observation"]["round"] = 1.0 if mutation == "numeric-round" else True
    elif mutation == "numeric-limit":
        next(
            member
            for member in payloads.values()
            if member["observation"]["tool"].endswith("list_issues")
        )["observation"]["arguments"]["limit"] = 250.0
    elif mutation in {"wrong-content", "extra-content"}:
        blocks = (
            [{"type": "image", "text": "{}"}]
            if mutation == "wrong-content"
            else [{"type": "text", "text": "{}"}] * 2
        )
        first["raw_override"] = release.canonical_json({"content": blocks, "isError": False})
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    if mutation in {"duplicate-response", "unsafe-response"}:
        record = json.loads(snapshot.read_bytes())
        rows = record["data"]["raw_observations"]
        if mutation == "duplicate-response":
            rows[1]["response"] = rows[0]["response"]
        else:
            rows[0]["response"]["path"] = "../escape.json"
        body = record["data"]
        body["snapshot_digest"] = release.sha256_json(
            {key: value for key, value in body.items() if key != "snapshot_digest"}
        )
        snapshot.write_bytes(
            release.canonical_json(
                release.make_record(
                    "linear-release-snapshot",
                    body,
                    invocation_id="synthetic-wire",
                    sequence=1,
                    synthetic=True,
                )
            )
        )
        captured = release._ReleaseCapturedFiles.capture(
            captured.root,
            [(path.name, "prerequisite-original") for path in captured.root.iterdir()],
            allowed_kinds=frozenset({"prerequisite-original"}),
            forbidden=[],
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_observation_payloads(snapshot, captured=captured)


def test_linear_original_wire_cannot_substitute_a_detached_readiness_policy(tmp_path: Path) -> None:
    data, payloads, kwargs, _ = _linear_wire_fixture()
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    kwargs["readiness_registry_raw"] += b" "
    with pytest.raises(release.ReleaseControlError, match="raw readiness policy"):
        release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)


def _linear_wire_fixture(
    *, catalog_override: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Synthetic full wire capture, independently assembled from the 95 known fixture rows."""
    registry, arguments, lifecycle = _linear_lifecycle_fixture()
    packet = json.loads(arguments["original_packet"])
    orders = []
    by_identifier = {row["identity"]["issue_identifier"]: row for row in arguments["issues"]}
    for task in packet["task_registry"]:
        task["linear_milestone_id"] = "synthetic-original-planning-milestone"
        # These independent synthetic catalog work orders declare no blockers.
        # The fixture's noncatalog current-decision edge is separately supplied.
        orders.append(
            {
                "task_id": task["task"],
                **{
                    key: task[key]
                    for key in (
                        "linear_issue",
                        "role",
                        "first_required_release",
                        "linear_milestone_id",
                    )
                },
                "authoritative_blocked_by": [],
            }
        )
        by_identifier[task["linear_issue"]]["description"] = (
            "<!-- METRIPLANE_MP2_DEPENDENCIES_V1\n"
            f"Task: {task['task']}\nAuthoritative blocked by: []\n-->\n"
        )
    original_packet = release.canonical_json(packet)
    arguments["original_packet"] = original_packet
    arguments["expected_packet_digest"] = release.sha256_bytes(original_packet)
    registry["task_catalog"] = packet["task_registry"]
    registry["catalog_binding"]["source"].update(
        bytes=len(original_packet), sha256=release.sha256_bytes(original_packet)
    )
    registry["catalog_binding"]["task_registry_sha256"] = release.sha256_json(
        packet["task_registry"]
    )
    original_work_orders = release.canonical_json({"tasks": orders})
    if catalog_override is not None:
        assert catalog_override in {"caller", "marker"}
        dependent, blocker = by_identifier["SYN-8"], by_identifier["SYN-4"]
        dependent["blocked_by"].append(
            {key: blocker["identity"][key] for key in ("issue_id", "issue_identifier")}
        )
        blocker["blocks"].append(
            {key: dependent["identity"][key] for key in ("issue_id", "issue_identifier")}
        )
        arguments["declared_dependencies"]["SYN-8"] = ["SYN-4"]
        if catalog_override == "marker":
            dependent["description"] = dependent["description"].replace("[]", "[MP2-003]")
    issues = copy.deepcopy(arguments["issues"])
    projects = sorted({row["identity"]["project_id"] for row in issues})
    registry["linear_capture_policy"] = {
        "root_project_ids": projects,
        "follow_cross_project_blockers": True,
        "include_all_catalog_tasks": True,
        "include_all_roadmap_gate_slots": True,
        "include_archived": True,
        "nonblocking_relation_disposition": "RETAIN_ENDPOINTS_NOT_AUTOMATIC_BOM",
        "provider_snapshot_atomicity": "not_claimed",
        "require_reciprocal_blocking_relations": True,
        "stable_complete_rounds": 2,
        "unknown_dependency_disposition": "BLOCKED_REQUIRES_EXPLICIT_POLICY_BINDING",
        "provider_transport_binding": {
            "path": "synthetic-unbound-transport",
            "bytes": 1,
            "sha256": release.sha256_bytes(b"x"),
        },
    }
    registry_raw = release.canonical_json(registry)
    context = registry["release_contexts"][0]
    payloads: dict[str, Any] = {}
    scans, teams, milestones = [], [], []
    for round_number in (1, 2):
        clock = f"2026-01-03T00:0{round_number}:00Z"

        def observe(kind: str, arguments: dict[str, Any], payload: object, label: str) -> str:
            observation_id = f"synthetic-r{round_number}-{label}"
            payloads[observation_id] = {
                "observation": {
                    "id": observation_id,
                    "round": round_number,
                    "tool": "mcp__codex_apps__linear_" + kind,
                    "arguments": arguments,
                    "started_at": clock,
                    "completed_at": clock,
                    "response": {},
                    "extracted_json_pointer": "/content/0/text",
                    "capture_status": "SUCCESS",
                    "payload_encoding": "json_text",
                },
                "payload": payload,
            }
            return observation_id

        wires = []
        for row in issues:
            identity = row["identity"]
            milestone = row["project_milestone"]
            wire = {
                "id": identity["issue_identifier"],
                "uuid": identity["issue_id"],
                "projectId": identity["project_id"],
                "teamId": identity["team_id"],
                "title": row["title"],
                "description": row["description"],
                "status": row["state"]["name"],
                "statusType": row["state"]["type"],
                "projectMilestone": None
                if milestone is None
                else {"id": milestone["id"], "name": milestone["name"]},
                "parentId": None,
                "assigneeId": None,
            }
            for native, normalized in [
                ("createdAt", "created_at"),
                ("updatedAt", "updated_at"),
                ("archivedAt", "archived_at"),
                ("completedAt", "completed_at"),
                ("startedAt", "started_at"),
                ("canceledAt", "canceled_at"),
            ]:
                wire[native] = row[normalized]
            wires.append(wire)
            detail = {
                **wire,
                "relations": {
                    native: [
                        {"id": edge["issue_identifier"], "title": "Fixture endpoint display label"}
                        for edge in row[normalized]
                    ]
                    for native, normalized in [
                        ("blocks", "blocks"),
                        ("blockedBy", "blocked_by"),
                        ("relatedTo", "related_to"),
                    ]
                },
            }
            detail["relations"]["duplicateOf"] = None
            row["detail_observation_id"] = observe(
                "get_issue",
                {"id": wire["id"], "includeRelations": True},
                detail,
                "detail-" + wire["id"],
            )
            row["index_observation_ids"] = []
        for project in projects:
            rows = [wire for wire in wires if wire["projectId"] == project]
            page_ids, cursor = [], None
            for offset in range(0, len(rows), 47):
                page = rows[offset : offset + 47]
                request = {
                    "project": project,
                    "includeArchived": True,
                    "limit": 250,
                    "orderBy": "createdAt",
                    "fields": list(release._RELEASE_LINEAR_INDEX_FIELDS),
                }
                if cursor is not None:
                    request["cursor"] = cursor
                more = offset + 47 < len(rows)
                body = {"issues": page, "hasNextPage": more}
                cursor = page[-1]["uuid"]
                if more:
                    body["cursor"] = cursor
                observation_id = observe(
                    "list_issues", request, body, f"project-{project}-{offset}"
                )
                page_ids.append(observation_id)
                for row in issues:
                    if row["identity"]["issue_id"] in {wire["uuid"] for wire in page}:
                        row["index_observation_ids"] = [observation_id]
            scans.append(
                {
                    "project_id": project,
                    "round": round_number,
                    "page_observation_ids": page_ids,
                    "issue_ids": sorted(row["uuid"] for row in rows),
                    "terminal_has_next_page": False,
                }
            )
            values = (
                [context["provider_milestone"]]
                if context["provider_milestone"]["project_id"] == project
                else []
            )
            observation_id = observe(
                "list_milestones",
                {"project": project},
                {
                    "milestones": [
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "description": "Synthetic dictionary extra field",
                        }
                        for row in values
                    ]
                },
                "milestones-" + project,
            )
            if round_number == 2:
                milestones.append(
                    {"project_id": project, "observation_id": observation_id, "milestones": values}
                )
        for row in lifecycle["team_statuses"]:
            observation_id = observe(
                "list_issue_statuses",
                {"team": row["team_id"]},
                row["states"],
                "states-" + row["team_id"],
            )
            if round_number == 2:
                teams.append({**row, "observation_id": observation_id})
    arguments["issues"] = issues
    projection = release._release_linear_bom_projection(registry, **arguments)
    catalogue = sorted(
        row["identity"]["issue_id"]
        for row in issues
        if int(row["identity"]["issue_identifier"].split("-")[1]) <= 93
    )
    all_ids = sorted(row["identity"]["issue_id"] for row in issues)
    direct_ids = sorted(row["issue_id"] for row in context["direct_gate_issues"])
    semantic = {
        "project_scans": [
            {"project_id": row["project_id"], "issue_ids": row["issue_ids"]}
            for row in scans
            if row["round"] == 2
        ],
        "issues": [
            {
                key: value
                for key, value in row.items()
                if key not in {"detail_observation_id", "index_observation_ids"}
            }
            for row in issues
        ],
        "team_statuses": [
            {key: value for key, value in row.items() if key != "observation_id"} for row in teams
        ],
        "project_milestones": [
            {key: value for key, value in row.items() if key != "observation_id"}
            for row in milestones
        ],
        "blocking_closure_issue_ids": all_ids,
        "relation_endpoint_issue_ids": [],
        "boundary_identity_readbacks": [],
    }
    data = {
        "snapshot_contract": "full-project-plus-cross-project-dependency-closure.v1",
        "tool": "capture_linear_release_snapshot.py",
        "readiness_registry_digest": release.sha256_bytes(registry_raw),
        "task_state_policy_digest": lifecycle["expected_task_state_policy_digest"],
        "catalog_projection_digest": projection["catalog_projection_digest"],
        "context_policy_id": arguments["context_id"],
        "framework_milestone": "v0.4",
        "task_id": "SYN-94",
        "decision_issue_id": context["decision"]["issue_id"],
        "state": "In Progress",
        "capture_started_at": "2026-01-03T00:01:00Z",
        "capture_completed_at": "2026-01-03T00:02:00Z",
        "raw_observations": [],
        "project_scans": scans,
        "team_statuses": teams,
        "project_milestones": milestones,
        "issues": issues,
        "catalog_issue_ids": catalogue,
        "direct_gate_issue_ids": direct_ids,
        **{
            key: projection[key]
            for key in ("required_bom_ids", "required_bom", "required_bom_snapshot_digest")
        },
        "coverage": {
            "root_project_ids": projects,
            "root_catalog_issue_ids": catalogue,
            "root_current_decision_id": context["decision"]["issue_id"],
            "root_direct_gate_ids": direct_ids,
            "blocking_closure_issue_ids": all_ids,
            "relation_endpoint_issue_ids": [],
            "unresolved_issue_identifiers": [],
            "unresolved_pages": [],
            "excluded_required_issues": [],
        },
        "stabilization": {
            "rounds": 2,
            "method": "two-complete-equal-projections-no-atomic-snapshot-claim",
            "round_1_projection_digest": release.sha256_json(semantic),
            "round_2_projection_digest": release.sha256_json(semantic),
        },
        "producer_intent_digest": "a" * 64,
        "invocation_root_locator": "invocations",
    }
    kwargs = {
        "readiness_registry_raw": registry_raw,
        "original_work_orders": original_work_orders,
        "expected_work_orders_digest": release.sha256_bytes(original_work_orders),
        "expected_readiness_digest": release.sha256_bytes(registry_raw),
        **{
            key: arguments[key]
            for key in (
                "original_packet",
                "expected_packet_digest",
                "context_id",
                "declared_dependencies",
            )
        },
        **{
            key: lifecycle[key]
            for key in ("task_state_policy_raw", "expected_task_state_policy_digest")
        },
        "observed_at": "2026-01-03T00:03:00Z",
        "consumer_stage": "prepromotion",
    }
    return data, payloads, kwargs, semantic


def _linear_wire_capture(
    tmp_path: Path, data: dict[str, Any], payloads: dict[str, Any]
) -> tuple[Path, release._ReleaseCapturedFiles]:
    root = tmp_path / "captured-original"
    root.mkdir()
    members = []
    data["raw_observations"] = []
    for number, member in enumerate(payloads.values()):
        raw = member.get(
            "raw_override",
            release.canonical_json(
                {
                    "content": [{"type": "text", "text": json.dumps(member["payload"])}],
                    "isError": False,
                }
            ),
        )
        path = root / f"response-{number}.json"
        path.write_bytes(raw)
        members.append((path.name, "prerequisite-original"))
        data["raw_observations"].append(
            {
                **member["observation"],
                "response": {
                    "path": path.name,
                    "bytes": len(raw),
                    "sha256": release.sha256_bytes(raw),
                },
            }
        )
    data["snapshot_digest"] = release.sha256_json(
        {key: value for key, value in data.items() if key != "snapshot_digest"}
    )
    snapshot = root / "snapshot.json"
    snapshot.write_bytes(
        release.canonical_json(
            release.make_record(
                "linear-release-snapshot",
                data,
                invocation_id="synthetic-wire",
                sequence=1,
                synthetic=True,
            )
        )
    )
    members.append((snapshot.name, "prerequisite-original"))
    return snapshot, release._ReleaseCapturedFiles.capture(
        root, members, allowed_kinds=frozenset({"prerequisite-original"}), forbidden=[]
    )


@pytest.mark.parametrize("override", ["caller", "marker"])
def test_linear_original_wire_cannot_redeclare_original_work_order_from_consistent_observed_graph(
    tmp_path: Path, override: str
) -> None:
    data, payloads, kwargs, _ = _linear_wire_fixture(catalog_override=override)
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    # Both raw rounds, reciprocal edges and recorded BOM reflect this override.
    # Their internal consistency cannot alter the independent original work order.
    expected = (
        "dependency projection changed original" if override == "caller" else "marker changed"
    )
    with pytest.raises(release.ReleaseControlError, match=expected):
        release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)


def test_linear_original_wire_full_rounds_and_relocated_snapshot(tmp_path: Path) -> None:
    data, payloads, kwargs, semantic = _linear_wire_fixture()
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    result = release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)
    assert len(result["record"]["data"]["issues"]) == 95
    assert len(result["record"]["data"]["catalog_issue_ids"]) == 93
    assert result["record"]["data"]["coverage"]["relation_endpoint_issue_ids"] == []
    assert result["record"]["data"]["stabilization"][
        "round_2_projection_digest"
    ] == release.sha256_json(semantic)
    # Rebuild the same immutable original bytes under a new root; no original path read occurs.
    import shutil

    relocated = tmp_path / "relocated"
    shutil.copytree(captured.root, relocated)
    shutil.rmtree(captured.root)
    inventory = [(path.name, "prerequisite-original") for path in relocated.iterdir()]
    moved = release._ReleaseCapturedFiles.capture(
        relocated, inventory, allowed_kinds=frozenset({"prerequisite-original"}), forbidden=[]
    )
    assert (
        release._release_linear_snapshot_replay(relocated / snapshot.name, captured=moved, **kwargs)
        == result
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-next-page",
        "cursor-loop",
        "orphan-page",
        "filtered-request",
        "missing-null",
        "missing-detail",
        "duplicate-uuid",
        "index-description-drift",
        "round-description-drift",
        "hidden-project-task",
        "missing-status",
        "wrong-state",
        "missing-milestone",
        "unresolved-endpoint",
        "nonreciprocal",
        "wrong-project",
        "duplicate-detail",
        "missing-round",
        "round-overlap",
        "stale",
        "future",
        "future-provider",
        "forged-bom",
        "forged-coverage",
        "forged-stability",
        "duplicate-json-key",
        "error-envelope",
        "truncated-payload",
        "wrong-pointer",
    ],
)
def test_linear_original_wire_rejects_partial_or_fabricated_capture(
    tmp_path: Path, mutation: str
) -> None:
    data, payloads, kwargs, _ = _linear_wire_fixture()
    detail = payloads["synthetic-r2-detail-SYN-1"]
    pages = [
        row
        for row in payloads.values()
        if row["observation"]["round"] == 2 and row["observation"]["tool"].endswith("list_issues")
    ]
    first_page = next(row for row in pages if row["payload"]["hasNextPage"])
    if mutation == "missing-next-page":
        del payloads[
            next(
                key
                for key, row in payloads.items()
                if row["observation"]["round"] == 2 and "cursor" in row["observation"]["arguments"]
            )
        ]
    elif mutation == "cursor-loop":
        page = next(row for row in pages if "cursor" in row["observation"]["arguments"])
        page["payload"].update(hasNextPage=True, cursor=page["observation"]["arguments"]["cursor"])
    elif mutation in {"orphan-page", "duplicate-detail"}:
        row = copy.deepcopy(first_page if mutation == "orphan-page" else detail)
        row["observation"]["id"] = "synthetic-extra"
        if mutation == "orphan-page":
            row["observation"]["arguments"]["cursor"] = "unowned-cursor"
        payloads["synthetic-extra"] = row
    elif mutation == "filtered-request":
        first_page["observation"]["arguments"]["state"] = "Done"
    elif mutation == "missing-null":
        del detail["payload"]["parentId"]
    elif mutation == "missing-detail":
        del payloads["synthetic-r2-detail-SYN-1"]
    elif mutation == "duplicate-uuid":
        detail["payload"]["uuid"] = payloads["synthetic-r2-detail-SYN-2"]["payload"]["uuid"]
    elif mutation == "index-description-drift":
        detail["payload"]["description"] += " changed"
    elif mutation == "round-description-drift":
        detail["payload"]["description"] += " changed"
        for page in pages:
            for row in page["payload"]["issues"]:
                if row["id"] == "SYN-1":
                    row["description"] = detail["payload"]["description"]
    elif mutation == "hidden-project-task":
        first_page["payload"]["issues"].append(
            {
                **first_page["payload"]["issues"][0],
                "id": "SYN-999",
                "uuid": "00000000-0000-0000-0000-000000000999",
            }
        )
    elif mutation in {"missing-status", "missing-milestone"}:
        suffix = "list_issue_statuses" if mutation == "missing-status" else "list_milestones"
        del payloads[
            next(
                key
                for key, row in payloads.items()
                if row["observation"]["round"] == 2 and row["observation"]["tool"].endswith(suffix)
            )
        ]
    elif mutation == "wrong-state":
        detail["payload"]["status"] = "Unknown state"
    elif mutation == "unresolved-endpoint":
        detail["payload"]["relations"]["blockedBy"] = [{"id": "SYN-999"}]
    elif mutation == "nonreciprocal":
        payloads["synthetic-r2-detail-SYN-95"]["payload"]["relations"]["blocks"] = []
    elif mutation == "wrong-project":
        detail["payload"]["projectId"] = "00000000-0000-0000-0000-000000099999"
    elif mutation == "missing-round":
        payloads = {key: row for key, row in payloads.items() if row["observation"]["round"] == 2}
    elif mutation == "round-overlap":
        payloads["synthetic-r1-detail-SYN-1"]["observation"]["completed_at"] = (
            "2026-01-03T00:02:01Z"
        )
        data["capture_completed_at"] = "2026-01-03T00:02:01Z"
    elif mutation in {"stale", "future"}:
        kwargs["observed_at"] = (
            "2026-01-03T00:08:00Z" if mutation == "stale" else "2026-01-03T00:00:00Z"
        )
    elif mutation == "future-provider":
        for member in payloads.values():
            values = (
                member["payload"].get("issues", [member["payload"]])
                if isinstance(member["payload"], dict)
                else []
            )
            for row in values:
                if row.get("id") == "SYN-1":
                    row["updatedAt"] = "2026-01-03T00:05:00Z"
    elif mutation == "forged-bom":
        data["required_bom"] = data["required_bom"][:1]
        data["required_bom_snapshot_digest"] = release.sha256_json(data["required_bom"])
    elif mutation == "forged-coverage":
        data["coverage"]["blocking_closure_issue_ids"] = data["catalog_issue_ids"]
    elif mutation == "forged-stability":
        data["stabilization"]["round_1_projection_digest"] = "b" * 64
    elif mutation == "duplicate-json-key":
        detail["raw_override"] = b'{"content":[],"content":[],"isError":false}'
    elif mutation == "error-envelope":
        detail["raw_override"] = release.canonical_json(
            {"content": [{"type": "text", "text": json.dumps(detail["payload"])}], "isError": True}
        )
    elif mutation == "truncated-payload":
        detail["payload"]["truncated"] = True
    elif mutation == "wrong-pointer":
        detail["observation"]["extracted_json_pointer"] = "/content/1/text"
    snapshot, captured = _linear_wire_capture(tmp_path, data, payloads)
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_snapshot_replay(snapshot, captured=captured, **kwargs)


@pytest.mark.parametrize("version", ["0.4.1", "0.4.10", "0.9.0", "1.0.100"])
def test_gate_accepts_canonical_package_versions(version: str) -> None:
    assert release._parse_release_package_version(version)[1] == version


@pytest.mark.parametrize(
    "version",
    [
        "v0.4.1",
        "0.04.1",
        "0.4.01",
        "0.4.1\n",
        " 0.4.1",
        "0.4.1+local",
        "0.4.1rc1",
        "0.4.1.post0",
        "0.4.١",
    ],
)
def test_gate_rejects_current_version_aliases(version: str) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._parse_release_package_version(version)


def test_gate_historical_post_syntax_does_not_authorize_current_post() -> None:
    plain = release._release_version_pair("0.4.0", "v0.4.0", historical=True)
    post = release._release_version_pair("0.4.0.post0", "v0.4.0.post0", historical=True)
    later = release._release_version_pair("0.4.1", "v0.4.1")
    assert plain < post < later
    with pytest.raises(release.ReleaseControlError):
        release._release_version_pair("0.4.0.post0", "v0.4.0.post0")


@pytest.mark.parametrize("control", [chr(number) for number in range(32)])
def test_gate_rejects_control_characters_in_raw_suffix(control: str) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_relative_suffix("proofs/a" + control + ".json", "test")


@pytest.mark.parametrize("path", ["", "/absolute", "a//b", "a/./b", "a/../b", "a/", "a\\b"])
def test_gate_rejects_noncanonical_raw_suffix(path: str) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_relative_suffix(path, "test")


def test_gate_captured_inventory_rejects_late_unlisted_read(tmp_path: Path) -> None:
    (tmp_path / "input.json").write_bytes(b"{}")
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [("input.json", "raw")],
        allowed_kinds=frozenset({"raw"}),
        forbidden=["gate-input.json", "invocations/gate-input"],
    )
    (tmp_path / "other.json").write_bytes(b"{}")
    assert captured.read("input.json", kind="raw") == b"{}"
    with pytest.raises(release.ReleaseControlError):
        captured.read("other.json", kind="raw")
    with pytest.raises(release.ReleaseControlError):
        captured.read("input.json", kind="authority")


def test_gate_captured_inventory_rejects_changed_same_path(tmp_path: Path) -> None:
    p = tmp_path / "input.json"
    p.write_bytes(b"{}")
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path, [(p.name, "raw")], allowed_kinds=frozenset({"raw"}), forbidden=[]
    )
    p.unlink()
    p.write_bytes(b"{}")
    with pytest.raises(release.ReleaseControlError):
        captured.revalidate()


def test_gate_capture_rejects_hardlink_even_when_only_one_alias_declared(tmp_path: Path) -> None:
    p = tmp_path / "input.json"
    p.write_bytes(b"{}")
    os.link(p, tmp_path / "alias.json")
    with pytest.raises(release.ReleaseControlError):
        release._ReleaseCapturedFiles.capture(
            tmp_path, [(p.name, "raw")], allowed_kinds=frozenset({"raw"}), forbidden=[]
        )


def test_gate_capture_rejects_symbolic_ancestor(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real/input.json").write_bytes(b"{}")
    (tmp_path / "linked").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(release.ReleaseControlError):
        release._ReleaseCapturedFiles.capture(
            tmp_path, [("linked/input.json", "raw")], allowed_kinds=frozenset({"raw"}), forbidden=[]
        )


def test_gate_capture_rejects_fifo_without_waiting_for_writer(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(release.ReleaseControlError):
        release._ReleaseCapturedFiles.capture(
            tmp_path, [("pipe", "raw")], allowed_kinds=frozenset({"raw"}), forbidden=[]
        )


def test_gate_capture_rejects_output_namespace_overlap(tmp_path: Path) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._ReleaseCapturedFiles.capture(
            tmp_path,
            [("invocations/gate-input/1/intent.json", "raw")],
            allowed_kinds=frozenset({"raw"}),
            forbidden=["invocations/gate-input"],
        )


@pytest.mark.parametrize("substitution", [True, 1.0])
def test_gate_raw_reference_rejects_numeric_alias_of_original_field(
    tmp_path: Path,
    substitution: object,
) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x")
    row = {"path": payload.name, "bytes": 1, "sha256": release.sha256_bytes(b"x")}
    container = tmp_path / "declaring.json"
    container.write_bytes(release.canonical_json({"nested": [row]}))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [(container.name, "declaring"), (payload.name, "raw")],
        allowed_kinds=frozenset({"raw", "declaring"}),
        forbidden=[],
    )
    arguments = dict(
        containing_path=container,
        containing_kind="declaring",
        field=("nested", 0),
        captured=captured,
        expected_kind="raw",
        label="payload",
    )
    assert release._release_captured_raw_file(row, **arguments) == (payload, b"x")
    with pytest.raises(release.ReleaseControlError, match="captured declaring field"):
        release._release_captured_raw_file({**row, "bytes": substitution}, **arguments)


def test_gate_raw_reference_requires_its_original_declaring_field(tmp_path: Path) -> None:
    row = {"path": "payload", "bytes": 1, "sha256": release.sha256_bytes(b"x")}
    (tmp_path / "payload").write_bytes(b"x")
    (tmp_path / "declaring").write_bytes(release.canonical_json({"a": row, "b": None}))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [("declaring", "declaring"), ("payload", "raw")],
        allowed_kinds=frozenset({"raw", "declaring"}),
        forbidden=[],
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_captured_raw_file(
            row,
            containing_path=tmp_path / "declaring",
            containing_kind="declaring",
            field=("b",),
            captured=captured,
            expected_kind="raw",
            label="payload",
        )


def test_gate_empty_capture_still_binds_the_actual_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [],
        allowed_kinds=frozenset({"raw"}),
        forbidden=[],
    )
    root.rename(tmp_path / "retained-original")
    root.mkdir()
    with pytest.raises(release.ReleaseControlError, match="substituted"):
        captured.revalidate()


def test_gate_same_bytes_under_replaced_ancestor_do_not_reuse_capture(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "payload").write_bytes(b"x")
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [("payload", "raw")],
        allowed_kinds=frozenset({"raw"}),
        forbidden=[],
    )
    root.rename(tmp_path / "old")
    root.mkdir()
    (root / "payload").write_bytes(b"x")
    with pytest.raises(release.ReleaseControlError):
        captured.read("payload", kind="raw")
    # A fresh capture is a different input context, never a relocation waiver.
    fresh = release._ReleaseCapturedFiles.capture(
        root,
        [("payload", "raw")],
        allowed_kinds=frozenset({"raw"}),
        forbidden=[],
    )
    assert fresh.read("payload", kind="raw") == b"x"


@pytest.mark.parametrize(
    "pointer", ["a", "/a/00", "/a/01", "/a/-", "/a/+0", "/a/٠", "/a/2", "/bad~2"]
)
def test_gate_json_pointer_rejects_noncanonical_or_absent_location(pointer: str) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_json_pointer({"a": [1, 2]}, pointer, "source")


def test_gate_json_pointer_resolves_escapes_without_guessing() -> None:
    value = {"": {"a/b": {"~0": [False, {"x": 3}]}}}
    assert release._release_json_pointer(value, "//a~1b/~00/1/x", "source") == 3
    assert release._release_json_pointer(value, "", "source") is value
    assert release._release_unique_json_rows([True, 1, 1.0, 1]) == [1, 1.0, True]


def _catalog_structure_fixture() -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    """Structural algorithm fixture only; it supplies no native authority proof."""

    def scenario(identity: str, children: list[str] | None = None) -> dict[str, object]:
        return {
            "id": identity,
            "first_required_release": "v0.4",
            "phase": "qualification",
            "kind": "release_requirement",
            "expected_subject": {
                "scope": "production_operation",
                "verdict": "PASS",
                "fault_id": None,
            },
            "retry_policy": "no_automatic_retry",
            "qualification_unit_terminal_on_verified_expectation": "PASS",
            "expansion": {
                "kind": "leaf",
                "implementation": {"state": "UNRESOLVED", "reason": "structural fixture"},
            }
            if children is None
            else {"kind": "group", "scenario_ids": children},
        }

    scenarios = [
        scenario("root", ["left", "right"]),
        scenario("left", ["leaf"]),
        scenario("right", ["leaf"]),
        scenario("leaf"),
    ]
    registry: dict[str, object] = {
        "scenarios": scenarios,
        "release_slots": [
            {
                "milestone": milestone,
                "qualification_attempts_required": 1,
                "qualification_scenario_ids": ["root"],
                "publication_reconciliation_scenario_ids": [],
                "postpublication_scenario_ids": [],
            }
            for milestone in release.MILESTONES
        ],
    }
    refs = {
        str(row["id"]): {
            "raw_registry_path": "docs/status/release-scenarios.json",
            "raw_registry_digest": "0" * 64,
            "json_pointer": "/scenarios/" + str(i),
        }
        for i, row in enumerate(scenarios)
    }
    return registry, refs


def test_catalog_diamond_retains_both_constraint_paths_after_memoization() -> None:
    registry, refs = _catalog_structure_fixture()
    result = release._release_scenario_structure(
        registry, root="root", milestone="v0.4", phase="qualification", source_refs=refs
    )
    assert result["leaf_scenario_ids"] == ["leaf"]
    assert [row["scenario_id"] for row in result["steps"]] == ["root", "left", "leaf", "right"]
    assert [path for path in result["constraint_uses"] if path[-1][0] == "leaf"] == [
        [("root", "v0.4"), ("left", "v0.4"), ("leaf", "v0.4")],
        [("root", "v0.4"), ("right", "v0.4"), ("leaf", "v0.4")],
    ]
    assert json.loads(release.canonical_json(registry)) == registry


@pytest.mark.parametrize(
    "mutation",
    ["cycle", "phase", "future", "empty", "retry", "subject", "duplicate", "unknown", "slots"],
)
def test_catalog_structural_constraints_fail_before_executable_units(mutation: str) -> None:
    original, refs = _catalog_structure_fixture()
    registry = copy.deepcopy(original)
    rows = registry["scenarios"]
    assert isinstance(rows, list)
    if mutation == "cycle":
        rows[2]["expansion"]["scenario_ids"] = ["root"]
    elif mutation == "phase":
        rows[3]["phase"] = "postpublication"
    elif mutation == "future":
        rows[3]["first_required_release"] = "v0.5"
    elif mutation == "empty":
        rows[0]["expansion"]["scenario_ids"] = []
    elif mutation == "retry":
        rows[1]["retry_policy"] = "fresh_invocation_preserve_all_attempts"
    elif mutation == "subject":
        rows[1]["expected_subject"]["verdict"] = "BLOCKED"
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[3]))
    elif mutation == "unknown":
        rows[1]["expansion"] = {"kind": "future-selector"}
    elif mutation == "slots":
        slots = registry["release_slots"]
        assert isinstance(slots, list)
        slots.append(None)
    with pytest.raises(release.ReleaseControlError):
        release._release_scenario_structure(
            registry, root="root", milestone="v0.4", phase="qualification", source_refs=refs
        )


def _catalog_unit_fixture() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Static graph fixture, deliberately separate from full native gate authority."""
    base, _ = _catalog_structure_fixture()
    scenario_registry: dict[str, Any] = base
    scenarios = scenario_registry["scenarios"]
    environments = [
        {
            "id": "linux",
            "profile_id": "profile",
            "first_required_release": "v0.4",
            "execution": {"state": "CONFIGURED", "executor_ids": ["executor"]},
        }
    ]
    executors = [
        {
            "id": "executor",
            "phase": "qualification",
            "binding": {"state": "CONFIGURED", "recipe": {"effect_class": "scratch_only"}},
        }
    ]
    obligations = []
    for name, owner in [
        ("ONE", "left"),
        ("TWO", "right"),
        ("P1", "prerequisite-one"),
        ("P2", "prerequisite-two"),
    ]:
        obligations.append(
            {
                "id": "MP2-007.OBL." + name,
                "first_required_release": "v0.4",
                "lifecycle": "active",
                "superseded_by": [],
                "supersession_authority": [],
                "implementation": {"state": "CONFIGURED", "executor_ids": ["executor"]},
                "environment_ids": ["linux"],
                "profile_ids": ["profile"],
                "scenario_ids": [owner],
                "criterion_ids": ["MP2-007.A01"],
                "family_ids": ["BASELINE"],
            }
        )
    for identity in ("prerequisite-one", "prerequisite-two"):
        row = copy.deepcopy(scenarios[-1])
        row["id"] = identity
        scenarios.append(row)
    for row in scenarios:
        row.update(
            environment_pairs=[{"environment_id": "linux", "profile_id": "profile"}],
            covers_stages=["qualification"],
            prerequisite_scenario_ids=[],
        )
        required = {
            "root": ["ONE", "TWO"],
            "left": ["ONE"],
            "right": ["TWO"],
            "leaf": ["ONE"],
            "prerequisite-one": ["P1"],
            "prerequisite-two": ["P2"],
        }[row["id"]]
        row["required_obligations"] = {
            "state": "MAPPED",
            "obligation_ids": ["MP2-007.OBL." + x for x in required],
        }
        if row["expansion"]["kind"] == "leaf":
            row["expansion"]["implementation"] = {
                "state": "CONFIGURED",
                "executor_ids": ["executor"],
            }
    scenarios[1]["prerequisite_scenario_ids"] = ["prerequisite-one"]
    scenarios[2]["prerequisite_scenario_ids"] = ["prerequisite-two"]
    scenario_registry["executors"] = []
    raw = {
        "docs/status/release-scenarios.json": release.canonical_json(scenario_registry),
        "docs/status/supported-environments.json": release.canonical_json(
            {"environments": environments, "executors": executors}
        ),
        "docs/status/release-test-obligations.json": release.canonical_json(
            {
                "obligations": obligations,
                "executors": [],
                "criterion_requirements": [
                    {
                        "criterion_id": "MP2-007.A01",
                        "first_required_release": "v0.4",
                        "required_family_ids": ["BASELINE"],
                        "mapping": {
                            "state": "MAPPED",
                            "obligation_ids": [row["id"] for row in obligations],
                        },
                    }
                ],
            }
        ),
    }
    return release._release_catalog_declarations(raw)


def _catalog_redeclare(
    parsed: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    return release._release_catalog_declarations(
        {key: release.canonical_json(value) for key, value in parsed.items()}
    )


def test_catalog_shared_leaf_unions_owned_obligations_and_all_parent_prerequisites() -> None:
    parsed, declarations = _catalog_unit_fixture()
    original = release.canonical_json(parsed)
    graph = release._release_catalog_graph(parsed, declarations)
    assert not graph["unresolved_declarations"]
    assert len(graph["execution_units"]) == 21
    for milestone in release.MILESTONES:
        units = {
            u["scenario_id"]: u
            for u in graph["execution_units"]
            if u["slot_milestone"] == milestone
        }
        leaf = units["leaf"]
        assert leaf["obligation_ids"] == ["MP2-007.OBL.ONE", "MP2-007.OBL.TWO"]
        assert set(leaf["prerequisite_unit_ids"]) == {
            units[p]["unit_id"] for p in ("prerequisite-one", "prerequisite-two")
        }
        assert {r["obligation_id"] for r in leaf["coverage_reasons"]} == set(leaf["obligation_ids"])
    assert len({u["unit_id"] for u in graph["execution_units"] if u["scenario_id"] == "leaf"}) == 7
    assert release.canonical_json(parsed) == original
    assert release.canonical_json(
        release._release_catalog_graph(parsed, declarations)
    ) == release.canonical_json(graph)


def test_catalog_parent_reference_cannot_grant_unmapped_obligation_ownership() -> None:
    parsed, _ = _catalog_unit_fixture()
    parsed["docs/status/release-test-obligations.json"]["obligations"][1]["scenario_ids"] = [
        "prerequisite-one"
    ]
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert graph["unresolved_declarations"]
    leaf = next(u for u in graph["execution_units"] if u["scenario_id"] == "leaf")
    assert leaf["obligation_ids"] == ["MP2-007.OBL.ONE"]
    assert any(
        row["unresolved_dependency_id"] == "MP2-007.OBL.TWO"
        for row in graph["unresolved_declarations"]
    )


@pytest.mark.parametrize("case", ["self", "cycle", "phase", "future", "unknown", "mutation"])
def test_catalog_prerequisites_and_recipes_do_not_borrow_authority(case: str) -> None:
    parsed, _ = _catalog_unit_fixture()
    scenarios = parsed["docs/status/release-scenarios.json"]["scenarios"]
    if case == "self":
        scenarios[1]["prerequisite_scenario_ids"] = ["leaf"]
    elif case == "cycle":
        scenarios[4]["prerequisite_scenario_ids"] = ["root"]
    elif case == "phase":
        scenarios[4]["phase"] = "postpublication"
    elif case == "future":
        scenarios[4]["first_required_release"] = "v0.5"
    elif case == "unknown":
        scenarios[1]["prerequisite_scenario_ids"] = ["absent"]
    elif case == "mutation":
        parsed["docs/status/supported-environments.json"]["executors"][0]["binding"]["recipe"][
            "effect_class"
        ] = "existing_release_mutation"
    with pytest.raises(release.ReleaseControlError):
        release._release_catalog_graph(*_catalog_redeclare(parsed))


def test_catalog_fault_leaf_keeps_its_subject_when_parent_requires_pass() -> None:
    parsed, _ = _catalog_unit_fixture()
    leaf = parsed["docs/status/release-scenarios.json"]["scenarios"][3]
    leaf["kind"] = "fault_rehearsal"
    leaf["expected_subject"] = {
        "scope": "isolated_fault_subject",
        "verdict": "BLOCKED",
        "fault_id": "retained-fault",
    }
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    unit = next(u for u in graph["execution_units"] if u["scenario_id"] == "leaf")
    assert unit["expected_subject"] == leaf["expected_subject"]
    assert unit["qualification_unit_terminal_on_verified_expectation"] == "PASS"


def test_catalog_unresolved_prerequisite_prevents_dependent_unit_materialization() -> None:
    parsed, _ = _catalog_unit_fixture()
    row = parsed["docs/status/release-scenarios.json"]["scenarios"][4]
    row["expansion"]["implementation"] = {
        "state": "UNRESOLVED",
        "reason": "Required software mapping is absent",
    }
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not any(
        unit["scenario_id"] in {"leaf", "prerequisite-one"} for unit in graph["execution_units"]
    )
    assert all(
        slot["expansions"]["qualification"][0]["unresolved_declarations"]
        for slot in graph["release_slots"]
    )

    assert all(
        not slot["expansions"]["qualification"][0]["execution_unit_ids"]
        for slot in graph["release_slots"]
    )


def _planning_membership_fixture() -> tuple[dict[str, Any], bytes]:
    """Synthetic complete-size packet, with no real provider or policy authority."""
    tasks = [
        {
            "task": f"MP2-{i:03}",
            "linear_issue": f"SYN-{i}",
            "role": "implementation",
            "first_required_release": "v0.4",
            "blocks_release": True,
        }
        for i in range(93)
    ]
    slots = []
    for i, milestone in enumerate(release.MILESTONES):
        decision = tasks[80 + i]
        decision.update(role="release_decision", first_required_release=milestone)
        slots.append(
            {
                "version": milestone,
                "linear_milestone_id": f"synthetic-milestone-{i}",
                "release_decision_task": decision["task"],
                "linear_release_decision_issue": decision["linear_issue"],
                "required_development_tasks": [tasks[i]["task"]],
                "required_scenario_ids": [f"SCENARIO-{i}"],
                "qualification_scenario_ids": [f"SCENARIO-{i}"],
                "publication_reconciliation_scenario_ids": [],
                "postpublication_scenario_ids": [],
                "qualification_attempts_required": 3 if i >= 5 else 1,
            }
        )
    raw = release.canonical_json({"task_registry": tasks, "releases": slots})
    return {
        "task_catalog": copy.deepcopy(tasks),
        "release_gate_slots": copy.deepcopy(slots),
        "catalog_binding": {
            "source": {
                "path": "original.json",
                "bytes": len(raw),
                "sha256": release.sha256_bytes(raw),
            },
            "task_registry_sha256": release.sha256_json(tasks),
            "release_slots_sha256": release.sha256_json(slots),
            "snapshot_role": "UNCHANGED_PLANNING_AUTHORITY_NOT_CURRENT_PROVIDER_FACTS",
        },
    }, raw


def test_readiness_projection_keeps_complete_original_membership() -> None:
    registry, raw = _planning_membership_fixture()
    actual = release._release_readiness_catalog_projection(
        registry, original_packet=raw, expected_packet_digest=release.sha256_bytes(raw)
    )
    assert len(actual["task_catalog"]) == 93
    assert len(actual["release_gate_slots"]) == 7


@pytest.mark.parametrize(
    "mutation",
    [
        "six-gates-only",
        "same-count-substitution",
        "phase-move",
        "repetition",
        "number-for-bool",
        "renewed-local-hash",
        "raw-whitespace",
    ],
)
def test_readiness_projection_rejects_rewritten_planning_authority(mutation: str) -> None:
    registry, raw = _planning_membership_fixture()
    expected = release.sha256_bytes(raw)
    if mutation == "six-gates-only":
        registry["task_catalog"] = registry["task_catalog"][:6]
    elif mutation == "same-count-substitution":
        registry["task_catalog"][0]["task"] = "MP2-999"
    elif mutation == "phase-move":
        row = registry["release_gate_slots"][0]
        row["postpublication_scenario_ids"] = row["qualification_scenario_ids"]
        row["qualification_scenario_ids"] = []
    elif mutation == "repetition":
        registry["release_gate_slots"][-1]["qualification_attempts_required"] = 1
    elif mutation == "number-for-bool":
        registry["task_catalog"][0]["blocks_release"] = 1
    elif mutation == "renewed-local-hash":
        packet = json.loads(raw)
        packet["task_registry"][0]["linear_issue"] = "SYN-NEW"
        raw = release.canonical_json(packet)
        registry["task_catalog"] = packet["task_registry"]
        registry["catalog_binding"]["source"].update(
            bytes=len(raw), sha256=release.sha256_bytes(raw)
        )
        registry["catalog_binding"]["task_registry_sha256"] = release.sha256_json(
            packet["task_registry"]
        )
    else:
        raw += b"\n"
    with pytest.raises(release.ReleaseControlError):
        release._release_readiness_catalog_projection(
            registry, original_packet=raw, expected_packet_digest=expected
        )


def _criterion_requirements_fixture() -> tuple[dict[str, Any], bytes]:
    tasks, criteria = [], []
    families = {f"F{i}": "synthetic family" for i in range(19)}
    for i in range(93):
        task_id = f"MP2-{i:03}"
        first = "post-v1.0" if i == 92 else "v0.4"
        predicates = []
        for offset in range(4 if i == 92 else 3):
            criterion_id = task_id + f".A{offset + 1:02}"
            text = f"Synthetic predicate {i}/{offset}"
            predicates.append(
                {
                    "criterion_id": criterion_id,
                    "predicate": text,
                    "required_test_family_ids": ["F0", "F1"],
                }
            )
            criteria.append(
                {
                    "task_id": task_id,
                    "criterion_id": criterion_id,
                    "predicate": text,
                    "predicate_digest": release.sha256_json(text),
                    "first_required_release": first,
                    "required_family_ids": ["F0", "F1"],
                }
            )
        tasks.append(
            {
                "task_id": task_id,
                "first_required_release": first,
                "task_specific_acceptance_predicates": predicates,
            }
        )
    return {"criterion_requirements": criteria}, release.canonical_json(
        {"tasks": tasks, "test_family_definitions": families}
    )


def test_criterion_projection_retains_all_families_and_future_rows() -> None:
    registry, raw = _criterion_requirements_fixture()
    result = release._release_obligation_criterion_projection(
        registry, original_packet=raw, expected_packet_digest=release.sha256_bytes(raw)
    )
    assert len(result) == 280
    assert result["MP2-092.A04"]["first_required_release"] == "post-v1.0"


@pytest.mark.parametrize(
    "mutation",
    [
        "old-thirteen-only",
        "drop-future",
        "same-count-substitution",
        "duplicate",
        "family-drop",
        "family-order",
        "retarget",
        "rewrite-predicate",
        "forged-original",
    ],
)
def test_criterion_projection_rejects_criterion_and_family_reductions(mutation: str) -> None:
    registry, raw = _criterion_requirements_fixture()
    expected = release.sha256_bytes(raw)
    rows = registry["criterion_requirements"]
    if mutation == "old-thirteen-only":
        registry["criterion_requirements"] = rows[:13]
    elif mutation == "drop-future":
        registry["criterion_requirements"] = rows[:-4]
    elif mutation == "same-count-substitution":
        rows[0]["criterion_id"] = "MP2-999.A01"
    elif mutation == "duplicate":
        rows[1] = copy.deepcopy(rows[0])
    elif mutation == "family-drop":
        rows[0]["required_family_ids"] = ["F0"]
    elif mutation == "family-order":
        rows[0]["required_family_ids"].reverse()
    elif mutation == "retarget":
        rows[0]["first_required_release"] = "post-v1.0"
    elif mutation == "rewrite-predicate":
        rows[0].update(
            predicate="weaker claim", predicate_digest=release.sha256_json("weaker claim")
        )
    else:
        packet = json.loads(raw)
        packet["tasks"][0]["task_specific_acceptance_predicates"][0]["required_test_family_ids"] = [
            "F0"
        ]
        raw = release.canonical_json(packet)
        rows[0]["required_family_ids"] = ["F0"]
    with pytest.raises(release.ReleaseControlError):
        release._release_obligation_criterion_projection(
            registry, original_packet=raw, expected_packet_digest=expected
        )


def test_catalog_checks_complete_environment_projection_without_inventing_pairs() -> None:
    parsed, _ = _catalog_unit_fixture()
    environment = copy.deepcopy(
        parsed["docs/status/supported-environments.json"]["environments"][0]
    )
    environment["id"] = "macos"
    parsed["docs/status/supported-environments.json"]["environments"].append(environment)
    parsed["docs/status/release-test-obligations.json"]["obligations"][0]["environment_ids"].append(
        "macos"
    )
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not any(unit["environment_id"] == "macos" for unit in graph["execution_units"])
    assert any(
        row["stable_id"] == "MP2-007.OBL.ONE" and "projection coverage" in row["reason"]
        for row in graph["unresolved_declarations"]
    )


def test_catalog_future_obligation_gap_does_not_rewrite_an_earlier_slot() -> None:
    parsed, _ = _catalog_unit_fixture()
    registry = parsed["docs/status/release-test-obligations.json"]
    later = copy.deepcopy(registry["obligations"][0])
    later.update(id="MP2-007.OBL.LATER", first_required_release="v0.5", environment_ids=["macos"])
    registry["obligations"].append(later)
    registry["criterion_requirements"][0]["mapping"]["obligation_ids"].append(later["id"])
    parsed["docs/status/release-scenarios.json"]["scenarios"][0]["required_obligations"][
        "obligation_ids"
    ].append(later["id"])
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not graph["release_slots"][0]["expansions"]["qualification"][0][
        "unresolved_declarations"
    ]
    assert all(
        slot["expansions"]["qualification"][0]["unresolved_declarations"]
        for slot in graph["release_slots"][1:]
    )


def test_catalog_one_configured_family_cannot_satisfy_every_required_family() -> None:
    parsed, _ = _catalog_unit_fixture()
    parsed["docs/status/release-test-obligations.json"]["criterion_requirements"][0][
        "required_family_ids"
    ].append("SECURITY")
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert any(
        row["stable_id"] == "MP2-007.A01" and "every required family" in row["reason"]
        for row in graph["unresolved_declarations"]
    )


def test_catalog_criterion_and_obligation_mappings_must_be_reciprocal() -> None:
    parsed, _ = _catalog_unit_fixture()
    parsed["docs/status/release-test-obligations.json"]["obligations"][0]["criterion_ids"] = [
        "MP2-007.A02"
    ]
    with pytest.raises(release.ReleaseControlError):
        release._release_catalog_graph(*_catalog_redeclare(parsed))


def test_catalog_does_not_silently_drop_an_unmatched_declared_executor() -> None:
    parsed, _ = _catalog_unit_fixture()
    leaf = parsed["docs/status/release-scenarios.json"]["scenarios"][3]
    leaf["expansion"]["implementation"]["executor_ids"].append("unmatched")
    extra = copy.deepcopy(parsed["docs/status/supported-environments.json"]["executors"][0])
    extra["id"] = "unmatched"
    parsed["docs/status/supported-environments.json"]["executors"].append(extra)
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert any(
        row["unresolved_dependency_id"] == "unmatched" for row in graph["unresolved_declarations"]
    )
    assert all(
        slot["expansions"]["qualification"][0]["unresolved_declarations"]
        for slot in graph["release_slots"]
    )


@pytest.mark.parametrize("future_first", [True, False])
def test_catalog_obligation_scenario_order_does_not_change_current_applicability(
    future_first: bool,
) -> None:
    parsed, _ = _catalog_unit_fixture()
    registry = parsed["docs/status/release-scenarios.json"]
    future = copy.deepcopy(registry["scenarios"][1])
    future.update(id="future", first_required_release="v0.5")
    registry["scenarios"].append(future)
    obligation = parsed["docs/status/release-test-obligations.json"]["obligations"][0]
    obligation["scenario_ids"] = ["future", "left"] if future_first else ["left", "future"]
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not graph["unresolved_declarations"]
    assert len(graph["execution_units"]) == 21


def test_catalog_retirement_cannot_drop_a_current_obligation_for_a_future_replacement() -> None:
    parsed, _ = _catalog_unit_fixture()
    obligations = parsed["docs/status/release-test-obligations.json"]["obligations"]
    successor = copy.deepcopy(obligations[0])
    successor.update(id="MP2-007.OBL.FUTURE", first_required_release="v0.5")
    obligations.append(successor)
    obligations[0].update(
        lifecycle="retired_with_reviewed_supersession",
        superseded_by=[successor["id"]],
        supersession_authority=[{"synthetic": True}],
    )
    with pytest.raises(release.ReleaseControlError, match="no current replacement"):
        release._release_catalog_graph(*_catalog_redeclare(parsed))


@pytest.mark.parametrize("mask", range(1, 32))
def test_catalog_empty_unresolved_mappings_remain_current_blockers(mask: int) -> None:
    parsed, _ = _catalog_unit_fixture()
    row = parsed["docs/status/release-test-obligations.json"]["obligations"][0]
    fields = ("criterion_ids", "family_ids", "environment_ids", "profile_ids", "scenario_ids")
    selected = [field for bit, field in enumerate(fields) if mask & (1 << bit)]
    row["implementation"] = {
        "state": "UNRESOLVED",
        "reason": "Original authority does not bind these mappings",
    }
    for field in selected:
        row[field] = []
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not any(unit["scenario_id"] == "leaf" for unit in graph["execution_units"])
    for slot in graph["release_slots"]:
        causes = slot["expansions"]["qualification"][0]["unresolved_declarations"]
        assert all(
            any(
                cause["stable_id"] == row["id"] and cause["field_pointer"].endswith("/" + field)
                for cause in causes
            )
            for field in selected
        )
    assert not any(
        reason["obligation_id"] == row["id"]
        for unit in graph["execution_units"]
        for reason in unit["coverage_reasons"]
    )


def test_catalog_empty_mappings_cannot_hide_current_bom_applicability() -> None:
    parsed, _ = _catalog_unit_fixture()
    row = parsed["docs/status/release-test-obligations.json"]["obligations"][0]
    row["implementation"] = {"state": "UNRESOLVED", "reason": "Missing retained mapping"}
    for field in ("criterion_ids", "family_ids", "environment_ids", "profile_ids", "scenario_ids"):
        row[field] = []
    row["first_required_release"] = "v0.5"
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not graph["release_slots"][0]["expansions"]["qualification"][0][
        "unresolved_declarations"
    ]
    assert all(
        slot["expansions"]["qualification"][0]["unresolved_declarations"]
        for slot in graph["release_slots"][1:]
    )


def test_catalog_reverse_criterion_mapping_cannot_create_extra_coverage() -> None:
    parsed, _ = _catalog_unit_fixture()
    parsed["docs/status/release-test-obligations.json"]["criterion_requirements"][0]["mapping"][
        "obligation_ids"
    ] = ["MP2-007.OBL.ONE"]
    with pytest.raises(release.ReleaseControlError, match="not reciprocal"):
        release._release_catalog_graph(*_catalog_redeclare(parsed))


def test_catalog_reciprocity_uses_current_reviewed_replacement_identity() -> None:
    parsed, _ = _catalog_unit_fixture()
    obligations = parsed["docs/status/release-test-obligations.json"]["obligations"]
    successor = copy.deepcopy(obligations[0])
    successor["id"] = "MP2-007.OBL.REPLACEMENT"
    obligations.append(successor)
    obligations[0].update(
        lifecycle="retired_with_reviewed_supersession",
        superseded_by=[successor["id"]],
        supersession_authority=[{"synthetic": True}],
    )
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert not graph["unresolved_declarations"]
    leaf = next(unit for unit in graph["execution_units"] if unit["scenario_id"] == "leaf")
    assert leaf["obligation_ids"] == ["MP2-007.OBL.REPLACEMENT", "MP2-007.OBL.TWO"]


def test_catalog_pruning_shared_unit_marks_every_affected_root_even_with_slot_coverage() -> None:
    parsed, _ = _catalog_unit_fixture()
    registry = parsed["docs/status/release-scenarios.json"]
    healthy = copy.deepcopy(registry["scenarios"][3])
    healthy["id"] = "healthy"
    obligations = parsed["docs/status/release-test-obligations.json"]["obligations"]
    healthy["required_obligations"]["obligation_ids"] = [row["id"] for row in obligations]
    registry["scenarios"].append(healthy)
    for obligation in obligations:
        obligation["scenario_ids"].append("healthy")
    for slot in registry["release_slots"]:
        slot["qualification_scenario_ids"] = ["leaf", "root", "healthy"]
    registry["scenarios"][4]["expansion"]["implementation"] = {
        "state": "UNRESOLVED",
        "reason": "Required prerequisite implementation absent",
    }
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    for slot in graph["release_slots"]:
        early = slot["expansions"]["qualification"][0]
        assert early["root_scenario_id"] == "leaf"
        assert early["leaf_scenario_ids"] == ["leaf"]
        assert early["execution_unit_ids"] == []
        assert any(
            "cannot be materialized" in cause["reason"]
            for cause in early["unresolved_declarations"]
        )
    assert any(unit["scenario_id"] == "healthy" for unit in graph["execution_units"])


def test_catalog_unresolved_criterion_mapping_cannot_be_used_as_coverage_reason() -> None:
    parsed, _ = _catalog_unit_fixture()
    parsed["docs/status/release-test-obligations.json"]["criterion_requirements"][0]["mapping"] = {
        "state": "UNRESOLVED",
        "known_obligation_ids": [],
        "reason": "No original current mapping",
    }
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert graph["execution_units"] == []
    assert all(
        slot["expansions"]["qualification"][0]["unresolved_declarations"]
        for slot in graph["release_slots"]
    )


@pytest.mark.parametrize("field", ["covers_stages", "environment_pairs"])
@pytest.mark.parametrize("identity", ["root", "leaf"])
def test_catalog_empty_scenario_mapping_is_visible_and_prunes_units(
    field: str, identity: str
) -> None:
    parsed, _ = _catalog_unit_fixture()
    scenario = next(
        r for r in parsed["docs/status/release-scenarios.json"]["scenarios"] if r["id"] == identity
    )
    scenario[field] = []
    scenario["required_obligations"] = {
        "state": "UNRESOLVED",
        "reason": "Original mapping unavailable",
        "known_obligation_ids": [],
    }
    if scenario["expansion"]["kind"] == "leaf":
        scenario["expansion"]["implementation"] = {
            "state": "UNRESOLVED",
            "reason": "No approved recipe",
        }
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    for slot in graph["release_slots"]:
        trace = slot["expansions"]["qualification"][0]
        assert not trace["execution_unit_ids"]
        assert any(
            r["stable_id"] == identity and r["field_pointer"].endswith("/" + field)
            for r in trace["unresolved_declarations"]
        )


@pytest.mark.parametrize("field", ["covers_stages", "environment_pairs"])
@pytest.mark.parametrize("coverage_unresolved", [True, False])
def test_catalog_configured_leaf_cannot_use_an_empty_mapping(
    field: str, coverage_unresolved: bool
) -> None:
    parsed, _ = _catalog_unit_fixture()
    scenario = parsed["docs/status/release-scenarios.json"]["scenarios"][3]
    scenario[field] = []
    if coverage_unresolved:
        scenario["required_obligations"] = {
            "state": "UNRESOLVED",
            "reason": "Original mapping unavailable",
            "known_obligation_ids": [],
        }
    with pytest.raises(release.ReleaseControlError, match="configured scenario has an empty"):
        release._release_catalog_graph(*_catalog_redeclare(parsed))


@pytest.mark.parametrize("first", ["v0.4", "v0.5"])
def test_catalog_required_environment_floor_precedes_missing_profile_filter(first: str) -> None:
    parsed, _ = _catalog_unit_fixture()
    missing = {
        "id": "macos-py313",
        "profile_id": None,
        "declaration": "REQUIRED",
        "first_required_release": first,
        "execution": {"state": "UNRESOLVED", "reason": "Original image/profile not bound"},
        "platform": {"os_release": None, "architecture": None},
        "runtime": {
            "implementation": "CPython",
            "lock_source": None,
            "dependency_extras": [],
            "dependency_groups": [],
            "toolchain_sources": [],
        },
    }
    parsed["docs/status/supported-environments.json"]["environments"].append(missing)
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    fields = [
        "profile_id",
        "platform/os_release",
        "platform/architecture",
        "runtime/lock_source",
        "runtime/dependency_groups",
        "runtime/toolchain_sources",
        "execution",
    ]
    for slot in graph["release_slots"]:
        causes = slot["expansions"]["qualification"][0]["unresolved_declarations"]
        relevant = [r for r in causes if r["stable_id"] == missing["id"]]
        if slot["milestone"] == "v0.4" and first == "v0.5":
            assert not relevant
        else:
            assert all(
                any(r["field_pointer"].endswith("/" + field) for r in relevant) for field in fields
            )
            assert not any(r["field_pointer"].endswith("/dependency_extras") for r in relevant)


def test_catalog_historical_environment_is_retained_without_current_support_promotion() -> None:
    parsed, _ = _catalog_unit_fixture()
    old = {
        "id": "historical-windows",
        "profile_id": "original-profile",
        "declaration": "HISTORICAL_PROPOSAL",
        "first_required_release": None,
        "execution": {"state": "UNRESOLVED", "reason": "Historical proposal, no current policy"},
    }
    parsed["docs/status/supported-environments.json"]["environments"].append(old)
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert any(r["stable_id"] == old["id"] for r in graph["unresolved_declarations"])
    assert not any(unit["environment_id"] == old["id"] for unit in graph["execution_units"])
    assert all(
        not trace["unresolved_declarations"]
        for slot in graph["release_slots"]
        for trace in slot["expansions"]["qualification"]
    )


def test_catalog_configured_required_environment_needs_a_real_qualification_unit() -> None:
    parsed, _ = _catalog_unit_fixture()
    extra = copy.deepcopy(parsed["docs/status/supported-environments.json"]["environments"][0])
    extra.update(id="macos", declaration="REQUIRED")
    parsed["docs/status/supported-environments.json"]["environments"].append(extra)
    graph = release._release_catalog_graph(*_catalog_redeclare(parsed))
    assert all(
        any(
            r["stable_id"] == "macos" and "no configured qualification unit" in r["reason"]
            for r in slot["expansions"]["qualification"][0]["unresolved_declarations"]
        )
        for slot in graph["release_slots"]
    )


def _configuration_fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], release._ReleaseCapturedFiles, dict[str, Any]]:
    import hashlib

    raw = b"version = 1\n"
    identity = {
        "repository": "Miko997/metriplane",
        "path": "uv.lock",
        "git_mode": "100644",
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
        ).hexdigest(),
        "bytes": len(raw),
        "sha256": release.sha256_bytes(raw),
    }
    reference = {
        "binding": "candidate_source_blob",
        **{k: identity[k] for k in ["repository", "path", "git_mode", "git_blob"]},
        "source_bytes": {
            "path": "configuration/uv.lock",
            "bytes": len(raw),
            "sha256": identity["sha256"],
        },
    }
    (tmp_path / "configuration").mkdir()
    (tmp_path / "configuration/uv.lock").write_bytes(raw)
    (tmp_path / "registry.json").write_bytes(
        release.canonical_json({"environments": [{"runtime": {"lock_source": reference}}]})
    )
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("registry.json", "environment-registry"),
            ("configuration/uv.lock", "configuration-source"),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"environment-registry", "configuration-source"}),
    )
    return reference, captured, {"uv.lock": identity}


def _configuration_arguments(
    tmp_path: Path, captured: release._ReleaseCapturedFiles, expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "containing_path": tmp_path / "registry.json",
        "containing_kind": "environment-registry",
        "field": ("environments", 0, "runtime", "lock_source"),
        "captured": captured,
        "expected_sources": expected,
    }


def test_configuration_original_raw_field_is_bound_to_independent_source_identity(
    tmp_path: Path,
) -> None:
    reference, captured, expected = _configuration_fixture(tmp_path)
    assert (
        release._release_configuration_source(
            reference, **_configuration_arguments(tmp_path, captured, expected)
        )
        == b"version = 1\n"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("git_blob", "1" * 40),
        ("git_mode", "100755"),
        ("repository", "caller/other"),
        ("path", "pyproject.toml"),
        ("binding", "git_binding"),
    ],
)
def test_configuration_reference_cannot_replace_an_independently_expected_source(
    tmp_path: Path, field: str, value: str
) -> None:
    reference, captured, expected = _configuration_fixture(tmp_path)
    reference[field] = value
    with pytest.raises(release.ReleaseControlError):
        release._release_configuration_source(
            reference, **_configuration_arguments(tmp_path, captured, expected)
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("git_blob", "2" * 40),
        ("git_mode", "120000"),
        ("bytes", True),
        ("bytes", 1.0),
        ("bytes", 1),
        ("sha256", "3" * 64),
        ("path", "pyproject.toml"),
        ("repository", "caller/other"),
    ],
)
def test_configuration_source_replays_expected_mode_blob_raw_size_and_digest(
    tmp_path: Path, field: str, value: object
) -> None:
    reference, captured, expected = _configuration_fixture(tmp_path)
    expected["uv.lock"][field] = value
    with pytest.raises(release.ReleaseControlError):
        release._release_configuration_source(
            reference, **_configuration_arguments(tmp_path, captured, expected)
        )


@pytest.mark.parametrize(
    "field",
    [
        ("environments", 0, "authority", 0),
        ("environments", 0, "runtime", "toolchain_sources", 0),
        ("environments", True, "runtime", "lock_source"),
        ("environments", 0, "runtime", "lock_source", 0),
        ("environments", 0, "unknown", 0),
    ],
)
def test_configuration_reference_has_a_closed_native_field_role(
    tmp_path: Path, field: tuple[object, ...]
) -> None:
    reference, captured, expected = _configuration_fixture(tmp_path)
    arguments = _configuration_arguments(tmp_path, captured, expected)
    arguments["field"] = field
    with pytest.raises(release.ReleaseControlError):
        release._release_configuration_source(reference, **arguments)


def test_configuration_self_consistent_substitution_still_needs_independent_expected_source(
    tmp_path: Path,
) -> None:
    import hashlib

    reference, _, expected = _configuration_fixture(tmp_path)
    raw = b"version = 2\n"
    reference["git_blob"] = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
    ).hexdigest()
    reference["source_bytes"].update(bytes=len(raw), sha256=release.sha256_bytes(raw))
    (tmp_path / "configuration/uv.lock").write_bytes(raw)
    (tmp_path / "registry.json").write_bytes(
        release.canonical_json({"environments": [{"runtime": {"lock_source": reference}}]})
    )
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("registry.json", "environment-registry"),
            ("configuration/uv.lock", "configuration-source"),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"environment-registry", "configuration-source"}),
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_configuration_source(
            reference, **_configuration_arguments(tmp_path, captured, expected)
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"jobs: {}\njobs: {}\n",
        b"jobs: &jobs {}\nother: *jobs\n",
        b"jobs: !!python/object:unknown {}\n",
        b"jobs: {<<: {test: {}}}\n",
        b"[]\n",
        b"jobs: [",
        b"",
    ],
)
def test_configuration_workflow_rejects_ambiguous_or_unsafe_yaml(raw: bytes) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_workflow_declaration(raw)


def _current_configuration_bytes() -> dict[str, bytes]:
    root = Path(__file__).resolve().parents[1]
    return {
        name: (root / name).read_bytes()
        for name in (".github/workflows/ci.yml", "pyproject.toml", "uv.lock")
    }


def test_current_environment_floor_replays_all_four_original_ci_cells() -> None:
    rows = release._release_current_environment_floor(_current_configuration_bytes())
    assert {(r["os_family"], r["python_minor"]) for r in rows} == {
        ("linux", "3.12"),
        ("linux", "3.13"),
        ("macos", "3.12"),
        ("macos", "3.13"),
    }
    assert len(rows) == 4
    assert all(
        "architecture" not in row and "profile_id" not in row and "os_release" not in row
        for row in rows
    )


@pytest.mark.parametrize(
    "before,after",
    [
        (b"runs-on: macos-latest", b"runs-on: macos-15"),
        (b'python-version: ["3.12", "3.13"]', b'python-version: ["3.12"]'),
        (b"shard-index: [0, 1, 2, 3]", b"shard-index: [0, 1, 2]"),
        (b"  linux-python313:", b"  other-job:"),
        (b"--group dev", b"--group unknown"),
        (b"--shard-count 4", b"--shard-count 3"),
        (b'python-version: "3.13"', b'python-version: "3.14"'),
    ],
)
def test_current_environment_floor_rejects_altered_job_minor_runner_or_recipe(
    before: bytes, after: bytes
) -> None:
    config = _current_configuration_bytes()
    assert before in config[".github/workflows/ci.yml"]
    config[".github/workflows/ci.yml"] = config[".github/workflows/ci.yml"].replace(before, after)
    with pytest.raises(release.ReleaseControlError):
        release._release_current_environment_floor(config)


def _migrated_floor_fixture(
    tmp_path: Path, mutate: Any = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    import hashlib

    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "docs/status/supported-environments.json").read_bytes())
    if mutate is not None:
        mutate(registry)
    expected = {}
    declared = [("registry.json", "environment-registry")]
    for name, raw in _current_configuration_bytes().items():
        destination = tmp_path / "authority/configuration" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        declared.append((destination.relative_to(tmp_path).as_posix(), "configuration-source"))
        expected[name] = {
            "repository": "Miko997/metriplane",
            "path": name,
            "git_mode": "100644",
            "git_blob": hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
            ).hexdigest(),
            "bytes": len(raw),
            "sha256": release.sha256_bytes(raw),
        }
    (tmp_path / "registry.json").write_bytes(release.canonical_json(registry))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        declared,
        forbidden=[],
        allowed_kinds=frozenset({"environment-registry", "configuration-source"}),
    )
    return registry, {
        "containing_path": tmp_path / "registry.json",
        "captured": captured,
        "expected_sources": expected,
    }


def test_migrated_environment_floor_preserves_current_source_requirements(tmp_path: Path) -> None:
    registry, arguments = _migrated_floor_fixture(tmp_path)
    rows = release._release_environment_floor_projection(registry, **arguments)
    assert len(rows) == 4
    assert {row["id"] for row in rows} == {
        r["id"] for r in registry["environments"] if r["declaration"] == "REQUIRED"
    }
    assert all(r["execution"]["state"] == "UNRESOLVED" for r in registry["environments"])


@pytest.mark.parametrize(
    "mutation",
    [
        "drop",
        "rename",
        "demote",
        "defer",
        "minor",
        "os",
        "labels",
        "groups",
        "extras",
        "implementation",
        "lock",
        "toolchain",
    ],
)
def test_migrated_floor_rejects_omitted_or_inconsistent_original_cell(
    tmp_path: Path, mutation: str
) -> None:
    def mutate(registry: dict[str, Any]) -> None:
        row = next(r for r in registry["environments"] if r["id"] == "current-ci-macos-py313")
        if mutation == "drop":
            registry["environments"].remove(row)
        elif mutation == "rename":
            row["id"] = "unreviewed-new-id"
        elif mutation == "demote":
            row["declaration"] = "HISTORICAL_PROPOSAL"
        elif mutation == "defer":
            row["first_required_release"] = "v0.5"
        elif mutation in {"minor", "groups", "extras", "implementation"}:
            key, value = {
                "minor": ("python_minor", "3.12"),
                "groups": ("dependency_groups", []),
                "extras": ("dependency_extras", ["gpu"]),
                "implementation": ("implementation", None),
            }[mutation]
            row["runtime"][key] = value
        elif mutation in {"os", "labels"}:
            row["platform"]["os_family" if mutation == "os" else "runner_labels"] = (
                "windows" if mutation == "os" else ["macos-15"]
            )
        elif mutation == "lock":
            row["runtime"]["lock_source"] = None
        elif mutation == "toolchain":
            row["runtime"]["toolchain_sources"] = []

    registry, arguments = _migrated_floor_fixture(tmp_path, mutate)
    with pytest.raises(release.ReleaseControlError):
        release._release_environment_floor_projection(registry, **arguments)


def test_complete_migrated_catalog_keeps_all_unfinished_acceptance_work_blocking() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = {
        name: (root / name).read_bytes() for name in release._RELEASE_EXECUTION_REGISTRIES.values()
    }
    parsed, declarations = release._release_catalog_declarations(raw)
    graph = release._release_catalog_graph(parsed, declarations)
    assert not graph["execution_units"]
    assert len(graph["release_slots"]) == 7
    for slot in graph["release_slots"]:
        assert all(
            trace["unresolved_declarations"]
            for phase in slot["expansions"].values()
            for trace in phase
        )
        qualification = slot["expansions"]["qualification"]
        assert all(
            any(
                r["stable_id"] == "current-ci-macos-py313" for r in trace["unresolved_declarations"]
            )
            for trace in qualification
        )
    assert len(declarations["scenarios"]) == 66
    assert len(declarations["obligations"]) == 37
    assert len(declarations["criteria"]) == 280


def _catalog_data_fixture(*, complete: bool = False) -> tuple[dict[str, bytes], dict[str, Any]]:
    if complete:
        root = Path(__file__).resolve().parents[1]
        raw = {
            name: (root / name).read_bytes()
            for name in release._RELEASE_EXECUTION_REGISTRIES.values()
        }
    else:
        # Small configured graph for repeated semantic countermodels. The full
        # cardinality/schema projection is exercised separately exactly once.
        parsed, _ = _catalog_unit_fixture()
        raw = {name: release.canonical_json(value) for name, value in parsed.items()}
    return raw, {
        "expected_registry_digests": {
            name: release.sha256_bytes(value) for name, value in raw.items()
        },
        "run_id": "synthetic-catalog-run",
        "producer_intent_digest": "a" * 64,
    }


def test_scenario_catalog_payload_preserves_all_original_work_and_acyclic_identity() -> None:
    raw, arguments = _catalog_data_fixture(complete=True)
    original = copy.deepcopy(raw)
    data = release._release_scenario_catalog_data(raw, **arguments)
    assert raw == original
    assert data["catalog_digest"] == release.sha256_json(
        {k: v for k, v in data.items() if k != "catalog_digest"}
    )
    assert len(data["declarations"]["criteria"]) == 280
    assert len(data["declarations"]["obligations"]) == 37
    assert len(data["declarations"]["scenarios"]) == 66
    assert [slot["milestone"] for slot in data["release_slots"]] == list(release.MILESTONES)
    assert data["execution_units"] == [] and data["unresolved_declarations"]
    assert "gate_input_digest" not in data and "terminal_digest" not in data


def test_scenario_catalog_payload_replays_configured_graph_deterministically() -> None:
    raw, arguments = _catalog_data_fixture()
    data = release._release_scenario_catalog_data(raw, **arguments)
    assert len(data["execution_units"]) == 21
    assert data["unresolved_declarations"] == []
    record = release.make_record(
        "release-scenario-catalog",
        data,
        invocation_id="synthetic-catalog-control",
        sequence=1,
        synthetic=True,
    )
    assert (
        release._release_scenario_catalog_replay(record, raw, synthetic=True, **arguments) == data
    )
    assert (
        release._release_scenario_catalog_data(dict(reversed(list(raw.items()))), **arguments)
        == data
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "omit-criterion",
        "omit-slot",
        "omit-unresolved",
        "extra-declaration",
        "pointer",
        "registry",
        "run",
        "producer",
        "extra-self-field",
        "self-digest",
        "status",
        "mode",
    ],
)
def test_scenario_catalog_payload_replay_rejects_consistent_rewrites(mutation: str) -> None:
    raw, arguments = _catalog_data_fixture()
    data = release._release_scenario_catalog_data(raw, **arguments)
    if mutation == "omit-criterion":
        data["declarations"]["criteria"].pop()
    elif mutation == "omit-slot":
        data["release_slots"].pop()
    elif mutation == "omit-unresolved":
        data["unresolved_declarations"] = [{"caller": "unapproved"}]
    elif mutation == "extra-declaration":
        data["declarations"]["executors"].append({"caller": "unapproved"})
    elif mutation == "pointer":
        data["declarations"]["scenarios"][0]["source"]["json_pointer"] = "/scenarios/999"
    elif mutation == "registry":
        data["scenario_registry_digest"] = "f" * 64
    elif mutation == "run":
        data["run_id"] = "different-run"
    elif mutation == "producer":
        data["producer_intent_digest"] = "f" * 64
    elif mutation == "extra-self-field":
        data["gate_input_digest"] = "f" * 64
    data["catalog_digest"] = release.sha256_json(
        {k: v for k, v in data.items() if k != "catalog_digest"}
    )
    if mutation == "self-digest":
        data["catalog_digest"] = "f" * 64
    record = release.make_record(
        "release-scenario-catalog",
        data,
        invocation_id="synthetic-catalog-control",
        sequence=1,
        synthetic=mutation != "mode",
        status="FAIL" if mutation == "status" else "PASS",
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_scenario_catalog_replay(record, raw, synthetic=True, **arguments)


@pytest.mark.parametrize(
    "mutation", ["missing-raw", "extra-raw", "missing-binding", "wrong-binding"]
)
def test_scenario_catalog_payload_checks_original_bindings_before_parse(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    raw, arguments = _catalog_data_fixture()
    first = next(iter(raw))
    if mutation == "missing-raw":
        raw.pop(first)
    elif mutation == "extra-raw":
        raw["extra.json"] = b"{}"
    elif mutation == "missing-binding":
        arguments["expected_registry_digests"].pop(first)
    else:
        arguments["expected_registry_digests"][first] = "0" * 64

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("unbound catalog original was parsed")

    monkeypatch.setattr(release, "_source_json", forbidden)
    with pytest.raises(release.ReleaseControlError):
        release._release_scenario_catalog_data(raw, **arguments)


def test_environment_projection_cannot_attribute_caller_changed_profile_to_original(
    tmp_path: Path,
) -> None:
    registry, arguments = _migrated_floor_fixture(tmp_path)
    row = next(r for r in registry["environments"] if r["id"] == "current-ci-macos-py313")
    row["profile_id"] = "unapproved-caller-profile"
    with pytest.raises(release.ReleaseControlError, match="captured original registry"):
        release._release_environment_floor_projection(registry, **arguments)


def test_configuration_field_cannot_borrow_an_unrelated_captured_owner(tmp_path: Path) -> None:
    reference, _, expected = _configuration_fixture(tmp_path)
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [("registry.json", "unrelated-record"), ("configuration/uv.lock", "configuration-source")],
        forbidden=[],
        allowed_kinds=frozenset({"unrelated-record", "configuration-source"}),
    )
    arguments = _configuration_arguments(tmp_path, captured, expected)
    arguments["containing_kind"] = "unrelated-record"
    with pytest.raises(release.ReleaseControlError, match="exact environment registry owner"):
        release._release_configuration_source(reference, **arguments)


def test_configuration_yaml_parser_depth_failure_is_a_closed_validation_error() -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_workflow_declaration(b"jobs: " + b"[" * 600 + b"0" + b"]" * 600)


@pytest.mark.parametrize("path", [None, [], {}, 1])
def test_configuration_source_rejects_non_string_path_as_validation_error(
    tmp_path: Path, path: object
) -> None:
    reference, captured, expected = _configuration_fixture(tmp_path)
    reference["path"] = path
    with pytest.raises(release.ReleaseControlError):
        release._release_configuration_source(
            reference, **_configuration_arguments(tmp_path, captured, expected)
        )


def test_original_prerequisite_contract_table_matches_all_closed_schema_variants() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads(
        (root / "schemas/metriplane.release-gate-input.v1.schema.json").read_bytes()
    )
    observed = {}
    for variant in schema["$defs"]["prerequisite_proof"]["oneOf"]:
        fields = variant["properties"]
        tool = fields["producer"]["const"]
        assert fields["stage"]["const"] == release._invocation_stage(tool)
        companion = fields["companion_validations"]["items"]["properties"]["tool"]["const"]
        observed[tool] = (fields["record_type"]["const"], fields["record_kind"]["const"], companion)
    assert observed == release._RELEASE_GATE_PREREQUISITES
    assert len(observed) == 13


@pytest.mark.parametrize(
    "tail", [["--unknown", "x"], ["--out", "other.json"], ["--require-backends"], ["--help"]]
)
def test_original_arguments_reject_duplicate_unknown_and_incomplete_flags(tail: list[str]) -> None:
    argv = [
        "validate_release_evidence_stores.py",
        "--stores",
        "stores.json",
        "--mode",
        "preflight",
        "--scope",
        "scope",
        "--require-backends",
        "all",
        "--out",
        "preflight.json",
        "--invocation-dir",
        "invocations/validate-release-evidence-stores/001",
    ]
    with pytest.raises(release.ReleaseControlError):
        release._release_original_arguments(argv[0], argv + tail)


def test_original_arguments_preserve_exact_forms_and_inline_path_spelling() -> None:
    argv = [
        "validate_linear_release_snapshot.py",
        "--record=snapshot.json",
        "--registry",
        "registry.json",
        "--invocation-dir",
        "invocations/validate-linear-release-snapshot/001",
    ]
    parsed = release._release_original_arguments(argv[0], argv)
    assert parsed == {
        "record": "snapshot.json",
        "registry": "registry.json",
        "invocation-dir": "invocations/validate-linear-release-snapshot/001",
    }
    with pytest.raises(release.ReleaseControlError):
        release._release_original_arguments(argv[0], argv + ["--milestone", "v0.4"])


def _synthetic_original_worker_fixture(
    context: release.ReleaseInvocation, outputs: list[dict[str, str]], *, code: int = 0
) -> list[str]:
    """Explicit synthetic common-worker bytes; this is not native backend execution."""
    directory = context.directory
    (directory / "staged").mkdir()
    names = ["worker.pid", "worker-result.json"]
    (directory / "worker.pid").write_bytes(release.canonical_json({"pid": os.getpid()}))
    (directory / "worker-result.json").write_bytes(
        release.canonical_json(
            {
                "schema_version": "metriplane.release-worker-result.v1",
                "exit_code": code,
                "outputs": outputs,
                "producer_intent_digest": release.sha256_json(context.intent),
            }
        )
    )
    for row in outputs:
        path = directory / "staged" / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((context.root / row["path"]).read_bytes())
        names.append("staged/" + row["path"])
    return [(directory / name).relative_to(context.root).as_posix() for name in names]


def _original_journal_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[release.ReleaseInvocation, release._ReleaseCapturedFiles, dict[str, Any]]:
    import shutil

    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    old = tmp_path / "historical"
    old.mkdir()
    stores = old / "inputs/stores.json"
    stores.parent.mkdir()
    stores.write_bytes(b"{}")
    tool = "validate_release_evidence_stores.py"
    output = old / "nested/preflight.json"
    directory = old / "invocations/validate-release-evidence-stores/001"
    argv = [
        "--stores",
        str(stores),
        "--mode",
        "preflight",
        "--scope",
        "synthetic",
        "--require-backends",
        "all",
        "--out",
        str(output),
        "--invocation-dir",
        str(directory),
    ]
    context = release.begin_release_invocation(
        tool,
        argv,
        directory,
        input_paths=[(stores, "application/json")],
        planned_outputs=[(output, "metriplane.release-evidence-store-preflight.v1")],
    )
    record = release.make_record(
        "release-evidence-store-preflight",
        {
            "producer_intent_digest": release.sha256_json(context.intent),
            "invocation_root_locator": "invocations",
        },
        invocation_id=context.intent["invocation_id"],
        sequence=1,
        synthetic=True,
        status="PASS",
    )
    output.parent.mkdir()
    output.write_bytes(release.canonical_json(record))
    (directory / "stdout").write_bytes(b"")
    (directory / "stderr").write_bytes(b"")
    release._complete_invocation(
        context,
        0,
        [
            {
                "path": "nested/preflight.json",
                "schema_id": "metriplane.release-evidence-store-preflight.v1",
                "sha256": release.sha256_json(record),
            }
        ],
    )
    worker_names = _synthetic_original_worker_fixture(
        context,
        [
            {
                "path": "nested/preflight.json",
                "schema_id": "metriplane.release-evidence-store-preflight.v1",
                "sha256": release.sha256_json(record),
            }
        ],
    )
    terminal = json.loads((directory / "invocation.json").read_bytes())
    (directory / "terminal-commit.json").write_bytes(
        release.canonical_json(
            {
                "schema_version": "metriplane.gate-terminal-commit.v1",
                "intent_sha256": release.sha256_json(context.intent),
                "terminal_sha256": release.sha256_json(terminal),
            }
        )
    )
    current = tmp_path / "retained"
    shutil.move(old, current)
    names = [
        "inputs/stores.json",
        "nested/preflight.json",
        "invocations/validate-release-evidence-stores/001/intent.json",
        "invocations/validate-release-evidence-stores/001/invocation.json",
        "invocations/validate-release-evidence-stores/001/stdout",
        "invocations/validate-release-evidence-stores/001/stderr",
        "invocations/validate-release-evidence-stores/001/terminal-commit.json",
        *worker_names,
    ]
    captured = release._ReleaseCapturedFiles.capture(
        current,
        [(name, "prerequisite-original") for name in names],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    actual_directory = current / "invocations/validate-release-evidence-stores/001"
    actual = release._validate_intent_bytes(
        actual_directory,
        captured.read(
            "invocations/validate-release-evidence-stores/001/intent.json",
            kind="prerequisite-original",
        ),
    )
    return actual, captured, record


def test_original_native_journal_replays_after_historical_root_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, captured, record = _original_journal_fixture(tmp_path, monkeypatch)
    old, arguments = release._release_original_invocation_binding(
        context,
        expected_tool="validate_release_evidence_stores.py",
        captured=captured,
        output_plan=[
            {
                "path": "nested/preflight.json",
                "schema_id": "metriplane.release-evidence-store-preflight.v1",
            }
        ],
    )
    assert old == tmp_path / "historical"
    assert not old.exists()
    assert arguments["stores"] == str(old / "inputs/stores.json")
    terminal = release._release_captured_journal_terminal(
        context, captured=captured, require_pass=True
    )
    assert terminal["status"] == "PASS"
    assert terminal["invocation_id"] == record["invocation_id"]
    # This fixture proves original journal mechanics, never native backend authority.


@pytest.mark.parametrize("mutation", ["head", "output", "extra-output", "wrong-tool", "wrong-root"])
def test_original_invocation_rejects_changed_binding_even_with_same_named_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, captured, _ = _original_journal_fixture(tmp_path, monkeypatch)
    intent = copy.deepcopy(context.intent)
    plan = [
        {
            "path": "nested/preflight.json",
            "schema_id": "metriplane.release-evidence-store-preflight.v1",
        }
    ]
    expected_tool = "validate_release_evidence_stores.py"
    if mutation == "head":
        intent["inputs"][0]["sha256"] = "1" * 64
    elif mutation == "output":
        plan[0]["path"] = "preflight.json"
    elif mutation == "extra-output":
        plan.append({"path": "extra", "schema_id": "application/octet-stream"})
    elif mutation == "wrong-tool":
        expected_tool = "capture_release_target_observations.py"
    updated = release.ReleaseInvocation(
        context.directory,
        context.root / "other" if mutation == "wrong-root" else context.root,
        intent,
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_original_invocation_binding(
            updated, expected_tool=expected_tool, captured=captured, output_plan=plan
        )


@pytest.mark.parametrize(
    "member",
    [
        "inputs/stores.json",
        "nested/preflight.json",
        "invocations/validate-release-evidence-stores/001/intent.json",
        "invocations/validate-release-evidence-stores/001/invocation.json",
        "invocations/validate-release-evidence-stores/001/stdout",
        "invocations/validate-release-evidence-stores/001/stderr",
    ],
)
def test_original_journal_rejects_each_mutated_relocated_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    context, captured, _ = _original_journal_fixture(tmp_path, monkeypatch)
    original = captured.root / member
    original.rename(original.with_name(original.name + ".retained-original"))
    original.write_bytes(b"changed original")
    with pytest.raises(release.ReleaseControlError):
        release._release_captured_journal_terminal(context, captured=captured, require_pass=True)


@pytest.mark.parametrize("field", ["inputs", "planned_outputs", "tool_version"])
def test_original_terminal_cannot_borrow_a_caller_changed_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    context, captured, _ = _original_journal_fixture(tmp_path, monkeypatch)
    intent = copy.deepcopy(context.intent)
    intent[field] = "caller-version" if field == "tool_version" else []
    altered = release.ReleaseInvocation(context.directory, context.root, intent)
    with pytest.raises(release.ReleaseControlError, match="captured original intent"):
        release._release_captured_journal_terminal(altered, captured=captured, require_pass=True)


def _prerequisite_bundle_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate: Any = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    from datetime import UTC, datetime

    context, original, record = _original_journal_fixture(tmp_path, monkeypatch)
    files = []
    for name, _, raw, _, _ in original.rows:
        files.append(
            {"path": "retained/" + name, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}
        )
    by_name = {row["path"]: row for row in files}
    bundle = {
        "schema_version": "metriplane.release-prerequisite-proofs.v1",
        "release_context_digest": "a" * 64,
        "captured_original_files": files,
        "proofs": [
            {
                "producer": "validate_release_evidence_stores.py",
                "stage": "validate-release-evidence-stores",
                "record_type": "release-evidence-store-preflight",
                "record_kind": None,
                "record": by_name["retained/nested/preflight.json"],
                "record_digest": release.sha256_json(record),
                "original_run_root": "retained",
                "producer_intent": by_name[
                    "retained/invocations/validate-release-evidence-stores/001/intent.json"
                ],
                "producer_terminal": by_name[
                    "retained/invocations/validate-release-evidence-stores/001/invocation.json"
                ],
                "companion_validations": [],
            }
        ],
    }
    if mutate is not None:
        mutate(bundle)
    (tmp_path / "bundle.json").write_bytes(release.canonical_json(bundle))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("bundle.json", "prerequisite-proofs"),
            *(("retained/" + row[0], "prerequisite-original") for row in original.rows),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-proofs", "prerequisite-original"}),
    )
    return bundle, {
        "bundle_path": tmp_path / "bundle.json",
        "captured": captured,
        "expected_context_digest": "a" * 64,
        "before": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def test_native_prerequisite_origin_replays_closed_original_journal_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch)
    rows = release._release_prerequisite_origin_rows(bundle, **arguments)
    assert len(rows) == 1
    assert rows[0]["producer"] == "validate_release_evidence_stores.py"
    assert rows[0]["record_path"] == "retained/nested/preflight.json"
    assert rows[0]["run_root"] == "retained"
    assert rows[0]["historical_root"] == str(tmp_path / "historical")
    # Native provider/store semantics are deliberately absent in this journal fixture.


@pytest.mark.parametrize(
    "mutation",
    [
        "producer",
        "type",
        "kind",
        "stage",
        "digest",
        "root",
        "extra-companion",
        "duplicate-record",
        "duplicate-file",
        "missing-file",
        "foreign-context",
        "intent-path",
        "terminal-path",
    ],
)
def test_prerequisite_origin_rejects_changed_type_root_or_original_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    def mutate(bundle: dict[str, Any]) -> None:
        row = bundle["proofs"][0]
        if mutation == "producer":
            row["producer"] = "validate_release_source_freeze.py"
        elif mutation == "type":
            row["record_type"] = "release-target-resolution"
        elif mutation == "kind":
            row["record_kind"] = "complete_export"
        elif mutation == "stage":
            row["stage"] = "other"
        elif mutation == "digest":
            row["record_digest"] = "0" * 64
        elif mutation == "root":
            row["original_run_root"] = "retained/nested"
        elif mutation == "extra-companion":
            row["companion_validations"] = [{}]
        elif mutation == "duplicate-record":
            bundle["proofs"].append(copy.deepcopy(row))
        elif mutation == "duplicate-file":
            bundle["captured_original_files"].append(
                copy.deepcopy(bundle["captured_original_files"][0])
            )
        elif mutation == "missing-file":
            bundle["captured_original_files"].pop()
        elif mutation == "foreign-context":
            bundle["release_context_digest"] = "b" * 64
        elif mutation == "intent-path":
            row["producer_intent"] = row["record"]
        elif mutation == "terminal-path":
            row["producer_terminal"] = row["record"]

    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch, mutate)
    with pytest.raises(release.ReleaseControlError):
        release._release_prerequisite_origin_rows(bundle, **arguments)


def test_prerequisite_origin_cannot_borrow_a_caller_modified_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch)
    bundle["proofs"] = []
    with pytest.raises(release.ReleaseControlError, match="captured original"):
        release._release_prerequisite_origin_rows(bundle, **arguments)


def _target_conflict_policy() -> dict[str, Any]:
    raw = release.canonical_json(
        {
            "owner": "MP2-007",
            "schema_version": "metriplane.release-targets.v1",
            "milestones": [
                {
                    "id": name,
                    "predecessor": "v0.3.0" if index == 0 else release.MILESTONES[index - 1],
                    "required_targets": ["github-release", "pypi", "testpypi"],
                    "version_line": name + ".x",
                }
                for index, name in enumerate(release.MILESTONES)
            ],
        }
    )
    return {
        "target_registry_raw": raw,
        "expected_target_registry_digest": release.sha256_bytes(raw),
    }


def _target_conflict_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = [
        {
            "artifacts": [],
            "raw_result_digest": "a" * 64,
            "state": state,
            "target_id": target,
            "version": "0.4.1",
        }
        for target, state in zip(
            ["github-release", "pypi", "testpypi"], ["occupied", "partial", "unused"], strict=True
        )
    ]
    history = [
        {
            "burn_manifest_digest": "b" * 64,
            "index_receipt_digest": "c" * 64,
            "observation_digest": "d" * 64,
            "package_version": "0.4.1",
            "release_tag": "v0.4.1",
            "sequence": 7,
            "target_id": "github-release",
        }
    ]
    return observations, history


@pytest.mark.parametrize(
    "case",
    [
        "mixed",
        "all-new",
        "all-indexed",
        "all-unused",
        "unused-after-burn",
        "historical-post",
        "multiple-versions",
    ],
)
def test_target_conflict_projection_preserves_every_pair_and_original_operation(case: str) -> None:
    observed, history = _target_conflict_fixture()
    versions = ["0.4.1"]
    if case == "all-new":
        history = []
    elif case == "all-indexed":
        history.append({**history[0], "target_id": "pypi"})
    elif case in {"all-unused", "unused-after-burn"}:
        for row in observed:
            row["state"] = "unused"
        if case == "all-unused":
            history = []
    elif case == "historical-post":
        history[0].update(package_version="0.4.0.post0", release_tag="v0.4.0.post0")
    elif case == "multiple-versions":
        versions.append("0.4.2")
        observed.extend([{**row, "version": "0.4.2"} for row in observed])
    original = copy.deepcopy((observed, history))
    result = release._release_target_conflict_projection(
        observed,
        history,
        milestone="v0.4",
        expected_versions=versions,
        expected_operation_order=list(
            dict.fromkeys(row["index_receipt_digest"] for row in history)
        ),
        **_target_conflict_policy(),
    )
    affected = [
        {
            "target_id": row["target_id"],
            "version": row["version"],
            "target_state_digest": release.sha256_json(row),
        }
        for row in observed
        if row["state"] != "unused"
    ]
    affected.sort(key=lambda row: (row["target_id"], row["version"]))
    assert result["affected_targets"] == affected
    assert (observed, history) == original
    if case in {"all-indexed", "all-unused", "unused-after-burn"}:
        assert result["newly_affected_targets"] == []
        assert result["disposition"] == "no_new_burn" and result["indexing_required"] is False
    else:
        assert result["newly_affected_targets"]
        assert result["disposition"] == "new_burn" and result["indexing_required"] is True
    if case == "mixed":
        assert [row["target_id"] for row in result["newly_affected_targets"]] == ["pypi"]
    if case == "unused-after-burn":
        assert history[0]["package_version"] == "0.4.1"  # No index append does not authorize reuse.


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-provider",
        "duplicate-provider",
        "extra-version",
        "unknown",
        "malformed-state",
        "unused-with-artifact",
        "duplicate-artifact",
        "future-expected-digest",
        "readback-size",
        "readback-digest",
        "readback-path",
        "history-duplicate",
        "history-other-milestone",
        "history-bad-target",
        "history-malformed-target",
        "history-bad-sequence",
        "history-conflicting-operation",
        "history-order",
        "history-receipt",
        "current-post",
        "current-alias",
        "missing-version",
        "duplicate-version",
    ],
)
def test_target_conflict_projection_rejects_incomplete_or_ambiguous_input(mutation: str) -> None:
    observed, history = _target_conflict_fixture()
    versions = ["0.4.1"]
    artifact = {
        "expected_digest": None,
        "name": "original.whl",
        "observed_digest": "e" * 64,
        "size": 2,
        "original_read_back": {"path": "assets/original.whl", "bytes": 2, "sha256": "e" * 64},
    }
    if mutation == "missing-provider":
        observed.pop()
    elif mutation == "duplicate-provider":
        observed.append(copy.deepcopy(observed[0]))
    elif mutation == "extra-version":
        observed[0]["version"] = "0.4.2"
    elif mutation in {"unknown", "malformed-state"}:
        observed[0]["state"] = "unknown" if mutation == "unknown" else {}
    elif mutation == "unused-with-artifact":
        observed[2]["artifacts"] = [artifact]
    elif mutation in {
        "duplicate-artifact",
        "future-expected-digest",
        "readback-size",
        "readback-digest",
        "readback-path",
    }:
        observed[0]["artifacts"] = [artifact]
        if mutation == "duplicate-artifact":
            observed[0]["artifacts"].append(copy.deepcopy(artifact))
        elif mutation == "future-expected-digest":
            artifact["expected_digest"] = artifact["observed_digest"]
        elif mutation == "readback-size":
            artifact["original_read_back"]["bytes"] = True
        elif mutation == "readback-digest":
            artifact["original_read_back"]["sha256"] = "f" * 64
        else:
            artifact["original_read_back"]["path"] = "../original.whl"
    elif mutation == "history-duplicate":
        history.append(copy.deepcopy(history[0]))
    elif mutation == "history-other-milestone":
        history[0].update(package_version="0.5.0", release_tag="v0.5.0")
    elif mutation in {"history-bad-target", "history-malformed-target"}:
        history[0]["target_id"] = "unapproved" if mutation == "history-bad-target" else {}
    elif mutation == "history-bad-sequence":
        history[0]["sequence"] = True
    elif mutation == "history-conflicting-operation":
        history.append({**history[0], "target_id": "pypi", "burn_manifest_digest": "f" * 64})
    elif mutation == "history-order":
        history.append({**history[0], "target_id": "pypi", "sequence": 1})
    elif mutation == "history-receipt":
        history[0]["index_receipt_digest"] = "bad"
    elif mutation == "current-post":
        versions = ["0.4.1.post0"]
    elif mutation == "current-alias":
        versions = ["0.4.01"]
    elif mutation == "missing-version":
        versions = []
    else:
        assert mutation == "duplicate-version"
        versions.append(versions[0])
    with pytest.raises(release.ReleaseControlError):
        release._release_target_conflict_projection(
            observed,
            history,
            milestone="v0.4",
            expected_versions=versions,
            expected_operation_order=list(
                dict.fromkeys(row["index_receipt_digest"] for row in history)
            ),
            **_target_conflict_policy(),
        )


@pytest.mark.parametrize("second_sequence", [1, 7, 8])
def test_target_conflict_projection_orders_original_receipts_not_scoped_sequences(
    second_sequence: int,
) -> None:
    observed, history = _target_conflict_fixture()
    history.append(
        {
            **history[0],
            "target_id": "pypi",
            "index_receipt_digest": "e" * 64,
            "burn_manifest_digest": "f" * 64,
            "sequence": second_sequence,
        }
    )
    result = release._release_target_conflict_projection(
        observed,
        history,
        milestone="v0.4",
        expected_versions=["0.4.1"],
        expected_operation_order=["c" * 64, "e" * 64],
        **_target_conflict_policy(),
    )
    assert len(result["affected_targets"]) == 2
    assert result["newly_affected_targets"] == []
    assert result["disposition"] == "no_new_burn"


@pytest.mark.parametrize(
    "mutation",
    [
        "sequence",
        "manifest",
        "observation",
        "missing-order",
        "extra-order",
        "duplicate-order",
        "bad-order-digest",
        "reordered-groups",
        "interleaved-groups",
        "reordered-pairs",
    ],
)
def test_target_conflict_projection_enforces_independent_original_operation_order(
    mutation: str,
) -> None:
    observed, history = _target_conflict_fixture()
    first = copy.deepcopy(history[0])
    history.extend(
        [
            {**first, "target_id": "pypi"},
            {**first, "target_id": "testpypi", "index_receipt_digest": "e" * 64},
        ]
    )
    order = ["c" * 64, "e" * 64]  # Separately held original index order, never rebuilt from rows.
    if mutation == "sequence":
        history[1]["sequence"] = 8
    elif mutation == "manifest":
        history[1]["burn_manifest_digest"] = "f" * 64
    elif mutation == "observation":
        history[1]["observation_digest"] = "f" * 64
    elif mutation == "missing-order":
        order.pop()
    elif mutation == "extra-order":
        order.append("f" * 64)
    elif mutation == "duplicate-order":
        order.append(order[0])
    elif mutation == "bad-order-digest":
        order[0] = "bad"
    elif mutation == "reordered-groups":
        history = [history[2], history[0], history[1]]
    elif mutation == "interleaved-groups":
        history = [history[0], history[2], history[1]]
    else:
        assert mutation == "reordered-pairs"
        history[0], history[1] = history[1], history[0]
    with pytest.raises(release.ReleaseControlError):
        release._release_target_conflict_projection(
            observed,
            history,
            milestone="v0.4",
            expected_versions=["0.4.1"],
            expected_operation_order=order,
            **_target_conflict_policy(),
        )


@pytest.mark.parametrize(
    "mutation",
    ["digest", "owner", "schema", "missing-slot", "slot-order", "targets", "line", "predecessor"],
)
def test_target_registry_projection_rejects_original_policy_drift(mutation: str) -> None:
    arguments = _target_conflict_policy()
    policy = json.loads(arguments["target_registry_raw"])
    if mutation == "digest":
        arguments["expected_target_registry_digest"] = "0" * 64
    else:
        if mutation == "owner":
            policy["owner"] = "MP2-008"
        elif mutation == "schema":
            policy["schema_version"] = "metriplane.release-targets.v2"
        elif mutation == "missing-slot":
            policy["milestones"].pop()
        elif mutation == "slot-order":
            policy["milestones"].reverse()
        elif mutation == "targets":
            policy["milestones"][-1]["required_targets"].pop()
        elif mutation == "line":
            policy["milestones"][-1]["version_line"] = "1.0.x"
        else:
            assert mutation == "predecessor"
            policy["milestones"][-1]["predecessor"] = "v0.3.0"
        raw = release.canonical_json(policy)
        arguments.update(
            target_registry_raw=raw, expected_target_registry_digest=release.sha256_bytes(raw)
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_target_registry_projection(
            arguments["target_registry_raw"],
            expected_digest=arguments["expected_target_registry_digest"],
            milestone="v0.4",
        )


def test_target_conflict_projection_never_reads_checkout_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("target projection tried to read checkout policy")

    observed, history = _target_conflict_fixture()
    arguments = _target_conflict_policy()
    monkeypatch.setattr(release, "_required_release_targets", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    result = release._release_target_conflict_projection(
        observed,
        history,
        milestone="v0.4",
        expected_versions=["0.4.1"],
        expected_operation_order=["c" * 64],
        **arguments,
    )
    assert [row["target_id"] for row in result["newly_affected_targets"]] == ["pypi"]


def _target_selection_policy(*, exact: bool) -> dict[str, str]:
    return {
        "resolution_mode": "owner_approved_exact_target"
        if exact
        else "next_unused_same_milestone_patch",
        "conflict_disposition": "BLOCKED_REQUIRES_NEW_OWNER_RELEASE_IDENTITY"
        if exact
        else "DURABLE_BURN_THEN_SAME_MILESTONE_PATCH",
        "initial_normalized_package_version": "0.4.1",
        "initial_release_tag": "v0.4.1",
    }


@pytest.mark.parametrize(
    "case", ["empty", "new", "indexed", "provider-now-absent", "historical-only"]
)
def test_target_selection_exact_identity_preserves_permanent_burn_exclusion(case: str) -> None:
    observed, history = _target_conflict_fixture()
    if case in {"empty", "new"}:
        history = []
    if case in {"empty", "provider-now-absent", "historical-only"}:
        for row in observed:
            row["state"] = "unused"
    if case == "indexed":
        history.append({**history[0], "target_id": "pypi"})
    if case == "historical-only":
        history[0].update(package_version="0.4.0.post0", release_tag="v0.4.0.post0")
    result = release._release_target_selection_projection(
        observed,
        history,
        target_policy=_target_selection_policy(exact=True),
        milestone="v0.4",
        expected_versions=["0.4.1"],
        expected_operation_order=[] if not history else ["c" * 64],
        **_target_conflict_policy(),
    )
    assert result["selected_package_version"] == result["selected_release_tag"] == "v0.4.1"
    assert result["target_usable"] is (case in {"empty", "historical-only"})
    assert result["indexing_required"] is (case == "new")
    assert result["prior_burn_digests"] == (["b" * 64] if history else [])


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "gap",
        "reorder",
        "before-initial",
        "unknown",
        "no-unused",
        "after-unused",
        "exact-search",
    ],
)
def test_target_selection_patch_requires_complete_finite_original_search(
    mutation: str | None,
) -> None:
    observed, history = _target_conflict_fixture()
    versions = ["0.4.1", "0.4.2"]
    observed.extend([{**row, "version": "0.4.2", "state": "unused"} for row in observed])
    if mutation == "gap":
        versions[-1] = "0.4.3"
        for row in observed[3:]:
            row["version"] = "0.4.3"
    elif mutation == "reorder":
        versions.reverse()
    elif mutation == "before-initial":
        versions[0] = "0.4.0"
        for row in observed[:3]:
            row["version"] = "0.4.0"
    elif mutation == "unknown":
        observed[-1]["state"] = "unknown"
    elif mutation == "no-unused":
        observed[-1]["state"] = "partial"
    elif mutation == "after-unused":
        versions.append("0.4.3")
        observed.extend([{**row, "version": "0.4.3", "state": "unused"} for row in observed[:3]])
    arguments = {
        "target_policy": _target_selection_policy(exact=mutation == "exact-search"),
        "milestone": "v0.4",
        "expected_versions": versions,
        "expected_operation_order": ["c" * 64],
        **_target_conflict_policy(),
    }
    if mutation is not None:
        with pytest.raises(release.ReleaseControlError):
            release._release_target_selection_projection(observed, history, **arguments)
    else:
        result = release._release_target_selection_projection(observed, history, **arguments)
        assert result["selected_package_version"] == result["selected_release_tag"] == "v0.4.2"
        assert result["target_usable"] is True and result["indexing_required"] is True
        assert [row["version"] for row in result["affected_targets"]] == ["0.4.1", "0.4.1"]


def _target_control_fixture() -> dict[str, Any]:
    # Complete shape fixtures with synthetic original subjects, not native provider/index proof.
    context, _ = _context_policy_fixture()
    observations, history = _target_conflict_fixture()
    policy = _target_conflict_policy()
    ref = {"path": "original.json", "bytes": 1, "sha256": "a" * 64}
    observation_data = {
        "api_version": "synthetic-native-wire",
        "capture_phase": "prebuild",
        "captured_at": "2026-09-08T20:00:00Z",
        "invocation_root_locator": "invocations",
        "observations": [ref],
        "original_registry": ref,
        "original_release_context": {
            "record_type": "release-context",
            "record_digest": release.sha256_json(context),
            "original_file": ref,
        },
        "producer_intent_digest": "1" * 64,
        "provider": "synthetic-provider-wire",
        "registry_digest": policy["expected_target_registry_digest"],
        "targets": observations,
        "tool": "capture_release_target_observations.py",
    }
    lineage_data = {
        "burns": history,
        "index_backend_id": "attempt-index",
        "index_genesis_digest": "2" * 64,
        "invocation_root_locator": "invocations",
        "milestone": "v0.4",
        "original_genesis": ref,
        "original_index_export": {
            "record_type": "release-attempt-index",
            "record_digest": "3" * 64,
            "original_file": ref,
        },
        "producer_intent_digest": "4" * 64,
        "read_back_complete": True,
        "through_head": "5" * 64,
    }
    observation_data["observation_digest"] = release.sha256_json(observation_data)
    lineage_data["lineage_digest"] = release.sha256_json(lineage_data)
    observation_record = release.make_record(
        "release-target-observations",
        observation_data,
        invocation_id="synthetic-original-observations",
        sequence=1,
        synthetic=True,
    )
    lineage_record = release.make_record(
        "release-burn-lineage",
        lineage_data,
        invocation_id="synthetic-original-lineage",
        sequence=1,
        synthetic=True,
    )
    return {
        "context": context,
        "observations": observation_record,
        "lineage": lineage_record,
        "expected_context_digest": release.sha256_json(context),
        "expected_observations_digest": release.sha256_json(observation_record),
        "expected_lineage_digest": release.sha256_json(lineage_record),
        "expected_versions": ["0.4.1"],
        "expected_operation_order": ["c" * 64],
        "producer_intent_digest": "6" * 64,
        **policy,
    }


@pytest.mark.parametrize("record_type", ["release-target-resolution", "release-target-burn"])
def test_target_control_payload_binds_full_original_subjects_and_every_conflict(
    record_type: str,
) -> None:
    arguments = _target_control_fixture()
    original = copy.deepcopy(arguments)
    data, usable = release._release_target_control_data(record_type, **arguments)
    assert arguments == original
    assert usable is False  # A correctly recorded exact conflict cannot authorize the release.
    assert data["burn_lineage_digest"] == release.sha256_json(arguments["lineage"])
    assert data["producer_intent_digest"] == "6" * 64
    if record_type == "release-target-resolution":
        assert data["resolution_digest"] == release.sha256_json(
            {k: v for k, v in data.items() if k != "resolution_digest"}
        )
        assert data["observations_digest"] == release.sha256_json(arguments["observations"])
        assert data["release_context_digest"] == release.sha256_json(arguments["context"])
        assert data["prior_burn_digests"] == [
            "b" * 64
        ]  # Original evidence-manifest C, not burn_id.
        assert data["burn_target_ids"] == ["github-release", "pypi"]
        assert data["selected_package_version"] == data["selected_release_tag"] == "v0.4.1"
        assert data["requires_new_burn"] is True
    else:
        assert data["burn_id"] == release.sha256_json(
            {k: v for k, v in data.items() if k != "burn_id"}
        )
        assert data["observation_digest"] == release.sha256_json(arguments["observations"])
        assert data["disposition"] == "new_burn" and data["indexing_required"] is True
        assert [row["target_id"] for row in data["affected_targets"]] == ["github-release", "pypi"]
        assert data["resolved_package_version"] == data["resolved_release_tag"] == "v0.4.1"


@pytest.mark.parametrize("subject", ["context", "observations", "lineage"])
@pytest.mark.parametrize("mutation", ["expected-c", "self-c", "mode", "status"])
def test_target_control_payload_rejects_original_subject_rebinding(
    subject: str, mutation: str
) -> None:
    arguments = _target_control_fixture()
    record = arguments[subject]
    if mutation == "expected-c":
        arguments["expected_" + subject + "_digest"] = "0" * 64
    else:
        data = copy.deepcopy(record["data"])
        if mutation == "self-c":
            data[
                {
                    "context": "context_digest",
                    "observations": "observation_digest",
                    "lineage": "lineage_digest",
                }[subject]
            ] = "0" * 64
        record = release.make_record(
            record["record_type"],
            data,
            invocation_id=record["invocation_id"],
            sequence=1,
            synthetic=mutation != "mode",
            status="FAIL" if mutation == "status" else "PASS",
        )
        arguments[subject] = record
        arguments["expected_" + subject + "_digest"] = release.sha256_json(record)
    with pytest.raises(release.ReleaseControlError):
        release._release_target_control_data("release-target-resolution", **arguments)


def _manifest_content_fixture() -> dict[str, Any]:
    data = {
        "candidate_digest": "c" * 64,
        "entries": [
            {
                "path": "inputs/original.json",
                "media_type": "application/json",
                "role": "original-input",
                "size": 0,
                "sha256": release.sha256_bytes(b""),
            }
        ],
        "invocation_journal_digests": ["a" * 64, "b" * 64],
        "phase": "attempt",
        "scope_id": "fixture-attempt",
        "scope_kind": "release-attempt",
        "producer_intent_digest": "d" * 64,
        "invocation_root_locator": "invocations",
    }
    data["manifest_digest"] = release.sha256_json(
        {key: data[key] for key in ("entries", "invocation_journal_digests")}
    )
    return data


@pytest.mark.parametrize("phase", release._MANIFEST_PHASES)
def test_manifest_content_has_one_projection_across_all_existing_phases(phase: str) -> None:
    data = _manifest_content_fixture()
    digest = data["manifest_digest"]
    data["phase"] = phase
    data["producer_intent_digest"] = "e" * 64
    data["candidate_digest"] = None
    assert release._release_evidence_manifest_content(data) == data["entries"]
    assert data["manifest_digest"] == digest  # Phase/producer metadata belongs to payload/full C.


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-self",
        "changed-entry",
        "changed-journal",
        "duplicate-path",
        "unsorted-paths",
        "traversal",
        "absolute",
        "dot",
        "double-slash",
        "backslash",
        "control",
        "empty-path",
        "negative-size",
        "bool-size",
        "entry-extra",
        "entry-digest",
        "no-entries",
        "no-journals",
        "duplicate-journal",
        "unsorted-journals",
        "bad-journal",
        "unknown-phase",
        "missing-producer",
        "bad-producer",
        "bad-locator",
        "extra-field",
        "scope-whitespace",
        "scope-too-long",
    ],
)
def test_manifest_content_rejects_digest_drift_and_ambiguous_inventory(mutation: str) -> None:
    data = _manifest_content_fixture()
    entry = data["entries"][0]
    paths = {
        "traversal": "../original.json",
        "absolute": "/original.json",
        "dot": "./original.json",
        "double-slash": "inputs//original.json",
        "backslash": "inputs\\original.json",
        "control": "inputs/original\n.json",
        "empty-path": "",
    }
    if mutation in paths:
        entry["path"] = paths[mutation]
    elif mutation == "wrong-self":
        data["manifest_digest"] = "0" * 64
    elif mutation == "changed-entry":
        entry["size"] = 1
    elif mutation == "changed-journal":
        data["invocation_journal_digests"][1] = "f" * 64
    elif mutation == "duplicate-path":
        data["entries"].append(copy.deepcopy(entry))
    elif mutation == "unsorted-paths":
        data["entries"].append({**entry, "path": "a.json"})
    elif mutation in {"negative-size", "bool-size"}:
        entry["size"] = -1 if mutation == "negative-size" else False
    elif mutation == "entry-extra":
        entry["authorized"] = True
    elif mutation == "entry-digest":
        entry["sha256"] = "bad"
    elif mutation == "no-entries":
        data["entries"] = []
    elif mutation == "no-journals":
        data["invocation_journal_digests"] = []
    elif mutation == "duplicate-journal":
        data["invocation_journal_digests"].append("b" * 64)
    elif mutation == "unsorted-journals":
        data["invocation_journal_digests"].reverse()
    elif mutation == "bad-journal":
        data["invocation_journal_digests"] = ["bad"]
    elif mutation == "unknown-phase":
        data["phase"] = "pretend-published"
    elif mutation == "missing-producer":
        del data["producer_intent_digest"]
    elif mutation == "bad-producer":
        data["producer_intent_digest"] = "bad"
    elif mutation == "bad-locator":
        data["invocation_root_locator"] = "other-invocations"
    elif mutation == "scope-whitespace":
        data["scope_id"] = "fixture scope"
    elif mutation == "scope-too-long":
        data["scope_kind"] = "a" * 161
    else:
        assert mutation == "extra-field"
        data["retention_approved"] = True
    if mutation not in {"wrong-self", "changed-entry", "changed-journal"}:
        data["manifest_digest"] = release.sha256_json(
            {key: data[key] for key in ("entries", "invocation_journal_digests")}
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_evidence_manifest_content(data)


@pytest.mark.parametrize(
    "mutation", ["none", "false-self", "missing-required", "wrong-scope", "duplicate-required"]
)
def test_attempt_manifest_consumer_recomputes_content_and_preserves_required_subject_closure(
    mutation: str,
) -> None:
    data = _manifest_content_fixture()
    required = {data["entries"][0]["sha256"]}
    if mutation == "false-self":
        data["manifest_digest"] = "0" * 64
    elif mutation == "missing-required":
        required.add("f" * 64)
    elif mutation == "wrong-scope":
        data["scope_id"] = "other-attempt"
    elif mutation == "duplicate-required":
        data["entries"].append({**data["entries"][0], "path": "inputs/second.json"})
        data["manifest_digest"] = release.sha256_json(
            {key: data[key] for key in ("entries", "invocation_journal_digests")}
        )
    record = release.make_record(
        "release-evidence-manifest",
        data,
        invocation_id="fixture-manifest",
        sequence=1,
        synthetic=True,
    )
    kwargs = {
        "attempt": {"candidate_digest": "c" * 64, "attempt_id": "fixture-attempt"},
        "required_raw_digests": required,
        "live": False,
    }
    if mutation == "none":
        release._validate_attempt_evidence_manifest(record, **kwargs)
    else:
        with pytest.raises(release.ReleaseControlError):
            release._validate_attempt_evidence_manifest(record, **kwargs)


def test_original_target_capture_contract_requires_explicit_upstream_context() -> None:
    tool = "capture_release_target_observations.py"
    argv = [
        tool,
        "--targets",
        "inputs/targets.json",
        "--provider-auth-from-approved-environment",
        "--out",
        "observations.json",
        "--invocation-dir",
        "invocations/capture-release-target-observations/001",
    ]
    with pytest.raises(release.ReleaseControlError):
        release._release_original_arguments(tool, argv)
    parsed = release._release_original_arguments(
        tool, [*argv, "--release-context", "inputs/context.json"]
    )
    assert parsed["release-context"] == "inputs/context.json"
    assert parsed["targets"] == "inputs/targets.json"
    assert tool not in release._INVOCATION_STAGES  # Parsing does not implement the native route.


def _companion_control_fixture(
    root: Path, monkeypatch: pytest.MonkeyPatch, case: str, mutation: str = "none"
) -> tuple[release.ReleaseInvocation, release.ReleaseInvocation, release._ReleaseCapturedFiles]:
    """Actual immutable intents; deliberately no native records, terminal or authority claim."""
    names = [
        "registry",
        "targets",
        "protected",
        "policy",
        "context",
        "manifest",
        "input-a",
        "input-b",
        "record",
        "keyring",
        "keyring-copy",
        "genesis",
    ]
    files = {}
    for name in names:
        path = root / (name + ".json")
        path.write_bytes(
            release.canonical_json(
                {"synthetic-control-fixture": "keyring" if name == "keyring-copy" else name}
            )
        )
        files[name] = str(path)
    output = files["record"]
    if case == "linear":
        tool = "capture_linear_release_snapshot.py"
        pa = {"project-id": "fixture-project", "registry": files["registry"]}
        ca = {"record": output, "registry": files["registry"]}
    elif case in {"roles", "roles-trust"}:
        tool = "record_release_role_assignments.py"
        pa = {
            "milestone": "v0.4",
            "run-id": "fixture-run",
            "signed-assignments": files["protected"],
            "policy": files["policy"],
            "release-context": files["context"],
        }
        ca = {
            "record": output,
            "milestone": "v0.4",
            "run-id": "fixture-run",
            "check-conflicts": True,
            "check-freshness": True,
        }
        if case == "roles-trust":
            trust = {
                "provider-attestation-keyring": files["keyring"],
                "provider-attestation-keyring-digest": "a" * 64,
                "authority-policy-digest": "b" * 64,
            }
            pa.update(trust)
            ca.update(trust)
    elif case == "target":
        tool = "resolve_release_target.py"
        pa = {
            "milestone": "v0.4",
            "initial-package-version": "0.4.1",
            "initial-release-tag": "v0.4.1",
            "targets": files["targets"],
            "live-target-observations": files["input-a"],
            "retained-burn-lineage": files["input-b"],
        }
        ca = {"record": output, "targets": files["targets"], "read-back-lineage": True}
    elif case.startswith("retention"):
        tool = "retain_release_evidence.py"
        pa = {"phase": "target-burn", "stores": "fixture-stores"}
        ca = {"receipts": output, "read-back": True}
        if case != "retention-input":
            pa["manifest"] = ca["manifest"] = files["manifest"]
        if case != "retention-manifest":
            pa["input"] = ca["input"] = [files["input-a"], files["input-b"]]
        if case == "retention-journal":
            pa.update(
                {
                    "invocation-root": str(root),
                    "through-stage": "target-burn",
                    "exclude-current-invocation": True,
                }
            )
            ca.update({"invocation-root": str(root), "through-stage": "target-burn"})
    elif case == "index-update":
        tool = "update_release_attempt_index.py"
        pa = {
            "entry-manifest": files["manifest"],
            "entry-receipts": files["input-a"],
            "scope-kind": "release_staging",
            "milestone": "v0.4",
            "run-id": "fixture-run",
            "stage": "target-burn",
            "sequence": "1",
            "release-tag": "v0.4.1",
            "candidate-id-not-resolved": True,
            "index-backend": "fixture-index",
            "expected-head": "fixture-head",
            "operation-id": "fixture-operation",
        }
        ca = {
            "index-backend": "fixture-index",
            "genesis": files["genesis"],
            "through-receipt": output,
            "read-back": True,
        }
    elif case == "index-export":
        tool = "export_release_attempt_index.py"
        pa = {
            "index-backend": "fixture-index",
            "genesis": files["genesis"],
            "through-head": "fixture-head",
            "stores": "fixture-stores",
            "read-back-all": True,
        }
        ca = {
            "record": output,
            "index-backend": "fixture-index",
            "genesis": files["genesis"],
            "read-back": True,
        }
    else:
        assert case in {"manifest", "manifest-conflict"}
        tool = "build_release_evidence_manifest.py"
        pa = {
            "phase": "target-burn",
            "input": [files["input-a"]],
            "invocation-root": str(root),
            "exclude-current-invocation": True,
        }
        ca = {"record": output}
        if case == "manifest-conflict":
            pa["phase"] = "postpublication-conflict"
            pa["candidate-dir"] = str(root)
            pa["no-assurance-round"] = True
            required = "require-lkg-disposition-and-applicable-invalidation-receipt"
            pa[required] = ca[required] = True
    if mutation == "shared-copy":
        flag = "registry" if case == "linear" else "targets" if case == "target" else "manifest"
        copy_path = root / "same-bytes-different-suffix.json"
        copy_path.write_bytes(Path(ca[flag]).read_bytes())
        files["alternate"] = str(copy_path)
        ca[flag] = str(copy_path)
    elif mutation == "later-linear-form":
        ca.update(
            {
                "frozen-snapshot": files["input-a"],
                "milestone": "v0.4",
                "current-decision": "fixture-decision",
                "require-full-release-bom-closed-except-current-decision": True,
                "require-exact-reciprocal-relations": True,
                "require-exact-milestone-assignments": True,
                "require-current-decision-state": "open_running",
            }
        )
    elif mutation == "scope-run":
        ca["run-id"] = "different-run"
    elif mutation == "scope-milestone":
        ca["milestone"] = "v0.5"
    elif mutation == "partial-trust":
        del ca["authority-policy-digest"]
    elif mutation == "different-trust":
        ca["provider-attestation-keyring-digest"] = "f" * 64
    elif mutation == "equal-trust-copy":
        ca["provider-attestation-keyring"] = files["keyring-copy"]
    elif mutation == "changed-trust-copy":
        ca["provider-attestation-keyring"] = files["context"]
    elif mutation == "input-order":
        ca["input"] = list(reversed(ca["input"]))
    elif mutation == "input-duplicate":
        ca["input"] = [*ca["input"], ca["input"][0]]
    elif mutation == "other-retention-form":
        del ca["manifest"]
        ca["input"] = [files["input-a"]]
    elif mutation == "different-through-stage":
        ca["through-stage"] = "index-recovery"
    elif mutation == "different-invocation-root":
        ca["invocation-root"] = str(root / "other-root")
    elif mutation == "different-backend":
        ca["index-backend"] = "different-index"
    elif mutation == "different-genesis":
        ca["genesis"] = files["context"]
    elif mutation == "relative-genesis":
        monkeypatch.chdir(root)
        ca["genesis"] = "genesis.json"
    elif mutation == "missing-lkg-check":
        del ca["require-lkg-disposition-and-applicable-invalidation-receipt"]
    elif mutation == "stronger-lkg-check":
        ca["require-lkg-disposition-and-applicable-invalidation-receipt"] = True
    companion = release._RELEASE_GATE_PREREQUISITES[tool][2]
    assert companion is not None
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")

    def reserve(name: str, arguments: dict[str, Any], producer: bool) -> release.ReleaseInvocation:
        directory = root / "invocations" / release._invocation_stage(name) / "001"
        values = {**arguments, "invocation-dir": str(directory)}
        if producer:
            values["out"] = output
        argv = []
        for flag, value in values.items():
            for item in value if isinstance(value, list) else [value]:
                argv.append("--" + flag)
                if item is not True:
                    argv.append(str(item))
        release._release_original_arguments(name, [name, *argv])
        inputs = []
        for file_name, value in files.items():
            # Explicit fixture controls, not a transitive native authority inventory.
            if mutation == "uncaptured-genesis" and not producer and file_name == "genesis":
                continue
            kind = "application/json"
            if (
                mutation == "shared-type"
                and not producer
                and file_name in {"registry", "targets", "manifest"}
            ):
                kind = "application/octet-stream"
            if mutation == "genesis-type" and not producer and file_name == "genesis":
                kind = "application/octet-stream"
            inputs.append((Path(value), kind))
        return release.begin_release_invocation(
            name,
            argv,
            directory,
            input_paths=inputs,
            planned_outputs=[(Path(output), "application/json")] if producer else [],
        )

    producer_context = reserve(tool, pa, True)
    companion_context = reserve(companion, ca, False)
    if mutation == "genesis-hash":
        intent = copy.deepcopy(companion_context.intent)
        for row in intent["inputs"]:
            if row["path"] == files["genesis"]:
                row["sha256"] = "0" * 64
        intent["invocation_id"] = release._intent_identity(intent)
        intent_path = companion_context.directory / "intent.json"
        intent_path.chmod(0o600)
        intent_path.write_bytes(release.canonical_json(intent))
        companion_context = release.ReleaseInvocation(
            companion_context.directory, companion_context.root, intent
        )
    capture = release._ReleaseCapturedFiles.capture(
        root,
        [
            (Path(value).relative_to(root).as_posix(), "prerequisite-original")
            for value in files.values()
        ]
        + [
            ((ctx.directory / "intent.json").relative_to(root).as_posix(), "prerequisite-original")
            for ctx in [producer_context, companion_context]
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    return producer_context, companion_context, capture


@pytest.mark.parametrize(
    "case",
    [
        "linear",
        "roles",
        "roles-trust",
        "target",
        "manifest",
        "manifest-conflict",
        "retention-manifest",
        "retention-input",
        "retention-journal",
        "index-update",
        "index-export",
    ],
)
def test_original_companion_controls_preserve_all_six_existing_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    producer, companion, captured = _companion_control_fixture(tmp_path, monkeypatch, case)
    release._release_original_companion_bindings(producer, companion, captured=captured)
    assert not (producer.directory / "invocation.json").exists()
    assert not (companion.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    "case,mutation,passes",
    [
        ("linear", "shared-copy", False),
        ("linear", "shared-type", False),
        ("linear", "later-linear-form", False),
        ("roles", "scope-run", False),
        ("roles", "scope-milestone", False),
        ("roles-trust", "partial-trust", False),
        ("roles-trust", "different-trust", False),
        ("roles-trust", "equal-trust-copy", True),
        ("roles-trust", "changed-trust-copy", False),
        ("target", "shared-copy", False),
        ("target", "shared-type", False),
        ("retention-manifest", "shared-copy", False),
        ("retention-manifest", "other-retention-form", False),
        ("retention-input", "input-order", True),
        ("retention-input", "input-duplicate", False),
        ("retention-journal", "different-through-stage", False),
        ("retention-journal", "different-invocation-root", False),
        ("index-update", "different-backend", False),
        ("index-export", "different-backend", False),
        ("index-export", "different-genesis", False),
        ("index-update", "uncaptured-genesis", False),
        ("index-export", "uncaptured-genesis", False),
        ("index-update", "genesis-hash", False),
        ("index-export", "genesis-hash", False),
        ("index-export", "genesis-type", False),
        ("index-export", "relative-genesis", True),
        ("index-update", "relative-genesis", True),
        ("manifest-conflict", "missing-lkg-check", False),
        ("manifest", "stronger-lkg-check", True),
    ],
)
def test_original_companion_controls_reject_changed_contract_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, mutation: str, passes: bool
) -> None:
    producer, companion, captured = _companion_control_fixture(
        tmp_path, monkeypatch, case, mutation
    )
    if passes:
        release._release_original_companion_bindings(producer, companion, captured=captured)
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_original_companion_bindings(producer, companion, captured=captured)


def _companion_bundle_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, alias: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    import shutil
    from datetime import UTC, datetime

    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    old = tmp_path / "historical"
    old.mkdir()
    registry = old / "registry.json"
    registry.write_bytes(b"{}")
    output = old / "snapshot.json"
    producer = "capture_linear_release_snapshot.py"
    directory = old / "invocations/capture-linear-release-snapshot/001"
    argv = [
        "--project-id",
        "synthetic-project",
        "--registry",
        str(registry),
        "--out",
        str(output),
        "--invocation-dir",
        str(directory),
    ]
    producer_context = release.begin_release_invocation(
        producer,
        argv,
        directory,
        input_paths=[(registry, "application/json")],
        planned_outputs=[(output, "metriplane.linear-release-snapshot.v1")],
    )
    record = release.make_record(
        "linear-release-snapshot",
        {
            "producer_intent_digest": release.sha256_json(producer_context.intent),
            "invocation_root_locator": "invocations",
        },
        invocation_id=producer_context.intent["invocation_id"],
        sequence=1,
        synthetic=True,
        status="PASS",
    )
    output.write_bytes(release.canonical_json(record))
    for name in ["stdout", "stderr"]:
        (directory / name).write_bytes(b"")
    release._complete_invocation(
        producer_context,
        0,
        [
            {
                "path": "snapshot.json",
                "schema_id": "metriplane.linear-release-snapshot.v1",
                "sha256": release.sha256_json(record),
            }
        ],
    )
    consumed = old / "other-snapshot.json" if alias else output
    if alias:
        consumed.write_bytes(release.canonical_json(record))
    companion = "validate_linear_release_snapshot.py"
    validation_dir = old / "invocations/validate-linear-release-snapshot/001"
    validation_args = [
        "--record",
        str(consumed),
        "--registry",
        str(registry),
        "--invocation-dir",
        str(validation_dir),
    ]
    validation = release.begin_release_invocation(
        companion,
        validation_args,
        validation_dir,
        input_paths=[
            (consumed, "metriplane.linear-release-snapshot.v1"),
            (registry, "application/json"),
        ],
        planned_outputs=[],
    )
    for name in ["stdout", "stderr"]:
        (validation_dir / name).write_bytes(b"")
    release._complete_invocation(validation, 0, [])
    worker_names = _synthetic_original_worker_fixture(
        producer_context,
        [
            {
                "path": "snapshot.json",
                "schema_id": "metriplane.linear-release-snapshot.v1",
                "sha256": release.sha256_json(record),
            }
        ],
    ) + _synthetic_original_worker_fixture(validation, [])
    retained = tmp_path / "retained"
    shutil.move(old, retained)
    names = [
        "registry.json",
        "snapshot.json",
        *worker_names,
        *(
            f"invocations/{stage}/001/{name}"
            for stage in ["capture-linear-release-snapshot", "validate-linear-release-snapshot"]
            for name in ["intent.json", "invocation.json", "stdout", "stderr"]
        ),
    ]
    if alias:
        names.append("other-snapshot.json")
    refs = {}
    for name in names:
        raw = (retained / name).read_bytes()
        refs[name] = {
            "path": "retained/" + name,
            "bytes": len(raw),
            "sha256": release.sha256_bytes(raw),
        }
    bundle = {
        "schema_version": "metriplane.release-prerequisite-proofs.v1",
        "release_context_digest": "a" * 64,
        "captured_original_files": [refs[name] for name in sorted(refs)],
        "proofs": [
            {
                "producer": producer,
                "stage": "capture-linear-release-snapshot",
                "record_type": "linear-release-snapshot",
                "record_kind": None,
                "record": refs["snapshot.json"],
                "record_digest": release.sha256_json(record),
                "original_run_root": "retained",
                "producer_intent": refs[
                    "invocations/capture-linear-release-snapshot/001/intent.json"
                ],
                "producer_terminal": refs[
                    "invocations/capture-linear-release-snapshot/001/invocation.json"
                ],
                "companion_validations": [
                    {
                        "tool": companion,
                        "stage": "validate-linear-release-snapshot",
                        "intent": refs[
                            "invocations/validate-linear-release-snapshot/001/intent.json"
                        ],
                        "terminal": refs[
                            "invocations/validate-linear-release-snapshot/001/invocation.json"
                        ],
                    }
                ],
            }
        ],
    }
    (tmp_path / "bundle.json").write_bytes(release.canonical_json(bundle))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("bundle.json", "prerequisite-proofs"),
            *(("retained/" + name, "prerequisite-original") for name in names),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-proofs", "prerequisite-original"}),
    )
    return bundle, {
        "bundle_path": tmp_path / "bundle.json",
        "captured": captured,
        "expected_context_digest": "a" * 64,
        "before": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def test_prerequisite_companion_binds_its_original_record_and_control_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arguments = _companion_bundle_fixture(tmp_path, monkeypatch)
    rows = release._release_prerequisite_origin_rows(bundle, **arguments)
    assert len(rows[0]["companions"]) == 1
    assert rows[0]["companions"][0]["tool"] == "validate_linear_release_snapshot.py"


def test_prerequisite_companion_cannot_substitute_identical_record_at_another_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arguments = _companion_bundle_fixture(tmp_path, monkeypatch, alias=True)
    with pytest.raises(release.ReleaseControlError, match="different record path"):
        release._release_prerequisite_origin_rows(bundle, **arguments)


@pytest.mark.parametrize(
    "extra",
    [
        "invocations/validate-release-evidence-stores/001/unlisted.json",
        "invocations/validate-release-evidence-stores/002/intent.json",
        "invocations/other/001/intent.json",
        "invocations/validate-release-evidence-stores/001/workspace/unlisted.json",
    ],
)
def test_prerequisite_origin_rejects_unlisted_journal_before_reading_unknown_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch)
    path = tmp_path / "retained" / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unlisted original")
    with pytest.raises(release.ReleaseControlError, match="unlisted"):
        release._release_prerequisite_origin_rows(bundle, **arguments)


@pytest.mark.parametrize("name", ["staged", "workspace"])
def test_original_journal_allows_only_empty_fixed_scratch_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch)
    path = tmp_path / "retained/invocations/validate-release-evidence-stores/001" / name
    path.mkdir(exist_ok=True)
    assert release._release_prerequisite_origin_rows(bundle, **arguments)


def test_original_journal_never_follows_an_unlisted_scratch_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, arguments = _prerequisite_bundle_fixture(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "retained/invocations/validate-release-evidence-stores/001/workspace").symlink_to(
        outside, target_is_directory=True
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_prerequisite_origin_rows(bundle, **arguments)


def _original_retry_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, incomplete_latest: bool = False
) -> tuple[release.ReleaseInvocation, release._ReleaseCapturedFiles]:
    import shutil

    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    old = tmp_path / "historical"
    old.mkdir()
    stores = old / "stores.json"
    stores.write_bytes(b"{}")
    names = ["stores.json"]
    for sequence in range(1, 5 if incomplete_latest else 4):
        directory = old / f"invocations/validate-release-evidence-stores/{sequence:03d}"
        output = old / f"preflight-{sequence}.json"
        context = release.begin_release_invocation(
            "validate_release_evidence_stores.py",
            [
                "--stores",
                str(stores),
                "--mode",
                "preflight",
                "--scope",
                "synthetic",
                "--require-backends",
                "all",
                "--out",
                str(output),
                "--invocation-dir",
                str(directory),
            ],
            directory,
            input_paths=[(stores, "application/json")],
            planned_outputs=[(output, "metriplane.release-evidence-store-preflight.v1")],
        )
        names.append((directory / "intent.json").relative_to(old).as_posix())
        if sequence in {2, 4}:
            continue
        for name in ["stdout", "stderr"]:
            (directory / name).write_bytes(b"")
            names.append((directory / name).relative_to(old).as_posix())
        outputs = []
        if sequence == 1:
            (directory / "workspace").mkdir()
            (directory / "workspace/partial.bin").write_bytes(b"original failed payload")
            names.extend(_synthetic_original_worker_fixture(context, [], code=1))
            release._retain_partial_files(context)
            names.extend(
                [
                    (directory / name).relative_to(old).as_posix()
                    for name in ["partial-files.json", "workspace/partial.bin"]
                ]
            )
        else:
            output.write_bytes(b"{}")
            names.append(output.name)
            outputs = [
                {
                    "path": output.name,
                    "schema_id": "metriplane.release-evidence-store-preflight.v1",
                    "sha256": release.sha256_bytes(b"{}"),
                }
            ]
        if sequence != 1:
            names.extend(_synthetic_original_worker_fixture(context, outputs))
        release._complete_invocation(context, 1 if sequence == 1 else 0, outputs)
        names.append((directory / "invocation.json").relative_to(old).as_posix())
        if (directory / "terminal-commit.json").exists():
            names.append((directory / "terminal-commit.json").relative_to(old).as_posix())
    current = tmp_path / "retained"
    shutil.move(old, current)
    captured = release._ReleaseCapturedFiles.capture(
        current,
        [(name, "prerequisite-original") for name in names],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    directory = current / "invocations/validate-release-evidence-stores/003"
    actual = release._validate_intent_bytes(
        directory,
        captured.read(
            (directory / "intent.json").relative_to(current).as_posix(),
            kind="prerequisite-original",
        ),
    )
    return actual, captured


def test_original_lineage_preserves_failed_and_interrupted_relocated_predecessors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, captured = _original_retry_fixture(tmp_path, monkeypatch)
    release._release_replay_original_namespace(captured, captured.root)
    rows = release._release_replay_original_lineage(context, captured=captured)
    assert [row["intent"]["sequence"] for row in rows] == [3, 2, 1]
    assert [None if row["terminal"] is None else row["terminal"]["status"] for row in rows] == [
        "PASS",
        None,
        "FAIL",
    ]
    assert rows[1]["disposition"] == "INTERRUPTED_MISSING_TERMINAL"
    assert not (tmp_path / "historical").exists()


def test_original_namespace_rejects_captured_later_incomplete_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, captured = _original_retry_fixture(tmp_path, monkeypatch, incomplete_latest=True)
    assert release._release_replay_original_lineage(context, captured=captured)
    with pytest.raises(release.ReleaseControlError):
        release._release_replay_original_namespace(captured, captured.root)


@pytest.mark.parametrize("sequence", [True, 1.0, 0, -1, "1"])
def test_original_intent_rejects_non_integer_or_wrong_predecessor_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sequence: Any
) -> None:
    context, captured = _original_retry_fixture(tmp_path, monkeypatch)
    directory = context.directory.parent / "002"
    raw = captured.read(
        (directory / "intent.json").relative_to(captured.root).as_posix(),
        kind="prerequisite-original",
    )
    intent = json.loads(raw)
    intent["predecessor"]["sequence"] = sequence
    intent["invocation_id"] = release._intent_identity(intent)
    with pytest.raises(release.ReleaseControlError, match="predecessor"):
        release._validate_intent_bytes(directory, release.canonical_json(intent))


@pytest.mark.parametrize("value", [" ", "\t", "0"])
def test_original_arguments_reject_worker_absent_values(value: str) -> None:
    argv = [
        "record_release_blocker_attempt.py",
        "--sequence",
        value,
        "--stage",
        "gate-instance",
        "--disposition",
        "recoverable",
        "--candidate-identity",
        "candidate.json",
        "--failed-invocation-dir",
        "failure",
        "--out",
        "blocker.json",
        "--invocation-dir",
        "invocations/record-release-blocker-attempt/001",
    ]
    control = ["1" if item == value else item for item in argv]
    assert release._release_original_arguments(control[0], control)["sequence"] == 1
    with pytest.raises(release.ReleaseControlError):
        release._release_original_arguments(argv[0], argv)


@pytest.mark.parametrize("mutation", ["size", "digest", "roots", "missing", "unreadable"])
def test_original_partial_inventory_rejects_false_retained_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, captured = _original_retry_fixture(tmp_path, monkeypatch)
    directory = context.directory.parent / "001"
    original = release._validate_intent_bytes(
        directory,
        captured.read(
            (directory / "intent.json").relative_to(captured.root).as_posix(),
            kind="prerequisite-original",
        ),
    )
    path = directory / "partial-files.json"
    value = json.loads(path.read_bytes())
    if mutation == "size":
        value["files"][0]["size"] += 1
    elif mutation == "digest":
        value["files"][0]["sha256"] = "0" * 64
    elif mutation == "roots":
        value["roots"][1]["kind"] = "absent"
    elif mutation == "missing":
        value["files"] = []
    else:
        value["unreadable"] = ["unknown"]
    path.rename(tmp_path / "retained-original-partial.json")
    path.write_bytes(release.canonical_json(value))
    recaptured = release._ReleaseCapturedFiles.capture(
        captured.root,
        [(row[0], row[1]) for row in captured.rows],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    with pytest.raises(release.ReleaseControlError, match="partial inventory"):
        release._release_captured_partial_inventory(original, captured=recaptured)


@pytest.mark.parametrize("member", ["unowned.bin", "workspace/unowned.bin", "staged/unowned.bin"])
def test_original_namespace_rejects_captured_but_unowned_pass_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    context, captured = _original_retry_fixture(tmp_path, monkeypatch)
    path = context.directory / member
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"captured does not mean owned")
    recaptured = release._ReleaseCapturedFiles.capture(
        captured.root,
        [
            *((row[0], row[1]) for row in captured.rows),
            (path.relative_to(captured.root).as_posix(), "prerequisite-original"),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_replay_original_namespace(recaptured, captured.root)


def test_original_namespace_regular_file_root_is_a_typed_rejection(tmp_path: Path) -> None:
    (tmp_path / "invocations").write_bytes(b"not a directory")
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [("invocations", "prerequisite-original")],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_assert_original_journal_inventory(captured, tmp_path)


def _linear_bom_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Complete-size synthetic planning and normalized rows; no provider authority."""
    from uuid import UUID

    registry, original = _planning_membership_fixture()
    packet = json.loads(original)
    for task in packet["task_registry"]:
        task["linear_issue"] = "SYN-" + str(int(task["linear_issue"].split("-")[1]) + 1)
    for slot in packet["releases"]:
        slot["linear_release_decision_issue"] = "SYN-" + str(
            int(slot["linear_release_decision_issue"].split("-")[1]) + 1
        )
    original = release.canonical_json(packet)
    registry["task_catalog"] = packet["task_registry"]
    registry["release_gate_slots"] = packet["releases"]
    registry["catalog_binding"]["source"].update(
        bytes=len(original), sha256=release.sha256_bytes(original)
    )
    registry["catalog_binding"]["task_registry_sha256"] = release.sha256_json(
        packet["task_registry"]
    )
    registry["catalog_binding"]["release_slots_sha256"] = release.sha256_json(packet["releases"])
    project, external, team = [str(UUID(int=i)) for i in (10001, 10002, 10003)]
    issues, bindings, dependencies = [], [], {}
    for number in range(1, 96):
        task = packet["task_registry"][number - 1] if number <= 93 else None
        identity = {
            "provider": "linear",
            "issue_id": str(UUID(int=number)),
            "issue_identifier": f"SYN-{number}",
            "project_id": external if number == 95 else project,
            "team_id": team,
        }
        row = {
            "identity": identity,
            "title": f"Synthetic task {number}",
            "description": "Complete synthetic work order",
            "project_milestone": None,
            "parent": None,
            "state": {"id": str(UUID(int=20001)), "name": "Done", "type": "completed"},
            "assignee_ids": [],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "archived_at": None,
            "completed_at": "2026-01-02T00:00:00Z",
            "started_at": None,
            "canceled_at": None,
            "blocks": [],
            "blocked_by": [],
            "related_to": [],
            "duplicate_of": None,
            "detail_observation_id": f"synthetic-detail-{number}",
            "index_observation_ids": [],
        }
        issues.append(row)
        bindings.append(
            {
                "issue_identifier": identity["issue_identifier"],
                "identity": identity,
                "catalog_task_id": None if task is None else task["task"],
                "expected_milestone": None,
                "binding_status": "UNRESOLVED",
                "assignment_authority": {
                    "path": "synthetic-authority",
                    "bytes": 0,
                    "sha256": release.sha256_bytes(b""),
                },
            }
        )
        dependencies[identity["issue_identifier"]] = []
    decision, direct = issues[93], issues[94]
    provider_milestone = {
        "id": str(UUID(int=30001)),
        "name": "Synthetic patch milestone",
        "project_id": project,
    }
    decision["project_milestone"] = provider_milestone
    bindings[93]["expected_milestone"] = provider_milestone
    decision["state"] = {"id": str(UUID(int=20002)), "name": "In Progress", "type": "started"}
    # Sticky completed_at is retained; it never classifies this current decision as closed.
    decision["blocked_by"] = [{k: direct["identity"][k] for k in ("issue_id", "issue_identifier")}]
    direct["blocks"] = [{k: decision["identity"][k] for k in ("issue_id", "issue_identifier")}]
    dependencies["SYN-94"] = ["SYN-95"]
    registry["provider_issue_bindings"] = bindings
    registry["release_contexts"] = [
        {
            "context_id": "synthetic-patch",
            "framework_milestone": "v0.4",
            "preserve_original_cumulative_bom": True,
            "decision": decision["identity"],
            "direct_gate_issues": [direct["identity"]],
            "roadmap_catalog_task_id": None,
            "provider_milestone": provider_milestone,
        }
    ]
    issues.sort(key=lambda row: (row["identity"]["issue_identifier"], row["identity"]["issue_id"]))
    return registry, {
        "context_id": "synthetic-patch",
        "issues": issues,
        "original_packet": original,
        "expected_packet_digest": release.sha256_bytes(original),
        "declared_dependencies": dependencies,
    }


def _linear_catalog_dependency_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Independent synthetic declarations; observed graph edges are not their source."""
    registry, bom = _linear_bom_fixture()
    packet = json.loads(bom["original_packet"])
    orders = []
    by_identifier = {row["identity"]["issue_identifier"]: row for row in bom["issues"]}
    for task in packet["task_registry"]:
        task["linear_milestone_id"] = "synthetic-original-planning-milestone"
        dependencies = ["MP2-003", "MP2-000"] if task["task"] == "MP2-007" else []
        orders.append(
            {
                "task_id": task["task"],
                **{
                    key: task[key]
                    for key in (
                        "linear_issue",
                        "role",
                        "first_required_release",
                        "linear_milestone_id",
                    )
                },
                "authoritative_blocked_by": dependencies,
            }
        )
        by_identifier[task["linear_issue"]]["description"] = (
            "Narrative MP2-099 is not a dependency.\n\n"
            "<!-- METRIPLANE_MP2_DEPENDENCIES_V1\n"
            f"Task: {task['task']}\n"
            f"Authoritative blocked by: [{', '.join(dependencies)}]\n-->\n"
        )
    original = release.canonical_json(packet)
    registry["task_catalog"] = packet["task_registry"]
    registry["catalog_binding"]["source"].update(
        bytes=len(original), sha256=release.sha256_bytes(original)
    )
    registry["catalog_binding"]["task_registry_sha256"] = release.sha256_json(
        packet["task_registry"]
    )
    work_orders = release.canonical_json({"tasks": orders})
    return registry, {
        "issues": bom["issues"],
        "original_packet": original,
        "expected_packet_digest": release.sha256_bytes(original),
        "original_work_orders": work_orders,
        "expected_work_orders_digest": release.sha256_bytes(work_orders),
    }


def test_linear_catalog_dependencies_project_original_sets_without_using_observed_edges() -> None:
    registry, arguments = _linear_catalog_dependency_fixture()
    before = copy.deepcopy(arguments)
    result = release._release_linear_catalog_dependencies(registry, **arguments)
    assert len(result) == 93
    assert result["SYN-8"] == ["SYN-1", "SYN-4"]
    assert result["SYN-1"] == []
    assert "SYN-94" not in result and "SYN-95" not in result
    assert arguments == before
    selected = next(
        row for row in arguments["issues"] if row["identity"]["issue_identifier"] == "SYN-8"
    )
    assert selected["blocked_by"] == []  # Pure declaration proof is not graph agreement.
    selected["description"] = selected["description"].replace(
        "MP2-003, MP2-000", "MP2-000, MP2-003"
    )
    assert release._release_linear_catalog_dependencies(registry, **arguments) == result
    selected["description"] = selected["description"].replace("\n", "  \n")
    assert release._release_linear_catalog_dependencies(registry, **arguments) == result


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-marker",
        "duplicate-marker",
        "wrong-task",
        "missing-edge",
        "extra-edge",
        "duplicate-edge",
        "range-syntax",
        "unknown-marker",
        "inline-marker",
        "trailing-marker-data",
        "missing-issue",
        "duplicate-issue",
        "uuid-alias",
        "missing-description",
        "missing-work-order",
        "duplicate-work-order",
        "work-order-identity",
        "work-order-role",
        "work-order-milestone",
        "work-order-release",
        "work-order-self",
        "work-order-unknown",
        "work-order-duplicate-edge",
        "wrong-original-hash",
        "wrong-catalog-hash",
    ],
)
def test_linear_catalog_dependencies_reject_marker_and_original_authority_drift(
    mutation: str,
) -> None:
    registry, arguments = _linear_catalog_dependency_fixture()
    issue = next(
        row for row in arguments["issues"] if row["identity"]["issue_identifier"] == "SYN-8"
    )
    replacements = {
        "missing-marker": ("<!-- METRIPLANE_MP2_DEPENDENCIES_V1", "<!-- absent"),
        "wrong-task": ("Task: MP2-007", "Task: MP2-008"),
        "missing-edge": ("MP2-003, MP2-000", "MP2-003"),
        "extra-edge": ("MP2-003, MP2-000", "MP2-003, MP2-000, MP2-002"),
        "duplicate-edge": ("MP2-003, MP2-000", "MP2-003, MP2-000, MP2-003"),
        "range-syntax": ("MP2-003, MP2-000", "MP2-000..MP2-003"),
        "unknown-marker": ("DEPENDENCIES_V1", "DEPENDENCIES_V2"),
        "inline-marker": ("\n<!--", "same line <!--"),
        "trailing-marker-data": ("\n-->", "\nUnexpected: []\n-->"),
    }
    if mutation in replacements:
        issue["description"] = issue["description"].replace(*replacements[mutation])
    elif mutation == "duplicate-marker":
        issue["description"] += issue["description"]
    elif mutation == "missing-issue":
        arguments["issues"].remove(issue)
    elif mutation == "duplicate-issue":
        arguments["issues"].append(copy.deepcopy(issue))
    elif mutation == "uuid-alias":
        issue["identity"]["issue_id"] = arguments["issues"][0]["identity"]["issue_id"]
    elif mutation == "missing-description":
        del issue["description"]
    elif mutation == "wrong-original-hash":
        arguments["expected_work_orders_digest"] = "0" * 64
    elif mutation == "wrong-catalog-hash":
        arguments["expected_packet_digest"] = "0" * 64
    else:
        packet = json.loads(arguments["original_work_orders"])
        order = packet["tasks"][7]
        if mutation == "missing-work-order":
            packet["tasks"].pop()
        elif mutation == "duplicate-work-order":
            packet["tasks"].append(copy.deepcopy(order))
        elif mutation == "work-order-identity":
            order["linear_issue"] = "SYN-999"
        elif mutation == "work-order-role":
            order["role"] = "release_decision"
        elif mutation == "work-order-milestone":
            order["linear_milestone_id"] = "different-milestone"
        elif mutation == "work-order-release":
            order["first_required_release"] = "v0.5"
        elif mutation == "work-order-self":
            order["authoritative_blocked_by"].append("MP2-007")
        elif mutation == "work-order-unknown":
            order["authoritative_blocked_by"].append("MP2-999")
        else:
            assert mutation == "work-order-duplicate-edge"
            order["authoritative_blocked_by"].append("MP2-003")
        arguments["original_work_orders"] = release.canonical_json(packet)
        arguments["expected_work_orders_digest"] = release.sha256_bytes(
            arguments["original_work_orders"]
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_catalog_dependencies(registry, **arguments)


def test_linear_bom_preserves_cumulative_catalog_and_external_direct_gate() -> None:
    registry, arguments = _linear_bom_fixture()
    result = release._release_linear_bom_projection(registry, **arguments)
    assert len(result["catalog_issue_ids"]) == 93
    assert {"SYN-1", "SYN-81", "SYN-94", "SYN-95"} <= set(result["required_bom_ids"])
    assert "SYN-82" not in result["required_bom_ids"]  # Later roadmap decision remains captured.
    direct = next(
        row
        for row in result["required_bom"]
        if row["issue"]["identity"]["issue_identifier"] == "SYN-95"
    )
    current = next(
        row
        for row in result["required_bom"]
        if row["issue"]["identity"]["issue_identifier"] == "SYN-94"
    )
    assert direct["issue"]["identity"]["project_id"] != current["issue"]["identity"]["project_id"]
    assert direct["catalog_task_id"] is None and current["catalog_task_id"] is None
    assert result["required_bom_snapshot_digest"] == release.sha256_json(result["required_bom"])
    assert result["required_bom_snapshot_digest"] != release.sha256_json(result["required_bom_ids"])
    assert len(result["unresolved_bindings"]) == 95


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-issue",
        "duplicate-uuid",
        "duplicate-identifier",
        "description",
        "unknown-endpoint",
        "wrong-endpoint-identifier",
        "self-edge",
        "duplicate-edge",
        "nonreciprocal",
        "project",
        "milestone",
        "catalog-id",
        "decision-catalog-id",
        "missing-policy",
        "unknown-dependency",
        "undeclared-edge",
        "declaration-omitted",
        "cycle",
        "wrong-catalog",
        "no-cumulative",
        "unsorted",
    ],
)
def test_linear_bom_rejects_incomplete_or_rewritten_graphs(mutation: str) -> None:
    registry, arguments = _linear_bom_fixture()
    issues = arguments["issues"]
    by_name = {row["identity"]["issue_identifier"]: row for row in issues}
    current, direct = by_name["SYN-94"], by_name["SYN-95"]
    if mutation == "missing-issue":
        issues.remove(by_name["SYN-2"])
    elif mutation == "duplicate-uuid":
        issues.append(copy.deepcopy(issues[0]))
    elif mutation == "duplicate-identifier":
        by_name["SYN-2"]["identity"]["issue_identifier"] = "SYN-1"
    elif mutation == "description":
        del current["description"]
    elif mutation == "unknown-endpoint":
        current["blocked_by"][0]["issue_id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "wrong-endpoint-identifier":
        current["blocked_by"][0]["issue_identifier"] = "SYN-1"
    elif mutation == "self-edge":
        current["blocked_by"] = [
            {k: current["identity"][k] for k in ("issue_id", "issue_identifier")}
        ]
    elif mutation == "duplicate-edge":
        current["blocked_by"] *= 2
    elif mutation == "nonreciprocal":
        direct["blocks"] = []
    elif mutation == "project":
        current["identity"] = {
            **current["identity"],
            "project_id": direct["identity"]["project_id"],
        }
    elif mutation == "milestone":
        current["project_milestone"] = {
            "id": current["identity"]["issue_id"],
            "name": "Other",
            "project_id": current["identity"]["project_id"],
        }
    elif mutation == "catalog-id":
        registry["provider_issue_bindings"][-1]["catalog_task_id"] = "MP2-001"
    elif mutation == "decision-catalog-id":
        registry["release_contexts"][0]["roadmap_catalog_task_id"] = "MP2-018"
    elif mutation == "missing-policy":
        registry["provider_issue_bindings"].pop(0)
    elif mutation == "unknown-dependency":
        registry["provider_issue_bindings"].pop()
    elif mutation == "undeclared-edge":
        arguments["declared_dependencies"]["SYN-94"] = []
    elif mutation == "declaration-omitted":
        del arguments["declared_dependencies"]["SYN-1"]
    elif mutation == "cycle":
        direct["blocked_by"] = [
            {k: current["identity"][k] for k in ("issue_id", "issue_identifier")}
        ]
        current["blocks"] = [{k: direct["identity"][k] for k in ("issue_id", "issue_identifier")}]
        arguments["declared_dependencies"]["SYN-95"] = ["SYN-94"]
    elif mutation == "wrong-catalog":
        registry["task_catalog"] = registry["task_catalog"][:6]
    elif mutation == "no-cumulative":
        registry["release_contexts"][0]["preserve_original_cumulative_bom"] = False
    else:
        issues.reverse()
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_bom_projection(registry, **arguments)


def _linear_lifecycle_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from uuid import UUID

    registry, arguments = _linear_bom_fixture()
    states = {
        "closed": {"id": str(UUID(int=20001)), "name": "Done", "type": "completed"},
        "open_running": {"id": str(UUID(int=20002)), "name": "In Progress", "type": "started"},
        "open_finalizing": {"id": str(UUID(int=20003)), "name": "In Review", "type": "started"},
    }
    team = arguments["issues"][0]["identity"]["team_id"]
    policy = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs/status/release-task-state-policy.json"
        ).read_bytes()
    )
    policy["workflow_states"], policy["provider"]["team_id"] = states, team
    raw = release.canonical_json(policy)
    lifecycle = {
        "issues": {row["identity"]["issue_id"]: row for row in arguments["issues"]},
        "team_statuses": [
            {
                "team_id": team,
                "observation_id": "synthetic-team-statuses",
                "states": sorted(states.values(), key=lambda row: row["id"]),
            }
        ],
        "task_state_policy_raw": raw,
        "expected_task_state_policy_digest": release.sha256_bytes(raw),
    }
    return registry, arguments, lifecycle


def test_linear_lifecycle_preserves_sticky_completed_at_on_current_open_decision() -> None:
    registry, arguments, lifecycle = _linear_lifecycle_fixture()
    projection = release._release_linear_bom_projection(registry, **arguments)
    current = lifecycle["issues"][projection["decision_issue_id"]]
    assert current["completed_at"] is not None and current["state"]["type"] == "started"
    release._release_linear_lifecycle(projection, **lifecycle)


@pytest.mark.parametrize(
    "mutation",
    [
        "required-started",
        "required-duplicate",
        "required-canceled",
        "required-unknown",
        "archived",
        "current-closed",
        "current-finalizing",
        "dictionary-mismatch",
        "dictionary-missing",
        "stale-policy-digest",
        "omitted-current-bom",
        "id-only-bom",
        "copied-issue",
    ],
)
def test_linear_lifecycle_rejects_false_completion_or_policy_authority(mutation: str) -> None:
    from uuid import UUID

    registry, arguments, lifecycle = _linear_lifecycle_fixture()
    rows = {row["identity"]["issue_identifier"]: row for row in arguments["issues"]}
    states = lifecycle["team_statuses"][0]["states"]
    if mutation.startswith("required-"):
        category = mutation.removeprefix("required-")
        state = {"id": str(UUID(int=20004)), "name": "Synthetic " + category, "type": category}
        rows["SYN-1"]["state"] = state
        states.append(state)
    elif mutation == "archived":
        rows["SYN-1"]["archived_at"] = "2026-01-03T00:00:00Z"
    elif mutation == "current-closed":
        rows["SYN-94"]["state"] = states[0]
    elif mutation == "current-finalizing":
        rows["SYN-94"]["state"] = states[2]
    elif mutation == "dictionary-mismatch":
        states[0]["name"] = "Different state name"
    elif mutation == "dictionary-missing":
        lifecycle["team_statuses"] = []
    elif mutation == "stale-policy-digest":
        lifecycle["expected_task_state_policy_digest"] = "0" * 64
    projection = release._release_linear_bom_projection(registry, **arguments)
    if mutation == "omitted-current-bom":
        projection["required_bom"] = [
            row
            for row in projection["required_bom"]
            if row["issue"]["identity"]["issue_identifier"] != "SYN-94"
        ]
        projection["required_bom_snapshot_digest"] = release.sha256_json(projection["required_bom"])
    elif mutation == "id-only-bom":
        projection["required_bom_snapshot_digest"] = release.sha256_json(
            projection["required_bom_ids"]
        )
    elif mutation == "copied-issue":
        projection = copy.deepcopy(projection)
        projection["required_bom"][0]["issue"]["description"] = "Truncated replacement"
        projection["required_bom_snapshot_digest"] = release.sha256_json(projection["required_bom"])
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_lifecycle(projection, **lifecycle)


def test_linear_boundary_relations_do_not_expand_unrelated_workspace_into_bom() -> None:
    from uuid import UUID

    registry, arguments = _linear_bom_fixture()
    related = copy.deepcopy(arguments["issues"][0])
    related["identity"] = {
        **related["identity"],
        "issue_id": str(UUID(int=999)),
        "issue_identifier": "SYN-999",
    }
    related["related_to"] = [{"issue_id": str(UUID(int=1000)), "issue_identifier": "SYN-1000"}]
    required = next(
        row for row in arguments["issues"] if row["identity"]["issue_identifier"] == "SYN-1"
    )
    required["related_to"] = [
        {"issue_id": related["identity"]["issue_id"], "issue_identifier": "SYN-999"}
    ]
    arguments["issues"].append(related)
    arguments["issues"].sort(
        key=lambda row: (row["identity"]["issue_identifier"], row["identity"]["issue_id"])
    )
    projection = release._release_linear_bom_projection(registry, **arguments)
    assert "SYN-999" not in projection["required_bom_ids"]


@pytest.mark.parametrize(
    "mutation",
    ["window", "skew", "transition", "extra-transition", "atomicity", "role", "state-alias"],
)
def test_raw_task_policy_cannot_weaken_existing_release_constraints(mutation: str) -> None:
    _, _, lifecycle = _linear_lifecycle_fixture()
    policy = json.loads(lifecycle["task_state_policy_raw"])
    if mutation == "window":
        policy["freshness_windows_seconds"]["terminal_commit"] = 300
    elif mutation == "skew":
        policy["server_clock_skew_budget_seconds"]["capture"] = 300
    elif mutation == "transition":
        policy["allowed_transitions"][1]["required_after"] = "completed_timestamp_present"
    elif mutation == "extra-transition":
        policy["allowed_transitions"].append(copy.deepcopy(policy["allowed_transitions"][0]))
    elif mutation == "atomicity":
        policy["cross_system_atomicity"] = "atomic"
    elif mutation == "role":
        policy["allowed_transitions"][0]["authorized_role"] = "anyone"
    else:
        policy["workflow_states"]["open_finalizing"] = policy["workflow_states"]["open_running"]
    raw = release.canonical_json(policy)
    with pytest.raises(release.ReleaseControlError):
        release._release_task_state_policy_projection(
            raw, expected_digest=release.sha256_bytes(raw)
        )


def test_linear_catalog_can_retain_an_explicitly_unassigned_project() -> None:
    registry, arguments = _linear_bom_fixture()
    row = next(row for row in arguments["issues"] if row["identity"]["issue_identifier"] == "SYN-1")
    row["identity"]["project_id"] = None
    binding = next(
        row for row in registry["provider_issue_bindings"] if row["issue_identifier"] == "SYN-1"
    )
    binding["identity"]["project_id"] = None
    projection = release._release_linear_bom_projection(registry, **arguments)
    assert (
        next(
            row
            for row in projection["required_bom"]
            if row["issue"]["identity"]["issue_identifier"] == "SYN-1"
        )["issue"]["identity"]["project_id"]
        is None
    )


@pytest.mark.parametrize("which", ["decision", "direct"])
def test_linear_context_roots_require_their_explicit_project(which: str) -> None:
    registry, arguments = _linear_bom_fixture()
    context = registry["release_contexts"][0]
    identity = context["decision"] if which == "decision" else context["direct_gate_issues"][0]
    identity["project_id"] = None
    with pytest.raises(release.ReleaseControlError):
        release._release_linear_bom_projection(registry, **arguments)


@pytest.mark.parametrize("field", ["id", "name", "project_id"])
def test_linear_current_context_cannot_borrow_a_different_provider_milestone(field: str) -> None:
    from uuid import UUID

    registry, arguments = _linear_bom_fixture()
    context = registry["release_contexts"][0]
    context["provider_milestone"] = {
        **context["provider_milestone"],
        field: "Other name" if field == "name" else str(UUID(int=40000)),
    }
    with pytest.raises(release.ReleaseControlError, match="context milestone"):
        release._release_linear_bom_projection(registry, **arguments)


@pytest.mark.parametrize("mutation", ["known-identifier", "reused-uuid", "reused-identifier"])
def test_linear_uncaptured_boundary_references_keep_one_global_identity_pair(mutation: str) -> None:
    from uuid import UUID

    registry, arguments = _linear_bom_fixture()
    boundary = copy.deepcopy(arguments["issues"][0])
    boundary["identity"] = {
        **boundary["identity"],
        "issue_id": str(UUID(int=999)),
        "issue_identifier": "SYN-999",
        "project_id": None,
    }
    boundary["related_to"] = [{"issue_id": str(UUID(int=1000)), "issue_identifier": "SYN-1000"}]
    if mutation == "known-identifier":
        boundary["related_to"][0]["issue_identifier"] = "SYN-1"
    else:
        boundary["parent"] = {
            "issue_id": str(UUID(int=1000 if mutation == "reused-uuid" else 1001)),
            "issue_identifier": "SYN-1001" if mutation == "reused-uuid" else "SYN-1000",
        }
    arguments["issues"].append(boundary)
    arguments["issues"].sort(
        key=lambda row: (row["identity"]["issue_identifier"], row["identity"]["issue_id"])
    )
    with pytest.raises(release.ReleaseControlError, match="boundary reference aliases"):
        release._release_linear_bom_projection(registry, **arguments)


def _index_scope_fixture(kind: str, *, sequence: int = 7) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "kind": kind,
        "scope_id": "c" * 64,
        "stage": "index-recovery",
        "sequence": sequence,
    }
    if kind in {"release_staging", "evaluation_staging"}:
        scope.update(milestone="v0.4", run_id="fixture-run")
    if kind in {"release_staging", "release_candidate", "release_completion"}:
        scope.update(release_tag="v0.4.1", candidate_id="c" * 64)
    if kind == "evaluation_staging":
        scope["evaluation_id"] = None
    if kind == "evaluation_candidate":
        scope.update(milestone="v0.4", evaluation_id="e" * 64, slot=None)
    if kind == "release_completion":
        scope.update(
            stage="release-completion", assurance_round=2, completion_manifest_digest="f" * 64
        )
    return scope


def _index_entry_fixture(kind: str = "release_candidate") -> dict[str, Any]:
    return {
        "schema_version": "metriplane.release-attempt-index-entry.v1",
        "backend_id": "attempt-index",
        "genesis_digest": "a" * 64,
        "generation": 19,
        "previous_head": "b" * 64,
        "operation_id": "fixture-attempt",
        "token": "fixture-native-token",
        "milestone": "v0.4",
        "scope": _index_scope_fixture(kind),
        "entry_manifest_digest": "d" * 64,
        "entry_receipts_digest": "e" * 64,
    }


def _index_receipt_fixture(
    entry: dict[str, Any], *, disposition: str = "committed"
) -> dict[str, Any]:
    scope = entry["scope"]
    return {
        **{
            key: entry[key]
            for key in (
                "backend_id",
                "genesis_digest",
                "generation",
                "previous_head",
                "operation_id",
                "token",
                "milestone",
                "entry_manifest_digest",
                "entry_receipts_digest",
            )
        },
        "kind": "update_receipt",
        "disposition": disposition,
        "entry_scope": scope,
        "scope_id": scope["scope_id"],
        "scope_kind": scope["kind"],
        "sequence": scope["sequence"],
        "stage": scope["stage"],
        "committed_head": release.sha256_json(entry),
        "read_back_digest": release.sha256_json(entry),
        "producer_intent_digest": "f" * 64,
        "invocation_root_locator": "invocations",
    }


@pytest.mark.parametrize(
    "kind",
    [
        "release_staging",
        "release_candidate",
        "evaluation_staging",
        "evaluation_candidate",
        "release_completion",
    ],
)
@pytest.mark.parametrize("disposition", ["committed", "idempotent"])
def test_index_content_preserves_all_five_original_scope_forms(kind: str, disposition: str) -> None:
    entry = _index_entry_fixture(kind)
    assert (
        release._release_index_receipt_content(
            _index_receipt_fixture(entry, disposition=disposition)
        )
        == entry
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "scope-extra",
        "sequence-bool",
        "generation-bool",
        "generation-zero",
        "generation-one-head",
        "later-null-head",
        "genesis",
        "kind",
        "backend",
        "operation",
        "token",
        "scope-kind",
        "scope-sequence",
        "scope-stage",
        "scope-id",
        "head",
        "readback",
        "producer",
        "locator",
        "tag-milestone",
        "tag-malformed",
        "scope-candidate",
        "scope-tag-null",
    ],
)
def test_index_content_rejects_receipt_and_entry_substitution(mutation: str) -> None:
    entry = _index_entry_fixture()
    data = _index_receipt_fixture(entry)
    if mutation == "extra":
        data["extra"] = True
    elif mutation == "scope-extra":
        data["entry_scope"]["extra"] = True
    elif mutation == "sequence-bool":
        data["entry_scope"]["sequence"] = data["sequence"] = True
    elif mutation == "generation-bool":
        data["generation"] = True
    elif mutation == "generation-zero":
        data["generation"] = 0
    elif mutation == "generation-one-head":
        data["generation"] = 1
    elif mutation == "later-null-head":
        data["previous_head"] = None
    elif mutation == "genesis":
        data["genesis_digest"] = "invalid"
    elif mutation == "kind":
        data["kind"] = "complete_export"
    elif mutation == "backend":
        data["backend_id"] = "success-chain"
    elif mutation == "operation":
        data["operation_id"] = "bad operation"
    elif mutation == "token":
        data["token"] = " "
    elif mutation == "scope-kind":
        data["scope_kind"] = "release_staging"
    elif mutation == "scope-sequence":
        data["sequence"] = 8
    elif mutation == "scope-stage":
        data["stage"] = "target-burn"
    elif mutation == "scope-id":
        data["scope_id"] = "other"
    elif mutation == "head":
        data["committed_head"] = "1" * 64
    elif mutation == "readback":
        data["read_back_digest"] = "1" * 64
    elif mutation == "producer":
        data["producer_intent_digest"] = None
    elif mutation == "locator":
        data["invocation_root_locator"] = "../invocations"
    elif mutation == "tag-milestone":
        data["entry_scope"]["release_tag"] = "v0.5.1"
    elif mutation == "tag-malformed":
        data["entry_scope"]["release_tag"] = "v0.04.1"
    elif mutation == "scope-candidate":
        data["entry_scope"]["candidate_id"] = None
    else:
        data["entry_scope"]["release_tag"] = None
    with pytest.raises(release.ReleaseControlError):
        release._release_index_receipt_content(data)


@pytest.mark.parametrize("receipt_sequence", [1, 7, 42])
def test_index_content_attempt_consumer_requires_original_graph_not_receipt_counter(
    receipt_sequence: int,
) -> None:
    entry = _index_entry_fixture()
    entry["scope"]["stage"] = "qualification-attempt"
    record = release.make_record(
        "release-attempt-index",
        _index_receipt_fixture(entry),
        invocation_id="fixture-index",
        sequence=receipt_sequence,
        synthetic=True,
    )
    kwargs = dict(
        attempt={
            "attempt_id": entry["operation_id"],
            "milestone": "v0.4",
            "candidate_digest": "c" * 64,
        },
        expected_release_tag="v0.4.1",
        expected_manifest_digest="d" * 64,
        retention_digest="e" * 64,
        live=False,
    )
    with pytest.raises(release.ReleaseControlError, match="original operation/attempt graph"):
        release._validate_attempt_index_payload(record, **kwargs)


def _index_export_fixture(count: int = 2) -> tuple[dict[str, Any], dict[str, Any]]:
    """Original content bytes only: no native authority or durable store proof."""
    files: dict[str, bytes] = {}

    def raw_ref(name: str, raw: bytes) -> dict[str, Any]:
        files[name] = raw
        return {"path": name, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}

    def record_ref(name: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        record = release.make_record(
            kind, data, invocation_id="fixture-origin", sequence=42, synthetic=True
        )
        return {
            "record_type": kind,
            "record_digest": release.sha256_json(record),
            "original_file": raw_ref(name, release.canonical_json(record) + b"\n"),
        }

    genesis = raw_ref("genesis.raw", b"original fixture genesis\n")
    rows = []
    previous = None
    for generation in range(1, count + 1):
        manifest = record_ref(
            f"manifest-{generation}.json", "release-evidence-manifest", _manifest_content_fixture()
        )
        subject = manifest["original_file"]["sha256"]
        stores = []
        for sid in ("payload-store-a", "payload-store-b"):
            proofs = {
                key: raw_ref(
                    f"{generation}-{sid}-{key}.raw",
                    files[manifest["original_file"]["path"]]
                    if key == "read_back"
                    else (sid + key).encode(),
                )
                for key in ("put", "hold", "read_back")
            }
            stores.append(
                {
                    "store_id": sid,
                    "content_digest": subject,
                    "read_back_digest": subject,
                    "put_receipt_digest": proofs["put"]["sha256"],
                    "hold_receipt_digest": proofs["hold"]["sha256"],
                    "namespace": "fixture",
                    "object_key": "fixture-subject",
                    "independence_group": sid,
                    "backend_binding_digest": "b" * 64,
                    "native_proofs": proofs,
                }
            )
        retention = record_ref(
            f"retention-{generation}.json",
            "release-retention-receipts",
            {
                "all_content_equal": True,
                "input_digest": subject,
                "invocation_root_locator": "invocations",
                "original_registry": raw_ref("registry.raw", b"fixture registry"),
                "phase": "attempt",
                "producer_intent_digest": "1" * 64,
                "receipt_set_digest": release.sha256_json(stores),
                "retained_at": "2026-09-08T12:00:00Z",
                "stores": stores,
            },
        )
        entry = _index_entry_fixture()
        entry.update(
            genesis_digest=genesis["sha256"],
            generation=generation,
            previous_head=previous,
            operation_id=f"operation-{generation}",
            entry_manifest_digest=manifest["record_digest"],
            entry_receipts_digest=retention["record_digest"],
        )
        entry["scope"]["sequence"] = generation
        previous = release.sha256_json(entry)
        rows.append(
            {
                "entry": entry,
                "entry_digest": previous,
                "original_native_response": raw_ref(
                    f"native-{generation}.raw", f"opaque fixture native {generation}".encode()
                ),
                "original_receipt": record_ref(
                    f"receipt-{generation}.json",
                    "release-attempt-index",
                    _index_receipt_fixture(entry),
                ),
                "original_manifest": manifest,
                "original_retention": retention,
            }
        )
    head = previous or genesis["sha256"]
    export = {
        "kind": "complete_export",
        "backend_id": "attempt-index",
        "backend_binding_digest": "b" * 64,
        "genesis": genesis,
        "genesis_digest": genesis["sha256"],
        "through_head": head,
        "generation": count,
        "capture_started_at": "2026-09-08T12:00:00Z",
        "capture_completed_at": "2026-09-08T12:00:02Z",
        "entries": rows,
        "head_observation": {
            "head": head,
            "generation": count,
            "observed_at": "2026-09-08T12:00:01Z",
            "original_native_response": raw_ref("head.raw", b"opaque fixture native head"),
        },
        "producer_intent_digest": "f" * 64,
        "invocation_root_locator": "invocations",
    }
    return export, {
        "original_files": files,
        "expected_genesis_digest": genesis["sha256"],
        "expected_backend_binding_digest": "b" * 64,
        "expected_head": head,
        "expected_generation": count,
        "synthetic": True,
    }


@pytest.mark.parametrize("count", [0, 1, 2, 5])
def test_index_content_complete_export_replays_original_head_and_every_generation(
    count: int,
) -> None:
    data, args = _index_export_fixture(count)
    result = release._release_index_export_content(data, **args)
    assert len(result) == count
    assert [row["entry"]["generation"] for row in result] == list(range(1, count + 1))
    assert all(row["receipt"]["sequence"] == 42 for row in result)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "reorder",
        "fork",
        "generation",
        "duplicate-op",
        "duplicate-scope",
        "entry-c",
        "receipt-c",
        "receipt-r",
        "manifest-c",
        "retention-c",
        "native-r",
        "missing-raw",
        "native-path",
        "native-bool",
        "genesis-r",
        "bound-genesis",
        "bound-backend",
        "bound-head",
        "bound-generation",
        "head-c",
        "head-generation",
        "head-before",
        "head-after",
        "interval",
        "export-kind",
        "export-extra",
        "export-producer",
        "mode",
    ],
)
def test_index_content_complete_export_rejects_incomplete_or_rebound_history(mutation: str) -> None:
    data, args = _index_export_fixture()
    row = data["entries"][1]
    if mutation == "missing":
        data["entries"].pop()
    elif mutation == "extra":
        data["entries"].append(row)
    elif mutation == "reorder":
        data["entries"].reverse()
    elif mutation == "fork":
        row["entry"]["previous_head"] = "0" * 64
    elif mutation == "generation":
        row["entry"]["generation"] = 3
    elif mutation == "duplicate-op":
        row["entry"]["operation_id"] = data["entries"][0]["entry"]["operation_id"]
    elif mutation == "duplicate-scope":
        row["entry"]["scope"]["sequence"] = 1
    elif mutation == "entry-c":
        row["entry_digest"] = "0" * 64
    elif mutation == "receipt-c":
        row["original_receipt"]["record_digest"] = "0" * 64
    elif mutation == "receipt-r":
        row["original_receipt"]["original_file"]["sha256"] = "0" * 64
    elif mutation == "manifest-c":
        row["original_manifest"]["record_digest"] = "0" * 64
    elif mutation == "retention-c":
        row["original_retention"]["record_digest"] = "0" * 64
    elif mutation == "native-r":
        row["original_native_response"]["sha256"] = "0" * 64
    elif mutation == "missing-raw":
        args["original_files"].pop(row["original_native_response"]["path"])
    elif mutation == "native-path":
        row["original_native_response"]["path"] = "../escape"
    elif mutation == "native-bool":
        row["original_native_response"]["bytes"] = True
    elif mutation == "genesis-r":
        data["genesis"]["sha256"] = "0" * 64
    elif mutation == "bound-genesis":
        args["expected_genesis_digest"] = "0" * 64
    elif mutation == "bound-backend":
        args["expected_backend_binding_digest"] = "0" * 64
    elif mutation == "bound-head":
        args["expected_head"] = "0" * 64
    elif mutation == "bound-generation":
        args["expected_generation"] = 1
    elif mutation == "head-c":
        data["head_observation"]["head"] = "0" * 64
    elif mutation == "head-generation":
        data["head_observation"]["generation"] = 1
    elif mutation == "head-before":
        data["head_observation"]["observed_at"] = "2026-09-08T11:59:59Z"
    elif mutation == "head-after":
        data["head_observation"]["observed_at"] = "2026-09-08T12:00:03Z"
    elif mutation == "interval":
        data["capture_started_at"] = "2026-09-08T12:00:03Z"
    elif mutation == "export-kind":
        data["kind"] = "update_receipt"
    elif mutation == "export-extra":
        data["extra"] = True
    elif mutation == "export-producer":
        data["producer_intent_digest"] = "bad"
    else:
        args["synthetic"] = False
    with pytest.raises(release.ReleaseControlError):
        release._release_index_export_content(data, **args)


def test_index_content_rejects_raw_substitution_before_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data, args = _index_export_fixture(1)
    ref = data["entries"][0]["original_receipt"]["original_file"]
    args["original_files"][ref["path"]] = b"not json"

    def forbidden(*args: object) -> Any:
        raise AssertionError("substituted original bytes reached parser")

    monkeypatch.setattr(release, "_source_json", forbidden)
    with pytest.raises(release.ReleaseControlError, match="before parsing"):
        release._release_index_export_content(data, **args)


@pytest.mark.parametrize(
    "kind,field",
    [
        (kind, field)
        for kind in (
            "release_staging",
            "release_candidate",
            "evaluation_staging",
            "evaluation_candidate",
            "release_completion",
        )
        for field in (("scope_id", "run_id") if kind.endswith("_staging") else ("scope_id",))
    ],
)
def test_index_content_required_identifiers_cannot_be_null(kind: str, field: str) -> None:
    entry = _index_entry_fixture(kind)
    entry["scope"][field] = None
    # Rebuild all entry/receipt digests: rejection must depend on required identity.
    with pytest.raises(release.ReleaseControlError, match="index scope"):
        release._release_index_receipt_content(_index_receipt_fixture(entry))


@pytest.mark.parametrize("tag", ["v0.4.1", "v0.4.2", None])
def test_index_content_qualification_binds_exact_candidate_release_tag(tag: object) -> None:
    entry = _index_entry_fixture()
    entry["scope"]["stage"] = "qualification-attempt"
    record = release.make_record(
        "release-attempt-index",
        _index_receipt_fixture(entry),
        invocation_id="fixture-index",
        sequence=42,
        synthetic=True,
    )
    args: dict[str, Any] = {
        "attempt": {
            "attempt_id": "fixture-attempt",
            "milestone": "v0.4",
            "candidate_digest": "c" * 64,
        },
        "expected_release_tag": tag,
        "expected_manifest_digest": "d" * 64,
        "retention_digest": "e" * 64,
        "live": False,
    }
    if tag == "v0.4.1":
        with pytest.raises(release.ReleaseControlError, match="original operation/attempt graph"):
            release._validate_attempt_index_payload(record, **args)
    else:
        with pytest.raises(release.ReleaseControlError, match="semantic binding"):
            release._validate_attempt_index_payload(record, **args)


def _retention_content_fixture(
    subject: bytes = b"original fixture subject\n",
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Opaque byte controls only: no native adapter or approved administration."""
    files: dict[str, bytes] = {}

    def ref(name: str, raw: bytes, *, base: str = "") -> dict[str, Any]:
        files[base + name] = raw
        return {"path": name, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}

    stores, backends, declarations = [], [], []
    for sid in ("payload-store-a", "payload-store-b"):
        binding = {
            "adapter_id": "fixture-only-no-native-owner",
            **{
                field: ref(sid + "-" + field + ".raw", (sid + field).encode(), base="inputs/")
                for field in (
                    "public_configuration",
                    "owner_binding_authority",
                    "provider_resource_identity",
                    "administration_identity",
                    "durability_retention_policy",
                    "namespace_policy",
                )
            },
        }
        backends.append(
            {
                "backend_id": sid,
                "backend_kind": "immutable_payload",
                "binding_status": "BOUND_CONFIGURED",
                "independence_group": sid,
                "live_binding": binding,
            }
        )
        declarations.append(
            {
                "id": sid,
                "backend_id": sid,
                "independence_group": sid,
                "live_binding": {"backend_id": sid, "binding_digest": release.sha256_json(binding)},
            }
        )
        proofs = {
            field: ref(
                sid + "-" + field + ".raw",
                subject if field == "read_back" else (sid + field).encode(),
            )
            for field in ("put", "hold", "read_back")
        }
        stores.append(
            {
                "store_id": sid,
                "content_digest": release.sha256_bytes(subject),
                "read_back_digest": release.sha256_bytes(subject),
                "put_receipt_digest": proofs["put"]["sha256"],
                "hold_receipt_digest": proofs["hold"]["sha256"],
                "namespace": "fixture",
                "object_key": "subject",
                "independence_group": sid,
                "backend_binding_digest": release.sha256_json(binding),
                "native_proofs": proofs,
            }
        )
    registry = {
        "schema_version": "metriplane.release-evidence-stores.v1",
        "owner": "MP2-007",
        "secrets_embedded": False,
        "live_status": "BLOCKED_NOT_READY",
        "attempt_index": {},
        "backends": backends
        + [
            {"backend_id": sid}
            for sid in (
                "attempt-index",
                "success-chain",
                "last-known-good",
                "main-health-state",
                "main-health-summary",
            )
        ],
        "stores": declarations,
    }
    data = {
        "all_content_equal": True,
        "input_digest": release.sha256_bytes(subject),
        "invocation_root_locator": "invocations",
        "producer_intent_digest": "d" * 64,
        "original_registry": ref(
            "inputs/registry.json", json.dumps(registry, indent=2).encode() + b"\n"
        ),
        "phase": "attempt",
        "receipt_set_digest": release.sha256_json(stores),
        "retained_at": "2026-09-08T12:00:00Z",
        "stores": stores,
    }
    return data, files


def _retention_refresh(data: dict[str, Any]) -> None:
    data["receipt_set_digest"] = release.sha256_json(data["stores"])


def _retention_record_refresh(record: dict[str, Any]) -> None:
    replacement = release.make_record(
        record["record_type"],
        record["data"],
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=record["synthetic"],
        status=record["status"],
        signatures=record["signatures"],
    )
    record.clear()
    record.update(replacement)


def _retention_file_fixture(
    root: Path, subject: bytes = b"original fixture subject\n"
) -> tuple[dict[str, Any], dict[str, bytes], Path]:
    data, files = _retention_content_fixture(subject)
    record = release.make_record(
        "release-retention-receipts",
        data,
        invocation_id="fixture-retention",
        sequence=3,
        synthetic=True,
    )
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    path = root / "receipts.json"
    path.write_bytes(json.dumps(record, indent=2).encode() + b"\n")
    return record, files, path


@pytest.mark.parametrize("phase", sorted(release._RETENTION_PHASES))
def test_retention_content_complete_original_projection_all_phases(phase: str) -> None:
    data, files = _retention_content_fixture()
    data["phase"] = phase
    assert release._release_retention_content(data) == data["stores"]
    replay = release._release_retention_original_byte_replay(
        data,
        original_files=files,
        expected_registry_digest=data["original_registry"]["sha256"],
        subject=b"original fixture subject\n",
    )
    assert set(replay) == {"registry", "stores"}
    assert all(
        set(row) == {"store", "backend", "configuration", "native"} for row in replay["stores"]
    )
    # Distinct labels cannot create native or independent-administration authority.
    with pytest.raises(release.ReleaseControlError, match="remain unimplemented"):
        release._release_retention_native_authority_required(live=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-pair",
        "extra",
        "locator",
        "producer",
        "phase-list",
        "phase",
        "time",
        "time-basic",
        "boolean-content",
        "registry-size",
        "registry-path",
        "registry-hash",
        "reversed",
        "missing-store",
        "extra-store-field",
        "native-extra",
        "native-missing",
        "native-size",
        "native-path",
        "put-r",
        "hold-r",
        "readback-r",
        "content-r",
        "binding-c",
        "receipt-c",
        "group-type",
        "group-duplicate",
    ],
)
def test_retention_content_rejects_closed_shape_and_digest_drift(mutation: str) -> None:
    data, _ = _retention_content_fixture()
    row = data["stores"][0]
    if mutation == "missing-pair":
        del data["producer_intent_digest"]
    elif mutation == "extra":
        data["approved"] = True
    elif mutation == "locator":
        data["invocation_root_locator"] = "../invocations"
    elif mutation == "producer":
        data["producer_intent_digest"] = None
    elif mutation == "phase-list":
        data["phase"] = []
    elif mutation == "phase":
        data["phase"] = "qualified-publication"
    elif mutation == "time":
        data["retained_at"] = False
    elif mutation == "time-basic":
        data["retained_at"] = "20260908T120000Z"
    elif mutation == "boolean-content":
        data["all_content_equal"] = 1
    elif mutation.startswith("registry-"):
        field, value = {
            "registry-size": ("bytes", True),
            "registry-path": ("path", "../registry"),
            "registry-hash": ("sha256", "g" * 64),
        }[mutation]
        data["original_registry"][field] = value
    elif mutation == "reversed":
        data["stores"].reverse()
    elif mutation == "missing-store":
        data["stores"].pop()
    elif mutation == "extra-store-field":
        row["approved"] = True
    elif mutation == "native-extra":
        row["native_proofs"]["approved"] = True
    elif mutation == "native-missing":
        del row["native_proofs"]["hold"]
    elif mutation == "native-size":
        row["native_proofs"]["put"]["bytes"] = True
    elif mutation == "native-path":
        row["native_proofs"]["put"]["path"] = "./put.raw"
    elif mutation in {"put-r", "hold-r", "readback-r", "content-r"}:
        field = {
            "put-r": "put_receipt_digest",
            "hold-r": "hold_receipt_digest",
            "readback-r": "read_back_digest",
            "content-r": "content_digest",
        }[mutation]
        row[field] = "0" * 64
    elif mutation == "binding-c":
        row["backend_binding_digest"] = False
    elif mutation == "group-type":
        row["independence_group"] = []
    elif mutation == "group-duplicate":
        row["independence_group"] = data["stores"][1]["independence_group"]
    _retention_refresh(data)
    if mutation == "receipt-c":
        data["receipt_set_digest"] = "0" * 64
    with pytest.raises(release.ReleaseControlError):
        release._release_retention_content(data)


@pytest.mark.parametrize(
    "mutation",
    [
        "expected-registry",
        "registry-bytes",
        "registry-c-for-r",
        "missing-raw",
        "extra-raw",
        "subject",
        "put-bytes",
        "hold-bytes",
        "readback-bytes",
        "config-bytes",
        "config-parent",
        "backend-order",
        "unresolved",
        "binding-c",
        "store-binding",
        "store-label",
        "extra-binding",
        "malformed-registry",
    ],
)
def test_retention_original_bytes_and_complete_raw_closure(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, files = _retention_content_fixture()
    expected = data["original_registry"]["sha256"]
    subject = b"original fixture subject\n"
    registry_path = data["original_registry"]["path"]
    registry = json.loads(files[registry_path])
    parser_calls: list[str] = []
    original_parse = release._source_json

    def parse(raw: bytes, label: str) -> dict[str, Any]:
        parser_calls.append(label)
        return original_parse(raw, label)

    monkeypatch.setattr(release, "_source_json", parse)
    if mutation == "expected-registry":
        expected = "0" * 64
    elif mutation == "registry-bytes":
        files[registry_path] += b" "
    elif mutation == "registry-c-for-r":
        expected = data["original_registry"]["sha256"] = release.sha256_json(registry)
    elif mutation == "missing-raw":
        del files["payload-store-a-put.raw"]
    elif mutation == "extra-raw":
        files["unlisted.raw"] = b"unlisted"
    elif mutation == "subject":
        subject += b"changed"
    elif mutation.endswith("-bytes"):
        name = {
            "put-bytes": "payload-store-a-put.raw",
            "hold-bytes": "payload-store-a-hold.raw",
            "readback-bytes": "payload-store-a-read_back.raw",
            "config-bytes": "inputs/payload-store-a-public_configuration.raw",
        }[mutation]
        files[name] += b"changed"
    elif mutation == "config-parent":
        files["payload-store-a-public_configuration.raw"] = files.pop(
            "inputs/payload-store-a-public_configuration.raw"
        )
    else:
        if mutation == "backend-order":
            registry["backends"].reverse()
        elif mutation == "unresolved":
            registry["backends"][0]["binding_status"] = "UNRESOLVED"
            registry["backends"][0]["live_binding"] = None
        elif mutation == "binding-c":
            data["stores"][0]["backend_binding_digest"] = "0" * 64
        elif mutation == "store-binding":
            registry["stores"][0]["live_binding"]["binding_digest"] = "0" * 64
        elif mutation == "store-label":
            registry["stores"][0]["independence_group"] = "different-label"
        elif mutation == "extra-binding":
            registry["backends"][0]["live_binding"]["approved"] = True
        raw = json.dumps(registry, indent=2).encode() + b"\n"
        if mutation == "malformed-registry":
            raw = b'{"owner":"MP2-007","owner":"duplicate"}'
        files[registry_path] = raw
        data["original_registry"].update(bytes=len(raw), sha256=release.sha256_bytes(raw))
        expected = data["original_registry"]["sha256"]
    _retention_refresh(data)
    with pytest.raises(release.ReleaseControlError):
        release._release_retention_original_byte_replay(
            data, original_files=files, expected_registry_digest=expected, subject=subject
        )
    if mutation in {"expected-registry", "registry-bytes", "registry-c-for-r", "subject"}:
        assert parser_calls == []


@pytest.mark.parametrize("manifest", [None, b'{ "manifest": 1 }\n'])
@pytest.mark.parametrize("inputs", [[], [b'{ "input": 1 }\n'], [b"b", b"a"], [b"a", b"a"]])
def test_retention_subject_preserves_raw_input_policy(
    inputs: list[bytes], manifest: bytes | None
) -> None:
    if not inputs and manifest is None:
        with pytest.raises(release.ReleaseControlError):
            release._release_retention_subject_bytes(inputs, manifest)
        return
    subject = release._release_retention_subject_bytes(inputs, manifest)
    if manifest is not None:
        assert subject == manifest
    elif len(inputs) == 1:
        assert subject == inputs[0]
    else:
        assert release.sha256_bytes(subject) == release.sha256_json(
            sorted(release.sha256_bytes(raw) for raw in inputs)
        )
        assert len(json.loads(subject)) == len(inputs)


def test_retention_original_files_preserve_pretty_wire_and_relocate(tmp_path: Path) -> None:
    root = tmp_path / "old"
    record, _, path = _retention_file_fixture(root)
    original_r = release.sha256_bytes(path.read_bytes())
    assert original_r != release.sha256_json(record)
    root.rename(tmp_path / "relocated")
    path = tmp_path / "relocated/receipts.json"
    release._release_retention_file_replay(
        record["data"],
        record=record,
        record_path=path,
        expected_record_digest=original_r,
        subject=b"original fixture subject\n",
    )
    assert not root.exists()


@pytest.mark.parametrize(
    "mutation", ["symlink", "fifo", "hardlink", "ancestor", "record-r", "record-c", "later-drift"]
)
def test_retention_original_files_fail_closed_before_or_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root = tmp_path / "retention"
    record, _, path = _retention_file_fixture(root)
    expected = release.sha256_bytes(path.read_bytes())
    selected = root / "payload-store-a-put.raw"
    if mutation in {"symlink", "fifo", "hardlink"}:
        selected.unlink()
        other = root / "payload-store-b-put.raw"
        if mutation == "symlink":
            selected.symlink_to(other)
        elif mutation == "fifo":
            os.mkfifo(selected)
        else:
            os.link(other, selected)
    elif mutation == "ancestor":
        (root / "inputs").rename(root / "real-inputs")
        (root / "inputs").symlink_to(root / "real-inputs", target_is_directory=True)
    elif mutation == "record-r":
        expected = release.sha256_json(record)
    elif mutation == "record-c":
        record["invocation_id"] = "different-original"
    elif mutation == "later-drift":
        original = release._release_retention_original_byte_replay

        def replay(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = original(*args, **kwargs)
            selected.write_bytes(b"changed after initial capture")
            return result

        monkeypatch.setattr(release, "_release_retention_original_byte_replay", replay)
    with pytest.raises(release.ReleaseControlError):
        release._release_retention_file_replay(
            record["data"],
            record=record,
            record_path=path,
            expected_record_digest=expected,
            subject=b"original fixture subject\n",
        )


def test_retention_indexed_original_preserves_r_and_checks_it_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record, _, path = _retention_file_fixture(tmp_path)
    raw = path.read_bytes()
    digest = release.sha256_bytes(raw)
    indexed = {digest: [(path, record)]}
    assert release._release_retention_indexed_original(
        indexed, digest, record, identity_kind="raw_R"
    ) == (path, raw)
    path.write_bytes(raw + b" ")
    monkeypatch.setattr(
        release, "_source_json", lambda *_: pytest.fail("parse preceded raw R comparison")
    )
    with pytest.raises(release.ReleaseControlError, match="before parsing"):
        release._release_retention_indexed_original(indexed, digest, record, identity_kind="raw_R")


def test_retention_public_content_is_synthetic_only_and_journal_form_stays_blocked(
    tmp_path: Path,
) -> None:
    original = release.make_record(
        "release-target-observations", {}, invocation_id="fixture-input", sequence=1, synthetic=True
    )
    subject = json.dumps(original, indent=2).encode() + b"\n"
    record, _, path = _retention_file_fixture(tmp_path, subject)
    input_path = tmp_path / "subject.json"
    input_path.write_bytes(subject)
    args: dict[str, Any] = {
        "inputs": [input_path],
        "manifest": None,
        "invocation_root": None,
        "through_stage": None,
        "live": False,
        "record_path": path,
    }
    release.validate_release_retention_receipts(record, **args)
    with pytest.raises(release.ReleaseControlError, match="synthetic"):
        release.validate_release_retention_receipts(record, **(args | {"live": True}))
    unsigned = copy.deepcopy(record)
    unsigned["synthetic"] = False
    _retention_record_refresh(unsigned)
    with pytest.raises(release.ReleaseControlError, match="authenticated signature"):
        release.validate_release_retention_receipts(unsigned, **(args | {"live": True}))
    (tmp_path / "invocations").mkdir()
    with pytest.raises(
        release.ReleaseControlError, match="terminal inventory replay remains unimplemented"
    ):
        release.validate_release_retention_receipts(
            record,
            **(
                args
                | {
                    "invocation_root": tmp_path / "invocations",
                    "through_stage": "publication-reconciliation",
                }
            ),
        )


def _publication_retention_fixture(tmp_path: Path) -> dict[str, Any]:
    staged_data = _manifest_content_fixture()
    staged_data["phase"] = "prepublication"
    staged = release.make_record(
        "release-evidence-manifest",
        staged_data,
        invocation_id="fixture-staged",
        sequence=1,
        synthetic=True,
    )
    staged_raw = json.dumps(staged, indent=2).encode() + b"\n"
    staged_path = tmp_path / "staged.json"
    staged_path.write_bytes(staged_raw)
    retention, _, retention_path = _retention_file_fixture(tmp_path / "retention", staged_raw)
    retention["data"]["phase"] = "prepublication"
    _retention_record_refresh(retention)
    retention_path.write_bytes(json.dumps(retention, indent=2).encode() + b"\n")
    retention_raw = retention_path.read_bytes()
    qualified_data = _manifest_content_fixture()
    qualified_data["phase"] = "qualified-publication"
    qualified_data["entries"] = [
        {
            "path": name,
            "media_type": "application/json",
            "role": "original-input",
            "size": len(raw),
            "sha256": release.sha256_bytes(raw),
        }
        for name, raw in (("retention/receipts.json", retention_raw), ("staged.json", staged_raw))
    ]
    qualified_data["manifest_digest"] = release.sha256_json(
        {key: qualified_data[key] for key in ("entries", "invocation_journal_digests")}
    )
    qualified = release.make_record(
        "release-evidence-manifest",
        qualified_data,
        invocation_id="fixture-qualified",
        sequence=4,
        synthetic=True,
    )
    return {
        "retention_record": retention,
        "retention_digest": release.sha256_json(retention),
        "qualified_manifest": qualified,
        "candidate_digest": "c" * 64,
        "indexed": {
            release.sha256_bytes(staged_raw): [(staged_path, staged)],
            release.sha256_bytes(retention_raw): [(retention_path, retention)],
        },
        "live": False,
    }


@pytest.mark.parametrize(
    "form", ["manifest", "input-manifest", "multiple", "missing-manifest-input"]
)
def test_retention_public_subject_forms_keep_raw_manifest_precedence(
    tmp_path: Path, form: str
) -> None:
    paths = []
    originals = []
    for number in range(2):
        record = release.make_record(
            "release-target-observations",
            {"fixture": number},
            invocation_id="fixture-subject",
            sequence=number + 1,
            synthetic=True,
        )
        raw = json.dumps(record, indent=2).encode() + b"\n"
        path = tmp_path / f"subject-{number}.json"
        path.write_bytes(raw)
        paths.append(path)
        originals.append(raw)
    manifest_path = None
    manifest_raw = None
    if form != "multiple":
        data = _manifest_content_fixture()
        data["entries"] = [
            {
                "path": path.name,
                "media_type": "application/json",
                "role": "original-input",
                "size": len(raw),
                "sha256": release.sha256_bytes(raw),
            }
            for path, raw in zip(paths, originals, strict=True)
        ]
        if form == "missing-manifest-input":
            data["entries"].pop()
        data["manifest_digest"] = release.sha256_json(
            {key: data[key] for key in ("entries", "invocation_journal_digests")}
        )
        manifest_record = release.make_record(
            "release-evidence-manifest",
            data,
            invocation_id="fixture-manifest",
            sequence=1,
            synthetic=True,
        )
        manifest_raw = json.dumps(manifest_record, indent=2).encode() + b"\n"
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_bytes(manifest_raw)
    subject = release._release_retention_subject_bytes(originals, manifest_raw)
    record, _, path = _retention_file_fixture(tmp_path / "retention", subject)
    args = {
        "inputs": [] if form == "manifest" else paths,
        "manifest": manifest_path,
        "invocation_root": None,
        "through_stage": None,
        "live": False,
        "record_path": path,
    }
    if form == "missing-manifest-input":
        with pytest.raises(release.ReleaseControlError, match="absent from the original manifest"):
            release.validate_release_retention_receipts(record, **args)
    else:
        release.validate_release_retention_receipts(record, **args)


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "final-phase",
        "qualified-phase",
        "candidate",
        "missing-staged",
        "missing-receipt",
        "receipt-c-for-r",
        "receipt-index-r",
        "staged-c-for-r",
        "staged-candidate",
    ],
)
def test_retention_publication_uses_original_prepublication_subject_without_future_cycle(
    tmp_path: Path, mutation: str
) -> None:
    args = _publication_retention_fixture(tmp_path)
    retention = args["retention_record"]["data"]
    qualified = args["qualified_manifest"]["data"]
    staged_path, staged = args["indexed"][retention["input_digest"]][0]
    if mutation == "final-phase":
        retention["phase"] = "final"
    elif mutation == "qualified-phase":
        qualified["phase"] = "prepublication"
    elif mutation == "candidate":
        args["candidate_digest"] = "0" * 64
    elif mutation.startswith("missing-"):
        name = "staged.json" if mutation == "missing-staged" else "retention/receipts.json"
        qualified["entries"] = [row for row in qualified["entries"] if row["path"] != name]
    elif mutation == "receipt-c-for-r":
        qualified["entries"][0]["sha256"] = release.sha256_json(args["retention_record"])
    elif mutation == "receipt-index-r":
        args["retention_digest"] = release.sha256_bytes(
            json.dumps(args["retention_record"], indent=2).encode() + b"\n"
        )
    elif mutation == "staged-c-for-r":
        retention["input_digest"] = release.sha256_json(staged)
    elif mutation == "staged-candidate":
        staged["data"]["candidate_digest"] = "0" * 64
        _retention_record_refresh(staged)
        raw = json.dumps(staged, indent=2).encode() + b"\n"
        staged_path.write_bytes(raw)
        args["indexed"][release.sha256_bytes(raw)] = [(staged_path, staged)]
        retention["input_digest"] = release.sha256_bytes(raw)
        for row in retention["stores"]:
            row["content_digest"] = row["read_back_digest"] = release.sha256_bytes(raw)
            row["native_proofs"]["read_back"].update(
                bytes=len(raw), sha256=release.sha256_bytes(raw)
            )
        _retention_refresh(retention)
    if mutation == "staged-c-for-r":
        for row in retention["stores"]:
            row["content_digest"] = row["read_back_digest"] = retention["input_digest"]
            row["native_proofs"]["read_back"]["sha256"] = retention["input_digest"]
        _retention_refresh(retention)
    # Rebind valid envelopes/original receipt bytes so negative cases reach semantic guards.
    previous_r = next(
        digest
        for digest, values in args["indexed"].items()
        if values[0][1] is args["retention_record"]
    )
    retention_path = args["indexed"][previous_r][0][0]
    _retention_record_refresh(args["retention_record"])
    receipt_raw = json.dumps(args["retention_record"], indent=2).encode() + b"\n"
    retention_path.write_bytes(receipt_raw)
    current_r = release.sha256_bytes(receipt_raw)
    args["indexed"][current_r] = [(retention_path, args["retention_record"])]
    if mutation != "receipt-index-r":
        args["retention_digest"] = release.sha256_json(args["retention_record"])
    for row in qualified["entries"]:
        if row["sha256"] == previous_r:
            row.update(size=len(receipt_raw), sha256=current_r)
    qualified["manifest_digest"] = release.sha256_json(
        {key: qualified[key] for key in ("entries", "invocation_journal_digests")}
    )
    _retention_record_refresh(args["qualified_manifest"])
    if mutation == "none":
        assert release._release_publication_retention_subject(**args) == staged_path.read_bytes()
        assert not (tmp_path / "final-retention-receipts.json").exists()
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_publication_retention_subject(**args)


def _evidence_identity_fixture(tmp_path: Path) -> tuple[dict[str, Any], Path, bytes]:
    record = release.make_record(
        "release-target-observations",
        {"content": "original"},
        invocation_id="fixture-evidence-identity",
        sequence=7,
        synthetic=True,
    )
    raw = json.dumps(record, indent=2).encode() + b"\n"
    path = tmp_path / "original.json"
    path.write_bytes(raw)
    assert release.sha256_bytes(raw) != release.sha256_json(record)
    return record, path, raw


@pytest.mark.parametrize("identity_kind", ["raw_R", "record_C"])
@pytest.mark.parametrize(
    "mutation", ["none", "wrong-domain", "wrong-type", "drift", "wrong-index-key", "mutated-record"]
)
def test_evidence_identity_resolves_exact_original_domain_before_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_kind: Any,
    mutation: str,
) -> None:
    record, path, raw = _evidence_identity_fixture(tmp_path)
    indexed = release._evidence_record_index(tmp_path)
    r, c = release.sha256_bytes(raw), release.sha256_json(record)
    digest = r if identity_kind == "raw_R" else c
    expected_type = "release-target-observations"
    if mutation == "wrong-domain":
        digest = c if identity_kind == "raw_R" else r
    elif mutation == "wrong-type":
        expected_type = "release-retention-receipts"
    elif mutation == "drift":
        path.write_bytes(raw + b" ")
        monkeypatch.setattr(release, "_source_json", lambda *_: pytest.fail("R must precede parse"))
    elif mutation == "wrong-index-key":
        indexed = {c: [(path, record)]}
    elif mutation == "mutated-record":
        indexed[r][0][1]["data"]["content"] = "changed"
    args = dict(identity_kind=identity_kind, live=False)
    if mutation == "none":
        observed = release._resolved_evidence_record(
            indexed, digest, expected_type, "fixture", **args
        )
        assert observed == record
        assert release._release_retention_indexed_original(
            indexed,
            digest,
            record,
            identity_kind=identity_kind,
        ) == (path, raw)
    else:
        with pytest.raises(release.ReleaseControlError):
            release._resolved_evidence_record(indexed, digest, expected_type, "fixture", **args)


@pytest.mark.parametrize("form", ["unbound", "first-R", "second-R", "unknown-R"])
def test_evidence_identity_equal_c_does_not_select_an_arbitrary_retention_wire(
    tmp_path: Path,
    form: str,
) -> None:
    record, path, raw = _evidence_identity_fixture(tmp_path)
    second = tmp_path / "second.json"
    second_raw = raw + b"\n"
    second.write_bytes(second_raw)
    indexed = release._evidence_record_index(tmp_path)
    c = release.sha256_json(record)
    # C alone selects the same record content. It grants neither wire provenance nor authority.
    assert (
        release._resolved_evidence_record(
            indexed,
            c,
            "release-target-observations",
            "fixture",
            identity_kind="record_C",
            live=False,
        )
        == record
    )
    expected = (
        None
        if form == "unbound"
        else {
            "first-R": release.sha256_bytes(raw),
            "second-R": release.sha256_bytes(second_raw),
            "unknown-R": "0" * 64,
        }[form]
    )
    if form in {"first-R", "second-R"}:
        assert release._release_retention_indexed_original(
            indexed,
            c,
            record,
            identity_kind="record_C",
            expected_raw_digest=expected,
        ) == ((path, raw) if form == "first-R" else (second, second_raw))
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_retention_indexed_original(
                indexed,
                c,
                record,
                identity_kind="record_C",
                expected_raw_digest=expected,
            )


@pytest.mark.parametrize(
    "mutation", ["none", "missing", "duplicate", "size", "C-as-R", "R-as-C", "drift"]
)
def test_evidence_identity_manifest_closes_full_record_c_through_original_raw_r(
    tmp_path: Path,
    mutation: str,
) -> None:
    record, path, raw = _evidence_identity_fixture(tmp_path)
    indexed = release._evidence_record_index(tmp_path)
    c, r = release.sha256_json(record), release.sha256_bytes(raw)
    entries = [{"sha256": r, "size": len(raw)}]
    required = {c}
    if mutation == "missing":
        required.add("0" * 64)
    elif mutation == "duplicate":
        entries.append(dict(entries[0]))
    elif mutation == "size":
        entries[0]["size"] = len(raw) + 1
    elif mutation == "C-as-R":
        entries[0]["sha256"] = c
    elif mutation == "R-as-C":
        required = {r}
    elif mutation == "drift":
        path.write_bytes(raw + b" ")
    if mutation == "none":
        assert release._release_manifest_record_raw_digests(entries, indexed, required) == {r}
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_manifest_record_raw_digests(entries, indexed, required)


@pytest.mark.parametrize("form", ["input", "manifest"])
@pytest.mark.parametrize("mutation", ["bytes", "same-bytes-new-inode", "ancestor"])
def test_retention_public_original_lifetime_survives_complete_receipt_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    form: str,
    mutation: str,
) -> None:
    record, path, raw = _evidence_identity_fixture(tmp_path)
    if form == "manifest":
        record = release.make_record(
            "release-evidence-manifest",
            _manifest_content_fixture(),
            invocation_id="fixture-subject-manifest",
            sequence=1,
            synthetic=True,
        )
        raw = json.dumps(record, indent=2).encode() + b"\n"
        path.write_bytes(raw)
    receipt, _, receipt_path = _retention_file_fixture(tmp_path / "retention", raw)
    original = release._release_retention_file_replay

    def replay(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        if mutation == "bytes":
            path.write_bytes(raw + b" ")
        elif mutation == "same-bytes-new-inode":
            path.rename(tmp_path / "previous-original.json")
            path.write_bytes(raw)
        else:
            import shutil

            previous = tmp_path.with_name(tmp_path.name + "-previous")
            tmp_path.rename(previous)
            shutil.copytree(previous, tmp_path)

    monkeypatch.setattr(release, "_release_retention_file_replay", replay)
    with pytest.raises(release.ReleaseControlError):
        release.validate_release_retention_receipts(
            receipt,
            inputs=[path] if form == "input" else [],
            manifest=path if form == "manifest" else None,
            invocation_root=None,
            through_stage=None,
            live=False,
            record_path=receipt_path,
        )


def test_retention_file_known_ancestor_is_checked_before_next_member_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    receipt, _, path = _retention_file_fixture(tmp_path)
    original_parse = release._source_json
    original_open = os.open
    changed = False
    foreign_file_opens: list[str] = []

    def parse(raw: bytes, label: str) -> Any:
        nonlocal changed
        value = original_parse(raw, label)
        if label == "retention original registry" and not changed:
            (tmp_path / "inputs").rename(tmp_path / "previous-inputs")
            shutil.copytree(tmp_path / "previous-inputs", tmp_path / "inputs")
            changed = True
        return value

    def observed_open(name: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if changed and not flags & os.O_DIRECTORY:
            foreign_file_opens.append(str(name))
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(release, "_source_json", parse)
    monkeypatch.setattr(os, "open", observed_open)
    with pytest.raises(release.ReleaseControlError, match="ancestor"):
        release._release_retention_file_replay(
            receipt["data"],
            record=receipt,
            record_path=path,
            expected_record_digest=release.sha256_bytes(path.read_bytes()),
            subject=b"original fixture subject\n",
        )
    assert changed and foreign_file_opens == []


@pytest.mark.parametrize("boundary", ["receipt-replay", "readback"])
@pytest.mark.parametrize("mutation", ["ancestor", "same-bytes-new-object"])
def test_retention_public_handoff_preserves_pre_access_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    mutation: str,
) -> None:
    import shutil

    _, subject_path, raw = _evidence_identity_fixture(tmp_path)
    receipt, _, receipt_path = _retention_file_fixture(tmp_path / "retention", raw)
    (tmp_path / "readbacks").mkdir()
    readbacks = {
        key: tmp_path / "readbacks" / (key + ".raw")
        for key in ("payload-store-a", "payload-store-b")
    }
    for path in readbacks.values():
        path.write_bytes(raw)
    chosen = receipt_path if boundary == "receipt-replay" else readbacks["payload-store-a"]
    method = (
        "_release_retention_file_replay"
        if boundary == "receipt-replay"
        else "_validate_observed_store_readbacks"
    )
    original = getattr(release, method)
    original_read = os.read
    foreign_bytes: list[bytes] = []
    changed = False

    def read(fd: int, size: int) -> bytes:
        value = original_read(fd, size)
        if changed and value:
            foreign_bytes.append(value)
        return value

    def handoff(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        if mutation == "ancestor":
            prior = chosen.parent.with_name(chosen.parent.name + "-previous")
            chosen.parent.rename(prior)
            shutil.copytree(prior, chosen.parent)
        else:
            previous = chosen.with_name(chosen.name + ".previous")
            chosen.rename(previous)
            chosen.write_bytes(previous.read_bytes())
        changed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(release, method, handoff)
    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release.validate_release_retention_receipts(
            receipt,
            inputs=[subject_path],
            manifest=None,
            invocation_root=None,
            through_stage=None,
            live=False,
            record_path=receipt_path,
            readbacks=readbacks,
        )
    assert changed and foreign_bytes == []


# Original command content controls; native approval/complete S4 attempt wire remain separate.
def _index_command_reseal(record: Any) -> Any:
    result = release.make_record(
        record["record_type"],
        record["data"],
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=record["synthetic"],
        status=record["status"],
    )
    record.clear()
    record.update(result)


def _index_command_build(
    root: Any,
    purpose: Any,
    mutation: Any = "none",
    sequence_text: Any = "001",
    attempt_id: Any = "001",
    aggregate_sequence: Any = 2,
    subject_data: Any = None,
) -> Any:
    root.mkdir()
    phase = "target-burn" if purpose == "burn" else "attempt"
    directory = root if purpose == "burn" else root / "attempts" / attempt_id
    directory.mkdir(parents=True, exist_ok=True)
    subject_path = directory / ("target-burn.json" if purpose == "burn" else "attempt-summary.json")
    data = (
        copy.deepcopy(
            release._release_target_control_data(
                "release-target-burn", **_target_control_fixture()
            )[0]
        )
        if purpose == "burn"
        else {
            "attempt_id": attempt_id,
            "candidate_digest": "c" * 64,
            "milestone": "v0.4",
            "coordination_digest": "f" * 64,
            "result": "FAIL",
        }
    )
    if subject_data is not None:
        data = copy.deepcopy(subject_data)
    subject = release.make_record(
        "release-target-burn" if purpose == "burn" else "release-attempt",
        data,
        invocation_id="fixture-subject-original",
        sequence=aggregate_sequence,
        synthetic=True,
    )
    if mutation == "no-new":
        subject["data"].update(disposition="no_new_burn", indexing_required=False)
    if mutation == "burn-tag":
        subject["data"]["resolved_release_tag"] = "v0.4.2"
    if purpose == "burn" and mutation in {"no-new", "burn-tag"}:
        subject["data"]["burn_id"] = release.sha256_json(
            {k: v for k, v in subject["data"].items() if k != "burn_id"}
        )
    if mutation == "attempt-id":
        subject["data"]["attempt_id"] = "other-attempt"
    _index_command_reseal(subject)

    def write(path: Any, record: Any) -> Any:
        path.write_bytes(json.dumps(record, indent=2).encode() + b"\n")
        return path.read_bytes()

    subject_raw = write(subject_path, subject)
    paths = [subject_path]
    coordination = None
    coordination_path = None
    if purpose == "attempt":
        coordination = release.make_record(
            "release-attempt-coordination",
            {"attempt_id": attempt_id, "candidate_digest": "c" * 64, "milestone": "v0.4"},
            invocation_id="fixture-coordination",
            sequence=4,
            synthetic=True,
        )
        if mutation == "coordination-id":
            coordination["data"]["attempt_id"] = "other-attempt"
            _index_command_reseal(coordination)
        coordination_path = directory / "coordination.json"
        write(coordination_path, coordination)
        paths.append(coordination_path)
    manifest_data = _manifest_content_fixture()
    manifest_data["phase"] = phase
    if purpose == "burn":
        manifest_data.update(
            candidate_digest=None,
            scope_id="fixture-run",
            scope_kind="release-staging",
        )
    manifest_data["entries"] = [
        {
            "path": p.name,
            "size": len(p.read_bytes()),
            "sha256": release.sha256_bytes(p.read_bytes()),
            "media_type": "application/json",
            "role": "original-input",
        }
        for p in sorted(paths)
    ]
    if mutation == "subject-path":
        row = next((r for r in manifest_data["entries"] if r["path"] == subject_path.name))
        row["path"] = "identical-copy.json"
        (directory / "identical-copy.json").write_bytes(subject_raw)
        paths.append(directory / "identical-copy.json")
        manifest_data["entries"].sort(key=lambda r: r["path"])
    if mutation == "subject-size":
        next((r for r in manifest_data["entries"] if r["path"] == subject_path.name))["size"] += 1
    if mutation == "manifest-phase":
        manifest_data["phase"] = "final"
    manifest_data["manifest_digest"] = release.sha256_json(
        {k: manifest_data[k] for k in ["entries", "invocation_journal_digests"]}
    )
    manifest = release.make_record(
        "release-evidence-manifest",
        manifest_data,
        invocation_id="fixture-manifest",
        sequence=1,
        synthetic=True,
    )
    manifest_path = directory / "manifest.json"
    manifest_raw = write(manifest_path, manifest)
    paths.append(manifest_path)
    retention_data, _ = _retention_content_fixture(manifest_raw)
    retention_data["phase"] = phase
    if mutation == "retention-C-as-R":
        retention_data["input_digest"] = release.sha256_json(manifest)
        for row in retention_data["stores"]:
            row["content_digest"] = row["read_back_digest"] = retention_data["input_digest"]
            row["native_proofs"]["read_back"]["sha256"] = retention_data["input_digest"]
        _retention_refresh(retention_data)
    retention = release.make_record(
        "release-retention-receipts",
        retention_data,
        invocation_id="fixture-retention",
        sequence=1,
        synthetic=True,
    )
    retention_path = directory / "retention.json"
    write(retention_path, retention)
    paths.append(retention_path)
    scope = {
        "kind": "release_staging" if purpose == "burn" else "release_candidate",
        "scope_id": "explicit-original-scope",
        "stage": "target-burn" if purpose == "burn" else "qualification-attempt",
        "sequence": 1,
        "release_tag": "v0.4.1",
        "candidate_id": None if purpose == "burn" else "c" * 64,
    }
    if purpose == "burn":
        scope.update(milestone="v0.4", run_id="fixture-run")
    output = directory / "index-receipt.json"
    flags = {
        "entry-manifest": str(manifest_path),
        "entry-receipts": str(retention_path),
        "scope-kind": scope["kind"],
        "stage": scope["stage"],
        "sequence": sequence_text,
        "release-tag": "v0.4.1",
        "index-backend": "attempt-index",
        "expected-head": "b" * 64,
        "operation-id": "original-operation-not-attempt-id",
        "out": str(output),
    }
    if purpose == "burn":
        flags.update(
            milestone="v0.4", **{"run-id": "fixture-run", "candidate-id-not-resolved": True}
        )
    else:
        flags["candidate-id"] = "c" * 64
    if mutation == "argv-operation":
        flags["operation-id"] = "different-original-operation"
    if mutation == "argv-head":
        flags["expected-head"] = "e" * 64
    if mutation == "argv-tag":
        flags["release-tag"] = "v0.4.2"
    if mutation == "argv-sequence":
        flags["sequence"] = "2"
    if mutation == "argv-out":
        flags["out"] = str(directory / "another-receipt.json")
    if mutation == "argv-missing-manifest":
        del flags["entry-manifest"]
    if mutation == "candidate-resolved":
        flags.pop("candidate-id-not-resolved", None)
        flags["candidate-id"] = "c" * 64
    input_paths = [
        (manifest_path, "metriplane.release-evidence-manifest.v1"),
        (retention_path, "metriplane.release-retention-receipts.v1"),
    ]
    if mutation == "input-schema":
        input_paths[0] = (manifest_path, "application/octet-stream")
    contexts = []
    for journal_sequence in (1, 2):
        invocation = (
            root
            / "invocations"
            / release._invocation_stage("update_release_attempt_index.py")
            / f"{journal_sequence:03d}"
        )
        local = {**flags, "invocation-dir": str(invocation)}
        argv = []
        for key, value in local.items():
            argv.append("--" + key)
            argv.extend([] if value is True else [str(value)])
        contexts.append(
            release.begin_release_invocation(
                "update_release_attempt_index.py",
                argv,
                invocation,
                input_paths=input_paths,
                planned_outputs=[(output, "metriplane.release-attempt-index.v1")],
            )
        )
    update = contexts[-1]
    entry = _index_entry_fixture()
    entry.update(
        scope=copy.deepcopy(scope),
        operation_id="original-operation-not-attempt-id",
        entry_manifest_digest=release.sha256_json(manifest),
        entry_receipts_digest=release.sha256_json(retention),
    )
    if mutation == "receipt-sequence":
        entry["scope"]["sequence"] = 2
    if mutation == "receipt-operation":
        entry["operation_id"] = attempt_id
    if mutation == "receipt-tag":
        entry["scope"]["release_tag"] = "v0.4.2"
    if mutation == "receipt-scope":
        entry["scope"]["scope_id"] = "different-scope"
    if mutation == "receipt-manifest":
        entry["entry_manifest_digest"] = "0" * 64
    if mutation == "manifest-R-as-C":
        entry["entry_manifest_digest"] = release.sha256_bytes(manifest_raw)
    if mutation == "receipt-retention":
        entry["entry_receipts_digest"] = "0" * 64
    if mutation == "receipt-prior":
        entry["previous_head"] = "d" * 64
    data = _index_receipt_fixture(entry)
    data["producer_intent_digest"] = release.sha256_json(update.intent)
    if mutation == "producer-intent":
        data["producer_intent_digest"] = "0" * 64
    receipt = release.make_record(
        "release-attempt-index",
        data,
        invocation_id=update.intent["invocation_id"],
        sequence=2,
        synthetic=True,
    )
    if mutation == "producer-counter":
        receipt["sequence"] = 1
        _index_command_reseal(receipt)
    if mutation == "mode":
        receipt["synthetic"] = False
        _index_command_reseal(receipt)
    write(output, receipt)
    paths.append(output)
    if mutation == "input-drift":
        manifest_path.write_bytes(manifest_raw + b" ")
    paths.extend((c.directory / "intent.json" for c in contexts))
    if mutation == "relocate":
        original_root = root
        root = root.with_name(root.name + "-relocated")
        original_root.rename(root)

        def moved(p: Any) -> Any:
            return root / p.relative_to(original_root)

        paths = [moved(p) for p in paths]
        output = moved(output)
        subject_path = moved(subject_path)
        directory = moved(directory)
        if coordination_path is not None:
            coordination_path = moved(coordination_path)
        update = release.ReleaseInvocation(moved(update.directory), root, update.intent)
    capture = release._ReleaseCapturedFiles.capture(
        root,
        [(str(p.relative_to(root)), "prerequisite-original") for p in paths],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    arguments = dict(
        update=update,
        receipt_path=output,
        captured=capture,
        subject_record=subject,
        subject_path=subject_path,
        expected_scope=scope,
        expected_operation_id="original-operation-not-attempt-id",
        expected_milestone="v0.4",
        expected_release_tag="v0.4.1",
        expected_index_backend="attempt-index",
        expected_prior_head="b" * 64,
        expected_synthetic=True,
    )
    if purpose == "attempt":
        arguments.update(
            attempt_directory=directory,
            expected_attempt_id=attempt_id,
            coordination_record=coordination,
            coordination_path=coordination_path,
        )
    if mutation == "missing-attempt-owner":
        arguments["expected_attempt_id"] = None
    if mutation == "missing-scope":
        arguments["expected_scope"] = None
    return (receipt, arguments)


@pytest.mark.parametrize("purpose", ["burn", "attempt"])
@pytest.mark.parametrize("sequence_text", ["1", "001", "+1", " 001 "])
@pytest.mark.parametrize("mutation", ["none", "relocate"])
def test_index_original_command_original_command_projection(
    tmp_path: Any, purpose: Any, sequence_text: Any, mutation: Any
) -> Any:
    receipt, args = _index_command_build(tmp_path / "case", purpose, mutation, sequence_text)
    result = release._release_index_original_update_binding(receipt, **args)
    assert result["entry"]["scope"]["sequence"] == 1 and receipt["sequence"] == 2
    assert result["entry"]["operation_id"] != "001"
    assert set(result) == {
        "entry",
        "original_update_intent_digest",
        "manifest_record_digest",
        "retention_record_digest",
        "manifest_raw_digest",
        "subject_record_digest",
    }


@pytest.mark.parametrize("attempt_id", ["001", "test-alpha"])
@pytest.mark.parametrize("aggregate_sequence", [1, 2, 7])
def test_index_original_command_logical_attempt_not_aggregation_counter_or_operation(
    tmp_path: Any, attempt_id: Any, aggregate_sequence: Any
) -> Any:
    receipt, args = _index_command_build(
        tmp_path / "case", "attempt", attempt_id=attempt_id, aggregate_sequence=aggregate_sequence
    )
    result = release._release_index_original_update_binding(receipt, **args)
    assert result["entry"]["scope"]["sequence"] == 1


@pytest.mark.parametrize(
    "purpose,mutation",
    [
        (p, m)
        for p in ["burn", "attempt"]
        for m in [
            "subject-path",
            "subject-size",
            "manifest-phase",
            "retention-C-as-R",
            "argv-operation",
            "argv-head",
            "argv-tag",
            "argv-sequence",
            "argv-out",
            "argv-missing-manifest",
            "input-schema",
            "input-drift",
            "receipt-sequence",
            "receipt-operation",
            "receipt-tag",
            "receipt-scope",
            "receipt-manifest",
            "manifest-R-as-C",
            "receipt-retention",
            "receipt-prior",
            "producer-intent",
            "producer-counter",
            "mode",
            "missing-scope",
        ]
    ]
    + [
        ("burn", "no-new"),
        ("burn", "burn-tag"),
        ("burn", "candidate-resolved"),
        ("attempt", "attempt-id"),
        ("attempt", "coordination-id"),
        ("attempt", "missing-attempt-owner"),
    ],
)
def test_index_original_command_original_command_negative_bindings(
    tmp_path: Any, purpose: Any, mutation: Any
) -> Any:
    receipt, args = _index_command_build(tmp_path / "case", purpose, mutation)
    with pytest.raises(release.ReleaseControlError):
        release._release_index_original_update_binding(receipt, **args)


@pytest.mark.parametrize("value", ["0", "-0", "1.0", "NaN", "one"])
def test_index_original_command_original_integer_rejects_nonworker_or_absent_values(
    tmp_path: Any, value: Any
) -> Any:
    receipt, args = _index_command_build(tmp_path / "case", "burn", sequence_text=value)
    with pytest.raises(release.ReleaseControlError):
        release._release_index_original_update_binding(receipt, **args)


def _gate_pair_content_fixture(
    tmp_path: Path, new_burn: bool
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, Any]]:
    """Small graph unit controls: no native approval, complete registry cardinality or usable target claim."""
    context, ca = _context_policy_fixture()
    policy, _ = _predecessor_policy_fixture()
    predraw = release.canonical_json(policy)
    context["data"]["predecessor_policy_digest"] = release.sha256_bytes(predraw)
    context["data"]["context_digest"] = release.sha256_json(
        {k: v for k, v in context["data"].items() if k != "context_digest"}
    )
    _index_command_reseal(context)
    linear = ca["linear_snapshot"]
    role_root = tmp_path / "roles"
    role_root.mkdir()
    protected_path, _ = _original_role_byte_fixture(role_root)
    protected = json.loads(protected_path.read_bytes())
    roles_data = copy.deepcopy(protected["data"]["assignments"])
    roles_data.update(
        kind="recorded_assignments",
        release_context_digest=release.sha256_json(context),
        original_protected_input={
            "path": "protected.json",
            "bytes": len(protected_path.read_bytes()),
            "sha256": release.sha256_bytes(protected_path.read_bytes()),
        },
        original_protected_input_digest=release.sha256_json(protected),
        producer_intent_digest="2" * 64,
        invocation_root_locator="invocations",
    )
    roles = release.make_record(
        "release-role-assignments",
        roles_data,
        invocation_id="fixture-roles",
        sequence=1,
        synthetic=True,
    )
    targets = _target_control_fixture()
    targets["context"] = context
    targets["expected_context_digest"] = release.sha256_json(context)
    od = targets["observations"]["data"]
    od["original_release_context"]["record_digest"] = release.sha256_json(context)
    if not new_burn:
        for row in od["targets"]:
            row["state"] = "unused"
        targets["lineage"]["data"]["burns"] = []
        targets["expected_operation_order"] = []
    for name, field in (("observations", "observation_digest"), ("lineage", "lineage_digest")):
        d = targets[name]["data"]
        d[field] = release.sha256_json({k: v for k, v in d.items() if k != field})
        _index_command_reseal(targets[name])
        targets[
            "expected_" + name.rstrip("s") + "_digest"
            if name == "lineage"
            else "expected_observations_digest"
        ] = release.sha256_json(targets[name])
    resolution_data, _ = release._release_target_control_data(
        "release-target-resolution", **targets
    )
    burn_data, _ = release._release_target_control_data("release-target-burn", **targets)
    resolution = release.make_record(
        "release-target-resolution",
        resolution_data,
        invocation_id="fixture-resolution",
        sequence=1,
        synthetic=True,
    )
    burn = release.make_record(
        "release-target-burn", burn_data, invocation_id="fixture-burn", sequence=1, synthetic=True
    )
    original_index = None
    receipt = None
    if new_burn:
        receipt, binding_args = _index_command_build(
            tmp_path / "index", "burn", subject_data=burn_data
        )
        burn = binding_args["subject_record"]
        original_index = {
            k: v
            for k, v in binding_args.items()
            if k
            not in {
                "subject_record",
                "expected_milestone",
                "expected_release_tag",
                "expected_synthetic",
            }
        }
    raws, catalog_args = _catalog_data_fixture()
    catalog_args["run_id"] = roles_data["run_id"]
    cat = release._release_scenario_catalog_data(raws, **catalog_args)
    catalog = release.make_record(
        "release-scenario-catalog",
        cat,
        invocation_id="fixture-gate-pair",
        sequence=3,
        synthetic=True,
    )
    _, _, wire_args, _ = _linear_wire_fixture()
    registries = {flag: raws[path] for flag, path in release._RELEASE_EXECUTION_REGISTRIES.items()}
    registries.update(
        {
            "readiness-registry": ca["readiness_registry_raw"],
            "targets": targets["target_registry_raw"],
            "evidence-stores": (
                Path(__file__).resolve().parents[1] / "docs/status/release-evidence-stores.json"
            ).read_bytes(),
            "task-state-policy": wire_args["task_state_policy_raw"],
        }
    )
    subjects = {
        "release-context": context,
        "linear-snapshot": linear,
        "role-assignments": roles,
        "target-resolution": resolution,
        "target-burn": burn,
        "scenario-catalog": catalog,
    }
    if receipt is not None:
        subjects["target-burn-index-receipt"] = receipt
    args = dict(
        expected_subject_digests={k: release.sha256_json(v) for k, v in subjects.items()},
        expected_registry_digests={k: release.sha256_bytes(v) for k, v in registries.items()},
        predecessor_policy_raw=predraw,
        expected_predecessor_policy_digest=release.sha256_bytes(predraw),
        expected_context_id=ca["expected_context_id"],
        expected_predecessor_milestone="v0.4",
        milestone="v0.4",
        run_id=roles_data["run_id"],
        producer_intent_digest=catalog_args["producer_intent_digest"],
        invocation_id="fixture-gate-pair",
        sequence=3,
        synthetic=True,
        no_new_burn=not new_burn,
        burn_index_original=original_index,
    )
    return subjects, registries, args


@pytest.mark.parametrize("new_burn", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "policy-R",
        "catalog-invocation",
        "different-context",
        "missing-original-index",
        "wrong-burn-original",
        "unrelated-receipt",
    ],
)
def test_gate_pair_content_replays_original_burn_and_policy_crosslinks(
    tmp_path: Path, new_burn: bool, mutation: str
) -> None:
    subjects, registries, args = _gate_pair_content_fixture(tmp_path, new_burn)
    if mutation == "policy-R":
        registries["task-state-policy"] += b" "
        args["expected_registry_digests"]["task-state-policy"] = release.sha256_bytes(
            registries["task-state-policy"]
        )
    elif mutation == "catalog-invocation":
        subjects["scenario-catalog"]["invocation_id"] = "different-catalog"
        _index_command_reseal(subjects["scenario-catalog"])
    elif mutation == "different-context":
        subjects["target-resolution"]["data"]["release_context_digest"] = "0" * 64
        _index_command_reseal(subjects["target-resolution"])
    elif mutation == "missing-original-index":
        args["burn_index_original"] = None if new_burn else {}
    elif mutation == "wrong-burn-original":
        subjects["target-burn"]["data"]["reason"] += " altered original"
        _index_command_reseal(subjects["target-burn"])
        if not new_burn:
            args["burn_index_original"] = {}
    elif mutation == "unrelated-receipt":
        if new_burn:
            entry = release._release_index_receipt_content(
                subjects["target-burn-index-receipt"]["data"]
            )
            entry["scope"].update(release_tag="v0.4.2", scope_id="unrelated", sequence=99)
            entry.update(
                operation_id="unrelated-operation",
                entry_manifest_digest="9" * 64,
                entry_receipts_digest="8" * 64,
            )
            subjects["target-burn-index-receipt"]["data"] = _index_receipt_fixture(entry)
            _index_command_reseal(subjects["target-burn-index-receipt"])
        else:
            subjects["target-burn-index-receipt"] = release.make_record(
                "release-attempt-index",
                _index_receipt_fixture(_index_entry_fixture("release_staging")),
                invocation_id="unrelated-index",
                sequence=1,
                synthetic=True,
            )
    args["expected_subject_digests"] = {k: release.sha256_json(v) for k, v in subjects.items()}
    if mutation == "none":
        data = release._release_gate_pair_data(subjects, registries, **args)
        assert len(data) == 21 and data["scenario_catalog_digest"] == release.sha256_json(
            subjects["scenario-catalog"]
        )
        assert data["gate_input_digest"] == release.sha256_json(
            {k: v for k, v in data.items() if k != "gate_input_digest"}
        )
        assert (data["target_burn_index_receipt_digest"] is not None) == new_burn
    else:
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_pair_data(subjects, registries, **args)


@pytest.mark.parametrize("aggregate_sequence", [1, 2, 7])
@pytest.mark.parametrize(
    "operation", ["original-operation-not-attempt-id", "wrong-original-operation"]
)
def test_attempt_index_consumer_requires_actual_original_update_graph(
    tmp_path: Path, aggregate_sequence: int, operation: str
) -> None:
    receipt, original = _index_command_build(
        tmp_path / "attempt", "attempt", aggregate_sequence=aggregate_sequence
    )
    original["expected_operation_id"] = operation
    data = receipt["data"]
    args = dict(
        attempt=original["subject_record"]["data"],
        expected_release_tag="v0.4.1",
        expected_manifest_digest=data["entry_manifest_digest"],
        retention_digest=data["entry_receipts_digest"],
        live=False,
        original_update=original,
    )
    if operation == "original-operation-not-attempt-id":
        release._validate_attempt_index_payload(receipt, **args)
    else:
        with pytest.raises(release.ReleaseControlError):
            release._validate_attempt_index_payload(receipt, **args)


def _gate_pair_output_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, new_burn: bool = False
) -> tuple[release.ReleaseInvocation, dict[str, Any], dict[str, Any], list[str]]:
    """Completed synthetic common journal, with content and transport tested separately.

    Original gate capture fixture and compact content fixture have deliberately
    separate upstream graphs. This test does not establish their correspondence,
    native prerequisites, a real worker execution, a public gate or readiness.
    """
    root = tmp_path / "original"
    root.mkdir()
    context, _ = _gate_input_plan_fixture(root, monkeypatch, new_burn=new_burn)
    source = tmp_path / "content"
    source.mkdir()
    subjects, registries, args = _gate_pair_content_fixture(source, new_burn)
    args.update(
        invocation_id=context.intent["invocation_id"],
        sequence=context.intent["sequence"],
        producer_intent_digest=release.sha256_json(context.intent),
    )
    catalog = release.make_record(
        "release-scenario-catalog",
        release._release_scenario_catalog_data(
            {
                path: registries[flag]
                for flag, path in release._RELEASE_EXECUTION_REGISTRIES.items()
            },
            expected_registry_digests={
                path: args["expected_registry_digests"][flag]
                for flag, path in release._RELEASE_EXECUTION_REGISTRIES.items()
            },
            run_id=args["run_id"],
            producer_intent_digest=args["producer_intent_digest"],
        ),
        invocation_id=context.intent["invocation_id"],
        sequence=context.intent["sequence"],
        synthetic=True,
    )
    subjects["scenario-catalog"] = catalog
    args["expected_subject_digests"]["scenario-catalog"] = release.sha256_json(catalog)
    data = release._release_gate_pair_data(subjects, registries, **args)
    gate = release.make_record(
        "release-gate-input",
        data,
        invocation_id=context.intent["invocation_id"],
        sequence=context.intent["sequence"],
        synthetic=True,
    )
    outputs = []
    for name, kind in release._RELEASE_GATE_OUTPUT_PLAN:
        value = gate if name == "gate-input.json" else catalog
        raw = release.canonical_json(value)
        (root / name).write_bytes(raw)
        outputs.append({"path": name, "schema_id": kind, "sha256": release.sha256_bytes(raw)})
    for name in ("stdout", "stderr"):
        (context.directory / name).write_bytes(b"")
    _gate_fixture_terminal_content(context, 0, outputs, monkeypatch)
    worker_names = _synthetic_original_worker_fixture(context, outputs)
    _gate_fixture_synthetic_witness(context)
    names = [
        "gate-input.json",
        "scenario-catalog.json",
        *[
            (context.directory / n).relative_to(root).as_posix()
            for n in ("intent.json", "invocation.json", "stdout", "stderr", "terminal-commit.json")
        ],
        *worker_names,
    ]
    return context, data, catalog, names


def _gate_pair_output_capture(root: Path, names: list[str]) -> release._ReleaseCapturedFiles:
    return release._ReleaseCapturedFiles.capture(
        root,
        [(name, "prerequisite-original") for name in names],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )


@pytest.mark.parametrize("new_burn", [False, True])
@pytest.mark.parametrize("relocate", [False, True])
def test_gate_pair_output_common_terminal_replays_both_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_burn: bool, relocate: bool
) -> None:
    context, data, catalog, names = _gate_pair_output_fixture(
        tmp_path, monkeypatch, new_burn=new_burn
    )
    original = context.root
    if relocate:
        destination = tmp_path / "retained"
        original.rename(destination)
        context = release.ReleaseInvocation(
            destination / context.directory.relative_to(original), destination, context.intent
        )
    captured = _gate_pair_output_capture(context.root, names)
    real_read = release._release_held_path

    def read(path: Path, **kwargs: Any) -> Any:
        if relocate:
            assert not path.is_relative_to(original)
        return real_read(path, **kwargs)

    monkeypatch.setattr(release, "_release_held_path", read)
    result = release._release_gate_pair_output_replay(
        context, captured=captured, expected_gate_data=data, expected_catalog_record=catalog
    )
    assert result["gate_record"]["data"] == data
    assert result["catalog_record"] == catalog
    assert len(result["terminal"]["data"]["outputs"]) == 2
    assert set(result) == {"gate_record", "catalog_record", "terminal", "producer_intent_digest"}
    with pytest.raises(release.ReleaseControlError, match="native command owner"):
        release._release_captured_original_context(context, captured=captured)


@pytest.mark.parametrize(
    "missing",
    [
        "gate-input.json",
        "scenario-catalog.json",
        "invocation.json",
        "worker-result.json",
        "worker.pid",
        "staged/gate-input.json",
        "staged/scenario-catalog.json",
    ],
)
def test_gate_pair_output_cannot_pass_partial_installation_or_pending_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    context, data, catalog, names = _gate_pair_output_fixture(tmp_path, monkeypatch)
    path = (
        context.root
        if missing in {"gate-input.json", "scenario-catalog.json"}
        else context.directory
    ) / missing
    path.unlink()
    names.remove(path.relative_to(context.root).as_posix())
    captured = _gate_pair_output_capture(context.root, names)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_pair_output_replay(
            context, captured=captured, expected_gate_data=data, expected_catalog_record=catalog
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "gate-fail",
        "catalog-fail",
        "gate-mode",
        "catalog-mode",
        "gate-intent",
        "catalog-intent",
        "gate-sequence",
        "catalog-sequence",
        "gate-locator",
        "catalog-locator",
        "gate-signatures",
        "catalog-signatures",
        "catalog-foreign-C",
        "gate-self-C",
        "gate-run",
        "gate-expected-content",
        "catalog-expected-content",
        "noncanonical-output",
        "terminal-one-output",
        "worker-one-output",
        "worker-fail",
        "staged-other-bytes",
        "extra-journal-member",
        "unbound-context",
        "wrong-root",
    ],
)
def test_gate_pair_output_rejects_common_journal_and_coproducer_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, data, catalog, names = _gate_pair_output_fixture(tmp_path, monkeypatch)
    gate_path = context.root / "gate-input.json"
    catalog_path = context.root / "scenario-catalog.json"
    gate = json.loads(gate_path.read_bytes())
    cat = json.loads(catalog_path.read_bytes())
    selected = gate if mutation.startswith("gate-") else cat
    if mutation.endswith("-fail") and mutation != "worker-fail":
        selected["status"] = "FAIL"
    elif mutation.endswith("-mode"):
        selected["synthetic"] = False
    elif mutation.endswith("-intent"):
        selected["data"]["producer_intent_digest"] = "a" * 64
    elif mutation.endswith("-sequence"):
        selected["sequence"] += 1
    elif mutation.endswith("-locator"):
        selected["data"]["invocation_root_locator"] = "other"
    elif mutation.endswith("-signatures"):
        selected["signatures"] = [{"fixture": "unowned signature"}]
    elif mutation == "catalog-foreign-C":
        gate["data"]["scenario_catalog_digest"] = "b" * 64
    elif mutation == "gate-self-C":
        gate["data"]["gate_input_digest"] = "c" * 64
    elif mutation == "gate-run":
        gate["data"]["run_id"] = "another-fixture-run"
    elif mutation == "gate-expected-content":
        data = {**data, "run_id": "different-independent-content"}
    elif mutation == "catalog-expected-content":
        catalog = copy.deepcopy(catalog)
        catalog["data"]["run_id"] = "different-independent-catalog"
    elif mutation == "terminal-one-output":
        p = context.directory / "invocation.json"
        t = json.loads(p.read_bytes())
        t["data"]["outputs"].pop()
        t["data"]["invocation_digest"] = release.sha256_json(
            {k: v for k, v in t["data"].items() if k != "invocation_digest"}
        )
        _index_command_reseal(t)
        p.chmod(0o600)
        p.write_bytes(release.canonical_json(t))
        _gate_fixture_synthetic_witness(context)
    elif mutation in {"worker-one-output", "worker-fail"}:
        p = context.directory / "worker-result.json"
        w = json.loads(p.read_bytes())
        if mutation == "worker-one-output":
            w["outputs"].pop()
        else:
            w["exit_code"] = 1
            w["outputs"] = []
        p.write_bytes(release.canonical_json(w))
    elif mutation == "staged-other-bytes":
        (context.directory / "staged/scenario-catalog.json").write_bytes(b"{}")
    elif mutation == "extra-journal-member":
        p = context.directory / "unowned.json"
        p.write_bytes(b"{}")
        names.append(p.relative_to(context.root).as_posix())
    elif mutation == "unbound-context":
        intent = copy.deepcopy(context.intent)
        intent["tool_version"] += "-changed"
        context = release.ReleaseInvocation(context.directory, context.root, intent)
    elif mutation == "wrong-root":
        context = release.ReleaseInvocation(context.directory, tmp_path, context.intent)
    _index_command_reseal(gate)
    _index_command_reseal(cat)
    if mutation.endswith("-signatures"):
        selected = gate if mutation.startswith("gate-") else cat
        subject = release.signature_subject_digest(selected)
        selected["signatures"] = [
            {
                "actor_id": "fixture-unowned-gate-signer",
                "provider": "test-fixture",
                "algorithm": "test-sha256-v1",
                "synthetic": True,
                "subject_digest": subject,
                "signature": release.sha256_json(
                    {
                        "actor_id": "fixture-unowned-gate-signer",
                        "subject_digest": subject,
                    }
                ),
            }
        ]
        selected["record_id"] = release.sha256_json(
            {k: v for k, v in selected.items() if k != "record_id"}
        )
        release.validate_record(selected)
    gate_path.write_bytes(release.canonical_json(gate))
    catalog_path.write_bytes(release.canonical_json(cat))
    if mutation == "noncanonical-output":
        gate_path.write_bytes(json.dumps(gate, indent=2).encode())
    captured = _gate_pair_output_capture(gate_path.parent, names)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_pair_output_replay(
            context, captured=captured, expected_gate_data=data, expected_catalog_record=catalog
        )


@pytest.mark.parametrize("replacement", ["directory", "inode"])
def test_gate_pair_output_held_identity_rejects_replacement_before_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    context, data, catalog, names = _gate_pair_output_fixture(tmp_path, monkeypatch)
    captured = _gate_pair_output_capture(context.root, names)
    old = context.root / "gate-input.json"
    original_bytes = old.read_bytes()
    if replacement == "directory":
        import shutil

        context.root.rename(tmp_path / "removed")
        shutil.copytree(tmp_path / "removed", context.root)
    else:
        old.unlink()
        old.write_bytes(original_bytes)
    reads = 0
    foreign_reads = 0
    replacement_identity = (old.stat().st_dev, old.stat().st_ino)
    real_read = release.os.read

    def count_read(fd: int, size: int) -> bytes:
        nonlocal reads, foreign_reads
        reads += 1
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) == replacement_identity:
            foreign_reads += 1
        return real_read(fd, size)

    monkeypatch.setattr(release.os, "read", count_read)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_pair_output_replay(
            context, captured=captured, expected_gate_data=data, expected_catalog_record=catalog
        )
    assert foreign_reads == 0
    if replacement == "directory":
        assert reads == 0


def _source_content_reseal(record: dict[str, Any], self_field: str | None = None) -> None:
    data = record["data"]
    if self_field:
        data[self_field] = release.sha256_json({k: v for k, v in data.items() if k != self_field})
    newer = release.make_record(
        record["record_type"],
        data,
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=record["synthetic"],
        status=record["status"],
        signatures=record["signatures"],
    )
    record.clear()
    record.update(newer)


def _source_content_fixture(
    *, generic: bool = False, bootstrap: bool = False, conflict: str | None = None
) -> dict[str, Any]:
    context, context_inputs = _context_policy_fixture()
    baseline = context["data"]["comparison_baseline"]
    baseline["normalized_package_version"] = "0.3.0" if bootstrap else "0.4.0.post2"
    baseline["release_tag"] = "v" + baseline["normalized_package_version"]
    for item in baseline["artifacts"]:
        item["filename"] = (
            "metriplane-"
            + baseline["normalized_package_version"]
            + ("-py3-none-any.whl" if item["kind"] == "wheel" else ".tar.gz")
        )
    if generic or bootstrap:
        context["data"]["target_policy"].update(
            resolution_mode="next_unused_same_milestone_patch",
            conflict_disposition="DURABLE_BURN_THEN_SAME_MILESTONE_PATCH",
        )
    if bootstrap:
        context["data"]["target_policy"].update(
            initial_normalized_package_version="0.4.0", initial_release_tag="v0.4.0"
        )
    context = _reseal_context_policy_fixture(context, context_inputs, amend_selected_policy=True)
    controls = _target_control_fixture()
    controls["context"] = context
    controls["expected_context_digest"] = release.sha256_json(context)
    initial = context["data"]["target_policy"]["initial_normalized_package_version"]
    od = controls["observations"]["data"]
    od["original_release_context"]["record_digest"] = release.sha256_json(context)
    for row in od["targets"]:
        row.update(state="unused", version=initial, artifacts=[])
    controls["lineage"]["data"]["burns"] = []
    controls["expected_operation_order"] = []
    controls["expected_versions"] = [initial]
    if generic and (not bootstrap):
        first = copy.deepcopy(od["targets"])
        for row in first:
            row["state"] = "occupied"
        for row in od["targets"]:
            row["version"] = "0.4.2"
        od["targets"] = first + od["targets"]
        controls["expected_versions"].append("0.4.2")
    if conflict:
        od["targets"][0]["state"] = "occupied"
        if conflict in ("already-indexed", "historical-absence"):
            controls["lineage"]["data"]["burns"] = [
                {
                    "burn_manifest_digest": "a" * 64,
                    "index_receipt_digest": "b" * 64,
                    "observation_digest": "c" * 64,
                    "package_version": initial,
                    "release_tag": "v" + initial,
                    "sequence": 1,
                    "target_id": od["targets"][0]["target_id"],
                }
            ]
            controls["expected_operation_order"] = ["b" * 64]
        if conflict == "historical-absence":
            od["targets"][0]["state"] = "unused"
    for name, self_field, expected in [
        ("observations", "observation_digest", "expected_observations_digest"),
        ("lineage", "lineage_digest", "expected_lineage_digest"),
    ]:
        _source_content_reseal(controls[name], self_field)
        controls[expected] = release.sha256_json(controls[name])
    target_data, usable = release._release_target_control_data(
        "release-target-resolution", **controls
    )
    target = release.make_record(
        "release-target-resolution",
        target_data,
        invocation_id="fixture-target",
        sequence=4,
        synthetic=True,
    )
    cat_data = {
        "catalog_digest": "",
        "expansion_contract": "metriplane.scenario-expansion.v1",
        "producer_intent_digest": "d" * 64,
        "invocation_root_locator": "invocations",
        "run_id": "synthetic-source-run",
        "scenario_registry_digest": "1" * 64,
        "environment_registry_digest": "2" * 64,
        "obligation_registry_digest": "3" * 64,
        "declarations": {},
        "release_slots": [],
        "execution_units": [],
        "unresolved_declarations": [],
    }
    catalog = release.make_record(
        "release-scenario-catalog",
        cat_data,
        invocation_id="fixture-gate",
        sequence=7,
        synthetic=True,
    )
    _source_content_reseal(catalog, "catalog_digest")
    gate_data = {k: "e" * 64 for k in release._SOURCE_REGISTRY_INPUTS}
    for k in (
        "scenario_registry_digest",
        "environment_registry_digest",
        "obligation_registry_digest",
    ):
        gate_data[k] = cat_data[k]
    gate_data.update(
        expected_predecessor_milestone="v0.3.0" if bootstrap else "v0.4",
        gate_input_digest="",
        invocation_root_locator="invocations",
        linear_snapshot_digest=context["data"]["linear_snapshot_digest"],
        milestone="v0.4",
        predecessor_policy_digest=context["data"]["predecessor_policy_digest"],
        producer_intent_digest="d" * 64,
        readiness_registry_digest=context["data"]["readiness_registry_digest"],
        release_context_digest=release.sha256_json(context),
        role_assignments_digest="8" * 64,
        run_id="synthetic-source-run",
        scenario_catalog_digest=release.sha256_json(catalog),
        target_burn_digest="9" * 64,
        target_burn_index_receipt_digest="f" * 64 if target_data["requires_new_burn"] else None,
        target_registry_digest=controls["expected_target_registry_digest"],
        target_resolution_digest=release.sha256_json(target),
        task_state_policy_digest=context_inputs["linear_snapshot"]["data"][
            "task_state_policy_digest"
        ],
    )
    gate = release.make_record(
        "release-gate-input", gate_data, invocation_id="fixture-gate", sequence=7, synthetic=True
    )
    _source_content_reseal(gate, "gate_input_digest")
    return {
        "gate": gate,
        "target": target,
        "context": context,
        "catalog": catalog,
        "expected_record_digests": {
            "gate-input": release.sha256_json(gate),
            "target-resolution": release.sha256_json(target),
            "release-context": release.sha256_json(context),
            "scenario-catalog": release.sha256_json(catalog),
        },
        "run_id": "synthetic-source-run",
        "synthetic": True,
        "context_policy_inputs": context_inputs,
        "target_control_inputs": {
            k: v
            for k, v in controls.items()
            if k not in ("context", "expected_context_digest", "producer_intent_digest")
        },
    }


def _source_content_refresh(a: dict[str, Any], name: str) -> None:
    self_field = {
        "gate": "gate_input_digest",
        "target": "resolution_digest",
        "context": "context_digest",
        "catalog": "catalog_digest",
    }[name]
    _source_content_reseal(a[name], self_field)
    key = {
        "gate": "gate-input",
        "target": "target-resolution",
        "context": "release-context",
        "catalog": "scenario-catalog",
    }[name]
    a["expected_record_digests"][key] = release.sha256_json(a[name])
    if name != "gate":
        a["gate"]["data"][
            {
                "target": "target_resolution_digest",
                "context": "release_context_digest",
                "catalog": "scenario_catalog_digest",
            }[name]
        ] = release.sha256_json(a[name])
        if name == "context":
            a["target"]["data"]["release_context_digest"] = release.sha256_json(a[name])
            _source_content_refresh(a, "target")
        _source_content_refresh(a, "gate")


def test_source_content_current_exact_target_content_and_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = copy.deepcopy(_source_content_fixture())
    original = copy.deepcopy(a)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pure source content attempted filesystem/process IO")

    for name in ("_safe_release_bytes", "_source_blob", "_source_git", "_release_held_path"):
        monkeypatch.setattr(release, name, forbidden)
    g, t = release._release_source_input_content(**a)
    assert a == original
    assert len(g) == 21 and len(t) == 15
    assert t["selected_package_version"] == "v0.4.1"
    assert t["resolution_rule"] == "owner_approved_exact_target"


@pytest.mark.parametrize(
    "generic,bootstrap,version", [(True, False, "v0.4.2"), (True, True, "v0.4.0")]
)
def test_source_content_explicit_generic_and_original_bootstrap(
    generic: bool, bootstrap: bool, version: str
) -> None:
    a = _source_content_fixture(generic=generic, bootstrap=bootstrap)
    g, t = release._release_source_input_content(**a)
    assert t["selected_package_version"] == version
    assert g["expected_predecessor_milestone"] == ("v0.3.0" if bootstrap else "v0.4")


@pytest.mark.parametrize("conflict", ["new", "already-indexed", "historical-absence"])
def test_source_content_exact_conflict_never_authorizes_source_after_burn(conflict: str) -> None:
    a = _source_content_fixture(conflict=conflict)
    assert a["target"]["data"]["requires_new_burn"] is (conflict == "new")
    with pytest.raises(release.ReleaseControlError, match="occupied or previously burned"):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("name", ["gate", "target"])
def test_source_content_old_payload_cannot_be_a_fallback(name: str) -> None:
    a = copy.deepcopy(_source_content_fixture())
    for k in ("producer_intent_digest", "invocation_root_locator", "release_context_digest"):
        del a[name]["data"][k]
    _source_content_refresh(a, name)
    with pytest.raises(release.ReleaseControlError, match="shape"):
        release._release_source_input_content(**a)


@pytest.mark.parametrize(
    "name,field",
    [
        (name, field)
        for name in ("gate", "target")
        for field in _source_content_fixture()[name]["data"]
    ],
)
def test_source_content_every_required_gate_target_field_is_enforced(name: str, field: str) -> None:
    a = copy.deepcopy(_source_content_fixture())
    del a[name]["data"][field]
    _source_content_reseal(a[name])
    a["expected_record_digests"]["gate-input" if name == "gate" else "target-resolution"] = (
        release.sha256_json(a[name])
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("gate", "extra", True),
        ("target", "extra", True),
        ("gate", "release_context_digest", "0" * 64),
        ("target", "release_context_digest", "0" * 64),
        ("gate", "scenario_catalog_digest", "0" * 64),
        ("gate", "target_resolution_digest", "0" * 64),
        ("gate", "linear_snapshot_digest", "0" * 64),
        ("gate", "readiness_registry_digest", "0" * 64),
        ("gate", "predecessor_policy_digest", "0" * 64),
        ("gate", "task_state_policy_digest", "0" * 64),
        ("gate", "target_registry_digest", "0" * 64),
        ("gate", "run_id", "other-run"),
        ("gate", "milestone", "v0.5"),
        ("target", "milestone", "v0.5"),
        ("target", "requires_new_burn", 1),
        ("gate", "target_burn_index_receipt_digest", "0" * 64),
        ("target", "resolution_rule", "next_unused_same_milestone_patch"),
        ("target", "selected_package_version", "v0.4.2"),
        ("target", "selected_release_tag", "v0.4.2"),
        ("target", "initial_package_version", "v0.4.0"),
        ("target", "initial_release_tag", "v0.4.0"),
        ("target", "burn_lineage_digest", "0" * 64),
        ("target", "observations_digest", "0" * 64),
        ("target", "burn_target_ids", ["pypi"]),
        ("target", "prior_burn_digests", ["0" * 64]),
        ("catalog", "run_id", "other-run"),
        ("catalog", "producer_intent_digest", "0" * 64),
        ("catalog", "scenario_registry_digest", "0" * 64),
        ("catalog", "environment_registry_digest", "0" * 64),
        ("catalog", "obligation_registry_digest", "0" * 64),
        ("catalog", "expansion_contract", "other"),
    ],
)
def test_source_content_consistent_envelope_rewrites_do_not_change_crosslinks(
    name: str, field: str, value: Any
) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a[name]["data"][field] = value
    _source_content_refresh(a, name)
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("name", ["gate", "target", "catalog"])
@pytest.mark.parametrize(
    "locator",
    [
        "../invocations",
        "/invocations",
        "C:\\invocations",
        "invocations\\staged",
        "invocations/../other",
        "invocations\x00",
        "./invocations",
        None,
    ],
)
def test_source_content_platform_locator_aliases_never_resolve(name: str, locator: Any) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a[name]["data"]["invocation_root_locator"] = locator
    _source_content_refresh(a, name)
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize(
    "version",
    ["0.4.1", "vv0.4.1", "v0.4.01", "v0.4.1.post2", "v0.4.1rc1", "v0.4.１", "v0.4.1\n", None, 4],
)
def test_source_content_legacy_wire_uses_strict_normalized_version_owner(version: Any) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a["target"]["data"]["selected_package_version"] = version
    a["target"]["data"]["selected_release_tag"] = version
    _source_content_refresh(a, "target")
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("name", ["gate", "target", "context", "catalog"])
@pytest.mark.parametrize(
    "field,value", [("status", "FAIL"), ("synthetic", False), ("sequence", True)]
)
def test_source_content_original_envelope_modes_and_counters(
    name: str, field: str, value: Any
) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a[name][field] = value
    if field == "sequence":
        with pytest.raises(release.ReleaseControlError):
            _source_content_reseal(a[name])
        return
    _source_content_refresh(a, name)
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("field,value", [("invocation_id", "other-original"), ("sequence", 8)])
def test_source_content_catalog_is_same_original_gate_producer(field: str, value: Any) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a["catalog"][field] = value
    _source_content_refresh(a, "catalog")
    with pytest.raises(release.ReleaseControlError, match="producer companion"):
        release._release_source_input_content(**a)


@pytest.mark.parametrize(
    "location", ["expected_record_digests", "context_policy_inputs", "target_control_inputs"]
)
def test_source_content_closed_original_input_namespaces(location: str) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a[location]["unlisted"] = "0" * 64
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize(
    "location,field,value",
    [
        ("context_policy_inputs", "expected_context_id", "unapproved"),
        ("context_policy_inputs", "readiness_registry_raw", b"changed"),
        ("context_policy_inputs", "predecessor_policy_raw", b"changed"),
        ("target_control_inputs", "expected_versions", ["0.4.0"]),
        ("target_control_inputs", "target_registry_raw", b"changed"),
        ("target_control_inputs", "expected_observations_digest", "0" * 64),
        ("target_control_inputs", "expected_lineage_digest", "0" * 64),
        ("target_control_inputs", "expected_operation_order", ["0" * 64]),
    ],
)
def test_source_content_independent_expected_originals_cannot_drift(
    location: str, field: str, value: Any
) -> None:
    a = copy.deepcopy(_source_content_fixture())
    a[location][field] = value
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("target_state", ["UNKNOWN", "unused-but-assumed", None])
def test_source_content_unobserved_target_never_becomes_complete(target_state: Any) -> None:
    a = copy.deepcopy(_source_content_fixture())
    obs = a["target_control_inputs"]["observations"]
    obs["data"]["targets"][0]["state"] = target_state
    _source_content_reseal(obs, "observation_digest")
    a["target_control_inputs"]["expected_observations_digest"] = release.sha256_json(obs)
    with pytest.raises(release.ReleaseControlError):
        release._release_source_input_content(**a)


@pytest.mark.parametrize("name", ["target", "catalog"])
def test_source_content_producer_owned_unsigned_shape_is_not_signed_authority(name: str) -> None:
    a = copy.deepcopy(_source_content_fixture())
    record = a[name]
    subject = release.signature_subject_digest(record)
    record["signatures"] = [
        {
            "actor_id": "explicit-synthetic-content-fixture",
            "algorithm": "test-sha256-v1",
            "provider": "test-fixture",
            "signature": release.sha256_json(
                {"actor_id": "explicit-synthetic-content-fixture", "subject_digest": subject}
            ),
            "subject_digest": subject,
            "synthetic": True,
        }
    ]
    _source_content_refresh(a, name)
    release._validated_record_signers(a[name], live=False)
    with pytest.raises(release.ReleaseControlError, match="has signatures"):
        release._release_source_input_content(**a)


def _gate_copy_install_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, new_burn: bool = False
) -> tuple[
    release.ReleaseInvocation, dict[str, Any], dict[str, Any], list[str], list[dict[str, str]]
]:
    """Actual copy/terminal owners over synthetic mechanical fixtures, not native gate authority."""
    context, data, catalog, names = _gate_pair_output_fixture(
        tmp_path, monkeypatch, new_burn=new_burn
    )
    terminal = json.loads((context.directory / "invocation.json").read_bytes())
    for row in terminal["data"]["outputs"]:
        (context.root / row["path"]).unlink()
    (context.directory / "invocation.json").unlink()
    (context.directory / "terminal-commit.json").unlink()
    _gate_fixture_remember_stage(context, monkeypatch)
    return context, data, catalog, names, terminal["data"]["outputs"]


@pytest.mark.parametrize("new_burn", [False, True])
@pytest.mark.parametrize("relocate", [False, True])
def test_gate_copy_install_single_link_outputs_replay_with_common_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_burn: bool, relocate: bool
) -> None:
    context, data, catalog, names, outputs = _gate_copy_install_fixture(
        tmp_path, monkeypatch, new_burn=new_burn
    )
    if relocate:
        current = tmp_path / "relocated"
        context.root.rename(current)
        context = release.ReleaseInvocation(
            current / context.directory.relative_to(context.root), current, context.intent
        )
    release._install_release_outputs(
        context, outputs, gate_stage_capture=_gate_fixture_carried_stage(context)
    )
    for row in outputs:
        staged = context.directory / "staged" / row["path"]
        canonical = context.root / row["path"]
        assert staged.read_bytes() == canonical.read_bytes()
        assert staged.stat().st_nlink == canonical.stat().st_nlink == 1
        assert (staged.stat().st_dev, staged.stat().st_ino) != (
            canonical.stat().st_dev,
            canonical.stat().st_ino,
        )
        assert canonical.stat().st_mode & 0o777 == 0o400
    assert not (context.directory / "invocation.json").exists()
    _gate_fixture_terminal_content(context, 0, outputs, monkeypatch)
    _gate_fixture_synthetic_witness(context)
    captured = _gate_pair_output_capture(context.root, names)
    actual = release._release_gate_pair_output_replay(
        context, captured=captured, expected_gate_data=data, expected_catalog_record=catalog
    )
    assert actual["gate_record"]["data"] == data
    assert actual["catalog_record"] == catalog
    with pytest.raises(release.ReleaseControlError, match="existing terminal"):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )


@pytest.mark.parametrize("name", ["gate-input.json", "scenario-catalog.json"])
@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_gate_copy_install_never_overwrites_any_preexisting_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, kind: str
) -> None:
    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    p = context.root / name
    if kind == "file":
        p.write_bytes(b"original unrelated bytes")
    elif kind == "directory":
        p.mkdir()
    else:
        p.symlink_to("missing-original")
    original = p.lstat()
    with pytest.raises(
        release.ReleaseControlError, match="unsafe" if kind == "symlink" else "overwrite"
    ):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    assert p.lstat() == original
    assert not (
        context.root / ("scenario-catalog.json" if name == "gate-input.json" else "gate-input.json")
    ).exists()
    assert not (context.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-tool",
        "wrong-root",
        "one-output",
        "reordered",
        "extra-field",
        "wrong-type",
        "wrong-R",
        "changed-context",
        "changed-staged",
        "noncanonical-staged",
        "hardlinked-staged",
        "premature-terminal",
        "missing-staged",
    ],
)
def test_gate_copy_install_rejects_bad_plan_and_staged_originals_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    p = context.directory / "staged/gate-input.json"
    if mutation == "wrong-tool":
        context = release.ReleaseInvocation(
            context.directory, context.root, {**context.intent, "tool": "freeze_release_source.py"}
        )
    elif mutation == "wrong-root":
        context = release.ReleaseInvocation(context.directory, tmp_path, context.intent)
    elif mutation == "one-output":
        outputs.pop()
    elif mutation == "reordered":
        outputs.reverse()
    elif mutation == "extra-field":
        outputs[0]["extra"] = "unowned"
    elif mutation == "wrong-type":
        outputs[0]["schema_id"] = "metriplane.release-scenario-catalog.v1"
    elif mutation == "wrong-R":
        outputs[0]["sha256"] = "0" * 64
    elif mutation == "changed-context":
        context = release.ReleaseInvocation(
            context.directory, context.root, {**context.intent, "tool_version": "unowned"}
        )
    elif mutation == "changed-staged":
        value = json.loads(p.read_bytes())
        value["synthetic"] = False
        _index_command_reseal(value)
        p.write_bytes(release.canonical_json(value))
        outputs[0]["sha256"] = release.sha256_bytes(p.read_bytes())
    elif mutation == "noncanonical-staged":
        p.write_bytes(json.dumps(json.loads(p.read_bytes()), indent=2).encode())
        outputs[0]["sha256"] = release.sha256_bytes(p.read_bytes())
    elif mutation == "hardlinked-staged":
        os.link(p, tmp_path / "staged-alias")
    elif mutation == "premature-terminal":
        (context.directory / "invocation.json").write_bytes(b"{}")
    elif mutation == "missing-staged":
        p.unlink()
    with pytest.raises(release.ReleaseControlError):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    assert not (p.parents[4] / "gate-input.json").exists()
    assert not (p.parents[4] / "scenario-catalog.json").exists()


@pytest.mark.parametrize("failed_file", [1, 2])
def test_gate_copy_install_retains_original_files_after_fsync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_file: int
) -> None:
    import stat

    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    actual_fsync = os.fsync
    file_syncs = 0

    def fail(fd: int) -> None:
        nonlocal file_syncs
        if stat.S_ISREG(os.fstat(fd).st_mode):
            file_syncs += 1
            if file_syncs == failed_file:
                raise OSError("synthetic gate payload fsync failure")
        actual_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="synthetic gate payload"):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    for row in outputs[:failed_file]:
        p = context.root / row["path"]
        assert p.read_bytes() == (context.directory / "staged" / row["path"]).read_bytes()
        assert p.stat().st_nlink == 1
    if failed_file == 1:
        assert not (context.root / "scenario-catalog.json").exists()
    assert not (context.directory / "invocation.json").exists()
    monkeypatch.setattr(os, "fsync", actual_fsync)
    with pytest.raises(release.ReleaseControlError, match="overwrite"):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )


def test_gate_copy_install_retains_partial_write_and_never_fills_it_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    original_fdopen = os.fdopen

    class Partial:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.stream = original_fdopen(*args, **kwargs)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            self.stream.close()

        def write(self, raw: bytes) -> None:
            self.stream.write(raw[:25])
            self.stream.flush()
            raise OSError("synthetic partial gate copy")

    monkeypatch.setattr(os, "fdopen", Partial)
    with pytest.raises(OSError, match="synthetic partial gate"):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    actual = context.root / "gate-input.json"
    original = (context.directory / "staged/gate-input.json").read_bytes()
    assert actual.read_bytes() == original[:25]
    assert not (context.root / "scenario-catalog.json").exists()
    assert not (context.directory / "invocation.json").exists()
    monkeypatch.setattr(os, "fdopen", original_fdopen)
    with pytest.raises(release.ReleaseControlError, match="overwrite"):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    assert actual.read_bytes() == original[:25]


def test_gate_copy_install_rejects_stage_replacement_between_copies_before_foreign_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat

    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    p = context.directory / "staged/scenario-catalog.json"
    original = p.read_bytes()
    actual_fsync = os.fsync
    actual_read = os.read
    foreign: tuple[int, int] | None = None
    foreign_reads = 0

    def swap(fd: int) -> None:
        nonlocal foreign
        actual_fsync(fd)
        if foreign is None and stat.S_ISREG(os.fstat(fd).st_mode):
            p.rename(p.with_name("preserved-original-catalog"))
            p.write_bytes(original)
            foreign = (p.stat().st_dev, p.stat().st_ino)

    def read(fd: int, size: int) -> bytes:
        nonlocal foreign_reads
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) == foreign:
            foreign_reads += 1
        return actual_read(fd, size)

    monkeypatch.setattr(os, "fsync", swap)
    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    assert foreign is not None and foreign_reads == 0
    assert (context.root / "gate-input.json").exists()
    assert not (context.root / "scenario-catalog.json").exists()
    assert not (context.directory / "invocation.json").exists()


_PREDECESSOR_CONTENT_TEST_ROOT_TYPES = {
    "qualification_digest": "release-qualification",
    "reconciliation_digest": "release-publication-reconciliation",
    "final_retention_digest": "release-retention-receipts",
    "chain_receipt_digest": "release-evidence-chain",
    "lkg_digest": "release-last-known-good",
    "pointer_transition_retention_digest": "release-retention-receipts",
    "pointer_envelope_digest": "release-evidence-manifest",
    "pointer_retention_digest": "release-retention-receipts",
    "pointer_index_receipt_digest": "release-attempt-index",
    "closed_decision_digest": "release-protected-input",
    "close_ready_observation_digest": "release-task-state-observation",
    "close_root_digest": "release-attempt-index",
}


def _predecessor_content_reseal(record: dict[str, Any]) -> None:
    n = release.make_record(
        record["record_type"],
        record["data"],
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=record["synthetic"],
        status=record["status"],
        signatures=record["signatures"],
    )
    record.clear()
    record.update(n)


def _predecessor_content_ref(path: str, raw: bytes) -> dict[str, Any]:
    return {"path": path, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}


def _predecessor_original_custody_fixture(root: Path) -> Path:
    originals = {
        "raw/provider.json": b"provider-state\n",
        "git/blob": b"git object payload\n",
        "artifacts/package.whl": b"wheel bytes\n",
        "artifacts/package.tar.gz": b"sdist bytes\n",
    }
    for name, raw in originals.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git_raw = originals["git/blob"]
    git_oid = hashlib.sha1(
        f"blob {len(git_raw)}\0".encode("ascii") + git_raw, usedforsecurity=False
    ).hexdigest()
    proof = {
        "schema_version": "metriplane.release-predecessor-proof-index.v1",
        "records": [],
        "raw_proofs": [
            {
                "kind": "original_provider_state_readback",
                "purpose": "fixture custody",
                "original_file": _predecessor_content_ref(
                    "raw/provider.json", originals["raw/provider.json"]
                ),
            }
        ],
        "git_objects": [
            {
                "kind": "original_git_object",
                "object_type": "blob",
                "git_object_id": git_oid,
                "original_file": _predecessor_content_ref("git/blob", git_raw),
            }
        ],
        "artifacts": [
            {
                "kind": "original_distribution_payload",
                "artifact_kind": kind,
                "filename": name,
                "original_file": _predecessor_content_ref(path, originals[path]),
            }
            for kind, name, path in (
                ("wheel", "package.whl", "artifacts/package.whl"),
                ("sdist", "package.tar.gz", "artifacts/package.tar.gz"),
            )
        ],
    }
    path = root / "inputs/proof-index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(release.canonical_json(proof))
    return path


def test_predecessor_original_custody_reads_every_exact_indexed_byte(tmp_path: Path) -> None:
    proof_path = _predecessor_original_custody_fixture(tmp_path)
    proof, records = release._release_predecessor_proof_originals(tmp_path, proof_path)
    assert proof["schema_version"] == "metriplane.release-predecessor-proof-index.v1"
    assert records == {}


@pytest.mark.parametrize("mutation", ["bytes", "git-object", "alias"])
def test_predecessor_original_custody_rejects_substitution(tmp_path: Path, mutation: str) -> None:
    proof_path = _predecessor_original_custody_fixture(tmp_path)
    if mutation == "bytes":
        (tmp_path / "raw/provider.json").write_bytes(b"changed\n")
    else:
        proof = json.loads(proof_path.read_bytes())
        if mutation == "git-object":
            proof["git_objects"][0]["git_object_id"] = "0" * 40
        else:
            proof["artifacts"][1]["original_file"] = copy.deepcopy(
                proof["artifacts"][0]["original_file"]
            )
        proof_path.write_bytes(release.canonical_json(proof))
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_proof_originals(tmp_path, proof_path)


def _predecessor_reconciled_graph_fixture() -> tuple[
    dict[tuple[str, str], tuple[Path, dict[str, Any]]], dict[str, Any], dict[str, str]
]:
    originals: dict[tuple[str, str], tuple[Path, dict[str, Any]]] = {}

    def add(record_type: str, data: dict[str, Any]) -> str:
        record = {
            "record_type": record_type,
            "status": "PASS",
            "synthetic": True,
            "data": data,
        }
        digest = release.sha256_json(record)
        originals[(record_type, digest)] = (Path("/retained") / digest, record)
        return digest

    candidate_id = "1" * 64
    source_digest = add(
        "release-source-freeze",
        {
            "dirty": False,
            "milestone": "v0.4",
            "source_sha": "a" * 40,
            "source_tree": "b" * 40,
        },
    )
    artifact_digest = add(
        "release-artifact-manifest",
        {"milestone": "v0.4", "artifacts": "validated-by-common-owner"},
    )
    candidate_digest = add(
        "release-candidate-identity",
        {
            "candidate_digest": candidate_id,
            "milestone": "v0.4",
            "package_version": "v0.4.0.post2",
            "release_tag": "v0.4.0.post2",
            "source_freeze_digest": source_digest,
            "artifact_manifest_digest": artifact_digest,
        },
    )
    qualification_digest = add(
        "release-qualification", {"candidate_digest": candidate_id, "milestone": "v0.4"}
    )
    evidence_manifest_digest = add(
        "release-evidence-manifest",
        {
            "phase": "qualified-publication",
            "candidate_digest": candidate_id,
            "entries": [{"sha256": qualification_digest}],
        },
    )
    reconciliation_digest = add(
        "release-publication-reconciliation",
        {
            "candidate_digest": candidate_id,
            "milestone": "v0.4",
            "qualification_digest": qualification_digest,
            "evidence_manifest_digest": evidence_manifest_digest,
            "result": "RECONCILED",
            "burn_required": False,
            "partial_targets": [],
        },
    )
    final_retention_digest = add(
        "release-retention-receipts",
        {"phase": "final", "input_digest": evidence_manifest_digest},
    )
    chain_head = "2" * 64
    chain_digest = add(
        "release-evidence-chain",
        {
            "backend_id": "success-chain",
            "candidate_digest": candidate_id,
            "reconciliation_digest": reconciliation_digest,
            "final_receipts_digest": final_retention_digest,
            "committed_head": chain_head,
            "read_back_digest": chain_head,
            "disposition": "committed",
            "evidence_manifest_digest": evidence_manifest_digest,
            "expected_head": None,
            "generation": 1,
            "milestone": "v0.4",
            "operation_id": "chain-1",
            "previous_head": None,
        },
    )
    lkg_digest = add(
        "release-last-known-good",
        {
            "backend_id": "last-known-good",
            "candidate_digest": candidate_id,
            "chain_head": chain_head,
            "committed_token": "token-1",
            "expected_generation": 0,
            "invalidation_decision_digest": None,
            "milestone": "v0.4",
            "new_generation": 1,
            "operation_id": "lkg-1",
            "previous_release_digest": None,
            "read_back_digest": "3" * 64,
            "reconciliation_digest": reconciliation_digest,
            "state": "LKG",
        },
    )
    transition_retention_digest = add(
        "release-retention-receipts",
        {"phase": "pointer-transition", "input_digest": lkg_digest},
    )
    pointer_manifest_digest = add(
        "release-evidence-manifest",
        {
            "phase": "pointer-transition",
            "candidate_digest": candidate_id,
            "entries": [{"sha256": lkg_digest}, {"sha256": transition_retention_digest}],
        },
    )
    pointer_retention_digest = add(
        "release-retention-receipts",
        {"phase": "pointer-transition-envelope", "input_digest": pointer_manifest_digest},
    )
    pointer_index_digest = add(
        "release-attempt-index",
        {
            "kind": "update_receipt",
            "scope_kind": "release_candidate",
            "stage": "pointer-transition",
            "entry_manifest_digest": pointer_manifest_digest,
            "entry_receipts_digest": pointer_retention_digest,
            "candidate_id": candidate_id,
        },
    )
    observation_digest = add(
        "release-task-state-observation",
        {
            "candidate_digest": candidate_id,
            "latest_pointer_index_digest": pointer_index_digest,
            "phase": "close-ready",
        },
    )
    close_manifest_digest = add(
        "release-evidence-manifest",
        {
            "phase": "release-finalizing-observation",
            "candidate_digest": candidate_id,
            "entries": [
                {"sha256": observation_digest},
                {"sha256": pointer_index_digest},
            ],
        },
    )
    close_retention_digest = add(
        "release-retention-receipts",
        {"phase": "release-task-finalizing", "input_digest": close_manifest_digest},
    )
    close_root_digest = add(
        "release-attempt-index",
        {
            "kind": "update_receipt",
            "scope_kind": "release_candidate",
            "stage": "release-task-finalizing",
            "entry_manifest_digest": close_manifest_digest,
            "entry_receipts_digest": close_retention_digest,
            "candidate_id": candidate_id,
        },
    )
    decision_identity = {
        "provider": "linear",
        "team_id": "00000000-0000-0000-0000-000000000001",
        "project_id": "00000000-0000-0000-0000-000000000002",
        "issue_id": "00000000-0000-0000-0000-000000000003",
        "issue_identifier": "MET-3",
    }
    closed_digest = add(
        "release-protected-input",
        {
            "input_kind": "task_state_transition",
            "transition_kind": "release_decision_closed",
            "decision": "CLOSED",
            "subject_digests": [
                {"subject": "predecessor_candidate_identity", "sha256": candidate_digest},
                {
                    "subject": "decision_identity",
                    "sha256": release.sha256_json(decision_identity),
                },
                {"subject": "role_assignments", "sha256": "6" * 64},
                {"subject": "task_state_policy_registry", "sha256": "7" * 64},
                {"subject": "durable_close_root", "sha256": close_root_digest},
                {"subject": "original_provider_close_event", "sha256": "8" * 64},
            ],
        },
    )
    expected = {
        "qualification_digest": qualification_digest,
        "reconciliation_digest": reconciliation_digest,
        "final_retention_digest": final_retention_digest,
        "chain_receipt_digest": chain_digest,
        "chain_head": chain_head,
        "lkg_digest": lkg_digest,
        "pointer_transition_retention_digest": transition_retention_digest,
        "pointer_envelope_digest": pointer_manifest_digest,
        "pointer_retention_digest": pointer_retention_digest,
        "pointer_index_receipt_digest": pointer_index_digest,
        "closed_decision_digest": closed_digest,
        "close_ready_observation_digest": observation_digest,
        "close_root_digest": close_root_digest,
    }
    subject = {
        "framework_milestone": "v0.4",
        "normalized_package_version": "0.4.0.post2",
        "release_tag": "v0.4.0.post2",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "artifacts": [
            {
                "kind": "wheel",
                "filename": "metriplane-0.4.0.post2-py3-none-any.whl",
                "bytes": 10,
                "sha256": "a" * 64,
            },
            {
                "kind": "sdist",
                "filename": "metriplane-0.4.0.post2.tar.gz",
                "bytes": 20,
                "sha256": "b" * 64,
            },
        ],
    }
    return originals, subject, expected


def test_predecessor_reconciled_graph_follows_complete_linked_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    originals, subject, expected = _predecessor_reconciled_graph_fixture()
    monkeypatch.setattr(
        release, "_release_predecessor_candidate_identity_payload", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        release,
        "_validate_artifact_manifest_payload",
        lambda *a, **kw: [
            {
                "path": "metriplane-0.4.0.post2-py3-none-any.whl",
                "size": 10,
                "sha256": "a" * 64,
            },
            {"path": "metriplane-0.4.0.post2.tar.gz", "size": 20, "sha256": "b" * 64},
        ],
    )
    monkeypatch.setattr(
        release,
        "_release_original_artifact_descriptors",
        lambda *a, **kw: {row["kind"]: row for row in subject["artifacts"]},
    )
    monkeypatch.setattr(release, "_release_evidence_manifest_content", lambda data: data["entries"])
    monkeypatch.setattr(
        release, "_release_predecessor_qualification_originals", lambda *a, **kw: None
    )
    monkeypatch.setattr(release, "_release_retention_content", lambda *a, **kw: None)
    monkeypatch.setattr(
        release,
        "_release_index_receipt_content",
        lambda data: {
            "scope": {"candidate_id": data["candidate_id"]},
            "entry_manifest_digest": data["entry_manifest_digest"],
            "entry_receipts_digest": data["entry_receipts_digest"],
        },
    )
    assert (
        release._release_predecessor_reconciled_graph(
            originals,
            subject=subject,
            candidate_milestone="v0.4",
            decision_identity={
                "provider": "linear",
                "team_id": "00000000-0000-0000-0000-000000000001",
                "project_id": "00000000-0000-0000-0000-000000000002",
                "issue_id": "00000000-0000-0000-0000-000000000003",
                "issue_identifier": "MET-3",
            },
        )
        == expected
    )
    static = {
        "chain_genesis_raw": Path("docs/releases/release-evidence-chain-genesis.json").read_bytes(),
        "attempt_genesis_raw": Path(
            "docs/releases/release-attempt-index-genesis.json"
        ).read_bytes(),
        "release_genesis_raw": Path("docs/releases/v0.3.0-genesis.json").read_bytes(),
        "stores_raw": Path("docs/status/release-evidence-stores.json").read_bytes(),
        "chain_backend": "success-chain",
        "attempt_index_backend": "attempt-index",
        "lkg_backend": "last-known-good",
    }
    assert release._release_predecessor_static_authorities(**static) == release.sha256_bytes(
        static["attempt_genesis_raw"]
    )
    substituted = json.loads(static["stores_raw"])
    substituted["stores"][1]["independence_group"] = substituted["stores"][0]["independence_group"]
    static["stores_raw"] = release.canonical_json(substituted)
    with pytest.raises(release.ReleaseControlError, match="aliased"):
        release._release_predecessor_static_authorities(**static)
    decision_identity = {
        "provider": "linear",
        "team_id": "00000000-0000-0000-0000-000000000001",
        "project_id": "00000000-0000-0000-0000-000000000002",
        "issue_id": "00000000-0000-0000-0000-000000000003",
        "issue_identifier": "MET-3",
    }
    decision_row = {
        "identity": decision_identity,
        "framework_milestone": "v0.4",
        "release_tag": "v0.4.0.post2",
    }
    registry_raw = release.canonical_json({"decision": decision_row})
    (tmp_path / "decision.json").write_bytes(registry_raw)
    decision = {
        "identity": decision_identity,
        "authority": {
            "raw_registry": _predecessor_content_ref("decision.json", registry_raw),
            "json_pointer": "/decision",
            "canonical_row_digest": release.sha256_json(decision_row),
        },
    }
    assert (
        release._release_predecessor_decision_authority(tmp_path, decision, subject=subject)
        == decision_identity
    )
    decision["identity"] = {**decision_identity, "issue_identifier": "MET-4"}
    with pytest.raises(release.ReleaseControlError, match="changes its selection"):
        release._release_predecessor_decision_authority(tmp_path, decision, subject=subject)


@pytest.mark.parametrize(
    "mutation",
    [
        "competing-lkg",
        "pointer-substitution",
        "final-manifest-substitution",
        "final-retention-substitution",
        "close-retention-substitution",
        "missing-chain-ancestry",
        "missing-lkg-ancestry",
        "later-chain-successor",
        "later-lkg-successor",
        "invalidation",
    ],
)
def test_predecessor_reconciled_graph_rejects_unrelated_or_later_history(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    originals, subject, expected = _predecessor_reconciled_graph_fixture()
    monkeypatch.setattr(
        release, "_release_predecessor_candidate_identity_payload", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        release,
        "_validate_artifact_manifest_payload",
        lambda *a, **kw: [
            {
                "path": "metriplane-0.4.0.post2-py3-none-any.whl",
                "size": 10,
                "sha256": "a" * 64,
            },
            {"path": "metriplane-0.4.0.post2.tar.gz", "size": 20, "sha256": "b" * 64},
        ],
    )
    monkeypatch.setattr(
        release,
        "_release_original_artifact_descriptors",
        lambda *a, **kw: {row["kind"]: row for row in subject["artifacts"]},
    )
    monkeypatch.setattr(release, "_release_evidence_manifest_content", lambda data: data["entries"])
    monkeypatch.setattr(
        release, "_release_predecessor_qualification_originals", lambda *a, **kw: None
    )
    monkeypatch.setattr(release, "_release_retention_content", lambda *a, **kw: None)
    monkeypatch.setattr(
        release,
        "_release_index_receipt_content",
        lambda data: {
            "scope": {"candidate_id": data["candidate_id"]},
            "entry_manifest_digest": data["entry_manifest_digest"],
            "entry_receipts_digest": data["entry_receipts_digest"],
        },
    )
    if mutation == "competing-lkg":
        original = copy.deepcopy(originals[("release-last-known-good", expected["lkg_digest"])][1])
        original["data"]["operation_id"] = "competing"
        digest = release.sha256_json(original)
        originals[("release-last-known-good", digest)] = (Path("/retained") / digest, original)
    elif mutation == "pointer-substitution":
        manifest = originals[("release-evidence-manifest", expected["pointer_envelope_digest"])][1]
        manifest["data"]["entries"][0]["sha256"] = "9" * 64
    elif mutation == "final-manifest-substitution":
        manifest = next(
            record
            for (kind, _), (_, record) in originals.items()
            if kind == "release-evidence-manifest"
            and record["data"].get("phase") == "qualified-publication"
        )
        manifest["data"]["candidate_digest"] = "9" * 64
    elif mutation == "final-retention-substitution":
        retention = originals[("release-retention-receipts", expected["final_retention_digest"])][1]
        retention["data"]["input_digest"] = "9" * 64
    elif mutation == "close-retention-substitution":
        retention = next(
            record
            for (kind, _), (_, record) in originals.items()
            if kind == "release-retention-receipts"
            and record["data"].get("phase") == "release-task-finalizing"
        )
        retention["data"]["input_digest"] = "9" * 64
    elif mutation == "missing-chain-ancestry":
        chain = originals[("release-evidence-chain", expected["chain_receipt_digest"])][1]
        chain["data"].update(generation=2, expected_head="9" * 64, previous_head="9" * 64)
    elif mutation == "missing-lkg-ancestry":
        lkg = originals[("release-last-known-good", expected["lkg_digest"])][1]
        lkg["data"].update(
            expected_generation=1, new_generation=2, previous_release_digest="9" * 64
        )
    elif mutation == "later-chain-successor":
        prior = originals[("release-evidence-chain", expected["chain_receipt_digest"])][1]
        successor = copy.deepcopy(prior)
        successor["data"].update(
            committed_head="9" * 64,
            read_back_digest="9" * 64,
            expected_head=prior["data"]["committed_head"],
            previous_head=prior["data"]["committed_head"],
            generation=2,
        )
        digest = release.sha256_json(successor)
        originals[("release-evidence-chain", digest)] = (Path("/retained") / digest, successor)
    elif mutation == "later-lkg-successor":
        prior = originals[("release-last-known-good", expected["lkg_digest"])][1]
        successor = copy.deepcopy(prior)
        successor["data"].update(
            expected_generation=1,
            new_generation=2,
            previous_release_digest=expected["lkg_digest"],
            operation_id="later-lkg",
        )
        digest = release.sha256_json(successor)
        originals[("release-last-known-good", digest)] = (Path("/retained") / digest, successor)
    else:
        invalidated = copy.deepcopy(
            originals[("release-last-known-good", expected["lkg_digest"])][1]
        )
        invalidated["data"].update(
            state="INVALIDATED",
            invalidation_decision_digest="9" * 64,
            previous_release_digest=expected["lkg_digest"],
            operation_id="invalidate-1",
        )
        digest = release.sha256_json(invalidated)
        originals[("release-last-known-good", digest)] = (Path("/retained") / digest, invalidated)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_reconciled_graph(
            originals,
            subject=subject,
            candidate_milestone="v0.4",
            decision_identity={
                "provider": "linear",
                "team_id": "00000000-0000-0000-0000-000000000001",
                "project_id": "00000000-0000-0000-0000-000000000002",
                "issue_id": "00000000-0000-0000-0000-000000000003",
                "issue_identifier": "MET-3",
            },
        )


def _connected_predecessor_command_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[str]]:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    root = tmp_path / "predecessor-run"
    root.mkdir()
    base = _predecessor_content_fixture()
    readiness_raw = base["context_policy_inputs"]["readiness_registry_raw"]
    linear = base["context_policy_inputs"]["linear_snapshot"]
    policy = json.loads(base["context_policy_inputs"]["predecessor_policy_raw"])
    subject = policy["expected_predecessor_subject"]

    wheel_raw = b"w" * 123
    sdist_raw = b"s" * 123
    git_raw = {"tree": b"100644 file\0" + b"1" * 20}
    source_tree = hashlib.sha1(
        f"tree {len(git_raw['tree'])}\0".encode() + git_raw["tree"],
        usedforsecurity=False,
    ).hexdigest()
    git_raw["commit"] = b"tree " + source_tree.encode() + b"\n"
    source_commit = hashlib.sha1(
        f"commit {len(git_raw['commit'])}\0".encode() + git_raw["commit"],
        usedforsecurity=False,
    ).hexdigest()
    git_raw["tag"] = b"object " + source_commit.encode() + b"\ntype commit\ntag v0.4.0.post1\n"
    subject.update(
        source_commit=source_commit,
        source_tree=source_tree,
        tag_object=hashlib.sha1(
            f"tag {len(git_raw['tag'])}\0".encode() + git_raw["tag"],
            usedforsecurity=False,
        ).hexdigest(),
        artifacts=[
            {
                "kind": "wheel",
                "filename": "metriplane-0.4.0.post1-py3-none-any.whl",
                "bytes": len(wheel_raw),
                "sha256": release.sha256_bytes(wheel_raw),
                "readback": _predecessor_content_ref("artifacts/wheel", wheel_raw),
            },
            {
                "kind": "sdist",
                "filename": "metriplane-0.4.0.post1.tar.gz",
                "bytes": len(sdist_raw),
                "sha256": release.sha256_bytes(sdist_raw),
                "readback": _predecessor_content_ref("artifacts/sdist", sdist_raw),
            },
        ],
    )
    decision_identity = policy["expected_predecessor_decision"]["identity"]
    historical_decision_row = {
        "identity": decision_identity,
        "framework_milestone": subject["framework_milestone"],
        "release_tag": subject["release_tag"],
    }
    historical_registry_raw = release.canonical_json({"original_decision": historical_decision_row})
    policy["expected_predecessor_decision"]["authority"] = {
        "raw_registry": _predecessor_content_ref(
            "original/historical-policy.json", historical_registry_raw
        ),
        "json_pointer": "/original_decision",
        "canonical_row_digest": release.sha256_json(historical_decision_row),
    }
    policy_raw = release.canonical_json(policy)
    context = json.loads(base["original_bytes"]["release_context"])
    context["data"]["predecessor_policy_digest"] = release.sha256_bytes(policy_raw)
    context["data"]["context_digest"] = release.sha256_json(
        {k: v for k, v in context["data"].items() if k != "context_digest"}
    )
    context = release.make_record(
        "release-context",
        context["data"],
        invocation_id=context["invocation_id"],
        sequence=context["sequence"],
        synthetic=True,
    )
    context_digest = release.sha256_json(context)
    target = copy.deepcopy(base["target"])
    target["data"]["release_context_digest"] = context_digest
    _predecessor_content_reseal(target)
    gate = release.make_record(
        "release-gate-input",
        {
            "milestone": "v0.4",
            "release_context_digest": context_digest,
            "predecessor_policy_digest": release.sha256_bytes(policy_raw),
            "expected_predecessor_milestone": "v0.4",
            "target_resolution_digest": release.sha256_json(target),
        },
        invocation_id="connected-gate",
        sequence=1,
        synthetic=True,
    )

    records: list[tuple[str, dict[str, Any]]] = []

    def record(record_type: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        value = release.make_record(
            record_type,
            data,
            invocation_id="historical-" + record_type.replace("release-", "")[:40],
            sequence=1,
            synthetic=True,
        )
        digest = release.sha256_json(value)
        records.append((digest, value))
        return digest, value

    def retention(phase: str, input_digest: str) -> tuple[str, dict[str, Any]]:
        stores = []
        for store_id, group in (
            ("payload-store-a", "fixture-independent-a"),
            ("payload-store-b", "fixture-independent-b"),
        ):
            proofs = {
                "put": _predecessor_content_ref(
                    f"native/{store_id}-put", (store_id + "-put").encode()
                ),
                "hold": _predecessor_content_ref(
                    f"native/{store_id}-hold", (store_id + "-hold").encode()
                ),
                "read_back": {
                    "path": f"native/{store_id}-read-back",
                    "bytes": 1,
                    "sha256": input_digest,
                },
            }
            stores.append(
                {
                    "store_id": store_id,
                    "content_digest": input_digest,
                    "read_back_digest": input_digest,
                    "put_receipt_digest": proofs["put"]["sha256"],
                    "hold_receipt_digest": proofs["hold"]["sha256"],
                    "independence_group": group,
                    "namespace": "fixture-history",
                    "object_key": input_digest,
                    "backend_binding_digest": release.sha256_json(
                        {"store_id": store_id, "group": group}
                    ),
                    "native_proofs": proofs,
                }
            )
        return record(
            "release-retention-receipts",
            {
                "all_content_equal": True,
                "input_digest": input_digest,
                "phase": phase,
                "receipt_set_digest": release.sha256_json(stores),
                "retained_at": "2026-01-01T00:00:30Z",
                "stores": stores,
                "original_registry": _predecessor_content_ref(
                    "original/stores.json", b"fixture stores\n"
                ),
                "invocation_root_locator": "invocations",
                "producer_intent_digest": "f" * 64,
            },
        )

    source_digest, _ = record(
        "release-source-freeze",
        {
            "dirty": False,
            "milestone": "v0.4",
            "source_sha": subject["source_commit"],
            "source_tree": subject["source_tree"],
        },
    )
    artifact_rows = [
        {
            "media_type": "application/vnd.pypa.wheel+zip",
            "path": subject["artifacts"][0]["filename"],
            "sha256": subject["artifacts"][0]["sha256"],
            "size": subject["artifacts"][0]["bytes"],
        },
        {
            "media_type": "application/gzip",
            "path": subject["artifacts"][1]["filename"],
            "sha256": subject["artifacts"][1]["sha256"],
            "size": subject["artifacts"][1]["bytes"],
        },
    ]
    artifact_digest, _ = record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": release.sha256_json(artifact_rows),
            "artifacts": artifact_rows,
            "build_invocation_id": "historical-build",
            "build_recipe_digest": "1" * 64,
            "milestone": "v0.4",
            "source_digest": "2" * 64,
            "source_freeze_digest": source_digest,
            "target_resolution_digest": "3" * 64,
            "invocation_root_locator": "invocations",
            "producer_intent_digest": "4" * 64,
        },
    )
    candidate_data = {
        "artifact_manifest_digest": artifact_digest,
        "artifact_set_digest": release.sha256_json(artifact_rows),
        "build_invocation_id": "historical-build",
        "evaluation_adoption_digest": None,
        "evaluation_adoption_mode": "none",
        "gate_input_digest": "5" * 64,
        "milestone": "v0.4",
        "package_version": "v0.4.0.post1",
        "predecessor_digest": "6" * 64,
        "release_tag": "v0.4.0.post1",
        "source_freeze_digest": source_digest,
        "finalization_intent_digest": "7" * 64,
        "control_journal_locator": str(
            root
            / "history/.control/historical-run/invocations/candidate-finalization/001/invocation.json"
        ),
    }
    candidate_data["candidate_digest"] = release._candidate_payload_digest(candidate_data)
    candidate_data["final_directory"] = str(
        root / "history/v0.4.0.post1" / candidate_data["candidate_digest"]
    )
    candidate_full_digest, _ = record("release-candidate-identity", candidate_data)
    plan_cell = {
        "cell_id": "fixture-cell",
        "environment_id": "fixture-environment",
        "obligation_ids": ["fixture-obligation"],
        "profile_id": "fixture-profile",
        "scenario_ids": ["fixture-scenario"],
    }
    expected_subject = {"fixture": "historical-subject"}
    recipe = {"fixture": "historical-recipe"}
    catalog_data = {
        "execution_units": [
            {
                "environment_id": plan_cell["environment_id"],
                "expected_subject": expected_subject,
                "obligation_ids": plan_cell["obligation_ids"],
                "phase": "qualification",
                "profile_id": plan_cell["profile_id"],
                "recipe": recipe,
                "scenario_id": plan_cell["scenario_ids"][0],
                "slot_milestone": "v0.4",
                "unit_id": plan_cell["cell_id"],
            }
        ]
    }
    catalog_data["catalog_digest"] = release.sha256_json(catalog_data)
    catalog_digest, _ = record("release-scenario-catalog", catalog_data)
    plan_data = {
        "attempt_count": 1,
        "candidate_digest": candidate_data["candidate_digest"],
        "candidate_manifest_digest": artifact_digest,
        "cells": [plan_cell],
        "delta_digest": "8" * 64,
        "delta_test_map_digest": "9" * 64,
        "expected_terminal_result": "PASS",
        "gate_instance_digest": "a" * 64,
        "milestone": "v0.4",
        "predecessor_digest": candidate_data["predecessor_digest"],
        "readiness_digest": "b" * 64,
        "scenario_catalog_digest": catalog_digest,
    }
    plan_data["plan_digest"] = release.sha256_json(plan_data)
    plan_digest, _ = record("release-qualification-plan", plan_data)
    attempt_id = "historical-attempt"
    cell_digest, _ = record(
        "release-cell-result",
        {
            "artifact_digest": candidate_data["artifact_set_digest"],
            "attempt_id": attempt_id,
            "candidate_digest": candidate_data["candidate_digest"],
            "cell_id": plan_cell["cell_id"],
            "completed_at": "2026-01-01T00:00:20Z",
            "evidence": {
                "expected_subject_digest": release.sha256_json(expected_subject),
                "kind": "command",
                "observed_process_exit": 0,
                "outputs": [
                    {
                        "id": "historical-result",
                        "media_type": "application/json",
                        "path": "result.json",
                        "sha256": "e" * 64,
                        "size": 1,
                    }
                ],
                "recipe_digest": release.sha256_json(recipe),
            },
            "environment_id": plan_cell["environment_id"],
            "obligation_ids": plan_cell["obligation_ids"],
            "plan_digest": plan_digest,
            "profile_id": plan_cell["profile_id"],
            "result": "PASS",
            "runner_identity": "fixture-runner",
            "scenario_ids": plan_cell["scenario_ids"],
            "started_at": "2026-01-01T00:00:10Z",
            "stderr_digest": "1" * 64,
            "stdout_digest": "2" * 64,
            "unexpected_outcomes": [],
        },
    )
    termination_digest, _ = record(
        "provider-run-termination",
        {
            "job_id": "fixture-job",
            "provider_run_id": "fixture-run",
            "state": "success",
            "tool": "github-provider",
        },
    )
    coordination_digest, _ = record(
        "release-attempt-coordination",
        {
            "attempt_id": attempt_id,
            "candidate_digest": candidate_data["candidate_digest"],
            "cells": [
                {
                    "cell_id": plan_cell["cell_id"],
                    "job_id": "fixture-job",
                    "provider_run_id": "fixture-run",
                    "provider_termination_digest": termination_digest,
                    "status": "terminal",
                }
            ],
            "coordination_result": "PASS",
            "hard_runner_losses": [],
            "milestone": "v0.4",
            "provider": "github",
            "qualification_plan_digest": plan_digest,
        },
    )
    required_records = [
        ("coordination.json", coordination_digest),
        ("plan.json", plan_digest),
        ("result.json", cell_digest),
        ("termination.json", termination_digest),
    ]
    attempt_entries = [
        {
            "media_type": "application/json",
            "path": path,
            "role": "historical-record",
            "sha256": digest,
            "size": len(release.canonical_json(next(v for d, v in records if d == digest))),
        }
        for path, digest in required_records
    ]
    attempt_journals = ["1" * 64]
    attempt_manifest_digest, _ = record(
        "release-evidence-manifest",
        {
            "candidate_digest": candidate_data["candidate_digest"],
            "entries": attempt_entries,
            "invocation_journal_digests": attempt_journals,
            "manifest_digest": release.sha256_json(
                {"entries": attempt_entries, "invocation_journal_digests": attempt_journals}
            ),
            "phase": "attempt",
            "scope_id": attempt_id,
            "scope_kind": "release-attempt",
            "producer_intent_digest": "2" * 64,
            "invocation_root_locator": "invocations",
        },
    )
    attempt_retention_digest, _ = retention("attempt", attempt_manifest_digest)
    attempt_scope = {
        "kind": "release_candidate",
        "scope_id": attempt_id,
        "stage": "qualification-attempt",
        "sequence": 1,
        "release_tag": candidate_data["release_tag"],
        "candidate_id": candidate_data["candidate_digest"],
    }
    attempt_entry = {
        "schema_version": "metriplane.release-attempt-index-entry.v1",
        "backend_id": "attempt-index",
        "genesis_digest": release.sha256_bytes(
            Path("docs/releases/release-attempt-index-genesis.json").read_bytes()
        ),
        "generation": 1,
        "previous_head": None,
        "operation_id": "historical-qualification-attempt",
        "token": "historical-qualification-token",
        "milestone": "v0.4",
        "scope": attempt_scope,
        "entry_manifest_digest": attempt_manifest_digest,
        "entry_receipts_digest": attempt_retention_digest,
    }
    attempt_index_digest, _ = record("release-attempt-index", _index_receipt_fixture(attempt_entry))
    attempt_data = {
        "attempt_id": attempt_id,
        "candidate_digest": candidate_data["candidate_digest"],
        "cells": [
            {"cell_id": plan_cell["cell_id"], "result": "PASS", "result_digest": cell_digest}
        ],
        "coordination_digest": coordination_digest,
        "milestone": "v0.4",
        "qualification_plan_digest": plan_digest,
        "result": "PASS",
        "warning_summary_digest": "0" * 64,
    }

    def warning(subject: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        warning_data = {
            "candidate_digest": candidate_data["candidate_digest"],
            "deselection_count": 0,
            "policy_digest": "3" * 64,
            "result": "PASS",
            "retry_count": 0,
            "skip_count": 0,
            "subject_digest": release.sha256_json(subject),
            "unexpected_warning_count": 0,
            "warnings": [],
            "xfail_count": 0,
            "xpass_count": 0,
        }
        warning_data["summary_digest"] = release.sha256_json(warning_data)
        return record("release-warning-summary", warning_data)

    attempt_subject = dict(attempt_data)
    del attempt_subject["warning_summary_digest"]
    attempt_warning_digest, _ = warning(attempt_subject)
    attempt_data["warning_summary_digest"] = attempt_warning_digest
    attempt_digest, _ = record("release-attempt", attempt_data)
    qualification_data = {
        "attempt_evidence": [
            {
                "attempt_digest": attempt_digest,
                "attempt_id": attempt_id,
                "index_receipt_digest": attempt_index_digest,
                "manifest_digest": attempt_manifest_digest,
                "retention_receipts_digest": attempt_retention_digest,
            }
        ],
        "candidate_digest": candidate_data["candidate_digest"],
        "executed_cell_ids": [plan_cell["cell_id"]],
        "expected_cell_ids": [plan_cell["cell_id"]],
        "plan_digest": plan_digest,
        "qualification_digest": "0" * 64,
        "result": "PASS",
        "terminal_results": attempt_data["cells"],
        "unexpected_outcomes": [],
        "warning_summary_digest": "0" * 64,
    }
    qualification_subject = dict(qualification_data)
    del qualification_subject["warning_summary_digest"]
    del qualification_subject["qualification_digest"]
    qualification_warning_digest, _ = warning(qualification_subject)
    qualification_data["warning_summary_digest"] = qualification_warning_digest
    qualification_unsigned = dict(qualification_data)
    del qualification_unsigned["qualification_digest"]
    qualification_data["qualification_digest"] = release.sha256_json(qualification_unsigned)
    qualification_digest, _ = record("release-qualification", qualification_data)
    evidence_manifest_digest, _ = record(
        "release-evidence-manifest",
        {
            "phase": "qualified-publication",
            "candidate_digest": candidate_data["candidate_digest"],
            "entries": [{"sha256": qualification_digest}],
        },
    )
    reconciliation_digest, _ = record(
        "release-publication-reconciliation",
        {
            "candidate_digest": candidate_data["candidate_digest"],
            "milestone": "v0.4",
            "qualification_digest": qualification_digest,
            "evidence_manifest_digest": evidence_manifest_digest,
            "result": "RECONCILED",
            "burn_required": False,
            "partial_targets": [],
        },
    )
    final_retention_digest, _ = retention("final", evidence_manifest_digest)
    chain_head = "8" * 64
    _chain_digest, _ = record(
        "release-evidence-chain",
        {
            "backend_id": "success-chain",
            "candidate_digest": candidate_data["candidate_digest"],
            "reconciliation_digest": reconciliation_digest,
            "final_receipts_digest": final_retention_digest,
            "committed_head": chain_head,
            "read_back_digest": chain_head,
            "disposition": "committed",
            "evidence_manifest_digest": evidence_manifest_digest,
            "expected_head": None,
            "generation": 1,
            "milestone": "v0.4",
            "operation_id": "historical-chain",
            "previous_head": None,
        },
    )
    lkg_digest, _ = record(
        "release-last-known-good",
        {
            "backend_id": "last-known-good",
            "candidate_digest": candidate_data["candidate_digest"],
            "chain_head": chain_head,
            "committed_token": "historical-token",
            "expected_generation": 0,
            "invalidation_decision_digest": None,
            "milestone": "v0.4",
            "new_generation": 1,
            "operation_id": "historical-lkg",
            "previous_release_digest": None,
            "read_back_digest": "9" * 64,
            "reconciliation_digest": reconciliation_digest,
            "state": "LKG",
        },
    )
    transition_retention_digest, _ = retention("pointer-transition", lkg_digest)

    def manifest(phase: str, required: list[tuple[str, str]]) -> tuple[str, dict[str, Any]]:
        entries = [
            {
                "media_type": "application/json",
                "path": path,
                "role": "historical-record",
                "sha256": digest,
                "size": len(release.canonical_json(next(v for d, v in records if d == digest))),
            }
            for path, digest in sorted(required)
        ]
        journals = ["a" * 64]
        return record(
            "release-evidence-manifest",
            {
                "candidate_digest": candidate_data["candidate_digest"],
                "entries": entries,
                "invocation_journal_digests": journals,
                "manifest_digest": release.sha256_json(
                    {"entries": entries, "invocation_journal_digests": journals}
                ),
                "phase": phase,
                "scope_id": candidate_data["candidate_digest"],
                "scope_kind": "release_candidate",
                "producer_intent_digest": "b" * 64,
                "invocation_root_locator": "invocations",
            },
        )

    pointer_manifest_digest, _ = manifest(
        "pointer-transition",
        [
            ("history/lkg.json", lkg_digest),
            ("history/lkg-retention.json", transition_retention_digest),
        ],
    )
    pointer_retention_digest, _ = retention("pointer-transition-envelope", pointer_manifest_digest)

    def index(stage: str, manifest_digest: str, receipts_digest: str, sequence: int) -> str:
        scope = {
            "kind": "release_candidate",
            "scope_id": "historical-" + stage,
            "stage": stage,
            "sequence": sequence,
            "release_tag": "v0.4.0.post1",
            "candidate_id": candidate_data["candidate_digest"],
        }
        entry = {
            "schema_version": "metriplane.release-attempt-index-entry.v1",
            "backend_id": "attempt-index",
            "genesis_digest": release.sha256_bytes(
                Path("docs/releases/release-attempt-index-genesis.json").read_bytes()
            ),
            "generation": sequence,
            "previous_head": None if sequence == 1 else "d" * 64,
            "operation_id": "historical-" + stage,
            "token": "historical-index-token-" + str(sequence),
            "milestone": "v0.4",
            "scope": scope,
            "entry_manifest_digest": manifest_digest,
            "entry_receipts_digest": receipts_digest,
        }
        receipt = _index_receipt_fixture(entry)
        digest, _ = record("release-attempt-index", receipt)
        return digest

    pointer_index_digest = index(
        "pointer-transition", pointer_manifest_digest, pointer_retention_digest, 1
    )
    observation_digest, _ = record(
        "release-task-state-observation",
        {
            "candidate_digest": candidate_data["candidate_digest"],
            "latest_pointer_index_digest": pointer_index_digest,
            "phase": "close-ready",
        },
    )
    close_manifest_digest, _ = manifest(
        "release-finalizing-observation",
        [
            ("history/close-observation.json", observation_digest),
            ("history/pointer-index.json", pointer_index_digest),
        ],
    )
    close_retention_digest, _ = retention("release-task-finalizing", close_manifest_digest)
    close_root_digest = index(
        "release-task-finalizing", close_manifest_digest, close_retention_digest, 2
    )
    close_root_head = next(value for digest, value in records if digest == close_root_digest)[
        "data"
    ]["committed_head"]
    role_digest, _ = record(
        "release-role-assignments",
        {
            "author_id": "historical-author",
            "authorized_executor_id": "historical-operator",
            "non_author_reviewer_id": "historical-reviewer",
            "publisher_id": "historical-publisher",
            "task_id": "MP2-007",
            "milestone": "v0.4",
        },
    )
    task_policy_raw = Path("docs/status/release-task-state-policy.json").read_bytes()
    provider_event = {
        **decision_identity,
        "api_version": "fixture-v1",
        "event_id": "historical-close-event",
        "actor_id": "historical-operator",
        "before_state_id": "00000000-0000-0000-0000-000000000010",
        "after_state_id": "00000000-0000-0000-0000-000000000011",
        "before_state_key": "open_finalizing",
        "after_state_key": "closed",
        "server_timestamp": "2026-01-01T00:01:00Z",
    }
    provider_event_raw = release.canonical_json(provider_event)
    closed_data = {
        "input_kind": "task_state_transition",
        "transition_kind": "release_decision_closed",
        "decision": "CLOSED",
        "authorized_role": "release_operator",
        "conflicts": [],
        "signer_identity": "historical-operator",
        "signing_method": "provider-attestation-v1",
        "authority_policy_digest": "a" * 64,
        "provider_attestation_keyring_digest": "b" * 64,
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-01T00:02:00Z",
        "provider_event": provider_event,
        "original_provider_close_event": _predecessor_content_ref(
            "original/provider-close-event.json", provider_event_raw
        ),
        "task_state_policy_registry": _predecessor_content_ref(
            "original/task-state-policy.json", task_policy_raw
        ),
        "subject_digests": [
            {"subject": "predecessor_candidate_identity", "sha256": candidate_full_digest},
            {
                "subject": "decision_identity",
                "sha256": release.sha256_json(decision_identity),
            },
            {"subject": "role_assignments", "sha256": role_digest},
            {
                "subject": "task_state_policy_registry",
                "sha256": release.sha256_bytes(task_policy_raw),
            },
            {"subject": "durable_close_root", "sha256": close_root_digest},
            {
                "subject": "original_provider_close_event",
                "sha256": release.sha256_bytes(provider_event_raw),
            },
        ],
    }
    unsigned_closed = release.make_record(
        "release-protected-input",
        closed_data,
        invocation_id="historical-closed-decision",
        sequence=1,
        synthetic=True,
    )
    signature_subject = release.signature_subject_digest(unsigned_closed)
    closed_signature = {
        "actor_id": "historical-operator",
        "algorithm": "test-sha256-v1",
        "provider": "test-fixture",
        "subject_digest": signature_subject,
        "synthetic": True,
        "signature": release.sha256_json(
            {"actor_id": "historical-operator", "subject_digest": signature_subject}
        ),
    }
    closed = release.make_record(
        "release-protected-input",
        closed_data,
        invocation_id="historical-closed-decision",
        sequence=1,
        synthetic=True,
        signatures=[closed_signature],
    )
    closed_decision_digest = release.sha256_json(closed)
    records.append((closed_decision_digest, closed))
    linear_digest = release.sha256_json(linear)
    records.append((linear_digest, linear))

    for path, raw in {
        "readiness.json": readiness_raw,
        "inputs/context.json": release.canonical_json(context),
        "inputs/policy.json": policy_raw,
        "original/historical-policy.json": historical_registry_raw,
        "original/provider-close-event.json": provider_event_raw,
        "original/task-state-policy.json": task_policy_raw,
        "gate-input.json": release.canonical_json(gate),
        "target-resolution.json": release.canonical_json(target),
        "artifacts/wheel": wheel_raw,
        "artifacts/sdist": sdist_raw,
        **{"git/" + kind: raw for kind, raw in git_raw.items()},
    }.items():
        output = root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(raw)
    record_rows = []
    for sequence, (digest, value) in enumerate(records):
        path = f"records/{sequence:03d}.json"
        raw = release.canonical_json(value)
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(raw)
        record_rows.append(
            {
                "kind": "original_release_record",
                "record_type": value["record_type"],
                "record_digest": digest,
                "original_file": _predecessor_content_ref(path, raw),
            }
        )
    raw_rows = [
        {
            "kind": "original_role_key_policy",
            "purpose": "readiness_registry",
            "original_file": _predecessor_content_ref("readiness.json", readiness_raw),
        }
    ]
    raw_rows.extend(
        [
            {
                "kind": "original_provider_event",
                "purpose": "original_provider_close_event",
                "original_file": _predecessor_content_ref(
                    "original/provider-close-event.json", provider_event_raw
                ),
            },
            {
                "kind": "original_role_key_policy",
                "purpose": "task_state_policy_registry",
                "original_file": _predecessor_content_ref(
                    "original/task-state-policy.json", task_policy_raw
                ),
            },
        ]
    )
    readback_values = {
        "provider_state": {
            "schema_version": "metriplane.release-provider-state-readback.v1",
            "complete": True,
            "decision_identity": decision_identity,
            "state": "CLOSED",
            "closed_decision_digest": closed_decision_digest,
        },
        "provider_event_history": {
            "schema_version": "metriplane.release-provider-event-history-readback.v1",
            "complete": True,
            "decision_identity": decision_identity,
            "latest_state": "CLOSED",
            "closed_decision_digest": closed_decision_digest,
            "event_count": 1,
        },
        "success_chain_readback": {
            "schema_version": "metriplane.release-success-chain-readback.v1",
            "complete": True,
            "backend_id": "success-chain",
            "head": chain_head,
            "selected_record_digest": _chain_digest,
        },
        "lkg_state_and_history_readback": {
            "schema_version": "metriplane.release-lkg-state-readback.v1",
            "complete": True,
            "backend_id": "last-known-good",
            "head": lkg_digest,
            "selected_record_digest": lkg_digest,
        },
        "attempt_index_readback": {
            "schema_version": "metriplane.release-attempt-index-readback.v1",
            "complete": True,
            "backend_id": "attempt-index",
            "head": close_root_head,
            "selected_record_digest": close_root_digest,
        },
    }
    for name, value in readback_values.items():
        raw = release.canonical_json(value)
        path = "readbacks/" + name
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(raw)
        raw_rows.append(
            {
                "kind": "original_provider_state_readback"
                if name.startswith("provider")
                else "original_backend_state_readback",
                "purpose": name,
                "original_file": _predecessor_content_ref(path, raw),
            }
        )
    proof = {
        "schema_version": "metriplane.release-predecessor-proof-index.v1",
        "records": record_rows,
        "raw_proofs": raw_rows,
        "git_objects": [
            {
                "kind": "original_git_object",
                "object_type": kind,
                "git_object_id": subject[field],
                "original_file": _predecessor_content_ref("git/" + kind, git_raw[kind]),
            }
            for kind, field in (
                ("commit", "source_commit"),
                ("tree", "source_tree"),
                ("tag", "tag_object"),
            )
        ],
        "artifacts": [
            {
                "kind": "original_distribution_payload",
                "artifact_kind": row["kind"],
                "filename": row["filename"],
                "original_file": row["readback"],
            }
            for row in subject["artifacts"]
        ],
    }
    proof_path = root / "inputs/proof-index.json"
    proof_path.write_bytes(release.canonical_json(proof))
    for name, source in (
        ("chain-genesis.json", "docs/releases/release-evidence-chain-genesis.json"),
        ("index-genesis.json", "docs/releases/release-attempt-index-genesis.json"),
        ("v0.4-genesis.json", "docs/releases/v0.3.0-genesis.json"),
        ("stores.json", "docs/status/release-evidence-stores.json"),
    ):
        (root / "inputs" / name).write_bytes(Path(source).read_bytes())
    argv = [
        "--milestone",
        "v0.4",
        "--expected-predecessor-milestone",
        "v0.4",
        "--release-context",
        str(root / "inputs/context.json"),
        "--predecessor-policy",
        str(root / "inputs/policy.json"),
        "--prerequisite-proofs",
        str(proof_path),
        "--chain-backend",
        "success-chain",
        "--chain-genesis",
        str(root / "inputs/chain-genesis.json"),
        "--lkg-backend",
        "last-known-good",
        "--attempt-index-backend",
        "attempt-index",
        "--attempt-index-genesis",
        str(root / "inputs/index-genesis.json"),
        "--stores",
        str(root / "inputs/stores.json"),
        "--v0.4-genesis",
        str(root / "inputs/v0.4-genesis.json"),
        "--require-prior-lkg",
        "--project-id",
        context["data"]["decision"]["project_id"],
        "--require-prior-decision-closed",
        "--out",
        str(root / "predecessor.json"),
        "--invocation-dir",
        str(root / "invocations/resolve-release-predecessor/001"),
    ]
    return root, argv


def test_public_predecessor_commands_connect_original_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    assert release.run_release_command("resolve_release_predecessor.py", argv) == 0
    output = root / "predecessor.json"
    predecessor = json.loads(output.read_bytes())
    assert output.stat().st_nlink == 1
    release._ReleaseCapturedFiles.capture(
        root,
        [("predecessor.json", "prerequisite-original")],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    release.validate_release_producer_journal(
        predecessor, output, producer="resolve_release_predecessor.py"
    )
    validator = [
        "--record",
        str(output),
        "--milestone",
        "v0.4",
        "--release-context",
        str(root / "inputs/context.json"),
        "--predecessor-policy",
        str(root / "inputs/policy.json"),
        "--read-back-chain",
        "--read-back-lkg",
        "--read-back-pointer-index",
        "--require-embedded-prior-decision-closed-observation",
        "--invocation-dir",
        str(root / "invocations/validate-release-predecessor/001"),
    ]
    assert release.run_release_command("validate_release_predecessor.py", validator) == 0
    terminal = release._validate_terminal(
        release._validate_intent(root / "invocations/validate-release-predecessor/001")
    )
    assert terminal["status"] == "PASS" and terminal["data"]["outputs"] == []

    original = (root / "readbacks/success_chain_readback").read_bytes()
    (root / "readbacks/success_chain_readback").chmod(0o600)
    (root / "readbacks/success_chain_readback").write_bytes(b"substituted\n")
    with pytest.raises(release.ReleaseControlError):
        release._validate_bound_invocation(
            release._validate_intent(root / "invocations/resolve-release-predecessor/001")
        )
    (root / "readbacks/success_chain_readback").write_bytes(original)

    relocated = tmp_path / "relocated-predecessor-run"
    shutil.copytree(root, relocated)
    shutil.rmtree(root)
    relocated_validator = [
        value.replace(str(root), str(relocated)).replace(
            "validate-release-predecessor/001", "validate-release-predecessor/002"
        )
        for value in validator
    ]
    assert release.run_release_command("validate_release_predecessor.py", relocated_validator) == 0


def test_predecessor_selection_rejects_semantically_incomplete_refreshed_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    assert release.run_release_command("resolve_release_predecessor.py", argv) == 0
    predecessor = json.loads((root / "predecessor.json").read_bytes())["data"]
    proof = json.loads((root / "inputs/proof-index.json").read_bytes())
    policy = json.loads((root / "inputs/policy.json").read_bytes())
    row = next(
        value for value in proof["raw_proofs"] if value.get("purpose") == "success_chain_readback"
    )
    path = root / row["original_file"]["path"]
    changed = json.loads(path.read_bytes())
    changed["complete"] = False
    raw = release.canonical_json(changed)
    path.write_bytes(raw)
    row["original_file"] = _predecessor_content_ref(row["original_file"]["path"], raw)
    linked = {
        key: predecessor[key]
        for key in (
            "chain_head",
            "chain_receipt_digest",
            "lkg_digest",
            "close_root_digest",
            "closed_decision_digest",
        )
    }
    with pytest.raises(release.ReleaseControlError, match="backend readback"):
        release._release_predecessor_selection_observations(
            root,
            proof,
            observed_at="2026-01-01T00:00:00Z",
            linked=linked,
            decision_identity=policy["expected_predecessor_decision"]["identity"],
            attempt_index_head=json.loads((root / "readbacks/attempt_index_readback").read_bytes())[
                "head"
            ],
        )


def test_predecessor_closed_decision_rejects_signer_without_operator_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    proof, originals = release._release_predecessor_proof_originals(
        root, root / "inputs/proof-index.json"
    )
    policy = json.loads((root / "inputs/policy.json").read_bytes())
    candidate_digest = next(
        digest for (kind, digest) in originals if kind == "release-candidate-identity"
    )
    close_root_digest = next(
        digest
        for (kind, digest), (_, record) in originals.items()
        if kind == "release-attempt-index"
        and record["data"].get("stage") == "release-task-finalizing"
    )
    closed_digest = next(
        digest for (kind, digest) in originals if kind == "release-protected-input"
    )
    closed = copy.deepcopy(originals[("release-protected-input", closed_digest)][1])
    role_row = next(
        ((kind, digest), path, record)
        for (kind, digest), (path, record) in originals.items()
        if kind == "release-role-assignments"
    )
    role = copy.deepcopy(role_row[2])
    role["data"]["authorized_executor_id"] = "different-operator"
    _predecessor_content_reseal(role)
    role_digest = release.sha256_json(role)
    originals[("release-role-assignments", role_digest)] = (role_row[1], role)
    next(row for row in closed["data"]["subject_digests"] if row["subject"] == "role_assignments")[
        "sha256"
    ] = role_digest
    unsigned = release.make_record(
        "release-protected-input",
        closed["data"],
        invocation_id=closed["invocation_id"],
        sequence=closed["sequence"],
        synthetic=True,
    )
    signature_subject = release.signature_subject_digest(unsigned)
    closed = release.make_record(
        "release-protected-input",
        closed["data"],
        invocation_id=closed["invocation_id"],
        sequence=closed["sequence"],
        synthetic=True,
        signatures=[
            {
                "actor_id": "historical-operator",
                "algorithm": "test-sha256-v1",
                "provider": "test-fixture",
                "subject_digest": signature_subject,
                "synthetic": True,
                "signature": release.sha256_json(
                    {"actor_id": "historical-operator", "subject_digest": signature_subject}
                ),
            }
        ],
    )
    changed_closed_digest = release.sha256_json(closed)
    originals[("release-protected-input", changed_closed_digest)] = (
        Path("/retained") / changed_closed_digest,
        closed,
    )
    with pytest.raises(release.ReleaseControlError, match="operator role"):
        release._release_predecessor_closed_decision(
            root,
            proof,
            originals,
            closed_digest=changed_closed_digest,
            candidate_full_digest=candidate_digest,
            close_root_digest=close_root_digest,
            decision_identity=policy["expected_predecessor_decision"]["identity"],
            predecessor_milestone="v0.4",
        )


def test_predecessor_qualification_rejects_missing_dependency_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    _proof, originals = release._release_predecessor_proof_originals(
        root, root / "inputs/proof-index.json"
    )
    qualification = next(
        record for (kind, _), (_, record) in originals.items() if kind == "release-qualification"
    )
    candidate = next(
        record
        for (kind, _), (_, record) in originals.items()
        if kind == "release-candidate-identity"
    )
    plan_digest = qualification["data"]["plan_digest"]
    del originals[("release-qualification-plan", plan_digest)]
    with pytest.raises(release.ReleaseControlError, match="qualification plan"):
        release._release_predecessor_qualification_originals(
            originals, qualification, candidate_record=candidate
        )


def test_predecessor_qualification_rejects_missing_planned_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    _proof, originals = release._release_predecessor_proof_originals(
        root, root / "inputs/proof-index.json"
    )
    qualification = next(
        record for (kind, _), (_, record) in originals.items() if kind == "release-qualification"
    )
    candidate = next(
        record
        for (kind, _), (_, record) in originals.items()
        if kind == "release-candidate-identity"
    )
    plan_digest = qualification["data"]["plan_digest"]
    plan = originals.pop(("release-qualification-plan", plan_digest))[1]
    plan["data"]["attempt_count"] = 2
    unsigned = dict(plan["data"])
    del unsigned["plan_digest"]
    plan["data"]["plan_digest"] = release.sha256_json(unsigned)
    _predecessor_content_reseal(plan)
    changed_plan_digest = release.sha256_json(plan)
    originals[("release-qualification-plan", changed_plan_digest)] = (
        Path("/retained") / changed_plan_digest,
        plan,
    )
    qualification["data"]["plan_digest"] = changed_plan_digest
    qualification_unsigned = dict(qualification["data"])
    del qualification_unsigned["qualification_digest"]
    qualification["data"]["qualification_digest"] = release.sha256_json(qualification_unsigned)
    _predecessor_content_reseal(qualification)
    with pytest.raises(release.ReleaseControlError, match="plan cell inventory"):
        release._release_predecessor_qualification_originals(
            originals, qualification, candidate_record=candidate
        )


@pytest.mark.parametrize("broken_edge", ["commit-tree", "tag-commit", "tag-invalid-byte"])
def test_predecessor_subject_originals_rejects_unrelated_git_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken_edge: str
) -> None:
    root, _ = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    proof = json.loads((root / "inputs/proof-index.json").read_bytes())
    policy = json.loads((root / "inputs/policy.json").read_bytes())
    subject = policy["expected_predecessor_subject"]

    if broken_edge == "commit-tree":
        replacement = b"tree " + b"0" * 40 + b"\n"
        kind, subject_field = "commit", "source_commit"
    elif broken_edge == "tag-commit":
        replacement = b"object " + b"0" * 40 + b"\ntype commit\ntag v0.4.0.post1\n"
        kind, subject_field = "tag", "tag_object"
    else:
        replacement = (
            b"object "
            + subject["source_commit"].encode()
            + b"\xff\ntype commit\ntag v0.4.0.post1\n"
        )
        kind, subject_field = "tag", "tag_object"
    row = next(value for value in proof["git_objects"] if value["object_type"] == kind)
    path = root / row["original_file"]["path"]
    path.write_bytes(replacement)
    oid = hashlib.sha1(
        f"{kind} {len(replacement)}\0".encode() + replacement, usedforsecurity=False
    ).hexdigest()
    row["git_object_id"] = oid
    row["original_file"] = _predecessor_content_ref(row["original_file"]["path"], replacement)
    subject[subject_field] = oid

    with pytest.raises(release.ReleaseControlError, match="relationship"):
        release._release_predecessor_subject_originals(root, proof, subject)


def test_public_predecessor_command_interruption_cannot_claim_success_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv = _connected_predecessor_command_fixture(tmp_path, monkeypatch)
    popen = release.subprocess.Popen

    class InterruptedChild:
        pid = 987654320

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def wait(self) -> int:
            if hasattr(self, "killed"):
                return -2
            raise KeyboardInterrupt

        def kill(self) -> None:
            self.killed = True

    monkeypatch.setattr(release.subprocess, "Popen", InterruptedChild)
    monkeypatch.setattr(release, "_stop_worker_group", lambda _pid: True)
    assert release.run_release_command("resolve_release_predecessor.py", argv) == 130
    interrupted = root / "invocations/resolve-release-predecessor/001"
    terminal = release._validate_terminal(release._validate_intent(interrupted))
    assert terminal["status"] == "CANCELLED" and terminal["data"]["outputs"] == []
    assert not (root / "predecessor.json").exists()
    assert not (interrupted / "terminal-commit.json").exists()

    monkeypatch.setattr(release.subprocess, "Popen", popen)
    retry = [
        value.replace("resolve-release-predecessor/001", "resolve-release-predecessor/002")
        for value in argv
    ]
    assert release.run_release_command("resolve_release_predecessor.py", retry) == 0
    output = root / "predecessor.json"
    release.validate_release_producer_journal(
        json.loads(output.read_bytes()), output, producer="resolve_release_predecessor.py"
    )


def _predecessor_content_fixture(
    *, bootstrap: bool = False, generic: bool = False, previous: str = "0.4.0.post1"
) -> dict[str, Any]:
    context, args = _context_policy_fixture()
    policy, _ = _predecessor_policy_fixture()
    subject = policy["expected_predecessor_subject"]
    baseline = context["data"]["comparison_baseline"]
    baseline.update(
        normalized_package_version="0.3.0" if bootstrap else "0.4.0.post2",
        release_tag="v0.3.0" if bootstrap else "v0.4.0.post2",
    )
    for a in baseline["artifacts"]:
        a["filename"] = (
            "metriplane-"
            + baseline["normalized_package_version"]
            + ("-py3-none-any.whl" if a["kind"] == "wheel" else ".tar.gz")
        )
    if bootstrap:
        reg = json.loads(args["readiness_registry_raw"])
        slot = next((r for r in reg["release_gate_slots"] if r["version"] == "v0.4"))
        context["data"]["roadmap_catalog_task_id"] = slot["release_decision_task"]
        context["data"]["decision"] = copy.deepcopy(
            next(
                (
                    r["identity"]
                    for r in reg["provider_issue_bindings"]
                    if r["issue_identifier"] == slot["linear_release_decision_issue"]
                )
            )
        )
        context["data"]["target_policy"].update(
            initial_normalized_package_version="0.4.0", initial_release_tag="v0.4.0"
        )
        linear = args["linear_snapshot"]["data"]
        linear["decision_issue_id"] = context["data"]["decision"]["issue_id"]
        linear["task_id"] = context["data"]["decision"]["issue_identifier"]
        policy["lineage_mode"] = "ORIGINAL_BOOTSTRAP"
        policy["expected_predecessor_decision"] = None
        policy["proof_requirements"] = {
            k: k == "original_genesis" for k in policy["proof_requirements"]
        }
        previous = "0.3.0"
    if generic:
        context["data"]["target_policy"].update(
            resolution_mode="next_unused_same_milestone_patch",
            conflict_disposition="DURABLE_BURN_THEN_SAME_MILESTONE_PATCH",
            initial_normalized_package_version="0.4.0",
            initial_release_tag="v0.4.0",
        )
    context = _reseal_context_policy_fixture(context, args, amend_selected_policy=True)
    selected = json.loads(args["readiness_registry_raw"])["release_contexts"][0]
    policy["target_policy"] = copy.deepcopy(selected["target_policy"])
    policy["framework_milestone"] = selected["framework_milestone"]
    subject.update(
        normalized_package_version=previous,
        release_tag="v" + previous,
        framework_milestone=None if bootstrap else "v0.4",
    )
    for a in subject["artifacts"]:
        a["filename"] = (
            "metriplane-" + previous + ("-py3-none-any.whl" if a["kind"] == "wheel" else ".tar.gz")
        )
    policy["selection_authority"]["readiness_registry"] = _predecessor_content_ref(
        "readiness.json", args["readiness_registry_raw"]
    )
    policy["selection_authority"]["context_policy_digest"] = release.sha256_json(selected)
    policy_raw = (json.dumps(policy, indent=2) + "\n").encode()
    args["predecessor_policy_raw"] = policy_raw
    args["expected_predecessor_policy_digest"] = release.sha256_bytes(policy_raw)
    context["data"]["predecessor_policy_digest"] = args["expected_predecessor_policy_digest"]
    context = _reseal_context_policy_fixture(context, args)
    context_raw = (json.dumps(context, indent=2) + "\n").encode()
    release._release_context_policy_projection(context, **args)
    release._release_predecessor_policy_projection(
        policy_raw,
        expected_digest=release.sha256_bytes(policy_raw),
        **{
            k: args[k]
            for k in ("readiness_registry_raw", "expected_readiness_digest", "expected_context_id")
        },
    )
    # Original synthetic content fixtures: no native history or authority is asserted.
    samples = {
        "bootstrap": {
            "data": {
                "lineage_mode": "ORIGINAL_BOOTSTRAP",
                "candidate_milestone": "v0.4",
                "predecessor_milestone": None,
                "version": "v0.3.0",
                "package_version": "0.3.0",
                "release_context_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "release_context": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "predecessor_policy_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "predecessor_policy": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "predecessor_subject": {
                    "framework_milestone": None,
                    "normalized_package_version": "0.3.0",
                    "release_tag": "v0.3.0",
                    "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "source_tree": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "tag_object": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "artifacts": [
                        {
                            "bytes": 1,
                            "filename": "x.whl",
                            "kind": "wheel",
                            "readback": {
                                "path": "original/input.json",
                                "bytes": 1,
                                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            },
                            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        },
                        {
                            "bytes": 1,
                            "filename": "x.tar.gz",
                            "kind": "sdist",
                            "readback": {
                                "path": "original/input.json",
                                "bytes": 1,
                                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            },
                            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        },
                    ],
                },
                "predecessor_subject_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "proof_index": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "producer_intent_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "invocation_root_locator": "invocations",
                "genesis_authority_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "completion_digest": None,
                "selection_observations": None,
                "qualification_digest": None,
                "reconciliation_digest": None,
                "final_retention_digest": None,
                "chain_receipt_digest": None,
                "chain_head": None,
                "lkg_digest": None,
                "pointer_transition_retention_digest": None,
                "pointer_envelope_digest": None,
                "pointer_retention_digest": None,
                "pointer_index_receipt_digest": None,
                "closed_decision_digest": None,
                "close_ready_observation_digest": None,
                "close_root_digest": None,
            }
        },
        "reconciled": {
            "data": {
                "lineage_mode": "RECONCILED_LKG",
                "candidate_milestone": "v0.4",
                "predecessor_milestone": "v0.4",
                "version": "v0.4.0.post2",
                "package_version": "0.4.0.post2",
                "release_context_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "release_context": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "predecessor_policy_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "predecessor_policy": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "predecessor_subject": {
                    "framework_milestone": "v0.4",
                    "normalized_package_version": "0.4.0.post2",
                    "release_tag": "v0.4.0.post2",
                    "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "source_tree": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "tag_object": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "artifacts": [
                        {
                            "bytes": 1,
                            "filename": "x.whl",
                            "kind": "wheel",
                            "readback": {
                                "path": "original/input.json",
                                "bytes": 1,
                                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            },
                            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        },
                        {
                            "bytes": 1,
                            "filename": "x.tar.gz",
                            "kind": "sdist",
                            "readback": {
                                "path": "original/input.json",
                                "bytes": 1,
                                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            },
                            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        },
                    ],
                },
                "predecessor_subject_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "proof_index": {
                    "path": "original/input.json",
                    "bytes": 1,
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
                "producer_intent_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "invocation_root_locator": "invocations",
                "genesis_authority_digest": None,
                "completion_digest": None,
                "selection_observations": {
                    "observed_at": "2026-09-08T00:00:00Z",
                    "provider_state": {
                        "path": "original/input.json",
                        "bytes": 1,
                        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                    "provider_event_history": {
                        "path": "original/input.json",
                        "bytes": 1,
                        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                    "success_chain_readback": {
                        "path": "original/input.json",
                        "bytes": 1,
                        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                    "lkg_state_and_history_readback": {
                        "path": "original/input.json",
                        "bytes": 1,
                        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                    "attempt_index_readback": {
                        "path": "original/input.json",
                        "bytes": 1,
                        "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                },
                "qualification_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "reconciliation_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "final_retention_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "chain_receipt_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "chain_head": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "lkg_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "pointer_transition_retention_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "pointer_envelope_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "pointer_retention_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "pointer_index_receipt_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "closed_decision_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "close_ready_observation_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "close_root_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        },
    }
    data = copy.deepcopy(samples["bootstrap" if bootstrap else "reconciled"]["data"])
    data.update(
        release_context=_predecessor_content_ref("inputs/context.json", context_raw),
        release_context_digest=release.sha256_json(context),
        predecessor_policy=_predecessor_content_ref("inputs/policy.json", policy_raw),
        predecessor_policy_digest=release.sha256_bytes(policy_raw),
        predecessor_subject=copy.deepcopy(subject),
        predecessor_subject_digest=release.sha256_json(subject),
        package_version=previous,
        version="v" + previous,
        producer_intent_digest="c" * 64,
    )
    rawrow = {
        "kind": "original_genesis_authority" if bootstrap else "original_provider_event",
        "purpose": "SYNTHETIC_SCHEMA_ONLY_NO_NATIVE_PROOF",
        "original_file": _predecessor_content_ref("raw/original.json", b"opaque synthetic proof"),
    }
    index = {
        "schema_version": "metriplane.release-predecessor-proof-index.v1",
        "records": [],
        "raw_proofs": [rawrow],
        "git_objects": [
            {
                "kind": "original_git_object",
                "object_type": kind,
                "git_object_id": subject[field],
                "original_file": _predecessor_content_ref(
                    "git/" + kind, b"opaque original " + kind.encode()
                ),
            }
            for kind, field in [
                ("commit", "source_commit"),
                ("tree", "source_tree"),
                ("tag", "tag_object"),
            ]
        ],
        "artifacts": [
            {
                "kind": "original_distribution_payload",
                "artifact_kind": a["kind"],
                "filename": a["filename"],
                "original_file": copy.deepcopy(a["readback"]),
            }
            for a in subject["artifacts"]
        ],
    }
    if not bootstrap:
        for i, (field, kind) in enumerate(_PREDECESSOR_CONTENT_TEST_ROOT_TYPES.items()):
            digest = release.sha256_json({"SYNTHETIC_SCHEMA_ONLY": field})
            data[field] = digest
            index["records"].append(
                {
                    "kind": "original_release_record",
                    "record_type": kind,
                    "record_digest": digest,
                    "original_file": _predecessor_content_ref(
                        "records/" + str(i) + ".json", b"opaque synthetic record"
                    ),
                }
            )
        data["chain_head"] = "d" * 64
        data["selection_observations"] = {
            "observed_at": "2026-01-01T00:00:00Z",
            **{
                name: _predecessor_content_ref(
                    "current/" + name + ".json", b"opaque synthetic state"
                )
                for name in (
                    "provider_state",
                    "provider_event_history",
                    "success_chain_readback",
                    "lkg_state_and_history_readback",
                    "attempt_index_readback",
                )
            },
        }
    index_raw = (json.dumps(index, indent=2) + "\n").encode()
    data["proof_index"] = _predecessor_content_ref("inputs/proof-index.json", index_raw)
    record = release.make_record(
        "release-predecessor",
        data,
        invocation_id="synthetic-original-predecessor",
        sequence=9,
        synthetic=True,
    )
    targetdata = {
        "selected_package_version": "v0.4.0" if bootstrap else "v0.4.1",
        "selected_release_tag": "v0.4.0" if bootstrap else "v0.4.1",
        "release_context_digest": release.sha256_json(context),
        "milestone": "v0.4",
        "resolution_rule": policy["target_policy"]["resolution_mode"],
    }
    target = release.make_record(
        "release-target-resolution",
        targetdata,
        invocation_id="synthetic-target-content-premise",
        sequence=1,
        synthetic=True,
    )
    gate = {
        "milestone": "v0.4",
        "release_context_digest": release.sha256_json(context),
        "predecessor_policy_digest": release.sha256_bytes(policy_raw),
        "expected_predecessor_milestone": subject["framework_milestone"] or subject["release_tag"],
        "target_resolution_digest": release.sha256_json(target),
    }
    return {
        "record": record,
        "gate_data": gate,
        "target": target,
        "original_bytes": {
            "release_context": context_raw,
            "predecessor_policy": policy_raw,
            "proof_index": index_raw,
        },
        "expected_original_paths": {
            name: data[name]["path"]
            for name in ("release_context", "predecessor_policy", "proof_index")
        },
        "expected_record_digest": release.sha256_json(record),
        "expected_invocation_id": record["invocation_id"],
        "expected_sequence": 9,
        "expected_producer_intent_digest": "c" * 64,
        "context_policy_inputs": args,
        "synthetic": True,
    }


def _predecessor_content_refresh(a: dict[str, Any]) -> None:
    _predecessor_content_reseal(a["record"])
    a["expected_record_digest"] = release.sha256_json(a["record"])


def _predecessor_content_rewrite_index(a: dict[str, Any], index: dict[str, Any]) -> None:
    raw = (json.dumps(index, indent=2) + "\n").encode()
    a["original_bytes"]["proof_index"] = raw
    a["record"]["data"]["proof_index"] = _predecessor_content_ref(
        a["expected_original_paths"]["proof_index"], raw
    )
    _predecessor_content_refresh(a)


@pytest.mark.parametrize(
    "kwargs", [{}, {"bootstrap": True}, {"generic": True}, {"previous": "0.4.0.post2"}]
)
def test_predecessor_content_complete_current_content_preserves_explicit_lineage(
    kwargs: dict[str, Any],
) -> None:
    a = _predecessor_content_fixture(**kwargs)
    before = copy.deepcopy(a)
    d = release._release_predecessor_content(**a)
    assert a == before and len(d) == 30
    assert d["package_version"] == (
        "0.3.0" if kwargs.get("bootstrap") else kwargs.get("previous", "0.4.0.post1")
    )


@pytest.mark.parametrize("field", list(_predecessor_content_fixture()["record"]["data"]))
def test_predecessor_content_every_required_current_field(field: str) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    del a["record"]["data"][field]
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "field,value",
    [
        ("extra", True),
        ("lineage_mode", "ORIGINAL_BOOTSTRAP"),
        ("candidate_milestone", "v0.5"),
        ("predecessor_milestone", None),
        ("version", "v0.3.0"),
        ("package_version", "0.3.0"),
        ("release_context_digest", "0" * 64),
        ("predecessor_policy_digest", "0" * 64),
        ("predecessor_subject_digest", "0" * 64),
        ("producer_intent_digest", "0" * 64),
        ("invocation_root_locator", "../invocations"),
        ("completion_digest", "0" * 64),
        ("selection_observations", None),
        ("genesis_authority_digest", "0" * 64),
        ("chain_head", None),
        *[(field, None) for field in _PREDECESSOR_CONTENT_TEST_ROOT_TYPES],
    ],
)
def test_predecessor_content_consistently_resealed_payload_mutations(
    field: str, value: Any
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a["record"]["data"][field] = value
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize("field", list(_PREDECESSOR_CONTENT_TEST_ROOT_TYPES))
def test_predecessor_content_all_original_typed_roots_are_required(field: str) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    index = json.loads(a["original_bytes"]["proof_index"])
    index["records"] = [
        r for r in index["records"] if r["record_digest"] != a["record"]["data"][field]
    ]
    _predecessor_content_rewrite_index(a, index)
    with pytest.raises(release.ReleaseControlError, match="omits an exact original root"):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize("field", list(_predecessor_content_fixture()["original_bytes"]))
@pytest.mark.parametrize(
    "value",
    [
        "../old",
        "/tmp/original",
        "C:\\original",
        "inputs\\original",
        "./original",
        "inputs//original",
        "a\x00",
    ],
)
def test_predecessor_content_native_paths_cannot_use_platform_aliases(
    field: str, value: str
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a["record"]["data"][field]["path"] = value
    a["expected_original_paths"][field] = value
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize("field", list(_predecessor_content_fixture()["original_bytes"]))
@pytest.mark.parametrize(
    "member,value", [("bytes", True), ("bytes", 0), ("sha256", "0" * 64), ("extra", True)]
)
def test_predecessor_content_raw_original_reference_shape_and_identity(
    field: str, member: str, value: Any
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a["record"]["data"][field][member] = value
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "member",
    [
        "expected_record_digest",
        "expected_invocation_id",
        "expected_sequence",
        "expected_producer_intent_digest",
    ],
)
def test_predecessor_content_original_journal_expectations_do_not_come_from_output(
    member: str,
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a[member] = (
        10
        if member == "expected_sequence"
        else "different"
        if member == "expected_invocation_id"
        else "0" * 64
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize("clock", ["2026-01-01T00:00:00Z", "2026-01-01T02:00:00+02:00"])
def test_predecessor_content_original_old_clock_is_not_required_to_be_fresh_today(
    clock: str,
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a["record"]["data"]["selection_observations"]["observed_at"] = clock
    _predecessor_content_refresh(a)
    release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "clock",
    [
        None,
        4,
        "2026-01-01",
        "2026-01-01T00:00Z",
        "2026-01-01T00:00:00",
        "2026-13-01T00:00:00Z",
        "2026-01-01T00:00:00Z\n",
    ],
)
def test_predecessor_content_selection_clock_syntax_does_not_invent_freshness(clock: Any) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a["record"]["data"]["selection_observations"]["observed_at"] = clock
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize("field", ["raw_proofs", "git_objects", "artifacts"])
def test_predecessor_content_typed_index_cannot_drop_required_leaf_categories(field: str) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    index = json.loads(a["original_bytes"]["proof_index"])
    index[field] = []
    _predecessor_content_rewrite_index(a, index)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "mode",
    [
        "duplicate-record",
        "same-record-other-file",
        "same-file-other-record",
        "wrong-root-type",
        "unknown-record-type",
        "extra-field",
        "root-C-to-payload-C",
    ],
)
def test_predecessor_content_proof_index_does_not_alias_original_record_roots(mode: str) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    index = json.loads(a["original_bytes"]["proof_index"])
    first = index["records"][0]
    if mode in ("duplicate-record", "same-record-other-file", "same-file-other-record"):
        other = copy.deepcopy(first)
        if mode == "same-record-other-file":
            other["original_file"]["path"] = "other.json"
        if mode == "same-file-other-record":
            other["record_digest"] = "0" * 64
        index["records"].append(other)
    elif mode == "wrong-root-type":
        first["record_type"] = "release-context"
    elif mode == "unknown-record-type":
        first["record_type"] = "untrusted-plugin-validator"
    elif mode == "extra-field":
        first["validator"] = "arbitrary"
    else:
        first["record_digest"] = "0" * 64
    _predecessor_content_rewrite_index(a, index)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


def test_predecessor_content_comparison_baseline_does_not_select_an_lkg() -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    context = json.loads(a["original_bytes"]["release_context"])
    assert context["data"]["comparison_baseline"]["normalized_package_version"] == "0.4.0.post2"
    assert a["record"]["data"]["package_version"] == "0.4.0.post1"
    a["record"]["data"]["package_version"] = "0.4.0.post2"
    a["record"]["data"]["version"] = "v0.4.0.post2"
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError, match="selected context"):
        release._release_predecessor_content(**a)


def test_predecessor_content_current_patch_cannot_use_initial_framework_bootstrap() -> None:
    a = _predecessor_content_fixture(bootstrap=True)
    context = json.loads(a["original_bytes"]["release_context"])
    context["data"]["target_policy"]["initial_normalized_package_version"] = "0.4.1"
    context["data"]["target_policy"]["initial_release_tag"] = "v0.4.1"
    raw = release.canonical_json(context)
    a["original_bytes"]["release_context"] = raw
    a["record"]["data"]["release_context"] = _predecessor_content_ref(
        a["expected_original_paths"]["release_context"], raw
    )
    a["record"]["data"]["release_context_digest"] = release.sha256_json(context)
    _predecessor_content_refresh(a)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


def test_predecessor_content_content_layer_performs_no_filesystem_or_native_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unexpected native IO")

    for name in ("_safe_release_bytes", "_release_held_path", "_source_git"):
        monkeypatch.setattr(release, name, forbidden)
    release._release_predecessor_content(**copy.deepcopy(_predecessor_content_fixture()))


@pytest.mark.parametrize(
    "category,field,value",
    [
        ("artifacts", "filename", "metriplane-wrong.whl"),
        ("artifacts", "artifact_kind", "unknown"),
        ("git_objects", "git_object_id", "0" * 40),
        ("git_objects", "object_type", "blob"),
    ],
)
def test_predecessor_content_subject_git_and_artifact_roots_must_remain_selected(
    category: str, field: str, value: Any
) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    index = json.loads(a["original_bytes"]["proof_index"])
    index[category][0][field] = value
    _predecessor_content_rewrite_index(a, index)
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "field", ["original_bytes", "expected_original_paths", "context_policy_inputs", "gate_data"]
)
def test_predecessor_content_incomplete_python_input_mapping_is_typed_error(field: str) -> None:
    a = copy.deepcopy(_predecessor_content_fixture())
    a[field] = None
    with pytest.raises(release.ReleaseControlError):
        release._release_predecessor_content(**a)


@pytest.mark.parametrize(
    "clock,valid",
    [
        ("2026-01-01T00:00:00+00:60", False),
        ("2026-01-01T00:00:00-12:99", False),
        ("2026-01-01t00:00:00Z", True),
        ("2026-01-01T00:00:00z", True),
        ("2026-01-01t00:00:00z", True),
        ("2026-01-01T00:00:00+24:00", False),
        ("2026-01-01T00:00:00-24:00", False),
        ("2026-01-01T00:00:00+23:59", True),
        ("2026-01-01T00:00:00-23:59", True),
        ("2026-01-01T00:00:00-00:00", True),
        ("2026-01-01T00:00:00+00:00", True),
        ("2024-02-29t00:00:00.000000001z", True),
        ("2026-02-29T00:00:00Z", False),
        ("2026-01-01T00:00:00Z\n", False),
        ("2026-01-01T24:00:00Z", False),
        ("2026-01-01T00:60:00Z", False),
        ("2026-01-01T00:00:60Z", False),
        ("0000-01-01T00:00:00Z", False),
    ],
)
def test_predecessor_content_original_rfc3339_offset_and_case(clock: str, valid: bool) -> None:
    a = _predecessor_content_fixture()
    a["record"]["data"]["selection_observations"]["observed_at"] = clock
    _predecessor_content_refresh(a)
    original = release.canonical_json(a["record"])
    if valid:
        result = release._release_predecessor_content(**a)
        assert result["selection_observations"]["observed_at"] == clock
    else:
        with pytest.raises(release.ReleaseControlError, match="clock"):
            release._release_predecessor_content(**a)
    assert release.canonical_json(a["record"]) == original


def _gate_reservation_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Explicit synthetic fixture",
            "-c",
            "user.email=synthetic@example.invalid",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def _gate_reservation_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[str], Any]:
    repo = tmp_path / "repository"
    repo.mkdir()
    root = repo / "run"
    root.mkdir()
    argv, _ = _gate_declared_capture_fixture(root)
    args = release._release_original_arguments(argv[0], argv)
    for flag, field in release._RELEASE_GATE_SOURCE_FIELDS.items():
        dest = repo / release._SOURCE_REGISTRY_INPUTS[field]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(args[flag]).read_bytes())
    (repo / ".gitignore").write_text("/run/\n/other-run/\n/moved-run/\n/stale-run/\n")
    _gate_reservation_git(repo, "init", "-q")
    _gate_reservation_git(repo, "add", ".")
    _gate_reservation_git(repo, "commit", "-qm", "Explicit transport fixture; no native authority")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    held = release._release_gate_prepare_inputs(argv[1:], root / "invocations/gate-input/001")
    return (root, argv, held)


def _gate_reservation_reserve(root: Path, argv: list[str], held: Any, **changes: Any) -> Any:
    kwargs = {
        "input_paths": [
            (root / n, "metriplane." + k + ".v1") for n, k, _, _, _ in held.captured.rows
        ],
        "planned_outputs": [(root / n, k) for n, k in release._RELEASE_GATE_OUTPUT_PLAN],
        "_gate_inputs": held,
    }
    kwargs.update(changes)
    return release.begin_release_invocation(
        argv[0], argv[1:], root / "invocations/gate-input/001", **kwargs
    )


def test_gate_reservation_full_original_intent_and_two_outputs(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    assert isinstance(context, release._ReleaseGateInvocation)
    assert context.gate_inputs.captured is held.captured
    assert context.intent["argv"] == argv
    assert len(context.intent["inputs"]) == len(held.captured.rows) > 7
    assert context.intent["planned_outputs"] == [
        {"path": n, "schema_id": k} for n, k in release._RELEASE_GATE_OUTPUT_PLAN
    ]
    assert held.source_sha == _gate_reservation_git(root.parent, "rev-parse", "HEAD")
    assert held.source_tree == _gate_reservation_git(root.parent, "rev-parse", "HEAD^{tree}")
    assert (context.directory / "intent.json").read_bytes() == release.canonical_json(
        context.intent
    )
    release._validate_bound_invocation(context)
    assert not (root / "gate-input.json").exists()


@pytest.mark.parametrize("relative", [False, True])
def test_gate_reservation_run_uses_exact_capture_and_keeps_original_argv(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    root, argv, _ = _gate_reservation_prepared
    if relative:
        argv = [
            str(Path(v).relative_to(root.parent)) if v.startswith(str(root)) else v for v in argv
        ]
    seen = []

    def supervisor(context: Any, **kwargs: Any) -> int:
        release._validate_bound_invocation(context)
        seen.append(context)
        return 3

    monkeypatch.setattr(release, "_supervise_release_invocation", supervisor)
    assert release.run_release_command(argv[0], argv[1:]) == 3
    assert len(seen) == 1
    assert seen[0].intent["argv"] == argv
    assert seen[0].gate_inputs.captured is not None
    assert not (root / "gate-input.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "wrong-type",
        "duplicate",
        "missing-output",
        "extra-output",
        "wrong-output-type",
        "wrong-argv",
        "no-capture",
        "wrong-capture-root",
        "wrong-head",
        "wrong-tree",
        "wrong-digests",
    ],
)
def test_gate_reservation_reservation_refuses_incomplete_or_forged_binding(
    _gate_reservation_prepared: Any, mutation: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    inputs = [(root / n, "metriplane." + k + ".v1") for n, k, _, _, _ in held.captured.rows]
    outputs = [(root / n, k) for n, k in release._RELEASE_GATE_OUTPUT_PLAN]
    if mutation == "missing":
        inputs.pop()
    elif mutation == "extra":
        inputs.append((root / "unknown.json", "metriplane.prerequisite-original.v1"))
    elif mutation == "wrong-type":
        inputs[0] = (inputs[0][0], "metriplane.unknown.v1")
    elif mutation == "duplicate":
        inputs.append(inputs[0])
    elif mutation == "missing-output":
        outputs.pop()
    elif mutation == "extra-output":
        outputs.append((root / "extra.json", "metriplane.release-gate-input.v1"))
    elif mutation == "wrong-output-type":
        outputs[0] = (outputs[0][0], outputs[1][1])
    elif mutation == "wrong-argv":
        argv = [*argv, "--unknown", "value"]
    elif mutation == "no-capture":
        held = None
    elif mutation == "wrong-capture-root":
        held = dataclasses.replace(
            held, captured=dataclasses.replace(held.captured, root=root / "other")
        )
    elif mutation == "wrong-head":
        held = dataclasses.replace(held, source_sha="a" * 40)
    elif mutation == "wrong-tree":
        held = dataclasses.replace(held, source_tree="b" * 40)
    elif mutation == "wrong-digests":
        held = dataclasses.replace(
            held, registry_digests=tuple(((f, "c" * 64) for f, _ in held.registry_digests))
        )
    with pytest.raises(release.ReleaseControlError):
        release.begin_release_invocation(
            argv[0],
            argv[1:],
            root / "invocations/gate-input/001",
            input_paths=inputs,
            planned_outputs=outputs,
            _gate_inputs=held,
        )
    assert not (root / "invocations/gate-input/001").exists()


@pytest.mark.parametrize(
    "tool",
    [
        "freeze_release_source.py",
        "build_release_artifacts.py",
        "finalize_release_candidate.py",
        "validate_release_candidate.py",
    ],
)
def test_gate_reservation_private_capture_cannot_change_other_command_paths(
    _gate_reservation_prepared: Any, tool: str
) -> None:
    root, _, held = _gate_reservation_prepared
    with pytest.raises(release.ReleaseControlError, match="only to prepare"):
        release.begin_release_invocation(
            tool,
            [],
            root / "invocations/gate-input/001",
            input_paths=[],
            planned_outputs=[],
            _gate_inputs=held,
        )


@pytest.mark.parametrize(
    "mutation", ["delete", "bytes", "same-byte-inode", "symlink", "fifo", "ancestor", "root"]
)
def test_gate_reservation_capture_change_rejects_before_selected_file_read(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    path = root / "inputs/readiness-registry.json"
    original = path.read_bytes()
    if mutation == "delete":
        path.unlink()
    elif mutation == "bytes":
        path.write_bytes(original + b" ")
    elif mutation == "same-byte-inode":
        path.unlink()
        path.write_bytes(original)
    elif mutation == "symlink":
        path.unlink()
        path.symlink_to("obligations.json")
    elif mutation == "fifo":
        path.unlink()
        os.mkfifo(path)
    elif mutation == "ancestor":
        (root / "inputs").rename(root / "old-inputs")
        shutil.copytree(root / "old-inputs", root / "inputs")
    elif mutation == "root":
        root.rename(root.parent / "stale-run")
        shutil.copytree(root.parent / "stale-run", root)
    real_read = release.os.read
    selected_reads = []

    def read(fd: int, n: int) -> bytes:
        if _gate_reservation_descriptor_names_file(fd, path):
            selected_reads.append(fd)
        return real_read(fd, n)

    monkeypatch.setattr(release.os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        _gate_reservation_reserve(root, argv, held)
    assert selected_reads == []
    assert not (root / "invocations/gate-input/001").exists()


@pytest.mark.parametrize(
    "mutation", ["tracked", "untracked", "head", "source-file-inode", "copied-registry"]
)
def test_gate_reservation_git_source_or_copied_registry_drift_blocks(
    _gate_reservation_prepared: Any, mutation: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    repo = root.parent
    path = repo / release._SOURCE_REGISTRY_INPUTS["readiness_registry_digest"]
    if mutation == "tracked":
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "untracked":
        (repo / "unknown").write_text("foreign")
    elif mutation == "head":
        _gate_reservation_git(repo, "commit", "--allow-empty", "-qm", "new identity, same tree")
    elif mutation == "source-file-inode":
        raw = path.read_bytes()
        path.unlink()
        path.write_bytes(raw)
    elif mutation == "copied-registry":
        copied = root / "inputs/readiness-registry.json"
        copied.write_bytes(copied.read_bytes() + b" ")
    with pytest.raises(release.ReleaseControlError):
        _gate_reservation_reserve(root, argv, held)
    assert not (root / "invocations/gate-input/001").exists()


def test_gate_reservation_missing_original_input_never_shortens_reserved_inventory(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, _ = _gate_reservation_prepared
    (root / "inputs/readiness-registry.json").unlink()
    assert release.run_release_command(argv[0], argv[1:]) == 2
    assert not (root / "invocations/gate-input/001").exists()


def test_gate_reservation_held_capture_identity_survives_nested_replay(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    replay = release._release_gate_input_plan_replay(
        context,
        expected_registry_digests=dict(held.registry_digests),
        original_capture=held.captured,
    )
    assert replay["captured"] is held.captured


def test_gate_reservation_ordinary_relocated_replay_never_reads_historical_checkout(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    moved = root.parent / "moved-run"
    root.rename(moved)
    ordinary = release.ReleaseInvocation(
        moved / "invocations/gate-input/001", moved, context.intent
    )
    monkeypatch.setattr(
        release, "_source_git", lambda *a: pytest.fail("historical replay must not read Git")
    )
    monkeypatch.setattr(
        release,
        "_source_repository",
        lambda *a: pytest.fail("historical replay must not read source"),
    )
    release._validate_bound_invocation(ordinary)
    with pytest.raises(release.ReleaseControlError, match="actual producer-held"):
        release._supervise_release_invocation(ordinary)
    assert not (moved / "invocations/gate-input/001/stdout").exists()


def test_gate_reservation_unimplemented_gate_operation_remains_blocked(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    assert release._tool_operation(argv[0], argv[1:], context) == 3
    assert not (context.directory / "staged").exists()


@pytest.mark.parametrize("mutation", ["bytes", "same-byte-file", "same-byte-directory"])
def test_gate_reservation_intent_identity_is_held_across_nested_replay(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    path = context.directory / "intent.json"
    raw = path.read_bytes()
    if mutation == "bytes":
        path.chmod(384)
        path.write_bytes(raw + b" ")
    elif mutation == "same-byte-file":
        path.unlink()
        path.write_bytes(raw)
    else:
        stale = context.directory.with_name("saved")
        context.directory.rename(stale)
        shutil.copytree(stale, context.directory)
    reads = []
    original = release.os.read

    def read(fd: int, n: int) -> bytes:
        if _gate_reservation_descriptor_names_file(fd, path):
            reads.append(fd)
        return original(fd, n)

    monkeypatch.setattr(release.os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._validate_bound_invocation(context)
    assert reads == []


def test_gate_reservation_git_head_changed_during_original_blob_read_rejects(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _ = _gate_reservation_prepared
    original = release._source_git
    flipped = False

    def command(repo: Path, *args: str) -> bytes:
        nonlocal flipped
        raw = original(repo, *args)
        if args[:2] == ("cat-file", "blob") and (not flipped):
            flipped = True
            _gate_reservation_git(
                repo, "commit", "--allow-empty", "-qm", "same tree changed during capture"
            )
        return raw

    monkeypatch.setattr(release, "_source_git", command)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_prepare_inputs(argv[1:], root / "invocations/gate-input/001")
    assert flipped
    assert not (root / "invocations/gate-input/001").exists()


def test_gate_reservation_final_capture_checks_observed_file_identity_before_read(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, held = _gate_reservation_prepared
    original_capture = release._ReleaseCapturedFiles.capture.__func__
    target = root / "inputs/readiness-registry.json"
    changed = False
    later_reads = []
    real_read = release.os.read

    def read(fd: int, n: int) -> bytes:
        if changed and _gate_reservation_descriptor_names_file(fd, target):
            later_reads.append(fd)
        return real_read(fd, n)

    def capture(cls: Any, current: Path, *args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        if current == root and kwargs.get("expected_file_identities") is not None:
            raw = target.read_bytes()
            target.unlink()
            target.write_bytes(raw)
            changed = True
        return original_capture(cls, current, *args, **kwargs)

    monkeypatch.setattr(release.os, "read", read)
    monkeypatch.setattr(release._ReleaseCapturedFiles, "capture", classmethod(capture))
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_declared_input_capture(
            root, argv, expected_registry_digests=dict(held.registry_digests)
        )
    assert changed and later_reads == []


def test_gate_reservation_second_reservation_never_overwrites_intent(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    original = (context.directory / "intent.json").read_bytes()
    with pytest.raises(release.ReleaseControlError):
        _gate_reservation_reserve(root, argv, held)
    assert (context.directory / "intent.json").read_bytes() == original


@pytest.mark.parametrize(
    "boundary", ["before-worker", "after-quiescence", "after-output-check", "after-install"]
)
def test_gate_reservation_supervisor_rejects_input_change_at_each_boundary(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    original_capture = held.captured
    events = []
    target = root / "inputs/readiness-registry.json"

    def corrupt() -> None:
        target.write_bytes(target.read_bytes() + b" ")

    if boundary == "before-worker":
        corrupt()

    class Child:
        pid = 123456789

        def __init__(self, *args: Any, **kwargs: Any):
            assert kwargs["start_new_session"] is True
            events.append("worker")
            self.directory_fd, self.receipt_fd = kwargs["pass_fds"]

        def wait(self) -> int:
            (context.directory / "staged").mkdir()
            refs = []
            for name, kind in release._RELEASE_GATE_OUTPUT_PLAN:
                raw = b"{}"
                (context.directory / "staged" / name).write_bytes(raw)
                refs.append({"path": name, "schema_id": kind, "sha256": release.sha256_bytes(raw)})
            identity = release._release_gate_write_json_at(
                self.directory_fd,
                "worker-result.json",
                {
                    "schema_version": "metriplane.release-worker-result.v1",
                    "exit_code": 0,
                    "outputs": refs,
                    "producer_intent_digest": release.sha256_json(context.intent),
                },
            )
            receipt = release.canonical_json({"result_identity": identity})
            assert os.write(self.receipt_fd, receipt) == len(receipt)
            return 0

    def stop(pid: int) -> bool:
        events.append("quiesced")
        if boundary == "after-quiescence":
            corrupt()
        return True

    def verify(actual: Any, outputs: Any) -> None:
        assert actual is context and actual.gate_inputs.captured is original_capture
        events.append("output-check")
        if boundary == "after-output-check":
            corrupt()

    def install(actual: Any, outputs: Any, **kwargs: Any) -> None:
        assert actual is context and actual.gate_inputs.captured is original_capture
        events.append("install-spy")
        if boundary == "after-install":
            corrupt()

    monkeypatch.setattr(release.subprocess, "Popen", Child)
    monkeypatch.setattr(
        release, "_release_gate_source_revalidate", lambda h: dict(h.registry_digests)
    )
    monkeypatch.setattr(release, "_stop_worker_group", stop)
    monkeypatch.setattr(release, "_verify_staged_outputs", verify)
    monkeypatch.setattr(release, "_install_release_outputs", install)
    assert release._supervise_release_invocation(context) == 3
    terminal = json.loads((context.directory / "invocation.json").read_bytes())
    assert terminal["status"] == "BLOCKED" and terminal["data"]["outputs"] == []
    assert "install-spy" not in events if boundary != "after-install" else "install-spy" in events
    assert "worker" not in events if boundary == "before-worker" else "worker" in events
    assert not (root / "gate-input.json").exists()


def test_gate_reservation_persistent_worker_group_retains_incomplete_journal(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)

    class Child:
        pid = 123456789

        def __init__(self, *a: Any, **k: Any):
            pass

        def wait(self) -> int:
            return -9

    monkeypatch.setattr(release.subprocess, "Popen", Child)
    monkeypatch.setattr(
        release, "_release_gate_source_revalidate", lambda h: dict(h.registry_digests)
    )
    monkeypatch.setattr(release, "_stop_worker_group", lambda p: False)
    monkeypatch.setattr(
        release, "_install_release_outputs", lambda *a, **k: pytest.fail("must not install")
    )
    with pytest.raises(release.ReleaseControlError, match="incomplete"):
        release._supervise_release_invocation(context)
    assert (context.directory / "intent.json").exists()
    assert not (context.directory / "invocation.json").exists()


def test_gate_reservation_native_output_admission_is_not_enabled_by_reservation(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    (context.directory / "staged").mkdir()
    refs = []
    for name, kind in release._RELEASE_GATE_OUTPUT_PLAN:
        raw = b"{}"
        (context.directory / "staged" / name).write_bytes(raw)
        refs.append({"path": name, "schema_id": kind, "sha256": release.sha256_bytes(raw)})
    monkeypatch.setattr(release, "_collect_staged_outputs", lambda c: refs)
    with pytest.raises(release.ReleaseControlError, match="held worker handoff"):
        release._verify_staged_outputs(context, refs)


def test_gate_reservation_different_argv_sequence_rejects_before_intent(
    _gate_reservation_prepared: Any,
) -> None:
    root, argv, _ = _gate_reservation_prepared
    wrong = [
        str(root / "invocations/gate-input/002")
        if v == str(root / "invocations/gate-input/001")
        else v
        for v in argv
    ]
    with pytest.raises(release.ReleaseControlError, match="directory differ"):
        release._release_gate_prepare_inputs(wrong[1:], root / "invocations/gate-input/001")
    assert not (root / "invocations/gate-input/001").exists()


@pytest.mark.parametrize("replacement", ["root", "journal-stage"])
@pytest.mark.parametrize("ordinary", [False, True])
def test_gate_reservation_output_reads_reject_replacement_after_plan_replay_before_bytes(
    _gate_reservation_prepared: Any,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
    ordinary: bool,
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    if ordinary:
        context = release.ReleaseInvocation(context.directory, context.root, context.intent)
    staged = context.directory / "staged"
    staged.mkdir()
    refs = []
    for name, kind in release._RELEASE_GATE_OUTPUT_PLAN:
        raw = b"{}"
        (staged / name).write_bytes(raw)
        refs.append({"path": name, "schema_id": kind, "sha256": release.sha256_bytes(raw)})
    actual_replay = release._release_gate_input_plan_replay
    replaced = False

    def replay(*args: Any, **kwargs: Any) -> Any:
        nonlocal replaced
        result = actual_replay(*args, **kwargs)
        if replacement == "root":
            old = root.parent / "stale-run"
            root.rename(old)
            shutil.copytree(old, root)
        else:
            stage = context.directory.parent
            old = stage.with_name("old-gate-input")
            stage.rename(old)
            shutil.copytree(old, stage)
        replaced = True
        return result

    reads = []
    actual_read = release.os.read

    def read(fd: int, n: int) -> bytes:
        if replaced and any(
            _gate_reservation_descriptor_names_file(fd, staged / name)
            for name, _ in release._RELEASE_GATE_OUTPUT_PLAN
        ):
            reads.append(fd)
        return actual_read(fd, n)

    monkeypatch.setattr(release, "_release_gate_input_plan_replay", replay)
    monkeypatch.setattr(release.os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._validate_bound_invocation(context, outputs=refs, output_root=staged)
    assert replaced and reads == []


def test_gate_reservation_bound_output_reader_refuses_unrelated_root_without_read(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    outside = root.parent / "other-run"
    outside.mkdir()
    with pytest.raises(release.ReleaseControlError, match="different current output root"):
        release._validate_bound_invocation(context, outputs=[], output_root=outside)


@pytest.mark.parametrize("mutation", ["none", "intent", "capture", "observations"])
def test_gate_reservation_output_capture_has_exact_same_plan_and_retains_files(
    _gate_reservation_prepared: Any, mutation: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    staged = context.directory / "staged"
    staged.mkdir()
    for name, _ in release._RELEASE_GATE_OUTPUT_PLAN:
        (staged / name).write_bytes(b"{}")
    _gate_fixture_remember_stage(context, None)
    plan = release._release_gate_input_plan_replay(
        context,
        expected_registry_digests=dict(held.registry_digests),
        original_capture=held.captured,
    )
    if mutation == "intent":
        plan = {**plan, "intent": {**context.intent, "sequence": 2}}
    elif mutation == "capture":
        plan = {**plan, "captured": dataclasses.replace(held.captured)}
    elif mutation == "observations":
        plan = {**plan, "intent_identity": None}
    if mutation != "none":
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_output_capture(
                context,
                staged,
                input_plan=plan,
                original_outputs=_gate_fixture_carried_stage(context),
            )
        return
    outputs = release._release_gate_output_capture(
        context, staged, input_plan=plan, original_outputs=_gate_fixture_carried_stage(context)
    )
    assert len(outputs.rows) == 2
    target = staged / "gate-input.json"
    target.unlink()
    target.write_bytes(b"{}")
    with pytest.raises(release.ReleaseControlError):
        outputs.revalidate()


def _gate_reservation_descriptor_names_file(fd: int, path: Path) -> bool:
    """Portable test spy: match the actual open object, without Linux-only procfs."""
    try:
        visible = path.stat()
    except FileNotFoundError:
        return False
    opened = os.fstat(fd)
    return (opened.st_dev, opened.st_ino) == (visible.st_dev, visible.st_ino)


def test_gate_reservation_descriptor_spy_observes_real_open_objects(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.write_bytes(b"first fixture object")
    second.write_bytes(b"second fixture object")
    with first.open("rb") as stream:
        assert _gate_reservation_descriptor_names_file(stream.fileno(), first)
        assert not _gate_reservation_descriptor_names_file(stream.fileno(), second)
        assert not _gate_reservation_descriptor_names_file(stream.fileno(), tmp_path / "missing")


@pytest.mark.parametrize("replacement", ["root", "stage", "intent"])
def test_gate_copy_install_producer_capture_rejects_replacement_before_byte_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    context, _, _, _, outputs = _gate_copy_install_fixture(tmp_path, monkeypatch)
    assert isinstance(context, release._ReleaseGateInvocation)
    if replacement == "root":
        old = context.root.with_name("old-root")
        context.root.rename(old)
        shutil.copytree(old, context.root)
    elif replacement == "stage":
        old = context.directory.parent.with_name("old-stage")
        context.directory.parent.rename(old)
        shutil.copytree(old, context.directory.parent)
    else:
        target = context.directory / "intent.json"
        raw = target.read_bytes()
        target.unlink()
        target.write_bytes(raw)
    selected = [
        context.directory / "intent.json",
        *[context.directory / "staged" / row["path"] for row in outputs],
    ]
    foreign_reads: list[int] = []
    original = os.read

    def read(fd: int, size: int) -> bytes:
        if any(_gate_reservation_descriptor_names_file(fd, path) for path in selected):
            foreign_reads.append(fd)
        return original(fd, size)

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._install_release_gate_pair(
            context, outputs, original_stage_capture=_gate_fixture_carried_stage(context)
        )
    assert foreign_reads == []
    assert not any((context.root / row["path"]).exists() for row in outputs)


def _gate_staged_pair_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, new_burn: bool = False
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    context, data, catalog, _, refs = _gate_copy_install_fixture(
        tmp_path, monkeypatch, new_burn=new_burn
    )
    assert isinstance(context, release._ReleaseGateInvocation)
    plan = release._release_gate_input_plan_replay(
        context,
        expected_registry_digests=dict(context.gate_inputs.registry_digests),
        original_capture=context.gate_inputs.captured,
    )
    return context, plan, data, catalog, refs


@pytest.mark.parametrize("new_burn", [False, True])
def test_gate_staged_pair_replays_content_without_future_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_burn: bool
) -> None:
    context, plan, data, catalog, refs = _gate_staged_pair_fixture(
        tmp_path, monkeypatch, new_burn=new_burn
    )
    result = release._release_gate_staged_pair_replay(
        context,
        input_plan=plan,
        expected_gate_data=data,
        expected_catalog_record=catalog,
        original_outputs=_gate_fixture_carried_stage(context),
    )
    assert result["outputs"] == refs
    assert result["gate_record"]["data"] == data
    assert result["catalog_record"] == catalog
    assert len(result["captured"].rows) == 2
    assert not (context.directory / "invocation.json").exists()
    assert not (context.root / "gate-input.json").exists()
    # Content/transport graphs are intentionally separate mechanical fixtures.
    # This does not assert native input authority, a worker process or public PASS.


@pytest.mark.parametrize(
    "mutation",
    [
        "gate-content",
        "catalog-content",
        "terminal",
        "extra-file",
        "extra-directory",
        "extra-symlink",
    ],
)
def test_gate_staged_pair_rejects_mismatched_content_and_complete_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    context, plan, data, catalog, _ = _gate_staged_pair_fixture(tmp_path, monkeypatch)
    staged = context.directory / "staged"
    if mutation == "gate-content":
        data = {**data, "run_id": "different"}
    elif mutation == "catalog-content":
        catalog = {**catalog, "sequence": 9}
    elif mutation == "terminal":
        (context.directory / "invocation.json").write_bytes(b"premature terminal")
    elif mutation == "extra-file":
        (staged / "unplanned").write_bytes(b"unknown")
    elif mutation == "extra-directory":
        (staged / "unplanned").mkdir()
    else:
        (staged / "unplanned").symlink_to("gate-input.json")
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_staged_pair_replay(
            context,
            input_plan=plan,
            expected_gate_data=data,
            expected_catalog_record=catalog,
            original_outputs=_gate_fixture_carried_stage(context),
        )
    assert not (context.root / "gate-input.json").exists()


def test_gate_staged_pair_keeps_captured_stage_before_next_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, plan, data, catalog, _ = _gate_staged_pair_fixture(tmp_path, monkeypatch)
    staged = context.directory / "staged"
    actual = release._release_gate_output_capture
    changed = False
    reads: list[int] = []
    original_read = os.read

    def capture(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        result = actual(*args, **kwargs)
        old = staged.with_name("old-staged")
        staged.rename(old)
        shutil.copytree(old, staged)
        changed = True
        return result

    def read(fd: int, size: int) -> bytes:
        if changed and any(
            _gate_reservation_descriptor_names_file(fd, staged / name)
            for name, _ in release._RELEASE_GATE_OUTPUT_PLAN
        ):
            reads.append(fd)
        return original_read(fd, size)

    monkeypatch.setattr(release, "_release_gate_output_capture", capture)
    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_staged_pair_replay(
            context,
            input_plan=plan,
            expected_gate_data=data,
            expected_catalog_record=catalog,
            original_outputs=_gate_fixture_carried_stage(context),
        )
    assert changed and reads == []


def test_gate_staged_pair_detects_new_member_during_directory_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, plan, data, catalog, _ = _gate_staged_pair_fixture(tmp_path, monkeypatch)
    staged = context.directory / "staged"
    actual = os.listdir
    changed = False

    def listdir(path: Any) -> Any:
        nonlocal changed
        result = actual(path)
        if (
            isinstance(path, int)
            and _gate_reservation_descriptor_names_file(path, staged)
            and not changed
        ):
            (staged / "late-member").write_bytes(b"unplanned late evidence")
            changed = True
        return result

    monkeypatch.setattr(os, "listdir", listdir)
    with pytest.raises(release.ReleaseControlError, match="stage changed"):
        release._release_gate_staged_pair_replay(
            context,
            input_plan=plan,
            expected_gate_data=data,
            expected_catalog_record=catalog,
            original_outputs=_gate_fixture_carried_stage(context),
        )
    assert changed and (staged / "late-member").read_bytes() == b"unplanned late evidence"


@pytest.fixture
def _gate_write_reserved(_gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    root, argv, held = _gate_reservation_prepared
    c = _gate_reservation_reserve(root, argv, held)
    monkeypatch.setattr(
        release, "_release_gate_source_revalidate", lambda h: dict(h.registry_digests)
    )
    return c


def _gate_write_replace_directory(path: Path) -> Path:
    old = path.with_name(path.name + "-original")
    path.rename(old)
    shutil.copytree(old, path, symlinks=True)
    return old


def _gate_write_fake_worker(
    c: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_wait: Any = None,
    code: Any = 3,
    settled: Any = True,
) -> Any:

    class Child:
        pid = 987654321

        def __init__(self, *a: Any, **kw: Any) -> None:
            self.kw = kw
            assert kw["pass_fds"][0] >= 0 and len(kw["pass_fds"]) == 2

        def wait(self) -> Any:
            if on_wait:
                on_wait(self.kw)
            else:
                fd = self.kw["pass_fds"][0]
                os.mkdir("staged", dir_fd=fd)
                identity = release._release_gate_write_json_at(
                    fd,
                    "worker-result.json",
                    {
                        "schema_version": "metriplane.release-worker-result.v1",
                        "exit_code": code,
                        "outputs": [],
                        "producer_intent_digest": release.sha256_json(c.intent),
                    },
                )
                os.write(
                    self.kw["pass_fds"][1], release.canonical_json({"result_identity": identity})
                )
            return code

    monkeypatch.setattr(release.subprocess, "Popen", Child)
    monkeypatch.setattr(release, "_stop_worker_group", lambda pid: settled)
    return Child


@pytest.mark.parametrize("where", ["root", "stage", "journal", "intent"])
def test_gate_write_original_namespace_replacement_before_supervision_has_no_foreign_effect(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, where: Any
) -> None:
    c = _gate_write_reserved
    target = {
        "root": c.root,
        "stage": c.directory.parent,
        "journal": c.directory,
        "intent": c.directory / "intent.json",
    }[where]
    if where == "intent":
        raw = target.read_bytes()
        target.rename(target.with_suffix(".original"))
        target.write_bytes(raw)
    else:
        _gate_write_replace_directory(target)
    monkeypatch.setattr(
        release.subprocess, "Popen", lambda *a, **k: pytest.fail("worker must not start")
    )
    with pytest.raises(release.ReleaseControlError):
        release._supervise_release_invocation(c)
    assert not (c.directory / "stdout").exists()
    assert not (c.directory / "stderr").exists()
    assert not (c.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    "boundary", ["diagnostic-create", "worker-return", "partial-write", "terminal-write"]
)
def test_gate_write_substituted_root_never_receives_later_effects(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, boundary: Any
) -> None:
    c = _gate_write_reserved
    substituted = []
    original_open = release.os.open
    original_write = release._release_gate_write_json_at

    def change() -> Any:
        old = _gate_write_replace_directory(c.root)
        substituted.append(old)
        for name in ("stdout", "stderr", "partial-files.json", "invocation.json"):
            p = c.directory / name
            if p.exists():
                p.unlink()

    if boundary == "diagnostic-create":

        def opening(path: Any, flags: Any, *args: Any, **kwargs: Any) -> Any:
            if path == "stdout" and kwargs.get("dir_fd") is not None and (not substituted):
                change()
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(release.os, "open", opening)
    if boundary == "worker-return":

        def wait(kw: Any) -> Any:
            change()

        _gate_write_fake_worker(c, monkeypatch, on_wait=wait)
    else:
        _gate_write_fake_worker(c, monkeypatch)
    if boundary in {"partial-write", "terminal-write"}:

        def writing(fd: Any, name: Any, value: Any) -> Any:
            if name == (
                "partial-files.json" if boundary == "partial-write" else "invocation.json"
            ) and (not substituted):
                change()
            return original_write(fd, name, value)

        monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    with pytest.raises(release.ReleaseControlError):
        release._supervise_release_invocation(c)
    assert substituted
    for name in ("stdout", "stderr", "partial-files.json", "invocation.json"):
        assert not (c.directory / name).exists(), name
    assert (substituted[0] / c.directory.relative_to(c.root) / "intent.json").exists()


@pytest.mark.parametrize(
    "where", ["stdout", "stderr", "partial-files.json", "invocation.json", "worker-result.json"]
)
def test_gate_write_actual_writer_identity_is_not_adopted_from_same_byte_replacement(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, where: Any
) -> None:
    c = _gate_write_reserved
    changed = []
    original_write = release._release_gate_write_json_at

    def replacing(path: Any) -> Any:
        raw = path.read_bytes()
        path.rename(path.with_name(path.name + ".original"))
        path.write_bytes(raw)
        changed.append(path)

    if where in {"stdout", "stderr"}:

        def wait(kw: Any) -> Any:
            replacing(c.directory / where)

        _gate_write_fake_worker(c, monkeypatch, on_wait=wait)
    else:
        _gate_write_fake_worker(c, monkeypatch)

        def writing(fd: Any, name: Any, value: Any) -> Any:
            identity = original_write(fd, name, value)
            if name == where:
                replacing(c.directory / name)
            return identity

        monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    if where == "worker-result.json":
        assert release._supervise_release_invocation(c) == 3
        assert json.loads((c.directory / "invocation.json").read_bytes())["status"] == "BLOCKED"
    else:
        with pytest.raises(release.ReleaseControlError):
            release._supervise_release_invocation(c)
    assert changed


def test_gate_write_ordinary_input_drift_retains_genuine_blocked_terminal(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _gate_write_reserved
    p = c.root / "inputs/readiness-registry.json"
    p.write_bytes(p.read_bytes() + b" ")
    monkeypatch.setattr(
        release.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("changed input must not start worker"),
    )
    assert release._supervise_release_invocation(c) == 3
    record = json.loads((c.directory / "invocation.json").read_bytes())
    assert record["status"] == "BLOCKED"
    assert record["data"]["outputs"] == []
    assert len(record["data"]["inputs"]) == 2
    assert (c.directory / "stderr").stat().st_size > 0


def test_gate_write_quiescent_blocked_worker_completes_original_journal(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _gate_write_reserved
    _gate_write_fake_worker(c, monkeypatch)
    assert release._supervise_release_invocation(c) == 3
    assert json.loads((c.directory / "invocation.json").read_bytes())["status"] == "BLOCKED"
    assert (
        json.loads((c.directory / "partial-files.json").read_bytes())["roots"][0]["kind"]
        == "directory"
    )


def test_gate_write_unsettled_worker_retains_incomplete_original_journal(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _gate_write_reserved
    _gate_write_fake_worker(c, monkeypatch, settled=False)
    with pytest.raises(release.ReleaseControlError, match="incomplete"):
        release._supervise_release_invocation(c)
    assert (c.directory / "stdout").exists() and (not (c.directory / "invocation.json").exists())


def test_gate_write_partial_projection_preserves_original_wire_and_unsafe_inventory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    directory = root / "invocations/gate-input/001"
    directory.mkdir(parents=True)
    c = release.ReleaseInvocation(directory, root, {})
    stage = directory / "staged"
    stage.mkdir()
    (stage / "a").mkdir()
    (stage / "a" / "z").write_bytes(b"z")
    (stage / "a-").write_bytes(b"a")
    (stage / "link").symlink_to(tmp_path / "foreign")
    os.mkfifo(stage / "fifo")
    (directory / "workspace").symlink_to(stage)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        pins = {}
        held = release._release_gate_partial_projection_at(c, fd, observed_identities=pins)
        assert held == release._partial_file_projection(c)
        assert release._release_gate_partial_projection_at(c, fd, expected_identities=pins) == held
    finally:
        os.close(fd)


@pytest.mark.parametrize("mutation", ["file", "directory", "absent-root", "new-member"])
def test_gate_write_partial_recensus_rejects_substitution_before_foreign_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    root = tmp_path / "run"
    directory = root / "invocations/gate-input/001"
    directory.mkdir(parents=True)
    c = release.ReleaseInvocation(directory, root, {})
    stage = directory / "staged"
    stage.mkdir()
    (stage / "nested").mkdir()
    p = stage / "nested/file"
    p.write_bytes(b"original")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        pins = {}
        release._release_gate_partial_projection_at(c, fd, observed_identities=pins)
        if mutation == "file":
            p.rename(p.with_name("saved"))
            p.write_bytes(b"foreign")
        elif mutation == "directory":
            _gate_write_replace_directory(stage / "nested")
        elif mutation == "absent-root":
            (directory / "workspace").mkdir()
            (directory / "workspace/new").write_bytes(b"foreign")
        else:
            (stage / "new").write_bytes(b"foreign")
        foreign = []
        original_read = release.os.read

        def reading(number: Any, *args: Any) -> Any:
            data = original_read(number, *args)
            if b"foreign" in data:
                foreign.append(data)
            return data

        monkeypatch.setattr(release.os, "read", reading)
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_partial_projection_at(c, fd, expected_identities=pins)
        assert not foreign
    finally:
        os.close(fd)


def test_gate_write_actual_gate_worker_uses_original_fd_and_reports_blocked_without_builds(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    c = _gate_write_reserved
    package = tmp_path / "worker-package" / "metriplane"
    shutil.copytree(
        Path(release.__file__).absolute().parent,
        package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (package / "release_control.py").write_bytes(Path(release.__file__).read_bytes())
    monkeypatch.setattr(release, "__file__", str(package / "release_control.py"))
    assert release._supervise_release_invocation(c) == 3
    result = json.loads((c.directory / "worker-result.json").read_bytes())
    assert result["exit_code"] == 3 and result["outputs"] == []
    terminal = json.loads((c.directory / "invocation.json").read_bytes())
    assert terminal["status"] == "BLOCKED"
    assert list((c.directory / "staged").iterdir()) == []
    assert (
        "gate native held worker operation is not implemented"
        in (c.directory / "stderr").read_text()
    )


def test_gate_write_worker_result_substitution_rejects_before_foreign_bytes(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _gate_write_reserved
    reads = []
    original_read = release.os.read
    original_write = release._release_gate_write_json_at

    def writing(fd: Any, name: Any, value: Any) -> Any:
        identity = original_write(fd, name, value)
        if name == "worker-result.json":
            p = c.directory / name
            p.rename(p.with_name(name + ".original"))
            p.write_bytes(b"FOREIGN RESULT")
        return identity

    def reading(fd: Any, *args: Any) -> Any:
        result = original_read(fd, *args)
        if b"FOREIGN RESULT" in result:
            reads.append(result)
        return result

    monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    monkeypatch.setattr(release.os, "read", reading)
    _gate_write_fake_worker(c, monkeypatch)
    assert release._supervise_release_invocation(c) == 3
    assert reads == []


def test_gate_write_partial_late_member_is_rejected_before_new_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "run"
    directory = root / "invocations/gate-input/001"
    directory.mkdir(parents=True)
    c = release.ReleaseInvocation(directory, root, {})
    stage = directory / "staged"
    stage.mkdir()
    p = stage / "old"
    p.write_bytes(b"old")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    changed = []
    original_read = release.os.read
    try:
        pins = {}
        release._release_gate_partial_projection_at(c, fd, observed_identities=pins)

        def reading(number: Any, *args: Any) -> Any:
            raw = original_read(number, *args)
            if raw == b"old" and (not changed):
                (stage / "new").write_bytes(b"foreign")
                changed.append(True)
            return raw

        monkeypatch.setattr(release.os, "read", reading)
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_partial_projection_at(c, fd, expected_identities=pins)
        assert changed
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "failure", ["normal", "stderr-create", "directory-fsync", "terminal-write"]
)
def test_gate_write_supervisor_closes_owned_descriptors_on_every_exit(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    c = _gate_write_reserved
    owned = []
    original_open = release.os.open
    original_dup = release.os.dup
    original_pipe = release.os.pipe
    original_fsync = release.os.fsync
    original_write = release._release_gate_write_json_at
    _gate_write_fake_worker(c, monkeypatch)

    def opening(path: Any, flags: Any, *args: Any, **kwargs: Any) -> Any:
        if failure == "stderr-create" and path == "stderr":
            raise OSError("controlled stderr creation failure")
        fd = original_open(path, flags, *args, **kwargs)
        owned.append(fd)
        return fd

    def dup(fd: Any) -> Any:
        result = original_dup(fd)
        owned.append(result)
        return result

    def pipe() -> Any:
        a, b = original_pipe()
        owned.extend((a, b))
        return (a, b)

    def fsync(fd: Any) -> Any:
        if failure == "directory-fsync" and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("controlled directory fsync failure")
        return original_fsync(fd)

    def writing(fd: Any, name: Any, value: Any) -> Any:
        if failure == "terminal-write" and name == "invocation.json":
            raise OSError("controlled terminal write failure")
        return original_write(fd, name, value)

    monkeypatch.setattr(release.os, "open", opening)
    monkeypatch.setattr(release.os, "dup", dup)
    monkeypatch.setattr(release.os, "pipe", pipe)
    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    if failure == "normal":
        assert release._supervise_release_invocation(c) == 3
    else:
        with pytest.raises(release.ReleaseControlError):
            release._supervise_release_invocation(c)
    for fd in set(owned):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_gate_write_wait_failure_stops_original_worker_before_negative_completion(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _gate_write_reserved
    events = []

    class Child:
        pid = 987654321

        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        def wait(self) -> Any:
            events.append("wait")
            if events == ["wait"]:
                raise OSError("controlled wait failure")
            return -9

        def kill(self) -> Any:
            events.append("kill")

    monkeypatch.setattr(release.subprocess, "Popen", Child)

    def stop(pid: Any) -> Any:
        events.append("quiesce")
        return True

    monkeypatch.setattr(release, "_stop_worker_group", stop)
    assert release._supervise_release_invocation(c) == 3
    assert events == ["wait", "kill", "wait", "quiesce"]
    assert json.loads((c.directory / "invocation.json").read_bytes())["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "receipt", ["empty", "wrong-type", "extra-field", "trailing-message", "wrong-inode"]
)
def test_gate_write_worker_result_requires_complete_actual_identity_handoff(
    _gate_write_reserved: Any, monkeypatch: pytest.MonkeyPatch, receipt: Any
) -> None:
    c = _gate_write_reserved
    original_write = release._release_gate_write_json_at

    def wait(kw: Any) -> Any:
        fd = kw["pass_fds"][0]
        identity = original_write(
            fd,
            "worker-result.json",
            {
                "schema_version": "metriplane.release-worker-result.v1",
                "exit_code": 3,
                "outputs": [],
                "producer_intent_digest": release.sha256_json(c.intent),
            },
        )
        if receipt == "empty":
            raw = b""
        elif receipt == "wrong-type":
            raw = release.canonical_json({"result_identity": [True] * 7})
        elif receipt == "extra-field":
            raw = release.canonical_json({"result_identity": identity, "extra": 1})
        elif receipt == "trailing-message":
            raw = release.canonical_json({"result_identity": identity}) + b"{}"
        else:
            raw = release.canonical_json(
                {"result_identity": [identity[0], identity[1] + 1, *identity[2:]]}
            )
        if raw:
            os.write(kw["pass_fds"][1], raw)

    _gate_write_fake_worker(c, monkeypatch, on_wait=wait)
    assert release._supervise_release_invocation(c) == 3
    assert (c.directory / "stderr").stat().st_size > 0
    assert json.loads((c.directory / "invocation.json").read_bytes())["status"] == "BLOCKED"


@pytest.mark.parametrize("replacement", ["root", "intent"])
def test_gate_write_reservation_retains_original_writer_before_first_read(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    original_write = release._release_gate_write_json_at
    changed: list[Path] = []
    foreign: list[tuple[int, int]] = []
    read_inodes: list[tuple[int, int]] = []
    original_read = release.os.read

    def writing(fd: int, name: str, value: Any) -> tuple[int, ...]:
        if name == "intent.json" and replacement == "root":
            saved = _gate_write_replace_directory(root)
            changed.append(saved)
        identity = original_write(fd, name, value)
        if name == "intent.json" and replacement == "intent":
            path = held.directory / name
            raw = path.read_bytes()
            saved = path.with_name("intent-original.json")
            path.rename(saved)
            path.write_bytes(raw)
            observed = path.stat()
            foreign.append((observed.st_dev, observed.st_ino))
            changed.append(saved)
        return identity

    def reading(fd: int, length: int) -> bytes:
        observed = os.fstat(fd)
        if (observed.st_dev, observed.st_ino) in foreign:
            read_inodes.append((observed.st_dev, observed.st_ino))
        return original_read(fd, length)

    monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    monkeypatch.setattr(release.os, "read", reading)
    with pytest.raises(release.ReleaseControlError):
        _gate_reservation_reserve(root, argv, held)
    assert changed and read_inodes == []
    if replacement == "root":
        assert not (held.directory / "intent.json").exists()
        assert (changed[0] / held.directory.relative_to(root) / "intent.json").exists()


@pytest.mark.parametrize("partial_kind", ["path-order", "unreadable"])
def test_gate_write_retry_preserves_original_negative_partial_semantics(
    _gate_reservation_prepared: Any, monkeypatch: pytest.MonkeyPatch, partial_kind: str
) -> None:
    root, argv, held = _gate_reservation_prepared
    context = _gate_reservation_reserve(root, argv, held)
    for name in ("stdout", "stderr"):
        (context.directory / name).write_bytes(b"")
    staged = context.directory / "staged"
    staged.mkdir()
    if partial_kind == "path-order":
        (staged / "a").mkdir()
        (staged / "a/z").write_bytes(b"original nested bytes")
        (staged / "a-").write_bytes(b"original sibling bytes")
    else:
        (staged / "unreadable-file").write_bytes(b"original inaccessible partial")
        original_open = release.os.open

        def opening(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if Path(path).name == "unreadable-file" and flags & os.O_ACCMODE == os.O_RDONLY:
                raise PermissionError("controlled original partial read failure")
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(release.os, "open", opening)
    # Preserve an actual old common negative journal as the compatibility input.
    release._retain_partial_files(context)
    release._complete_invocation(context, 3, [])
    original_terminal = (context.directory / "invocation.json").read_bytes()
    original_partial = (context.directory / "partial-files.json").read_bytes()
    next_directory = context.directory.with_name("002")
    next_argv = list(argv)
    next_argv[next_argv.index("--invocation-dir") + 1] = str(next_directory)
    next_held = release._release_gate_prepare_inputs(next_argv[1:], next_directory)
    successor = release.begin_release_invocation(
        argv[0],
        next_argv[1:],
        next_directory,
        input_paths=[
            (root / name, "metriplane." + kind + ".v1")
            for name, kind, _, _, _ in next_held.captured.rows
        ],
        planned_outputs=[(root / name, kind) for name, kind in release._RELEASE_GATE_OUTPUT_PLAN],
        _gate_inputs=next_held,
    )
    assert successor.intent["predecessor"]["terminal_digest"] == release.sha256_bytes(
        original_terminal
    )
    assert (context.directory / "invocation.json").read_bytes() == original_terminal
    assert (context.directory / "partial-files.json").read_bytes() == original_partial
    assert isinstance(successor, release._ReleaseGateInvocation)
    assert successor.prior_capture is not None and successor.prior_inventory is not None
    if partial_kind == "path-order":
        names = [row["path"] for row in json.loads(original_partial)["files"]]
        assert names == [
            "invocations/gate-input/001/staged/a/z",
            "invocations/gate-input/001/staged/a-",
        ]
    else:
        assert json.loads(original_partial)["unreadable"] == [
            "invocations/gate-input/001/staged/unreadable-file"
        ]
        assert not any(row[0].endswith("/unreadable-file") for row in successor.prior_capture.rows)
        assert str(staged / "unreadable-file") in successor.prior_inventory["entries"]


@pytest.mark.parametrize("fault", ["none", "kill", "reap"])
@pytest.mark.parametrize("settled", [True, False])
def test_gate_write_cancellation_always_attempts_original_group_quiescence(
    _gate_write_reserved: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    settled: bool,
) -> None:
    context = _gate_write_reserved
    events: list[str] = []

    class Child:
        pid = 987654321

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            events.append("spawn")

        def wait(self) -> int:
            events.append("wait")
            if events.count("wait") == 1:
                raise KeyboardInterrupt
            if fault == "reap":
                raise OSError("controlled cancellation reap failure")
            return -2

        def kill(self) -> None:
            events.append("kill")
            if fault == "kill":
                raise ProcessLookupError("controlled cancellation kill race")

    def stop(pid: int) -> bool:
        assert pid == Child.pid
        events.append("quiesce")
        return settled

    monkeypatch.setattr(release.subprocess, "Popen", Child)
    monkeypatch.setattr(release, "_stop_worker_group", stop)
    if settled:
        assert release._supervise_release_invocation(context) == (130 if fault == "none" else 3)
        terminal = json.loads((context.directory / "invocation.json").read_bytes())
        assert terminal["status"] == ("CANCELLED" if fault == "none" else "BLOCKED")
    else:
        with pytest.raises(release.ReleaseControlError, match="incomplete"):
            release._supervise_release_invocation(context)
        assert not (context.directory / "invocation.json").exists()
    assert events.count("quiesce") == 1
    assert events[-1] == "quiesce"
    assert events[:3] == ["spawn", "wait", "kill"]
    assert (context.directory / "intent.json").exists()


_FIXTURE_NATIVE_MUTATIONS = [
    "admin-alias",
    "request-extra",
    "request-subject",
    "request-operation",
    "response-extra",
    "response-backend",
    "response-namespace",
    "response-binding",
    "trace-missing",
    "trace-extra",
    "trace-effect",
    "trace-before",
    "duplicate-json",
    "nan-json",
    "receipt-extra",
    "receipt-domain",
    "receipt-ordinal",
    "receipt-intent",
    "receipt-sequence",
    "receipt-tool",
    "receipt-scope",
    "receipt-window",
    "receipt-future",
    "receipt-time-type",
    "receipt-time-offset",
    "ref-traversal",
    "ref-wrong-suffix",
    "ref-response-alias",
    "ref-size-bool",
    "ref-raw-digest",
    "wrong-signer",
    "bad-signature",
    "live-signature",
    "signature-provider",
]


def _fixture_native_rawref(path: Any, raw: Any) -> Any:
    return {"path": path, "bytes": len(raw), "sha256": release.sha256_bytes(raw)}


def _fixture_native_sign(receipt: Any, actor: Any = None) -> Any:
    subject = release.sha256_json({k: v for k, v in receipt.items() if k != "signature"})
    actor = actor or release._RELEASE_FIXTURE_NATIVE_ACTOR
    receipt["signature"] = {
        "actor_id": actor,
        "algorithm": "test-sha256-v1",
        "provider": "test-fixture",
        "subject_digest": subject,
        "synthetic": True,
        "signature": release.sha256_json({"actor_id": actor, "subject_digest": subject}),
    }


def _fixture_native_registry_bundle(mutation: Any = None) -> Any:
    original = (
        Path(release.__file__).absolute().parents[1] / "docs/status/release-evidence-stores.json"
    )
    data = json.loads(original.read_bytes())
    files = {}
    controls = {}
    for index, row in enumerate(data["backends"]):
        if index == 0 and mutation and mutation.startswith("namespace-"):
            field = "preflight" if mutation.endswith("preflight") else "test"
            row["namespaces"][field] = (
                row["namespaces"][field]
                .replace("release-preflight/", "release-preflight/../../production/")
                .replace("release-tests/", "release-tests/../../production/")
            )
        values = {
            "public_configuration": {"fixture_only": True},
            "owner_binding_authority": {"fixture_actor": release._RELEASE_FIXTURE_NATIVE_ACTOR},
            "provider_resource_identity": {"resource_id": "synthetic-resource-" + str(index)},
            "administration_identity": {"administration_id": "synthetic-admin-" + str(index)},
            "durability_retention_policy": {
                "mode": "retain_indefinitely",
                "deletion": "forbidden",
                "hold": "governance_hold_required",
            },
            "namespace_policy": {key: row["namespaces"][key] for key in ["preflight", "test"]},
        }
        if index == 1 and mutation == "resource-alias":
            values["provider_resource_identity"]["resource_id"] = "synthetic-resource-0"
        if index == 1 and mutation == "control-admin-alias":
            values["administration_identity"]["administration_id"] = "synthetic-admin-0"
        if index == 0 and mutation == "control-id-alias":
            values["provider_resource_identity"]["resource_id"] += " "
        row["binding_status"] = "BOUND_CONFIGURED"
        binding = {"adapter_id": "synthetic-fixture-native-v1"}
        for key, value in values.items():
            name = "controls/" + row["backend_id"] + "/" + key + ".json"
            raw = (
                json.dumps(
                    {
                        "schema_version": "metriplane.release-fixture-backend-control.v1",
                        "control_kind": key,
                        "backend_id": row["backend_id"],
                        "value": value,
                    },
                    indent=2,
                ).encode()
                + b"\n"
            )
            binding[key] = _fixture_native_rawref(name, raw)
            files[name] = raw
        row["live_binding"] = binding
        controls[row["backend_id"]] = values
    for declaration, row in zip(data["stores"], data["backends"][:2], strict=True):
        declaration["live_binding"] = {
            "backend_id": row["backend_id"],
            "binding_digest": release.sha256_json(row["live_binding"]),
        }
    return (data, files, controls)


def _fixture_native_registry() -> Any:
    return _fixture_native_registry_bundle()[0]


def _fixture_native_backend_controls() -> Any:
    return _fixture_native_registry_bundle()[2]


def _fixture_native_preflight_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any = None,
    *,
    relative: Any = False,
    relocate: Any = False,
) -> Any:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    root = tmp_path / "historical"
    root.mkdir()
    stores = root / "inputs/stores.json"
    stores.parent.mkdir()
    registry_data, control_files, controls = _fixture_native_registry_bundle(mutation)
    stores.write_bytes(json.dumps(registry_data, indent=2).encode() + b"\n")
    for name, raw in control_files.items():
        target = stores.parent / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    registry_raw = stores.read_bytes()
    registry_digest = release.sha256_bytes(registry_raw)
    tool = "validate_release_evidence_stores.py"
    args = {
        "stores": str(stores),
        "mode": "preflight",
        "scope": "fixture-run",
        "require-backends": "all",
    }
    subject, operations = release._release_fixture_preflight_expectations(
        args,
        registry_raw=registry_raw,
        expected_registry_digest=registry_digest,
        backend_controls=controls,
    )
    plan = release._release_fixture_native_plan(
        tool=tool, sequence=1, subject=subject, operations=operations
    )
    output = root / "preflight.json"
    directory = root / "invocations/validate-release-evidence-stores/001"
    native_outputs = [
        (root / row["paths"][field], kind)
        for row in plan
        for field, kind in [
            ("request", "metriplane.release-fixture-native-request.v1"),
            ("response", "application/octet-stream"),
            ("receipt", release._RELEASE_FIXTURE_NATIVE_WIRE),
        ]
    ]
    argv = [
        "--stores",
        str(stores),
        "--mode",
        "preflight",
        "--scope",
        "fixture-run",
        "--require-backends",
        "all",
        "--out",
        str(output),
        "--invocation-dir",
        str(directory),
    ]
    if relative:
        monkeypatch.chdir(root)
        argv = [v.replace(str(root) + "/", "") if isinstance(v, str) else v for v in argv]
    extra_output = None
    if mutation in {"unrelated-extra-output", "other-native-stage-output"}:
        name = (
            "unexpected.bin"
            if mutation == "unrelated-extra-output"
            else "native-fixture/another-stage/001/response.bin"
        )
        extra_output = root / name
        native_outputs.append((extra_output, "application/octet-stream"))
    original = release.begin_release_invocation(
        tool,
        argv,
        directory,
        input_paths=[
            (stores, "metriplane.release-evidence-stores.v1"),
            *[(stores.parent / name, "application/octet-stream") for name in control_files],
        ],
        planned_outputs=[
            (output, "metriplane.release-evidence-store-preflight.v1"),
            *native_outputs,
        ],
    )
    refs = []
    all_paths = [
        stores,
        directory / "intent.json",
        *[stores.parent / name for name in control_files],
    ]
    for index, row in enumerate(plan):
        request = copy.deepcopy(row["request"])
        request_arguments = request["arguments"]
        response = {
            "backend_id": request_arguments["backend_id"],
            "binding_digest": request_arguments["binding_digest"],
            "namespace": request_arguments["namespace"],
            "administration_identity": "synthetic-admin-" + str(index),
            "resource_id": request_arguments["resource_id"],
            "trace": release._release_fixture_preflight_trace(request_arguments),
        }
        if mutation == "admin-alias" and index == 1:
            response["administration_identity"] = "synthetic-admin-0"
        if index == 0:
            if mutation == "request-extra":
                request["extra"] = 1
            if mutation == "request-subject":
                request["subject"]["subject_digest"] = "e" * 64
            if mutation == "request-operation":
                request["kind"] = "index.read"
            if mutation == "response-extra":
                response["extra"] = 1
            if mutation == "response-backend":
                response["backend_id"] = "attempt-index"
            if mutation == "response-namespace":
                response["namespace"] = "metriplane/releases/real"
            if mutation == "response-binding":
                response["binding_digest"] = "e" * 64
            if mutation == "trace-missing":
                response["trace"].pop()
            if mutation == "trace-extra":
                response["trace"].append(response["trace"][0])
            if mutation == "trace-effect":
                response["trace"][0]["effect"] = "PASS"
            if mutation == "trace-before":
                response["trace"][0]["before"] = {"generation": 9}
        request_raw = json.dumps(request, indent=2).encode() + b"\n"
        response_raw = json.dumps(response, indent=2).encode() + b"\n"
        if index == 0 and mutation == "duplicate-json":
            response_raw = b'{"backend_id":"x","backend_id":"x"}'
        if index == 0 and mutation == "nan-json":
            response_raw = b'{"x":NaN}'
        receipt = {
            "schema_version": release._RELEASE_FIXTURE_NATIVE_WIRE,
            "scope": release._RELEASE_FIXTURE_NATIVE_SCOPE,
            "producer": {
                "tool": tool,
                "invocation_id": original.intent["invocation_id"],
                "sequence": 1,
                "intent_digest": release.sha256_json(original.intent),
            },
            "subject": subject,
            "ordinal": index + 1,
            "request": _fixture_native_rawref(row["paths"]["request"], request_raw),
            "response": _fixture_native_rawref(row["paths"]["response"], response_raw),
            "started_at": original.intent["started_at"],
            "completed_at": original.intent["started_at"],
        }
        if index == 0:
            if mutation == "receipt-extra":
                receipt["extra"] = 1
            if mutation == "receipt-domain":
                receipt["subject"] = {**subject, "kind": "release_context"}
            if mutation == "receipt-ordinal":
                receipt["ordinal"] = True
            if mutation == "receipt-intent":
                receipt["producer"]["intent_digest"] = "e" * 64
            if mutation == "receipt-sequence":
                receipt["producer"]["sequence"] = 2
            if mutation == "receipt-tool":
                receipt["producer"]["tool"] = "retain_release_evidence.py"
            if mutation == "receipt-scope":
                receipt["scope"] = "LIVE"
            if mutation == "receipt-window":
                receipt["started_at"] = "2000-01-01T00:00:00Z"
            if mutation == "receipt-future":
                receipt["completed_at"] = "2099-01-01T00:00:00Z"
            if mutation == "receipt-time-type":
                receipt["started_at"] = 1
            if mutation == "receipt-time-offset":
                receipt["started_at"] = "2026-01-01T00:00:00+00:60"
            if mutation == "ref-traversal":
                receipt["request"]["path"] = "../outside"
            if mutation == "ref-wrong-suffix":
                receipt["request"]["path"] += ".copy"
            if mutation == "ref-response-alias":
                receipt["response"]["path"] = row["paths"]["request"]
            if mutation == "ref-size-bool":
                receipt["request"]["bytes"] = True
            if mutation == "ref-raw-digest":
                receipt["request"]["sha256"] = "e" * 64
        _fixture_native_sign(
            receipt,
            actor="another-fixture-actor" if mutation == "wrong-signer" and index == 0 else None,
        )
        if index == 0:
            if mutation == "bad-signature":
                receipt["signature"]["signature"] = "e" * 64
            if mutation == "live-signature":
                receipt["signature"]["synthetic"] = False
            if mutation == "signature-provider":
                receipt["signature"]["provider"] = "github"
        receipt_raw = json.dumps(receipt, indent=2).encode() + b"\n"
        for field, content in [
            ("request", request_raw),
            ("response", response_raw),
            ("receipt", receipt_raw),
        ]:
            target = root / row["paths"][field]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            all_paths.append(target)
        refs.append(_fixture_native_rawref(row["paths"]["receipt"], receipt_raw))
    record = release.make_record(
        "release-evidence-store-preflight",
        {
            "producer_intent_digest": release.sha256_json(original.intent),
            "invocation_root_locator": "invocations",
        },
        invocation_id=original.intent["invocation_id"],
        sequence=1,
        synthetic=True,
        status="PASS",
    )
    output.write_bytes(release.canonical_json(record))
    all_paths.append(output)
    for name in ["stdout", "stderr"]:
        (directory / name).write_bytes(b"")
        all_paths.append(directory / name)
    if extra_output is not None:
        extra_output.parent.mkdir(parents=True, exist_ok=True)
        extra_output.write_bytes(b"coherent but undeclared fixture operation")
        all_paths.append(extra_output)
    output_rows = [
        {
            "path": row["path"],
            "schema_id": row["schema_id"],
            "sha256": release.sha256_bytes((root / row["path"]).read_bytes()),
        }
        for row in original.intent["planned_outputs"]
    ]
    release._complete_invocation(original, 0, output_rows)
    all_paths.append(directory / "invocation.json")
    terminal = release._source_json((directory / "invocation.json").read_bytes(), "terminal")
    names = [path.relative_to(root).as_posix() for path in all_paths]
    if relocate:
        new_root = tmp_path / "relocated"
        shutil.move(root, new_root)
        root = new_root
        directory = root / "invocations/validate-release-evidence-stores/001"
        original = release._validate_intent_bytes(
            directory, (directory / "intent.json").read_bytes()
        )
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [(name, "prerequisite-original") for name in names],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    kwargs = {
        "captured": captured,
        "record_path": root / "preflight.json",
        "expected_inputs": {
            "stores": [
                {
                    "path": "inputs/stores.json",
                    "schema_id": "metriplane.release-evidence-stores.v1",
                    "sha256": registry_digest,
                }
            ]
        },
        "selection": {"registry_digest": registry_digest},
        "proof_refs": refs,
        "use_interval": (original.intent["started_at"], terminal["data"]["completed_at"]),
        "live": False,
    }
    return (original, kwargs, plan)


@pytest.mark.parametrize(
    "relative,relocate", [(False, False), (True, False), (False, True), (True, True)]
)
def test_fixture_native_actual_original_intent_and_fixture_receipts_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: Any, relocate: Any
) -> None:
    original, kwargs, plan = _fixture_native_preflight_fixture(
        tmp_path, monkeypatch, relative=relative, relocate=relocate
    )
    facts = release._release_fixture_native_replay(original, **kwargs)
    assert len(facts.operations) == 7 and len(facts.raw_inventory) == 21
    assert len(facts.original_input_inventory) == 43
    assert all((isinstance(row, bytes) for row in facts.operations))
    assert json.loads(facts.producer_identity)["intent_digest"] == release.sha256_json(
        original.intent
    )
    assert not hasattr(facts, "verified_derived")
    with pytest.raises(Exception):
        facts.operations = ()
    if relocate:
        assert not (tmp_path / "historical").exists()
    assert (
        release._release_fixture_native_plan(
            tool=original.intent["tool"],
            sequence=1,
            subject=json.loads(facts.subject),
            operations=release._release_fixture_preflight_expectations(
                {"mode": "preflight", "scope": "fixture-run", "require-backends": "all"},
                registry_raw=kwargs["captured"].read(
                    "inputs/stores.json", kind="prerequisite-original"
                ),
                expected_registry_digest=kwargs["selection"]["registry_digest"],
                backend_controls=_fixture_native_backend_controls(),
            )[1],
        )
        == plan
    )


@pytest.mark.parametrize("mutation", _FIXTURE_NATIVE_MUTATIONS)
def test_fixture_native_consistent_native_proof_rewrites_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    original, kwargs, _ = _fixture_native_preflight_fixture(tmp_path, monkeypatch, mutation)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_replay(original, **kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "reorder",
        "wrong-input-type",
        "wrong-input-R",
        "input-missing",
        "selection-extra",
        "window-extension",
        "same-byte-root-replacement",
    ],
)
def test_fixture_native_complete_operation_input_and_custody_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    original, kwargs, _ = _fixture_native_preflight_fixture(tmp_path, monkeypatch)
    if mutation == "missing":
        kwargs["proof_refs"].pop()
    if mutation == "extra":
        kwargs["proof_refs"].append(kwargs["proof_refs"][0])
    if mutation == "reorder":
        kwargs["proof_refs"].reverse()
    if mutation == "wrong-input-type":
        kwargs["expected_inputs"]["stores"][0]["schema_id"] = "application/octet-stream"
    if mutation == "wrong-input-R":
        kwargs["expected_inputs"]["stores"][0]["sha256"] = "e" * 64
    if mutation == "input-missing":
        kwargs["expected_inputs"] = {}
    if mutation == "selection-extra":
        kwargs["selection"]["future_final_context_digest"] = "e" * 64
    if mutation == "window-extension":
        kwargs["use_interval"] = ("2000-01-01T00:00:00Z", kwargs["use_interval"][1])
    if mutation == "same-byte-root-replacement":
        saved = original.root.with_name("retained-original")
        original.root.rename(saved)
        shutil.copytree(saved, original.root)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_replay(original, **kwargs)


@pytest.mark.parametrize("live", [True, 0, 1, None, "false"])
def test_fixture_native_live_guard_precedes_all_reads(live: Any) -> None:

    class NoReads:
        def __getattr__(self, key: Any) -> Any:
            raise AssertionError("unexpected capture read")

    original = SimpleNamespace(intent={"environment": {"fixture_mode": "1"}})
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_replay(
            original,
            captured=NoReads(),
            record_path=Path("/absent"),
            expected_inputs={},
            selection={},
            proof_refs=[],
            use_interval=("bad", "bad"),
            live=live,
        )


@pytest.mark.parametrize(
    "kind",
    [
        "release-target-resolution",
        "release-target-burn",
        "release-evidence-manifest",
        "release-staging-attempt",
        "release-index-recovery",
    ],
)
def test_fixture_native_pure_derived_types_get_no_native_credit(kind: Any) -> None:
    tool = next((k for k, v in release._RELEASE_GATE_PREREQUISITES.items() if v[0] == kind))
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_plan(
            tool=tool,
            sequence=1,
            subject={
                "kind": "release_context",
                "subject_digest": "a" * 64,
                "original_policy_digest": "b" * 64,
            },
            operations=[],
        )


def _fixture_native_genesis_raw() -> Any:
    return (
        json.dumps(
            {
                "schema_version": "metriplane.release-fixture-index-genesis.v1",
                "backend_id": "attempt-index",
                "fixture_actor": release._RELEASE_FIXTURE_NATIVE_ACTOR,
                "run_id": "fixture-run",
                "namespace": "metriplane/release-tests/fixture-run/attempt-index",
                "binding_digest": "c" * 64,
            },
            indent=2,
        ).encode()
        + b"\n"
    )


def _fixture_native_entry(generation: Any = 1, previous: Any = None) -> Any:
    scope = {
        "kind": "release_staging",
        "scope_id": "synthetic-run",
        "stage": "target-burn",
        "sequence": 8,
        "run_id": "synthetic-run",
        "candidate_id": None,
        "release_tag": "v0.4.1",
        "milestone": "v0.4",
    }
    return {
        "schema_version": "metriplane.release-attempt-index-entry.v1",
        "backend_id": "attempt-index",
        "genesis_digest": release.sha256_bytes(_fixture_native_genesis_raw()),
        "generation": generation,
        "previous_head": previous,
        "operation_id": "synthetic-operation",
        "token": "opaque-fixture-token",
        "milestone": "v0.4",
        "scope": scope,
        "entry_manifest_digest": "a" * 64,
        "entry_receipts_digest": "b" * 64,
    }


def _fixture_native_index_args(e: Any) -> Any:
    return {
        "index-backend": "attempt-index",
        "expected-head": e["previous_head"] or e["genesis_digest"],
        "operation-id": e["operation_id"],
        "scope-kind": e["scope"]["kind"],
        "sequence": 8,
        "stage": "target-burn",
    }


def test_fixture_native_index_scope_counters_and_empty_complete_history() -> None:
    e = _fixture_native_entry()
    subject, ops = release._release_fixture_index_expectations(
        _fixture_native_index_args(e),
        tool="update_release_attempt_index.py",
        genesis_raw=_fixture_native_genesis_raw(),
        expected_genesis_digest=e["genesis_digest"],
        original_entry=e,
        expected_prior_generation=0,
    )
    req = ops[0]["request"]
    assert "token" not in req and "generation" not in req and ("entry" not in req)
    assert req["prior_generation"] == 0 and req["entry_payload"]["scope"]["sequence"] == 8
    response = {
        "backend_id": "attempt-index",
        "genesis_digest": e["genesis_digest"],
        "operation_id": e["operation_id"],
        "expected_head": e["genesis_digest"],
        "entry": e,
        "committed_head": release.sha256_json(e),
        "read_back_digest": release.sha256_json(e),
        "disposition": "committed",
    }
    assert (
        release._release_fixture_native_response("index.cas", req, release.canonical_json(response))
        == response
    )
    read = {
        "backend_id": "attempt-index",
        "genesis_digest": e["genesis_digest"],
        "namespace": json.loads(_fixture_native_genesis_raw())["namespace"],
        "binding_digest": "c" * 64,
        "through_head": e["genesis_digest"],
    }
    assert (
        release._release_fixture_native_response(
            "index.read", read, release.canonical_json({**read, "entries": []})
        )["entries"]
        == []
    )
    read["through_head"] = release.sha256_json(e)
    assert release._release_fixture_native_response(
        "index.read", read, release.canonical_json({**read, "entries": [e]})
    )["entries"] == [e]


def test_fixture_native_cas_and_export_share_the_same_logical_scope_key() -> None:
    scope = _fixture_native_entry()["scope"]
    rebound = {**scope, "release_tag": "v0.4.2"}
    assert release._release_index_scope_key(scope) == release._release_index_scope_key(rebound)


@pytest.mark.parametrize(
    "mutation",
    ["generation", "head", "operation", "payload", "genesis", "readback", "disposition", "extra"],
)
def test_fixture_native_index_consistent_false_response_rejects(mutation: Any) -> None:
    e = _fixture_native_entry()
    _, ops = release._release_fixture_index_expectations(
        _fixture_native_index_args(e),
        tool="update_release_attempt_index.py",
        genesis_raw=_fixture_native_genesis_raw(),
        expected_genesis_digest=e["genesis_digest"],
        original_entry=e,
        expected_prior_generation=0,
    )
    response = {
        "backend_id": "attempt-index",
        "genesis_digest": e["genesis_digest"],
        "operation_id": e["operation_id"],
        "expected_head": e["genesis_digest"],
        "entry": copy.deepcopy(e),
        "committed_head": release.sha256_json(e),
        "read_back_digest": release.sha256_json(e),
        "disposition": "committed",
    }
    if mutation == "generation":
        response["entry"]["generation"] = True
    if mutation == "head":
        response["expected_head"] = "e" * 64
    if mutation == "operation":
        response["entry"]["operation_id"] = "other"
    if mutation == "payload":
        response["entry"]["entry_manifest_digest"] = "e" * 64
    if mutation == "genesis":
        response["entry"]["genesis_digest"] = "e" * 64
    if mutation == "readback":
        response["read_back_digest"] = "e" * 64
    if mutation == "disposition":
        response["disposition"] = "conflict"
    if mutation == "extra":
        response["extra"] = True
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response(
            "index.cas", ops[0]["request"], release.canonical_json(response)
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "reordered", "duplicate-scope", "duplicate-operation", "changed-genesis"],
)
def test_fixture_native_complete_index_history_rejects(mutation: Any) -> None:
    first = _fixture_native_entry()
    second = _fixture_native_entry(2, release.sha256_json(first))
    second["scope"]["sequence"] = 9
    second["operation_id"] = "another"
    rows = [first, second]
    request = {
        "backend_id": "attempt-index",
        "genesis_digest": first["genesis_digest"],
        "namespace": json.loads(_fixture_native_genesis_raw())["namespace"],
        "binding_digest": "c" * 64,
        "through_head": release.sha256_json(second),
    }
    if mutation == "missing":
        rows = [second]
    if mutation == "reordered":
        rows.reverse()
    if mutation == "duplicate-scope":
        second["scope"]["sequence"] = 8
    if mutation == "duplicate-operation":
        second["operation_id"] = first["operation_id"]
    if mutation == "changed-genesis":
        second["genesis_digest"] = "e" * 64
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response(
            "index.read", request, release.canonical_json({**request, "entries": rows})
        )


@pytest.mark.parametrize("form", ["manifest", "single", "multiple"])
def test_fixture_native_retention_original_R_subject_policy(form: Any) -> None:
    store = release.canonical_json(_fixture_native_registry())
    inputs = (
        [b'{ "original": 1 }\n']
        if form == "single"
        else [b"original b\n", b"original a\n"]
        if form == "multiple"
        else []
    )
    manifest = b'{\n  "entries": []\n}\n' if form == "manifest" else None
    args = {
        "phase": "target-burn",
        **(
            {"manifest": "original.json"}
            if manifest is not None
            else {"input": ["x"] * len(inputs)}
        ),
    }
    subject, operations = release._release_fixture_retention_expectations(
        args,
        original_inputs=inputs,
        original_manifest=manifest,
        registry_raw=store,
        expected_registry_digest=release.sha256_bytes(store),
        fixture_run_id="run",
        backend_controls=_fixture_native_backend_controls(),
    )
    expected = (
        manifest
        if manifest is not None
        else inputs[0]
        if len(inputs) == 1
        else release.canonical_json(sorted((release.sha256_bytes(x) for x in inputs)))
    )
    assert subject["subject_digest"] == release.sha256_bytes(expected) and len(operations) == 6
    assert release._release_fixture_native_response(
        "retention.read", operations[2]["request"], expected
    )["original_digest"] == release.sha256_bytes(expected)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response(
            "retention.read", operations[2]["request"], expected + b" "
        )


@pytest.mark.parametrize("payload", [{"issues": []}, [{"id": "fixture"}]])
def test_fixture_native_linear_original_native_envelope_allows_object_or_array(
    payload: Any,
) -> None:
    raw = json.dumps(
        {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    ).encode()
    assert release._release_fixture_native_response("linear.read", {}, raw)["payload"] == payload


@pytest.mark.parametrize("payload", [{"errors": []}, {"truncated": False}, 1, None, "text"])
def test_fixture_native_linear_native_incomplete_error_payload_rejects(payload: Any) -> None:
    raw = json.dumps(
        {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    ).encode()
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response("linear.read", {}, raw)


def test_fixture_native_role_original_provenance_has_no_self_R_or_future_assignment_C_cycle() -> (
    None
):
    request = {
        "role": "operator",
        "binding": {
            "provider": "github",
            "actor_id": "fictional-operator",
            "provenance_digest": "a" * 64,
        },
        "expected_operator": "fictional-operator",
        "run_id": "fixture-run",
        "milestone": "v0.4",
        "context_digest": "b" * 64,
        "policy_digest": "c" * 64,
        "subjects": [{"subject": "assignment_payload", "sha256": "d" * 64}],
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-01T01:00:00Z",
    }
    response = {k: v for k, v in request.items() if k not in {"binding", "subjects"}}
    response["binding_subject"] = {
        k: v for k, v in request["binding"].items() if k != "provenance_digest"
    }
    response["granting_actor"] = release._RELEASE_FIXTURE_NATIVE_ACTOR
    assert (
        release._release_fixture_native_response(
            "role.delegation", request, release.canonical_json(response)
        )
        == response
    )
    changed = copy.deepcopy(response)
    changed["subjects"] = request["subjects"]
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response(
            "role.delegation", request, release.canonical_json(changed)
        )


@pytest.mark.parametrize("mutation", ["namespace-preflight", "namespace-test"])
def test_fixture_native_coordinator_namespace_countermodels_reject_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    with pytest.raises(release.ReleaseControlError, match="template"):
        _fixture_native_preflight_fixture(tmp_path, monkeypatch, mutation)
    assert not list(tmp_path.rglob("intent.json"))


@pytest.mark.parametrize("mutation", ["resource-alias", "control-admin-alias", "control-id-alias"])
def test_fixture_native_coordinator_resource_and_administration_countermodels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    original, kwargs, _ = _fixture_native_preflight_fixture(tmp_path, monkeypatch, mutation)
    with pytest.raises(release.ReleaseControlError, match="resource|administration|canonical"):
        release._release_fixture_native_replay(original, **kwargs)


@pytest.mark.parametrize(
    "bad",
    [
        "metriplane/release-tests/{run_id}/../payload-a",
        "metriplane/release-tests/{run_id}/payload-a/extra",
        "metriplane/release-tests/{run_id}\\payload-a",
        "metriplane/release-tests/{other}/payload-a",
        "metriplane/release-tests/{run_id}/{run_id}/payload-a",
        "metriplane/release-tests/{run_id}/payload-a\n",
    ],
)
def test_fixture_native_exact_owned_namespace_template_variants(bad: Any) -> None:
    data, _, controls = _fixture_native_registry_bundle()
    data["backends"][0]["namespaces"]["test"] = bad
    raw = release.canonical_json(data)
    with pytest.raises(release.ReleaseControlError, match="template"):
        release._release_fixture_retention_expectations(
            {"phase": "target-burn", "input": ["x"]},
            original_inputs=[b"x"],
            original_manifest=None,
            registry_raw=raw,
            expected_registry_digest=release.sha256_bytes(raw),
            fixture_run_id="fixture-run",
            backend_controls=controls,
        )


def _fixture_native_target_inputs(generic: Any = False) -> Any:
    raw = (
        b'{"data":{"comparison_baseline":{"artifacts":[{"bytes":123,"filename":"metriplane-0.4.0.post2-py3-none-any.whl","kind":"wheel","readback":{"bytes":123,"path":"artifacts/wheel","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"bytes":123,"filename":"metriplane-0.4.0.post2.tar.gz","kind":"sdist","readback":{"bytes":123,"path":"artifacts/sdist","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"normalized_package_version":"0.4.0.post2","release_observation":{"bytes":1,"path":"provider/release.json","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},"release_tag":"v0.4.0.post2","source_commit":"1111111111111111111111111111111111111111","source_tree":"2222222222222222222222222222222222222222","tag_object":"3333333333333333333333333333333333333333","tag_observation":{"bytes":1,"path":"provider/tag.json","sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}},"context_digest":"97a3aa5e828e76d3389b24c9c0a9488000096e492b7fb33076efd70956d20ad7","context_id":"synthetic-patch","context_policy_digest":"b97097ed9304d280cf17ac3d6f6909479a4ded39fa313c13224034314faecb2e","cumulative_bom_snapshot_digest":"b23c391c7fbb5c19098424cb4161987d5d5f11a8ad42ef8e1a17922ae9ecf9d6","decision":{"issue_id":"00000000-0000-0000-0000-00000000005e","issue_identifier":"SYN-94","project_id":"00000000-0000-0000-0000-000000002711","provider":"linear","team_id":"00000000-0000-0000-0000-000000002713"},"direct_gate_issues":[{"issue_id":"00000000-0000-0000-0000-00000000005f","issue_identifier":"SYN-95","project_id":"00000000-0000-0000-0000-000000002712","provider":"linear","team_id":"00000000-0000-0000-0000-000000002713"}],"framework_milestone":"v0.4","linear_snapshot_digest":"998be2d01e2dd10cff2e34e08eb4cdda91c4d69c858ce86022493abc263e35c8","predecessor_policy_digest":"f31b79a8f0ea112cacef1724fda29287e97c72fffab4eeef9782959b179f25e7","predecessor_requirement":"VALIDATE_ORIGINAL_GENESIS_OR_RECONCILED_LKG_GRAPH_UNDER_BOUND_POLICY","provider_milestone":{"id":"00000000-0000-0000-0000-000000007531","name":"Synthetic patch milestone","project_id":"00000000-0000-0000-0000-000000002711"},"readiness_registry_digest":"282d13513e4c887c6bf62a6c5bbd83ae9e0dc1ff89f868f2cbdffcf79fb36c72","roadmap_catalog_task_id":null,"target_policy":{"conflict_disposition":"DURABLE_BURN_THEN_SAME_MILESTONE_PATCH","initial_normalized_package_version":"0.4.1","initial_release_tag":"v0.4.1","resolution_mode":"next_unused_same_milestone_patch"}},"invocation_id":"synthetic-context","payload_digest":"c2249fb4d56b1e90d497d8213c02ea1f4253cbd344c2818f6be06b0b10e50d36","record_id":"10e7828ed03c47f1e38630f28ee02507f0f451ac90481139f485f6e723e2e100","record_type":"release-context","schema_version":"metriplane.release-record.v1","sequence":1,"signatures":[],"status":"PASS","synthetic":true}'
        if generic
        else b'{"data":{"comparison_baseline":{"artifacts":[{"bytes":123,"filename":"metriplane-0.4.0.post2-py3-none-any.whl","kind":"wheel","readback":{"bytes":123,"path":"artifacts/wheel","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"bytes":123,"filename":"metriplane-0.4.0.post2.tar.gz","kind":"sdist","readback":{"bytes":123,"path":"artifacts/sdist","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"normalized_package_version":"0.4.0.post2","release_observation":{"bytes":1,"path":"provider/release.json","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},"release_tag":"v0.4.0.post2","source_commit":"1111111111111111111111111111111111111111","source_tree":"2222222222222222222222222222222222222222","tag_object":"3333333333333333333333333333333333333333","tag_observation":{"bytes":1,"path":"provider/tag.json","sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}},"context_digest":"30df7af13682c07ddf2769feeef3830673d8372b15e75fb081161f72ccff80bd","context_id":"synthetic-patch","context_policy_digest":"58bd0447763967d97c6c9f41e924a578211ae265161a82a2430f074b1923bfe3","cumulative_bom_snapshot_digest":"b23c391c7fbb5c19098424cb4161987d5d5f11a8ad42ef8e1a17922ae9ecf9d6","decision":{"issue_id":"00000000-0000-0000-0000-00000000005e","issue_identifier":"SYN-94","project_id":"00000000-0000-0000-0000-000000002711","provider":"linear","team_id":"00000000-0000-0000-0000-000000002713"},"direct_gate_issues":[{"issue_id":"00000000-0000-0000-0000-00000000005f","issue_identifier":"SYN-95","project_id":"00000000-0000-0000-0000-000000002712","provider":"linear","team_id":"00000000-0000-0000-0000-000000002713"}],"framework_milestone":"v0.4","linear_snapshot_digest":"9ff9aa121cae3eb78d65fe6befad4f47f2c58d3c00199244bfdec7841e7f7bf0","predecessor_policy_digest":"f31b79a8f0ea112cacef1724fda29287e97c72fffab4eeef9782959b179f25e7","predecessor_requirement":"VALIDATE_ORIGINAL_GENESIS_OR_RECONCILED_LKG_GRAPH_UNDER_BOUND_POLICY","provider_milestone":{"id":"00000000-0000-0000-0000-000000007531","name":"Synthetic patch milestone","project_id":"00000000-0000-0000-0000-000000002711"},"readiness_registry_digest":"dfa9879b487bd099d5ba626f672b01bc7f3bb506d07b788e72ce5ebeab74269f","roadmap_catalog_task_id":null,"target_policy":{"conflict_disposition":"BLOCKED_REQUIRES_NEW_OWNER_RELEASE_IDENTITY","initial_normalized_package_version":"0.4.1","initial_release_tag":"v0.4.1","resolution_mode":"owner_approved_exact_target"}},"invocation_id":"synthetic-context","payload_digest":"1fd6602515abaa38085bba78f26925a0bebdc48388d765397900a5b5995d1eed","record_id":"def6a1ae1d68fa96e24d67ac09d9627b32641a0a51b6855f3054993699bd21d3","record_type":"release-context","schema_version":"metriplane.release-record.v1","sequence":1,"signatures":[],"status":"PASS","synthetic":true}'
    )
    return (
        json.loads(raw),
        (
            Path(release.__file__).absolute().parents[1] / "docs/status/release-targets.json"
        ).read_bytes(),
    )


def test_fixture_native_target_current_exact_identity_and_closed_three_native_domains() -> None:
    context, raw = _fixture_native_target_inputs()
    subject, operations = release._release_fixture_target_expectations(
        {"provider-auth-from-approved-environment": True},
        context=context,
        expected_context_digest=release.sha256_json(context),
        registry_raw=raw,
        expected_registry_digest=release.sha256_bytes(raw),
        requested_versions=["0.4.1"],
    )
    assert [op["request"]["target_id"] for op in operations] == [
        "github-release",
        "pypi",
        "testpypi",
    ]
    for op in operations:
        request = op["request"]
        response = {
            k: request[k] for k in ["target_id", "normalized_package_version", "release_tag"]
        }
        response.update(state="unused", artifacts=[])
        assert (
            release._release_fixture_native_response(
                "target.query", request, release.canonical_json(response)
            )
            == response
        )
    assert subject["kind"] == "release_context"


@pytest.mark.parametrize(
    "versions", [[], ["0.4.0"], ["v0.4.1"], ["0.4.1", "0.4.2"], ["0.4.1", "0.4.1"], ["0.4.0.post2"]]
)
def test_fixture_native_exact_target_no_fallback_or_automatic_identity(versions: Any) -> None:
    context, raw = _fixture_native_target_inputs()
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_target_expectations(
            {"provider-auth-from-approved-environment": True},
            context=context,
            expected_context_digest=release.sha256_json(context),
            registry_raw=raw,
            expected_registry_digest=release.sha256_bytes(raw),
            requested_versions=versions,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "wrong-tag",
        "wrong-target",
        "unused-artifacts",
        "filename-unsafe",
        "size-bool",
        "duplicate-artifact",
        "extra",
    ],
)
def test_fixture_native_target_fixed_native_response_failures(mutation: Any) -> None:
    request = {"target_id": "pypi", "normalized_package_version": "0.4.1", "release_tag": "v0.4.1"}
    row = {
        **request,
        "state": "occupied",
        "artifacts": [
            {
                "name": "metriplane.whl",
                "bytes": 1,
                "sha256": release.sha256_bytes(b"x"),
                "original_read_back": _fixture_native_rawref("artifact-readbacks/wheel.bin", b"x"),
            }
        ],
    }
    if mutation == "unknown":
        row["state"] = "unknown"
    if mutation == "wrong-tag":
        row["release_tag"] = "v0.4.2"
    if mutation == "wrong-target":
        row["target_id"] = "testpypi"
    if mutation == "unused-artifacts":
        row["state"] = "unused"
    if mutation == "filename-unsafe":
        row["artifacts"][0]["name"] = "../metriplane.whl"
    if mutation == "size-bool":
        row["artifacts"][0]["bytes"] = True
    if mutation == "duplicate-artifact":
        row["artifacts"].append(row["artifacts"][0])
    if mutation == "extra":
        row["future_context_C"] = "a" * 64
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_response(
            "target.query", request, release.canonical_json(row)
        )


def _fixture_native_linear_inputs() -> Any:
    policy = {"context_id": "fixture-context", "decision": {"project_id": "fixture-project"}}
    raw = json.dumps({"release_contexts": [policy]}, indent=2).encode() + b"\n"
    observations = {
        f"round-{n}": {
            "observation": {
                "id": f"round-{n}",
                "round": n,
                "tool": "mcp__codex_apps__linear_get_issue",
                "arguments": {"id": "MET-163", "includeRelations": True},
                "started_at": f"2026-01-01T00:00:0{n}Z",
                "completed_at": f"2026-01-01T00:00:0{n}Z",
            }
        }
        for n in [1, 2]
    }
    paths = {key: key + ".json" for key in observations}
    return (policy, raw, observations, paths)


def test_fixture_native_linear_policy_domain_is_acyclic_and_preserves_original_R() -> None:
    policy, raw, observations, paths = _fixture_native_linear_inputs()
    subject, operations = release._release_fixture_linear_expectations(
        {"project-id": "fixture-project"},
        readiness_raw=raw,
        expected_readiness_digest=release.sha256_bytes(raw),
        context_id="fixture-context",
        expected_context_policy_digest=release.sha256_json(policy),
        replayed_observations=observations,
        response_paths=paths,
    )
    assert subject == {
        "kind": "readiness_context_policy",
        "subject_digest": release.sha256_json(policy),
        "original_policy_digest": release.sha256_bytes(raw),
    }
    assert release.sha256_bytes(raw) != release.sha256_json(json.loads(raw))
    assert len(operations) == 2 and all(
        ("final_context" not in json.dumps(op) for op in operations)
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_native_plan(
            tool="capture_linear_release_snapshot.py",
            sequence=1,
            subject={**subject, "kind": "release_context"},
            operations=operations,
        )


@pytest.mark.parametrize(
    "mutation",
    ["policy-C", "raw-R", "project", "missing-round", "alias-path", "wrong-id", "missing-response"],
)
def test_fixture_native_linear_constructor_original_policy_and_request_inventory(
    mutation: Any,
) -> None:
    policy, raw, observations, paths = _fixture_native_linear_inputs()
    kwargs = dict(
        readiness_raw=raw,
        expected_readiness_digest=release.sha256_bytes(raw),
        context_id="fixture-context",
        expected_context_policy_digest=release.sha256_json(policy),
        replayed_observations=observations,
        response_paths=paths,
    )
    args = {"project-id": "fixture-project"}
    if mutation == "policy-C":
        kwargs["expected_context_policy_digest"] = "a" * 64
    if mutation == "raw-R":
        kwargs["expected_readiness_digest"] = release.sha256_json(json.loads(raw))
    if mutation == "project":
        args["project-id"] = "wrong-project"
    if mutation == "missing-round":
        observations["round-2"]["observation"]["round"] = 1
    if mutation == "alias-path":
        paths["round-2"] = paths["round-1"]
    if mutation == "wrong-id":
        observations["round-2"]["observation"]["id"] = "other"
    if mutation == "missing-response":
        paths.pop("round-2")
    with pytest.raises(release.ReleaseControlError):
        subject, operations = release._release_fixture_linear_expectations(args, **kwargs)
        release._release_fixture_native_plan(
            tool="capture_linear_release_snapshot.py",
            sequence=1,
            subject=subject,
            operations=operations,
        )


@pytest.mark.parametrize(
    "mutation", ["actor", "namespace", "placeholder", "backend", "extra", "opaque", "run-alias"]
)
def test_fixture_native_closed_fixture_index_genesis_no_real_backend_or_opaque_authority(
    mutation: Any,
) -> None:
    value = json.loads(_fixture_native_genesis_raw())
    if mutation == "actor":
        value["fixture_actor"] = "real-provider"
    if mutation == "namespace":
        value["namespace"] = "metriplane/release-control/attempt-index"
    if mutation == "placeholder":
        value["namespace"] = "metriplane/release-tests/../../production/attempt-index"
    if mutation == "backend":
        value["backend_id"] = "success-chain"
    if mutation == "extra":
        value["approved"] = True
    if mutation == "run-alias":
        value["run_id"] = "../fixture-run"
    raw = b"opaque original bytes" if mutation == "opaque" else release.canonical_json(value)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_index_genesis(raw)


def _fixture_native_inherited_fixtures() -> Any:
    return sys.modules[__name__]


@pytest.mark.parametrize("purpose", ["burn", "attempt"])
@pytest.mark.parametrize("relative", ["none", "relocate"])
def test_fixture_native_default_index_content_owner_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: Any, relative: Any
) -> None:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    module = _fixture_native_inherited_fixtures()
    receipt, kwargs = module._index_command_build(tmp_path / "legacy-original", purpose, relative)
    result = release._release_index_original_update_binding(receipt, **kwargs)
    assert result["entry"]["operation_id"] == "original-operation-not-attempt-id"
    assert set(result) == {
        "entry",
        "original_update_intent_digest",
        "manifest_record_digest",
        "retention_record_digest",
        "manifest_raw_digest",
        "subject_record_digest",
    }


def _fixture_native_native_index_content_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> Any:
    """Actual common intents; content-only primary fixtures, no worker/native authority."""
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    module = _fixture_native_inherited_fixtures()
    old_entry = module._index_entry_fixture

    def fixture_entry(*args: Any, **kwargs: Any) -> Any:
        value = old_entry(*args, **kwargs)
        value["genesis_digest"] = release.sha256_bytes(_fixture_native_genesis_raw())
        return value

    monkeypatch.setattr(module, "_index_entry_fixture", fixture_entry)
    old_begin = release.begin_release_invocation
    captured_plans = []

    def begin(
        tool: Any, argv: Any, directory: Any, *, input_paths: Any, planned_outputs: Any
    ) -> Any:
        arguments = release._release_original_arguments(tool, [tool, *argv])
        candidate = fixture_entry()
        candidate.update(
            scope={
                "kind": "release_staging",
                "scope_id": "explicit-original-scope",
                "stage": "target-burn",
                "sequence": 1,
                "release_tag": "v0.4.1",
                "candidate_id": None,
                "milestone": "v0.4",
                "run_id": "fixture-run",
            },
            operation_id=arguments["operation-id"],
            entry_manifest_digest=release.sha256_json(
                json.loads(Path(arguments["entry-manifest"]).read_bytes())
            ),
            entry_receipts_digest=release.sha256_json(
                json.loads(Path(arguments["entry-receipts"]).read_bytes())
            ),
        )
        subject, ops = release._release_fixture_index_expectations(
            arguments,
            tool=tool,
            genesis_raw=_fixture_native_genesis_raw(),
            expected_genesis_digest=candidate["genesis_digest"],
            original_entry=candidate,
            expected_prior_generation=18,
        )
        plan = release._release_fixture_native_plan(
            tool=tool, sequence=int(directory.name), subject=subject, operations=ops
        )
        root = directory.parents[2]
        outputs = list(planned_outputs) + [
            (root / plan[0]["paths"][field], kind)
            for field, kind in (
                ("request", "metriplane.release-fixture-native-request.v1"),
                ("response", "application/octet-stream"),
                ("receipt", release._RELEASE_FIXTURE_NATIVE_WIRE),
            )
        ]
        if mutation == "extra":
            outputs.append((root / "native-fixture/extra.bin", "application/octet-stream"))
        if mutation == "wrong-type":
            outputs[-1] = (outputs[-1][0], "application/octet-stream")
        captured_plans.append(plan)
        return old_begin(tool, argv, directory, input_paths=input_paths, planned_outputs=outputs)

    monkeypatch.setattr(release, "begin_release_invocation", begin)
    receipt, kwargs = module._index_command_build(
        tmp_path / "native-original", "burn", "none", " 001 "
    )
    kwargs.update(
        _fixture_native_genesis_raw=_fixture_native_genesis_raw(),
        _fixture_native_prior_generation=18,
    )
    return (receipt, kwargs, captured_plans)


@pytest.mark.parametrize(
    "mutation", ["none", "extra", "wrong-type", "default", "live", "prior-bool", "wrong-genesis"]
)
def test_fixture_native_index_consumer_exact_fixture_plan_amendment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    receipt, kwargs, plans = _fixture_native_native_index_content_fixture(
        tmp_path, monkeypatch, mutation
    )
    if mutation == "default":
        kwargs.pop("_fixture_native_genesis_raw")
        kwargs.pop("_fixture_native_prior_generation")
    if mutation == "live":
        kwargs["expected_synthetic"] = False
    if mutation == "prior-bool":
        kwargs["_fixture_native_prior_generation"] = True
    if mutation == "wrong-genesis":
        kwargs["_fixture_native_genesis_raw"] = _fixture_native_genesis_raw() + b" "
    if mutation != "none":
        with pytest.raises(release.ReleaseControlError):
            release._release_index_original_update_binding(receipt, **kwargs)
    else:
        result = release._release_index_original_update_binding(receipt, **kwargs)
        assert result["entry"]["generation"] == 19 and result["entry"]["scope"]["sequence"] == 1
        assert len(plans) == 2 and len(kwargs["update"].intent["planned_outputs"]) == 4
        assert plans[0][0]["request"] == plans[1][0]["request"]
        assert plans[0][0]["paths"] != plans[1][0]["paths"]


@pytest.mark.parametrize("mutation", ["unrelated-extra-output", "other-native-stage-output"])
def test_fixture_native_complete_fixture_output_inventory_no_opaque_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    original, kwargs, _ = _fixture_native_preflight_fixture(tmp_path, monkeypatch, mutation)
    with pytest.raises(release.ReleaseControlError, match="full output plan"):
        release._release_fixture_native_replay(original, **kwargs)


def _gate_fixture_terminal_content(
    context: Any, code: int, outputs: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic mechanical journal setup; never the native completion producer."""
    assert context.intent["environment"]["fixture_mode"] == "1"
    with monkeypatch.context() as patch:
        patch.setattr(release, "_validate_terminal", release._validate_terminal_entry)
        release._complete_invocation(context, code, outputs)


def _gate_fixture_synthetic_witness(context: Any) -> None:
    """Explicit fixture bytes, not proof that a native worker or release ran."""
    assert context.intent["environment"]["fixture_mode"] == "1"
    terminal = json.loads((context.directory / "invocation.json").read_bytes())
    raw = release.canonical_json(release._release_gate_terminal_commit_record(context, terminal))
    path = context.directory / "terminal-commit.json"
    if path.exists():
        path.chmod(0o600)
    path.write_bytes(raw)


def _gate_completion_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    with monkeypatch.context() as patch:
        patch.setattr(release, "_validate_terminal", release._validate_terminal_entry)
        context, data, catalog, names, outputs = _gate_copy_install_fixture(tmp_path, patch)
        held_stage = _gate_fixture_carried_stage(context)
    monkeypatch.chdir(context.gate_inputs.working_directory)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    release._install_release_outputs(context, outputs, gate_stage_capture=held_stage)
    names = [
        "gate-input.json",
        "scenario-catalog.json",
        *[
            (context.directory / n).relative_to(context.root).as_posix()
            for n in [
                "worker.pid",
                "worker-result.json",
                "staged/gate-input.json",
                "staged/scenario-catalog.json",
            ]
        ],
    ]
    captured = _gate_pair_output_capture(context.root, names)
    completion = release._ReleaseGateCompletion(
        captured, release.canonical_json(data), release.canonical_json(catalog)
    )
    ids = {
        n: release._release_gate_file_identity((context.directory / n).stat())
        for n in ["stdout", "stderr"]
    }
    fd = release._release_gate_open_pinned_directory(
        context.directory, context.intent_capture.rows[0][4]
    )
    return (context, completion, outputs, ids, fd)


def _gate_completion_captured_all(context: Any) -> Any:
    names = [
        "gate-input.json",
        "scenario-catalog.json",
        *[
            (context.directory / n).relative_to(context.root).as_posix()
            for n in [
                "intent.json",
                "invocation.json",
                "stdout",
                "stderr",
                "worker.pid",
                "worker-result.json",
                "staged/gate-input.json",
                "staged/scenario-catalog.json",
                "terminal-commit.json",
            ]
        ],
    ]
    return _gate_pair_output_capture(
        context.root, [n for n in names if (context.root / n).exists()]
    )


def _gate_completion_complete(
    context: Any, completion: Any, outputs: Any, ids: Any, fd: Any
) -> Any:
    release._release_gate_complete_at(context, fd, 0, outputs, ids, completion=completion)


def test_gate_completion_complete_prefix_has_acyclic_original_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    try:
        _gate_completion_complete(c, e, outputs, ids, fd)
    finally:
        os.close(fd)
    terminal = json.loads((c.directory / "invocation.json").read_bytes())
    raw = (c.directory / "terminal-commit.json").read_bytes()
    assert raw == release.canonical_json(
        {
            "schema_version": "metriplane.gate-terminal-commit.v1",
            "intent_sha256": release.sha256_json(c.intent),
            "terminal_sha256": release.sha256_json(terminal),
        }
    )
    assert all(
        (
            "terminal-commit" not in row["path"]
            for row in terminal["data"]["inputs"]
            + terminal["data"]["outputs"]
            + c.intent["planned_outputs"]
        )
    )
    capture = _gate_completion_captured_all(c)
    result = release._release_gate_pair_output_replay(
        c,
        captured=capture,
        expected_gate_data=json.loads(e.expected_gate_data),
        expected_catalog_record=json.loads(e.expected_catalog_record),
    )
    assert result["terminal"]["status"] == "PASS"
    assert release._validate_terminal(c)["status"] == "PASS"


@pytest.mark.parametrize(
    "fault",
    [
        "terminal-file-fsync",
        "terminal-dir-fsync",
        "post-terminal-capture",
        "worker-drift",
        "installed-drift",
        "extra-journal",
        "extra-stage",
    ],
)
def test_gate_completion_failed_prefix_never_gets_success_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    injected = []
    sync = release.os.fsync
    capture = release._release_gate_journal_capture_at

    def fsync(actual: Any) -> Any:
        terminal = c.directory / "invocation.json"
        if (
            terminal.exists()
            and (not injected)
            and (fault in {"terminal-file-fsync", "terminal-dir-fsync"})
        ):
            info = os.fstat(actual)
            target = terminal.stat() if fault == "terminal-file-fsync" else os.fstat(fd)
            if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                injected.append(fault)
                raise OSError("controlled terminal persistence failure")
        return sync(actual)

    def reading(ctx: Any, directory_fd: Any, identities: Any) -> Any:
        got = capture(ctx, directory_fd, identities)
        if (
            "invocation.json" in identities
            and (not injected)
            and (fault not in {"terminal-file-fsync", "terminal-dir-fsync"})
        ):
            injected.append(fault)
            if fault == "post-terminal-capture":
                raise release.ReleaseControlError("controlled post-terminal barrier failure")
            if fault in {"worker-drift", "installed-drift"}:
                path = (
                    c.directory / "worker-result.json"
                    if fault == "worker-drift"
                    else c.root / "gate-input.json"
                )
                path.chmod(384)
                path.write_bytes(path.read_bytes() + b" ")
            elif fault == "extra-journal":
                (c.directory / "unknown").mkdir()
            elif fault == "extra-stage":
                (c.directory / "staged/unknown").mkdir()
        return got

    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release, "_release_gate_journal_capture_at", reading)
    try:
        with pytest.raises((OSError, release.ReleaseControlError)):
            _gate_completion_complete(c, e, outputs, ids, fd)
    finally:
        os.close(fd)
    assert (
        injected
        and (c.directory / "invocation.json").exists()
        and (not (c.directory / "terminal-commit.json").exists())
    )
    with pytest.raises(release.ReleaseControlError):
        release._validate_terminal(c)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "wrong-intent", "wrong-terminal", "extra", "whitespace", "negative", "other-owner"],
)
def test_gate_completion_completed_reader_rejects_invalid_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    try:
        _gate_completion_complete(c, e, outputs, ids, fd)
    finally:
        os.close(fd)
    path = c.directory / "terminal-commit.json"
    record = json.loads(path.read_bytes())
    terminal = json.loads((c.directory / "invocation.json").read_bytes())
    if mutation == "missing":
        path.unlink()
    elif mutation == "negative":
        terminal["status"] = "BLOCKED"
    elif mutation == "other-owner":
        c = release.ReleaseInvocation(
            c.directory, c.root, {**c.intent, "tool": "validate_release_gate_input.py"}
        )
    else:
        if mutation == "wrong-intent":
            record["intent_sha256"] = "1" * 64
        elif mutation == "wrong-terminal":
            record["terminal_sha256"] = "2" * 64
        elif mutation == "extra":
            record["approved"] = True
        raw = release.canonical_json(record) + (b" " if mutation == "whitespace" else b"")
        path.chmod(384)
        path.write_bytes(raw)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_terminal_commit_replay(
            c, terminal, captured=_gate_completion_captured_all(c)
        )


@pytest.mark.parametrize("mode", ["no-completion", "extra-completion", "premature"])
def test_gate_completion_completion_requires_actual_handoff_before_terminal_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    if mode == "premature":
        (c.directory / "terminal-commit.json").write_bytes(b"premature")
    try:
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_complete_at(
                c,
                fd,
                3 if mode == "extra-completion" else 0,
                outputs,
                ids,
                completion=None if mode == "no-completion" else e,
            )
    finally:
        os.close(fd)
    assert not (c.directory / "invocation.json").exists()


@pytest.mark.parametrize("boundary", ["staged", "installed"])
def test_gate_completion_pending_pair_rejects_premature_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: Any
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(release, "_validate_terminal", release._validate_terminal_entry)
        c, plan, data, catalog, outputs = _gate_staged_pair_fixture(tmp_path, patch)
    monkeypatch.chdir(c.gate_inputs.working_directory)
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    (c.directory / "terminal-commit.json").write_bytes(b"premature")
    with pytest.raises(release.ReleaseControlError):
        if boundary == "staged":
            release._release_gate_staged_pair_replay(
                c,
                input_plan=plan,
                expected_gate_data=data,
                expected_catalog_record=catalog,
                original_outputs=_gate_fixture_carried_stage(c),
            )
        else:
            release._install_release_gate_pair(
                c, outputs, original_stage_capture=_gate_fixture_carried_stage(c)
            )
    assert not (c.root / "gate-input.json").exists()


@pytest.mark.parametrize("fault", ["receipt-fsync", "receipt-replacement", "root-replacement"])
def test_gate_completion_witness_records_only_durable_prefix_and_actual_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    write = release._release_gate_write_json_at
    sync = release.os.fsync
    observed = []
    read_inodes = []
    foreign = []
    read = release.os.read

    def writing(d: Any, name: Any, value: Any) -> Any:
        identity = write(d, name, value)
        if name == "invocation.json" and fault == "root-replacement":
            original = c.root.with_name("detached-original")
            c.root.rename(original)
            shutil.copytree(original, c.root)
            observed.append(original)
        if name == "terminal-commit.json" and fault == "receipt-replacement":
            p = c.directory / name
            raw = p.read_bytes()
            p.rename(p.with_name("original-receipt"))
            p.write_bytes(raw)
            foreign.append((p.stat().st_dev, p.stat().st_ino))
            observed.append(p)
        return identity

    def fsync(d: Any) -> Any:
        p = c.directory / "terminal-commit.json"
        if (
            fault == "receipt-fsync"
            and p.exists()
            and (not observed)
            and ((os.fstat(d).st_dev, os.fstat(d).st_ino) == (p.stat().st_dev, p.stat().st_ino))
        ):
            observed.append(p)
            raise OSError("controlled witness fsync failure after committed prefix")
        return sync(d)

    def reading(d: Any, n: Any) -> Any:
        identity = (os.fstat(d).st_dev, os.fstat(d).st_ino)
        if identity in foreign:
            read_inodes.append(identity)
        return read(d, n)

    monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release.os, "read", reading)
    try:
        with pytest.raises((OSError, release.ReleaseControlError)):
            _gate_completion_complete(c, e, outputs, ids, fd)
    finally:
        os.close(fd)
    assert observed and (not read_inodes)
    if fault == "root-replacement":
        assert not (c.directory / "terminal-commit.json").exists()
        assert not (observed[0] / c.directory.relative_to(c.root) / "terminal-commit.json").exists()
    elif fault == "receipt-fsync":
        assert release._validate_terminal(c)["status"] == "PASS"
        captured = _gate_completion_captured_all(c)
        release._release_gate_terminal_commit_replay(
            c, json.loads((c.directory / "invocation.json").read_bytes()), captured=captured
        )


@pytest.mark.parametrize("prior", ["negative", "interrupted", "uncommitted-pass"])
def test_gate_completion_prior_history_cannot_acquire_or_backfill_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    try:
        if prior == "uncommitted-pass":
            _gate_completion_complete(c, e, outputs, ids, fd)
            (c.directory / "terminal-commit.json").unlink()
        else:
            if prior == "negative":
                release._retain_partial_files(c)
                release._complete_invocation(c, 3, [])
            (c.directory / "terminal-commit.json").write_bytes(b"not a success witness")
    finally:
        os.close(fd)
    stage = c.directory.parent
    stagefd = release._release_gate_open_pinned_directory(stage, c.intent_capture.rows[0][4][:-1])
    try:
        inventory = release._release_gate_stage_inventory(
            stage, stagefd, c.intent_capture.rows[0][4][:-1]
        )
    finally:
        os.close(stagefd)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_prior_journals(c.gate_inputs, stage, inventory)
    assert not (stage / "002").exists()


@pytest.mark.parametrize("failure", [None, 0, 1, 2])
def test_gate_completion_cleanup_attempts_every_owned_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    fds = [os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY) for _ in range(3)]
    close = release.os.close
    calls = []

    def closing(fd: Any) -> Any:
        calls.append(fd)
        close(fd)
        if failure is not None and fd == fds[failure]:
            raise OSError("controlled close-reported failure")

    monkeypatch.setattr(release.os, "close", closing)
    if failure is None:
        release._release_gate_completion_close(fds)
    else:
        with pytest.raises(release.ReleaseControlError, match="descriptor cleanup"):
            release._release_gate_completion_close(fds)
    assert calls == list(reversed(fds))
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("failure", ["root-open", "file-close"])
def test_gate_completion_precommit_cleanup_failure_closes_remaining_owned_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Any
) -> None:
    c, e, outputs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    opening = release._release_gate_open_pinned_directory
    close = release.os.close
    sync = release.os.fsync
    owned = set()
    stage_seen = []
    armed = []
    injected = []

    def open_dir(path: Any, pins: Any) -> Any:
        if failure == "root-open" and path == c.root and stage_seen:
            injected.append("root-open")
            raise OSError("controlled root open failure")
        actual = opening(path, pins)
        owned.add(actual)
        if path == c.directory / "staged":
            stage_seen.append(actual)
        return actual

    def fsync(actual: Any) -> Any:
        info = os.fstat(actual)
        target = (c.directory / "worker-result.json").stat()
        if failure == "file-close" and (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
            armed.append(actual)
        return sync(actual)

    def closing(actual: Any) -> Any:
        close(actual)
        owned.discard(actual)
        if failure == "file-close" and actual in armed and (not injected):
            injected.append("file-close")
            raise OSError("controlled synced file close failure")

    monkeypatch.setattr(release, "_release_gate_open_pinned_directory", open_dir)
    monkeypatch.setattr(release.os, "fsync", fsync)
    monkeypatch.setattr(release.os, "close", closing)
    try:
        with pytest.raises((OSError, release.ReleaseControlError)):
            _gate_completion_complete(c, e, outputs, ids, fd)
    finally:
        os.close(fd)
    assert injected and (not owned) and (not (c.directory / "terminal-commit.json").exists())


# These captures belong to explicitly mechanical fixture construction. Actual
# worker/install production captures must originate at their real writer boundary.
_GATE_FIXTURE_STAGE_CAPTURES: dict[str, Any] = {}


def _gate_fixture_remember_stage(context: Any, monkeypatch: Any) -> Any:
    rows = [
        ((context.directory / "staged" / name).relative_to(context.root).as_posix(), kind)
        for name, kind in release._RELEASE_GATE_OUTPUT_PLAN
    ]
    capture = release._ReleaseCapturedFiles.capture(
        context.root,
        rows,
        forbidden=(),
        allowed_kinds=frozenset(kind for _, kind in release._RELEASE_GATE_OUTPUT_PLAN),
        expected_root_directories=context.gate_inputs.captured.root_directories,
        expected_known_directories=context.intent_capture.rows[0][4],
    )
    if monkeypatch is None:
        _GATE_FIXTURE_STAGE_CAPTURES[str(context.directory)] = capture
    else:
        monkeypatch.setitem(_GATE_FIXTURE_STAGE_CAPTURES, str(context.directory), capture)
    return capture


def _gate_fixture_carried_stage(context: Any) -> Any:
    # A relocated generic readback has no live producer capture. It deliberately
    # follows only the standalone mechanical reader path, not a source handoff.
    if not isinstance(context, release._ReleaseGateInvocation):
        return None
    return _GATE_FIXTURE_STAGE_CAPTURES.get(str(context.directory))


def _gate_install_handoff_prepared(tmp_path, monkeypatch):
    c, plan, data, catalog, refs = _gate_staged_pair_fixture(tmp_path, monkeypatch)
    return (c, plan, data, catalog, refs, _gate_fixture_carried_stage(c))


@pytest.mark.parametrize("dispatcher", [False, True])
def test_gate_install_handoff_original_stage_survives_replay_copy_and_installed_handoff(
    tmp_path, monkeypatch, dispatcher
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    staged = release._release_gate_staged_pair_replay(
        c,
        input_plan=plan,
        expected_gate_data=data,
        expected_catalog_record=catalog,
        original_outputs=held,
    )
    assert staged["captured"] is held
    if dispatcher:
        installed = release._install_release_outputs(c, refs, gate_stage_capture=held)
    else:
        installed = release._install_release_gate_pair(c, refs, original_stage_capture=held)
    assert isinstance(installed, release._ReleaseCapturedFiles)
    assert {x[0] for x in installed.rows} == {"gate-input.json", "scenario-catalog.json"}
    for name, kind, raw, identity, ancestors in installed.rows:
        assert (
            kind == "prerequisite-original" and raw == (c.directory / "staged" / name).read_bytes()
        )
        assert identity == release._release_gate_file_identity((c.root / name).stat())
        staged_info = (c.directory / "staged" / name).stat()
        assert identity[:2] != (staged_info.st_dev, staged_info.st_ino)
        assert identity[3] == 1
    installed.revalidate()
    held.revalidate()
    assert not (c.directory / "invocation.json").exists()


@pytest.mark.parametrize("boundary", ["capture", "semantic", "install", "dispatch"])
def test_gate_install_handoff_producer_requires_original_stage_handoff(
    tmp_path, monkeypatch, boundary
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    with pytest.raises(release.ReleaseControlError, match="held"):
        if boundary == "capture":
            release._release_gate_output_capture(c, c.directory / "staged", input_plan=plan)
        elif boundary == "semantic":
            release._release_gate_staged_pair_replay(
                c, input_plan=plan, expected_gate_data=data, expected_catalog_record=catalog
            )
        elif boundary == "install":
            release._install_release_gate_pair(c, refs)
        else:
            release._install_release_outputs(c, refs)
    assert not (c.root / "gate-input.json").exists()


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "wrong-type", "wrong-root", "wrong-ancestors", "wrong-output-owner"],
)
def test_gate_install_handoff_exact_handoff_census_rejects_before_any_output_byte(
    tmp_path, monkeypatch, mutation
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    root = c.directory / "staged"
    rows = list(held.rows)
    if mutation == "missing":
        held = dataclasses.replace(held, rows=tuple(rows[:1]))
    elif mutation == "duplicate":
        held = dataclasses.replace(held, rows=(rows[0], rows[0]))
    elif mutation == "wrong-type":
        held = dataclasses.replace(
            held, rows=((rows[0][0], "prerequisite-original", *rows[0][2:]), rows[1])
        )
    elif mutation == "wrong-root":
        held = dataclasses.replace(held, root=tmp_path)
    elif mutation == "wrong-ancestors":
        held = dataclasses.replace(held, rows=tuple(((*row[:4], row[4][1:]) for row in rows)))
    else:
        root = c.directory
    output_inodes = {row[3][:2] for row in rows}
    reads = []
    read = release.os.read

    def reading(fd, n):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) in output_inodes:
            reads.append(fd)
        return read(fd, n)

    monkeypatch.setattr(release.os, "read", reading)
    with pytest.raises(release.ReleaseControlError):
        release._release_gate_pair_capture_handoff(c, root, held)
    assert not reads


@pytest.mark.parametrize("replacement", ["file", "staged-directory", "journal-directory", "root"])
def test_gate_install_handoff_replaced_stage_is_rejected_before_substituted_bytes(
    tmp_path, monkeypatch, replacement
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    release._release_gate_staged_pair_replay(
        c,
        input_plan=plan,
        expected_gate_data=data,
        expected_catalog_record=catalog,
        original_outputs=held,
    )
    target = {
        "file": c.directory / "staged/gate-input.json",
        "staged-directory": c.directory / "staged",
        "journal-directory": c.directory,
        "root": c.root,
    }[replacement]
    saved = target.with_name(target.name + "-original")
    target.rename(saved)
    if replacement == "file":
        target.write_bytes(saved.read_bytes())
    else:
        shutil.copytree(saved, target)
    foreign = set()
    for name, _ in release._RELEASE_GATE_OUTPUT_PLAN:
        st = (c.directory / "staged" / name).stat()
        foreign.add((st.st_dev, st.st_ino))
    reads = []
    read = release.os.read

    def reading(fd, n):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) in foreign:
            reads.append(fd)
        return read(fd, n)

    monkeypatch.setattr(release.os, "read", reading)
    with pytest.raises(release.ReleaseControlError):
        release._install_release_gate_pair(c, refs, original_stage_capture=held)
    assert not reads and (not (c.root / "gate-input.json").exists())


def test_gate_install_handoff_returned_installed_capture_rejects_identical_byte_replacement(
    tmp_path, monkeypatch
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    installed = release._install_release_gate_pair(c, refs, original_stage_capture=held)
    p = c.root / "gate-input.json"
    raw = p.read_bytes()
    p.rename(p.with_name("original-gate"))
    p.write_bytes(raw)
    with pytest.raises(release.ReleaseControlError):
        installed.revalidate()


def test_gate_install_handoff_gate_handoff_cannot_be_passed_to_another_installation_owner(
    tmp_path, monkeypatch
):
    c, plan, data, catalog, refs, held = _gate_install_handoff_prepared(tmp_path, monkeypatch)
    other = dataclasses.replace(c, intent={**c.intent, "tool": "validate_release_gate_input.py"})
    with pytest.raises(release.ReleaseControlError, match="another installation owner"):
        release._install_release_outputs(other, refs, gate_stage_capture=held)
    assert not (c.root / "gate-input.json").exists()


def _seed_staging_put(path: Any, raw: Any) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _seed_staging_preflight_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, relative: Any = False
) -> Any:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    root = tmp_path / "run"
    root.mkdir()
    registry, files, controls = _fixture_native_registry_bundle()
    registry_raw = json.dumps(registry, indent=2).encode() + b"\n"
    ordinary = {
        "inputs/stores.json": registry_raw,
        **{"inputs/" + n: raw for n, raw in files.items()},
    }
    for n, raw in ordinary.items():
        _seed_staging_put(root / n, raw)
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [(n, "prerequisite-original") for n in ordinary],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    tool = "validate_release_evidence_stores.py"
    directory = root / "invocations/validate-release-evidence-stores/001"
    argv = [
        tool,
        "--stores",
        str(root / "inputs/stores.json"),
        "--mode",
        "preflight",
        "--scope",
        "fixture-run",
        "--require-backends",
        "all",
        "--out",
        str(root / "preflight.json"),
        "--invocation-dir",
        str(directory),
    ]
    cwd = Path.cwd()
    if relative:
        cwd = root
        monkeypatch.chdir(cwd)
        argv = [v.removeprefix(str(root) + "/") for v in argv]
    arguments = release._release_original_arguments(tool, argv)
    subject, ops = release._release_fixture_preflight_expectations(
        arguments,
        registry_raw=registry_raw,
        expected_registry_digest=release.sha256_bytes(registry_raw),
        backend_controls=controls,
    )
    responses = {}
    for index, op in enumerate(ops):
        req = op["request"]
        value = {
            "backend_id": req["backend_id"],
            "binding_digest": req["binding_digest"],
            "namespace": req["namespace"],
            "administration_identity": req["administration_identity"],
            "resource_id": req["resource_id"],
            "trace": release._release_fixture_preflight_trace(req),
        }
        responses[f"response-{index}"] = json.dumps(value, indent=2).encode() + b"\n"
    name = "inputs/fixture-native/validate-release-evidence-stores/001/seed.json"
    seed = {
        "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
        "synthetic": True,
        "tool": tool,
        "command_digest": release.sha256_json(
            {"tool": tool, "argv": argv, "working_directory": str(cwd)}
        ),
        "members": [
            {
                "member_id": n,
                "path": "raw/" + n + ".bin",
                "schema_id": "application/octet-stream",
                "bytes": len(raw),
                "sha256": release.sha256_bytes(raw),
            }
            for n, raw in responses.items()
        ],
        "data": {"response_member_ids": list(responses)},
    }
    for n, raw in responses.items():
        _seed_staging_put(root / Path(name).parent / "raw" / f"{n}.bin", raw)
    _seed_staging_put(root / name, json.dumps(seed, indent=2).encode() + b"\n")
    kwargs = {
        "working_directory": cwd,
        "held_inputs": captured,
        "expected_inputs": {
            "stores": [
                {
                    "path": "inputs/stores.json",
                    "schema_id": "metriplane.release-evidence-stores.v1",
                    "sha256": release.sha256_bytes(registry_raw),
                }
            ]
        },
        "input_types": {
            n: "metriplane.release-evidence-stores.v1"
            if n == "inputs/stores.json"
            else "application/octet-stream"
            for n in ordinary
        },
        "selection": {"registry_digest": release.sha256_bytes(registry_raw)},
        "live": False,
    }
    return (root, argv, seed, name, kwargs)


@pytest.mark.parametrize("relative", [False, True])
def test_seed_staging_full_preflight_seed_before_any_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_preflight_seed(
        tmp_path, monkeypatch, relative=relative
    )
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert len(plan.operations) == 7 and len(plan.output_plan) == 22
    assert len(plan.input_plan) == 51
    assert (
        name,
        release._RELEASE_FIXTURE_SEED_SCHEMA,
        release.sha256_bytes((root / name).read_bytes()),
    ) in plan.input_plan
    assert not (plan.directory / "intent.json").exists()
    assert all((not (root / n).exists() for n, _ in plan.output_plan))
    assert not hasattr(plan, "approved") and (not hasattr(plan, "native_authority"))
    assert all(("producer" not in json.loads(raw) for raw in plan.operations))


def test_seed_staging_public_preflight_command_completes_connected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, _, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / argv[0]), *argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    directory = root / "invocations/validate-release-evidence-stores/001"
    context = release._validate_intent(directory)
    terminal = release._validate_terminal(context)
    assert terminal["status"] == "PASS"
    assert json.loads((directory / "worker.pid").read_bytes())["pid"] != os.getpid()
    witness = json.loads((directory / "terminal-commit.json").read_bytes())
    assert witness == {
        "schema_version": "metriplane.gate-terminal-commit.v1",
        "intent_sha256": release.sha256_json(context.intent),
        "terminal_sha256": release.sha256_json(terminal),
    }
    assert [
        {key: row[key] for key in ("path", "schema_id")} for row in terminal["data"]["outputs"]
    ] == context.intent["planned_outputs"]
    assert (root / "preflight.json").exists()
    assert len(list((root / "native-fixture/validate-release-evidence-stores/001").rglob("*"))) > 7


def test_seed_staging_public_preflight_worker_death_is_supervised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, _, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)

    def kill_worker(_: Any) -> NoReturn:
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL returned")

    monkeypatch.setattr(release, "_release_fixture_seed_emulate", kill_worker)
    assert release.run_release_command(argv[0], argv[1:]) == 137
    directory = root / "invocations/validate-release-evidence-stores/001"
    terminal = release._validate_terminal(release._validate_intent(directory))
    assert terminal["status"] == "CANCELLED"
    assert terminal["data"]["outputs"] == []
    assert (directory / "partial-files.json").exists()
    assert not (directory / "terminal-commit.json").exists()


def test_seed_staging_public_preflight_pass_requires_durable_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, _, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    assert release.run_release_command(argv[0], argv[1:]) == 0
    record_path = root / "preflight.json"
    record = json.loads(record_path.read_bytes())
    (root / "invocations/validate-release-evidence-stores/001/terminal-commit.json").unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(
            record, record_path, producer="validate_release_evidence_stores.py"
        )


@pytest.mark.parametrize("case", ["failure", "interruption", "replacement"])
def test_seed_staging_public_preflight_command_retains_nonpassing_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    root, argv, _, _, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    if case == "failure":
        monkeypatch.setattr(
            release,
            "_release_fixture_seed_emulate",
            lambda _: (_ for _ in ()).throw(release.ReleaseControlError("worker failure")),
        )
    elif case == "interruption":
        monkeypatch.setattr(
            release,
            "_release_fixture_seed_emulate",
            lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    else:
        collect = release._release_fixture_collect_staged

        def replace(emulation: Any, **kwargs: Any) -> Any:
            staged = kwargs["original_staged_directory"].path
            saved = staged.with_name("staged-original")
            staged.rename(saved)
            shutil.copytree(saved, staged)
            return collect(emulation, **kwargs)

        monkeypatch.setattr(release, "_release_fixture_collect_staged", replace)
    expected = 130 if case == "interruption" else 3
    assert release.run_release_command(argv[0], argv[1:]) == expected
    directory = root / "invocations/validate-release-evidence-stores/001"
    terminal = release._validate_terminal(release._validate_intent(directory))
    assert terminal["status"] == ("CANCELLED" if case == "interruption" else "BLOCKED")
    assert terminal["data"]["outputs"] == []
    assert not (root / "preflight.json").exists()
    assert (directory / "partial-files.json").exists()


def test_seed_staging_public_preflight_command_recovers_in_next_original_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, name, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    emulate = release._release_fixture_seed_emulate
    monkeypatch.setattr(
        release,
        "_release_fixture_seed_emulate",
        lambda _: (_ for _ in ()).throw(release.ReleaseControlError("first operation failed")),
    )
    assert release.run_release_command(argv[0], argv[1:]) == 3
    monkeypatch.setattr(release, "_release_fixture_seed_emulate", emulate)
    second_argv = [value.replace("/001", "/002") for value in argv]
    source = root / Path(name).parent
    destination = source.parent / "002"
    shutil.copytree(source, destination)
    seed_path = destination / "seed.json"
    seed = json.loads(seed_path.read_bytes())
    seed["command_digest"] = release.sha256_json(
        {"tool": argv[0], "argv": second_argv, "working_directory": str(Path.cwd())}
    )
    seed_path.write_bytes(json.dumps(seed, indent=2).encode() + b"\n")
    assert release.run_release_command(second_argv[0], second_argv[1:]) == 0
    first = release._validate_intent(root / "invocations/validate-release-evidence-stores/001")
    second = release._validate_intent(root / "invocations/validate-release-evidence-stores/002")
    terminal = release._validate_terminal(second)
    assert terminal["status"] == "PASS"
    assert second.intent["predecessor"]["intent_digest"] == release.sha256_bytes(
        (first.directory / "intent.json").read_bytes()
    )
    assert second.intent["predecessor"]["terminal_digest"] == release.sha256_bytes(
        (first.directory / "invocation.json").read_bytes()
    )


def test_seed_staging_public_preflight_command_is_consumed_by_journal_and_graph_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, _, _ = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    assert release.run_release_command(argv[0], argv[1:]) == 0
    record_path = root / "preflight.json"
    record = json.loads(record_path.read_bytes())
    release.validate_release_producer_journal(
        record, record_path, producer="validate_release_evidence_stores.py"
    )
    names = sorted(
        path.relative_to(tmp_path).as_posix() for path in root.rglob("*") if path.is_file()
    )
    originals = [
        {
            "path": name,
            "bytes": (tmp_path / name).stat().st_size,
            "sha256": release.sha256_bytes((tmp_path / name).read_bytes()),
        }
        for name in names
    ]
    lookup = {row["path"]: row for row in originals}
    prefix = root.relative_to(tmp_path).as_posix()
    primary = prefix + "/preflight.json"
    journal = prefix + "/invocations/validate-release-evidence-stores/001/"
    bundle = {
        "schema_version": "metriplane.release-prerequisite-proofs.v1",
        "release_context_digest": "a" * 64,
        "captured_original_files": originals,
        "proofs": [
            {
                "producer": "validate_release_evidence_stores.py",
                "stage": "validate-release-evidence-stores",
                "record_type": "release-evidence-store-preflight",
                "record_kind": None,
                "record": lookup[primary],
                "record_digest": release.sha256_json(record),
                "original_run_root": prefix,
                "producer_intent": lookup[journal + "intent.json"],
                "producer_terminal": lookup[journal + "invocation.json"],
                "companion_validations": [],
            }
        ],
    }
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(release.canonical_json(bundle))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("bundle.json", "prerequisite-proofs"),
            *((name, "prerequisite-original") for name in names),
        ],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-proofs", "prerequisite-original"}),
    )
    registry_raw = (root / "inputs/stores.json").read_bytes()
    result = release._release_prerequisite_graph_replay(
        bundle_path,
        captured=captured,
        expected_context_digest="a" * 64,
        before=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        live=False,
        selections={
            primary: {
                "inputs": {
                    "stores": [
                        {
                            "path": "inputs/stores.json",
                            "schema_id": "metriplane.release-evidence-stores.v1",
                            "sha256": release.sha256_bytes(registry_raw),
                        }
                    ]
                },
                "auxiliary": {},
                "selectors": {"registry_digest": release.sha256_bytes(registry_raw)},
                "proof_refs": [row["native_proof_files"][0] for row in record["data"]["backends"]],
                "dependencies": {},
            }
        },
    )
    assert len(result.nodes) == 1
    assert result.nodes[0].original_record == release.canonical_json(record)


@pytest.mark.parametrize(
    "case",
    [
        "live",
        "truthy-live",
        "mode",
        "tool",
        "command",
        "members-extra",
        "member-missing",
        "member-alias",
        "member-type",
        "member-length",
        "member-hash",
        "member-path",
        "physical-extra",
        "raw-extra",
        "raw-symlink",
        "raw-file-symlink",
        "seed-symlink",
        "response-extra",
        "response-backend",
        "extra-response",
        "missing-response",
        "unknown-field",
        "wrong-sequence",
        "sequence-alias",
        "foreign-stage",
    ],
)
def test_seed_staging_seed_closed_failure_before_any_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    if case == "live":
        kw["live"] = True
    elif case == "truthy-live":
        kw["live"] = 0
    elif case == "mode":
        monkeypatch.delenv("METRIPLANE_RELEASE_FIXTURE_MODE")
    elif case == "tool":
        seed["tool"] = "export_release_attempt_index.py"
    elif case == "command":
        seed["command_digest"] = "a" * 64
    elif case == "members-extra":
        seed["members"].append(copy.deepcopy(seed["members"][0]))
    elif case == "member-missing":
        seed["members"].pop()
    elif case == "member-alias":
        seed["members"][1]["path"] = seed["members"][0]["path"]
    elif case == "member-type":
        seed["members"][0]["schema_id"] = "other"
    elif case == "member-length":
        seed["members"][0]["bytes"] += 1
    elif case == "member-hash":
        seed["members"][0]["sha256"] = "a" * 64
    elif case == "member-path":
        seed["members"][0]["path"] = "raw/../other.bin"
    elif case == "physical-extra":
        _seed_staging_put(root / Path(name).parent / "extra", b"x")
    elif case == "raw-extra":
        _seed_staging_put(root / Path(name).parent / "raw/extra.bin", b"x")
    elif case == "raw-symlink":
        raw = root / Path(name).parent / "raw"
        raw.rename(raw.with_name("saved"))
        raw.symlink_to(raw.with_name("saved"), target_is_directory=True)
    elif case == "raw-file-symlink":
        raw = root / Path(name).parent / "raw/response-0.bin"
        raw.rename(raw.with_name("saved"))
        raw.symlink_to(raw.with_name("saved"))
    elif case == "response-extra" or case == "response-backend":
        raw = root / Path(name).parent / "raw/response-0.bin"
        value = json.loads(raw.read_bytes())
        value["extra" if case == "response-extra" else "backend_id"] = "other"
        data = json.dumps(value).encode()
        raw.write_bytes(data)
        seed["members"][0].update(bytes=len(data), sha256=release.sha256_bytes(data))
    elif case == "extra-response":
        seed["data"]["response_member_ids"].append("response-0")
    elif case == "missing-response":
        seed["data"]["response_member_ids"].pop()
    elif case == "unknown-field":
        seed["arbitrary"] = True
    elif case in {"wrong-sequence", "sequence-alias", "foreign-stage"}:
        argv[-1] = (
            argv[-1].replace("/001", "/002" if case == "wrong-sequence" else "/0001")
            if case != "foreign-stage"
            else argv[-1].replace("validate-release-evidence-stores", "other-stage")
        )
    (root / name).write_bytes(json.dumps(seed).encode())
    if case == "seed-symlink":
        seedpath = root / name
        seedpath.rename(seedpath.with_name("saved"))
        seedpath.symlink_to(seedpath.with_name("saved"))
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert not (root / "invocations").exists()


@pytest.mark.parametrize("member", ["seed", "raw", "root", "ancestor"])
def test_seed_staging_known_custody_replacement_zero_foreign_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    kw["held_inputs"] = plan.captured
    kw["input_types"] = {n: s for n, s, _ in plan.input_plan}
    path = root / name if member == "seed" else root / Path(name).parent / "raw/response-0.bin"
    original_read = os.read
    seen = []
    if member in {"seed", "raw"}:
        raw = path.read_bytes()
        path.rename(path.with_name("saved"))
        path.write_bytes(raw)
        foreign = path.stat().st_ino
    else:
        path = root if member == "root" else root / "inputs"
        saved = path.with_name("saved")
        path.rename(saved)
        import shutil

        shutil.copytree(saved, path)
        foreign = (path if member == "root" else root).stat().st_ino

    def read(fd: Any, n: Any) -> Any:
        if os.fstat(fd).st_ino == foreign:
            seen.append(True)
        return original_read(fd, n)

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert not seen


def _seed_staging_bind_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root, argv, seed, name, kw = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    original = release.begin_release_invocation(
        argv[0],
        argv[1:],
        plan.directory,
        input_paths=[(root / n, s) for n, s, _ in plan.input_plan],
        planned_outputs=[(root / n, s) for n, s in plan.output_plan],
    )
    intent_name = (original.directory / "intent.json").relative_to(root).as_posix()
    intent = release._ReleaseCapturedFiles.capture(
        root,
        [(intent_name, "prerequisite-original")],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
        expected_root_directories=plan.captured.root_directories,
    )
    bound = release._release_fixture_seed_bind(original, plan=plan, original_intent_capture=intent)
    return (root, kw, bound)


def _seed_staging_held_parents(destination: Any, names: Any, pins: Any) -> Any:
    parents = sorted(
        {p for n in names for p in Path(n).parents if p != Path(".")},
        key=lambda p: (len(p.parts), str(p)),
    )
    for p in parents:
        (destination / p).mkdir(exist_ok=True)
    held = [release._release_fixture_directory(destination / p, expected=pins) for p in parents]
    return held


def _seed_staging_primary_preflight(emulation: Any) -> Any:
    bound = emulation.bound
    original = bound.original
    plan = bound.plan
    ops = release._release_fixture_native_plan(
        tool=plan.tool,
        sequence=1,
        subject=json.loads(plan.subject),
        operations=[json.loads(x) for x in plan.operations],
    )
    rows = []
    for item, ref in zip(ops, emulation.proof_refs, strict=True):
        req = item["request"]["arguments"]
        rows.append(
            {
                "backend_id": req["backend_id"],
                "capabilities_tested": req["capabilities"],
                "create_digest": release.sha256_json(req["challenge"]),
                "namespace": req["namespace"],
                "operation_id": release.sha256_json(item["request"]),
                "read_back_digest": release.sha256_json(req["challenge"]),
                "result": "PASS",
                "backend_binding_digest": req["binding_digest"],
                "native_proof_files": [json.loads(ref)],
            }
        )
    raw = plan.captured.read("inputs/stores.json", kind="prerequisite-original")
    return release.make_record(
        "release-evidence-store-preflight",
        {
            "backends": rows,
            "independence_verified": True,
            "invocation_root_locator": "invocations",
            "mode": "isolated_preflight",
            "original_registry": {
                "path": "inputs/stores.json",
                "bytes": len(raw),
                "sha256": release.sha256_bytes(raw),
            },
            "producer_intent_digest": release.sha256_json(original.intent),
            "production_heads_mutated": False,
            "registry_digest": release.sha256_bytes(raw),
            "scope": "fixture-run",
        },
        invocation_id=original.intent["invocation_id"],
        sequence=1,
        synthetic=True,
    )


def _seed_staging_stage_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    root, kw, bound = _seed_staging_bind_fixture(tmp_path, monkeypatch)
    emulation = release._release_fixture_seed_emulate(bound)
    directory = bound.original.directory / "staged"
    directory.mkdir()
    pins = tuple(
        dict.fromkeys(
            (
                *bound.plan.captured.root_directories,
                *(p for row in bound.intent_capture.rows for p in row[4]),
            )
        )
    )
    staged = release._release_fixture_directory(directory, expected=pins)
    parents = _seed_staging_held_parents(
        directory, [n for n, _, _ in emulation.sidecars], staged.identities
    )
    native_capture = release._release_fixture_stage_sidecars(
        emulation, original_staged_directory=staged, original_parent_directories=parents
    )
    primary = release.canonical_json(_seed_staging_primary_preflight(emulation))
    primary_capture = release._release_fixture_write_set(
        staged,
        [("preflight.json", "metriplane.release-evidence-store-preflight.v1", primary)],
        before_effect=bound.revalidate,
        original_parent_directories=[],
    )
    all_stage = release._ReleaseCapturedFiles(
        directory, staged.identities, tuple(sorted((*native_capture.rows, *primary_capture.rows)))
    )
    return (root, kw, emulation, staged, parents, all_stage)


def _seed_staging_close_all(*groups: Any) -> Any:
    for group in groups:
        for obj in reversed(group):
            obj.close()


def test_seed_staging_exact_native_emulation_no_output_effects_and_original_seed_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, kw, bound = _seed_staging_bind_fixture(tmp_path, monkeypatch)
    e = release._release_fixture_seed_emulate(bound)
    assert len(e.sidecars) == 21 and len(e.proof_refs) == 7
    assert all((not (root / n).exists() for n, _, _ in e.sidecars))
    for ref in e.proof_refs:
        name = json.loads(ref)["path"]
        receipt = json.loads(next((raw for n, _, raw in e.sidecars if n == name)))
        assert receipt["producer"]["intent_digest"] == release.sha256_json(bound.original.intent)
        assert receipt["signature"]["provider"] == "test-fixture"
        assert receipt["signature"]["algorithm"] == "test-sha256-v1"
        assert release._release_fixture_native_timestamp(
            receipt["started_at"]
        ) >= release._release_fixture_native_timestamp(bound.original.intent["started_at"])
    assert not (bound.original.directory / "invocation.json").exists()


@pytest.mark.parametrize(
    "case",
    [
        "seed-omitted",
        "input-type",
        "input-R",
        "extra-input",
        "output-omitted",
        "extra-output",
        "argv",
        "mode",
        "intent-inode",
    ],
)
def test_seed_staging_binding_rejects_original_plan_or_created_intent_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    root, kw, bound = _seed_staging_bind_fixture(tmp_path, monkeypatch)
    original = bound.original
    if case == "intent-inode":
        p = original.directory / "intent.json"
        raw = p.read_bytes()
        p.rename(p.with_name("saved"))
        p.write_bytes(raw)
    else:
        intent = copy.deepcopy(original.intent)
        if case == "seed-omitted":
            intent["inputs"] = [x for x in intent["inputs"] if not x["path"].endswith("seed.json")]
        if case == "input-type":
            intent["inputs"][0]["schema_id"] = "other"
        if case == "input-R":
            intent["inputs"][0]["sha256"] = "a" * 64
        if case == "extra-input":
            intent["inputs"].append(intent["inputs"][0])
        if case == "output-omitted":
            intent["planned_outputs"].pop()
        if case == "extra-output":
            intent["planned_outputs"].append(
                {"path": "unplanned", "schema_id": "application/octet-stream"}
            )
        if case == "argv":
            intent["argv"][4] = "another"
        if case == "mode":
            intent["environment"]["fixture_mode"] = "0"
        original = release.ReleaseInvocation(original.directory, original.root, intent)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_seed_bind(
            original, plan=bound.plan, original_intent_capture=bound.intent_capture
        )


def test_seed_staging_complete_stage_and_exclusive_copy_with_exact_created_file_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, kw, e, stage, parents, captured = _seed_staging_stage_fixture(tmp_path, monkeypatch)
    run = None
    canonical = []
    try:
        collected = release._release_fixture_collect_staged(
            e, original_staged_directory=stage, original_stage_files=captured
        )
        run = release._release_fixture_directory(
            root, expected=e.bound.plan.captured.root_directories
        )
        canonical = _seed_staging_held_parents(
            root, [n for n, _ in e.bound.plan.output_plan], run.identities
        )
        installed = release._release_fixture_install_sidecar_set(
            collected, original_run_directory=run, original_parent_directories=canonical
        )
        assert len(installed.rows) == 22
        for name, schema, raw, identity, _ in installed.rows:
            assert raw == captured.read(name, kind=schema)
            assert identity[1] != next((row[3][1] for row in captured.rows if row[0] == name))
            assert (root / name).stat().st_mode & 146 == 0
        assert not (e.bound.original.directory / "invocation.json").exists()
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_install_sidecar_set(
                collected, original_run_directory=run, original_parent_directories=canonical
            )
    finally:
        _seed_staging_close_all(parents, canonical, [stage], [] if run is None else [run])


@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "missing",
        "symlink",
        "same-byte-replacement",
        "wrong-bytes",
        "wrong-kind",
        "missing-custody",
        "nonpass-primary",
    ],
)
def test_seed_staging_full_staged_collector_rejects_namespace_and_original_file_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    root, kw, e, stage, parents, captured = _seed_staging_stage_fixture(tmp_path, monkeypatch)
    try:
        target = stage.path / e.sidecars[0][0]
        if case == "extra":
            _seed_staging_put(stage.path / "unexpected.bin", b"extra")
        elif case == "missing":
            target.unlink()
        elif case == "symlink":
            target.rename(target.with_name("saved"))
            target.symlink_to(target.with_name("saved"))
        elif case == "same-byte-replacement":
            raw = target.read_bytes()
            target.rename(target.with_name("saved"))
            target.write_bytes(raw)
        elif case == "wrong-bytes":
            target.chmod(384)
            target.write_bytes(b"changed")
        elif case == "wrong-kind":
            captured = release._ReleaseCapturedFiles(
                captured.root,
                captured.root_directories,
                tuple(
                    (
                        (n, "other", *row[2:]) if n == e.sidecars[0][0] else row
                        for row in captured.rows
                        for n in [row[0]]
                    )
                ),
            )
        elif case == "missing-custody":
            captured = release._ReleaseCapturedFiles(
                captured.root, captured.root_directories, captured.rows[1:]
            )
        elif case == "nonpass-primary":
            p = stage.path / "preflight.json"
            p.chmod(384)
            rec = _seed_staging_primary_preflight(e)
            rec["status"] = "FAIL"
            rec["payload_digest"] = release.sha256_json(rec["data"])
            p.write_bytes(release.canonical_json(rec))
            fresh = release._ReleaseCapturedFiles.capture(
                stage.path,
                [("preflight.json", "prerequisite-original")],
                forbidden=(),
                allowed_kinds=frozenset({"prerequisite-original"}),
                expected_root_directories=captured.root_directories,
            )
            freshrow = fresh.rows[0]
            freshrow = (
                freshrow[0],
                "metriplane.release-evidence-store-preflight.v1",
                *freshrow[2:],
            )
            captured = release._ReleaseCapturedFiles(
                captured.root,
                captured.root_directories,
                tuple((row for row in captured.rows if row[0] != "preflight.json")) + (freshrow,),
            )
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_collect_staged(
                e, original_staged_directory=stage, original_stage_files=captured
            )
    finally:
        _seed_staging_close_all(parents, [stage])


def _seed_staging_generic_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: Any,
    ordinary: Any,
    flags: Any,
    data: Any,
    responses: Any,
    types: Any,
    selection: Any,
) -> Any:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    root = tmp_path / "run"
    root.mkdir(parents=True)
    for name, raw in ordinary.items():
        _seed_staging_put(root / name, raw)
    cwd = Path.cwd()
    directory = root / "invocations" / release._invocation_stage(tool) / "001"
    argv = [tool]
    expected = {}
    for flag, values in flags.items():
        for value in values if isinstance(values, list) else [values]:
            argv.append("--" + flag)
            if value is True:
                continue
            argv.append(str(root / value) if value in ordinary else str(value))
            if value in ordinary:
                expected.setdefault(flag, []).append(
                    {
                        "path": value,
                        "schema_id": types[value],
                        "sha256": release.sha256_bytes(ordinary[value]),
                    }
                )
    argv += ["--out", str(root / "primary.json"), "--invocation-dir", str(directory)]
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [(n, "prerequisite-original") for n in ordinary],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    name = f"inputs/fixture-native/{release._invocation_stage(tool)}/001/seed.json"
    seed = {
        "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
        "synthetic": True,
        "tool": tool,
        "command_digest": release.sha256_json(
            {"tool": tool, "argv": argv, "working_directory": str(cwd)}
        ),
        "members": [
            {
                "member_id": n,
                "path": "raw/" + n + ".bin",
                "schema_id": "application/octet-stream",
                "bytes": len(raw),
                "sha256": release.sha256_bytes(raw),
            }
            for n, raw in responses.items()
        ],
        "data": data,
    }
    for n, raw in responses.items():
        _seed_staging_put(root / Path(name).parent / "raw" / f"{n}.bin", raw)
    _seed_staging_put(root / name, json.dumps(seed, indent=2).encode() + b"\n")
    kw = {
        "working_directory": cwd,
        "held_inputs": captured,
        "expected_inputs": expected,
        "input_types": types,
        "selection": selection,
        "live": False,
    }
    return (root, argv, seed, name, kw)


def _seed_staging_target_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, generic: Any = False, artifacts: Any = False
) -> Any:
    from datetime import datetime, UTC, timedelta

    context, registry = _fixture_native_target_inputs(generic)
    versions = ["0.4.1", "0.4.2"] if generic else ["0.4.1"]
    _, ops = release._release_fixture_target_expectations(
        {"provider-auth-from-approved-environment": True},
        context=context,
        expected_context_digest=release.sha256_json(context),
        registry_raw=registry,
        expected_registry_digest=release.sha256_bytes(registry),
        requested_versions=versions,
    )
    raws = {}
    selected = []
    for i, op in enumerate(ops):
        req = op["request"]
        state = "occupied" if generic and i < 3 or (artifacts and i == 0) else "unused"
        items = []
        ids = []
        if state == "occupied":
            for k in range(2 if artifacts else 1):
                name = f"artifact-{i}-{k}"
                raw = b"explicit finite synthetic artifact " + name.encode()
                raws[name] = raw
                ids.append(name)
                items.append(
                    {"name": name + ".whl", "bytes": len(raw), "sha256": release.sha256_bytes(raw)}
                )
        name = f"response-{i}"
        raws[name] = (
            json.dumps(
                {
                    **{
                        k: req[k]
                        for k in ("target_id", "normalized_package_version", "release_tag")
                    },
                    "state": state,
                    "artifacts": items,
                },
                indent=2,
            ).encode()
            + b"\n"
        )
        selected.append({"response_member_id": name, "artifact_member_ids": ids})
    end = datetime.now(UTC) - timedelta(seconds=1)
    start = end - timedelta(seconds=1)
    data = {
        "requested_versions": versions,
        "responses": selected,
        "capture_started_at": start.isoformat().replace("+00:00", "Z"),
        "capture_completed_at": end.isoformat().replace("+00:00", "Z"),
    }
    ordinary = {
        "inputs/context.json": release.canonical_json(context),
        "inputs/targets.json": registry,
    }
    types = {
        "inputs/context.json": "metriplane.release-context.v1",
        "inputs/targets.json": "metriplane.release-targets.v1",
    }
    return _seed_staging_generic_seed(
        tmp_path,
        monkeypatch,
        "capture_release_target_observations.py",
        ordinary,
        {
            "release-context": "inputs/context.json",
            "targets": "inputs/targets.json",
            "provider-auth-from-approved-environment": True,
        },
        data,
        raws,
        types,
        {
            "context_digest": release.sha256_json(context),
            "registry_digest": release.sha256_bytes(registry),
        },
    )


@pytest.mark.parametrize("generic", [False, True])
def test_seed_staging_target_complete_finite_artifact_plan_and_distinct_clocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generic: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_target_seed(
        tmp_path, monkeypatch, generic=generic, artifacts=True
    )
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert len(plan.operations) == (6 if generic else 3)
    assert len(plan.artifact_payloads) == (6 if generic else 2)
    assert all(
        (
            n.startswith("native-fixture/capture-release-target-observations/001/")
            for n, _ in plan.artifact_payloads
        )
    )
    original = release.begin_release_invocation(
        argv[0],
        argv[1:],
        plan.directory,
        input_paths=[(root / n, s) for n, s, _ in plan.input_plan],
        planned_outputs=[(root / n, s) for n, s in plan.output_plan],
    )
    ip = (original.directory / "intent.json").relative_to(root).as_posix()
    intent = release._ReleaseCapturedFiles.capture(
        root,
        [(ip, "prerequisite-original")],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
        expected_root_directories=plan.captured.root_directories,
    )
    bound = release._release_fixture_seed_bind(original, plan=plan, original_intent_capture=intent)
    e = release._release_fixture_seed_emulate(bound)
    assert seed["data"]["capture_completed_at"] < e.operation_times[0][0]
    full = release._ReleaseCapturedFiles(
        root, plan.captured.root_directories, tuple((*plan.captured.rows, *intent.rows))
    )
    subject = json.loads(plan.subject)
    native_rows = []
    for op, raw, times in zip(
        plan.operations, plan.response_payloads, e.operation_times, strict=True
    ):
        op = json.loads(op)
        native_rows.append(
            release.canonical_json(
                {
                    "kind": op["kind"],
                    "request": op["request"],
                    "response": json.loads(raw),
                    "started_at": times[0],
                    "completed_at": times[1],
                }
            )
        )
    producer = {
        "tool": plan.tool,
        "invocation_id": original.intent["invocation_id"],
        "sequence": 1,
        "intent_digest": release.sha256_json(original.intent),
    }
    facts = release._ReleaseFixtureNativeFacts(
        release.canonical_json(producer),
        release.canonical_json(subject),
        tuple(native_rows),
        (),
        (),
    )
    options = {
        "captured": full,
        "original_context": json.loads((root / "inputs/context.json").read_bytes()),
        "expected_context_digest": kw["selection"]["context_digest"],
        "registry_raw": (root / "inputs/targets.json").read_bytes(),
        "expected_registry_digest": kw["selection"]["registry_digest"],
        "native_facts": facts,
    }
    result = release._release_fixture_target_transcript_replay(original, **options)
    assert (
        result["original_admission_clock"] == original.intent["started_at"]
        and result["supplied_interval"][1] == seed["data"]["capture_completed_at"]
    )
    assert result["fixture_api_version"] == "metriplane.release-fixture-native-request.v1"
    moved = root.with_name("moved")
    root.rename(moved)
    relocated = release.ReleaseInvocation(
        moved / "invocations" / release._invocation_stage(plan.tool) / "001", moved, original.intent
    )
    options["captured"] = release._ReleaseCapturedFiles.capture(
        moved,
        [(row[0], "prerequisite-original") for row in full.rows],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )

    class NoFreshWallClock(release.datetime):
        @classmethod
        def now(cls: Any, tz: Any = None) -> Any:
            raise AssertionError("historical fixture replay must use its original admission clock")

    monkeypatch.setattr(release, "datetime", NoFreshWallClock)
    assert release._release_fixture_target_transcript_replay(relocated, **options) == result
    bad = list(facts.operations)
    v = json.loads(bad[0])
    v["response"]["state"] = "unused"
    v["response"]["artifacts"] = []
    bad[0] = release.canonical_json(v)
    options["native_facts"] = release._ReleaseFixtureNativeFacts(
        facts.producer_identity, facts.subject, tuple(bad), (), ()
    )
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_target_transcript_replay(relocated, **options)


def test_seed_staging_public_target_command_completes_and_is_consumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, _, _ = _seed_staging_target_seed(
        tmp_path, monkeypatch, generic=True, artifacts=True
    )
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / argv[0]), *argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    directory = root / "invocations/capture-release-target-observations/001"
    context = release._validate_intent(directory)
    terminal = release._validate_terminal(context)
    assert terminal["status"] == "PASS"
    assert json.loads((directory / "worker.pid").read_bytes())["pid"] != os.getpid()
    record_path = root / "primary.json"
    record = json.loads(record_path.read_bytes())
    release.validate_release_producer_journal(
        record,
        record_path,
        producer="capture_release_target_observations.py",
    )
    assert record["data"]["observation_digest"] == release.sha256_json(
        {key: value for key, value in record["data"].items() if key != "observation_digest"}
    )
    assert {row["state"] for row in record["data"]["targets"]} == {
        "occupied",
        "unused",
    }
    assert len(terminal["data"]["outputs"]) == len(context.intent["planned_outputs"])
    witness_path = directory / "terminal-commit.json"
    witness = json.loads(witness_path.read_bytes())
    witness["terminal_sha256"] = "0" * 64
    witness_path.chmod(384)
    witness_path.write_bytes(release.canonical_json(witness))
    with pytest.raises(release.ReleaseControlError, match="completion witness|terminal-commit"):
        release.validate_release_producer_journal(
            record,
            record_path,
            producer="capture_release_target_observations.py",
        )


def _seed_staging_empty_burn_lineage(root: Path) -> Path:
    repository = Path(__file__).resolve().parents[1]
    genesis = _fixture_native_genesis_raw()
    genesis_path = root / "inputs/genesis.json"
    stores_path = root / "inputs/stores.json"
    _seed_staging_put(genesis_path, genesis)
    _seed_staging_put(stores_path, release.canonical_json(_fixture_native_registry()))
    genesis_digest = release.sha256_bytes(genesis)
    genesis_data = json.loads(genesis)
    response = release.canonical_json(
        {
            "backend_id": "attempt-index",
            "genesis_digest": genesis_digest,
            "namespace": genesis_data["namespace"],
            "binding_digest": genesis_data["binding_digest"],
            "through_head": genesis_digest,
            "entries": [],
        }
    )

    def execute(tool: str, argv: list[str], output: Path) -> None:
        seed_root = root / "inputs/fixture-native" / release._invocation_stage(tool) / "001"
        seed = {
            "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
            "synthetic": True,
            "tool": tool,
            "command_digest": release.sha256_json(
                {"tool": tool, "argv": argv, "working_directory": str(repository)}
            ),
            "members": [
                {
                    "member_id": "readback",
                    "path": "raw/readback.bin",
                    "schema_id": "application/octet-stream",
                    "bytes": len(response),
                    "sha256": release.sha256_bytes(response),
                }
            ],
            "data": {"response_member_ids": ["readback"]},
        }
        _seed_staging_put(seed_root / "raw/readback.bin", response)
        _seed_staging_put(seed_root / "seed.json", json.dumps(seed, indent=2).encode() + b"\n")
        completed = subprocess.run(
            [sys.executable, str(repository / "tools" / tool), *argv[1:]],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        record = json.loads(output.read_bytes())
        release.validate_release_producer_journal(record, output, producer=tool)

    index_path = root / "index-export.json"
    index_tool = "export_release_attempt_index.py"
    index_argv = [
        index_tool,
        "--index-backend",
        "attempt-index",
        "--genesis",
        str(genesis_path),
        "--through-head",
        genesis_digest,
        "--stores",
        str(stores_path),
        "--read-back-all",
        "--out",
        str(index_path),
        "--invocation-dir",
        str(root / "invocations/export-release-attempt-index/001"),
    ]
    execute(index_tool, index_argv, index_path)
    lineage_path = root / "burn-lineage.json"
    lineage_tool = "export_release_burn_lineage.py"
    lineage_argv = [
        lineage_tool,
        "--milestone",
        "v0.4",
        "--attempt-index-backend",
        "attempt-index",
        "--genesis",
        str(genesis_path),
        "--index-export",
        str(index_path),
        "--through-head",
        genesis_digest,
        "--read-back-all",
        "--out",
        str(lineage_path),
        "--invocation-dir",
        str(root / "invocations/export-release-burn-lineage/001"),
    ]
    execute(lineage_tool, lineage_argv, lineage_path)
    return lineage_path


def test_public_target_resolution_and_burn_commands_connect_retained_producers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, observation_argv, _, _, _ = _seed_staging_target_seed(
        tmp_path, monkeypatch, generic=True, artifacts=True
    )
    repository = Path(__file__).resolve().parents[1]
    observed = subprocess.run(
        [sys.executable, str(repository / "tools" / observation_argv[0]), *observation_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert observed.returncode == 0, observed.stderr or observed.stdout
    observations_path = root / "primary.json"
    lineage_path = _seed_staging_empty_burn_lineage(root)
    resolution_path = root / "target-resolution.json"
    resolution_argv = [
        "--milestone",
        "v0.4",
        "--initial-package-version",
        "v0.4.1",
        "--initial-release-tag",
        "v0.4.1",
        "--targets",
        "inputs/targets.json",
        "--live-target-observations",
        "primary.json",
        "--retained-burn-lineage",
        "burn-lineage.json",
        "--out",
        "target-resolution.json",
        "--invocation-dir",
        "invocations/resolve-release-target/001",
    ]
    resolved = subprocess.run(
        [sys.executable, str(repository / "tools/resolve_release_target.py"), *resolution_argv],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    resolution = json.loads(resolution_path.read_bytes())
    release.validate_release_producer_journal(
        resolution, resolution_path, producer="resolve_release_target.py"
    )
    assert resolution_path.stat().st_nlink == 1
    assert resolution["data"]["selected_package_version"] == "v0.4.2"
    assert resolution["data"]["requires_new_burn"] is True

    validated = subprocess.run(
        [
            sys.executable,
            str(repository / "tools/validate_release_target_resolution.py"),
            "--record",
            str(resolution_path),
            "--targets",
            str(root / "inputs/targets.json"),
            "--read-back-lineage",
            "--invocation-dir",
            str(root / "invocations/validate-release-target-resolution/001"),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert validated.returncode == 0, validated.stderr or validated.stdout
    validation = release._validate_terminal(
        release._validate_intent(root / "invocations/validate-release-target-resolution/001")
    )
    assert validation["status"] == "PASS"
    assert validation["data"]["outputs"] == []
    validation_context = release._validate_intent(
        root / "invocations/validate-release-target-resolution/001"
    )
    with monkeypatch.context() as isolated:
        isolated.setattr(
            release,
            "_validate_release_target_resolution_operation",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                release.ReleaseControlError("synthetic false-success worker")
            ),
        )
        with pytest.raises(release.ReleaseControlError, match="false-success"):
            release._verify_staged_outputs(validation_context, [])

    burn_path = root / "target-burn.json"
    burn_argv = [
        "--target-observations",
        str(observations_path),
        "--burn-lineage",
        str(lineage_path),
        "--target-resolution",
        str(resolution_path),
        "--out",
        str(burn_path),
        "--invocation-dir",
        str(root / "invocations/record-release-target-burn/001"),
    ]
    burned = subprocess.run(
        [sys.executable, str(repository / "tools/record_release_target_burn.py"), *burn_argv],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert burned.returncode == 0, burned.stderr or burned.stdout
    burn = json.loads(burn_path.read_bytes())
    release.validate_release_producer_journal(
        burn, burn_path, producer="record_release_target_burn.py"
    )
    assert burn_path.stat().st_nlink == 1
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [
            ("target-resolution.json", "prerequisite-original"),
            ("target-burn.json", "prerequisite-original"),
        ],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    captured.revalidate()
    assert burn["data"]["disposition"] == "new_burn"
    assert burn["data"]["indexing_required"] is True
    assert burn["data"]["resolved_package_version"] == "v0.4.2"
    assert {row["version"] for row in burn["data"]["affected_targets"]} == {"0.4.1"}

    original_resolution = resolution_path.read_bytes()
    retry_argv = [
        *resolution_argv[:-1],
        str(root / "invocations/resolve-release-target/002"),
    ]
    retry = subprocess.run(
        [sys.executable, str(repository / "tools/resolve_release_target.py"), *retry_argv],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert retry.returncode == 3
    assert resolution_path.read_bytes() == original_resolution
    retry_directory = root / "invocations/resolve-release-target/002"
    retry_terminal = release._validate_terminal(release._validate_intent(retry_directory))
    assert retry_terminal["status"] == "BLOCKED"
    assert retry_terminal["data"]["outputs"] == []
    assert not (retry_directory / "terminal-commit.json").exists()

    substituted_resolution = root / "substituted-target-resolution.json"
    substituted_resolution.write_bytes(resolution_path.read_bytes())
    rejected_burn = root / "rejected-target-burn.json"
    rejected = subprocess.run(
        [
            sys.executable,
            str(repository / "tools/record_release_target_burn.py"),
            "--target-observations",
            str(observations_path),
            "--burn-lineage",
            str(lineage_path),
            "--target-resolution",
            str(substituted_resolution),
            "--out",
            str(rejected_burn),
            "--invocation-dir",
            str(root / "invocations/record-release-target-burn/002"),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 3
    assert "BLOCKED_NOT_READY" in rejected.stdout
    assert not rejected_burn.exists()
    rejected_directory = root / "invocations/record-release-target-burn/002"
    rejected_terminal = release._validate_terminal(release._validate_intent(rejected_directory))
    assert rejected_terminal["status"] == "BLOCKED"
    assert rejected_terminal["data"]["outputs"] == []
    assert not (rejected_directory / "terminal-commit.json").exists()

    for command_context, selected in [
        (
            release._validate_intent(root / "invocations/record-release-target-burn/001"),
            lineage_path,
        ),
        (
            release._validate_intent(root / "invocations/validate-release-target-resolution/001"),
            root / "inputs/targets.json",
        ),
    ]:
        selected.chmod(0o600)
        original = selected.read_bytes()
        selected.write_bytes(original + b" ")
        with pytest.raises(release.ReleaseControlError):
            release._validate_bound_invocation(command_context)
        selected.write_bytes(original)
        selected.chmod(0o400)

    relocated = tmp_path / "relocated-target-run"
    shutil.copytree(root, relocated)
    shutil.rmtree(root)
    relocated_resolution_path = relocated / "target-resolution.json"
    relocated_burn_path = relocated / "target-burn.json"
    release.validate_release_producer_journal(
        json.loads(relocated_resolution_path.read_bytes()),
        relocated_resolution_path,
        producer="resolve_release_target.py",
    )
    release.validate_release_producer_journal(
        json.loads(relocated_burn_path.read_bytes()),
        relocated_burn_path,
        producer="record_release_target_burn.py",
    )
    relocated_validation = subprocess.run(
        [
            sys.executable,
            str(repository / "tools/validate_release_target_resolution.py"),
            "--record",
            str(relocated_resolution_path),
            "--targets",
            str(relocated / "inputs/targets.json"),
            "--read-back-lineage",
            "--invocation-dir",
            str(relocated / "invocations/validate-release-target-resolution/002"),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert relocated_validation.returncode == 0, (
        relocated_validation.stderr or relocated_validation.stdout
    )


def test_target_resolution_rejects_input_replacement_after_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, observation_argv, _, _, _ = _seed_staging_target_seed(
        tmp_path, monkeypatch, generic=True, artifacts=True
    )
    repository = Path(__file__).resolve().parents[1]
    observed = subprocess.run(
        [sys.executable, str(repository / "tools" / observation_argv[0]), *observation_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert observed.returncode == 0, observed.stderr or observed.stdout
    lineage_path = _seed_staging_empty_burn_lineage(root)
    out = root / "target-resolution.json"
    argv = [
        "--milestone",
        "v0.4",
        "--initial-package-version",
        "v0.4.1",
        "--initial-release-tag",
        "v0.4.1",
        "--targets",
        str(root / "inputs/targets.json"),
        "--live-target-observations",
        str(root / "primary.json"),
        "--retained-burn-lineage",
        str(lineage_path),
        "--out",
        str(out),
        "--invocation-dir",
        str(root / "invocations/resolve-release-target/001"),
    ]
    context = release.begin_release_invocation(
        "resolve_release_target.py",
        argv,
        root / "invocations/resolve-release-target/001",
        input_paths=release._release_target_command_input_paths(
            "resolve_release_target.py", argv, root
        ),
        planned_outputs=[(out, "metriplane.release-target-resolution.v1")],
    )
    lineage_path.chmod(0o600)
    original = lineage_path.read_bytes()
    lineage_path.write_bytes(original + b" ")
    with pytest.raises(
        release.ReleaseControlError, match="input identity changed after reservation"
    ):
        release._validate_bound_invocation(context)


@pytest.mark.parametrize("case", ["observation", "lineage-witness"])
def test_public_target_resolution_rejects_substituted_retained_history_before_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    root, observation_argv, _, _, _ = _seed_staging_target_seed(
        tmp_path, monkeypatch, generic=True, artifacts=True
    )
    repository = Path(__file__).resolve().parents[1]
    observed = subprocess.run(
        [sys.executable, str(repository / "tools" / observation_argv[0]), *observation_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert observed.returncode == 0, observed.stderr or observed.stdout
    observations_path = root / "primary.json"
    lineage_path = _seed_staging_empty_burn_lineage(root)
    if case == "observation":
        observations_path.chmod(0o600)
        value = json.loads(observations_path.read_bytes())
        value["data"]["targets"][0]["state"] = "unused"
        observations_path.write_bytes(release.canonical_json(value))
    else:
        lineage = json.loads(lineage_path.read_bytes())
        directory = root / "invocations/export-release-burn-lineage/001"
        witness_path = directory / "terminal-commit.json"
        witness_path.chmod(0o600)
        witness = json.loads(witness_path.read_bytes())
        witness["terminal_sha256"] = "0" * 64
        witness_path.write_bytes(release.canonical_json(witness))
        assert lineage["record_type"] == "release-burn-lineage"
    result = subprocess.run(
        [
            sys.executable,
            str(repository / "tools/resolve_release_target.py"),
            "--milestone",
            "v0.4",
            "--initial-package-version",
            "v0.4.1",
            "--initial-release-tag",
            "v0.4.1",
            "--targets",
            str(root / "inputs/targets.json"),
            "--live-target-observations",
            str(observations_path),
            "--retained-burn-lineage",
            str(lineage_path),
            "--out",
            str(root / "target-resolution.json"),
            "--invocation-dir",
            str(root / "invocations/resolve-release-target/001"),
        ],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == (2 if case == "observation" else 3)
    assert ("INVALID_INPUT" if case == "observation" else "BLOCKED_NOT_READY") in result.stdout
    assert not (root / "target-resolution.json").exists()
    invocation = root / "invocations/resolve-release-target/001"
    if case == "observation":
        assert not invocation.parent.exists()
    else:
        terminal = release._validate_terminal(release._validate_intent(invocation))
        assert terminal["status"] == "BLOCKED"
        assert terminal["data"]["outputs"] == []
        assert not (invocation / "terminal-commit.json").exists()


@pytest.mark.parametrize("case", ["failure", "interruption", "replacement"])
def test_seed_staging_public_target_command_retains_nonpassing_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    root, argv, _, _, _ = _seed_staging_target_seed(tmp_path, monkeypatch)
    if case == "failure":
        monkeypatch.setattr(
            release,
            "_release_fixture_seed_emulate",
            lambda _: (_ for _ in ()).throw(release.ReleaseControlError("worker failure")),
        )
    elif case == "interruption":
        monkeypatch.setattr(
            release,
            "_release_fixture_seed_emulate",
            lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    else:
        collect = release._release_fixture_collect_staged

        def replace(emulation: Any, **kwargs: Any) -> Any:
            staged = kwargs["original_staged_directory"].path
            saved = staged.with_name("staged-original")
            staged.rename(saved)
            shutil.copytree(saved, staged)
            return collect(emulation, **kwargs)

        monkeypatch.setattr(release, "_release_fixture_collect_staged", replace)
    expected = 130 if case == "interruption" else 3
    assert release.run_release_command(argv[0], argv[1:]) == expected
    directory = root / "invocations/capture-release-target-observations/001"
    terminal = release._validate_terminal(release._validate_intent(directory))
    assert terminal["status"] == ("CANCELLED" if case == "interruption" else "BLOCKED")
    assert terminal["data"]["outputs"] == []
    assert not (root / "primary.json").exists()
    assert (directory / "partial-files.json").exists()


def test_seed_staging_public_target_command_recovers_in_next_original_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, argv, _, name, _ = _seed_staging_target_seed(tmp_path, monkeypatch)
    emulate = release._release_fixture_seed_emulate
    monkeypatch.setattr(
        release,
        "_release_fixture_seed_emulate",
        lambda _: (_ for _ in ()).throw(release.ReleaseControlError("first operation failed")),
    )
    assert release.run_release_command(argv[0], argv[1:]) == 3
    monkeypatch.setattr(release, "_release_fixture_seed_emulate", emulate)
    second_argv = [value.replace("/001", "/002") for value in argv]
    source = root / Path(name).parent
    destination = source.parent / "002"
    shutil.copytree(source, destination)
    seed_path = destination / "seed.json"
    seed = json.loads(seed_path.read_bytes())
    seed["command_digest"] = release.sha256_json(
        {"tool": argv[0], "argv": second_argv, "working_directory": str(Path.cwd())}
    )
    seed_path.write_bytes(json.dumps(seed, indent=2).encode() + b"\n")
    assert release.run_release_command(second_argv[0], second_argv[1:]) == 0
    first = release._validate_intent(root / "invocations/capture-release-target-observations/001")
    second = release._validate_intent(root / "invocations/capture-release-target-observations/002")
    terminal = release._validate_terminal(second)
    assert terminal["status"] == "PASS"
    assert second.intent["predecessor"]["intent_digest"] == release.sha256_bytes(
        (first.directory / "intent.json").read_bytes()
    )
    assert second.intent["predecessor"]["terminal_digest"] == release.sha256_bytes(
        (first.directory / "invocation.json").read_bytes()
    )


@pytest.mark.parametrize(
    "case",
    [
        "old",
        "future",
        "inverted",
        "bad-version",
        "missing-artifact",
        "extra-artifact",
        "wrong-artifact-R",
        "no-transcript-time",
    ],
)
def test_seed_staging_target_seed_clock_content_and_complete_response_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_target_seed(tmp_path, monkeypatch, artifacts=True)
    if case == "old":
        seed["data"]["capture_started_at"] = seed["data"]["capture_completed_at"] = (
            "2000-01-01T00:00:00Z"
        )
    elif case == "future":
        seed["data"]["capture_started_at"] = seed["data"]["capture_completed_at"] = (
            "2099-01-01T00:00:00Z"
        )
    elif case == "inverted":
        seed["data"]["capture_started_at"] = "2099-01-01T00:00:00Z"
    elif case == "bad-version":
        seed["data"]["requested_versions"] = ["0.4.2"]
    elif case == "missing-artifact":
        seed["data"]["responses"][0]["artifact_member_ids"].pop()
    elif case == "extra-artifact":
        seed["data"]["responses"][0]["artifact_member_ids"].append("absent")
    elif case == "wrong-artifact-R":
        seed["members"][0]["sha256"] = "a" * 64
    elif case == "no-transcript-time":
        del seed["data"]["capture_completed_at"]
    (root / name).write_bytes(json.dumps(seed).encode())
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert not (root / "invocations").exists()


@pytest.mark.parametrize("which", ["directory-failure", "namespace-failure", "tree-failure"])
def test_seed_staging_close_failures_attempt_every_owned_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: Any
) -> None:
    root, argv, seed, name, kw = _seed_staging_preflight_seed(tmp_path, monkeypatch)
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    real_close = os.close
    calls = []

    def close(fd: Any) -> Any:
        calls.append(fd)
        real_close(fd)
        if len(calls) == 1:
            raise OSError("explicit synthetic close failure after actual release")

    if which == "directory-failure":
        monkeypatch.setattr(os, "close", close)
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_directory(
                root / "missing", expected=plan.captured.root_directories
            )
        assert len(calls) >= len(root.parts)
    elif which == "namespace-failure":
        monkeypatch.setattr(os, "close", close)
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_seed_namespace(
                plan.captured, name, {row["member_id"] for row in seed["members"]}
            )
        assert len(calls) > len(root.parts)
    else:
        directory = release._release_fixture_directory(
            root / Path(name).parent, expected=plan.captured.root_directories
        )
        try:
            monkeypatch.setattr(os, "close", close)
            with pytest.raises(release.ReleaseControlError):
                release._release_fixture_exact_tree(
                    directory,
                    {"seed.json", *{"raw/" + row["member_id"] + ".bin" for row in seed["members"]}},
                )
            assert len(calls) == 1
        finally:
            monkeypatch.setattr(os, "close", real_close)
            directory.close()


def _seed_staging_inherited_gate() -> Any:
    return sys.modules[__name__]


def test_seed_staging_linear_full_original_transcript_fixes_pagination_and_graph_before_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, UTC, timedelta

    original = _seed_staging_inherited_gate()
    data, payloads, options, _ = original._linear_wire_fixture()
    now = datetime.now(UTC) - timedelta(seconds=1)
    clock = {
        1: (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        2: now.isoformat().replace("+00:00", "Z"),
    }
    observations = []
    responses = {}
    for index, (identity, member) in enumerate(payloads.items()):
        obs = member["observation"]
        key = f"response-{index}"
        raw = (
            json.dumps(
                {
                    "content": [{"type": "text", "text": json.dumps(member["payload"])}],
                    "isError": False,
                },
                indent=2,
            ).encode()
            + b"\n"
        )
        responses[key] = raw
        observations.append(
            {
                **{k: obs[k] for k in ["id", "round", "tool", "arguments"]},
                "started_at": clock[obs["round"]],
                "completed_at": clock[obs["round"]],
                "response_member_id": key,
            }
        )
    registry = options["readiness_registry_raw"]
    reg = json.loads(registry)
    policy = next((x for x in reg["release_contexts"] if x["context_id"] == options["context_id"]))
    selection = {
        "context_id": options["context_id"],
        "context_policy_digest": release.sha256_json(policy),
        "readiness_digest": options["expected_readiness_digest"],
        "original_packet": options["original_packet"],
        "packet_digest": options["expected_packet_digest"],
        "original_work_orders": options["original_work_orders"],
        "work_orders_digest": options["expected_work_orders_digest"],
        "task_state_policy_raw": options["task_state_policy_raw"],
        "task_state_policy_digest": options["expected_task_state_policy_digest"],
        "declared_dependencies": options["declared_dependencies"],
        "consumer_stage": "prepromotion",
    }
    fixture = _seed_staging_generic_seed(
        tmp_path,
        monkeypatch,
        "capture_linear_release_snapshot.py",
        {"inputs/readiness.json": registry},
        {
            "registry": "inputs/readiness.json",
            "project-id": policy["decision"]["project_id"],
            "provider-auth-from-approved-environment": True,
        },
        {
            "capture_started_at": clock[1],
            "capture_completed_at": clock[2],
            "raw_observations": observations,
        },
        responses,
        {"inputs/readiness.json": "metriplane.release-readiness-registry.v1"},
        selection,
    )
    root, argv, seed, name, kwargs = fixture
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kwargs)
    assert len(plan.operations) == len(observations) > 190
    assert json.loads(plan.subject)["kind"] == "readiness_context_policy"
    assert len(plan.output_plan) == 3 * len(observations) + 1
    assert not (root / "invocations").exists()
    assert len(json.loads(plan.transcript)["projection"]["expected"]["issues"]) == 95
    path, captured = original._linear_wire_capture(tmp_path, data, payloads)
    assert (
        release._release_linear_snapshot_replay(path, captured=captured, **options)["record"][
            "data"
        ]["snapshot_contract"]
        == data["snapshot_contract"]
    )


def test_seed_staging_seed_full_empty_index_read_inventory_before_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = "export_release_attempt_index.py"
    genesis = _fixture_native_genesis_raw()
    digest = release.sha256_bytes(genesis)
    ordinary = {"inputs/genesis.json": genesis}
    types = {"inputs/genesis.json": "metriplane.release-fixture-index-genesis.v1"}
    flags = {
        "genesis": "inputs/genesis.json",
        "index-backend": "attempt-index",
        "through-head": digest,
        "read-back-all": True,
    }
    flags["stores"] = "inputs/stores.json"
    ordinary["inputs/stores.json"] = release.canonical_json(_fixture_native_registry())
    types["inputs/stores.json"] = "metriplane.release-evidence-stores.v1"
    args = {**flags}
    subject, ops = release._release_fixture_index_expectations(
        args, tool=tool, genesis_raw=genesis, expected_genesis_digest=digest
    )
    response = release.canonical_json({**ops[0]["request"], "entries": []})
    root, argv, seed, name, kw = _seed_staging_generic_seed(
        tmp_path,
        monkeypatch,
        tool,
        ordinary,
        flags,
        {"response_member_ids": ["readback"]},
        {"readback": response},
        types,
        {"genesis_digest": digest},
    )
    plan = release._release_fixture_seed_prepare(tool, argv, **kw)
    assert len(plan.operations) == 1 and len(plan.output_plan) == 4
    assert not (root / "invocations").exists()
    assert "original_index_export" not in json.loads(plan.response_payloads[0])
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / tool), *argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    record_path = root / "primary.json"
    record = json.loads(record_path.read_bytes())
    release.validate_release_producer_journal(record, record_path, producer=tool)
    assert record["data"]["entries"] == []
    assert record["data"]["generation"] == 0
    assert record["data"]["through_head"] == digest
    (root / "invocations/export-release-attempt-index/001/terminal-commit.json").unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(record, record_path, producer=tool)


@pytest.mark.parametrize("form", ["single", "multiple", "manifest"])
def test_seed_staging_retention_complete_seed_binds_original_raw_subject_and_six_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: Any
) -> None:
    registry, files, controls = _fixture_native_registry_bundle()
    raw = release.canonical_json(registry)
    ordinary = {
        "inputs/stores.json": raw,
        **{"inputs/" + n: raw for n, raw in files.items()},
        "inputs/a.bin": b"actual supplied fixture A\n",
    }
    if form == "multiple":
        ordinary["inputs/b.bin"] = b"original fixture B\n"
    if form == "manifest":
        ordinary["inputs/manifest.json"] = b'{"explicit":"original pretty manifest bytes"}\n'
    flags = {
        "stores": "inputs/stores.json",
        "phase": "target-burn",
        "input": ["inputs/a.bin"] + (["inputs/b.bin"] if form == "multiple" else []),
    }
    if form == "manifest":
        flags["manifest"] = "inputs/manifest.json"
        flags.pop("input")
    types = {
        n: "metriplane.release-evidence-stores.v1"
        if n == "inputs/stores.json"
        else "application/octet-stream"
        for n in ordinary
    }
    subject, ops = release._release_fixture_retention_expectations(
        flags,
        original_inputs=[ordinary[n] for n in flags.get("input", [])],
        original_manifest=ordinary.get("inputs/manifest.json"),
        registry_raw=raw,
        expected_registry_digest=release.sha256_bytes(raw),
        fixture_run_id="run",
        backend_controls=controls,
    )
    responses = {}
    retained = ordinary.get("inputs/manifest.json") or (
        ordinary["inputs/a.bin"]
        if form == "single"
        else release.canonical_json(
            sorted((release.sha256_bytes(ordinary[n]) for n in flags["input"]))
        )
    )
    for i, op in enumerate(ops):
        responses[f"effect-{i}"] = (
            retained
            if op["kind"] == "retention.read"
            else release.canonical_json(
                {
                    **op["request"],
                    "effect": "immutable_put"
                    if op["kind"] == "retention.put"
                    else "governance_hold",
                    "administration_identity": op["request"]["administration_identity"],
                }
            )
        )
    root, argv, seed, name, kw = _seed_staging_generic_seed(
        tmp_path,
        monkeypatch,
        "retain_release_evidence.py",
        ordinary,
        flags,
        {"response_member_ids": list(responses)},
        responses,
        types,
        {"registry_digest": release.sha256_bytes(raw), "fixture_run_id": "run"},
    )
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert len(plan.operations) == 6 and len(plan.output_plan) == 19
    assert json.loads(plan.subject)["subject_digest"] == release.sha256_bytes(retained)
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / argv[0]), *argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    record_path = root / "primary.json"
    record = json.loads(record_path.read_bytes())
    release.validate_release_producer_journal(
        record, record_path, producer="retain_release_evidence.py"
    )
    native = release._release_fixture_native_plan(
        tool=argv[0],
        sequence=1,
        subject=json.loads(plan.subject),
        operations=[json.loads(value) for value in plan.operations],
    )
    assert record["data"]["all_content_equal"] is True
    assert record["data"]["input_digest"] == release.sha256_bytes(retained)
    assert (root / native[2]["paths"]["response"]).read_bytes() == retained
    assert (root / native[5]["paths"]["response"]).read_bytes() == retained
    (root / "invocations/retain-release-evidence/001/terminal-commit.json").unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(
            record, record_path, producer="retain_release_evidence.py"
        )


def test_seed_staging_role_seed_uses_existing_signed_payload_and_original_provenance_without_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, UTC, timedelta

    original = _seed_staging_inherited_gate()
    source = tmp_path / "source"
    source.mkdir()
    protected, opts = original._original_role_byte_fixture(source)
    record = json.loads(protected.read_bytes())
    data = record["data"]
    assign = data["assignments"]
    now = datetime.now(UTC)
    issued = (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    expires = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    data.update(issued_at=issued, expires_at=expires)
    assign.update(valid_from=issued, valid_until=expires)
    context_raw = (
        json.dumps(json.loads((source / "context.json").read_bytes()), indent=2).encode() + b"\n"
    )
    (source / "context.json").write_bytes(context_raw)
    data["release_context"].update(bytes=len(context_raw), sha256=release.sha256_bytes(context_raw))
    for role in ["operator", "non_author_reviewer", "infrastructure_owner", "publisher"]:
        binding = assign[role]
        value = {
            "granting_actor": release._RELEASE_FIXTURE_NATIVE_ACTOR,
            "role": role,
            "binding_subject": {k: v for k, v in binding.items() if k != "provenance_digest"},
            "expected_operator": data["signer_identity"],
            "run_id": assign["run_id"],
            "milestone": assign["milestone"],
            "context_digest": assign["release_context_digest"],
            "policy_digest": release.sha256_bytes((source / "policy.bin").read_bytes()),
            "issued_at": issued,
            "expires_at": expires,
        }
        raw = json.dumps(value, indent=2).encode() + b"\n"
        (source / (role + ".bin")).write_bytes(raw)
        binding["provenance_digest"] = release.sha256_bytes(raw)
        data["role_provenance_files"][role].update(bytes=len(raw), sha256=release.sha256_bytes(raw))
    data["assignment_payload_digest"] = release.sha256_json(assign)
    data["subject_digests"][0]["sha256"] = release.sha256_json(assign)
    unsigned = release.make_record(
        "release-protected-input",
        data,
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=True,
    )
    digest = release.signature_subject_digest(unsigned)
    sig = {
        "provider": "test-fixture",
        "algorithm": "test-sha256-v1",
        "actor_id": data["signer_identity"],
        "synthetic": True,
        "subject_digest": digest,
        "signature": release.sha256_json(
            {"actor_id": data["signer_identity"], "subject_digest": digest}
        ),
    }
    record = release.make_record(
        "release-protected-input",
        data,
        invocation_id=record["invocation_id"],
        sequence=record["sequence"],
        synthetic=True,
        signatures=[sig],
    )
    protected.write_bytes(release.canonical_json(record))
    ordinary = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    types = {
        n: "metriplane.release-protected-input.v1"
        if n == "protected.json"
        else "metriplane.release-context.v1"
        if n == "context.json"
        else "application/octet-stream"
        for n in ordinary
    }
    selection = {
        "context_digest": opts["expected_context_digest"],
        "policy_digest": opts["expected_assignment_policy_digest"],
        "authority_policy_digest": opts["expected_authority_policy_digest"],
        "keyring_digest": opts["expected_keyring_digest"],
        "independently_expected_operator": data["signer_identity"],
        "use_interval": (
            now.isoformat().replace("+00:00", "Z"),
            now.isoformat().replace("+00:00", "Z"),
        ),
    }
    root, argv, seed, name, kw = _seed_staging_generic_seed(
        tmp_path / "new",
        monkeypatch,
        "record_release_role_assignments.py",
        ordinary,
        {
            "signed-assignments": "protected.json",
            "release-context": "context.json",
            "policy": "policy.bin",
            "run-id": assign["run_id"],
            "milestone": assign["milestone"],
        },
        {},
        {},
        types,
        selection,
    )
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    assert len(plan.operations) == 4 and len(plan.output_plan) == 9 and (not plan.artifact_payloads)
    assert all((not n.endswith("response.bin") for n, _ in plan.output_plan))
    assert all((json.loads(op)["response_path"].endswith(".bin") for op in plan.operations))
    assert not (root / "invocations").exists()
    actual_interval = release._release_fixture_role_interval
    observed_intervals = []

    def observe_interval(bound: Any, completed_at: str) -> None:
        observed_intervals.append((bound.original.intent["started_at"], completed_at))
        actual_interval(bound, completed_at)

    monkeypatch.setattr(release, "_release_fixture_role_interval", observe_interval)
    assert release.run_release_command(argv[0], argv[1:]) == 0
    directory = root / "invocations/record-release-role-assignments/001"
    context = release._validate_intent(directory)
    assert release._validate_terminal(context)["status"] == "PASS"
    output = root / "primary.json"
    result = json.loads(output.read_bytes())
    release.validate_release_producer_journal(
        result, output, producer="record_release_role_assignments.py"
    )
    names = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [(name, "prerequisite-original") for name in names],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    terminal = release._validate_terminal(context)
    assert observed_intervals == [(context.intent["started_at"], terminal["data"]["completed_at"])]
    replay = release._release_recorded_role_byte_replay(
        output,
        protected_path=root / "protected.json",
        context_path=root / "context.json",
        captured=captured,
        expected_context_digest=selection["context_digest"],
        expected_run_id="fixture-run",
        expected_milestone="v0.4",
        expected_assignment_policy_digest=selection["policy_digest"],
        expected_authority_policy_digest=selection["authority_policy_digest"],
        expected_keyring_digest=selection["keyring_digest"],
        expected_producer_intent_digest=release.sha256_json(context.intent),
        expected_invocation_id=context.intent["invocation_id"],
        expected_sequence=context.intent["sequence"],
        use_interval=(context.intent["started_at"], terminal["data"]["completed_at"]),
        live=False,
    )
    assert replay["recorded_assignments"] == result
    seed_source = root / Path(name).parent
    second_seed_directory = seed_source.parent / "002"
    shutil.copytree(seed_source, second_seed_directory)
    second_argv = [
        value.replace("/001", "/002").replace("/primary.json", "/primary-2.json") for value in argv
    ]
    second_seed = second_seed_directory / "seed.json"
    second_seed_record = json.loads(second_seed.read_bytes())
    second_seed_record["command_digest"] = release.sha256_json(
        {"tool": argv[0], "argv": second_argv, "working_directory": str(Path.cwd())}
    )
    second_seed.write_bytes(json.dumps(second_seed_record, indent=2).encode() + b"\n")

    def expire_before_completion(_: Any, __: str) -> None:
        raise release.ReleaseControlError("role authority expired during supervised action")

    monkeypatch.setattr(release, "_release_fixture_role_interval", expire_before_completion)
    assert release.run_release_command(second_argv[0], second_argv[1:]) == 3
    second_directory = root / "invocations/record-release-role-assignments/002"
    second_context = release._validate_intent(second_directory)
    second_terminal = release._validate_terminal(second_context)
    assert second_terminal["status"] == "BLOCKED"
    assert second_terminal["data"]["outputs"] == []
    assert not (root / "primary-2.json").exists()
    assert not (second_directory / "terminal-commit.json").exists()

    third_seed_directory = seed_source.parent / "003"
    shutil.copytree(seed_source, third_seed_directory)
    third_argv = [
        value.replace("/001", "/003").replace("/primary.json", "/primary-3.json") for value in argv
    ]
    third_seed = third_seed_directory / "seed.json"
    third_seed_record = json.loads(third_seed.read_bytes())
    third_seed_record["command_digest"] = release.sha256_json(
        {"tool": argv[0], "argv": third_argv, "working_directory": str(Path.cwd())}
    )
    third_seed.write_bytes(json.dumps(third_seed_record, indent=2).encode() + b"\n")
    monkeypatch.setattr(release, "_release_fixture_role_interval", actual_interval)
    assert release.run_release_command(third_argv[0], third_argv[1:]) == 0
    third_context = release._validate_intent(
        root / "invocations/record-release-role-assignments/003"
    )
    assert third_context.intent["predecessor"]["terminal_digest"] == release.sha256_bytes(
        (second_directory / "invocation.json").read_bytes()
    )
    assert release._validate_terminal(third_context)["status"] == "PASS"
    (directory / "terminal-commit.json").unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(
            result, output, producer="record_release_role_assignments.py"
        )


def test_seed_staging_cas_seed_uses_original_subject_graph_before_receipt_without_token_hash_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    original = _seed_staging_inherited_gate()
    receipt, old = original._index_command_build(tmp_path / "source", "burn")
    source = old["captured"].root
    oldargs = release._release_original_arguments(
        "update_release_attempt_index.py", old["update"].intent["argv"]
    )
    manifest = Path(oldargs["entry-manifest"]).read_bytes()
    retention = Path(oldargs["entry-receipts"]).read_bytes()
    subject = old["subject_record"]
    genesis = _fixture_native_genesis_raw()
    gd = release.sha256_bytes(genesis)
    ordinary = {
        "manifest.json": manifest,
        "retention.json": retention,
        "target-burn.json": (source / "target-burn.json").read_bytes(),
        "inputs/genesis.json": genesis,
    }
    types = {
        "manifest.json": "metriplane.release-evidence-manifest.v1",
        "retention.json": "metriplane.release-retention-receipts.v1",
        "target-burn.json": "metriplane.release-target-burn.v1",
        "inputs/genesis.json": "metriplane.release-fixture-index-genesis.v1",
    }
    selection = {
        k: old[k]
        for k in [
            "expected_scope",
            "expected_operation_id",
            "expected_milestone",
            "expected_release_tag",
            "expected_index_backend",
        ]
    }
    selection.update(
        genesis_path=tmp_path / "new/run/inputs/genesis.json",
        genesis_digest=gd,
        expected_prior_generation=0,
        expected_prior_head=gd,
        subject_path=tmp_path / "new/run/target-burn.json",
        subject_record=subject,
        attempt_directory=None,
        expected_attempt_id=None,
        coordination_record=None,
        coordination_path=None,
    )
    flags = {
        "entry-manifest": "manifest.json",
        "entry-receipts": "retention.json",
        "scope-kind": "release_staging",
        "scope-id": selection["expected_scope"]["scope_id"],
        "stage": "target-burn",
        "sequence": "001",
        "release-tag": "v0.4.1",
        "index-backend": "attempt-index",
        "expected-head": gd,
        "operation-id": selection["expected_operation_id"],
        "milestone": "v0.4",
        "run-id": selection["expected_scope"]["run_id"],
        "candidate-id-not-resolved": True,
    }
    entry = {
        "schema_version": "metriplane.release-attempt-index-entry.v1",
        "backend_id": "attempt-index",
        "genesis_digest": gd,
        "generation": 1,
        "previous_head": None,
        "operation_id": selection["expected_operation_id"],
        "token": "opaque-original-fixture-backend-token",
        "milestone": "v0.4",
        "scope": selection["expected_scope"],
        "entry_manifest_digest": release.sha256_json(json.loads(manifest)),
        "entry_receipts_digest": release.sha256_json(json.loads(retention)),
    }
    response = {
        "backend_id": "attempt-index",
        "genesis_digest": gd,
        "operation_id": entry["operation_id"],
        "expected_head": gd,
        "entry": entry,
        "committed_head": release.sha256_json(entry),
        "read_back_digest": release.sha256_json(entry),
        "disposition": "committed",
    }
    root, argv, seed, name, kw = _seed_staging_generic_seed(
        tmp_path / "new",
        monkeypatch,
        "update_release_attempt_index.py",
        ordinary,
        flags,
        {"response_member_ids": ["cas"]},
        {"cas": release.canonical_json(response)},
        types,
        selection,
    )
    plan = release._release_fixture_seed_prepare(argv[0], argv, **kw)
    req = json.loads(plan.operations[0])["request"]
    assert (
        len(plan.operations) == 1
        and len(plan.output_plan) == 4
        and ("token" not in req)
        and ("entry" not in req)
    )
    assert json.loads(plan.response_payloads[0])["entry"]["token"] != response["committed_head"]
    assert not (root / "invocations").exists()
    public_arguments = release._release_original_arguments(argv[0], argv)
    without_scope = dict(public_arguments)
    without_scope.pop("scope-id")
    with pytest.raises(release.ReleaseControlError, match="independently selected scope"):
        release._release_fixture_index_update_command_inputs(root, without_scope, Path.cwd())
    stale_head = dict(public_arguments)
    stale_head["expected-head"] = "f" * 64
    with pytest.raises(release.ReleaseControlError, match="complete acyclic receipt chain"):
        release._release_fixture_index_update_command_inputs(root, stale_head, Path.cwd())
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repository / "tools" / argv[0]), *argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    record_path = root / "primary.json"
    record = json.loads(record_path.read_bytes())
    release.validate_release_producer_journal(
        record, record_path, producer="update_release_attempt_index.py"
    )
    assert release._release_index_receipt_content(record["data"]) == entry
    assert record["data"]["committed_head"] == release.sha256_json(entry)

    def subsequent(
        *,
        journal_sequence: int,
        operation_id: str,
        scope_id: str,
        expected_head: str,
        token: str,
        output_name: str,
        generation: int = 2,
        scope_sequence: int | None = None,
        disposition: str = "committed",
    ) -> tuple[list[str], dict[str, Any]]:
        manifest_name = "manifest.json"
        retention_name = "retention.json"
        scope = {
            **selection["expected_scope"],
            "scope_id": scope_id,
            "sequence": journal_sequence if scope_sequence is None else scope_sequence,
        }
        next_entry = {
            **entry,
            "generation": generation,
            "previous_head": expected_head,
            "operation_id": operation_id,
            "token": token,
            "scope": scope,
        }
        next_response = release.canonical_json(
            {
                "backend_id": "attempt-index",
                "genesis_digest": gd,
                "operation_id": operation_id,
                "expected_head": expected_head,
                "entry": next_entry,
                "committed_head": release.sha256_json(next_entry),
                "read_back_digest": release.sha256_json(next_entry),
                "disposition": disposition,
            }
        )
        next_argv = [
            argv[0],
            "--entry-manifest",
            str(root / manifest_name),
            "--entry-receipts",
            str(root / retention_name),
            "--scope-kind",
            "release_staging",
            "--scope-id",
            scope_id,
            "--stage",
            "target-burn",
            "--sequence",
            str(scope["sequence"]),
            "--release-tag",
            "v0.4.1",
            "--index-backend",
            "attempt-index",
            "--expected-head",
            expected_head,
            "--operation-id",
            operation_id,
            "--milestone",
            "v0.4",
            "--run-id",
            selection["expected_scope"]["run_id"],
            "--candidate-id-not-resolved",
            "--out",
            str(root / output_name),
            "--invocation-dir",
            str(root / f"invocations/update-release-attempt-index/{journal_sequence:03d}"),
        ]
        seed_name = (
            f"inputs/fixture-native/update-release-attempt-index/{journal_sequence:03d}/seed.json"
        )
        seed_record = {
            "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
            "synthetic": True,
            "tool": argv[0],
            "command_digest": release.sha256_json(
                {"tool": argv[0], "argv": next_argv, "working_directory": str(Path.cwd())}
            ),
            "members": [
                {
                    "member_id": "cas",
                    "path": "raw/cas.bin",
                    "schema_id": "application/octet-stream",
                    "bytes": len(next_response),
                    "sha256": release.sha256_bytes(next_response),
                }
            ],
            "data": {"response_member_ids": ["cas"]},
        }
        seed_path = root / seed_name
        _seed_staging_put(seed_path.parent / "raw/cas.bin", next_response)
        _seed_staging_put(seed_path, json.dumps(seed_record, indent=2).encode() + b"\n")
        return next_argv, next_entry

    head1 = release.sha256_json(entry)
    second_argv, entry2 = subsequent(
        journal_sequence=2,
        operation_id="second-original-operation",
        scope_id="second-explicit-scope",
        expected_head=head1,
        token="opaque-second-fixture-backend-token",
        output_name="primary-2.json",
    )
    second = subprocess.run(
        [sys.executable, str(repository / "tools" / second_argv[0]), *second_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr or second.stdout
    second_path = root / "primary-2.json"
    second_record = json.loads(second_path.read_bytes())
    release.validate_release_producer_journal(
        second_record, second_path, producer="update_release_attempt_index.py"
    )
    assert release._release_index_receipt_content(second_record["data"]) == entry2

    competing_argv, _ = subsequent(
        journal_sequence=3,
        operation_id="competing-original-operation",
        scope_id="competing-explicit-scope",
        expected_head=head1,
        token="opaque-competing-fixture-backend-token",
        output_name="competing.json",
    )
    competing = subprocess.run(
        [sys.executable, str(repository / "tools" / competing_argv[0]), *competing_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert competing.returncode != 0
    assert "BLOCKED_NOT_READY" in competing.stdout
    assert (
        b"stale or competing writer"
        in (root / "invocations/update-release-attempt-index/003/stderr").read_bytes()
    )
    assert not (root / "competing.json").exists()
    assert not (root / "invocations/update-release-attempt-index/003/terminal-commit.json").exists()

    stores_raw = release.canonical_json(_fixture_native_registry())
    (root / "inputs/stores.json").write_bytes(stores_raw)
    export_tool = "export_release_attempt_index.py"
    export_argv = [
        export_tool,
        "--index-backend",
        "attempt-index",
        "--genesis",
        str(root / "inputs/genesis.json"),
        "--through-head",
        release.sha256_json(entry2),
        "--stores",
        str(root / "inputs/stores.json"),
        "--read-back-all",
        "--out",
        str(root / "export.json"),
        "--invocation-dir",
        str(root / "invocations/export-release-attempt-index/001"),
    ]
    genesis_data = json.loads(genesis)
    export_response = release.canonical_json(
        {
            "backend_id": "attempt-index",
            "genesis_digest": gd,
            "namespace": genesis_data["namespace"],
            "binding_digest": genesis_data["binding_digest"],
            "through_head": release.sha256_json(entry2),
            "entries": [entry, entry2],
        }
    )
    export_seed_name = "inputs/fixture-native/export-release-attempt-index/001/seed.json"
    export_seed = {
        "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
        "synthetic": True,
        "tool": export_tool,
        "command_digest": release.sha256_json(
            {"tool": export_tool, "argv": export_argv, "working_directory": str(Path.cwd())}
        ),
        "members": [
            {
                "member_id": "readback",
                "path": "raw/readback.bin",
                "schema_id": "application/octet-stream",
                "bytes": len(export_response),
                "sha256": release.sha256_bytes(export_response),
            }
        ],
        "data": {"response_member_ids": ["readback"]},
    }
    _seed_staging_put(root / Path(export_seed_name).parent / "raw/readback.bin", export_response)
    _seed_staging_put(root / export_seed_name, json.dumps(export_seed, indent=2).encode() + b"\n")
    exported = subprocess.run(
        [sys.executable, str(repository / "tools" / export_tool), *export_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert exported.returncode == 0, exported.stderr or exported.stdout
    export_path = root / "export.json"
    export_record = json.loads(export_path.read_bytes())
    release.validate_release_producer_journal(export_record, export_path, producer=export_tool)
    assert [row["entry"] for row in export_record["data"]["entries"]] == [entry, entry2]
    assert export_record["data"]["generation"] == 2

    burn_tool = "export_release_burn_lineage.py"
    burn_argv = [
        burn_tool,
        "--milestone",
        "v0.4",
        "--attempt-index-backend",
        "attempt-index",
        "--genesis",
        str(root / "inputs/genesis.json"),
        "--index-export",
        str(export_path),
        "--through-head",
        release.sha256_json(entry2),
        "--read-back-all",
        "--out",
        str(root / "burn-lineage.json"),
        "--invocation-dir",
        str(root / "invocations/export-release-burn-lineage/001"),
    ]
    burn_seed_name = "inputs/fixture-native/export-release-burn-lineage/001/seed.json"
    burn_seed = {
        "schema_version": release._RELEASE_FIXTURE_SEED_SCHEMA,
        "synthetic": True,
        "tool": burn_tool,
        "command_digest": release.sha256_json(
            {"tool": burn_tool, "argv": burn_argv, "working_directory": str(Path.cwd())}
        ),
        "members": [
            {
                "member_id": "readback",
                "path": "raw/readback.bin",
                "schema_id": "application/octet-stream",
                "bytes": len(export_response),
                "sha256": release.sha256_bytes(export_response),
            }
        ],
        "data": {"response_member_ids": ["readback"]},
    }
    _seed_staging_put(root / Path(burn_seed_name).parent / "raw/readback.bin", export_response)
    _seed_staging_put(root / burn_seed_name, json.dumps(burn_seed, indent=2).encode() + b"\n")
    burn_arguments = release._release_original_arguments(burn_tool, burn_argv)
    canonical_export = export_path.read_bytes()
    export_path.chmod(0o600)
    export_path.write_bytes(json.dumps(export_record, indent=2).encode() + b"\n")
    with pytest.raises(release.ReleaseControlError, match="producer|journal|output|bytes"):
        release._release_fixture_burn_lineage_command_inputs(root, burn_arguments, Path.cwd())
    export_path.write_bytes(canonical_export)
    burned = subprocess.run(
        [sys.executable, str(repository / "tools" / burn_tool), *burn_argv[1:]],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert burned.returncode == 0, burned.stderr or burned.stdout
    burn_path = root / "burn-lineage.json"
    burn_record = json.loads(burn_path.read_bytes())
    release.validate_release_producer_journal(burn_record, burn_path, producer=burn_tool)
    assert burn_record["data"]["through_head"] == release.sha256_json(entry2)
    assert burn_record["data"]["read_back_complete"] is True
    assert burn_record["data"]["burns"]

    head2 = release.sha256_json(entry2)
    interrupted_argv, entry3 = subsequent(
        journal_sequence=4,
        scope_sequence=3,
        generation=3,
        operation_id="interrupted-original-operation",
        scope_id="interrupted-explicit-scope",
        expected_head=head2,
        token="opaque-interrupted-fixture-backend-token",
        output_name="primary-3.json",
    )
    collect = release._release_fixture_collect_staged

    def interrupt_with_unsafe_partial(*_: Any, original_staged_directory: Any, **__: Any) -> Any:
        (original_staged_directory.path / "unsafe-link").symlink_to("missing-target")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        release,
        "_release_fixture_collect_staged",
        interrupt_with_unsafe_partial,
    )
    assert release.run_release_command(interrupted_argv[0], interrupted_argv[1:]) == 130
    interrupted_dir = root / "invocations/update-release-attempt-index/004"
    assert release._validate_terminal(release._validate_intent(interrupted_dir))["status"] == (
        "CANCELLED"
    )
    assert not (root / "primary-3.json").exists()
    assert not (interrupted_dir / "terminal-commit.json").exists()
    assert (
        "invocations/update-release-attempt-index/004/staged/unsafe-link"
        in json.loads((interrupted_dir / "partial-files.json").read_bytes())["unreadable"]
    )
    (interrupted_dir / "invocation.json").unlink()
    monkeypatch.setattr(release, "_release_fixture_collect_staged", collect)
    retry_argv, retry_entry = subsequent(
        journal_sequence=5,
        scope_sequence=3,
        generation=3,
        disposition="idempotent",
        operation_id="interrupted-original-operation",
        scope_id="interrupted-explicit-scope",
        expected_head=head2,
        token="opaque-interrupted-fixture-backend-token",
        output_name="primary-3.json",
    )
    assert retry_entry == entry3
    assert release.run_release_command(retry_argv[0], retry_argv[1:]) == 0
    recovered_path = root / "primary-3.json"
    recovered = json.loads(recovered_path.read_bytes())
    release.validate_release_producer_journal(
        recovered, recovered_path, producer="update_release_attempt_index.py"
    )
    assert recovered["data"]["disposition"] == "idempotent"
    assert release._release_index_receipt_content(recovered["data"]) == entry3
    duplicate = release.make_record(
        "release-attempt-index",
        recovered["data"],
        invocation_id=release._validate_intent(interrupted_dir).intent["invocation_id"],
        sequence=4,
        synthetic=True,
    )
    duplicate_path = root / "interrupted-installed-receipt.json"
    duplicate_path.write_bytes(release.canonical_json(duplicate))
    second_retry_argv, second_retry_entry = subsequent(
        journal_sequence=6,
        scope_sequence=3,
        generation=3,
        disposition="idempotent",
        operation_id="interrupted-original-operation",
        scope_id="interrupted-explicit-scope",
        expected_head=head2,
        token="opaque-interrupted-fixture-backend-token",
        output_name="primary-3-copy.json",
    )
    assert second_retry_entry == entry3
    assert release.run_release_command(second_retry_argv[0], second_retry_argv[1:]) == 0
    second_recovered_path = root / "primary-3-copy.json"
    second_recovered = json.loads(second_recovered_path.read_bytes())
    release.validate_release_producer_journal(
        second_recovered,
        second_recovered_path,
        producer="update_release_attempt_index.py",
    )
    reused_scope_argv, _ = subsequent(
        journal_sequence=7,
        scope_sequence=3,
        generation=4,
        operation_id="different-operation-reusing-scope",
        scope_id="interrupted-explicit-scope",
        expected_head=release.sha256_json(entry3),
        token="opaque-reused-scope-token",
        output_name="reused-scope.json",
    )
    assert release.run_release_command(reused_scope_argv[0], reused_scope_argv[1:]) == 3
    assert (
        b"reused logical scope"
        in (root / "invocations/update-release-attempt-index/007/stderr").read_bytes()
    )
    assert not (root / "reused-scope.json").exists()
    assert not (root / "invocations/update-release-attempt-index/007/terminal-commit.json").exists()

    state_directory = root / ".fixture-native-state"
    state_path = state_directory / "attempt-index.json"
    retained_state = state_directory / "attempt-index.retained"
    state_path.rename(retained_state)
    os.mkfifo(state_path, mode=0o600)
    fifo_argv, _ = subsequent(
        journal_sequence=8,
        scope_sequence=3,
        generation=3,
        disposition="idempotent",
        operation_id="interrupted-original-operation",
        scope_id="interrupted-explicit-scope",
        expected_head=head2,
        token="opaque-interrupted-fixture-backend-token",
        output_name="fifo-state.json",
    )
    assert release.run_release_command(fifo_argv[0], fifo_argv[1:]) == 3
    assert not (root / "fifo-state.json").exists()
    witness_path = root / "invocations/update-release-attempt-index/008/terminal-commit.json"
    assert not witness_path.exists()
    state_path.unlink()
    retained_state.rename(state_path)

    lock_path = state_directory / "attempt-index.lock"
    lock_alias = state_directory / "attempt-index.lock.alias"
    os.link(lock_path, lock_alias)
    hardlink_argv, _ = subsequent(
        journal_sequence=9,
        scope_sequence=3,
        generation=3,
        disposition="idempotent",
        operation_id="interrupted-original-operation",
        scope_id="interrupted-explicit-scope",
        expected_head=head2,
        token="opaque-interrupted-fixture-backend-token",
        output_name="hardlink-lock.json",
    )
    assert release.run_release_command(hardlink_argv[0], hardlink_argv[1:]) == 3
    assert not (root / "hardlink-lock.json").exists()
    assert not (root / "invocations/update-release-attempt-index/009/terminal-commit.json").exists()
    lock_alias.unlink()
    relocated = root.with_name(root.name + "-relocated")
    root.rename(relocated)
    try:
        relocated_held = release._ReleaseCapturedFiles.capture(
            relocated,
            [
                ("inputs/genesis.json", "prerequisite-original"),
                ("inputs/stores.json", "prerequisite-original"),
            ],
            forbidden=(),
            allowed_kinds=frozenset({"prerequisite-original"}),
        )
        captured, _, generation = release._release_fixture_index_export_history_capture(
            relocated,
            held=relocated_held,
            genesis_raw=genesis,
            genesis_digest=gd,
            through_head=release.sha256_json(entry3),
        )
        assert generation == 3
        captured.revalidate()
    finally:
        relocated.rename(root)
    for missing in (export_path, record_path, root / "target-burn.json"):
        retained = missing.with_name(missing.name + ".retained")
        missing.rename(retained)
        try:
            with pytest.raises(release.ReleaseControlError):
                release._release_fixture_burn_lineage_command_inputs(
                    root, burn_arguments, Path.cwd()
                )
        finally:
            retained.rename(missing)
    (root / "invocations/update-release-attempt-index/001/terminal-commit.json").unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(
            record, record_path, producer="update_release_attempt_index.py"
        )
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release._release_fixture_burn_lineage_command_inputs(root, burn_arguments, Path.cwd())
    burn_witness = root / "invocations/export-release-burn-lineage/001/terminal-commit.json"
    burn_witness.unlink()
    with pytest.raises(release.ReleaseControlError, match="terminal-commit|witness"):
        release.validate_release_producer_journal(burn_record, burn_path, producer=burn_tool)
    with pytest.raises(release.ReleaseControlError):
        release._release_fixture_seed_prepare(
            argv[0],
            argv,
            **{
                **kw,
                "selection": {**selection, "expected_operation_id": "same-as-attempt-invented"},
            },
        )


@pytest.mark.parametrize("case", ["reverse", "sorted", "missing", "extra"])
def test_seed_staging_role_key_set_never_json_order_determines_fixed_operation_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: Any
) -> None:
    original = _seed_staging_inherited_gate()
    root = tmp_path / "roles"
    root.mkdir()
    protected, kw = original._original_role_byte_fixture(root)
    replay = release._release_original_role_byte_replay(protected, **kw)
    rows = replay["original_provenance"]
    order = list(reversed(rows)) if case == "reverse" else sorted(rows)
    replay = {**replay, "original_provenance": {k: rows[k] for k in order}}
    if case == "missing":
        replay["original_provenance"].pop("publisher")
    if case == "extra":
        replay["original_provenance"]["unowned"] = rows["operator"]
    args = {"run-id": "fixture-run", "milestone": "v0.4"}
    options = {
        "original_role_replay": replay,
        "expected_context_digest": kw["expected_context_digest"],
        "expected_policy_digest": kw["expected_assignment_policy_digest"],
        "independently_expected_operator": "fixture-operator",
        "response_paths": {k: row["path"].name for k, row in replay["original_provenance"].items()},
    }
    if case in {"missing", "extra"}:
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_role_expectations(args, **options)
    else:
        subject, ops = release._release_fixture_role_expectations(args, **options)
        assert [op["request"]["role"] for op in ops] == [
            "operator",
            "non_author_reviewer",
            "infrastructure_owner",
            "publisher",
        ]


@pytest.mark.parametrize(
    "fault", ["partial-write", "file-fsync", "ancestor-swap", "file-swap", "missing-parent-custody"]
)
def test_seed_staging_exclusive_copy_failures_retain_original_partial_bytes_without_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Any
) -> None:
    root, kw, e, stage, parents, captured = _seed_staging_stage_fixture(tmp_path, monkeypatch)
    run = None
    canonical = []
    try:
        collected = release._release_fixture_collect_staged(
            e, original_staged_directory=stage, original_stage_files=captured
        )
        run = release._release_fixture_directory(
            root, expected=e.bound.plan.captured.root_directories
        )
        canonical = _seed_staging_held_parents(
            root, [n for n, _ in e.bound.plan.output_plan], run.identities
        )
        first = e.bound.plan.output_plan[0][0]
        target = root / first
        actual_write = os.write
        actual_fsync = os.fsync
        swapped = []
        if fault == "missing-parent-custody":
            canonical_arg = canonical[:-1]
        else:
            canonical_arg = canonical
        writes = []

        def write(fd: Any, raw: Any) -> Any:
            writes.append(fd)
            if fault == "partial-write":
                if len(writes) == 1:
                    return actual_write(fd, raw[:3])
                raise OSError("synthetic partial write interruption")
            if fault == "ancestor-swap" and (not swapped):
                parent = target.parent
                parent.rename(parent.with_name("retained-original"))
                parent.mkdir()
                swapped.append(parent)
            return actual_write(fd, raw)

        def fsync(fd: Any) -> Any:
            import stat

            if stat.S_ISREG(os.fstat(fd).st_mode):
                if fault == "file-fsync":
                    raise OSError("synthetic durable write failure")
                if fault == "file-swap" and (not swapped):
                    target.rename(target.with_name("retained-original"))
                    target.write_bytes(b"foreign replacement")
                    swapped.append(target)
            return actual_fsync(fd)

        monkeypatch.setattr(os, "write", write)
        monkeypatch.setattr(os, "fsync", fsync)
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_install_sidecar_set(
                collected, original_run_directory=run, original_parent_directories=canonical_arg
            )
        if fault == "partial-write":
            assert (
                target.read_bytes()
                == captured.read(first, kind=dict(e.bound.plan.output_plan)[first])[:3]
            )
        if fault == "ancestor-swap":
            assert list(target.parent.iterdir()) == []
        if fault == "file-swap":
            assert target.read_bytes() == b"foreign replacement"
        assert not (e.bound.original.directory / "invocation.json").exists()
    finally:
        _seed_staging_close_all(parents, canonical, [stage], [] if run is None else [run])


@pytest.mark.parametrize("changed", ["root", "native-parent"])
def test_seed_staging_directory_mode_identity_drift_rejects_before_output_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: Any
) -> None:
    root, kw, e, stage, parents, captured = _seed_staging_stage_fixture(tmp_path, monkeypatch)
    run = None
    canonical = []
    try:
        collected = release._release_fixture_collect_staged(
            e, original_staged_directory=stage, original_stage_files=captured
        )
        run = release._release_fixture_directory(
            root, expected=e.bound.plan.captured.root_directories
        )
        canonical = _seed_staging_held_parents(
            root, [n for n, _ in e.bound.plan.output_plan], run.identities
        )
        path = root if changed == "root" else canonical[-1].path
        old = path.stat().st_mode
        path.chmod(old ^ 8)
        called = []

        def write(*args: Any) -> Any:
            called.append(args)
            raise AssertionError("foreign write after directory identity drift")

        monkeypatch.setattr(os, "write", write)
        with pytest.raises(release.ReleaseControlError):
            release._release_fixture_install_sidecar_set(
                collected, original_run_directory=run, original_parent_directories=canonical
            )
        assert not called
    finally:
        _seed_staging_close_all(parents, canonical, [stage], [] if run is None else [run])


@pytest.mark.parametrize(
    "member",
    [
        "gate-input.json",
        "scenario-catalog.json",
        "worker.pid",
        "worker-result.json",
        "staged/gate-input.json",
        "staged/scenario-catalog.json",
        "stdout",
        "stderr",
        "invocation.json",
        "staged",
        "journal",
        "original-input",
    ],
)
def test_gate_completion_review_revalidates_complete_prefix_after_final_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    context, completion, outputs, identities, fd = _gate_completion_pending(tmp_path, monkeypatch)
    validate = release._validate_bound_invocation
    fired = []

    def final_bound(value: Any, **kwargs: Any) -> Any:
        result = validate(value, **kwargs)
        if (context.directory / "invocation.json").exists() and not fired:
            if member in {"gate-input.json", "scenario-catalog.json"}:
                target = context.root / member
            elif member == "original-input":
                target = context.gate_inputs.captured.root / context.gate_inputs.captured.rows[0][0]
            elif member == "journal":
                target = context.directory
            else:
                target = context.directory / member
            saved = tmp_path / "retained-original"
            target.rename(saved)
            if saved.is_dir():
                shutil.copytree(saved, target)
            else:
                target.write_bytes(saved.read_bytes())
            fired.append(target)
        return result

    monkeypatch.setattr(release, "_validate_bound_invocation", final_bound)
    try:
        with pytest.raises(release.ReleaseControlError):
            release._release_gate_complete_at(
                context, fd, 0, outputs, identities, completion=completion
            )
        assert fired
        assert not (context.directory / "terminal-commit.json").exists()
        assert not (tmp_path / "retained-original/terminal-commit.json").exists()
    finally:
        os.close(fd)


@pytest.mark.parametrize("owner", ["staged", "journal"])
@pytest.mark.parametrize("boundary", ["after-final-bound", "after-witness-write"])
def test_gate_completion_review_rejects_namespace_drift_at_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str, boundary: str
) -> None:
    context, completion, outputs, identities, fd = _gate_completion_pending(tmp_path, monkeypatch)
    fired = []

    def inject() -> None:
        parent = context.directory / "staged" if owner == "staged" else context.directory
        (parent / "unowned-empty-directory").mkdir()
        fired.append(parent)

    if boundary == "after-final-bound":
        validate = release._validate_bound_invocation

        def bound(value: Any, **kwargs: Any) -> Any:
            result = validate(value, **kwargs)
            if (context.directory / "invocation.json").exists() and not fired:
                inject()
            return result

        monkeypatch.setattr(release, "_validate_bound_invocation", bound)
    else:
        write = release._release_gate_write_json_at

        def writing(directory: int, name: str, value: Any) -> Any:
            result = write(directory, name, value)
            if name == "terminal-commit.json" and not fired:
                inject()
            return result

        monkeypatch.setattr(release, "_release_gate_write_json_at", writing)
    try:
        with pytest.raises(release.ReleaseControlError, match="namespace"):
            release._release_gate_complete_at(
                context, fd, 0, outputs, identities, completion=completion
            )
        assert fired
        assert (context.directory / "terminal-commit.json").exists() == (
            boundary == "after-witness-write"
        )
        # An already-created finite prefix witness is retained on later failure.
        # Current full journal replay must still enforce its exact namespace.
    finally:
        os.close(fd)


def _gate_reader_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    c, e, refs, ids, fd = _gate_completion_pending(tmp_path, monkeypatch)
    try:
        release._release_gate_complete_at(c, fd, 0, refs, ids, completion=e)
    finally:
        os.close(fd)
    record = json.loads((c.root / "gate-input.json").read_bytes())
    return (c, record)


@pytest.mark.parametrize("reader", ["held", "generic", "public", "catalog-public"])
def test_gate_reader_complete_original_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: Any
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    if reader == "held":
        assert release._validate_terminal(c)["status"] == "PASS"
    elif reader == "generic":
        assert (
            release._validate_terminal(release.ReleaseInvocation(c.directory, c.root, c.intent))[
                "status"
            ]
            == "PASS"
        )
    else:
        path = c.root / (
            "scenario-catalog.json" if reader == "catalog-public" else "gate-input.json"
        )
        record = json.loads(path.read_bytes())
        release.validate_release_producer_journal(
            record, path, producer="prepare_release_gate_input.py"
        )


def test_gate_reader_relocation_has_no_old_root_or_checkout_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    new = c.root.with_name("relocated")
    c.root.rename(new)
    repository = c.gate_inputs.repository
    repository.rename(repository.with_name("old-source-unavailable"))
    assert not c.root.exists() and (not repository.exists())
    current = release.ReleaseInvocation(new / c.directory.relative_to(c.root), new, c.intent)
    assert release._validate_terminal(current)["status"] == "PASS"
    release.validate_release_producer_journal(
        record, new / "gate-input.json", producer="prepare_release_gate_input.py"
    )


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("when", ["before-entry", "after-entry"])
@pytest.mark.parametrize("member", ["root", "journal", "intent", "terminal", "witness", "output"])
def test_gate_reader_original_reader_rejects_substitution_before_foreign_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public: Any, when: Any, member: Any
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    entry = release._validate_terminal_entry
    read = release.os.read
    foreign = set()
    reads = []
    injected = []
    target = {
        "root": c.root,
        "journal": c.directory,
        "intent": c.directory / "intent.json",
        "terminal": c.directory / "invocation.json",
        "witness": c.directory / "terminal-commit.json",
        "output": c.root / "gate-input.json",
    }[member]

    def replace() -> Any:
        saved = tmp_path / "saved-original-member"
        target.rename(saved)
        if saved.is_dir():
            shutil.copytree(saved, target)
        else:
            target.write_bytes(saved.read_bytes())
        values = list(target.rglob("*")) if target.is_dir() else [target]
        for path in values:
            if path.is_file():
                st = path.stat()
                foreign.add((st.st_dev, st.st_ino))
        injected.append(member)

    def validate(ctx: Any, **kwargs: Any) -> Any:
        if when == "before-entry" and (not injected):
            replace()
        value = entry(ctx, **kwargs)
        if when == "after-entry" and (not injected):
            replace()
        return value

    def reading(fd: Any, n: Any) -> Any:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) in foreign:
            reads.append(fd)
        return read(fd, n)

    monkeypatch.setattr(release, "_validate_terminal_entry", validate)
    monkeypatch.setattr(release.os, "read", reading)
    with pytest.raises(release.ReleaseControlError):
        if public:
            release.validate_release_producer_journal(
                record, c.root / "gate-input.json", producer="prepare_release_gate_input.py"
            )
        else:
            release._validate_terminal(c)
    assert injected and (not reads)


@pytest.mark.parametrize("member", ["root", "output", "witness"])
def test_gate_reader_public_retains_capture_through_final_output_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: Any
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    validate = release._validate_terminal
    read = release.os.read
    foreign = set()
    reads = []
    injected = []
    target = (
        c.root
        if member == "root"
        else c.root / "gate-input.json"
        if member == "output"
        else c.directory / "terminal-commit.json"
    )

    def terminal(ctx: Any, **kwargs: Any) -> Any:
        value = validate(ctx, **kwargs)
        saved = tmp_path / "saved-before-membership"
        target.rename(saved)
        if saved.is_dir():
            shutil.copytree(saved, target)
        else:
            target.write_bytes(saved.read_bytes())
        for path in list(target.rglob("*")) if target.is_dir() else [target]:
            if path.is_file():
                st = path.stat()
                foreign.add((st.st_dev, st.st_ino))
        injected.append(member)
        return value

    def reading(fd: Any, n: Any) -> Any:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) in foreign:
            reads.append(fd)
        return read(fd, n)

    monkeypatch.setattr(release, "_validate_terminal", terminal)
    monkeypatch.setattr(release.os, "read", reading)
    with pytest.raises(release.ReleaseControlError):
        release.validate_release_producer_journal(
            record, c.root / "gate-input.json", producer="prepare_release_gate_input.py"
        )
    assert injected and (not reads)


@pytest.mark.parametrize("code", [3, 137])
@pytest.mark.parametrize("partial", [False, True])
def test_gate_reader_negative_gate_preserves_failed_input_and_partial_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: Any, partial: Any
) -> None:
    (tmp_path / "run").mkdir()
    c, _ = _gate_input_plan_fixture(tmp_path / "run", monkeypatch)
    for name in ("stdout", "stderr"):
        (c.directory / name).write_bytes(name.encode())
    if partial:
        (c.directory / "staged").mkdir()
        (c.directory / "staged/partial.bin").write_bytes(b"retained partial")
        (c.directory / "workspace").mkdir()
        (c.directory / "workspace/unsafe").symlink_to("missing")
    release._retain_partial_files(c)
    release._complete_invocation(c, code, [])
    path = c.root / c.gate_inputs.captured.rows[0][0]
    path.write_bytes(path.read_bytes() + b"modified failed original input")
    result = release._validate_terminal(c)
    assert result["status"] == ("BLOCKED" if code == 3 else "CANCELLED")
    assert not (c.directory / "terminal-commit.json").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-witness",
        "wrong-witness",
        "duplicate-witness",
        "extra-stage-directory",
        "caller-record-rewrite",
    ],
)
def test_gate_reader_common_public_reader_closed_negative_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    witness = c.directory / "terminal-commit.json"
    if mutation == "missing-witness":
        witness.unlink()
    elif mutation == "wrong-witness":
        witness.chmod(384)
        witness.write_bytes(b"{}")
    elif mutation == "duplicate-witness":
        (c.directory / "witness-copy.json").write_bytes(witness.read_bytes())
    elif mutation == "extra-stage-directory":
        (c.directory / "staged/unknown").mkdir()
    else:
        record["data"]["gate_input_digest"] = "0" * 64
    with pytest.raises(release.ReleaseControlError):
        release.validate_release_producer_journal(
            record, c.root / "gate-input.json", producer="prepare_release_gate_input.py"
        )


def test_gate_reader_wrong_carrier_and_non_gate_optional_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _ = _gate_reader_completed(tmp_path, monkeypatch)
    carrier = release._release_gate_journal_readback_capture(c)
    changed = dataclasses.replace(c, intent={**c.intent, "tool": "validate_release_gate_input.py"})
    with pytest.raises(release.ReleaseControlError):
        release._validate_terminal(changed, _gate_readback=carrier)


@pytest.mark.parametrize(
    "mutation", [None, "prior-stderr", "interrupted-terminal", "interrupted-witness"]
)
def test_gate_reader_negative_interrupted_lineage_uses_original_complete_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    (tmp_path / "run").mkdir()
    first, _ = _gate_input_plan_fixture(tmp_path / "run", monkeypatch)

    def finish(c: Any) -> Any:
        for name in ("stdout", "stderr"):
            (c.directory / name).write_bytes(b"original diagnostic")
        release._retain_partial_files(c)
        release._complete_invocation(c, 3, [])

    def next_context(c: Any) -> Any:
        directory = c.directory.with_name(f"{c.intent['sequence'] + 1:03d}")
        argv = list(c.intent["argv"])
        argv[argv.index("--invocation-dir") + 1] = str(directory)
        held = release._release_gate_prepare_inputs(argv[1:], directory)
        return release.begin_release_invocation(
            argv[0],
            argv[1:],
            directory,
            input_paths=[
                (c.root / name, "metriplane." + kind + ".v1")
                for name, kind, _, _, _ in held.captured.rows
            ],
            planned_outputs=[
                (c.root / name, kind) for name, kind in release._RELEASE_GATE_OUTPUT_PLAN
            ],
            _gate_inputs=held,
        )

    finish(first)
    second = next_context(first)
    third = next_context(second)
    finish(third)
    if mutation == "prior-stderr":
        (first.directory / "stderr").write_bytes(b"changed prior diagnostic")
    elif mutation == "interrupted-terminal":
        finish(second)
    elif mutation == "interrupted-witness":
        (second.directory / "terminal-commit.json").symlink_to("missing")
    if mutation is None:
        assert release._validate_terminal(third)["status"] == "BLOCKED"
    else:
        with pytest.raises(release.ReleaseControlError):
            release._validate_terminal(third)


def test_gate_reader_genuine_unreadable_negative_partial_retains_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "run").mkdir()
    c, _ = _gate_input_plan_fixture(tmp_path / "run", monkeypatch)
    for name in ("stdout", "stderr"):
        (c.directory / name).write_bytes(b"")
    (c.directory / "staged").mkdir()
    (c.directory / "staged/unreadable-file").write_bytes(b"retained inaccessible original")
    opening = release.os.open

    def unreadable(path: Any, flags: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(path).name == "unreadable-file" and flags & os.O_ACCMODE == os.O_RDONLY:
            raise PermissionError("controlled original unreadable partial")
        return opening(path, flags, *args, **kwargs)

    monkeypatch.setattr(release.os, "open", unreadable)
    release._retain_partial_files(c)
    release._complete_invocation(c, 3, [])
    assert release._validate_terminal(c)["status"] == "BLOCKED"


@pytest.mark.parametrize("boundary", ["intent-discovery", "reader-handoff"])
@pytest.mark.parametrize("member", ["root", "journal", "intent", "output", "other-output"])
def test_gate_reader_public_earliest_original_capture_rejects_before_foreign_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: Any, member: Any
) -> None:
    c, record = _gate_reader_completed(tmp_path, monkeypatch)
    validating = release._validate_intent_bytes
    capturing = release._release_gate_journal_readback_capture
    reading = release.os.read
    foreign = set()
    reads = []
    injected = []
    target = {
        "root": c.root,
        "journal": c.directory,
        "intent": c.directory / "intent.json",
        "output": c.root / "gate-input.json",
        "other-output": c.root / "scenario-catalog.json",
    }[member]

    def replace() -> Any:
        saved = tmp_path / "earliest-original"
        target.rename(saved)
        if saved.is_dir():
            shutil.copytree(saved, target)
        else:
            target.write_bytes(saved.read_bytes())
        for path in list(target.rglob("*")) if target.is_dir() else [target]:
            if path.is_file():
                st = path.stat()
                foreign.add((st.st_dev, st.st_ino))
        injected.append(member)

    def validate(directory: Any, raw: Any) -> Any:
        value = validating(directory, raw)
        if not injected and boundary == "intent-discovery":
            replace()
        return value

    def capture(context: Any, **kwargs: Any) -> Any:
        if not injected and boundary == "reader-handoff":
            replace()
        return capturing(context, **kwargs)

    def read(fd: Any, count: Any) -> Any:
        st = os.fstat(fd)
        if (st.st_dev, st.st_ino) in foreign:
            reads.append(fd)
        return reading(fd, count)

    monkeypatch.setattr(release, "_validate_intent_bytes", validate)
    monkeypatch.setattr(release, "_release_gate_journal_readback_capture", capture)
    monkeypatch.setattr(release.os, "read", read)
    with pytest.raises(release.ReleaseControlError):
        release.validate_release_producer_journal(
            record, c.root / "gate-input.json", producer="prepare_release_gate_input.py"
        )
    assert injected and (not reads)


_GRAPH_RECOVERY_NEW_FLAGS = frozenset(
    {
        "role-assignments",
        "release-context",
        "signed-recovery-authorization",
        "recovery-operation-id",
        "recovery-sequence",
        "provider-attestation-keyring",
        "provider-attestation-keyring-digest",
        "authority-policy-digest",
    }
)


def _graph_write(path: Any, raw: Any) -> Any:
    if path.exists():
        os.chmod(path, 384)
    path.write_bytes(raw)


def _graph_compose_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any = None, relative: Any = False
) -> Any:
    original, native, plan = _fixture_native_preflight_fixture(
        tmp_path, monkeypatch, relative=relative
    )
    native["captured"].revalidate()
    record_path = original.root / "preflight.json"

    def ref(p: Any) -> Any:
        return {
            "path": p.relative_to(record_path.parent).as_posix(),
            "bytes": len(p.read_bytes()),
            "sha256": release.sha256_bytes(p.read_bytes()),
        }

    data = {
        "producer_intent_digest": release.sha256_json(original.intent),
        "invocation_root_locator": "invocations",
        "backends": [],
        "independence_verified": True,
        "mode": "isolated_preflight",
        "production_heads_mutated": False,
        "original_registry": ref(original.root / "inputs/stores.json"),
        "registry_digest": native["selection"]["registry_digest"],
        "scope": "fixture-run",
    }
    for row in plan:
        request = row["request"]["arguments"]
        data["backends"].append(
            {
                "backend_id": request["backend_id"],
                "backend_binding_digest": request["binding_digest"],
                "capabilities_tested": request["capabilities"],
                "create_digest": release.sha256_json(request["challenge"]),
                "read_back_digest": release.sha256_json(request["challenge"]),
                "namespace": request["namespace"],
                "operation_id": release.sha256_json(row["request"]),
                "result": "PASS",
                "native_proof_files": [
                    ref(original.root / row["paths"][field]) for field in ("receipt",)
                ],
            }
        )
    if mutation:
        mutation(data)
    record = release.make_record(
        "release-evidence-store-preflight",
        data,
        invocation_id=original.intent["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    _graph_write(record_path, release.canonical_json(record))
    terminal_path = original.directory / "invocation.json"
    terminal = json.loads(terminal_path.read_bytes())
    output_rows = terminal["data"]["outputs"]
    next((row for row in output_rows if row["path"] == "preflight.json"))["sha256"] = (
        release.sha256_bytes(record_path.read_bytes())
    )
    terminal["data"]["invocation_digest"] = release.sha256_json(
        {k: v for k, v in terminal["data"].items() if k != "invocation_digest"}
    )
    terminal = release.make_record(
        "release-stage-invocation",
        terminal["data"],
        invocation_id=original.intent["invocation_id"],
        sequence=1,
        synthetic=True,
    )
    _graph_write(terminal_path, release.canonical_json(terminal))
    _graph_write(
        terminal_path.parent / "terminal-commit.json",
        release.canonical_json(
            {
                "schema_version": "metriplane.gate-terminal-commit.v1",
                "intent_sha256": release.sha256_json(original.intent),
                "terminal_sha256": release.sha256_json(terminal),
            }
        ),
    )
    _graph_write(original.directory / "worker.pid", release.canonical_json({"pid": os.getpid()}))
    _graph_write(
        original.directory / "worker-result.json",
        release.canonical_json(
            {
                "schema_version": "metriplane.release-worker-result.v1",
                "exit_code": 0,
                "outputs": output_rows,
                "producer_intent_digest": release.sha256_json(original.intent),
            }
        ),
    )
    for row in output_rows:
        dest = original.directory / "staged" / row["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((original.root / row["path"]).read_bytes())
    names = sorted(
        (
            path.relative_to(tmp_path).as_posix()
            for path in original.root.rglob("*")
            if path.is_file()
        )
    )
    originals = [
        {
            "path": name,
            "bytes": (tmp_path / name).stat().st_size,
            "sha256": release.sha256_bytes((tmp_path / name).read_bytes()),
        }
        for name in names
    ]
    lookup = {row["path"]: row for row in originals}
    prefix = original.root.relative_to(tmp_path).as_posix()
    primary = prefix + "/preflight.json"
    journal = prefix + "/invocations/validate-release-evidence-stores/001/"
    bundle = {
        "schema_version": "metriplane.release-prerequisite-proofs.v1",
        "release_context_digest": "a" * 64,
        "captured_original_files": originals,
        "proofs": [
            {
                "producer": "validate_release_evidence_stores.py",
                "stage": "validate-release-evidence-stores",
                "record_type": "release-evidence-store-preflight",
                "record_kind": None,
                "record": lookup[primary],
                "record_digest": release.sha256_json(record),
                "original_run_root": prefix,
                "producer_intent": lookup[journal + "intent.json"],
                "producer_terminal": lookup[journal + "invocation.json"],
                "companion_validations": [],
            }
        ],
    }
    (tmp_path / "bundle.json").write_bytes(release.canonical_json(bundle))
    captured = release._ReleaseCapturedFiles.capture(
        tmp_path,
        [
            ("bundle.json", "prerequisite-proofs"),
            *((name, "prerequisite-original") for name in names),
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-proofs", "prerequisite-original"}),
    )
    kwargs = {
        "captured": captured,
        "expected_context_digest": "a" * 64,
        "before": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "live": False,
        "selections": {
            primary: {
                "inputs": native["expected_inputs"],
                "auxiliary": {},
                "selectors": native["selection"],
                "proof_refs": native["proof_refs"],
                "dependencies": {},
            }
        },
    }
    return (tmp_path / "bundle.json", kwargs, record, plan)


@pytest.mark.parametrize("relative", [False, True])
def test_graph_complete_preflight_graph_real_original_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: Any
) -> None:
    path, kwargs, record, plan = _graph_compose_fixture(tmp_path, monkeypatch, relative=relative)
    result = release._release_prerequisite_graph_replay(path, **kwargs)
    assert len(result.nodes) == 1 and result.nodes[0].original_record == release.canonical_json(
        record
    )
    assert len(result.nodes[0].native_facts.operations) == 7
    assert len(result.nodes[0].native_facts.raw_inventory) == 21
    assert not hasattr(result, "verified") and (not hasattr(result, "approved"))
    assert kwargs["captured"] is result.captured
    (tmp_path / "schema-primary.json").write_bytes(release.canonical_json(record))


@pytest.mark.parametrize(
    "field",
    ["scope", "registry_digest", "mode", "independence_verified", "production_heads_mutated"],
)
def test_graph_coherent_primary_top_field_rewrite_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: Any
) -> None:

    def mutate(data: Any) -> Any:
        data[field] = not data[field] if type(data[field]) is bool else "e" * 64

    path, kwargs, _, _ = _graph_compose_fixture(tmp_path, monkeypatch, mutation=mutate)
    with pytest.raises(release.ReleaseControlError, match="complete original semantic"):
        release._release_prerequisite_graph_replay(path, **kwargs)


@pytest.mark.parametrize(
    "field",
    [
        "backend_id",
        "backend_binding_digest",
        "capabilities_tested",
        "create_digest",
        "read_back_digest",
        "namespace",
        "operation_id",
        "result",
        "native_proof_files",
    ],
)
def test_graph_coherent_primary_backend_field_rewrite_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: Any
) -> None:

    def mutate(data: Any) -> Any:
        row = data["backends"][0]
        row[field] = [] if isinstance(row[field], list) else "e" * 64

    path, kwargs, _, _ = _graph_compose_fixture(tmp_path, monkeypatch, mutation=mutate)
    with pytest.raises(release.ReleaseControlError, match="complete original semantic"):
        release._release_prerequisite_graph_replay(path, **kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-selector",
        "missing-selector",
        "cycle",
        "unknown-dependency",
        "duplicate-dependency",
        "wrong-type",
        "wrong-R",
        "external-suffix",
        "extra-native-flag",
    ],
)
def test_graph_graph_selection_and_dependency_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    path, kwargs, _, _ = _graph_compose_fixture(tmp_path, monkeypatch)
    primary = next(iter(kwargs["selections"]))
    selected = kwargs["selections"][primary]
    if mutation == "extra-selector":
        selected["approved"] = True
    elif mutation == "missing-selector":
        del selected["proof_refs"]
    elif mutation == "cycle":
        selected["dependencies"] = {"self": primary}
    elif mutation == "unknown-dependency":
        selected["dependencies"] = {"unknown": "elsewhere.json"}
    elif mutation == "duplicate-dependency":
        selected["dependencies"] = {"one": primary, "two": primary}
    elif mutation == "wrong-type":
        selected["inputs"]["stores"][0]["schema_id"] = "application/json"
    elif mutation == "wrong-R":
        selected["inputs"]["stores"][0]["sha256"] = "e" * 64
    elif mutation == "external-suffix":
        selected["inputs"]["stores"][0]["path"] = "../outside.json"
    elif mutation == "extra-native-flag":
        selected["selectors"]["approved"] = True
    with pytest.raises(release.ReleaseControlError):
        release._release_prerequisite_graph_replay(path, **kwargs)


@pytest.mark.parametrize("live", [True, 0, 1, None, "False"])
def test_graph_live_and_mode_aliases_reject_before_io(live: Any) -> None:

    class NoRead:
        @property
        def root(self: Any) -> Any:
            raise AssertionError("must not read capture")

    with pytest.raises(release.ReleaseControlError, match="inaccessible to live"):
        release._release_prerequisite_graph_replay(
            Path("/never-read"),
            captured=NoRead(),
            expected_context_digest="a" * 64,
            before="",
            selections={},
            live=live,
        )


def test_graph_exact_closed_13_type_dispatch_inventory() -> None:
    assert len(release._RELEASE_GATE_PREREQUISITES) == 13
    assert len(release._RELEASE_GRAPH_NATIVE_TOOLS) == 8
    assert set(release._RELEASE_GATE_PREREQUISITES) - release._RELEASE_GRAPH_NATIVE_TOOLS == {
        "resolve_release_target.py",
        "record_release_target_burn.py",
        "build_release_evidence_manifest.py",
        "record_release_staging_attempt.py",
        "record_release_index_recovery.py",
    }


def _graph_recovery_content_fixture() -> Any:
    data, kw = _index_export_fixture(2)
    files = kw["original_files"]
    first, second = data["entries"]

    def get(row: Any) -> Any:
        return json.loads(files[row["original_file"]["path"]])

    original = get(first["original_receipt"])
    failure = get(second["original_receipt"])
    manifest = get(second["original_manifest"])
    retention = get(second["original_retention"])
    keyring = "a" * 64
    context = "c" * 64
    policy = release.release_authority_policy_digest(keyring)
    role_data = {
        "author_id": "fixture-author",
        "author_provider": "github",
        "authorized_executor_id": "fixture-operator",
        "non_author_reviewer_id": "fixture-reviewer",
        "publisher_id": "fixture-publisher",
        "task_id": "MP2-007",
        "milestone": "v0.4",
        "run_id": "fixture-run",
        "valid_from": "2026-09-08T00:00:00Z",
        "valid_until": "2026-09-10T00:00:00Z",
        "authority_policy_digest": policy,
        "provider_attestation_keyring_digest": keyring,
        "release_context_digest": context,
        "signing_method": "provider-attestation-v1",
        "independent_assurance": {"applicability": "not_applicable"},
    }
    for key, actor, role in [
        ("operator", "fixture-operator", "release_operator"),
        ("non_author_reviewer", "fixture-reviewer", "non_author_reviewer"),
        ("infrastructure_owner", "fixture-infrastructure", "infrastructure_owner"),
        ("publisher", "fixture-publisher", "publisher"),
    ]:
        role_data[key] = {
            "actor_id": actor,
            "backup_actor_id": actor + "-backup",
            "provider": "github",
            "role": role,
            "conflict_free": True,
            "provenance_digest": "b" * 64,
        }
    role_data.update(
        kind="recorded_assignments",
        original_protected_input={"path": "roles-original.json", "bytes": 1, "sha256": "d" * 64},
        original_protected_input_digest="e" * 64,
        producer_intent_digest="f" * 64,
        invocation_root_locator="invocations",
    )
    roles = release.make_record(
        "release-role-assignments",
        role_data,
        invocation_id="fixture-roles",
        sequence=1,
        synthetic=True,
    )
    entry = release._release_index_receipt_content(original["data"])
    plan = {
        "schema_version": "metriplane.release-index-recovery-plan.v1",
        "release_context_digest": context,
        "scope_kind": entry["scope"]["kind"],
        "scope_id": entry["scope"]["scope_id"],
        "index_backend_id": "attempt-index",
        "genesis_digest": entry["genesis_digest"],
        "original_receipt_digest": release.sha256_json(original),
        "failure_envelope_manifest_digest": release.sha256_json(manifest),
        "failure_envelope_receipts_digest": release.sha256_json(retention),
        "failure_entry_receipt_digest": release.sha256_json(failure),
        "recovery_operation_id": "owner-planned-recovery",
        "recovery_sequence": 19,
    }
    auth_data = {
        "authority_policy_digest": policy,
        "authorized_role": "infrastructure_owner",
        "conflicts": [],
        "decision": "AUTHORIZE_COMMITTED_INDEX_RECOVERY",
        "expires_at": "2026-09-10T00:00:00Z",
        "input_kind": "index_recovery",
        "issued_at": "2026-09-08T00:00:00Z",
        "provider_event": None,
        "signer_identity": "fixture-infrastructure",
        "signing_method": "provider-attestation-v1",
        "subject_digests": [
            {"subject": "recovery_plan", "sha256": release.sha256_json(plan)},
            {"subject": "role_assignments", "sha256": release.sha256_json(roles)},
        ],
    }
    authorization = release.make_record(
        "release-protected-input",
        auth_data,
        invocation_id="fixture-authorization",
        sequence=1,
        synthetic=True,
    )
    actor = "fixture-infrastructure"
    subject = release.signature_subject_digest(authorization)
    authorization["signatures"] = [
        {
            "actor_id": actor,
            "algorithm": "test-sha256-v1",
            "provider": "test-fixture",
            "subject_digest": subject,
            "synthetic": True,
            "signature": release.sha256_json({"actor_id": actor, "subject_digest": subject}),
        }
    ]
    authorization = release.make_record(
        "release-protected-input",
        auth_data,
        invocation_id="fixture-authorization",
        sequence=1,
        synthetic=True,
        signatures=authorization["signatures"],
    )
    return {
        "original_receipt": original,
        "failure_manifest": manifest,
        "failure_retention": retention,
        "failure_receipt": failure,
        "authorization": authorization,
        "roles": roles,
        "expected_context_digest": context,
        "expected_authority_policy_digest": policy,
        "planned_operation_id": "owner-planned-recovery",
        "planned_sequence": 19,
        "producer_intent_digest": "1" * 64,
        "use_interval": ("2026-09-09T00:00:00Z", "2026-09-09T00:00:01Z"),
    }


def test_graph_committed_recovery_plan_is_acyclic_and_counters_stay_distinct(
    tmp_path: Path,
) -> None:
    args = _graph_recovery_content_fixture()
    data = release._release_recovery_committed_data(**args)
    assert data["recovery_sequence"] == 19
    assert data["recovery_sequence"] != args["failure_receipt"]["sequence"]
    assert data["recovery_sequence"] != args["failure_receipt"]["data"]["generation"]
    assert data["authorization_digest"] == release.sha256_json(args["authorization"])
    assert data["original_entry_digest"] == release.sha256_json(
        release._release_index_receipt_content(args["original_receipt"]["data"])
    )
    assert data["live_absence_proof_digest"] is None
    record = release.make_record(
        "release-index-recovery", data, invocation_id="fixture-recovery", sequence=3, synthetic=True
    )
    (tmp_path / "schema-recovery.json").write_bytes(release.canonical_json(record))
    (tmp_path / "schema-recovery-authorization.json").write_bytes(
        release.canonical_json(args["authorization"])
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "operation",
        "sequence",
        "boolean-sequence",
        "context",
        "policy",
        "missing-signature",
        "wrong-signer",
        "expired",
        "reverse-clock",
        "roles",
        "original-entry",
        "failure-entry",
        "abandonment-kind",
        "future-subject",
        "extra-subject",
    ],
)
def test_graph_committed_recovery_original_authorization_cannot_be_echoed_or_rebound(
    mutation: Any,
) -> None:
    args = _graph_recovery_content_fixture()
    if mutation == "operation":
        args["planned_operation_id"] = "another-owner-operation"
    elif mutation == "sequence":
        args["planned_sequence"] = 20
    elif mutation == "boolean-sequence":
        args["planned_sequence"] = True
    elif mutation == "context":
        args["expected_context_digest"] = "d" * 64
    elif mutation == "policy":
        args["expected_authority_policy_digest"] = "d" * 64
    elif mutation == "missing-signature":
        args["authorization"]["signatures"] = []
    elif mutation == "wrong-signer":
        args["authorization"]["signatures"][0]["actor_id"] = "not-assigned"
    elif mutation == "expired":
        args["use_interval"] = ("2026-09-10T00:00:00Z", "2026-09-10T00:00:01Z")
    elif mutation == "reverse-clock":
        args["use_interval"] = ("2026-09-09T00:00:02Z", "2026-09-09T00:00:01Z")
    elif mutation == "roles":
        args["roles"]["data"]["infrastructure_owner"]["actor_id"] = "not-assigned"
    elif mutation == "original-entry":
        args["original_receipt"] = copy.deepcopy(args["failure_receipt"])
    elif mutation == "failure-entry":
        args["failure_receipt"] = copy.deepcopy(args["original_receipt"])
    elif mutation == "abandonment-kind":
        args["authorization"]["data"]["input_kind"] = "index_abandonment"
    elif mutation == "future-subject":
        args["authorization"]["data"]["subject_digests"][0] = {
            "subject": "future_recovery_record",
            "sha256": "f" * 64,
        }
    elif mutation == "extra-subject":
        args["authorization"]["data"]["subject_digests"].append(
            {"subject": "unrelated", "sha256": "e" * 64}
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_recovery_committed_data(**args)


def _graph_recovery_argv(form_number: Any, *, omit: Any = frozenset()) -> Any:
    tool = "record_release_index_recovery.py"
    contract = release.TOOL_CONTRACTS[tool]
    form = contract.forms[form_number]
    equals = dict(form.equals)
    argv = [tool]
    for key in sorted(form.required - omit):
        argv.append("--" + key)
        if key in contract.boolean:
            continue
        argv.append(
            sorted(equals[key])[0]
            if key in equals
            else contract.choices[key][0]
            if key in contract.choices
            else "19"
            if key in contract.integer
            else "original-fixture-value"
        )
    return argv


@pytest.mark.parametrize("form", range(6))
def test_graph_all_six_recovery_legacy_forms_fail_closed(form: Any) -> None:
    with pytest.raises(release.ReleaseControlError, match="exactly one complete command form"):
        release._release_original_arguments(
            "record_release_index_recovery.py",
            _graph_recovery_argv(form, omit=_GRAPH_RECOVERY_NEW_FLAGS),
        )
    values = release._release_original_arguments(
        "record_release_index_recovery.py", _graph_recovery_argv(form)
    )
    assert values["recovery-sequence"] == 19
    assert release._release_graph_positive_integer(values["recovery-sequence"], "recovery") == 19


@pytest.mark.parametrize("form", range(6))
@pytest.mark.parametrize("flag", sorted(_GRAPH_RECOVERY_NEW_FLAGS))
def test_graph_each_recovery_original_plan_and_authority_flag_mandatory(
    form: Any, flag: Any
) -> None:
    with pytest.raises(release.ReleaseControlError, match="exactly one complete command form"):
        release._release_original_arguments(
            "record_release_index_recovery.py", _graph_recovery_argv(form, omit={flag})
        )


@pytest.mark.parametrize("value", [True, False, 0, -1, "19", None, 19.0])
def test_graph_recovery_logical_sequence_has_one_typed_meaning(value: Any) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_graph_positive_integer(value, "recovery")


@pytest.mark.parametrize("references", [None, [], "captured", True, 1])
def test_graph_invalid_auxiliary_shape_rejects_before_original_or_io(references: Any) -> None:
    with pytest.raises(
        release.ReleaseControlError, match="auxiliary references must be a closed mapping"
    ):
        release._release_graph_auxiliary(None, captured=None, references=references)


def _failed_index_record(kind: Any, data: Any) -> Any:
    return release.make_record(
        kind, data, invocation_id="synthetic-original", sequence=1, synthetic=True
    )


def _failed_index_build_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: Any, *, command_mutation: Any = None
) -> Any:
    monkeypatch.setenv("METRIPLANE_RELEASE_FIXTURE_MODE", "1")
    root = tmp_path / "synthetic-run"
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    original = _graph_recovery_content_fixture()
    manifest = original["failure_manifest"]
    retention = original["failure_retention"]
    mp = inputs / "manifest.json"
    mp.write_bytes(release.canonical_json(manifest))
    rp = inputs / "retention.json"
    rp.write_bytes(release.canonical_json(retention))
    gp = inputs / "genesis.json"
    gp.write_bytes(_fixture_native_genesis_raw())
    entry = _fixture_native_entry()
    entry.update(
        entry_manifest_digest=release.sha256_json(manifest),
        entry_receipts_digest=release.sha256_json(retention),
    )
    receipt = _failed_index_record("release-attempt-index", _index_receipt_fixture(entry))
    ip = inputs / "receipt.json"
    ip.write_bytes(release.canonical_json(receipt))
    args = _fixture_native_index_args(entry)
    _, operations = release._release_fixture_index_expectations(
        args,
        tool="update_release_attempt_index.py",
        genesis_raw=gp.read_bytes(),
        expected_genesis_digest=entry["genesis_digest"],
        original_entry=entry,
        expected_prior_generation=0,
    )
    request = operations[0]["request"]
    response = {
        "backend_id": "attempt-index",
        "genesis_digest": entry["genesis_digest"],
        "operation_id": entry["operation_id"],
        "expected_head": entry["genesis_digest"],
        "entry": entry,
        "committed_head": release.sha256_json(entry),
        "read_back_digest": release.sha256_json(entry),
        "disposition": "committed",
    }
    assert (
        release._release_fixture_native_response(
            "index.cas", request, release.canonical_json(response)
        )
        == response
    )
    producer = {
        "tool": "update_release_attempt_index.py",
        "invocation_id": receipt["invocation_id"],
        "sequence": receipt["sequence"],
        "intent_digest": receipt["data"]["producer_intent_digest"],
    }
    facts = release._ReleaseFixtureNativeFacts(
        release.canonical_json(producer),
        b"{}",
        (release.canonical_json({"kind": "index.cas", "request": request, "response": response}),),
        (),
        (),
    )
    if stage == "attempt-index-update":
        tool = "update_release_attempt_index.py"
        argv = [
            "--entry-manifest",
            str(mp),
            "--entry-receipts",
            str(rp),
            "--scope-kind",
            "release_staging",
            "--milestone",
            "v0.4",
            "--run-id",
            root.name,
            "--release-tag",
            "v0.4.1",
            "--candidate-id-not-resolved",
            "--stage",
            "target-burn",
            "--sequence",
            "8",
            "--index-backend",
            "attempt-index",
            "--expected-head",
            entry["genesis_digest"],
            "--operation-id",
            entry["operation_id"],
            "--out",
            str(root / "index.json"),
        ]
        members = [
            (mp, "metriplane.release-evidence-manifest.v1"),
            (rp, "metriplane.release-retention-receipts.v1"),
        ]
        outputs = [(root / "index.json", "metriplane.release-attempt-index.v1")]
    else:
        tool = "validate_release_attempt_index.py"
        argv = [
            "--index-backend",
            "attempt-index",
            "--genesis",
            str(gp),
            "--through-receipt",
            str(ip),
            "--read-back",
        ]
        members = [
            (gp, "metriplane.release-fixture-index-genesis.v1"),
            (ip, "metriplane.release-attempt-index.v1"),
        ]
        outputs = []
    directory = root / "invocations" / release._invocation_stage(tool) / "001"
    argv += ["--invocation-dir", str(directory)]
    if command_mutation:
        flag, value = command_mutation
        argv[argv.index("--" + flag) + 1] = value
    failed = release.begin_release_invocation(
        tool, argv, directory, input_paths=members, planned_outputs=outputs
    )
    (directory / "stdout").write_bytes(b"")
    (directory / "stderr").write_bytes(b"synthetic original failed readback\n")
    release._retain_partial_files(failed)
    release._complete_invocation(failed, 3, [])
    terminal = json.loads((directory / "invocation.json").read_bytes())
    envelope = _failed_index_record(
        "release-staging-attempt",
        {
            "available_inputs": failed.intent["inputs"],
            "blockers": ["synthetic content fixture"],
            "disposition": "TERMINAL",
            "failed_invocation_digest": release.sha256_json(terminal),
            "invocation_root_locator": "invocations",
            "milestone": "v0.4",
            "producer_intent_digest": "a" * 64,
            "recovery_envelope_digest": None,
            "result": "BLOCKED",
            "run_id": root.name,
            "sequence": 1,
            "stage": stage,
            "stage_record_digest": None,
        },
    )
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [
            (p.relative_to(root).as_posix(), "prerequisite-original")
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    return (
        failed,
        dict(captured=captured, envelope=envelope, original_receipt=receipt, native_facts=facts),
    )


@pytest.mark.parametrize("stage", ["attempt-index-update", "attempt-index-validation"])
def test_failed_index_actual_negative_operation_content_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: Any
) -> None:
    failed, kw = _failed_index_build_fixture(tmp_path, monkeypatch, stage)
    result = release._release_graph_failed_index_operation(failed, **kw)
    assert result["stage"] == stage
    assert result["original_operation_id"] == "synthetic-operation"
    assert result["failed_intent_digest"] == release.sha256_json(failed.intent)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("operation-id", "unrelated-operation"),
        ("expected-head", "f" * 64),
        ("sequence", "9"),
        ("stage", "index-recovery"),
        ("run-id", "different-run"),
        ("release-tag", "v0.4.2"),
    ],
)
def test_failed_index_consistently_original_failed_command_cannot_name_different_native_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: Any, value: Any
) -> None:
    failed, kw = _failed_index_build_fixture(
        tmp_path, monkeypatch, "attempt-index-update", command_mutation=(flag, value)
    )
    with pytest.raises(
        release.ReleaseControlError, match="failed original update command|failed update changes"
    ):
        release._release_graph_failed_index_operation(failed, **kw)


@pytest.mark.parametrize("stage", ["attempt-index-update", "attempt-index-validation"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("failed_invocation_digest", "d" * 64),
        ("result", "FAIL"),
        ("run_id", "other-run"),
        ("milestone", "v0.5"),
        ("stage", "target-observation"),
        ("recovery_envelope_digest", "e" * 64),
        ("disposition", "RECOVERABLE"),
    ],
)
def test_failed_index_failure_subject_cannot_be_relabelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: Any, field: Any, value: Any
) -> None:
    failed, kw = _failed_index_build_fixture(tmp_path, monkeypatch, stage)
    data = copy.deepcopy(kw["envelope"]["data"])
    data[field] = value
    kw["envelope"] = _failed_index_record("release-staging-attempt", data)
    with pytest.raises(release.ReleaseControlError):
        release._release_graph_failed_index_operation(failed, **kw)


@pytest.mark.parametrize("mutation", ["other-kind", "no-facts", "token", "head", "producer"])
def test_failed_index_reconstructed_native_original_entry_not_receipt_self_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    failed, kw = _failed_index_build_fixture(tmp_path, monkeypatch, "attempt-index-update")
    fact = json.loads(kw["native_facts"].operations[0])
    if mutation == "other-kind":
        fact["kind"] = "index.read"
    if mutation == "token":
        fact["response"]["entry"]["token"] = "foreign-token"
    if mutation == "head":
        fact["request"]["expected_head"] = "c" * 64
    kw["native_facts"] = dataclasses.replace(
        kw["native_facts"],
        operations=() if mutation == "no-facts" else (release.canonical_json(fact),),
    )
    if mutation == "producer":
        producer = json.loads(kw["native_facts"].producer_identity)
        producer["intent_digest"] = "f" * 63 + "0"
        kw["native_facts"] = dataclasses.replace(
            kw["native_facts"], producer_identity=release.canonical_json(producer)
        )
    with pytest.raises(release.ReleaseControlError):
        release._release_graph_failed_index_operation(failed, **kw)


def _staging_namespace_namespace_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    failed, kw = _failed_index_build_fixture(tmp_path, monkeypatch, "attempt-index-update")
    root = failed.root
    envelope = kw["envelope"]
    subject_path = root / "failures/001/staging-attempt.json"
    subject_path.parent.mkdir(parents=True)
    subject_path.write_bytes(release.canonical_json(envelope))
    entry = release._release_index_receipt_content(kw["original_receipt"]["data"])
    scope = copy.deepcopy(entry["scope"])
    scope.update(stage="staging-failure", sequence=9)
    md = {
        "candidate_digest": None,
        "entries": [
            {
                "path": subject_path.relative_to(root).as_posix(),
                "media_type": "application/json",
                "role": "release-staging-attempt",
                "sha256": release.sha256_bytes(subject_path.read_bytes()),
                "size": subject_path.stat().st_size,
            }
        ],
        "invocation_journal_digests": [envelope["data"]["failed_invocation_digest"]],
        "phase": "staging-failure",
        "scope_kind": "release-staging",
        "scope_id": scope["run_id"],
        "producer_intent_digest": "a" * 64,
        "invocation_root_locator": "invocations",
    }
    md["manifest_digest"] = release.sha256_json(
        {k: md[k] for k in ("entries", "invocation_journal_digests")}
    )
    manifest = _failed_index_record("release-evidence-manifest", md)
    mp = subject_path.parent / "evidence-manifest.json"
    mp.write_bytes(release.canonical_json(manifest))
    rd = copy.deepcopy(_graph_recovery_content_fixture()["failure_retention"]["data"])
    rd["phase"] = "staging-failure"
    rd["input_digest"] = release.sha256_bytes(mp.read_bytes())
    for store in rd["stores"]:
        store["content_digest"] = store["read_back_digest"] = rd["input_digest"]
        store["native_proofs"]["read_back"]["sha256"] = rd["input_digest"]
        store["native_proofs"]["read_back"]["bytes"] = mp.stat().st_size
    rd["receipt_set_digest"] = release.sha256_json(rd["stores"])
    retention = _failed_index_record("release-retention-receipts", rd)
    held = release._ReleaseCapturedFiles.capture(
        root,
        [
            (p.relative_to(root).as_posix(), "prerequisite-original")
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ],
        forbidden=[],
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    return dict(
        root=root,
        receipt_path=subject_path.parent / "index.json",
        captured=held,
        manifest_path=mp,
        manifest_raw=mp.read_bytes(),
        manifest=manifest,
        retention=retention,
        subject_path=subject_path,
        subject_record=envelope,
        scope=scope,
        expected_milestone="v0.4",
        expected_release_tag="v0.4.1",
        expected_synthetic=True,
    )


def test_staging_namespace_nested_staging_manifest_uses_original_run_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _staging_namespace_namespace_fixture(tmp_path, monkeypatch)
    release._release_index_update_subject_content(**args)
    assert args["manifest_path"].parent != args["root"]
    assert (
        release._release_index_manifest_entry_root(
            root=args["root"],
            manifest_path=args["manifest_path"],
            manifest=args["manifest"],
            scope=args["scope"],
        )
        == args["root"]
    )
    for name in ("subject_record", "manifest", "retention"):
        (tmp_path / ("schema-" + name + ".json")).write_bytes(release.canonical_json(args[name]))


@pytest.mark.parametrize(
    "mutation",
    [
        "containing-relative",
        "other-run",
        "wrong-phase",
        "future-receipt",
        "wrong-size",
        "wrong-raw",
        "outside-root",
        "other-family",
    ],
)
def test_staging_namespace_staging_manifest_cannot_change_namespace_or_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: Any
) -> None:
    args = _staging_namespace_namespace_fixture(tmp_path, monkeypatch)
    if mutation == "outside-root":
        args["manifest_path"] = args["root"].parent / "foreign.json"
    elif mutation == "other-family":
        args["scope"] = {"kind": "evaluation_staging", "stage": "staging-failure"}
    else:
        md = copy.deepcopy(args["manifest"]["data"])
        if mutation == "containing-relative":
            md["entries"][0]["path"] = "staging-attempt.json"
        if mutation == "other-run":
            md["scope_id"] = "other-run"
        if mutation == "wrong-phase":
            md["phase"] = "target-burn"
        if mutation == "future-receipt":
            md["entries"][0]["path"] = args["receipt_path"].relative_to(args["root"]).as_posix()
        if mutation == "wrong-size":
            md["entries"][0]["size"] += 1
        if mutation == "wrong-raw":
            md["entries"][0]["sha256"] = "a" * 64
        md["manifest_digest"] = release.sha256_json(
            {k: md[k] for k in ("entries", "invocation_journal_digests")}
        )
        args["manifest"] = _failed_index_record("release-evidence-manifest", md)
    with pytest.raises(release.ReleaseControlError):
        release._release_index_update_subject_content(**args)


def _staging_namespace_argv(scope: Any = "release_staging", stage: Any = "staging-failure") -> Any:
    return [
        "update_release_attempt_index.py",
        "--scope-kind",
        scope,
        "--milestone",
        "v0.4",
        "--run-id",
        "run",
        "--entry-manifest",
        "manifest.json",
        "--entry-receipts",
        "receipts.json",
        "--release-tag",
        "v0.4.1",
        "--candidate-id-not-resolved",
        "--stage",
        stage,
        "--sequence",
        "9",
        "--index-backend",
        "attempt-index",
        "--expected-head",
        "a" * 64,
        "--operation-id",
        "failure-operation",
        "--out",
        "index.json",
        "--invocation-dir",
        "/fixture/invocations/update-release-attempt-index/001",
    ]


def test_staging_namespace_exact_new_failure_append_form() -> None:
    args = release._release_original_arguments(
        "update_release_attempt_index.py", _staging_namespace_argv()
    )
    assert args["scope-kind"] == "release_staging" and args["stage"] == "staging-failure"


@pytest.mark.parametrize(
    "scope,stage",
    [
        ("evaluation_staging", "staging-failure"),
        ("release_candidate", "staging-failure"),
        ("release_staging", "arbitrary-failure"),
        ("release_staging", "attempt-index-update"),
        ("release_staging", "attempt-index-validation"),
    ],
)
def test_staging_namespace_new_stage_does_not_widen_other_families(scope: Any, stage: Any) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_original_arguments(
            "update_release_attempt_index.py", _staging_namespace_argv(scope, stage)
        )


def test_failed_index_staging_append_reaches_original_native_input_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, kw = _failed_index_build_fixture(
        tmp_path,
        monkeypatch,
        "attempt-index-update",
        command_mutation=("stage", "staging-failure"),
    )
    arguments = release._release_original_arguments(
        original.intent["tool"], original.intent["argv"]
    )
    expected = {}
    for flag in ("entry-manifest", "entry-receipts"):
        path = Path(arguments[flag])
        row = next(row for row in original.intent["inputs"] if row["path"] == str(path))
        expected[flag] = [{**row, "path": path.relative_to(original.root).as_posix()}]
    actual, inputs = release._release_fixture_native_original_inputs(
        original,
        captured=kw["captured"],
        expected_inputs=expected,
    )
    assert actual["stage"] == "staging-failure"
    assert set(inputs) == {"entry-manifest", "entry-receipts"}
    assert all(
        values[0][1] == Path(arguments[flag]).read_bytes() for flag, values in inputs.items()
    )


def _failed_index_connected_manifest_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, unrelated: bool = False
) -> Any:
    failed, prior = _failed_index_build_fixture(tmp_path, monkeypatch, "attempt-index-update")
    root = failed.root
    staging_directory = root / "invocations/record-release-staging-attempt/001"
    staging = release.begin_release_invocation(
        "record_release_staging_attempt.py",
        [
            "--work-dir",
            str(root / "work"),
            "--stage",
            "attempt-index-update",
            "--failed-invocation-dir",
            str(failed.directory),
            "--out",
            str(root / "failure-envelope.json"),
            "--invocation-dir",
            str(staging_directory),
        ],
        staging_directory,
        input_paths=[(failed.directory / "intent.json", "metriplane.release-invocation-intent.v1")],
        planned_outputs=[(root / "failure-envelope.json", "metriplane.release-staging-attempt.v1")],
    )
    envelope_data = copy.deepcopy(prior["envelope"]["data"])
    envelope_data["producer_intent_digest"] = release.sha256_json(staging.intent)
    envelope = release.make_record(
        "release-staging-attempt",
        envelope_data,
        invocation_id=staging.intent["invocation_id"],
        sequence=staging.intent["sequence"],
        synthetic=True,
    )
    envelope_path = root / "failure-envelope.json"
    envelope_path.write_bytes(release.canonical_json(envelope))
    selected_path = envelope_path
    if unrelated:
        unrelated_record = release.make_record(
            "release-staging-attempt",
            {**envelope_data, "failed_invocation_digest": "e" * 64},
            invocation_id="fixture-unrelated-envelope",
            sequence=2,
            synthetic=True,
        )
        selected_path = root / "later-unrelated-envelope.json"
        selected_path.write_bytes(release.canonical_json(unrelated_record))
    manifest_path = root / "failures/001/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_data = _manifest_content_fixture()
    manifest_data.update(
        candidate_digest=None,
        phase="staging-failure",
        scope_id=root.name,
        scope_kind="release-staging",
        entries=[
            {
                "path": "failure-envelope.json",
                "media_type": "application/json",
                "role": "original-output",
                "size": len(envelope_path.read_bytes()),
                "sha256": release.sha256_bytes(envelope_path.read_bytes()),
            }
        ],
    )
    manifest_data["manifest_digest"] = release.sha256_json(
        {key: manifest_data[key] for key in ("entries", "invocation_journal_digests")}
    )
    manifest = release.make_record(
        "release-evidence-manifest",
        manifest_data,
        invocation_id="fixture-failure-manifest",
        sequence=1,
        synthetic=True,
    )
    manifest_path.write_bytes(release.canonical_json(manifest))
    manifest_directory = root / "invocations/build-release-evidence-manifest/001"
    manifest_original = release.begin_release_invocation(
        "build_release_evidence_manifest.py",
        [
            "--phase",
            "staging-failure",
            "--input",
            str(selected_path),
            "--invocation-root",
            str(root / "invocations"),
            "--exclude-current-invocation",
            "--out",
            str(manifest_path),
            "--invocation-dir",
            str(manifest_directory),
        ],
        manifest_directory,
        input_paths=[(selected_path, "metriplane.release-staging-attempt.v1")],
        planned_outputs=[(manifest_path, "metriplane.release-evidence-manifest.v1")],
    )
    captured = release._ReleaseCapturedFiles.capture(
        root,
        [
            (path.relative_to(root).as_posix(), "prerequisite-original")
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ],
        forbidden=(),
        allowed_kinds=frozenset({"prerequisite-original"}),
    )
    envelope_name = envelope_path.relative_to(root).as_posix()
    manifest_name = manifest_path.relative_to(root).as_posix()
    failure_entry = copy.deepcopy(
        release._release_index_receipt_content(prior["original_receipt"]["data"])
    )
    failure_entry["scope"] = {
        **failure_entry["scope"],
        "stage": "staging-failure",
        "sequence": failure_entry["scope"]["sequence"] + 1,
    }
    node = release._ReleasePrerequisiteGraphNode
    dependencies = {
        "original-entry-receipt": node(
            "inputs/receipt.json",
            "update_release_attempt_index.py",
            release.canonical_json(prior["original_receipt"]),
            ".",
            prior["native_facts"],
            (),
        ),
        "failure-entry-receipt": node(
            "failure-entry.json",
            "update_release_attempt_index.py",
            b"{}",
            ".",
            prior["native_facts"],
            (envelope_name,),
        ),
        "failure-envelope-manifest": node(
            manifest_name,
            "build_release_evidence_manifest.py",
            release.canonical_json(manifest),
            ".",
            None,
            (envelope_name,),
        ),
    }
    origins = {
        manifest_name: {
            "run_root": ".",
            "producer": "build_release_evidence_manifest.py",
            "record": {**manifest, "sequence": manifest_original.intent["sequence"]},
        },
        envelope_name: {
            "run_root": ".",
            "producer": "record_release_staging_attempt.py",
            "record": envelope,
        },
    }
    return {
        "captured": captured,
        "origins": origins,
        "dependencies": dependencies,
        "failure_manifest_path": manifest_path,
        "failure_manifest": manifest,
        "failure_entry": failure_entry,
        "original_receipt": prior["original_receipt"],
    }


def test_failed_index_connected_manifest_reaches_actual_original_failed_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = release._release_graph_failed_operation_from_manifest(
        **_failed_index_connected_manifest_fixture(tmp_path, monkeypatch)
    )
    assert result["original_operation_id"] == "synthetic-operation"
    assert result["failed_intent_digest"]


def test_failed_index_connected_manifest_rejects_later_unrelated_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(release.ReleaseControlError):
        release._release_graph_failed_operation_from_manifest(
            **_failed_index_connected_manifest_fixture(tmp_path, monkeypatch, unrelated=True)
        )
