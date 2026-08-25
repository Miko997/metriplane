# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from metriplane.release_control import MILESTONES, validate_record

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
    missing = sorted(name for name in TOOL_NAMES if not (ROOT / "tools" / name).is_file())
    assert missing == []
    for name in TOOL_NAMES - {"build_release_artifacts.py"}:
        text = (ROOT / "tools" / name).read_text(encoding="utf-8")
        assert "from metriplane.release_control import tool_main" in text
    artifact_adapter = (ROOT / "tools/build_release_artifacts.py").read_text(encoding="utf-8")
    assert "from tools.release_artifacts import" in artifact_adapter
    assert "create_manifest" in artifact_adapter
    assert "inspect_sdist" in artifact_adapter


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
    assert readiness["framework"] == "READY"
    assert readiness["live_release"] == "BLOCKED_NOT_READY"
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
