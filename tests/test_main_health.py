# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import stop_the_line
from tools.baseline_snapshot import SnapshotError, _internal_validate
from tools.stop_the_line import (
    HealthError,
    _github_changed_paths,
    _validate_current_provider_capture,
    canonical_bytes,
    digest,
    github_approval_evidence,
    github_owner_emergency_evidence,
    ingest,
    resolve,
    validate_candidate,
    validate_git_history,
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
STATE_SHA = "f" * 40
POLICY = json.loads((STATUS / "main-health-policy.json").read_text(encoding="utf-8"))


def _check_run(
    *,
    check_run_id: int = 42,
    conclusion: str = "failure",
    external_id: str = "main-health:1:1:old",
    head_sha: str = GOOD_SHA,
    name: str = "Main health admission / required",
) -> dict[str, object]:
    return {
        "app": {"id": 4722589, "slug": "metriplane-main-health-publisher"},
        "completed_at": "2026-08-26T08:00:00Z",
        "conclusion": conclusion,
        "details_url": "https://github.com/Miko997/metriplane/actions/runs/1",
        "external_id": external_id,
        "head_sha": head_sha,
        "id": check_run_id,
        "name": name,
        "output": {"summary": "old summary", "title": "old title"},
        "status": "completed",
    }


def _core_ruleset() -> dict[str, object]:
    return {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "enforcement": "active",
        "name": "Protect main",
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "parameters": {
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_extra_approval_for_unattributed_changes": True,
                    "require_last_push_approval": False,
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": False,
                    "required_reviewers": [],
                },
                "type": "pull_request",
            },
            {
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": "Metriplane / required", "integration_id": 15368},
                        {"context": "Documentation / required", "integration_id": 15368},
                        {"context": "Security / required", "integration_id": 15368},
                    ],
                    "strict_required_status_checks_policy": True,
                },
                "type": "required_status_checks",
            },
        ],
        "target": "branch",
    }


def _main_health_ruleset() -> dict[str, object]:
    return {
        "bypass_actors": [
            {
                "actor_id": 5,
                "actor_type": "RepositoryRole",
                "bypass_mode": "pull_request",
            }
        ],
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "enforcement": "active",
        "name": "Protect main health admission",
        "rules": [
            {
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {
                            "context": "Main health admission / required",
                            "integration_id": 4722589,
                        }
                    ],
                    "strict_required_status_checks_policy": True,
                },
                "type": "required_status_checks",
            }
        ],
        "target": "branch",
    }


def _state_protection_ruleset() -> dict[str, object]:
    return {
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["refs/heads/metriplane-main-health-state"],
            }
        },
        "enforcement": "active",
        "name": "Protect main health state",
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
        "target": "branch",
    }


def _state_writer_ruleset() -> dict[str, object]:
    return {
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "exclude": [],
                "include": ["refs/heads/metriplane-main-health-state"],
            }
        },
        "enforcement": "active",
        "name": "Restrict main health state writers",
        "rules": [{"type": "update"}],
        "target": "branch",
    }


@pytest.mark.parametrize(
    "case",
    ["missing-deletion", "changed-review-policy", "duplicate-required-check"],
)
def test_owner_bypass_rulesets_require_exact_core_protection(case: str) -> None:
    protection = _core_ruleset()
    rules = protection["rules"]
    assert isinstance(rules, list)
    if case == "missing-deletion":
        rules.pop(0)
    elif case == "changed-review-policy":
        rules[2]["parameters"]["required_approving_review_count"] = 1
    else:
        rules[3]["parameters"]["required_status_checks"].append(
            {"context": "Metriplane / required", "integration_id": 15368}
        )
    with pytest.raises(HealthError, match="governed"):
        stop_the_line._validate_owner_bypass_rulesets(protection, _main_health_ruleset())


def test_owner_bypass_ruleset_rejects_shared_actions_main_health_identity() -> None:
    main_health = _main_health_ruleset()
    rules = main_health["rules"]
    assert isinstance(rules, list)
    rules[0]["parameters"]["required_status_checks"][0]["integration_id"] = 15368
    with pytest.raises(HealthError, match="main-health bypass"):
        stop_the_line._validate_owner_bypass_rulesets(_core_ruleset(), main_health)


def test_owner_state_rulesets_require_provider_freeze() -> None:
    state_writer = _state_writer_ruleset()
    state_writer["bypass_actors"] = [
        {
            "actor_id": 4722589,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]

    with pytest.raises(HealthError, match="not frozen"):
        stop_the_line._validate_owner_state_rulesets(_state_protection_ruleset(), state_writer)


def test_main_health_reuses_one_app_check_run(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _check_run()
    requests: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        stop_the_line,
        "_github_provider_timestamp",
        lambda _token: "2026-08-26T08:01:00Z",
    )
    monkeypatch.setattr(stop_the_line, "_github_check_runs", lambda **_kwargs: [existing])

    def request(
        path: str,
        _token: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert payload is not None
        requests.append((path, method, payload))
        return {
            **existing,
            **payload,
            "app": existing["app"],
            "head_sha": GOOD_SHA,
            "id": 42,
        }

    monkeypatch.setattr(stop_the_line, "_github_request", request)
    external_id = f"main-health:123:2:{'a' * 32}:{GOOD_SHA}:1710000240"
    result = stop_the_line.set_github_check_run(
        app_id=4722589,
        app_slug="metriplane-main-health-publisher",
        conclusion="success",
        details_url="https://github.com/Miko997/metriplane/actions/runs/123",
        external_id=external_id,
        head_sha=GOOD_SHA,
        name="Main health admission / required",
        output_summary="Valid until the shared provider deadline.",
        output_title="Main health admission passed",
        repository="Miko997/metriplane",
        token="token",
    )
    assert result["id"] == 42
    assert requests == [
        (
            "repos/Miko997/metriplane/check-runs/42",
            "PATCH",
            {
                "completed_at": "2026-08-26T08:01:00Z",
                "conclusion": "success",
                "details_url": "https://github.com/Miko997/metriplane/actions/runs/123",
                "external_id": external_id,
                "name": "Main health admission / required",
                "output": {
                    "summary": "Valid until the shared provider deadline.",
                    "title": "Main health admission passed",
                },
                "status": "completed",
            },
        )
    ]


def test_main_health_quarantines_duplicate_app_checks_before_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = _check_run(check_run_id=41)
    canonical = _check_run(check_run_id=42)
    requests: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        stop_the_line,
        "_github_provider_timestamp",
        lambda _token: "2026-08-26T08:01:00Z",
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_check_runs",
        lambda **_kwargs: [canonical, duplicate],
    )

    def request(
        path: str,
        _token: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "PATCH"
        assert payload is not None
        requests.append((path, payload))
        check_run_id = int(path.rsplit("/", 1)[1])
        source = duplicate if check_run_id == 41 else canonical
        return {**source, **payload, "app": source["app"], "id": check_run_id}

    monkeypatch.setattr(stop_the_line, "_github_request", request)
    result = stop_the_line.set_github_check_run(
        app_id=4722589,
        app_slug="metriplane-main-health-publisher",
        conclusion="success",
        details_url="https://github.com/Miko997/metriplane/actions/runs/123",
        external_id=f"mh1:{GOOD_SHA}:123:1:{'a' * 32}:1710000240",
        head_sha=GOOD_SHA,
        name="Main health admission / required",
        output_summary="Valid until the shared provider deadline.",
        output_title="Main health admission passed",
        repository="Miko997/metriplane",
        token="token",
    )
    assert result["id"] == 42
    assert [path for path, _payload in requests] == [
        "repos/Miko997/metriplane/check-runs/41",
        "repos/Miko997/metriplane/check-runs/42",
    ]
    assert requests[0][1]["name"] == "Main health admission / required [superseded 41]"
    assert requests[0][1]["conclusion"] == "failure"
    assert requests[1][1]["name"] == "Main health admission / required"
    assert requests[1][1]["conclusion"] == "success"


def test_main_health_rejects_foreign_existing_check_before_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = _check_run()
    app = foreign["app"]
    assert isinstance(app, dict)
    app["slug"] = "another-publisher"
    monkeypatch.setattr(
        stop_the_line,
        "_github_provider_timestamp",
        lambda _token: "2026-08-26T08:01:00Z",
    )
    monkeypatch.setattr(stop_the_line, "_github_check_runs", lambda **_kwargs: [foreign])
    monkeypatch.setattr(
        stop_the_line,
        "_github_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an unbound check must not be patched")
        ),
    )

    with pytest.raises(HealthError, match="identity is not provider-bound"):
        stop_the_line.set_github_check_run(
            app_id=4722589,
            app_slug="metriplane-main-health-publisher",
            conclusion="success",
            details_url="https://github.com/Miko997/metriplane/actions/runs/123",
            external_id=f"mh1:{GOOD_SHA}:123:1:{'a' * 32}:1710000240",
            head_sha=GOOD_SHA,
            name="Main health admission / required",
            output_summary="Valid until the shared provider deadline.",
            output_title="Main health admission passed",
            repository="Miko997/metriplane",
            token="token",
        )


