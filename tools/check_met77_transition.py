# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate the one-use MET-77 transition terminal against GitHub provider state."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

ACTIONS_INTEGRATION_ID = 15368
APPROVAL_VARIABLE = "MET77_APPROVED_HEAD_SHA"
CANONICAL_ACTOR = "Miko997"
CANONICAL_API_URL = "https://api.github.com"
CANONICAL_OWNER = "Miko997"
CANONICAL_REPOSITORY = "Miko997/metriplane"
EXPECTED_BASE_SHA = "9d5b4ffa5236521423196a84acc6a613f7f13108"
EXPECTED_PULL_REQUEST = "86"
PER_PAGE = 100
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
REQUIRED_CHECKS = (
    "Metriplane / required",
    "Documentation / required",
    "Security / required",
)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
CHECK_STATUSES = {"completed", "in_progress", "pending", "queued", "requested", "waiting"}
CHECK_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "startup_failure",
    "success",
    "timed_out",
}


class TransitionValidationError(ValueError):
    """The one-use transition cannot truthfully report success."""


class ChecksPendingError(RuntimeError):
    """Provider checks are not terminal yet and may be polled again."""


@dataclass(frozen=True)
class TransitionContext:
    """Provider-owned event and approval values bound by the transition."""

    actor: str
    approved_head_sha: str
    base_ref: str
    base_sha: str
    checkout_sha: str
    event_name: str
    head_repository: str
    head_sha: str
    pr_author: str
    pr_number: str
    repository: str
    repository_owner: str
    api_url: str


@dataclass(frozen=True)
class CheckEvidence:
    """Validated provider identity and chronology for one check run."""

    app_id: int
    completed_at: datetime | None
    conclusion: str | None
    head_sha: str
    identifier: int
    name: str
    started_at: datetime
    status: str


def _require_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise TransitionValidationError(f"{field} is not a lowercase 40-character SHA")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TransitionValidationError(f"{field} is not a positive integer")
    return value


