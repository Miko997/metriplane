# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.baseline_snapshot import SnapshotError, _internal_validate
from tools.stop_the_line import (
    HealthError,
    canonical_bytes,
    digest,
    github_approval_evidence,
    github_owner_emergency_evidence,
    ingest,
    resolve,
    validate_candidate,
    validate_history,
    validate_owner_emergency_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "status"
GOOD_SHA = "a" * 40
BAD_SHA = "b" * 40
REVIEWED_SHA = "c" * 40
REPAIR_SHA = "d" * 40
TREE_SHA = "e" * 40
POLICY = json.loads((STATUS / "main-health-policy.json").read_text(encoding="utf-8"))


def _summary(
    sha: str,
    conclusion: str = "success",
    *,
    cadence: str = "protected-main",
    recorded_at: str = "2026-08-25T18:00:00Z",
    run_id: str = "1",
) -> dict[str, object]:
    return {
        "cadence": cadence,
        "conclusion": conclusion,
        "obligations": [{"id": "suite", "result": conclusion}],
        "recorded_at": recorded_at,
        "run_id": run_id,
        "schema_version": 1,
        "sha": sha,
    }


def test_candidate_result_never_mutates_global_state(tmp_path: Path) -> None:
    result = ingest(
        tmp_path,
        scope="candidate",
        summary=_summary(BAD_SHA, "failure", cadence="candidate"),
    )
    assert result == {
        "accepted": False,
        "mutated": False,
        "schema_version": 1,
        "sha": BAD_SHA,
    }
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(HealthError, match="requires cadence"):
        ingest(tmp_path, scope="candidate", summary=_summary(GOOD_SHA))


def test_first_main_result_activates_with_truthful_not_measured_prehistory(
    tmp_path: Path,
) -> None:
    state = ingest(
        tmp_path,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    activation = json.loads((tmp_path / "activation.json").read_text(encoding="utf-8"))
    assert activation["prehistory_disposition"] == "not_measured"
    assert activation["first_measured_sha"] == GOOD_SHA
    assert state["status"] == "green"
    assert state["generation"] == 1
    assert validate_history(tmp_path)["history_head"] == state["history_head"]
    assert (
        validate_candidate(
            tmp_path,
            base_sha=GOOD_SHA,
            checked_at="2026-08-25T18:30:00Z",
            max_age_seconds=3_600,
        )["status"]
        == "green"
    )
    with pytest.raises(HealthError, match="base SHA"):
        validate_candidate(
            tmp_path,
            base_sha=BAD_SHA,
            checked_at="2026-08-25T18:30:00Z",
            max_age_seconds=3_600,
        )
    with pytest.raises(HealthError, match="stale"):
        validate_candidate(
            tmp_path,
            base_sha=GOOD_SHA,
            checked_at="2026-08-25T20:00:01Z",
            max_age_seconds=3_600,
        )


def test_stale_generation_is_rejected_without_mutation(tmp_path: Path) -> None:
    ingest(
        tmp_path,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    before = (tmp_path / "state.json").read_bytes()
    with pytest.raises(HealthError, match="CAS conflict"):
        ingest(
            tmp_path,
            scope="main",
            summary=_summary(GOOD_SHA, recorded_at="2026-08-25T18:01:00Z"),
            expected_generation=0,
        )
    assert (tmp_path / "state.json").read_bytes() == before


def test_failure_persists_red_across_ordinary_green_ingestion(tmp_path: Path) -> None:
    red = ingest(
        tmp_path,
        scope="main",
        summary=_summary(BAD_SHA, "failure"),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    assert red["status"] == "red"
    assert red["first_bad_sha"] == BAD_SHA
    later = ingest(
        tmp_path,
        scope="main",
        summary=_summary(
            REPAIR_SHA,
            recorded_at="2026-08-25T19:00:00Z",
            run_id="2",
        ),
        expected_generation=1,
    )
    assert later["status"] == "red"
    assert later["first_bad_sha"] == BAD_SHA
    assert later["incident_digest"] == red["incident_digest"]
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "green"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(HealthError, match="contradicts history"):
        validate_history(tmp_path)


def _red_with_repair_results(
    root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    red = ingest(
        root,
        scope="main",
        summary=_summary(BAD_SHA, "failure"),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    incident_digest = red["incident_digest"]
    assert isinstance(incident_digest, str)
    repaired_main = _summary(
        REPAIR_SHA,
        recorded_at="2026-08-25T19:00:00Z",
        run_id="2",
    )
    ingest(root, scope="main", summary=repaired_main, expected_generation=1)
    ingest(
        root,
        scope="nightly",
        summary=_summary(
            REPAIR_SHA,
            cadence="nightly",
            recorded_at="2026-08-25T20:00:00Z",
            run_id="3",
        ),
        expected_generation=2,
    )
    ingest(
        root,
        scope="weekly",
        summary=_summary(
            REPAIR_SHA,
            cadence="weekly",
            recorded_at="2026-08-25T21:00:00Z",
            run_id="4",
        ),
        expected_generation=3,
    )
    approved_review = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {incident_digest}",
        "commit_id": REVIEWED_SHA,
        "id": 321,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T21:30:00Z",
        "user": {"id": 200, "login": "reviewer"},
    }
    approval_evidence = github_approval_evidence(
        pull={
            "head": {"sha": REVIEWED_SHA},
            "merge_commit_sha": REPAIR_SHA,
            "merged": True,
            "merged_at": "2026-08-25T21:45:00Z",
            "user": {"id": 100, "login": "author"},
        },
        review=approved_review,
        reviews=[approved_review],
        files=[{"filename": "tests/test_fix.py"}, {"filename": "metriplane/fix.py"}],
        head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
        merge_commit={
            "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
            "sha": REPAIR_SHA,
            "tree": {"sha": TREE_SHA},
        },
        reviewer_permission="write",
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest=incident_digest,
    )
    authorization = {
        "authorization_mode": approval_evidence["authorization_mode"],
        "approval_digest": digest(approval_evidence),
        "approval_id": approval_evidence["approval_id"],
        "approval_provider": approval_evidence["approval_provider"],
        "allowed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "author": approval_evidence["author"],
        "author_id": approval_evidence["author_id"],
        "changed_paths_digest": digest(sorted(approval_evidence["changed_paths"])),
        "expires_at": "2026-08-26T22:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "proposed_repair_sha": REVIEWED_SHA,
        "pull_request": approval_evidence["pull_request"],
        "repository": approval_evidence["repository"],
        "required_cadences": ["nightly", "weekly"],
        "reviewer": approval_evidence["reviewer"],
        "reviewer_id": approval_evidence["reviewer_id"],
        "reviewer_permission": approval_evidence["reviewer_permission"],
        "schema_version": 1,
    }
    return repaired_main, authorization, approval_evidence


def test_owner_emergency_candidate_is_exact_read_only_admission(tmp_path: Path) -> None:
    red = ingest(
        tmp_path,
        scope="main",
        summary=_summary(BAD_SHA, "failure"),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    incident_digest = red["incident_digest"]
    assert isinstance(incident_digest, str)
    allowed_paths = [
        "docs/status/main-health-owner-emergency.json",
        "tests/test_fix.py",
    ]
    manifest = {
        "authorization_mode": "single-maintainer-owner-emergency",
        "allowed_paths": allowed_paths,
        "base_sha": BAD_SHA,
        "expires_at": "2026-08-26T23:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "pull_request": "123",
        "repository": "Miko997/metriplane",
        "required_cadences": ["nightly", "weekly"],
        "schema_version": 1,
    }
    pull = {
        "base": {"repo": {"full_name": "Miko997/metriplane"}, "sha": BAD_SHA},
        "body": (
            "## Outcome\n\nRepair the open incident.\n\n"
            f"Main-health owner emergency: MET-999\nIncident: {incident_digest}\n\n"
            "## Changes\n\nExact repair only."
        ),
        "head": {"sha": REVIEWED_SHA},
        "number": 123,
        "user": {"id": 100, "login": "Miko997"},
    }
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = validate_owner_emergency_candidate(
        tmp_path,
        manifest=manifest,
        pull=pull,
        changed_paths=allowed_paths,
        expected_head_sha=REVIEWED_SHA,
        checked_at="2026-08-25T22:00:00Z",
    )
    assert result["status"] == "repair-candidate"
    assert result["head_sha"] == REVIEWED_SHA
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(HealthError, match="exact changed paths"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull=pull,
            changed_paths=[*allowed_paths, "unapproved.py"],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull={**pull, "user": {"id": 200, "login": "outsider"}},
            changed_paths=allowed_paths,
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull={**pull, "body": f"{pull['body']}\n\n{pull['body']}"},
            changed_paths=allowed_paths,
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull=pull,
            changed_paths=allowed_paths,
            expected_head_sha=GOOD_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )


def test_owner_emergency_resolution_binds_reviewed_head_merge_and_admin(
    tmp_path: Path,
) -> None:
    repaired_main, _, _ = _red_with_repair_results(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    incident_digest = state["incident_digest"]
    pull = {
        "body": (
            "## Outcome\n\nRepair the open incident.\n\n"
            f"Main-health owner emergency: MET-999\nIncident: {incident_digest}\n\n"
            "## Changes\n\nExact repair only."
        ),
        "head": {"sha": REVIEWED_SHA},
        "merge_commit_sha": REPAIR_SHA,
        "merged": True,
        "merged_at": "2026-08-25T21:45:00Z",
        "user": {"id": 100, "login": "Miko997"},
    }
    evidence = github_owner_emergency_evidence(
        pull=pull,
        files=[{"filename": "metriplane/fix.py"}, {"filename": "tests/test_fix.py"}],
        head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
        merge_commit={
            "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
            "sha": REPAIR_SHA,
            "tree": {"sha": TREE_SHA},
        },
        owner_permission="admin",
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest=incident_digest,
    )
    authorization = {
        "authorization_mode": evidence["authorization_mode"],
        "approval_digest": digest(evidence),
        "approval_id": evidence["approval_id"],
        "approval_provider": evidence["approval_provider"],
        "allowed_paths": evidence["changed_paths"],
        "author": evidence["author"],
        "author_id": evidence["author_id"],
        "changed_paths_digest": digest(evidence["changed_paths"]),
        "expires_at": "2026-08-26T22:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": evidence["issue"],
        "proposed_repair_sha": REVIEWED_SHA,
        "pull_request": evidence["pull_request"],
        "repository": evidence["repository"],
        "required_cadences": ["nightly", "weekly"],
        "reviewer": evidence["reviewer"],
        "reviewer_id": evidence["reviewer_id"],
        "reviewer_permission": evidence["reviewer_permission"],
        "schema_version": 1,
    }
    resolved = resolve(
        tmp_path,
        authorization=authorization,
        approval_evidence=evidence,
        repaired_main=repaired_main,
        resolved_at="2026-08-25T22:00:00Z",
        expected_generation=4,
    )
    assert resolved["status"] == "green"
    resolution = json.loads(next((tmp_path / "resolutions").glob("*.json")).read_text())
    assert resolution["authorization_mode"] == "single-maintainer-owner-emergency"

    with pytest.raises(HealthError, match="admin permission"):
        github_owner_emergency_evidence(
            pull=pull,
            files=[{"filename": "tests/test_fix.py"}],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            owner_permission="write",
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest=incident_digest,
        )


def test_provider_evidence_rejects_reviewed_to_merge_tree_drift(tmp_path: Path) -> None:
    repaired_main, authorization, approval_evidence = _red_with_repair_results(tmp_path)
    approval_evidence["merge_tree_sha"] = GOOD_SHA
    authorization["approval_digest"] = digest(approval_evidence)
    with pytest.raises(HealthError, match="reviewed head to repaired main"):
        resolve(
            tmp_path,
            authorization=authorization,
            approval_evidence=approval_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )


def test_exact_non_author_repair_closes_only_after_retained_main_and_deep_results(
    tmp_path: Path,
) -> None:
    approved = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {'f' * 64}",
        "commit_id": REVIEWED_SHA,
        "id": 1,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T20:00:00Z",
        "user": {"id": 200, "login": "reviewer"},
    }
    requested = {
        **approved,
        "body": "Please revise",
        "id": 2,
        "state": "CHANGES_REQUESTED",
        "submitted_at": "2026-08-25T20:01:00Z",
    }
    with pytest.raises(HealthError, match="superseded"):
        github_approval_evidence(
            pull={
                "head": {"sha": REVIEWED_SHA},
                "merge_commit_sha": REPAIR_SHA,
                "merged": True,
                "merged_at": "2026-08-25T21:00:00Z",
                "user": {"id": 100, "login": "author"},
            },
            review=approved,
            reviews=[approved, requested],
            files=[{"filename": "metriplane/fix.py"}],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            reviewer_permission="write",
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest="f" * 64,
        )
    repaired_main, authorization, approval_evidence = _red_with_repair_results(tmp_path)
    wrong_cadence = {**repaired_main, "cadence": "nightly"}
    with pytest.raises(HealthError, match="protected-main"):
        resolve(
            tmp_path,
            authorization=authorization,
            approval_evidence=approval_evidence,
            repaired_main=wrong_cadence,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    state = resolve(
        tmp_path,
        authorization=authorization,
        approval_evidence=approval_evidence,
        repaired_main=repaired_main,
        resolved_at="2026-08-25T22:00:00Z",
        expected_generation=4,
    )
    assert state["status"] == "green"
    assert state["last_good_sha"] == REPAIR_SHA
    assert state["incident_digest"] is None
    assert state["resolution_digest"]
    assert validate_history(tmp_path)["generation"] == 5
    state_path = tmp_path / "state.json"
    retained_state = json.loads(state_path.read_text(encoding="utf-8"))
    history_paths = sorted((tmp_path / "history").glob("*.json"))
    original_history = {path: path.read_bytes() for path in history_paths[1:]}
    history_values = [json.loads(path.read_text(encoding="utf-8")) for path in history_paths]
    prior_main = json.loads(
        (tmp_path / "results" / f"{history_values[1]['result_digest']}.json").read_text(
            encoding="utf-8"
        )
    )
    failed_main = {
        **prior_main,
        "conclusion": "failure",
        "obligations": [{"id": "suite", "result": "failure"}],
    }
    failed_main_digest = digest(failed_main)
    failed_retention = {
        "backend": "main-health-state-branch",
        "read_back_sha256": failed_main_digest,
        "result_digest": failed_main_digest,
        "schema_version": 1,
    }
    failed_result_path = tmp_path / "results" / f"{failed_main_digest}.json"
    failed_retention_path = tmp_path / "retention" / f"{failed_main_digest}.json"
    failed_result_path.write_bytes(canonical_bytes(failed_main))
    failed_retention_path.write_bytes(canonical_bytes(failed_retention))
    rewritten_history: list[Path] = []
    previous_digest = digest(history_values[0])
    for entry in history_values[1:]:
        rewritten = {**entry, "previous_digest": previous_digest}
        if rewritten["generation"] == 2:
            rewritten["result_digest"] = failed_main_digest
            rewritten["retention_digest"] = digest(failed_retention)
        rewritten_digest = digest(rewritten)
        rewritten_path = (
            tmp_path / "history" / f"{rewritten['generation']:08d}-{rewritten_digest}.json"
        )
        rewritten_path.write_bytes(canonical_bytes(rewritten))
        rewritten_history.append(rewritten_path)
        previous_digest = rewritten_digest
    for path in original_history:
        path.unlink()
    state_path.write_bytes(canonical_bytes({**retained_state, "history_head": previous_digest}))
    with pytest.raises(HealthError, match="exact retained main"):
        validate_history(tmp_path)
    for path in rewritten_history:
        path.unlink()
    for path, value in original_history.items():
        path.write_bytes(value)
    failed_result_path.unlink()
    failed_retention_path.unlink()
    state_path.write_bytes(canonical_bytes(retained_state))
    resolution_path = next((tmp_path / "resolutions").glob("*.json"))
    authorization_path = next((tmp_path / "repair-authorizations").glob("*.json"))
    evidence_path = next((tmp_path / "approval-evidence").glob("*.json"))
    repair_history_path = max((tmp_path / "history").glob("*.json"))
    originals = {
        path: path.read_bytes()
        for path in (
            resolution_path,
            authorization_path,
            evidence_path,
            repair_history_path,
        )
    }
    invalid_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    invalid_evidence.update(
        {"reviewer": "author", "reviewer_id": "100", "state": "CHANGES_REQUESTED"}
    )
    invalid_evidence_digest = digest(invalid_evidence)
    invalid_authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    invalid_authorization.update(
        {
            "approval_digest": invalid_evidence_digest,
            "reviewer": "author",
            "reviewer_id": "100",
        }
    )
    invalid_authorization_digest = digest(invalid_authorization)
    invalid_resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    invalid_resolution["authorization_digest"] = invalid_authorization_digest
    invalid_resolution_digest = digest(invalid_resolution)
    invalid_history = json.loads(repair_history_path.read_text(encoding="utf-8"))
    invalid_history["resolution_digest"] = invalid_resolution_digest
    invalid_history_digest = digest(invalid_history)
    invalid_paths = {
        tmp_path / "approval-evidence" / f"{invalid_evidence_digest}.json": invalid_evidence,
        tmp_path
        / "repair-authorizations"
        / f"{invalid_authorization_digest}.json": invalid_authorization,
        tmp_path / "resolutions" / f"{invalid_resolution_digest}.json": invalid_resolution,
        tmp_path
        / "history"
        / f"{invalid_history['generation']:08d}-{invalid_history_digest}.json": invalid_history,
    }
    for path, value in invalid_paths.items():
        path.write_bytes(canonical_bytes(value))
    for path in originals:
        path.unlink()
    invalid_state = {
        **retained_state,
        "history_head": invalid_history_digest,
        "resolution_digest": invalid_resolution_digest,
    }
    state_path.write_bytes(canonical_bytes(invalid_state))
    with pytest.raises(HealthError, match="non-author|approval evidence"):
        validate_history(tmp_path)
    for path in invalid_paths:
        path.unlink()
    for path, value in originals.items():
        path.write_bytes(value)
    state_path.write_bytes(canonical_bytes(retained_state))
    extra_resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    extra_resolution["resolved_at"] = "2026-08-25T22:01:00Z"
    extra_digest = digest(extra_resolution)
    extra_path = tmp_path / "resolutions" / f"{extra_digest}.json"
    extra_path.write_bytes(canonical_bytes(extra_resolution))
    with pytest.raises(HealthError, match="orphaned"):
        validate_history(tmp_path)
    retargeted = {**retained_state, "resolution_digest": extra_digest}
    state_path.write_bytes(canonical_bytes(retargeted))
    with pytest.raises(HealthError, match="latest repair resolution"):
        validate_history(tmp_path)
    state_path.write_bytes(canonical_bytes(retained_state))
    extra_path.unlink()
    incident = next((tmp_path / "incidents").glob("*.json"))
    incident.unlink()
    with pytest.raises(HealthError, match="No such file|incident"):
        validate_history(tmp_path)


@pytest.mark.parametrize("fault", ["self", "expired", "stale", "unrelated", "incomplete"])
def test_repair_faults_fail_closed(tmp_path: Path, fault: str) -> None:
    repaired_main, authorization, approval_evidence = _red_with_repair_results(tmp_path)
    resolved_at = "2026-08-25T22:00:00Z"
    if fault == "self":
        authorization["reviewer"] = "author"
        authorization["reviewer_id"] = authorization["author_id"]
    elif fault == "expired":
        resolved_at = "2026-08-27T22:00:00Z"
    elif fault == "stale":
        authorization["proposed_repair_sha"] = GOOD_SHA
    elif fault == "unrelated":
        approval_evidence["changed_paths"] = ["metriplane/unrelated.py"]
        authorization["changed_paths_digest"] = digest(approval_evidence["changed_paths"])
        authorization["approval_digest"] = digest(approval_evidence)
    else:
        authorization["required_cadences"] = ["nightly", "weekly", "missing"]
    before = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    with pytest.raises(HealthError):
        resolve(
            tmp_path,
            authorization=authorization,
            approval_evidence=approval_evidence,
            repaired_main=repaired_main,
            resolved_at=resolved_at,
            expected_generation=4,
        )
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == before


def test_incomplete_deep_results_fail_closed(tmp_path: Path) -> None:
    red = ingest(
        tmp_path,
        scope="main",
        summary=_summary(BAD_SHA, "failure"),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    incident_digest = red["incident_digest"]
    assert isinstance(incident_digest, str)
    repaired = _summary(REPAIR_SHA, recorded_at="2026-08-25T19:00:00Z", run_id="2")
    ingest(tmp_path, scope="main", summary=repaired, expected_generation=1)
    for cadence in ("nightly", "weekly"):
        forged = _summary(REPAIR_SHA, cadence=cadence, run_id=f"forged-{cadence}")
        (tmp_path / "results" / f"forged-{cadence}.json").write_text(
            json.dumps(forged), encoding="utf-8"
        )
    approval_evidence = {
        "authorization_mode": "independent-review",
        "approval_id": "321",
        "approval_provider": "github",
        "author": "author",
        "author_id": "100",
        "captured_at": "2026-08-25T21:30:00Z",
        "changed_paths": ["metriplane/fix.py"],
        "head_sha": REVIEWED_SHA,
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "merge_commit_sha": REPAIR_SHA,
        "merge_parent_shas": [GOOD_SHA, REVIEWED_SHA],
        "merge_tree_sha": TREE_SHA,
        "pull_request": "123",
        "repository": "Miko997/metriplane",
        "reviewed_tree_sha": TREE_SHA,
        "reviewer": "reviewer",
        "reviewer_id": "200",
        "reviewer_permission": "write",
        "schema_version": 1,
        "state": "APPROVED",
    }
    authorization = {
        "authorization_mode": approval_evidence["authorization_mode"],
        "approval_digest": digest(approval_evidence),
        "approval_id": approval_evidence["approval_id"],
        "approval_provider": approval_evidence["approval_provider"],
        "allowed_paths": ["metriplane/fix.py"],
        "author": approval_evidence["author"],
        "author_id": approval_evidence["author_id"],
        "changed_paths_digest": digest(approval_evidence["changed_paths"]),
        "expires_at": "2026-08-26T22:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "proposed_repair_sha": REVIEWED_SHA,
        "pull_request": approval_evidence["pull_request"],
        "repository": approval_evidence["repository"],
        "required_cadences": ["nightly", "weekly"],
        "reviewer": approval_evidence["reviewer"],
        "reviewer_id": approval_evidence["reviewer_id"],
        "reviewer_permission": approval_evidence["reviewer_permission"],
        "schema_version": 1,
    }
    with pytest.raises(HealthError, match="orphaned|incomplete"):
        resolve(
            tmp_path,
            authorization=authorization,
            approval_evidence=approval_evidence,
            repaired_main=repaired,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=2,
        )


def test_history_corruption_is_detected(tmp_path: Path) -> None:
    ingest(
        tmp_path,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    history = next((tmp_path / "history").glob("*.json"))
    value = json.loads(history.read_text(encoding="utf-8"))
    value["sha"] = BAD_SHA
    history.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(HealthError, match="filename digest"):
        validate_history(tmp_path)
    ingest_root = tmp_path / "retention"
    ingest(
        ingest_root,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    next((ingest_root / "retention").glob("*.json")).unlink()
    with pytest.raises(HealthError, match="retention receipt is missing"):
        validate_history(ingest_root)


def test_identical_ingestion_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        ingest(
            root,
            scope="main",
            summary=copy.deepcopy(_summary(GOOD_SHA)),
            activation_policy=copy.deepcopy(POLICY),
            expected_generation=-1,
        )
    first_files = {
        path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()
    }
    second_files = {
        path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()
    }
    assert first_files == second_files


def test_schema_policy_and_example_families_are_complete_json() -> None:
    names = {
        "main-health-history-activation-policy",
        "main-health-history-activation",
        "main-health-history",
        "main-health-incident",
        "main-health-owner-emergency",
        "main-health-provider-evidence",
        "main-health-repair-authorization",
        "main-health-resolution",
        "main-health-result-summary",
        "main-health-retention",
        "main-health-state",
    }
    for name in names:
        schema = json.loads(
            (STATUS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
        )
        example = json.loads((STATUS / "examples" / f"{name}.json").read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
        assert set(schema["required"]) == set(example)
        _internal_validate(example, schema)
        if name == "main-health-history":
            invalid = {**example, "resolution_digest": "f" * 64}
            with pytest.raises(SnapshotError):
                _internal_validate(invalid, schema)
            repair = {**example, "cadence": "repair-resolution"}
            with pytest.raises(SnapshotError):
                _internal_validate(repair, schema)