def test_stale_attempt_expiry_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    newer_external_id = f"main-health:124:1:{'b' * 32}:{GOOD_SHA}:1710000540"
    monkeypatch.setattr(
        stop_the_line,
        "_github_get",
        lambda _path, _token: _check_run(conclusion="success", external_id=newer_external_id),
    )

    def unexpected_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a stale lease must never PATCH the mutable check")

    monkeypatch.setattr(stop_the_line, "_github_request", unexpected_request)
    result = stop_the_line.expire_github_check_run(
        app_id=4722589,
        app_slug="metriplane-main-health-publisher",
        check_run_id=42,
        details_url="https://github.com/Miko997/metriplane/actions/runs/200",
        external_id=f"main-health:123:1:{'a' * 32}:{GOOD_SHA}:1710000240",
        head_sha=GOOD_SHA,
        name="Main health admission / required",
        output_summary="The shared provider deadline elapsed.",
        output_title="Main health admission expired",
        repository="Miko997/metriplane",
        token="token",
    )
    assert result == {
        "check_run_id": 42,
        "external_id": newer_external_id,
        "state": "stale",
    }


def test_exact_expiry_cannot_restore_an_external_id(monkeypatch: pytest.MonkeyPatch) -> None:
    external_id = f"mh1:{GOOD_SHA}:123:1:{'a' * 32}:1710000240"
    current = _check_run(conclusion="success", external_id=external_id)
    captured_payload: dict[str, object] = {}
    monkeypatch.setattr(stop_the_line, "_github_get", lambda _path, _token: current)
    monkeypatch.setattr(
        stop_the_line,
        "_github_provider_timestamp",
        lambda _token: "2026-08-26T08:04:00Z",
    )

    def request(
        _path: str,
        _token: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "PATCH"
        assert payload is not None
        captured_payload.update(payload)
        return {
            **current,
            **payload,
            "app": current["app"],
            "external_id": external_id,
            "head_sha": GOOD_SHA,
            "id": 42,
        }

    monkeypatch.setattr(stop_the_line, "_github_request", request)
    result = stop_the_line.expire_github_check_run(
        app_id=4722589,
        app_slug="metriplane-main-health-publisher",
        check_run_id=42,
        details_url="https://github.com/Miko997/metriplane/actions/runs/200",
        external_id=external_id,
        head_sha=GOOD_SHA,
        name="Main health admission / required",
        output_summary="The shared provider deadline elapsed.",
        output_title="Main health admission expired",
        repository="Miko997/metriplane",
        token="token",
    )
    assert result["state"] == "expired"
    assert "external_id" not in captured_payload
    assert captured_payload["conclusion"] == "failure"


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


def _owner_admission(
    manifest: dict[str, object],
    *,
    changed_paths: list[str],
    checked_at: str = "2026-08-25T21:44:00Z",
) -> dict[str, object]:
    collaborators = [{"id": "100", "login": "Miko997", "permission": "admin"}]
    artifact = {
        "authorization_mode": "single-maintainer-owner-emergency",
        "base_sha": manifest["base_sha"],
        "changed_paths": changed_paths,
        "checked_at": checked_at,
        "collaboration_digest": digest({"collaborators": collaborators, "pending_invitations": []}),
        "collaborators": collaborators,
        "head_sha": REVIEWED_SHA,
        "incident_digest": manifest["incident_digest"],
        "issue": manifest["issue"],
        "manifest_digest": digest(manifest),
        "main_health_ruleset": _main_health_ruleset(),
        "main_health_ruleset_digest": digest(_main_health_ruleset()),
        "main_health_ruleset_id": "2000",
        "pending_invitations": [],
        "protection_ruleset": _core_ruleset(),
        "protection_ruleset_digest": digest(_core_ruleset()),
        "protection_ruleset_id": "1000",
        "pull_request": str(manifest["pull_request"]),
        "repository": manifest["repository"],
        "schema_version": 1,
        "state_commit": STATE_SHA,
        "state_generation": 7,
        "state_protection_ruleset": _state_protection_ruleset(),
        "state_protection_ruleset_digest": digest(_state_protection_ruleset()),
        "state_protection_ruleset_id": "3000",
        "state_writer_ruleset": _state_writer_ruleset(),
        "state_writer_ruleset_digest": digest(_state_writer_ruleset()),
        "state_writer_ruleset_id": "4000",
        "status": "repair-candidate",
    }
    return {
        "artifact": artifact,
        "artifact_digest": digest(artifact),
        "comment_author": "Miko997",
        "comment_author_id": "100",
        "comment_created_at": "2026-08-25T21:44:30Z",
        "comment_id": "2000",
        "comment_updated_at": "2026-08-25T21:44:30Z",
        "provider": "github",
        "schema_version": 1,
    }


def _owner_merge_gate(admission: dict[str, object]) -> dict[str, object]:
    admission_digest = digest(admission)
    artifact = admission["artifact"]
    assert isinstance(artifact, dict)
    return {
        "admission_comment_id": admission["comment_id"],
        "admission_digest": admission_digest,
        "bypass_actor": {
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "pull_request",
        },
        "head_sha": REVIEWED_SHA,
        "main_health_ruleset_digest": artifact["main_health_ruleset_digest"],
        "main_health_ruleset_id": artifact["main_health_ruleset_id"],
        "merge_commit_sha": REPAIR_SHA,
        "merged_at": "2026-08-25T21:45:00Z",
        "merged_by": "Miko997",
        "merged_by_id": "100",
        "protection_ruleset_digest": artifact["protection_ruleset_digest"],
        "protection_ruleset_id": artifact["protection_ruleset_id"],
        "pull_request": "123",
        "repository": "Miko997/metriplane",
        "schema_version": 1,
        "state_commit": artifact["state_commit"],
        "state_generation": artifact["state_generation"],
        "state_protection_ruleset_digest": artifact["state_protection_ruleset_digest"],
        "state_protection_ruleset_id": artifact["state_protection_ruleset_id"],
        "state_writer_ruleset_digest": artifact["state_writer_ruleset_digest"],
        "state_writer_ruleset_id": artifact["state_writer_ruleset_id"],
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


def test_incident_identity_is_derived_from_immutable_opening_history(tmp_path: Path) -> None:
    state = ingest(
        tmp_path,
        scope="main",
        summary=_summary(BAD_SHA, "failure"),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    original_path = tmp_path / "incidents" / f"{state['incident_digest']}.json"
    forged = json.loads(original_path.read_text(encoding="utf-8"))
    forged["failing_obligations"] = ["forged"]
    forged_digest = digest(forged)
    (tmp_path / "incidents" / f"{forged_digest}.json").write_bytes(canonical_bytes(forged))
    state["incident_digest"] = forged_digest
    (tmp_path / "state.json").write_bytes(canonical_bytes(state))
    with pytest.raises(HealthError, match="opening history|incident pointer"):
        validate_history(tmp_path)


def test_provider_file_inventory_includes_rename_source_and_rejects_truncation() -> None:
    assert _github_changed_paths(
        {"changed_files": 1},
        [
            {
                "filename": "tests/allowed.py",
                "previous_filename": "tools/protected.py",
                "status": "renamed",
            }
        ],
    ) == ["tests/allowed.py", "tools/protected.py"]
    with pytest.raises(HealthError, match="incomplete|3,000"):
        _github_changed_paths({"changed_files": 3_001}, [])
    with pytest.raises(HealthError, match="incomplete|3,000"):
        _github_changed_paths(
            {"changed_files": 2},
            [{"filename": "only-one.py", "status": "modified"}],
        )


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
            "base": {"sha": GOOD_SHA},
            "changed_files": 2,
            "head": {"sha": REVIEWED_SHA},
            "merge_commit_sha": REPAIR_SHA,
            "merged": True,
            "merged_at": "2026-08-25T21:45:00Z",
            "user": {"id": 100, "login": "author"},
        },
        review=approved_review,
        reviews=[approved_review],
        files=[
            {"filename": "tests/test_fix.py", "status": "modified"},
            {"filename": "metriplane/fix.py", "status": "modified"},
        ],
        head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
        merge_commit={
            "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
            "sha": REPAIR_SHA,
            "tree": {"sha": TREE_SHA},
        },
        reviewer_permissions={"reviewer": "write"},
        captured_at="2026-08-25T21:46:00Z",
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
        "manifest_digest": None,
        "policy_amendment_digest": None,
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
    collaborators = [{"id": 100, "login": "Miko997", "role_name": "admin"}]
    manifest = {
        "authorization_mode": "single-maintainer-owner-emergency",
        "allowed_paths": allowed_paths,
        "base_sha": BAD_SHA,
        "collaboration_digest": digest(
            {
                "collaborators": [{"id": "100", "login": "Miko997", "permission": "admin"}],
                "pending_invitations": [],
            }
        ),
        "expires_at": "2026-08-26T23:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "policy_amendment": {
            "amended_rule": "repair_requires_non_author",
            "authorization_mode": "single-maintainer-owner-emergency",
            "incident_digest": incident_digest,
            "reason": "single-maintainer-no-independent-collaborator",
            "schema_version": 1,
            "scope": "incident-only",
        },
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
        "changed_files": 2,
        "number": 123,
        "user": {"id": 100, "login": "Miko997"},
    }
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = validate_owner_emergency_candidate(
        tmp_path,
        manifest=manifest,
        pull=pull,
        files=[
            {"filename": allowed_paths[0], "status": "modified"},
            {"filename": allowed_paths[1], "status": "modified"},
        ],
        collaborators=collaborators,
        invitations=[],
        expected_head_sha=REVIEWED_SHA,
        checked_at="2026-08-25T22:00:00Z",
    )
    assert result["status"] == "repair-candidate"
    assert result["head_sha"] == REVIEWED_SHA
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(HealthError, match="eligible independent collaborator"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull=pull,
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=[
                *collaborators,
                {"id": 200, "login": "reviewer", "role_name": "write"},
            ],
            invitations=[],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="eligible independent collaborator"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull=pull,
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=collaborators,
            invitations=[
                {
                    "id": 300,
                    "invitee": {"login": "invited-reviewer"},
                    "permissions": "write",
                }
            ],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="collaboration digest is stale"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest={**manifest, "collaboration_digest": "0" * 64},
            pull=pull,
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=collaborators,
            invitations=[],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="exact changed paths"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull={**pull, "changed_files": 3},
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
                {"filename": "unapproved.py", "status": "added"},
            ],
            collaborators=collaborators,
            invitations=[],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull={**pull, "user": {"id": 200, "login": "outsider"}},
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=collaborators,
            invitations=[],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull={**pull, "body": f"{pull['body']}\n\n{pull['body']}"},
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=collaborators,
            invitations=[],
            expected_head_sha=REVIEWED_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )
    with pytest.raises(HealthError, match="identity or marker"):
        validate_owner_emergency_candidate(
            tmp_path,
            manifest=manifest,
            pull=pull,
            files=[
                {"filename": allowed_paths[0], "status": "modified"},
                {"filename": allowed_paths[1], "status": "modified"},
            ],
            collaborators=collaborators,
            invitations=[],
            expected_head_sha=GOOD_SHA,
            checked_at="2026-08-25T22:00:00Z",
        )


