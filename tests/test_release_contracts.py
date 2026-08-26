# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from metriplane.release_control import MILESTONES, TOOL_CONTRACTS, tool_main, validate_record

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
