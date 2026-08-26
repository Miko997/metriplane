# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import pytest

from tools.check_met77_transition import (
    ACTIONS_INTEGRATION_ID,
    CANONICAL_ACTOR,
    CANONICAL_API_URL,
    CANONICAL_OWNER,
    CANONICAL_REPOSITORY,
    EXPECTED_BASE_SHA,
    EXPECTED_PULL_REQUEST,
    ChecksPendingError,
    GitHubChecksClient,
    TransitionContext,
    TransitionValidationError,
    context_from_environment,
    validate_check_runs,
    validate_transition_context,
    wait_for_required_checks,
)

HEAD_SHA = "a" * 40


def _context() -> TransitionContext:
    return TransitionContext(
        actor=CANONICAL_ACTOR,
        api_url=CANONICAL_API_URL,
        approved_head_sha=HEAD_SHA,
        base_ref="main",
        base_sha=EXPECTED_BASE_SHA,
        checkout_sha=HEAD_SHA,
        event_name="pull_request",
        head_repository=CANONICAL_REPOSITORY,
        head_sha=HEAD_SHA,
        pr_author=CANONICAL_OWNER,
        pr_number=EXPECTED_PULL_REQUEST,
        repository=CANONICAL_REPOSITORY,
        repository_owner=CANONICAL_OWNER,
    )


def _check_run(
    name: str,
    identifier: int,
    *,
    app_id: int = ACTIONS_INTEGRATION_ID,
    completed_at: str | None = "2026-08-26T19:10:20Z",
    conclusion: str | None = "success",
    head_sha: str = HEAD_SHA,
    started_at: str = "2026-08-26T19:10:00Z",
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "app": {"id": app_id, "slug": "github-actions"},
        "completed_at": completed_at,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "id": identifier,
        "name": name,
        "started_at": started_at,
        "status": status,
    }


def _successful_payload() -> dict[str, Any]:
    runs = [
        _check_run("Metriplane / required", 101),
        _check_run("Documentation / required", 201),
        _check_run("Security / required", 301),
    ]
    return {"check_runs": runs, "total_count": len(runs)}


def test_exact_provider_approval_and_checkout_are_required() -> None:
    validate_transition_context(_context())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", "reviewer"),
        ("api_url", "https://example.invalid"),
        ("base_ref", "release"),
        ("base_sha", "b" * 40),
        ("event_name", "push"),
        ("head_repository", "fork/metriplane"),
        ("pr_author", "contributor"),
        ("pr_number", "87"),
        ("repository", "Miko997/other"),
        ("repository_owner", "other"),
    ],
)
def test_noncanonical_transition_context_fails_closed(field: str, value: str) -> None:
    context = replace(_context(), **{field: value})
    with pytest.raises(TransitionValidationError):
        validate_transition_context(context)


@pytest.mark.parametrize(
    "context",
    [
        replace(_context(), approved_head_sha=""),
        replace(_context(), approved_head_sha="b" * 40),
        replace(_context(), checkout_sha="b" * 40),
        replace(_context(), head_sha="not-a-sha"),
        replace(
            _context(),
            approved_head_sha=EXPECTED_BASE_SHA,
            checkout_sha=EXPECTED_BASE_SHA,
            head_sha=EXPECTED_BASE_SHA,
        ),
    ],
)
def test_unapproved_or_inexact_head_fails_closed(context: TransitionContext) -> None:
    with pytest.raises(TransitionValidationError):
        validate_transition_context(context)