def test_owner_emergency_resolution_binds_reviewed_head_merge_and_admin(
    tmp_path: Path,
) -> None:
    repaired_main, _, _ = _red_with_repair_results(tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    incident_digest = state["incident_digest"]
    manifest = {
        "authorization_mode": "single-maintainer-owner-emergency",
        "allowed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "base_sha": BAD_SHA,
        "collaboration_digest": digest(
            {
                "collaborators": [{"id": "100", "login": "Miko997", "permission": "admin"}],
                "pending_invitations": [],
            }
        ),
        "expires_at": "2026-08-26T22:00:00Z",
        "failing_obligations": ["suite"],
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "policy_amendment": {
            "amended_rule": "repair_requires_non_author",
            "authorization_mode": "single-maintainer-owner-emergency",
            "incident_digest": incident_digest,
            "reason": "single-maintainer-no-independent-collaborator",
            "schema_version": 1,
            "scope": "incident-only",
        },
        "pull_request": "123",
        "repository": "Miko997/metriplane",
        "required_cadences": ["nightly", "weekly"],
        "schema_version": 1,
    }
    admission = _owner_admission(manifest, changed_paths=["metriplane/fix.py", "tests/test_fix.py"])
    merge_gate = _owner_merge_gate(admission)
    pull = {
        "base": {"sha": BAD_SHA},
        "body": (
            "## Outcome\n\nRepair the open incident.\n\n"
            f"Main-health owner emergency: MET-999\nIncident: {incident_digest}\n\n"
            "## Changes\n\nExact repair only."
        ),
        "head": {"sha": REVIEWED_SHA},
        "changed_files": 2,
        "merge_commit_sha": REPAIR_SHA,
        "merged": True,
        "merged_at": "2026-08-25T21:45:00Z",
        "merged_by": {"id": 100, "login": "Miko997"},
        "number": 123,
        "user": {"id": 100, "login": "Miko997"},
    }
    evidence = github_owner_emergency_evidence(
        pull=pull,
        files=[
            {"filename": "metriplane/fix.py", "status": "modified"},
            {"filename": "tests/test_fix.py", "status": "modified"},
        ],
        head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
        merge_commit={
            "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
            "sha": REPAIR_SHA,
            "tree": {"sha": TREE_SHA},
        },
        manifest=manifest,
        admission=admission,
        merge_gate=merge_gate,
        collaborators=[{"id": 100, "login": "Miko997", "role_name": "admin"}],
        invitations=[],
        captured_at="2026-08-25T21:46:00Z",
        owner_permission="admin",
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest=incident_digest,
    )
    provider_schema = json.loads(
        (STATUS / "schemas/main-health-provider-evidence.schema.json").read_text(encoding="utf-8")
    )
    _internal_validate(evidence, provider_schema)
    malformed_schema_evidence = copy.deepcopy(evidence)
    del malformed_schema_evidence["merge_gate"]["bypass_actor"]
    with pytest.raises(SnapshotError):
        _internal_validate(malformed_schema_evidence, provider_schema)
    null_emergency_evidence = copy.deepcopy(evidence)
    for field in (
        "admission",
        "admission_digest",
        "collaborators",
        "manifest",
        "manifest_digest",
        "merge_gate",
        "merge_gate_digest",
        "pending_invitations",
    ):
        null_emergency_evidence[field] = None
    with pytest.raises(SnapshotError):
        _internal_validate(null_emergency_evidence, provider_schema)
    extra_parent_evidence = copy.deepcopy(evidence)
    extra_parent_evidence["merge_parent_shas"].append("9" * 40)
    with pytest.raises(SnapshotError):
        _internal_validate(extra_parent_evidence, provider_schema)
    excluded_ref_evidence = copy.deepcopy(evidence)
    excluded_ref_evidence["admission"]["artifact"]["main_health_ruleset"]["conditions"]["ref_name"][
        "exclude"
    ] = ["refs/heads/release"]
    with pytest.raises(SnapshotError):
        _internal_validate(excluded_ref_evidence, provider_schema)
    boolean_state_evidence = copy.deepcopy(evidence)
    boolean_state_evidence["admission"]["artifact"]["state_generation"] = True
    boolean_state_evidence["merge_gate"]["state_generation"] = True
    with pytest.raises(SnapshotError):
        _internal_validate(boolean_state_evidence, provider_schema)
    thawed_state_writer_evidence = copy.deepcopy(evidence)
    thawed_state_writer_evidence["admission"]["artifact"]["state_writer_ruleset"][
        "bypass_actors"
    ] = [
        {
            "actor_id": 4722589,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    with pytest.raises(SnapshotError):
        _internal_validate(thawed_state_writer_evidence, provider_schema)
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
        "manifest_digest": evidence["manifest_digest"],
        "policy_amendment_digest": digest(manifest["policy_amendment"]),
        "proposed_repair_sha": REVIEWED_SHA,
        "pull_request": evidence["pull_request"],
        "repository": evidence["repository"],
        "required_cadences": ["nightly", "weekly"],
        "reviewer": evidence["reviewer"],
        "reviewer_id": evidence["reviewer_id"],
        "reviewer_permission": evidence["reviewer_permission"],
        "schema_version": 1,
    }
    with pytest.raises(HealthError, match="admitted manifest"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "allowed_paths": [*authorization["allowed_paths"], "unapproved.py"],
            },
            approval_evidence=evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    with pytest.raises(HealthError, match="expired"):
        resolve(
            tmp_path,
            authorization=authorization,
            approval_evidence=evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T20:00:00Z",
            expected_generation=4,
        )
    late_admission_evidence = copy.deepcopy(evidence)
    late_admission_evidence["admission"]["artifact"]["checked_at"] = "2026-08-25T21:46:00Z"
    late_admission_evidence["admission"]["artifact_digest"] = digest(
        late_admission_evidence["admission"]["artifact"]
    )
    late_admission_evidence["admission_digest"] = digest(late_admission_evidence["admission"])
    with pytest.raises(HealthError, match="bracket"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(late_admission_evidence),
            },
            approval_evidence=late_admission_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    edited_admission_evidence = copy.deepcopy(evidence)
    edited_admission_evidence["admission"]["comment_updated_at"] = "2026-08-25T21:45:01Z"
    edited_admission_evidence["admission_digest"] = digest(edited_admission_evidence["admission"])
    with pytest.raises(HealthError, match="attestation"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(edited_admission_evidence),
            },
            approval_evidence=edited_admission_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    stale_lease_evidence = copy.deepcopy(evidence)
    stale_lease_evidence["admission"]["artifact"]["checked_at"] = "2026-08-25T21:29:59Z"
    stale_lease_evidence["admission"]["artifact_digest"] = digest(
        stale_lease_evidence["admission"]["artifact"]
    )
    stale_lease_evidence["admission"]["comment_created_at"] = "2026-08-25T21:30:00Z"
    stale_lease_evidence["admission"]["comment_updated_at"] = "2026-08-25T21:30:00Z"
    stale_lease_evidence["admission_digest"] = digest(stale_lease_evidence["admission"])
    with pytest.raises(HealthError, match="bracket"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(stale_lease_evidence),
            },
            approval_evidence=stale_lease_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    invalid_admission_evidence = copy.deepcopy(evidence)
    invalid_admission_evidence["admission"]["artifact"]["status"] = "approved"
    invalid_admission_evidence["admission"]["artifact_digest"] = digest(
        invalid_admission_evidence["admission"]["artifact"]
    )
    invalid_admission_evidence["admission_digest"] = digest(invalid_admission_evidence["admission"])
    with pytest.raises(HealthError, match="pre-merge admission"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(invalid_admission_evidence),
            },
            approval_evidence=invalid_admission_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    changed_inventory_evidence = copy.deepcopy(evidence)
    changed_inventory_evidence["admission"]["artifact"]["pending_invitations"] = [
        {"id": "300", "invitee": "former-reader", "permission": "read"}
    ]
    changed_inventory_evidence["admission"]["artifact_digest"] = digest(
        changed_inventory_evidence["admission"]["artifact"]
    )
    changed_inventory_evidence["admission_digest"] = digest(changed_inventory_evidence["admission"])
    with pytest.raises(HealthError, match="bracket"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(changed_inventory_evidence),
            },
            approval_evidence=changed_inventory_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    fail_open_gate_evidence = copy.deepcopy(evidence)
    gate = fail_open_gate_evidence["merge_gate"]
    gate["bypass_actor"]["bypass_mode"] = "always"
    fail_open_gate_evidence["merge_gate_digest"] = digest(gate)
    with pytest.raises(HealthError, match="bracket"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(fail_open_gate_evidence),
            },
            approval_evidence=fail_open_gate_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    malformed_state_evidence = copy.deepcopy(evidence)
    malformed_admission = malformed_state_evidence["admission"]
    malformed_artifact = malformed_admission["artifact"]
    malformed_gate = malformed_state_evidence["merge_gate"]
    malformed_artifact["state_generation"] = True
    malformed_gate["state_generation"] = True
    malformed_admission["artifact_digest"] = digest(malformed_artifact)
    malformed_state_evidence["admission_digest"] = digest(malformed_admission)
    malformed_gate["admission_digest"] = malformed_state_evidence["admission_digest"]
    malformed_state_evidence["merge_gate_digest"] = digest(malformed_gate)
    with pytest.raises(HealthError, match="owner state binding is malformed"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(malformed_state_evidence),
            },
            approval_evidence=malformed_state_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
    thawed_writer_evidence = copy.deepcopy(evidence)
    thawed_admission = thawed_writer_evidence["admission"]
    thawed_artifact = thawed_admission["artifact"]
    thawed_gate = thawed_writer_evidence["merge_gate"]
    thawed_artifact["state_writer_ruleset"]["bypass_actors"] = [
        {
            "actor_id": 4722589,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    thawed_artifact["state_writer_ruleset_digest"] = digest(thawed_artifact["state_writer_ruleset"])
    thawed_admission["artifact_digest"] = digest(thawed_artifact)
    thawed_writer_evidence["admission_digest"] = digest(thawed_admission)
    thawed_gate["admission_digest"] = thawed_writer_evidence["admission_digest"]
    thawed_gate["state_writer_ruleset_digest"] = thawed_artifact["state_writer_ruleset_digest"]
    thawed_writer_evidence["merge_gate_digest"] = digest(thawed_gate)
    with pytest.raises(HealthError, match="state writer ruleset is not frozen"):
        resolve(
            tmp_path,
            authorization={
                **authorization,
                "approval_digest": digest(thawed_writer_evidence),
            },
            approval_evidence=thawed_writer_evidence,
            repaired_main=repaired_main,
            resolved_at="2026-08-25T22:00:00Z",
            expected_generation=4,
        )
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
                "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            manifest=manifest,
            admission=admission,
            merge_gate=merge_gate,
            collaborators=[{"id": 100, "login": "Miko997", "role_name": "admin"}],
            invitations=[],
            captured_at="2026-08-25T21:46:00Z",
            owner_permission="write",
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest=incident_digest,
        )
    with pytest.raises(HealthError, match="no eligible independent collaborator"):
        github_owner_emergency_evidence(
            pull=pull,
            files=[
                {"filename": "metriplane/fix.py", "status": "modified"},
                {"filename": "tests/test_fix.py", "status": "modified"},
            ],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            manifest=manifest,
            admission=admission,
            merge_gate=merge_gate,
            collaborators=[
                {"id": 100, "login": "Miko997", "role_name": "admin"},
                {
                    "id": 200,
                    "login": "reviewer",
                    "permissions": {"push": True},
                    "role_name": "custom-reviewer",
                },
            ],
            invitations=[],
            captured_at="2026-08-25T21:46:00Z",
            owner_permission="admin",
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


def test_github_approval_capture_uses_provider_time_with_backward_local_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incident_digest = "f" * 64
    pull = {
        "base": {"sha": GOOD_SHA},
        "changed_files": 1,
        "head": {"sha": REVIEWED_SHA},
        "merge_commit_sha": REPAIR_SHA,
        "merged": True,
        "merged_at": "2026-08-25T21:00:00Z",
        "user": {"id": 100, "login": "author"},
    }
    review = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {incident_digest}",
        "commit_id": REVIEWED_SHA,
        "id": 10,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T20:00:00Z",
        "user": {"id": 200, "login": "reviewer"},
    }
    provider_calls: list[str] = []

    def get(path: str, _token: str) -> object:
        if path.endswith("/pulls/123"):
            return pull
        if "/pulls/123/reviews?" in path:
            return [review]
        if "/pulls/123/files?" in path:
            return [{"filename": "metriplane/fix.py", "status": "modified"}]
        if path.endswith(f"/git/commits/{REVIEWED_SHA}"):
            return {"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}}
        if path.endswith(f"/git/commits/{REPAIR_SHA}"):
            return {
                "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            }
        if path.endswith("/collaborators/reviewer/permission"):
            return {"permission": "write"}
        raise AssertionError(path)

    def provider_now(token: str) -> object:
        provider_calls.append(token)
        return stop_the_line._timestamp("2026-08-25T21:01:00Z")

    monkeypatch.setattr(stop_the_line, "_github_get", get)
    monkeypatch.setattr(stop_the_line, "_github_provider_now", provider_now)
    monkeypatch.setattr(stop_the_line, "_utc_now", lambda: "2000-01-01T00:00:00Z")

    evidence = stop_the_line.capture_github_approval(
        repository="Miko997/metriplane",
        pull_request="123",
        review_id="10",
        issue="MET-999",
        incident_digest=incident_digest,
        token="token",
    )

    assert evidence["captured_at"] == "2026-08-25T21:01:00Z"
    assert provider_calls == ["token"]


def test_provider_refetch_rejects_field_drift_and_backward_time() -> None:
    retained = {"captured_at": "2026-08-25T21:00:00Z", "head_sha": REVIEWED_SHA}
    with pytest.raises(HealthError, match="stale at head_sha"):
        _validate_current_provider_capture(
            retained,
            {"captured_at": "2026-08-25T21:01:00Z", "head_sha": GOOD_SHA},
        )
    with pytest.raises(HealthError, match="predates"):
        _validate_current_provider_capture(
            retained,
            {"captured_at": "2026-08-25T20:59:00Z", "head_sha": REVIEWED_SHA},
        )


def test_owner_resolver_cli_refetches_both_provider_attestations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    admission = {"comment_id": "10"}
    merge_gate = {"comment_id": "11"}
    retained = {"captured_at": "2026-08-25T21:00:00Z", "head_sha": REVIEWED_SHA}
    authorization = {
        "authorization_mode": "single-maintainer-owner-emergency",
        "incident_digest": "f" * 64,
        "issue": "MET-999",
        "pull_request": "123",
        "repository": "Miko997/metriplane",
    }
    args = SimpleNamespace(
        admission_json=None,
        approval_evidence_json=retained,
        authorization_json=authorization,
        command="resolve",
        expected_generation=4,
        owner_admission_json=admission,
        owner_merge_gate_json=merge_gate,
        repaired_main_json={"sha": REPAIR_SHA},
        root=Path("state"),
    )
    seen: dict[str, object] = {}
    provider_calls: list[str] = []

    def capture(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"captured_at": "2026-08-25T21:01:00Z", "head_sha": REVIEWED_SHA}

    def provider_now(token: str) -> object:
        provider_calls.append(token)
        return stop_the_line._timestamp("2026-08-25T22:00:00Z")

    def resolve_current(*_args: object, **kwargs: object) -> dict[str, object]:
        seen["resolved_at"] = kwargs["resolved_at"]
        return {"status": "green"}

    monkeypatch.setattr(stop_the_line, "_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(stop_the_line, "validate_git_history", lambda _root: {})
    monkeypatch.setattr(stop_the_line, "capture_github_owner_emergency", capture)
    monkeypatch.setattr(stop_the_line, "_github_provider_now", provider_now)
    monkeypatch.setattr(stop_the_line, "_utc_now", lambda: "2000-01-01T00:00:00Z")
    monkeypatch.setattr(stop_the_line, "resolve", resolve_current)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    assert stop_the_line.main() == 0
    assert seen["admission"] is admission
    assert seen["merge_gate"] is merge_gate
    assert seen["resolved_at"] == "2026-08-25T22:00:00Z"
    assert provider_calls == ["test-token"]
    assert json.loads(capsys.readouterr().out) == {"status": "green"}


def test_owner_admission_fetches_provider_state_and_publishes_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    provider_calls: list[str] = []
    pull = {
        "head": {"sha": REVIEWED_SHA},
        "merged": False,
        "user": {"login": "Miko997"},
    }
    manifest = {"expires_at": "2026-08-26T22:00:00Z"}
    candidate: dict[str, object] = {
        "checked_at": "2026-08-25T21:44:00Z",
        "head_sha": REVIEWED_SHA,
        "pull_request": "123",
        "repository": "Miko997/metriplane",
    }

    def get(path: str, _token: str) -> object:
        calls.append(path)
        if path.endswith("/pulls/123"):
            return pull
        if path.endswith("/collaborators/Miko997/permission"):
            return {"permission": "admin"}
        if path.endswith("/git/ref/heads/metriplane-main-health-state"):
            return {
                "object": {"sha": STATE_SHA, "type": "commit"},
                "ref": "refs/heads/metriplane-main-health-state",
            }
        if path.endswith("/rulesets/1000"):
            return _core_ruleset()
        if path.endswith("/rulesets/2000"):
            return _main_health_ruleset()
        if path.endswith("/rulesets/3000"):
            return _state_protection_ruleset()
        if path.endswith("/rulesets/4000"):
            return _state_writer_ruleset()
        raise AssertionError(path)

    def list_provider(path: str, _token: str) -> list[dict[str, object]]:
        calls.append(path)
        return []

    def publish(**kwargs: object) -> dict[str, object]:
        artifact = kwargs["artifact"]
        assert isinstance(artifact, dict)
        assert artifact == {
            **candidate,
            "main_health_ruleset": _main_health_ruleset(),
            "main_health_ruleset_digest": digest(_main_health_ruleset()),
            "main_health_ruleset_id": "2000",
            "protection_ruleset": _core_ruleset(),
            "protection_ruleset_digest": digest(_core_ruleset()),
            "protection_ruleset_id": "1000",
            "state_commit": STATE_SHA,
            "state_generation": 7,
            "state_protection_ruleset": _state_protection_ruleset(),
            "state_protection_ruleset_digest": digest(_state_protection_ruleset()),
            "state_protection_ruleset_id": "3000",
            "state_writer_ruleset": _state_writer_ruleset(),
            "state_writer_ruleset_digest": digest(_state_writer_ruleset()),
            "state_writer_ruleset_id": "4000",
        }
        return {
            "artifact": artifact,
            "artifact_digest": digest(artifact),
            "comment_author": "Miko997",
            "comment_author_id": "100",
            "comment_created_at": "2026-08-25T21:44:01Z",
            "comment_id": "2000",
            "comment_updated_at": "2026-08-25T21:44:01Z",
            "provider": "github",
            "schema_version": 1,
        }

    def provider_now(token: str) -> object:
        provider_calls.append(token)
        return stop_the_line._timestamp("2026-08-25T21:44:00Z")

    def validate_candidate(*_args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["checked_at"] == "2026-08-25T21:44:00Z"
        return candidate

    monkeypatch.setattr(
        stop_the_line,
        "validate_git_history",
        lambda _root: {"generation": 7, "state_commit": STATE_SHA},
    )
    monkeypatch.setattr(stop_the_line, "_github_get", get)
    monkeypatch.setattr(stop_the_line, "_github_list", list_provider)
    monkeypatch.setattr(
        stop_the_line, "_github_stable_collaboration_snapshot", lambda *_args: ([], [])
    )
    monkeypatch.setattr(stop_the_line, "_github_manifest", lambda *_args: manifest)
    monkeypatch.setattr(stop_the_line, "validate_owner_emergency_candidate", validate_candidate)
    monkeypatch.setattr(stop_the_line, "_github_provider_now", provider_now)
    monkeypatch.setattr(stop_the_line, "_utc_now", lambda: "2000-01-01T00:00:00Z")
    monkeypatch.setattr(stop_the_line, "_post_github_artifact", publish)

    result = stop_the_line.capture_github_owner_admission(
        root=Path("state"),
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest="f" * 64,
        expected_head_sha=REVIEWED_SHA,
        protection_ruleset_id="1000",
        main_health_ruleset_id="2000",
        state_protection_ruleset_id="3000",
        state_writer_ruleset_id="4000",
        token="token",
    )
    assert result["comment_id"] == "2000"
    assert provider_calls == ["token"]
    assert any(path.endswith("/pulls/123/files") for path in calls)
    assert calls.count("repos/Miko997/metriplane/git/ref/heads/metriplane-main-health-state") == 2
    for ruleset_id in ("1000", "2000", "3000", "4000"):
        assert calls.count(f"repos/Miko997/metriplane/rulesets/{ruleset_id}") == 2


def test_live_state_binding_rejects_stale_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stop_the_line,
        "validate_git_history",
        lambda _root: {"generation": 7, "state_commit": STATE_SHA},
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_get",
        lambda _path, _token: {
            "object": {"sha": GOOD_SHA, "type": "commit"},
            "ref": "refs/heads/metriplane-main-health-state",
        },
    )

    with pytest.raises(HealthError, match="does not match the live provider ref"):
        stop_the_line._github_live_state_binding(
            Path("state"), repository="Miko997/metriplane", token="token"
        )


@pytest.mark.parametrize(
    "current",
    [
        {"state_commit": GOOD_SHA, "state_generation": 7},
        {"state_commit": STATE_SHA, "state_generation": 8},
    ],
)
def test_owner_state_binding_rejects_movement_between_admission_and_merge(
    current: dict[str, object],
) -> None:
    with pytest.raises(HealthError, match="changed before merge"):
        stop_the_line._require_owner_state_binding(
            {"state_commit": STATE_SHA, "state_generation": 7}, current
        )


def test_post_merge_owner_capture_uses_provider_time_with_backward_local_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest: dict[str, object] = {
        "base_sha": BAD_SHA,
        "incident_digest": "f" * 64,
        "issue": "MET-999",
        "pull_request": "123",
        "repository": "Miko997/metriplane",
    }
    admission = _owner_admission(manifest, changed_paths=["tools/stop_the_line.py"])
    merge_gate = _owner_merge_gate(admission)
    pull = {
        "head": {"sha": REVIEWED_SHA},
        "merge_commit_sha": REPAIR_SHA,
        "merged_at": "2026-08-25T21:45:00Z",
        "merged_by": {"id": 100, "login": "Miko997"},
        "user": {"login": "Miko997"},
    }
    seen: dict[str, object] = {}
    provider_calls: list[str] = []

    def get(path: str, _token: str) -> object:
        if path.endswith("/pulls/123"):
            return pull
        if "/pulls/123/files?" in path:
            return []
        if path.endswith("/rulesets/1000"):
            return _core_ruleset()
        if path.endswith("/rulesets/2000"):
            return _main_health_ruleset()
        if path.endswith("/rulesets/3000"):
            return _state_protection_ruleset()
        if path.endswith("/rulesets/4000"):
            return _state_writer_ruleset()
        if path.endswith("/git/ref/heads/metriplane-main-health-state"):
            return {
                "object": {"sha": STATE_SHA, "type": "commit"},
                "ref": "refs/heads/metriplane-main-health-state",
            }
        if "/git/commits/" in path:
            return {}
        if path.endswith("/collaborators/Miko997/permission"):
            return {"permission": "admin"}
        raise AssertionError(path)

    def provider_now(token: str) -> object:
        provider_calls.append(token)
        return stop_the_line._timestamp("2026-08-25T21:46:00Z")

    def normalize(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"captured_at": kwargs["captured_at"]}

    monkeypatch.setattr(stop_the_line, "_github_get", get)
    monkeypatch.setattr(stop_the_line, "_github_manifest", lambda *_args: manifest)
    monkeypatch.setattr(
        stop_the_line, "_github_stable_collaboration_snapshot", lambda *_args: ([], [])
    )
    monkeypatch.setattr(stop_the_line, "_refetch_github_artifact", lambda **_kwargs: admission)
    monkeypatch.setattr(stop_the_line, "_github_provider_now", provider_now)
    monkeypatch.setattr(stop_the_line, "_utc_now", lambda: "2000-01-01T00:00:00Z")
    monkeypatch.setattr(stop_the_line, "github_owner_emergency_evidence", normalize)

    evidence = stop_the_line.capture_github_owner_emergency(
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest="f" * 64,
        admission=admission,
        merge_gate=merge_gate,
        token="token",
    )

    assert evidence["captured_at"] == "2026-08-25T21:46:00Z"
    assert seen["captured_at"] == "2026-08-25T21:46:00Z"
    assert provider_calls == ["token"]


def test_collaboration_snapshot_rejects_invitation_acceptance_during_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = {"id": 100, "login": "Miko997", "role_name": "admin"}
    reviewer = {"id": 200, "login": "reviewer", "role_name": "write"}
    invitation = {
        "id": 300,
        "invitee": {"login": "reviewer"},
        "permissions": "write",
    }
    responses = iter([[invitation], [owner], [], [owner, reviewer]])
    monkeypatch.setattr(stop_the_line, "_github_list", lambda *_args: next(responses))

    with pytest.raises(HealthError, match="changed during capture"):
        stop_the_line._github_stable_collaboration_snapshot("Miko997/metriplane", "token")


@pytest.mark.parametrize(
    ("final_state_commit", "thaw_writer", "failure"),
    [
        (STATE_SHA, False, None),
        (GOOD_SHA, False, "changed before merge"),
        (STATE_SHA, True, "not frozen"),
    ],
    ids=["state-stable", "state-moves-before-graphql", "state-thaws-before-graphql"],
)
def test_governed_owner_merge_uses_exact_head_pr_only_bypass(
    monkeypatch: pytest.MonkeyPatch,
    final_state_commit: str,
    thaw_writer: bool,
    failure: str | None,
) -> None:
    admission = _owner_admission(
        {
            "base_sha": BAD_SHA,
            "incident_digest": "f" * 64,
            "issue": "MET-999",
            "pull_request": "123",
            "repository": "Miko997/metriplane",
        },
        changed_paths=["tools/stop_the_line.py"],
    )
    artifact = admission["artifact"]
    assert isinstance(artifact, dict)
    pull_before = {
        "head": {"sha": REVIEWED_SHA},
        "merged": False,
        "node_id": "PR_node",
    }
    pull_after = {
        "base": {"sha": BAD_SHA},
        "head": {"sha": REVIEWED_SHA},
        "merge_commit_sha": REPAIR_SHA,
        "merged": True,
        "merged_at": "2026-08-25T21:45:00Z",
        "merged_by": {"id": 100, "login": "Miko997"},
    }
    pulls = iter([pull_before, pull_before, pull_after])
    state_writer_checks: list[str] = []

    def get(path: str, _token: str) -> object:
        if path.endswith("/pulls/123"):
            return next(pulls)
        if path.endswith("/collaborators/Miko997/permission"):
            return {"permission": "admin"}
        if path.endswith("/rulesets/1000"):
            return _core_ruleset()
        if path.endswith("/rulesets/2000"):
            return _main_health_ruleset()
        if path.endswith("/rulesets/3000"):
            return _state_protection_ruleset()
        if path.endswith("/rulesets/4000"):
            state_writer_checks.append("checked")
            state_writer = _state_writer_ruleset()
            if thaw_writer and len(state_writer_checks) == 3:
                state_writer["bypass_actors"] = [
                    {
                        "actor_id": 4722589,
                        "actor_type": "Integration",
                        "bypass_mode": "always",
                    }
                ]
            return state_writer
        if path.endswith(f"/git/commits/{REVIEWED_SHA}"):
            return {"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}}
        if path.endswith(f"/git/commits/{REPAIR_SHA}"):
            return {
                "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            }
        raise AssertionError(path)

    graphql: list[dict[str, object]] = []
    provider_times: list[str] = []
    state_checks: list[str] = []

    def merge_graphql(_query: str, variables: dict[str, object], _token: str) -> dict[str, object]:
        graphql.append(variables)
        return {
            "mergePullRequest": {
                "pullRequest": {
                    "id": "PR_node",
                    "merged": True,
                    "mergedAt": "2026-08-25T21:45:00Z",
                }
            }
        }

    def provider_now(_token: str) -> object:
        provider_times.append("checked")
        return stop_the_line._timestamp("2026-08-25T21:44:59Z")

    def live_state(*_args: object, **_kwargs: object) -> dict[str, object]:
        state_checks.append("checked")
        state_commit = final_state_commit if len(state_checks) == 3 else STATE_SHA
        return {"state_commit": state_commit, "state_generation": 7}

    monkeypatch.setattr(stop_the_line, "_github_live_state_binding", live_state)
    monkeypatch.setattr(stop_the_line, "_github_provider_now", provider_now)
    monkeypatch.setattr(stop_the_line, "_refetch_github_artifact", lambda **_kwargs: admission)
    monkeypatch.setattr(stop_the_line, "_github_get", get)
    monkeypatch.setattr(stop_the_line, "_github_graphql", merge_graphql)
    monkeypatch.setattr(stop_the_line, "_github_list", lambda *_args: [])
    monkeypatch.setattr(
        stop_the_line, "_github_stable_collaboration_snapshot", lambda *_args: ([], [])
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_manifest",
        lambda *_args: {"expires_at": "2026-08-26T22:00:00Z"},
    )
    monkeypatch.setattr(
        stop_the_line,
        "validate_owner_emergency_candidate",
        lambda *_args, **_kwargs: {**artifact, "checked_at": "2026-08-25T21:44:59Z"},
    )

    def call() -> dict[str, object]:
        return stop_the_line.merge_github_owner_emergency(
            root=Path("state"),
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest="f" * 64,
            admission_attestation=admission,
            token="token",
        )

    if failure is None:
        assert call() == _owner_merge_gate(admission)
        assert graphql == [
            {
                "input": {
                    "expectedHeadOid": REVIEWED_SHA,
                    "mergeMethod": "MERGE",
                    "pullRequestId": "PR_node",
                }
            }
        ]
    else:
        with pytest.raises(HealthError, match=failure):
            call()
        assert graphql == []
    assert provider_times == ["checked", "checked", "checked"]
    assert state_checks == ["checked", "checked", "checked"]
    expected_writer_checks = 2 if final_state_commit != STATE_SHA else 3
    assert state_writer_checks == ["checked"] * expected_writer_checks


def test_governed_owner_merge_recovers_after_provider_completed_and_client_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _owner_admission(
        {
            "base_sha": BAD_SHA,
            "incident_digest": "f" * 64,
            "issue": "MET-999",
            "pull_request": "123",
            "repository": "Miko997/metriplane",
        },
        changed_paths=["tools/stop_the_line.py"],
    )
    artifact = admission["artifact"]
    assert isinstance(artifact, dict)
    merged_pull = {
        "base": {"sha": BAD_SHA},
        "head": {"sha": REVIEWED_SHA},
        "merge_commit_sha": REPAIR_SHA,
        "merged": True,
        "merged_at": "2026-08-25T21:45:00Z",
        "merged_by": {"id": 100, "login": "Miko997"},
    }
    commit_fetches: list[str] = []

    def get(path: str, _token: str) -> object:
        if path.endswith("/pulls/123"):
            return merged_pull
        if path.endswith("/collaborators/Miko997/permission"):
            return {"permission": "admin"}
        if path.endswith("/rulesets/1000"):
            return _core_ruleset()
        if path.endswith("/rulesets/2000"):
            return _main_health_ruleset()
        if path.endswith("/rulesets/3000"):
            return _state_protection_ruleset()
        if path.endswith("/rulesets/4000"):
            return _state_writer_ruleset()
        if path.endswith(f"/git/commits/{REVIEWED_SHA}"):
            commit_fetches.append(REVIEWED_SHA)
            return {"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}}
        if path.endswith(f"/git/commits/{REPAIR_SHA}"):
            commit_fetches.append(REPAIR_SHA)
            return {
                "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            }
        raise AssertionError(path)

    monkeypatch.setattr(
        stop_the_line,
        "_github_live_state_binding",
        lambda *_args, **_kwargs: {"state_commit": STATE_SHA, "state_generation": 7},
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_provider_now",
        lambda _token: stop_the_line._timestamp("2026-08-26T21:44:59Z"),
    )
    monkeypatch.setattr(stop_the_line, "_refetch_github_artifact", lambda **_kwargs: admission)
    monkeypatch.setattr(stop_the_line, "_github_get", get)
    monkeypatch.setattr(stop_the_line, "_github_list", lambda *_args: [])
    monkeypatch.setattr(
        stop_the_line, "_github_stable_collaboration_snapshot", lambda *_args: ([], [])
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_manifest",
        lambda *_args: {"expires_at": "2026-08-26T22:00:00Z"},
    )
    monkeypatch.setattr(
        stop_the_line,
        "validate_owner_emergency_candidate",
        lambda *_args, **_kwargs: {**artifact, "checked_at": "2026-08-25T21:45:00Z"},
    )
    monkeypatch.setattr(
        stop_the_line,
        "_github_graphql",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not re-merge")),
    )

    assert stop_the_line.merge_github_owner_emergency(
        root=Path("state"),
        repository="Miko997/metriplane",
        pull_request="123",
        issue="MET-999",
        incident_digest="f" * 64,
        admission_attestation=admission,
        token="token",
    ) == _owner_merge_gate(admission)
    assert commit_fetches == [REVIEWED_SHA, REPAIR_SHA]


def test_provider_evidence_rejects_merge_from_a_different_base() -> None:
    incident_digest = "f" * 64
    approved = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {incident_digest}",
        "commit_id": REVIEWED_SHA,
        "id": 1,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T20:00:00Z",
        "user": {"id": 200, "login": "reviewer"},
    }
    with pytest.raises(HealthError, match="exact base"):
        github_approval_evidence(
            pull={
                "base": {"sha": GOOD_SHA},
                "changed_files": 1,
                "head": {"sha": REVIEWED_SHA},
                "merge_commit_sha": REPAIR_SHA,
                "merged": True,
                "merged_at": "2026-08-25T21:00:00Z",
                "user": {"id": 100, "login": "author"},
            },
            review=approved,
            reviews=[approved],
            files=[{"filename": "metriplane/fix.py", "status": "modified"}],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": BAD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            reviewer_permissions={"reviewer": "write"},
            captured_at="2026-08-25T21:00:00Z",
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest=incident_digest,
        )


def test_provider_evidence_rejects_reversed_merge_parents() -> None:
    incident_digest = "f" * 64
    approved = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {incident_digest}",
        "commit_id": REVIEWED_SHA,
        "id": 1,
        "state": "APPROVED",
        "submitted_at": "2026-08-25T20:00:00Z",
        "user": {"id": 200, "login": "reviewer"},
    }
    with pytest.raises(HealthError, match="exact base"):
        github_approval_evidence(
            pull={
                "base": {"sha": GOOD_SHA},
                "changed_files": 1,
                "head": {"sha": REVIEWED_SHA},
                "merge_commit_sha": REPAIR_SHA,
                "merged": True,
                "merged_at": "2026-08-25T21:00:00Z",
                "user": {"id": 100, "login": "author"},
            },
            review=approved,
            reviews=[approved],
            files=[{"filename": "metriplane/fix.py", "status": "modified"}],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": REVIEWED_SHA}, {"sha": GOOD_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            reviewer_permissions={"reviewer": "write"},
            captured_at="2026-08-25T21:00:00Z",
            repository="Miko997/metriplane",
            pull_request="123",
            issue="MET-999",
            incident_digest=incident_digest,
        )


def test_review_reduction_preserves_authorized_changes_requested() -> None:
    incident_digest = "f" * 64
    approved = {
        "body": f"Main-health repair authorization: MET-999\nIncident: {incident_digest}",
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
    commented = {
        **approved,
        "body": "A later non-decisive comment",
        "id": 3,
        "state": "COMMENTED",
        "submitted_at": "2026-08-25T20:02:00Z",
    }
    outsider = {
        **requested,
        "id": 4,
        "user": {"id": 300, "login": "outsider"},
    }
    kwargs = {
        "pull": {
            "base": {"sha": GOOD_SHA},
            "changed_files": 1,
            "head": {"sha": REVIEWED_SHA},
            "merge_commit_sha": REPAIR_SHA,
            "merged": True,
            "merged_at": "2026-08-25T21:00:00Z",
            "user": {"id": 100, "login": "author"},
        },
        "files": [{"filename": "metriplane/fix.py", "status": "modified"}],
        "head_commit": {"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
        "merge_commit": {
            "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
            "sha": REPAIR_SHA,
            "tree": {"sha": TREE_SHA},
        },
        "repository": "Miko997/metriplane",
        "pull_request": "123",
        "issue": "MET-999",
        "incident_digest": incident_digest,
    }
    with pytest.raises(HealthError, match="superseded|requested changes"):
        github_approval_evidence(
            review=approved,
            reviews=[approved, requested, commented],
            reviewer_permissions={"reviewer": "write"},
            captured_at="2026-08-25T21:00:00Z",
            **kwargs,  # type: ignore[arg-type]
        )
    evidence = github_approval_evidence(
        review=approved,
        reviews=[approved, outsider],
        reviewer_permissions={"outsider": "none", "reviewer": "write"},
        captured_at="2026-08-25T21:00:00Z",
        **kwargs,  # type: ignore[arg-type]
    )
    assert evidence["state"] == "APPROVED"
    with pytest.raises(HealthError, match="capture predates"):
        github_approval_evidence(
            review=approved,
            reviews=[approved],
            reviewer_permissions={"reviewer": "write"},
            captured_at="2026-08-25T19:59:59Z",
            **kwargs,  # type: ignore[arg-type]
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
                "base": {"sha": GOOD_SHA},
                "changed_files": 1,
                "head": {"sha": REVIEWED_SHA},
                "merge_commit_sha": REPAIR_SHA,
                "merged": True,
                "merged_at": "2026-08-25T21:00:00Z",
                "user": {"id": 100, "login": "author"},
            },
            review=approved,
            reviews=[approved, requested],
            files=[{"filename": "metriplane/fix.py", "status": "modified"}],
            head_commit={"sha": REVIEWED_SHA, "tree": {"sha": TREE_SHA}},
            merge_commit={
                "parents": [{"sha": GOOD_SHA}, {"sha": REVIEWED_SHA}],
                "sha": REPAIR_SHA,
                "tree": {"sha": TREE_SHA},
            },
            reviewer_permissions={"reviewer": "write"},
            captured_at="2026-08-25T21:00:00Z",
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
        "admission": None,
        "admission_digest": None,
        "authorization_mode": "independent-review",
        "approval_id": "321",
        "approval_provider": "github",
        "author": "author",
        "author_id": "100",
        "base_sha": BAD_SHA,
        "captured_at": "2026-08-25T21:30:00Z",
        "changed_paths": ["metriplane/fix.py"],
        "collaborators": None,
        "decision_at": "2026-08-25T21:29:00Z",
        "head_sha": REVIEWED_SHA,
        "incident_digest": incident_digest,
        "issue": "MET-999",
        "manifest": None,
        "manifest_digest": None,
        "pending_invitations": None,
        "merge_commit_sha": REPAIR_SHA,
        "merge_parent_shas": [GOOD_SHA, REVIEWED_SHA],
        "merge_tree_sha": TREE_SHA,
        "pull_request": "123",
        "repository": "Miko997/metriplane",
        "reviewed_tree_sha": TREE_SHA,
        "reviewer": "reviewer",
        "reviewer_id": "200",
        "reviewer_permission": "write",
        "merge_gate": None,
        "merge_gate_digest": None,
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
        "manifest_digest": None,
        "policy_amendment_digest": None,
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


def test_git_history_rejects_a_fast_forward_whole_tree_replacement(tmp_path: Path) -> None:
    root = tmp_path / "state"
    replacement = tmp_path / "replacement"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True
    )
    for generation in range(2):
        ingest(
            root,
            scope="main",
            summary=_summary(GOOD_SHA),
            activation_policy=POLICY,
            expected_generation=-1 if generation == 0 else generation,
        )
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", f"generation {generation + 1}"],
            check=True,
        )
    assert validate_git_history(root)["generation"] == 2

    ungoverned = tmp_path / "ungoverned"
    shutil.copytree(root, ungoverned)
    ingest(
        ungoverned,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=2,
    )
    (ungoverned / "results/unvalidated-payload.bin").write_bytes(b"not governed")
    subprocess.run(["git", "-C", str(ungoverned), "add", "--all"], check=True)
    subprocess.run(
        ["git", "-C", str(ungoverned), "commit", "-qm", "add ungoverned payload"], check=True
    )
    with pytest.raises(HealthError, match="ungoverned|rewrites immutable"):
        validate_git_history(ungoverned)

    ingest(
        replacement,
        scope="main",
        summary=_summary(BAD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    for path in root.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in replacement.iterdir():
        target = root / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "replace complete state tree"], check=True
    )
    assert validate_history(root)["generation"] == 1
    with pytest.raises(
        HealthError,
        match="does not match its generations|exactly one generation|rewrites immutable",
    ):
        validate_git_history(root)


def test_git_history_rejects_evidence_committed_before_its_generation(tmp_path: Path) -> None:
    root = tmp_path / "state"
    future = tmp_path / "future"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True
    )
    ingest(
        root,
        scope="main",
        summary=_summary(GOOD_SHA),
        activation_policy=POLICY,
        expected_generation=-1,
    )
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "generation 1"], check=True)

    ingest(
        root,
        scope="main",
        summary=_summary(GOOD_SHA, recorded_at="2026-08-25T19:00:00Z", run_id="2"),
        activation_policy=POLICY,
        expected_generation=1,
    )
    shutil.copytree(root, future, ignore=shutil.ignore_patterns(".git"))
    ingest(
        future,
        scope="main",
        summary=_summary(GOOD_SHA, recorded_at="2026-08-25T20:00:00Z", run_id="3"),
        activation_policy=POLICY,
        expected_generation=2,
    )
    root_files = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
    for source in future.rglob("*"):
        relative = source.relative_to(future)
        if source.is_file() and relative not in root_files and relative != Path("state.json"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "generation 2 plus future evidence"],
        check=True,
    )
    shutil.copy2(future / "state.json", root / "state.json")
    subprocess.run(["git", "-C", str(root), "add", "state.json"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "generation 3 pointer"], check=True)

    assert validate_history(root)["generation"] == 3
    with pytest.raises(HealthError, match="complete history|invalid generation evidence"):
        validate_git_history(root)


def test_git_history_rejects_an_invalid_intermediate_state_pointer(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True
    )
    for generation in (1, 2):
        ingest(
            root,
            scope="main",
            summary=_summary(
                GOOD_SHA,
                recorded_at=f"2026-08-25T{17 + generation:02d}:00:00Z",
                run_id=str(generation),
            ),
            activation_policy=POLICY,
            expected_generation=-1 if generation == 1 else generation - 1,
        )
        if generation == 2:
            valid_state = (root / "state.json").read_bytes()
            state = json.loads(valid_state)
            state["history_head"] = "f" * 64
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", f"generation {generation}"], check=True
        )

    (root / "state.json").write_bytes(valid_state)
    ingest(
        root,
        scope="main",
        summary=_summary(GOOD_SHA, recorded_at="2026-08-25T20:00:00Z", run_id="3"),
        activation_policy=POLICY,
        expected_generation=2,
    )
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "generation 3"], check=True)

    assert validate_history(root)["generation"] == 3
    with pytest.raises(HealthError, match="invalid generation pointer"):
        validate_git_history(root)


def test_schema_policy_and_example_families_are_complete_json() -> None:
    names = {
        "main-health-history-activation-policy",
        "main-health-history-activation",
        "main-health-history",
        "main-health-incident",
        "main-health-owner-emergency",
        "main-health-policy-amendment",
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
    provider = json.loads(
        (STATUS / "examples/main-health-provider-evidence.json").read_text(encoding="utf-8")
    )
    authorization = json.loads(
        (STATUS / "examples/main-health-repair-authorization.json").read_text(encoding="utf-8")
    )
    resolution = json.loads(
        (STATUS / "examples/main-health-resolution.json").read_text(encoding="utf-8")
    )
    assert authorization["approval_digest"] == digest(provider)
    assert authorization["changed_paths_digest"] == digest(provider["changed_paths"])
    assert resolution["authorization_digest"] == digest(authorization)
    authorization_schema = json.loads(
        (STATUS / "schemas/main-health-repair-authorization.schema.json").read_text(
            encoding="utf-8"
        )
    )
    resolution_schema = json.loads(
        (STATUS / "schemas/main-health-resolution.schema.json").read_text(encoding="utf-8")
    )
    mismatched_authorization = {
        **authorization,
        "authorization_mode": "single-maintainer-owner-emergency",
    }
    with pytest.raises(SnapshotError):
        _internal_validate(mismatched_authorization, authorization_schema)
    mismatched_resolution = {
        **resolution,
        "authorization_mode": "single-maintainer-owner-emergency",
    }
    with pytest.raises(SnapshotError):
        _internal_validate(mismatched_resolution, resolution_schema)