def _require_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TransitionValidationError(f"{field} is not a UTC provider timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TransitionValidationError(f"{field} is not a valid provider timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise TransitionValidationError(f"{field} is not a UTC provider timestamp")
    return parsed


def validate_transition_context(context: TransitionContext) -> None:
    """Bind the run to the sole governed pull request and provider-held approval."""
    expected = {
        "actor": (context.actor, CANONICAL_ACTOR),
        "API URL": (context.api_url, CANONICAL_API_URL),
        "base ref": (context.base_ref, "main"),
        "base SHA": (context.base_sha, EXPECTED_BASE_SHA),
        "event": (context.event_name, "pull_request"),
        "head repository": (context.head_repository, CANONICAL_REPOSITORY),
        "pull-request author": (context.pr_author, CANONICAL_OWNER),
        "pull-request number": (context.pr_number, EXPECTED_PULL_REQUEST),
        "repository": (context.repository, CANONICAL_REPOSITORY),
        "repository owner": (context.repository_owner, CANONICAL_OWNER),
    }
    mismatches = [
        f"{field} is {actual!r}, expected {wanted!r}"
        for field, (actual, wanted) in expected.items()
        if actual != wanted
    ]
    if mismatches:
        raise TransitionValidationError("; ".join(mismatches))

    head_sha = _require_sha(context.head_sha, "event head SHA")
    approved_sha = _require_sha(context.approved_head_sha, f"{APPROVAL_VARIABLE} approval")
    checkout_sha = _require_sha(context.checkout_sha, "checked-out SHA")
    if approved_sha != head_sha:
        raise TransitionValidationError(
            f"event head {head_sha} does not equal provider approval {approved_sha}"
        )
    if checkout_sha != head_sha:
        raise TransitionValidationError(
            f"checked-out SHA {checkout_sha} does not equal approved event head {head_sha}"
        )
    if head_sha == EXPECTED_BASE_SHA:
        raise TransitionValidationError("approved head does not advance the governed base")


def _check_evidence(value: object, *, expected_sha: str) -> CheckEvidence:
    if not isinstance(value, dict):
        raise TransitionValidationError("provider check-run entry is not an object")
    identifier = _require_positive_int(value.get("id"), "check-run ID")
    name = value.get("name")
    if not isinstance(name, str) or not name or name.strip() != name:
        raise TransitionValidationError(f"check run {identifier} has an invalid name")
    head_sha = _require_sha(value.get("head_sha"), f"check run {identifier} head SHA")
    if head_sha != expected_sha:
        raise TransitionValidationError(
            f"check run {identifier} targets {head_sha}, expected exact head {expected_sha}"
        )
    status = value.get("status")
    if not isinstance(status, str) or status not in CHECK_STATUSES:
        raise TransitionValidationError(f"check run {identifier} has an invalid status")
    conclusion = value.get("conclusion")
    if conclusion is not None and (
        not isinstance(conclusion, str) or conclusion not in CHECK_CONCLUSIONS
    ):
        raise TransitionValidationError(f"check run {identifier} has an invalid conclusion")
    started_at = _require_timestamp(value.get("started_at"), f"check run {identifier} started_at")
    completed_value = value.get("completed_at")
    completed_at = (
        None
        if completed_value is None
        else _require_timestamp(completed_value, f"check run {identifier} completed_at")
    )
    if status == "completed":
        if conclusion is None or completed_at is None:
            raise TransitionValidationError(
                f"completed check run {identifier} has incomplete terminal evidence"
            )
        if completed_at < started_at:
            raise TransitionValidationError(
                f"check run {identifier} completes before its provider start time"
            )
    elif conclusion is not None or completed_at is not None:
        raise TransitionValidationError(
            f"non-terminal check run {identifier} exposes terminal evidence"
        )
    app = value.get("app")
    if not isinstance(app, dict):
        raise TransitionValidationError(f"check run {identifier} has no provider App identity")
    app_id = _require_positive_int(app.get("id"), f"check run {identifier} App ID")
    return CheckEvidence(
        app_id=app_id,
        completed_at=completed_at,
        conclusion=conclusion,
        head_sha=head_sha,
        identifier=identifier,
        name=name,
        started_at=started_at,
        status=status,
    )


def validate_check_runs(payload: object, *, expected_sha: str) -> dict[str, Any]:
    """Select unambiguous latest Actions attempts and require exact terminal success."""
    expected_sha = _require_sha(expected_sha, "expected check-run SHA")
    if not isinstance(payload, dict):
        raise TransitionValidationError("provider check-run response is not an object")
    total_count = payload.get("total_count")
    check_runs = payload.get("check_runs")
    if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
        raise TransitionValidationError("provider check-run total_count is invalid")
    if not isinstance(check_runs, list) or total_count != len(check_runs):
        raise TransitionValidationError("provider check-run inventory is incomplete or malformed")

    evidence = [_check_evidence(item, expected_sha=expected_sha) for item in check_runs]
    identifiers = [item.identifier for item in evidence]
    if len(identifiers) != len(set(identifiers)):
        raise TransitionValidationError("provider repeated a check-run ID")

    selected: dict[str, CheckEvidence] = {}
    pending: list[str] = []
    for name in REQUIRED_CHECKS:
        named = [item for item in evidence if item.name == name]
        wrong_app = [item.identifier for item in named if item.app_id != ACTIONS_INTEGRATION_ID]
        if wrong_app:
            raise TransitionValidationError(
                f"{name}: provider exposes non-Actions producer(s) {wrong_app!r}"
            )
        attempts = sorted(named, key=lambda item: item.identifier)
        if not attempts:
            pending.append(f"{name}: exact Actions check is missing")
            continue
        for previous, current in pairwise(attempts):
            if current.started_at <= previous.started_at:
                raise TransitionValidationError(
                    f"{name}: provider attempt chronology is ambiguous or inverted"
                )
        latest = attempts[-1]
        if latest.status != "completed":
            pending.append(f"{name}: latest exact Actions check is {latest.status}")
            continue
        if latest.conclusion != "success":
            raise TransitionValidationError(
                f"{name}: latest exact Actions check concluded {latest.conclusion!r}"
            )
        selected[name] = latest

    if pending:
        raise ChecksPendingError("; ".join(pending))
    checks: dict[str, dict[str, object]] = {}
    for name in REQUIRED_CHECKS:
        item = selected[name]
        if item.completed_at is None:
            raise TransitionValidationError(f"{name}: selected success has no completion time")
        checks[name] = {
            "check_run_id": item.identifier,
            "completed_at": item.completed_at.isoformat().replace("+00:00", "Z"),
        }
    return {
        "checks": checks,
        "head_sha": expected_sha,
        "integration_id": ACTIONS_INTEGRATION_ID,
        "result": "success",
        "schema_version": 1,
    }


class GitHubChecksClient:
    """Read a complete, bounded check-run inventory from the GitHub REST provider."""

    def __init__(
        self,
        *,
        api_url: str,
        repository: str,
        token: str,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.repository = repository
        self.token = token
        self.timeout_seconds = timeout_seconds

    def _request_json(self, url: str) -> object:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "metriplane-met77-transition",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise TransitionValidationError(
                        f"GitHub checks API returned unexpected HTTP {response.status}"
                    )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {408, 425, 429} or 500 <= exc.code <= 599:
                raise ChecksPendingError(
                    f"GitHub checks API returned retryable HTTP {exc.code}"
                ) from exc
            raise TransitionValidationError(f"GitHub checks API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ChecksPendingError(
                f"GitHub checks API is temporarily unavailable: {exc}"
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TransitionValidationError("GitHub checks API response exceeds the safety bound")
        try:
            return json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TransitionValidationError("GitHub checks API returned malformed JSON") from exc

    def fetch(self, *, head_sha: str) -> dict[str, Any]:
        """Fetch every check run with stable total-count pagination."""
        head_sha = _require_sha(head_sha, "checks API head SHA")
        encoded_repository = urllib.parse.quote(self.repository, safe="/")
        all_runs: list[object] = []
        expected_total: int | None = None
        for page in range(1, MAX_PAGES + 1):
            url = (
                f"{self.api_url}/repos/{encoded_repository}/commits/{head_sha}/check-runs"
                f"?filter=all&per_page={PER_PAGE}&page={page}"
            )
            payload = self._request_json(url)
            if not isinstance(payload, dict):
                raise TransitionValidationError("GitHub checks page is not an object")
            total_count = payload.get("total_count")
            batch = payload.get("check_runs")
            if (
                isinstance(total_count, bool)
                or not isinstance(total_count, int)
                or total_count < 0
                or not isinstance(batch, list)
                or len(batch) > PER_PAGE
            ):
                raise TransitionValidationError("GitHub checks page has an invalid shape")
            if total_count > MAX_PAGES * PER_PAGE:
                raise TransitionValidationError(
                    "GitHub checks inventory exceeds the pagination bound"
                )
            if expected_total is None:
                expected_total = total_count
            elif total_count != expected_total:
                raise TransitionValidationError("GitHub checks inventory changed during pagination")
            all_runs.extend(batch)
            if len(all_runs) == expected_total:
                return {"check_runs": all_runs, "total_count": expected_total}
            if len(all_runs) > expected_total or len(batch) < PER_PAGE:
                raise TransitionValidationError(
                    "GitHub checks pagination is incomplete or ambiguous"
                )
        raise TransitionValidationError("GitHub checks pagination exceeded its safety bound")


def wait_for_required_checks(
    fetch: Callable[[], object],
    *,
    expected_sha: str,
    attempts: int,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll boundedly while checks are missing, running, or provider transport retries."""
    if attempts < 1 or attempts > 120:
        raise TransitionValidationError("poll attempts must be between 1 and 120")
    if interval_seconds < 0 or interval_seconds > 60:
        raise TransitionValidationError("poll interval must be between 0 and 60 seconds")
    last_pending = "required checks did not appear"
    for attempt in range(1, attempts + 1):
        try:
            return validate_check_runs(fetch(), expected_sha=expected_sha)
        except ChecksPendingError as exc:
            last_pending = str(exc)
            if attempt < attempts:
                sleep(interval_seconds)
    raise TransitionValidationError(
        f"required checks did not settle after {attempts} provider reads: {last_pending}"
    )


def context_from_environment(
    environment: Mapping[str, str], *, checkout_sha: str
) -> TransitionContext:
    """Load only provider-owned GitHub context and the repository approval variable."""
    required = {
        "GITHUB_ACTOR",
        "GITHUB_API_URL",
        "GITHUB_EVENT_NAME",
        "GITHUB_REPOSITORY",
        "GITHUB_REPOSITORY_OWNER",
        "MET77_APPROVED_HEAD_SHA",
        "MET77_BASE_REF",
        "MET77_BASE_SHA",
        "MET77_HEAD_REPOSITORY",
        "MET77_HEAD_SHA",
        "MET77_PR_AUTHOR",
        "MET77_PR_NUMBER",
    }
    missing = sorted(name for name in required if name not in environment)
    if missing:
        raise TransitionValidationError(f"transition environment is incomplete: {missing!r}")
    return TransitionContext(
        actor=environment["GITHUB_ACTOR"],
        api_url=environment["GITHUB_API_URL"],
        approved_head_sha=environment["MET77_APPROVED_HEAD_SHA"],
        base_ref=environment["MET77_BASE_REF"],
        base_sha=environment["MET77_BASE_SHA"],
        checkout_sha=checkout_sha,
        event_name=environment["GITHUB_EVENT_NAME"],
        head_repository=environment["MET77_HEAD_REPOSITORY"],
        head_sha=environment["MET77_HEAD_SHA"],
        pr_author=environment["MET77_PR_AUTHOR"],
        pr_number=environment["MET77_PR_NUMBER"],
        repository=environment["GITHUB_REPOSITORY"],
        repository_owner=environment["GITHUB_REPOSITORY_OWNER"],
    )


def _checkout_sha() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TransitionValidationError("cannot resolve the checked-out SHA") from exc
    return completed.stdout.strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-attempts", type=int, default=90)
    parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        context = context_from_environment(os.environ, checkout_sha=_checkout_sha())
        validate_transition_context(context)
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise TransitionValidationError("read-only GITHUB_TOKEN is missing")
        client = GitHubChecksClient(
            api_url=context.api_url,
            repository=context.repository,
            token=token,
        )
        result = wait_for_required_checks(
            lambda: client.fetch(head_sha=context.head_sha),
            expected_sha=context.head_sha,
            attempts=args.poll_attempts,
            interval_seconds=args.poll_interval_seconds,
        )
    except TransitionValidationError as exc:
        raise SystemExit(f"MET-77 transition validation failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