def test_environment_loader_requires_every_provider_binding() -> None:
    environment = {
        "GITHUB_ACTOR": CANONICAL_ACTOR,
        "GITHUB_API_URL": CANONICAL_API_URL,
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": CANONICAL_REPOSITORY,
        "GITHUB_REPOSITORY_OWNER": CANONICAL_OWNER,
        "MET77_APPROVED_HEAD_SHA": HEAD_SHA,
        "MET77_BASE_REF": "main",
        "MET77_BASE_SHA": EXPECTED_BASE_SHA,
        "MET77_HEAD_REPOSITORY": CANONICAL_REPOSITORY,
        "MET77_HEAD_SHA": HEAD_SHA,
        "MET77_PR_AUTHOR": CANONICAL_OWNER,
        "MET77_PR_NUMBER": EXPECTED_PULL_REQUEST,
    }
    assert context_from_environment(environment, checkout_sha=HEAD_SHA) == _context()
    del environment["MET77_APPROVED_HEAD_SHA"]
    with pytest.raises(TransitionValidationError, match="environment is incomplete"):
        context_from_environment(environment, checkout_sha=HEAD_SHA)


def test_latest_unambiguous_actions_attempt_is_selected() -> None:
    payload = _successful_payload()
    payload["check_runs"].insert(
        0,
        _check_run(
            "Metriplane / required",
            100,
            completed_at="2026-08-26T19:09:20Z",
            started_at="2026-08-26T19:09:00Z",
        ),
    )
    payload["total_count"] = len(payload["check_runs"])
    result = validate_check_runs(payload, expected_sha=HEAD_SHA)
    assert result["result"] == "success"
    assert result["head_sha"] == HEAD_SHA
    assert result["checks"]["Metriplane / required"]["check_run_id"] == 101


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ([], "not an object"),
        ({"check_runs": [], "total_count": True}, "total_count"),
        ({"check_runs": {}, "total_count": 0}, "inventory"),
        ({"check_runs": [], "total_count": 1}, "inventory"),
        ({"check_runs": [None], "total_count": 1}, "entry"),
    ],
)
def test_malformed_provider_inventory_fails_closed(payload: object, match: str) -> None:
    with pytest.raises(TransitionValidationError, match=match):
        validate_check_runs(payload, expected_sha=HEAD_SHA)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("id", 0, "positive integer"),
        ("name", " Metriplane / required", "invalid name"),
        ("head_sha", "b" * 40, "expected exact head"),
        ("status", "unknown", "invalid status"),
        ("conclusion", "unknown", "invalid conclusion"),
        ("started_at", "not-a-time", "provider timestamp"),
        ("completed_at", "not-a-time", "provider timestamp"),
        ("app", None, "App identity"),
    ],
)
def test_malformed_check_record_fails_closed(field: str, value: object, match: str) -> None:
    payload = _successful_payload()
    payload["check_runs"][0][field] = value
    with pytest.raises(TransitionValidationError, match=match):
        validate_check_runs(payload, expected_sha=HEAD_SHA)


def test_terminal_and_nonterminal_shapes_are_strict() -> None:
    payload = _successful_payload()
    payload["check_runs"][0]["completed_at"] = None
    with pytest.raises(TransitionValidationError, match="incomplete terminal evidence"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload = _successful_payload()
    payload["check_runs"][0].update(status="in_progress", completed_at=None)
    with pytest.raises(TransitionValidationError, match="non-terminal.*terminal evidence"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload = _successful_payload()
    payload["check_runs"][0]["completed_at"] = "2026-08-26T19:09:59Z"
    with pytest.raises(TransitionValidationError, match="before its provider start"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)


def test_duplicate_id_wrong_app_and_ambiguous_attempts_fail_closed() -> None:
    payload = _successful_payload()
    payload["check_runs"][1]["id"] = 101
    with pytest.raises(TransitionValidationError, match="repeated a check-run ID"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload = _successful_payload()
    payload["check_runs"][0]["app"]["id"] = 7
    with pytest.raises(TransitionValidationError, match="non-Actions producer"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload = _successful_payload()
    payload["check_runs"].append(_check_run("Metriplane / required", 102))
    payload["total_count"] += 1
    with pytest.raises(TransitionValidationError, match="chronology is ambiguous"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload["check_runs"][-1]["started_at"] = "2026-08-26T19:09:59Z"
    with pytest.raises(TransitionValidationError, match="chronology is ambiguous"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)


def test_missing_or_running_latest_check_is_pending_and_cannot_be_masked() -> None:
    payload = _successful_payload()
    payload["check_runs"] = payload["check_runs"][:-1]
    payload["total_count"] -= 1
    with pytest.raises(ChecksPendingError, match="Security / required.*missing"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)

    payload = _successful_payload()
    payload["check_runs"].append(
        _check_run(
            "Metriplane / required",
            102,
            completed_at=None,
            conclusion=None,
            started_at="2026-08-26T19:11:00Z",
            status="in_progress",
        )
    )
    payload["total_count"] += 1
    with pytest.raises(ChecksPendingError, match="latest exact Actions check is in_progress"):
        validate_check_runs(payload, expected_sha=HEAD_SHA)


def test_latest_failed_check_fails_without_polling() -> None:
    payload = _successful_payload()
    payload["check_runs"].append(
        _check_run(
            "Metriplane / required",
            102,
            completed_at="2026-08-26T19:11:20Z",
            conclusion="failure",
            started_at="2026-08-26T19:11:00Z",
        )
    )
    payload["total_count"] += 1
    with pytest.raises(TransitionValidationError, match="concluded 'failure'"):
        wait_for_required_checks(
            lambda: payload,
            expected_sha=HEAD_SHA,
            attempts=3,
            interval_seconds=0,
        )


def test_bounded_polling_retries_pending_checks_and_transport() -> None:
    missing = _successful_payload()
    missing["check_runs"] = missing["check_runs"][:-1]
    missing["total_count"] -= 1
    responses: list[object] = [
        ChecksPendingError("temporary transport failure"),
        missing,
        _successful_payload(),
    ]
    sleeps: list[float] = []

    def fetch() -> object:
        value = responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    result = wait_for_required_checks(
        fetch,
        expected_sha=HEAD_SHA,
        attempts=3,
        interval_seconds=0.25,
        sleep=sleeps.append,
    )
    assert result["result"] == "success"
    assert sleeps == [0.25, 0.25]


def test_bounded_polling_fails_closed_at_deadline() -> None:
    missing = _successful_payload()
    missing["check_runs"] = missing["check_runs"][:-1]
    missing["total_count"] -= 1
    with pytest.raises(TransitionValidationError, match="did not settle after 2 provider reads"):
        wait_for_required_checks(
            lambda: missing,
            expected_sha=HEAD_SHA,
            attempts=2,
            interval_seconds=0,
        )


def test_checks_client_reads_complete_stable_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GitHubChecksClient(
        api_url=CANONICAL_API_URL,
        repository=CANONICAL_REPOSITORY,
        token="read-only-token",
    )
    first = [_check_run(f"other-{index}", index + 1) for index in range(100)]
    second = [_check_run("other-final", 101)]
    pages: list[object] = [
        {"check_runs": first, "total_count": 101},
        {"check_runs": second, "total_count": 101},
    ]
    requested: list[str] = []

    def request_json(url: str) -> object:
        requested.append(url)
        return pages.pop(0)

    monkeypatch.setattr(client, "_request_json", request_json)
    result = client.fetch(head_sha=HEAD_SHA)
    assert result["total_count"] == 101
    assert len(result["check_runs"]) == 101
    assert requested[0].endswith("filter=all&per_page=100&page=1")
    assert requested[1].endswith("filter=all&per_page=100&page=2")


def test_checks_client_rejects_provider_changes_between_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GitHubChecksClient(
        api_url=CANONICAL_API_URL,
        repository=CANONICAL_REPOSITORY,
        token="read-only-token",
    )
    pages: list[object] = [
        {"check_runs": [{} for _ in range(100)], "total_count": 101},
        {"check_runs": [{}], "total_count": 102},
    ]
    monkeypatch.setattr(client, "_request_json", lambda _url: pages.pop(0))
    with pytest.raises(TransitionValidationError, match="changed during pagination"):
        client.fetch(head_sha=HEAD_SHA)


def test_provider_fixtures_are_not_mutated() -> None:
    payload = _successful_payload()
    original = copy.deepcopy(payload)
    validate_check_runs(payload, expected_sha=HEAD_SHA)
    assert payload == original
