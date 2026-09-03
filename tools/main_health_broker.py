# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed GitHub App broker for protected-main health and merge admission."""

from __future__ import annotations

import argparse
import base64
import email.utils
import fcntl
import hashlib
import json
import os
import re
import socket
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from tools import observe_main_health, stop_the_line

APP_INTEGRATION_ID = 4722589
ACTIONS_INTEGRATION_ID = 15368
APP_SLUG = "metriplane-main-health-publisher"
SETTINGS_APP_SLUG = "metriplane-ruleset-witness"
REPOSITORY_OWNER = "Miko997"
REPOSITORY_NAME = "metriplane"
REPOSITORY = f"{REPOSITORY_OWNER}/{REPOSITORY_NAME}"
MAIN_BRANCH = "main"
MAIN_REF = f"refs/heads/{MAIN_BRANCH}"
MAX_PULL_COMMITS = 250
MERGE_READINESS_POLL_SECONDS = 2
MERGE_READINESS_TIMEOUT_SECONDS = 60
MERGE_READINESS_LEASE_MARGIN_SECONDS = 120
MERGE_READINESS_MAX_ATTEMPTS = 31
MAIN_HEALTH_CHECK = "Main health / required"
PUBLISH_LEASE_CHECK = "Release serialization / required"
PUBLISH_LEASE_REF_PREFIX = "refs/heads/release-leases/pypi-"
PUBLISH_LEASE_REF_GLOB = "refs/heads/release-leases/**"
RELEASE_TAG_REF_GLOB = "refs/tags/v*"
PUBLISH_LEASE_EXTERNAL_PREFIX = "metriplane-publish-lease.v1"
PUBLISH_WORKFLOW_PATH = ".github/workflows/publish-pypi.yml"
PUBLISH_WORKFLOW_NAME = "Publish Python distributions"
PUBLISH_REQUEST_MAX_AGE = timedelta(hours=2)
PUBLISH_AUTHORITY_PATHS = (
    PUBLISH_WORKFLOW_PATH,
    "schemas/metriplane.blockers.v1.schema.json",
    "tools/check_blockers.py",
    "tools/release_artifacts.py",
)
PUBLISH_VALIDATE_JOB = "Validate explicit production-promotion request"
PUBLISH_ARTIFACT_JOB = "Reverify artifacts before production approval"
PUBLISH_JOB = "Publish the verified artifacts to PyPI"
PUBLISH_VERIFY_JOB = "Verify production artifact identity and installation"
PUBLISH_RECONCILE_JOB = "Observe production main-update lease reconciliation"
PUBLISH_DISPATCH_BLOCKER_STEP = "Revalidate release blockers at production dispatch"
PUBLISH_WAIT_STEP = "Wait for the App-owned main-update lease"
PUBLISH_FENCED_BLOCKER_STEP = "Revalidate release blockers while main updates are fenced"
PUBLISH_REASSERT_STEP = "Reassert the lease and exact main immediately before publish"
PUBLISH_UPLOAD_STEP = "Publish the verified distributions to PyPI"
PUBLISH_RECONCILE_GUARD_STEP = "Retain the lease after any ambiguous or failed publication"
PUBLISH_RECONCILE_OBSERVE_STEP = "Observe exact main and the broker's terminal reconciliation"
PROVIDER_ACTION_STATUSES = {"completed", "in_progress", "pending", "queued", "requested", "waiting"}
PROVIDER_PENDING_ACTION_STATUSES = PROVIDER_ACTION_STATUSES - {"completed"}
CORE_CHECKS = (
    "Metriplane / required",
    "Documentation / required",
    "Security / required",
)
APP_TOKEN_PERMISSIONS = {
    "actions": "read",
    "checks": "write",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "read",
}
SETTINGS_TOKEN_PERMISSIONS = {
    "administration": "write",
    "metadata": "read",
}
SPOOL_SCHEMA_VERSION = 2
REQUEST_STATUSES = {"merged", "merging", "rejected", "uncertain"}
PUBLISH_LEASE_STATUSES = {
    "abandoned",
    "active",
    "creating",
    "quarantined",
    "released",
    "releasing",
}
PUBLISH_LEASE_FENCE_STATUSES = {"active", "creating", "quarantined", "releasing"}
PUBLISH_LEASE_TERMINAL_STATUSES = {"abandoned", "released"}
REQUEST_MARKER = "metriplane-merge-request:v1"
APPROVAL_MARKER = "metriplane-merge-approval:v1"
REPAIR_REQUEST_MARKER = "metriplane-repair-request:v1"
OWNER_REQUEST_MARKER = "metriplane-owner-merge-request:v1"
OWNER_REPAIR_REQUEST_MARKER = "metriplane-owner-repair-request:v1"
OWNER_AUTHORIZATION_MODE = "single-maintainer-owner-attestation"
OWNER_EMERGENCY_MODE = "single-maintainer-owner-emergency"
REQUEST_FIELDS = {
    "base_ref",
    "base_sha",
    "expires_at",
    "head_sha",
    "health_generation",
    "nonce",
    "pull_request",
    "repository",
    "requester_id",
    "schema_version",
}
REPAIR_REQUEST_FIELDS = {
    "base_ref",
    "base_sha",
    "expires_at",
    "head_sha",
    "incident_digest",
    "issue",
    "nonce",
    "pull_request",
    "repository",
    "requester_id",
    "schema_version",
    "state_generation",
}
OWNER_REQUEST_FIELDS = REQUEST_FIELDS | {
    "authorization_mode",
    "changed_paths_digest",
    "collaboration_digest",
    "ruleset_digests",
    "state_commit",
}
OWNER_REPAIR_REQUEST_FIELDS = REPAIR_REQUEST_FIELDS | {
    "authorization_mode",
    "changed_paths_digest",
    "collaboration_digest",
    "manifest_digest",
    "policy_amendment_digest",
    "ruleset_digests",
    "state_commit",
}
OWNER_CONTEXT_FIELDS = {
    "changed_paths_digest",
    "collaboration_digest",
    "collaborators",
    "owner_id",
    "owner_login",
    "owner_permission",
    "pending_invitations",
    "ruleset_digests",
    "state_commit",
}
OWNER_REPAIR_CONTEXT_FIELDS = OWNER_CONTEXT_FIELDS | {
    "manifest_expires_at",
    "manifest_digest",
    "policy_amendment_digest",
}
CONFIG_FIELDS = {
    "admission_ruleset_id",
    "app_id",
    "app_slug",
    "core_ruleset_id",
    "credential_path",
    "main_update_ruleset_id",
    "max_clock_skew_seconds",
    "poll_seconds",
    "release_lease_ruleset_id",
    "release_tag_ruleset_id",
    "repository",
    "settings_app_id",
    "settings_app_slug",
    "settings_credential_path",
    "state_branch",
    "state_protection_ruleset_id",
    "state_root",
    "state_writer_ruleset_id",
}
GOVERNED_RULESET_COUNT = 7
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
NONCE_RE = re.compile(r"[0-9a-f]{32}")
LEGACY_PROTECTED_MAIN_RESULTS = frozenset(
    {
        (
            "32883626832",
            "e8d221751144df169000e6c50e9b7c08e118692826eabea4293ae23fee301b20",
        ),
        (
            "32883626888",
            "e8ea35891d51ac4321be2717cd43630197958a62ad202fb6a02b286c6de7a165",
        ),
        (
            "32883626951",
            "d022cc8f74c9f0c5a1c7d1ddd8dd559cbffce3d587fe45b9bb91d06d4ba2acab",
        ),
        (
            "32890666879",
            "9ba6352c9ef52662ac1dff37acfce0a144131dd049bf086f0812fcdf39ba1b70",
        ),
        (
            "32893499507",
            "83da378f0d804e10480282b49c1dada4573cfc6ead2ea9810de7c5d8057d4f7f",
        ),
        (
            "32893499507",
            "f0eb90f3ff235434304b71ffe1b4b52606537734453f0211063601424dc4c976",
        ),
    }
)


class BrokerError(ValueError):
    """The broker cannot establish an exact safe transition."""


class ProviderError(BrokerError):
    """GitHub returned a definite unsuccessful response."""

    def __init__(self, message: str, *, status: int, request_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id


class ProviderTransportError(BrokerError):
    """GitHub may have accepted a request whose response was not observed."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BrokerError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise BrokerError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _provider_date(value: str | None) -> datetime:
    if value is None:
        raise BrokerError("provider response has no Date header")
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError) as exc:
        raise BrokerError("provider response has no valid Date header") from exc
    if parsed.tzinfo is None:
        raise BrokerError("provider Date header has no timezone")
    return parsed.astimezone(UTC)


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise BrokerError(f"{label} is not a lowercase 40-hex SHA")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise BrokerError(f"{label} must be a positive integer")
    return value


def _require_positive_decimal(value: Any, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise BrokerError(f"{label} must be a positive decimal string")
    return int(value)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BrokerError(f"cannot read broker configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BrokerError("broker configuration must be an object")
    return value


@dataclass(frozen=True)
class BrokerConfig:
    admission_ruleset_id: int
    app_id: int
    app_slug: str
    core_ruleset_id: int
    credential_path: Path
    main_update_ruleset_id: int
    max_clock_skew_seconds: int
    poll_seconds: int
    release_lease_ruleset_id: int
    release_tag_ruleset_id: int
    repository: str
    settings_app_id: int
    settings_app_slug: str
    settings_credential_path: Path
    state_branch: str
    state_protection_ruleset_id: int
    state_root: Path
    state_writer_ruleset_id: int

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> BrokerConfig:
        if set(value) != CONFIG_FIELDS:
            raise BrokerError("broker configuration fields are not exact")
        repository = value["repository"]
        if not isinstance(repository, str) or re.fullmatch(r"[^/\s]+/[^/\s]+", repository) is None:
            raise BrokerError("broker repository is invalid")
        if repository != REPOSITORY:
            raise BrokerError("broker repository is not canonical")
        app_slug = value["app_slug"]
        if app_slug != APP_SLUG:
            raise BrokerError("broker App slug is not canonical")
        settings_app_slug = value["settings_app_slug"]
        if settings_app_slug != SETTINGS_APP_SLUG:
            raise BrokerError("ruleset-witness App slug is not canonical")
        state_branch = value["state_branch"]
        if state_branch != "metriplane-main-health-state":
            raise BrokerError("broker state branch is not canonical")
        credential_path_value = value["credential_path"]
        settings_credential_path_value = value["settings_credential_path"]
        state_root_value = value["state_root"]
        if (
            not isinstance(credential_path_value, str)
            or not isinstance(settings_credential_path_value, str)
            or not isinstance(state_root_value, str)
        ):
            raise BrokerError("broker credential and state paths must be strings")
        credential_path = Path(credential_path_value)
        settings_credential_path = Path(settings_credential_path_value)
        state_root = Path(state_root_value)
        if (
            not credential_path.is_absolute()
            or not settings_credential_path.is_absolute()
            or not state_root.is_absolute()
        ):
            raise BrokerError("broker credential and state paths must be absolute")
        if credential_path == settings_credential_path:
            raise BrokerError("merge and ruleset-witness credentials must be distinct")
        max_clock_skew = _require_positive_int(
            value["max_clock_skew_seconds"], "max_clock_skew_seconds"
        )
        if max_clock_skew > 60:
            raise BrokerError("max_clock_skew_seconds must not exceed 60")
        poll_seconds = _require_positive_int(value["poll_seconds"], "poll_seconds")
        if poll_seconds > 60:
            raise BrokerError("poll_seconds must not exceed 60")
        app_id = _require_positive_int(value["app_id"], "app_id")
        if app_id != APP_INTEGRATION_ID:
            raise BrokerError("broker App ID is not canonical")
        settings_app_id = _require_positive_int(value["settings_app_id"], "settings_app_id")
        if settings_app_id == app_id:
            raise BrokerError("merge and ruleset-witness App IDs must be distinct")
        return cls(
            admission_ruleset_id=_require_positive_int(
                value["admission_ruleset_id"], "admission_ruleset_id"
            ),
            app_id=app_id,
            app_slug=app_slug,
            core_ruleset_id=_require_positive_int(value["core_ruleset_id"], "core_ruleset_id"),
            credential_path=credential_path,
            main_update_ruleset_id=_require_positive_int(
                value["main_update_ruleset_id"], "main_update_ruleset_id"
            ),
            max_clock_skew_seconds=max_clock_skew,
            poll_seconds=poll_seconds,
            release_lease_ruleset_id=_require_positive_int(
                value["release_lease_ruleset_id"], "release_lease_ruleset_id"
            ),
            release_tag_ruleset_id=_require_positive_int(
                value["release_tag_ruleset_id"], "release_tag_ruleset_id"
            ),
            repository=repository,
            settings_app_id=settings_app_id,
            settings_app_slug=settings_app_slug,
            settings_credential_path=settings_credential_path,
            state_branch=state_branch,
            state_protection_ruleset_id=_require_positive_int(
                value["state_protection_ruleset_id"], "state_protection_ruleset_id"
            ),
            state_root=state_root,
            state_writer_ruleset_id=_require_positive_int(
                value["state_writer_ruleset_id"], "state_writer_ruleset_id"
            ),
        )


@dataclass(frozen=True)
class PublishLeaseRecord:
    check_run_id: int | None
    created_at: str
    expires_at: str
    external_id: str
    lease_ref: str
    reason: str | None
    release_sha: str
    run_attempt: int
    run_id: int
    status: str
    updated_at: str

    @classmethod
    def create(
        cls,
        *,
        release_sha: str,
        run_attempt: int,
        run_id: int,
        created_at: str,
        expires_at: str,
    ) -> PublishLeaseRecord:
        release_sha = _require_sha(release_sha, "publish-lease release SHA")
        run_id = _require_positive_int(run_id, "publish-lease run ID")
        run_attempt = _require_positive_int(run_attempt, "publish-lease run attempt")
        lease_ref = f"{PUBLISH_LEASE_REF_PREFIX}{run_id}-{run_attempt}"
        external_id = f"{PUBLISH_LEASE_EXTERNAL_PREFIX}:{run_id}:{run_attempt}:{release_sha}"
        record = cls(
            check_run_id=None,
            created_at=created_at,
            expires_at=expires_at,
            external_id=external_id,
            lease_ref=lease_ref,
            reason=None,
            release_sha=release_sha,
            run_attempt=run_attempt,
            run_id=run_id,
            status="creating",
            updated_at=created_at,
        )
        _validate_publish_lease_record(record)
        return record


def _validate_publish_lease_record(record: PublishLeaseRecord) -> None:
    _require_sha(record.release_sha, "publish-lease release SHA")
    _require_positive_int(record.run_id, "publish-lease run ID")
    _require_positive_int(record.run_attempt, "publish-lease run attempt")
    expected_ref = f"{PUBLISH_LEASE_REF_PREFIX}{record.run_id}-{record.run_attempt}"
    expected_external = (
        f"{PUBLISH_LEASE_EXTERNAL_PREFIX}:{record.run_id}:{record.run_attempt}:{record.release_sha}"
    )
    if record.lease_ref != expected_ref or record.external_id != expected_external:
        raise BrokerError("durable publish-lease identity is inconsistent")
    if record.status not in PUBLISH_LEASE_STATUSES:
        raise BrokerError("durable publish-lease status is invalid")
    created_at = _timestamp(record.created_at)
    expires_at = _timestamp(record.expires_at)
    updated_at = _timestamp(record.updated_at)
    if expires_at <= created_at or updated_at < created_at:
        raise BrokerError("durable publish-lease timestamps are invalid")
    if record.check_run_id is not None:
        _require_positive_int(record.check_run_id, "publish-lease check-run ID")
    if record.status in {"active", "released", "releasing"} and record.check_run_id is None:
        raise BrokerError("durable publish-lease check-run identity is missing")
    if record.status in {"abandoned", "quarantined"}:
        if not isinstance(record.reason, str) or not record.reason:
            raise BrokerError("durable publish-lease terminal reason is missing")
    elif record.reason is not None:
        raise BrokerError("durable publish-lease reason is unexpected")


@dataclass(frozen=True)
class ApiResult:
    headers: dict[str, str]
    status: int
    value: Any

    @property
    def request_id(self) -> str | None:
        return self.headers.get("x-github-request-id")


class GitHubApi:
    def __init__(self, *, api_url: str = "https://api.github.com") -> None:
        self.api_url = api_url.rstrip("/")

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> ApiResult:
        mutating = method in {"DELETE", "PATCH", "POST", "PUT"}
        data = None if payload is None else canonical_bytes(payload)
        request = urllib.request.Request(
            f"{self.api_url}/{path.lstrip('/')}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                value: Any = None if not raw else json.loads(raw)
                result = ApiResult(
                    headers={key.lower(): value for key, value in response.headers.items()},
                    status=response.status,
                    value=value,
                )
        except urllib.error.HTTPError as exc:
            request_id = exc.headers.get("X-GitHub-Request-Id") if exc.headers else None
            if exc.code in {408, 425, 429} or 500 <= exc.code <= 599:
                raise ProviderTransportError(
                    f"GitHub {method} {path} returned ambiguous HTTP {exc.code}"
                ) from exc
            raise ProviderError(
                f"GitHub {method} {path} returned HTTP {exc.code}",
                status=exc.code,
                request_id=request_id,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderTransportError(
                f"GitHub {method} {path} response is ambiguous: {exc}"
            ) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            error_type = ProviderTransportError if mutating else BrokerError
            raise error_type(f"GitHub {method} {path} returned malformed JSON") from exc
        if result.status not in expected:
            if mutating:
                raise ProviderTransportError(
                    f"GitHub {method} {path} returned ambiguous HTTP {result.status}"
                )
            raise ProviderError(
                f"GitHub {method} {path} returned unexpected HTTP {result.status}",
                status=result.status,
                request_id=result.request_id,
            )
        return result

    def provider_now(self, token: str) -> datetime:
        result = self.request("rate_limit", token=token)
        return _provider_date(result.headers.get("date"))

    def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            result = self.request(f"{path}{separator}per_page=100&page={page}", token=token)
            if not isinstance(result.value, dict):
                raise BrokerError(f"GitHub pagination response for {path} is not an object")
            batch = result.value.get(key)
            if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
                raise BrokerError(f"GitHub pagination response for {path} has invalid {key}")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise BrokerError(f"GitHub pagination for {path} exceeded 100 pages")


def build_app_jwt(*, app_id: int, now: int, signer: Callable[[bytes], bytes]) -> str:
    if app_id <= 0 or now <= 0:
        raise BrokerError("App JWT identity or time is invalid")
    header = _b64url(canonical_bytes({"alg": "RS256", "typ": "JWT"}).rstrip(b"\n"))
    claims = _b64url(
        canonical_bytes({"exp": now + 540, "iat": now - 60, "iss": str(app_id)}).rstrip(b"\n")
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    signature = signer(signing_input)
    if not signature:
        raise BrokerError("App JWT signer returned an empty signature")
    return f"{header}.{claims}.{_b64url(signature)}"


class OpenSslSigner:
    def __init__(self, credential_path: Path) -> None:
        self.credential_path = credential_path

    def __call__(self, value: bytes) -> bytes:
        try:
            private = _credential_is_private(self.credential_path)
        except OSError as exc:
            raise BrokerError(f"cannot stat App credential: {exc}") from exc
        if not private:
            raise BrokerError("App credential is outside the private credential boundary")
        completed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(self.credential_path)],
            input=value,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            raise BrokerError("OpenSSL could not sign the App JWT")
        return completed.stdout


def _credential_is_private(credential_path: Path) -> bool:
    credential = credential_path.lstat()
    credential_mode = stat.S_IMODE(credential.st_mode)
    if not stat.S_ISREG(credential.st_mode):
        return False
    if credential_mode & 0o077 == 0:
        return True

    directory_value = os.environ.get("CREDENTIALS_DIRECTORY")
    if directory_value is None:
        return False
    directory = Path(directory_value)
    if not directory.is_absolute() or credential_path.parent != directory:
        return False
    directory_stat = directory.lstat()
    try:
        resolved_directory = directory.resolve(strict=True)
        resolved_credential = credential_path.resolve(strict=True)
    except OSError:
        return False
    return (
        resolved_directory == directory
        and resolved_credential == credential_path
        and stat.S_ISDIR(directory_stat.st_mode)
        and stat.S_IMODE(directory_stat.st_mode) == 0o550
        and directory_stat.st_uid == 0
        and directory_stat.st_gid == 0
        and credential_mode == 0o440
        and credential.st_uid == 0
        and credential.st_gid == 0
    )


@dataclass(frozen=True)
class InstallationToken:
    expires_at: datetime
    installation_id: int
    token: str


def _installation_identity(
    value: Any,
    *,
    api_url: str,
    app_id: int,
    app_slug: str,
    permissions: dict[str, str],
) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise BrokerError("GitHub App installation response is malformed")
    installation_id = _require_positive_int(value.get("id"), "installation ID")
    provider_app_id = _require_positive_int(value.get("app_id"), "installation App ID")
    if provider_app_id != app_id or value.get("app_slug") != app_slug:
        raise BrokerError("GitHub App installation App identity is not exact")
    account = value.get("account")
    if not isinstance(account, dict):
        raise BrokerError("GitHub App installation account is malformed")
    account_id = _require_positive_int(account.get("id"), "installation account ID")
    if account.get("login") != REPOSITORY_OWNER or account.get("type") != "User":
        raise BrokerError("GitHub App installation account identity is not canonical")
    target_id = _require_positive_int(value.get("target_id"), "installation target ID")
    if target_id != account_id or value.get("target_type") != "User":
        raise BrokerError("GitHub App installation target identity is not exact")
    if value.get("permissions") != permissions:
        raise BrokerError("GitHub App installation permissions are not exact")
    if value.get("repository_selection") != "selected":
        raise BrokerError("GitHub App installation repository selection is not exact")
    if "suspended_at" not in value or value["suspended_at"] is not None:
        raise BrokerError("GitHub App installation is suspended or suspension is unresolved")
    expected_tokens_url = f"{api_url}/app/installations/{installation_id}/access_tokens"
    if value.get("access_tokens_url") != expected_tokens_url:
        raise BrokerError("GitHub App installation ID is not exact")
    return installation_id, account_id


def _repository_identity(
    value: Any,
    *,
    account_id: int,
    label: str,
    require_default_branch: bool = False,
) -> int:
    if not isinstance(value, dict):
        raise BrokerError(f"{label} is malformed")
    repository_id = _require_positive_int(value.get("id"), f"{label} ID")
    owner = value.get("owner")
    if not isinstance(owner, dict):
        raise BrokerError(f"{label} owner is malformed")
    owner_id = _require_positive_int(owner.get("id"), f"{label} owner ID")
    if (
        value.get("name") != REPOSITORY_NAME
        or value.get("full_name") != REPOSITORY
        or (require_default_branch and value.get("default_branch") != MAIN_BRANCH)
        or owner.get("login") != REPOSITORY_OWNER
        or owner.get("type") != "User"
        or owner_id != account_id
    ):
        raise BrokerError(f"{label} identity is not canonical")
    return repository_id


class AppAuthenticator:
    def __init__(
        self,
        api: GitHubApi,
        config: BrokerConfig,
        *,
        clock: Callable[[], datetime] | None = None,
        purpose: str = "merge",
    ) -> None:
        self.api = api
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        if purpose == "merge":
            self.app_id = config.app_id
            self.app_slug = config.app_slug
            self.permissions = APP_TOKEN_PERMISSIONS
            credential_path = config.credential_path
        elif purpose == "settings":
            self.app_id = config.settings_app_id
            self.app_slug = config.settings_app_slug
            self.permissions = SETTINGS_TOKEN_PERMISSIONS
            credential_path = config.settings_credential_path
        else:
            raise BrokerError("GitHub App authenticator purpose is invalid")
        self.signer = OpenSslSigner(credential_path)
        self._cached: InstallationToken | None = None

    def mint(self) -> InstallationToken:
        local_now = self.clock()
        if local_now.tzinfo is None:
            raise BrokerError("App authenticator clock must include a timezone")
        local_now = local_now.astimezone(UTC)
        if self._cached is not None and self._cached.expires_at - local_now > timedelta(minutes=11):
            return self._cached
        app_jwt = build_app_jwt(
            app_id=self.app_id,
            now=int(local_now.timestamp()),
            signer=self.signer,
        )
        installation = self.api.request(
            f"repos/{self.config.repository}/installation",
            token=app_jwt,
        )
        installation_id, account_id = _installation_identity(
            installation.value,
            api_url=self.api.api_url,
            app_id=self.app_id,
            app_slug=self.app_slug,
            permissions=self.permissions,
        )
        token_result = self.api.request(
            f"app/installations/{installation_id}/access_tokens",
            token=app_jwt,
            method="POST",
            payload={
                "permissions": self.permissions,
                "repositories": [REPOSITORY_NAME],
            },
            expected=(201,),
        )
        if not isinstance(token_result.value, dict):
            raise BrokerError("GitHub App token response is malformed")
        token = token_result.value.get("token")
        permissions = token_result.value.get("permissions")
        expires_at = token_result.value.get("expires_at")
        if not isinstance(token, str) or not token or permissions != self.permissions:
            raise BrokerError("GitHub App token identity or permissions are not exact")
        if token_result.value.get("repository_selection") != "selected":
            raise BrokerError("GitHub App token repository selection is not exact")
        repositories = token_result.value.get("repositories")
        if not isinstance(repositories, list) or len(repositories) != 1:
            raise BrokerError("GitHub App token repository inventory is not exact")
        inventory_repository_id = _repository_identity(
            repositories[0], account_id=account_id, label="GitHub App token repository"
        )
        repository_result = self.api.request(
            f"repos/{self.config.repository}",
            token=token,
        )
        repository_id = _repository_identity(
            repository_result.value,
            account_id=account_id,
            label="token-authenticated repository",
            require_default_branch=True,
        )
        if repository_id != inventory_repository_id:
            raise BrokerError("GitHub App token repository ID is not exact")
        if not isinstance(expires_at, str):
            raise BrokerError("GitHub App token expiry is malformed")
        installation_token = InstallationToken(
            expires_at=_timestamp(expires_at),
            installation_id=installation_id,
            token=token,
        )
        self._cached = installation_token
        return installation_token


class DurableSpool:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / "broker.sqlite3"
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS check_runs (
                    head_sha TEXT PRIMARY KEY,
                    check_run_id INTEGER NOT NULL,
                    external_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    request_digest TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL UNIQUE,
                    pull_request INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cursors (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publish_leases (
                    external_id TEXT PRIMARY KEY,
                    run_id INTEGER NOT NULL,
                    run_attempt INTEGER NOT NULL,
                    release_sha TEXT NOT NULL,
                    lease_ref TEXT NOT NULL,
                    check_run_id INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT,
                    fence_slot INTEGER
                );
                CREATE UNIQUE INDEX IF NOT EXISTS publish_leases_run_identity
                    ON publish_leases(run_id, run_attempt);
                CREATE UNIQUE INDEX IF NOT EXISTS publish_leases_ref_identity
                    ON publish_leases(lease_ref);
                CREATE UNIQUE INDEX IF NOT EXISTS publish_leases_single_fence
                    ON publish_leases(fence_slot);
                """
            )
            self._validate_schema(connection)
        os.chmod(self.path, 0o600)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        version_row = connection.execute("PRAGMA user_version").fetchone()
        if version_row is None or int(version_row[0]) not in {0, 1, SPOOL_SCHEMA_VERSION}:
            raise BrokerError("durable spool schema version is incompatible")
        expected_columns = {
            "check_runs": (
                ("head_sha", "TEXT", False, True),
                ("check_run_id", "INTEGER", True, False),
                ("external_id", "TEXT", True, False),
                ("updated_at", "TEXT", True, False),
            ),
            "requests": (
                ("request_digest", "TEXT", False, True),
                ("nonce", "TEXT", True, False),
                ("pull_request", "INTEGER", True, False),
                ("request_json", "TEXT", True, False),
                ("status", "TEXT", True, False),
                ("updated_at", "TEXT", True, False),
            ),
            "cursors": (
                ("name", "TEXT", False, True),
                ("value", "TEXT", True, False),
            ),
            "publish_leases": (
                ("external_id", "TEXT", False, True),
                ("run_id", "INTEGER", True, False),
                ("run_attempt", "INTEGER", True, False),
                ("release_sha", "TEXT", True, False),
                ("lease_ref", "TEXT", True, False),
                ("check_run_id", "INTEGER", False, False),
                ("status", "TEXT", True, False),
                ("created_at", "TEXT", True, False),
                ("expires_at", "TEXT", True, False),
                ("updated_at", "TEXT", True, False),
                ("reason", "TEXT", False, False),
                ("fence_slot", "INTEGER", False, False),
            ),
        }
        for table, expected in expected_columns.items():
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            actual = tuple(
                (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in rows
            )
            if actual != expected:
                raise BrokerError(f"durable spool {table} schema is incompatible")
        unique_request_columns: set[tuple[str, ...]] = set()
        for index in connection.execute("PRAGMA index_list(requests)").fetchall():
            if not bool(index[2]):
                continue
            index_name = '"' + str(index[1]).replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA index_info({index_name})").fetchall()
            unique_request_columns.add(tuple(str(row[2]) for row in columns))
        if ("nonce",) not in unique_request_columns:
            raise BrokerError("durable spool nonce uniqueness is missing")
        publish_indexes: set[tuple[str, ...]] = set()
        for index in connection.execute("PRAGMA index_list(publish_leases)").fetchall():
            if not bool(index[2]):
                continue
            index_name = '"' + str(index[1]).replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA index_info({index_name})").fetchall()
            publish_indexes.add(tuple(str(row[2]) for row in columns))
        if (
            not {
                ("fence_slot",),
                ("lease_ref",),
                ("run_id", "run_attempt"),
            }
            <= publish_indexes
        ):
            raise BrokerError("durable publish-lease uniqueness is missing")
        rows = connection.execute(
            """
            SELECT external_id, run_id, run_attempt, release_sha, lease_ref,
                   check_run_id, status, created_at, expires_at, updated_at,
                   reason, fence_slot
            FROM publish_leases
            """
        ).fetchall()
        for row in rows:
            record = DurableSpool._publish_lease_from_row(row[:-1])
            expected_slot = 1 if record.status in PUBLISH_LEASE_FENCE_STATUSES else None
            if row[-1] != expected_slot:
                raise BrokerError("durable publish-lease fence slot is invalid")
        if int(version_row[0]) != SPOOL_SCHEMA_VERSION:
            connection.execute(f"PRAGMA user_version = {SPOOL_SCHEMA_VERSION}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def get_check_id(self, head_sha: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT check_run_id FROM check_runs WHERE head_sha = ?", (head_sha,)
            ).fetchone()
        return None if row is None else int(row[0])

    def get_check_external_id(self, head_sha: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT external_id FROM check_runs WHERE head_sha = ?", (head_sha,)
            ).fetchone()
        return None if row is None else str(row[0])

    def record_check(
        self, *, head_sha: str, check_run_id: int, external_id: str, updated_at: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO check_runs(head_sha, check_run_id, external_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(head_sha) DO UPDATE SET
                    check_run_id = excluded.check_run_id,
                    external_id = excluded.external_id,
                    updated_at = excluded.updated_at
                """,
                (head_sha, check_run_id, external_id, updated_at),
            )

    def request_status(self, request_digest: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM requests WHERE request_digest = ?", (request_digest,)
            ).fetchone()
        if row is None:
            return None
        status = str(row[0])
        if status not in REQUEST_STATUSES:
            raise BrokerError("durable request spool contains an invalid status")
        return status

    def record_request(
        self,
        *,
        request_digest: str,
        nonce: str,
        pull_request: int,
        request: dict[str, Any],
        status: str,
        updated_at: str,
    ) -> None:
        if (
            digest(request) != request_digest
            or request.get("nonce") != nonce
            or request.get("pull_request") != pull_request
        ):
            raise BrokerError("durable request identity is inconsistent")
        if status not in REQUEST_STATUSES:
            raise BrokerError("durable request status is invalid")
        request_json = canonical_bytes(request).decode().rstrip("\n")
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT nonce, pull_request, request_json, status
                FROM requests WHERE request_digest = ?
                """,
                (request_digest,),
            ).fetchone()
            if existing is None:
                if status != "merging":
                    raise BrokerError("durable request must begin in merging state")
                connection.execute(
                    """
                    INSERT INTO requests(
                        request_digest, nonce, pull_request, request_json, status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (request_digest, nonce, pull_request, request_json, status, updated_at),
                )
                return
            if existing[:3] != (nonce, pull_request, request_json):
                raise BrokerError("durable request identity changed after admission")
            old_status = str(existing[3])
            if old_status != "merging" and status != old_status:
                raise BrokerError("durable request status is terminal")
            connection.execute(
                """
                UPDATE requests SET status = ?, updated_at = ? WHERE request_digest = ?
                """,
                (status, updated_at, request_digest),
            )

    def requests_with_status(self, status: str) -> list[dict[str, Any]]:
        if status not in REQUEST_STATUSES:
            raise BrokerError("durable request status is invalid")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT request_digest, nonce, pull_request, request_json
                FROM requests WHERE status = ? ORDER BY pull_request, request_digest
                """,
                (status,),
            ).fetchall()
        values: list[dict[str, Any]] = []
        for request_digest, nonce, pull_request, request_json in rows:
            try:
                request = json.loads(request_json)
            except json.JSONDecodeError as exc:
                raise BrokerError("durable request spool contains malformed JSON") from exc
            if (
                not isinstance(request, dict)
                or digest(request) != request_digest
                or request.get("nonce") != nonce
                or request.get("pull_request") != pull_request
            ):
                raise BrokerError("durable request spool digest is invalid")
            values.append(
                {
                    "base_sha": request.get("base_sha"),
                    "head_sha": request.get("head_sha"),
                    "nonce": nonce,
                    "pull_request": pull_request,
                    "request": request,
                    "request_digest": request_digest,
                }
            )
        return values

    def get_cursor(self, name: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM cursors WHERE name = ?", (name,)).fetchone()
        return None if row is None else str(row[0])

    def set_cursor(self, name: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cursors(name, value) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET value = excluded.value
                """,
                (name, value),
            )

    @staticmethod
    def _publish_lease_from_row(row: tuple[Any, ...]) -> PublishLeaseRecord:
        if len(row) != 11:
            raise BrokerError("durable publish-lease row is malformed")
        record = PublishLeaseRecord(
            external_id=str(row[0]),
            run_id=int(row[1]),
            run_attempt=int(row[2]),
            release_sha=str(row[3]),
            lease_ref=str(row[4]),
            check_run_id=None if row[5] is None else int(row[5]),
            status=str(row[6]),
            created_at=str(row[7]),
            expires_at=str(row[8]),
            updated_at=str(row[9]),
            reason=None if row[10] is None else str(row[10]),
        )
        _validate_publish_lease_record(record)
        return record

    def publish_lease_fence(self) -> PublishLeaseRecord | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT external_id, run_id, run_attempt, release_sha, lease_ref,
                       check_run_id, status, created_at, expires_at, updated_at, reason
                FROM publish_leases WHERE fence_slot = 1
                """
            ).fetchall()
        if len(rows) > 1:
            raise BrokerError("durable spool contains concurrent publish leases")
        return None if not rows else self._publish_lease_from_row(rows[0])

    def begin_publish_lease(self, record: PublishLeaseRecord) -> PublishLeaseRecord:
        _validate_publish_lease_record(record)
        if record.status != "creating" or record.check_run_id is not None:
            raise BrokerError("new durable publish lease must begin in creating state")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_fence = connection.execute(
                "SELECT external_id FROM publish_leases WHERE fence_slot = 1"
            ).fetchone()
            if existing_fence is not None:
                raise BrokerError("another durable publish lease already owns the fence")
            connection.execute(
                """
                INSERT INTO publish_leases(
                    external_id, run_id, run_attempt, release_sha, lease_ref,
                    check_run_id, status, created_at, expires_at, updated_at,
                    reason, fence_slot
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, 1)
                """,
                (
                    record.external_id,
                    record.run_id,
                    record.run_attempt,
                    record.release_sha,
                    record.lease_ref,
                    record.status,
                    record.created_at,
                    record.expires_at,
                    record.updated_at,
                ),
            )
        return record

    def transition_publish_lease(
        self,
        *,
        external_id: str,
        status: str,
        updated_at: str,
        check_run_id: int | None = None,
        reason: str | None = None,
    ) -> PublishLeaseRecord:
        transitions = {
            "creating": {"abandoned", "active", "creating", "quarantined", "releasing"},
            "active": {"active", "quarantined", "releasing"},
            "quarantined": {"quarantined"},
            "releasing": {"quarantined", "released", "releasing"},
        }
        if status not in PUBLISH_LEASE_STATUSES:
            raise BrokerError("durable publish-lease status is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT external_id, run_id, run_attempt, release_sha, lease_ref,
                       check_run_id, status, created_at, expires_at, updated_at, reason
                FROM publish_leases WHERE external_id = ?
                """,
                (external_id,),
            ).fetchone()
            if row is None:
                raise BrokerError("durable publish lease is missing")
            old = self._publish_lease_from_row(row)
            if old.status in PUBLISH_LEASE_TERMINAL_STATUSES:
                if status != old.status or check_run_id not in {None, old.check_run_id}:
                    raise BrokerError("durable publish-lease status is terminal")
                return old
            if status not in transitions[old.status]:
                raise BrokerError("durable publish-lease transition is invalid")
            next_check_id = old.check_run_id if check_run_id is None else check_run_id
            if old.check_run_id is not None and next_check_id != old.check_run_id:
                raise BrokerError("durable publish-lease check identity changed")
            next_record = PublishLeaseRecord(
                check_run_id=next_check_id,
                created_at=old.created_at,
                expires_at=old.expires_at,
                external_id=old.external_id,
                lease_ref=old.lease_ref,
                reason=reason,
                release_sha=old.release_sha,
                run_attempt=old.run_attempt,
                run_id=old.run_id,
                status=status,
                updated_at=updated_at,
            )
            _validate_publish_lease_record(next_record)
            fence_slot = 1 if status in PUBLISH_LEASE_FENCE_STATUSES else None
            connection.execute(
                """
                UPDATE publish_leases
                SET check_run_id = ?, status = ?, updated_at = ?, reason = ?, fence_slot = ?
                WHERE external_id = ?
                """,
                (
                    next_record.check_run_id,
                    status,
                    updated_at,
                    reason,
                    fence_slot,
                    external_id,
                ),
            )
        return next_record


def _ruleset_view(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "bypass_actors",
        "conditions",
        "enforcement",
        "name",
        "rules",
        "source",
        "source_type",
        "target",
    }
    if not required <= set(value):
        raise BrokerError("GitHub ruleset response omits governed fields")
    return {key: value[key] for key in sorted(required)}


def _provider_ruleset(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "source": REPOSITORY,
        "source_type": "Repository",
    }


def _core_ruleset() -> dict[str, Any]:
    return {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": [MAIN_REF]}},
        "enforcement": "active",
        "name": "Protect main",
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "parameters": stop_the_line.CORE_PULL_REQUEST_PARAMETERS,
                "type": "pull_request",
            },
            {
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": name, "integration_id": ACTIONS_INTEGRATION_ID}
                        for name in CORE_CHECKS
                    ],
                    "strict_required_status_checks_policy": True,
                },
                "type": "required_status_checks",
            },
        ],
        "target": "branch",
    }


def _admission_ruleset() -> dict[str, Any]:
    return {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": [MAIN_REF]}},
        "enforcement": "active",
        "name": "Protect main health admission",
        "rules": [
            {
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": MAIN_HEALTH_CHECK, "integration_id": APP_INTEGRATION_ID}
                    ],
                    "strict_required_status_checks_policy": True,
                },
                "type": "required_status_checks",
            }
        ],
        "target": "branch",
    }


def _app_update_ruleset(*, name: str, include: list[str]) -> dict[str, Any]:
    return {
        "bypass_actors": [
            {"actor_id": APP_INTEGRATION_ID, "actor_type": "Integration", "bypass_mode": "always"}
        ],
        "conditions": {"ref_name": {"exclude": [], "include": include}},
        "enforcement": "active",
        "name": name,
        "rules": [{"type": "update"}],
        "target": "branch",
    }


def _state_protection_ruleset(state_branch: str) -> dict[str, Any]:
    return {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": [f"refs/heads/{state_branch}"]}},
        "enforcement": "active",
        "name": "Protect main health state",
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
        "target": "branch",
    }


def _release_lease_ruleset() -> dict[str, Any]:
    return {
        "bypass_actors": [
            {"actor_id": APP_INTEGRATION_ID, "actor_type": "Integration", "bypass_mode": "always"}
        ],
        "conditions": {"ref_name": {"exclude": [], "include": [PUBLISH_LEASE_REF_GLOB]}},
        "enforcement": "active",
        "name": "Restrict release lease writers",
        "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
        "target": "branch",
    }


def _release_tag_ruleset() -> dict[str, Any]:
    return {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": [RELEASE_TAG_REF_GLOB]}},
        "enforcement": "active",
        "name": "Protect release tags",
        "rules": [{"type": "update"}, {"type": "deletion"}],
        "target": "tag",
    }


def validate_hosted_rulesets(
    *, config: BrokerConfig, rulesets: dict[int, dict[str, Any]]
) -> dict[str, str]:
    expected = {
        config.core_ruleset_id: _provider_ruleset(_core_ruleset()),
        config.admission_ruleset_id: _provider_ruleset(_admission_ruleset()),
        config.main_update_ruleset_id: _provider_ruleset(
            _app_update_ruleset(name="Restrict main updates to broker", include=[MAIN_REF])
        ),
        config.state_protection_ruleset_id: _provider_ruleset(
            _state_protection_ruleset(config.state_branch)
        ),
        config.state_writer_ruleset_id: _provider_ruleset(
            _app_update_ruleset(
                name="Restrict main health state writers",
                include=[f"refs/heads/{config.state_branch}"],
            )
        ),
        config.release_lease_ruleset_id: _provider_ruleset(_release_lease_ruleset()),
        config.release_tag_ruleset_id: _provider_ruleset(_release_tag_ruleset()),
    }
    if set(rulesets) != set(expected):
        raise BrokerError("live ruleset ID inventory is not exact")
    digests: dict[str, str] = {}
    for ruleset_id, expected_value in expected.items():
        actual = _ruleset_view(rulesets[ruleset_id])
        if actual != expected_value:
            raise BrokerError(f"ruleset {ruleset_id} is not the governed broker configuration")
        digests[str(ruleset_id)] = digest(actual)
    return digests


def parse_merge_request(body: Any, *, reviewer_id: int) -> dict[str, Any]:
    if not isinstance(body, str):
        raise BrokerError("merge request review has no body")
    lines = body.rstrip("\n").splitlines()
    if len(lines) != 2 or lines[0] != REQUEST_MARKER:
        raise BrokerError("merge request review marker is invalid")
    try:
        value = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise BrokerError("merge request review JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise BrokerError("merge request review fields are not exact")
    if lines[1] != canonical_bytes(value).decode().rstrip("\n"):
        raise BrokerError("merge request review JSON is not canonical")
    if value["schema_version"] != 1 or value["base_ref"] != "main":
        raise BrokerError("merge request schema or base ref is invalid")
    _require_sha(value["base_sha"], "merge request base_sha")
    _require_sha(value["head_sha"], "merge request head_sha")
    _require_positive_int(value["pull_request"], "merge request pull_request")
    _require_positive_int(value["health_generation"], "merge request health_generation")
    requester_id = _require_positive_int(value["requester_id"], "merge request requester_id")
    if requester_id != reviewer_id:
        raise BrokerError("merge request requester does not match provider review actor")
    if value["repository"] != REPOSITORY:
        raise BrokerError("merge request repository is not canonical")
    if not isinstance(value["nonce"], str) or NONCE_RE.fullmatch(value["nonce"]) is None:
        raise BrokerError("merge request nonce is invalid")
    if not isinstance(value["expires_at"], str):
        raise BrokerError("merge request expiry is invalid")
    _timestamp(value["expires_at"])
    return value


def parse_approval(body: Any) -> str:
    if not isinstance(body, str):
        raise BrokerError("merge approval review has no body")
    prefix = f"{APPROVAL_MARKER} "
    normalized = body.removesuffix("\n")
    if not normalized.startswith(prefix):
        raise BrokerError("merge approval review marker is invalid")
    value = normalized[len(prefix) :]
    if DIGEST_RE.fullmatch(value) is None:
        raise BrokerError("merge approval digest is invalid")
    return value


def parse_repair_request(body: Any, *, reviewer_id: int) -> dict[str, Any]:
    if not isinstance(body, str):
        raise BrokerError("repair request review has no body")
    lines = body.rstrip("\n").splitlines()
    if len(lines) != 2 or lines[0] != REPAIR_REQUEST_MARKER:
        raise BrokerError("repair request review marker is invalid")
    try:
        value = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise BrokerError("repair request review JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != REPAIR_REQUEST_FIELDS:
        raise BrokerError("repair request review fields are not exact")
    if lines[1] != canonical_bytes(value).decode().rstrip("\n"):
        raise BrokerError("repair request review JSON is not canonical")
    if value["schema_version"] != 1 or value["base_ref"] != "main":
        raise BrokerError("repair request schema or base ref is invalid")
    _require_sha(value["base_sha"], "repair request base_sha")
    _require_sha(value["head_sha"], "repair request head_sha")
    _require_positive_int(value["pull_request"], "repair request pull_request")
    _require_positive_int(value["state_generation"], "repair request state_generation")
    requester_id = _require_positive_int(value["requester_id"], "repair request requester_id")
    if requester_id != reviewer_id:
        raise BrokerError("repair requester does not match provider review actor")
    if value["repository"] != REPOSITORY:
        raise BrokerError("repair request repository is not canonical")
    if not isinstance(value["nonce"], str) or NONCE_RE.fullmatch(value["nonce"]) is None:
        raise BrokerError("repair request nonce is invalid")
    if (
        not isinstance(value["incident_digest"], str)
        or DIGEST_RE.fullmatch(value["incident_digest"]) is None
    ):
        raise BrokerError("repair request incident digest is invalid")
    if (
        not isinstance(value["issue"], str)
        or re.fullmatch(r"[A-Z]+-[0-9]+", value["issue"]) is None
    ):
        raise BrokerError("repair request issue is invalid")
    if not isinstance(value["expires_at"], str):
        raise BrokerError("repair request expiry is invalid")
    _timestamp(value["expires_at"])
    return value


def _validate_owner_request_bindings(
    value: dict[str, Any], *, authorization_mode: str, label: str
) -> None:
    if value["authorization_mode"] != authorization_mode:
        raise BrokerError(f"{label} authorization mode is invalid")
    for field in ("changed_paths_digest", "collaboration_digest"):
        if not isinstance(value[field], str) or DIGEST_RE.fullmatch(value[field]) is None:
            raise BrokerError(f"{label} {field} is invalid")
    _require_sha(value["state_commit"], f"{label} state_commit")
    ruleset_digests = value["ruleset_digests"]
    if (
        not isinstance(ruleset_digests, dict)
        or len(ruleset_digests) != GOVERNED_RULESET_COUNT
        or not all(
            isinstance(identifier, str)
            and re.fullmatch(r"[1-9][0-9]*", identifier) is not None
            and isinstance(ruleset_digest, str)
            and DIGEST_RE.fullmatch(ruleset_digest) is not None
            for identifier, ruleset_digest in ruleset_digests.items()
        )
    ):
        raise BrokerError(f"{label} ruleset digests are invalid")


def parse_owner_request(body: Any, *, reviewer_id: int) -> dict[str, Any]:
    if not isinstance(body, str):
        raise BrokerError("owner merge request review has no body")
    lines = body.rstrip("\n").splitlines()
    if len(lines) != 2 or lines[0] != OWNER_REQUEST_MARKER:
        raise BrokerError("owner merge request review marker is invalid")
    try:
        value = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise BrokerError("owner merge request review JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != OWNER_REQUEST_FIELDS:
        raise BrokerError("owner merge request review fields are not exact")
    if lines[1] != canonical_bytes(value).decode().rstrip("\n"):
        raise BrokerError("owner merge request review JSON is not canonical")
    parse_merge_request(
        REQUEST_MARKER
        + "\n"
        + canonical_bytes({key: value[key] for key in REQUEST_FIELDS}).decode(),
        reviewer_id=reviewer_id,
    )
    _validate_owner_request_bindings(
        value,
        authorization_mode=OWNER_AUTHORIZATION_MODE,
        label="owner merge request",
    )
    return value


def parse_owner_repair_request(body: Any, *, reviewer_id: int) -> dict[str, Any]:
    if not isinstance(body, str):
        raise BrokerError("owner repair request review has no body")
    lines = body.rstrip("\n").splitlines()
    if len(lines) != 2 or lines[0] != OWNER_REPAIR_REQUEST_MARKER:
        raise BrokerError("owner repair request review marker is invalid")
    try:
        value = json.loads(lines[1])
    except json.JSONDecodeError as exc:
        raise BrokerError("owner repair request review JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != OWNER_REPAIR_REQUEST_FIELDS:
        raise BrokerError("owner repair request review fields are not exact")
    if lines[1] != canonical_bytes(value).decode().rstrip("\n"):
        raise BrokerError("owner repair request review JSON is not canonical")
    parse_repair_request(
        REPAIR_REQUEST_MARKER
        + "\n"
        + canonical_bytes({key: value[key] for key in REPAIR_REQUEST_FIELDS}).decode(),
        reviewer_id=reviewer_id,
    )
    _validate_owner_request_bindings(
        value,
        authorization_mode=OWNER_EMERGENCY_MODE,
        label="owner repair request",
    )
    for field in ("manifest_digest", "policy_amendment_digest"):
        if not isinstance(value[field], str) or DIGEST_RE.fullmatch(value[field]) is None:
            raise BrokerError(f"owner repair request {field} is invalid")
    return value


def _review_actor(review: dict[str, Any]) -> tuple[int, str]:
    user = review.get("user")
    if not isinstance(user, dict):
        raise BrokerError("provider review actor is malformed")
    actor_id = _require_positive_int(user.get("id"), "provider review actor ID")
    login = user.get("login")
    if not isinstance(login, str) or not login:
        raise BrokerError("provider review actor login is malformed")
    return actor_id, login.casefold()


def _commit_actor_ids(commits: Iterable[dict[str, Any]]) -> tuple[set[int], set[str]]:
    ids: set[int] = set()
    logins: set[str] = set()
    for commit in commits:
        for key in ("author", "committer"):
            actor = commit.get(key)
            if not isinstance(actor, dict):
                raise BrokerError(f"provider commit {key} actor is unresolved or malformed")
            actor_id = _require_positive_int(actor.get("id"), f"provider commit {key} actor ID")
            login = actor.get("login")
            if not isinstance(login, str) or not login:
                raise BrokerError(f"provider commit {key} actor login is malformed")
            ids.add(actor_id)
            logins.add(login.casefold())
    return ids, logins


def _validate_owner_context(context: dict[str, Any], *, repair: bool) -> None:
    expected_fields = OWNER_REPAIR_CONTEXT_FIELDS if repair else OWNER_CONTEXT_FIELDS
    if set(context) != expected_fields:
        raise BrokerError("single-maintainer provider context fields are not exact")
    owner_id = _require_positive_int(context.get("owner_id"), "repository owner ID")
    owner_login = context.get("owner_login")
    if (
        not isinstance(owner_login, str)
        or owner_login.casefold() != REPOSITORY_OWNER.casefold()
        or context.get("owner_permission") != "admin"
    ):
        raise BrokerError("single-maintainer context does not identify the repository owner")
    collaborators = context.get("collaborators")
    invitations = context.get("pending_invitations")
    if (
        not isinstance(collaborators, list)
        or not collaborators
        or collaborators
        != sorted(collaborators, key=lambda item: str(item.get("login", "")).casefold())
        or not all(
            isinstance(item, dict)
            and set(item) == {"id", "login", "permission"}
            and all(isinstance(item[field], str) and item[field] for field in item)
            for item in collaborators
        )
        or not isinstance(invitations, list)
        or invitations
        != sorted(
            invitations,
            key=lambda item: (str(item.get("invitee", "")).casefold(), str(item.get("id", ""))),
        )
        or not all(
            isinstance(item, dict)
            and set(item) == {"id", "invitee", "permission"}
            and all(isinstance(item[field], str) and item[field] for field in item)
            for item in invitations
        )
    ):
        raise BrokerError("single-maintainer collaboration inventory is malformed")
    owner_entries = [
        item for item in collaborators if item["login"].casefold() == owner_login.casefold()
    ]
    if (
        len(owner_entries) != 1
        or owner_entries[0]["id"] != str(owner_id)
        or owner_entries[0]["permission"] != "admin"
        or any(
            item["login"].casefold() != owner_login.casefold()
            and item["permission"] in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS
            for item in collaborators
        )
        or any(
            item["permission"] in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS
            for item in invitations
        )
    ):
        raise BrokerError("single-maintainer context found an eligible independent collaborator")
    collaboration_digest = digest(
        {"collaborators": collaborators, "pending_invitations": invitations}
    )
    if context.get("collaboration_digest") != collaboration_digest:
        raise BrokerError("single-maintainer collaboration digest is invalid")
    _require_sha(context.get("state_commit"), "single-maintainer state commit")
    for field in ("changed_paths_digest", "collaboration_digest"):
        if not isinstance(context.get(field), str) or DIGEST_RE.fullmatch(context[field]) is None:
            raise BrokerError(f"single-maintainer {field} is invalid")
    ruleset_digests = context.get("ruleset_digests")
    if (
        not isinstance(ruleset_digests, dict)
        or len(ruleset_digests) != GOVERNED_RULESET_COUNT
        or not all(
            isinstance(identifier, str)
            and re.fullmatch(r"[1-9][0-9]*", identifier) is not None
            and isinstance(value, str)
            and DIGEST_RE.fullmatch(value) is not None
            for identifier, value in ruleset_digests.items()
        )
    ):
        raise BrokerError("single-maintainer ruleset digests are invalid")
    if repair:
        expires_at = context.get("manifest_expires_at")
        if not isinstance(expires_at, str):
            raise BrokerError("single-maintainer manifest expiry is invalid")
        _timestamp(expires_at)
        for field in ("manifest_digest", "policy_amendment_digest"):
            if (
                not isinstance(context.get(field), str)
                or DIGEST_RE.fullmatch(context[field]) is None
            ):
                raise BrokerError(f"single-maintainer {field} is invalid")


def _select_owner_admission(
    *,
    commits: list[dict[str, Any]],
    now: datetime,
    owner_context: dict[str, Any],
    pull: dict[str, Any],
    repository: str,
    repair: bool,
    reviews: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_owner_context(owner_context, repair=repair)
    _commit_actor_ids(commits)
    pull_number = _require_positive_int(pull.get("number"), "owner pull request number")
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not isinstance(base, dict) or not isinstance(head, dict) or not isinstance(author, dict):
        raise BrokerError("owner pull request identity is malformed")
    base_sha = _require_sha(base.get("sha"), "owner pull request base SHA")
    head_sha = _require_sha(head.get("sha"), "owner pull request head SHA")
    author_id = _require_positive_int(author.get("id"), "owner pull request author ID")
    author_login = author.get("login")
    if (
        repository != REPOSITORY
        or author_id != owner_context["owner_id"]
        or not isinstance(author_login, str)
        or author_login.casefold() != str(owner_context["owner_login"]).casefold()
    ):
        raise BrokerError("single-maintainer request is not owner-authored")
    marker = OWNER_REPAIR_REQUEST_MARKER if repair else OWNER_REQUEST_MARKER
    parser = parse_owner_repair_request if repair else parse_owner_request
    requests: list[tuple[int, datetime, dict[str, Any], int, str]] = []
    for review in reviews:
        body = review.get("body")
        if not isinstance(body, str) or not body.startswith(marker):
            continue
        review_head_sha = _require_sha(review.get("commit_id"), "owner request review commit SHA")
        if review_head_sha != head_sha:
            continue
        if review.get("state") != "COMMENTED":
            raise BrokerError("single-maintainer request must be a COMMENTED provider review")
        requester_id, requester_login = _review_actor(review)
        request = parser(body, reviewer_id=requester_id)
        review_id = _require_positive_int(review.get("id"), "owner request review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("owner request review time is malformed")
        submitted_at = _timestamp(submitted_raw)
        expires_at = _timestamp(request["expires_at"])
        if expires_at <= submitted_at or expires_at - submitted_at > timedelta(minutes=10):
            raise BrokerError("owner request expiry exceeds its bounded lease")
        if (
            request["repository"] != repository
            or request["pull_request"] != pull_number
            or request["base_sha"] != base_sha
            or request["head_sha"] != head_sha
            or requester_id != owner_context["owner_id"]
            or requester_login != str(owner_context["owner_login"]).casefold()
            or request["changed_paths_digest"] != owner_context["changed_paths_digest"]
            or request["collaboration_digest"] != owner_context["collaboration_digest"]
            or request["ruleset_digests"] != owner_context["ruleset_digests"]
            or request["state_commit"] != owner_context["state_commit"]
        ):
            raise BrokerError("owner request does not bind the live provider context")
        if repair:
            if state is None:
                raise BrokerError("owner repair request has no red-state context")
            if _timestamp(request["expires_at"]) > _timestamp(
                str(owner_context["manifest_expires_at"])
            ):
                raise BrokerError("owner repair request outlives the emergency manifest")
            if (
                request["incident_digest"] != state.get("incident_digest")
                or request["state_generation"] != state.get("generation")
                or request["manifest_digest"] != owner_context["manifest_digest"]
                or request["policy_amendment_digest"] != owner_context["policy_amendment_digest"]
            ):
                raise BrokerError("owner repair request does not bind the open incident")
        requests.append((review_id, submitted_at, request, requester_id, requester_login))
    if not requests:
        raise BrokerError("pull request has no exact single-maintainer owner request")
    request_review_id, submitted_at, request, requester_id, requester_login = max(
        requests, key=lambda item: item[0]
    )
    if now < submitted_at - timedelta(seconds=60) or now >= _timestamp(request["expires_at"]):
        raise BrokerError("single-maintainer owner request is not currently valid")
    result = {
        "approval_review_id": request_review_id,
        "approver_id": requester_id,
        "approver_login": requester_login,
        "authorization_mode": request["authorization_mode"],
        "base_sha": base_sha,
        "changed_paths_digest": request["changed_paths_digest"],
        "collaboration_digest": request["collaboration_digest"],
        "head_sha": head_sha,
        "kind": "owner-repair" if repair else "owner-normal",
        "nonce": request["nonce"],
        "pull_request": pull_number,
        "request": request,
        "request_digest": digest(request),
        "request_review_id": request_review_id,
        "requester_id": requester_id,
        "reviewer_permission": "admin",
        "ruleset_digests": request["ruleset_digests"],
        "schema_version": 1,
        "state_commit": request["state_commit"],
    }
    if repair:
        result.update(
            {
                "incident_digest": request["incident_digest"],
                "issue": request["issue"],
                "manifest_expires_at": owner_context["manifest_expires_at"],
                "manifest_digest": request["manifest_digest"],
                "policy_amendment_digest": request["policy_amendment_digest"],
                "state_generation": request["state_generation"],
            }
        )
    else:
        result["health_generation"] = request["health_generation"]
    return result


def select_admission(
    *,
    commits: list[dict[str, Any]],
    now: datetime,
    pull: dict[str, Any],
    repository: str,
    reviewer_permissions: dict[str, str],
    reviews: list[dict[str, Any]],
    owner_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pull_number = _require_positive_int(pull.get("number"), "pull request number")
    if pull.get("state") != "open" or pull.get("draft") is not False:
        raise BrokerError("pull request is not an open non-draft candidate")
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not all(isinstance(item, dict) for item in (base, head, author)):
        raise BrokerError("pull request identity is malformed")
    assert isinstance(base, dict) and isinstance(head, dict) and isinstance(author, dict)
    head_repository = head.get("repo")
    if (
        base.get("ref") != "main"
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise BrokerError("fork or non-main pull request cannot enter broker admission")
    base_sha = _require_sha(base.get("sha"), "pull request base SHA")
    head_sha = _require_sha(head.get("sha"), "pull request head SHA")
    author_id = _require_positive_int(author.get("id"), "pull request author ID")

    requests: list[tuple[int, datetime, dict[str, Any], int, str]] = []
    for review in reviews:
        body = review.get("body")
        if not isinstance(body, str) or not body.startswith(REQUEST_MARKER):
            continue
        if review.get("state") != "COMMENTED":
            raise BrokerError("merge request must be a COMMENTED provider review")
        actor_id, actor_login = _review_actor(review)
        request = parse_merge_request(body, reviewer_id=actor_id)
        review_id = _require_positive_int(review.get("id"), "merge request review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("merge request review time is malformed")
        submitted_at = _timestamp(submitted_raw)
        expires_at = _timestamp(request["expires_at"])
        if expires_at <= submitted_at or expires_at - submitted_at > timedelta(minutes=10):
            raise BrokerError("merge request expiry exceeds its bounded lease")
        if request["repository"] != repository or request["pull_request"] != pull_number:
            raise BrokerError("merge request provider identity changed")
        if request["base_sha"] != base_sha or request["head_sha"] != head_sha:
            raise BrokerError("merge request head or base changed")
        if review.get("commit_id") != head_sha:
            raise BrokerError("merge request review is not anchored to the exact head")
        requests.append((review_id, submitted_at, request, actor_id, actor_login))
    if not requests:
        if owner_context is not None:
            return _select_owner_admission(
                commits=commits,
                now=now,
                owner_context=owner_context,
                pull=pull,
                repository=repository,
                repair=False,
                reviews=reviews,
            )
        raise BrokerError("pull request has no exact merge request review")
    request_review_id, submitted_at, request, requester_id, requester_login = max(
        requests, key=lambda item: item[0]
    )
    if now < submitted_at - timedelta(seconds=60) or now >= _timestamp(request["expires_at"]):
        raise BrokerError("merge request is not currently valid")
    request_digest = digest(request)
    commit_ids, commit_logins = _commit_actor_ids(commits)
    disallowed_ids = {author_id, requester_id, *commit_ids}
    disallowed_logins = {requester_login, *commit_logins}
    latest_decisive: dict[int, tuple[int, dict[str, Any], datetime, str]] = {}
    for review in reviews:
        state = review.get("state")
        if state not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        reviewer_id, reviewer_login = _review_actor(review)
        review_id = _require_positive_int(review.get("id"), "decisive review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("decisive review time is malformed")
        review_time = _timestamp(submitted_raw)
        if review_time <= submitted_at:
            continue
        previous = latest_decisive.get(reviewer_id)
        if previous is None or review_id > previous[0]:
            latest_decisive[reviewer_id] = (review_id, review, review_time, reviewer_login)
    approvals: list[tuple[int, int, str]] = []
    for reviewer_id, (review_id, review, review_time, reviewer_login) in latest_decisive.items():
        permission = reviewer_permissions.get(reviewer_login)
        if (
            review.get("state") == "CHANGES_REQUESTED"
            and permission in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS
        ):
            raise BrokerError("pull request has current requested changes")
        if review.get("state") != "APPROVED" or review_time > now + timedelta(seconds=60):
            continue
        try:
            approved_digest = parse_approval(review.get("body"))
        except BrokerError:
            continue
        if approved_digest != request_digest:
            continue
        if review.get("commit_id") != head_sha:
            continue
        if reviewer_id in disallowed_ids or reviewer_login in disallowed_logins:
            continue
        if permission not in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS:
            continue
        approvals.append((review_id, reviewer_id, reviewer_login))
    if not approvals:
        if owner_context is not None:
            return _select_owner_admission(
                commits=commits,
                now=now,
                owner_context=owner_context,
                pull=pull,
                repository=repository,
                repair=False,
                reviews=reviews,
            )
        raise BrokerError("merge request has no current independent provider approval")
    approval_review_id, approver_id, approver_login = max(approvals, key=lambda item: item[0])
    return {
        "approval_review_id": approval_review_id,
        "approver_id": approver_id,
        "approver_login": approver_login,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "health_generation": request["health_generation"],
        "kind": "normal",
        "nonce": request["nonce"],
        "pull_request": pull_number,
        "request": request,
        "request_digest": request_digest,
        "request_review_id": request_review_id,
        "requester_id": requester_id,
        "reviewer_permission": reviewer_permissions[approver_login],
        "schema_version": 1,
    }


def select_repair_admission(
    *,
    commits: list[dict[str, Any]],
    now: datetime,
    pull: dict[str, Any],
    repository: str,
    reviewer_permissions: dict[str, str],
    reviews: list[dict[str, Any]],
    state: dict[str, Any],
    owner_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pull_number = _require_positive_int(pull.get("number"), "repair pull request number")
    if pull.get("state") != "open" or pull.get("draft") is not False:
        raise BrokerError("repair pull request is not an open non-draft candidate")
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not all(isinstance(item, dict) for item in (base, head, author)):
        raise BrokerError("repair pull request identity is malformed")
    assert isinstance(base, dict) and isinstance(head, dict) and isinstance(author, dict)
    head_repository = head.get("repo")
    if (
        base.get("ref") != "main"
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise BrokerError("fork or non-main pull request cannot enter repair admission")
    base_sha = _require_sha(base.get("sha"), "repair pull request base SHA")
    head_sha = _require_sha(head.get("sha"), "repair pull request head SHA")
    author_id = _require_positive_int(author.get("id"), "repair pull request author ID")
    if state.get("status") != "red" or not isinstance(state.get("incident_digest"), str):
        raise BrokerError("repair admission requires one open red incident")

    requests: list[tuple[int, datetime, dict[str, Any], int, str]] = []
    for review in reviews:
        body = review.get("body")
        if not isinstance(body, str) or not body.startswith(REPAIR_REQUEST_MARKER):
            continue
        if review.get("state") != "COMMENTED":
            raise BrokerError("repair request must be a COMMENTED provider review")
        actor_id, actor_login = _review_actor(review)
        request = parse_repair_request(body, reviewer_id=actor_id)
        review_id = _require_positive_int(review.get("id"), "repair request review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("repair request review time is malformed")
        submitted_at = _timestamp(submitted_raw)
        expires_at = _timestamp(request["expires_at"])
        if expires_at <= submitted_at or expires_at - submitted_at > timedelta(minutes=10):
            raise BrokerError("repair request expiry exceeds its bounded lease")
        if request["repository"] != repository or request["pull_request"] != pull_number:
            raise BrokerError("repair request provider identity changed")
        if request["base_sha"] != base_sha or request["head_sha"] != head_sha:
            raise BrokerError("repair request head or base changed")
        if review.get("commit_id") != head_sha:
            raise BrokerError("repair request review is not anchored to the exact head")
        if request["incident_digest"] != state["incident_digest"] or request[
            "state_generation"
        ] != state.get("generation"):
            raise BrokerError("repair request does not bind the open incident generation")
        requests.append((review_id, submitted_at, request, actor_id, actor_login))
    if not requests:
        if owner_context is not None:
            return _select_owner_admission(
                commits=commits,
                now=now,
                owner_context=owner_context,
                pull=pull,
                repository=repository,
                repair=True,
                reviews=reviews,
                state=state,
            )
        raise BrokerError("pull request has no exact repair request review")
    request_review_id, submitted_at, request, requester_id, requester_login = max(
        requests, key=lambda item: item[0]
    )
    if now < submitted_at - timedelta(seconds=60) or now >= _timestamp(request["expires_at"]):
        raise BrokerError("repair request is not currently valid")

    request_digest = digest(request)
    commit_ids, commit_logins = _commit_actor_ids(commits)
    disallowed_ids = {author_id, requester_id, *commit_ids}
    disallowed_logins = {requester_login, *commit_logins}
    latest_decisive: dict[int, tuple[int, dict[str, Any], datetime, str]] = {}
    for review in reviews:
        review_state = review.get("state")
        if review_state not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        reviewer_id, reviewer_login = _review_actor(review)
        review_id = _require_positive_int(review.get("id"), "repair decisive review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("repair decisive review time is malformed")
        review_time = _timestamp(submitted_raw)
        if review_time <= submitted_at:
            continue
        previous = latest_decisive.get(reviewer_id)
        if previous is None or review_id > previous[0]:
            latest_decisive[reviewer_id] = (review_id, review, review_time, reviewer_login)

    approval_marker = (
        f"Main-health repair authorization: {request['issue']}\n"
        f"Incident: {request['incident_digest']}"
    )
    approvals: list[tuple[int, int, str, str]] = []
    for reviewer_id, (review_id, review, review_time, reviewer_login) in latest_decisive.items():
        permission = reviewer_permissions.get(reviewer_login)
        if permission not in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS:
            continue
        if review.get("state") == "CHANGES_REQUESTED":
            raise BrokerError("repair pull request has current requested changes")
        if (
            review.get("state") != "APPROVED"
            or review_time > now + timedelta(seconds=60)
            or (review.get("body") or "").strip() != approval_marker
            or review.get("commit_id") != head_sha
            or reviewer_id in disallowed_ids
            or reviewer_login in disallowed_logins
        ):
            continue
        approvals.append((review_id, reviewer_id, reviewer_login, permission))
    if not approvals:
        if owner_context is not None:
            return _select_owner_admission(
                commits=commits,
                now=now,
                owner_context=owner_context,
                pull=pull,
                repository=repository,
                repair=True,
                reviews=reviews,
                state=state,
            )
        raise BrokerError("repair request has no current independent provider approval")
    approval_review_id, approver_id, approver_login, reviewer_permission = max(
        approvals, key=lambda item: item[0]
    )
    return {
        "approval_review_id": approval_review_id,
        "approver_id": approver_id,
        "approver_login": approver_login,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "incident_digest": request["incident_digest"],
        "issue": request["issue"],
        "kind": "repair",
        "nonce": request["nonce"],
        "pull_request": pull_number,
        "request": request,
        "request_digest": request_digest,
        "request_review_id": request_review_id,
        "requester_id": requester_id,
        "reviewer_permission": reviewer_permission,
        "schema_version": 1,
        "state_generation": request["state_generation"],
    }


def validate_core_checks(*, check_runs: list[dict[str, Any]], head_sha: str) -> dict[str, int]:
    _require_sha(head_sha, "required-check head SHA")
    selected: dict[str, int] = {}
    for name in CORE_CHECKS:
        matching = []
        for check_run in check_runs:
            app = check_run.get("app")
            if (
                check_run.get("name") == name
                and check_run.get("head_sha") == head_sha
                and isinstance(app, dict)
                and app.get("id") == ACTIONS_INTEGRATION_ID
            ):
                matching.append(check_run)
        if not matching:
            raise BrokerError(f"{name}: exact Actions check is missing")
        latest = max(matching, key=lambda item: _require_positive_int(item.get("id"), "check ID"))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise BrokerError(f"{name}: latest exact Actions check is not successful")
        selected[name] = _require_positive_int(latest.get("id"), "check ID")
    return selected


class CheckController:
    def __init__(
        self,
        *,
        api: GitHubApi,
        config: BrokerConfig,
        spool: DurableSpool,
        token: str,
    ) -> None:
        self.api = api
        self.config = config
        self.spool = spool
        self.token = token

    def _runs(self, head_sha: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"check_name": MAIN_HEALTH_CHECK, "filter": "all"})
        runs = self.api.list_items(
            f"repos/{self.config.repository}/commits/{head_sha}/check-runs?{query}",
            key="check_runs",
            token=self.token,
        )
        return [
            run
            for run in runs
            if run.get("name") == MAIN_HEALTH_CHECK
            and isinstance(run.get("app"), dict)
            and run["app"].get("id") == self.config.app_id
        ]

    def _payload(
        self,
        *,
        completed_at: datetime | None = None,
        conclusion: str,
        external_id: str,
        head_sha: str,
        summary: str,
        title: str,
    ) -> dict[str, Any]:
        if completed_at is None:
            completed_at = self.api.provider_now(self.token)
        completed_at = completed_at.replace(microsecond=0)
        return {
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
            "conclusion": conclusion,
            "details_url": f"https://github.com/{self.config.repository}/commit/{head_sha}",
            "external_id": external_id,
            "name": MAIN_HEALTH_CHECK,
            "output": {"summary": summary, "title": title},
            "status": "completed",
        }

    def _validate_response(
        self,
        value: Any,
        *,
        check_run_id: int,
        conclusion: str,
        external_id: str,
        head_sha: str,
        name: str = MAIN_HEALTH_CHECK,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise BrokerError("App check-run response is malformed")
        app = value.get("app")
        if not (
            value.get("id") == check_run_id
            and value.get("head_sha") == head_sha
            and value.get("name") == name
            and value.get("status") == "completed"
            and value.get("conclusion") == conclusion
            and value.get("external_id") == external_id
            and isinstance(app, dict)
            and app.get("id") == self.config.app_id
            and app.get("slug") == self.config.app_slug
        ):
            raise BrokerError("App check-run response is not provider-bound")
        return value

    def ensure_failed(self, *, head_sha: str, reason: str) -> int:
        _require_sha(head_sha, "App check head SHA")
        runs = self._runs(head_sha)
        ids = sorted(_require_positive_int(run.get("id"), "App check ID") for run in runs)
        stored_id = self.spool.get_check_id(head_sha)
        canonical_id = stored_id if stored_id in ids else (ids[0] if ids else None)
        canonical_run = next(
            (
                run
                for run in runs
                if _require_positive_int(run.get("id"), "App check ID") == canonical_id
            ),
            None,
        )
        for run in runs:
            check_run_id = _require_positive_int(run.get("id"), "App check ID")
            if check_run_id == canonical_id:
                continue
            completed_at = self.api.provider_now(self.token).replace(microsecond=0)
            external_id = f"mhb1:superseded:{check_run_id}"
            name = f"{MAIN_HEALTH_CHECK} [superseded {check_run_id}]"
            result = self.api.request(
                f"repos/{self.config.repository}/check-runs/{check_run_id}",
                token=self.token,
                method="PATCH",
                payload={
                    "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
                    "conclusion": "failure",
                    "details_url": f"https://github.com/{self.config.repository}/commit/{head_sha}",
                    "external_id": external_id,
                    "name": name,
                    "output": {
                        "summary": f"Canonical broker check is {canonical_id}.",
                        "title": "Superseded broker check",
                    },
                    "status": "completed",
                },
            )
            self._validate_response(
                result.value,
                check_run_id=check_run_id,
                conclusion="failure",
                external_id=external_id,
                head_sha=head_sha,
                name=name,
            )
        consumed_digest: str | None = None
        if canonical_run is not None:
            previous_external_id = canonical_run.get("external_id")
            if isinstance(previous_external_id, str):
                consumed = re.fullmatch(
                    r"mhb1:(?:consumed|merge):([0-9a-f]{64})", previous_external_id
                )
                if consumed is not None:
                    consumed_digest = consumed.group(1)
        external_id = (
            f"mhb1:consumed:{consumed_digest}"
            if consumed_digest is not None
            else f"mhb1:closed:{digest({'head_sha': head_sha, 'reason': reason})}"
        )
        payload = self._payload(
            conclusion="failure",
            external_id=external_id,
            head_sha=head_sha,
            summary=reason,
            title="Broker admission closed",
        )
        if canonical_id is None:
            result = self.api.request(
                f"repos/{self.config.repository}/check-runs",
                token=self.token,
                method="POST",
                payload={"head_sha": head_sha, **payload},
                expected=(201,),
            )
            if not isinstance(result.value, dict):
                raise BrokerError("App check creation response is malformed")
            canonical_id = _require_positive_int(result.value.get("id"), "App check ID")
        else:
            result = self.api.request(
                f"repos/{self.config.repository}/check-runs/{canonical_id}",
                token=self.token,
                method="PATCH",
                payload=payload,
            )
        value = self._validate_response(
            result.value,
            check_run_id=canonical_id,
            conclusion="failure",
            external_id=external_id,
            head_sha=head_sha,
        )
        completed_at_value = value.get("completed_at")
        if not isinstance(completed_at_value, str):
            raise BrokerError("App check completion time is malformed")
        self.spool.record_check(
            head_sha=head_sha,
            check_run_id=canonical_id,
            external_id=external_id,
            updated_at=completed_at_value,
        )
        return canonical_id

    def succeed(
        self,
        *,
        check_run_id: int,
        head_sha: str,
        request: dict[str, Any],
        request_digest: str,
        summary: str,
    ) -> dict[str, Any]:
        if DIGEST_RE.fullmatch(request_digest) is None:
            raise BrokerError("App check request digest is invalid")
        if digest(request) != request_digest:
            raise BrokerError("App check request does not match its admission digest")
        expires_at = request.get("expires_at")
        if not isinstance(expires_at, str):
            raise BrokerError("App check admission expiry is malformed")
        publication_now = self.api.provider_now(self.token)
        if publication_now >= _timestamp(expires_at):
            raise BrokerError("broker admission lease expired before success publication")
        if self.spool.get_check_id(head_sha) != check_run_id:
            raise BrokerError("App check ID changed before success publication")
        external_id = f"mhb1:merge:{request_digest}"
        result = self.api.request(
            f"repos/{self.config.repository}/check-runs/{check_run_id}",
            token=self.token,
            method="PATCH",
            payload=self._payload(
                completed_at=publication_now,
                conclusion="success",
                external_id=external_id,
                head_sha=head_sha,
                summary=summary,
                title="Broker admission passed",
            ),
        )
        value = self._validate_response(
            result.value,
            check_run_id=check_run_id,
            conclusion="success",
            external_id=external_id,
            head_sha=head_sha,
        )
        completed_at = value.get("completed_at")
        if not isinstance(completed_at, str):
            raise BrokerError("App check completion time is malformed")
        self.spool.record_check(
            head_sha=head_sha,
            check_run_id=check_run_id,
            external_id=external_id,
            updated_at=completed_at,
        )
        return value


def _git_environment(token: str) -> dict[str, str]:
    try:
        basic_credential = base64.b64encode(f"x-access-token:{token}".encode("ascii")).decode(
            "ascii"
        )
    except UnicodeEncodeError as exc:
        raise BrokerError("GitHub App token is not ASCII") from exc
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic_credential}",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _git(
    root: Path,
    *arguments: str,
    token: str,
    check: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    command_environment = _git_environment(token)
    if environment:
        command_environment.update(environment)
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        env=command_environment,
        check=False,
    )
    if check and completed.returncode != 0:
        raise BrokerError(f"state-branch git command failed: git {' '.join(arguments)}")
    return completed


def _deep_result_identity(value: Any) -> tuple[int, int]:
    if not isinstance(value, str):
        raise BrokerError("deep-health result run identity is malformed")
    if value.isdigit():
        return (_require_positive_int(int(value), "legacy deep-health run ID"), 1)
    match = re.fullmatch(r"github-actions:([1-9][0-9]*):([1-9][0-9]*)", value)
    if match is None:
        raise BrokerError("deep-health result run identity is not canonical")
    return (int(match.group(1)), int(match.group(2)))


def _protected_main_result_identity(value: Any) -> str:
    if not isinstance(value, str):
        raise BrokerError("protected-main result run identity is malformed")
    if value.isdigit():
        run_id = _require_positive_int(int(value), "legacy protected-main run ID")
        return f"legacy-github-actions:{run_id}"
    if re.fullmatch(r"github-actions:[1-9][0-9]*:[1-9][0-9]*", value):
        return value
    if re.fullmatch(
        r"github-actions-set:v1:"
        r"metriplane=[1-9][0-9]*:[1-9][0-9]*;"
        r"documentation=(?:[1-9][0-9]*:[1-9][0-9]*|missing);"
        r"security=(?:[1-9][0-9]*:[1-9][0-9]*|missing)",
        value,
    ):
        return value
    raise BrokerError("protected-main result run identity is not canonical")


def _protected_main_selection_identity(selection: Mapping[str, Any]) -> str:
    runs = selection.get("runs")
    if not isinstance(runs, list):
        raise BrokerError("protected-main workflow selection is malformed")
    identities: dict[str, str] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise BrokerError("protected-main selected run is malformed")
        key = run.get("key")
        if key not in observe_main_health.REQUIRED_WORKFLOWS or key in identities:
            raise BrokerError("protected-main selected workflow identity is not exact")
        run_id = _require_positive_int(run.get("id"), f"{key} run ID")
        attempt = _require_positive_int(run.get("run_attempt"), f"{key} run attempt")
        identities[str(key)] = f"{run_id}:{attempt}"
    if "metriplane" not in identities:
        raise BrokerError("protected-main selection omits the triggering CI attempt")
    return (
        "github-actions-set:v1:"
        f"metriplane={identities['metriplane']};"
        f"documentation={identities.get('documentation', 'missing')};"
        f"security={identities.get('security', 'missing')}"
    )


def _repair_passing_results(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted((root / "history").glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BrokerError(f"cannot read repair history {path.name}") from exc
        if not isinstance(entry, dict):
            raise BrokerError("repair history entry is not an object")
        if entry.get("cadence") == "repair-resolution":
            continue
        result_digest = entry.get("result_digest")
        if not isinstance(result_digest, str) or DIGEST_RE.fullmatch(result_digest) is None:
            raise BrokerError("repair history result digest is malformed")
        try:
            result = json.loads(
                (root / "results" / f"{result_digest}.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BrokerError("cannot read retained repair result") from exc
        if not isinstance(result, dict):
            raise BrokerError("retained repair result is not an object")
        cadence = result.get("cadence")
        sha = result.get("sha")
        if cadence not in {"protected-main", "nightly", "weekly"}:
            continue
        if not isinstance(sha, str):
            raise BrokerError("repair result SHA is malformed")
        if cadence == "protected-main" and not _protected_main_result_identity(
            result.get("run_id")
        ).startswith("github-actions-set:v1:"):
            continue
        latest[(sha, str(cadence))] = result
    return {key: result for key, result in latest.items() if result.get("conclusion") == "success"}


class StateBranch:
    """Authoritative append-only health state stored on the protected provider branch."""

    def __init__(
        self,
        *,
        api: GitHubApi,
        config: BrokerConfig,
        token: str,
    ) -> None:
        self.api = api
        self.config = config
        self.token = token

    def provider_ref(self) -> str:
        result = self.api.request(
            f"repos/{self.config.repository}/git/ref/heads/{self.config.state_branch}",
            token=self.token,
        )
        if not isinstance(result.value, dict):
            raise BrokerError("state-branch ref response is malformed")
        provider_object = result.value.get("object")
        if (
            result.value.get("ref") != f"refs/heads/{self.config.state_branch}"
            or not isinstance(provider_object, dict)
            or provider_object.get("type") != "commit"
        ):
            raise BrokerError("state-branch ref response is not provider-bound")
        return _require_sha(provider_object.get("sha"), "state-branch ref SHA")

    def _checkout(self, root: Path, expected_ref: str) -> None:
        _git(root, "init", "--quiet", token=self.token)
        _git(
            root,
            "remote",
            "add",
            "origin",
            f"https://github.com/{self.config.repository}.git",
            token=self.token,
        )
        _git(
            root,
            "fetch",
            "--quiet",
            "origin",
            f"refs/heads/{self.config.state_branch}",
            token=self.token,
        )
        _git(root, "checkout", "--quiet", "--detach", "FETCH_HEAD", token=self.token)
        actual = _git(root, "rev-parse", "HEAD", token=self.token).stdout.decode().strip()
        if actual != expected_ref:
            raise BrokerError("state checkout does not match the provider ref")

    @staticmethod
    def _deep_identities(root: Path) -> dict[str, set[tuple[int, int]]]:
        identities: dict[str, set[tuple[int, int]]] = {"nightly": set(), "weekly": set()}
        for path in sorted((root / "results").glob("*.json")):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BrokerError(f"cannot read protected deep-health result {path.name}") from exc
            if not isinstance(result, dict) or result.get("cadence") not in identities:
                continue
            cadence = str(result["cadence"])
            identity = _deep_result_identity(result.get("run_id"))
            if identity in identities[cadence]:
                raise BrokerError("protected state repeats a deep-health run attempt")
            identities[cadence].add(identity)
        return identities

    @staticmethod
    def _result_identities(root: Path) -> set[tuple[str, str]]:
        identities: set[tuple[str, str]] = set()
        for path in sorted((root / "results").glob("*.json")):
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BrokerError(f"cannot read protected result {path.name}") from exc
            if not isinstance(result, dict):
                raise BrokerError("protected result is not an object")
            cadence = result.get("cadence")
            if cadence not in {"protected-main", "nightly", "weekly"}:
                continue
            if cadence == "protected-main":
                run_identity = result.get("run_id")
                identity = _protected_main_result_identity(run_identity)
                if isinstance(run_identity, str) and run_identity.isdigit():
                    result_digest = digest(result)
                    if path.name != f"{result_digest}.json":
                        raise BrokerError("legacy protected-main result is not digest-bound")
                    if (run_identity, result_digest) not in LEGACY_PROTECTED_MAIN_RESULTS:
                        raise BrokerError(
                            "legacy protected-main result is not an approved immutable record"
                        )
                    identity = f"legacy-result:{run_identity}:{result_digest}"
            else:
                run_id, attempt = _deep_result_identity(result.get("run_id"))
                identity = f"github-actions:{run_id}:{attempt}"
            result_identity = (str(cadence), identity)
            if result_identity in identities:
                raise BrokerError("protected state repeats a result identity")
            identities.add(result_identity)
        return identities

    def read_with_deep_identities(
        self,
    ) -> tuple[dict[str, Any], dict[str, set[tuple[int, int]]]]:
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-read-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            state = stop_the_line.validate_git_history(root)
            identities = self._deep_identities(root)
        after = self.provider_ref()
        if after != before or state.get("state_commit") != before:
            raise BrokerError("state branch changed during read-back validation")
        return state, identities

    def read_with_result_identities(
        self,
    ) -> tuple[dict[str, Any], set[tuple[str, str]]]:
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-results-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            state = stop_the_line.validate_git_history(root)
            identities = self._result_identities(root)
        after = self.provider_ref()
        if after != before or state.get("state_commit") != before:
            raise BrokerError("state branch changed during result identity validation")
        return state, identities

    def read(self) -> dict[str, Any]:
        state, _identities = self.read_with_deep_identities()
        return state

    def validate_owner_emergency_candidate(
        self,
        *,
        checked_at: str,
        collaborators: list[dict[str, Any]],
        expected_head_sha: str,
        files: list[dict[str, Any]],
        invitations: list[dict[str, Any]],
        manifest: dict[str, Any],
        pull: dict[str, Any],
    ) -> dict[str, Any]:
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-owner-admission-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            try:
                candidate = stop_the_line.validate_owner_emergency_candidate(
                    root,
                    manifest=manifest,
                    pull=pull,
                    files=files,
                    collaborators=collaborators,
                    invitations=invitations,
                    expected_head_sha=expected_head_sha,
                    checked_at=checked_at,
                )
            except stop_the_line.HealthError as exc:
                raise BrokerError(f"owner-emergency candidate validation failed: {exc}") from exc
        after = self.provider_ref()
        if after != before:
            raise BrokerError("state branch changed during owner-emergency admission")
        return candidate

    def append(
        self,
        *,
        expected_generation: int,
        scope: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        if scope == "main" and not _protected_main_result_identity(
            summary.get("run_id")
        ).startswith("github-actions-set:v1:"):
            raise BrokerError("new protected-main result must use an aggregate identity")
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-write-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            current = stop_the_line.validate_git_history(root)
            if current.get("generation") != expected_generation:
                raise BrokerError("state generation changed before append")
            updated = stop_the_line.ingest(
                root,
                scope=scope,
                summary=summary,
                expected_generation=expected_generation,
            )
            _git(root, "add", "--all", token=self.token)
            staged = _git(root, "diff", "--cached", "--quiet", token=self.token, check=False)
            if staged.returncode != 1:
                raise BrokerError("state append did not produce one staged transition")
            commit_environment = {
                "GIT_AUTHOR_EMAIL": "main-health-broker@users.noreply.github.com",
                "GIT_AUTHOR_NAME": "Metriplane Main Health Broker",
                "GIT_COMMITTER_EMAIL": "main-health-broker@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "Metriplane Main Health Broker",
            }
            _git(
                root,
                "commit",
                "--quiet",
                "-m",
                f"Record {scope} health generation {updated['generation']}",
                token=self.token,
                environment=commit_environment,
            )
            new_commit = _git(root, "rev-parse", "HEAD", token=self.token).stdout.decode().strip()
            parent = _git(root, "rev-parse", "HEAD^", token=self.token).stdout.decode().strip()
            _require_sha(new_commit, "new state commit")
            if parent != before:
                raise BrokerError("state append is not a direct fast-forward")
            if self.provider_ref() != before:
                raise BrokerError("state branch changed before CAS push")
            _git(
                root,
                "push",
                "--quiet",
                "origin",
                f"HEAD:refs/heads/{self.config.state_branch}",
                token=self.token,
            )
        if self.provider_ref() != new_commit:
            raise BrokerError("state branch push was not read back exactly")
        read_back = self.read()
        if read_back.get("state_commit") != new_commit or read_back.get("generation") != (
            expected_generation + 1
        ):
            raise BrokerError("state branch append read-back is not exact")
        return read_back

    def repair_context(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[tuple[str, str], dict[str, Any]]]:
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-repair-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            state = stop_the_line.validate_git_history(root)
            passing = _repair_passing_results(root)
            incident: dict[str, Any] | None = None
            incident_digest = state.get("incident_digest")
            if incident_digest is not None:
                try:
                    value = json.loads(
                        (root / "incidents" / f"{incident_digest}.json").read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise BrokerError("cannot read protected repair incident") from exc
                if not isinstance(value, dict) or digest(value) != incident_digest:
                    raise BrokerError("protected repair incident is not digest-bound")
                incident = value
        after = self.provider_ref()
        if after != before or state.get("state_commit") != before:
            raise BrokerError("state branch changed during repair context validation")
        return state, incident, passing

    def resolve_repair(
        self,
        *,
        approval_evidence: dict[str, Any],
        authorization: dict[str, Any],
        expected_generation: int,
        repaired_main: dict[str, Any],
        resolved_at: str,
    ) -> dict[str, Any]:
        before = self.provider_ref()
        self.config.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            dir=self.config.state_root, prefix="state-resolve-"
        ) as temporary:
            root = Path(temporary)
            self._checkout(root, before)
            current = stop_the_line.validate_git_history(root)
            if current.get("generation") != expected_generation:
                raise BrokerError("state generation changed before repair resolution")
            updated = stop_the_line.resolve(
                root,
                authorization=authorization,
                approval_evidence=approval_evidence,
                repaired_main=repaired_main,
                resolved_at=resolved_at,
                expected_generation=expected_generation,
            )
            _git(root, "add", "--all", token=self.token)
            staged = _git(root, "diff", "--cached", "--quiet", token=self.token, check=False)
            if staged.returncode != 1:
                raise BrokerError("repair resolution did not produce one staged transition")
            commit_environment = {
                "GIT_AUTHOR_EMAIL": "main-health-broker@users.noreply.github.com",
                "GIT_AUTHOR_NAME": "Metriplane Main Health Broker",
                "GIT_COMMITTER_EMAIL": "main-health-broker@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "Metriplane Main Health Broker",
            }
            _git(
                root,
                "commit",
                "--quiet",
                "-m",
                f"Resolve main health generation {updated['generation']}",
                token=self.token,
                environment=commit_environment,
            )
            new_commit = _git(root, "rev-parse", "HEAD", token=self.token).stdout.decode().strip()
            parent = _git(root, "rev-parse", "HEAD^", token=self.token).stdout.decode().strip()
            _require_sha(new_commit, "repair resolution state commit")
            if parent != before or self.provider_ref() != before:
                raise BrokerError("repair resolution is not an exact direct fast-forward")
            _git(
                root,
                "push",
                "--quiet",
                "origin",
                f"HEAD:refs/heads/{self.config.state_branch}",
                token=self.token,
            )
        if self.provider_ref() != new_commit:
            raise BrokerError("repair resolution push was not read back exactly")
        read_back = self.read()
        if (
            read_back.get("state_commit") != new_commit
            or read_back.get("generation") != expected_generation + 1
            or read_back.get("status") != "green"
        ):
            raise BrokerError("repair resolution read-back is not exact")
        return read_back


def _main_ref(api: GitHubApi, *, config: BrokerConfig, token: str) -> str:
    result = api.request(
        f"repos/{config.repository}/git/ref/heads/main",
        token=token,
    )
    if not isinstance(result.value, dict):
        raise BrokerError("main ref response is malformed")
    provider_object = result.value.get("object")
    if (
        result.value.get("ref") != "refs/heads/main"
        or not isinstance(provider_object, dict)
        or provider_object.get("type") != "commit"
    ):
        raise BrokerError("main ref response is not provider-bound")
    return _require_sha(provider_object.get("sha"), "main ref SHA")


def _check_runs(
    api: GitHubApi, *, config: BrokerConfig, head_sha: str, token: str
) -> list[dict[str, Any]]:
    return api.list_items(
        f"repos/{config.repository}/commits/{head_sha}/check-runs?filter=all",
        key="check_runs",
        token=token,
    )


def _validate_runtime_repository(api: GitHubApi, *, config: BrokerConfig, token: str) -> int:
    result = api.request(f"repos/{config.repository}", token=token)
    value = result.value
    if not isinstance(value, dict):
        raise BrokerError("runtime repository response is malformed")
    owner = value.get("owner")
    if not isinstance(owner, dict):
        raise BrokerError("runtime repository owner is malformed")
    _require_positive_int(value.get("id"), "runtime repository ID")
    _require_positive_int(owner.get("id"), "runtime repository owner ID")
    if (
        config.repository != REPOSITORY
        or value.get("name") != REPOSITORY_NAME
        or value.get("full_name") != config.repository
        or value.get("default_branch") != MAIN_BRANCH
        or owner.get("login") != REPOSITORY_OWNER
        or owner.get("type") != "User"
    ):
        raise BrokerError("runtime repository identity or default branch is not canonical")
    return _require_positive_int(owner.get("id"), "runtime repository owner ID")


def _rulesets(api: GitHubApi, *, config: BrokerConfig, token: str) -> dict[int, dict[str, Any]]:
    _validate_runtime_repository(api, config=config, token=token)
    identifiers = (
        config.core_ruleset_id,
        config.admission_ruleset_id,
        config.main_update_ruleset_id,
        config.state_protection_ruleset_id,
        config.state_writer_ruleset_id,
        config.release_lease_ruleset_id,
        config.release_tag_ruleset_id,
    )
    if len(set(identifiers)) != len(identifiers):
        raise BrokerError("governed ruleset IDs are not distinct")
    inventory = _provider_list(
        api,
        f"repos/{config.repository}/rulesets?includes_parents=true",
        token=token,
    )
    active = [item for item in inventory if item.get("enforcement") == "active"]
    active_ids = [_require_positive_int(item.get("id"), "active ruleset ID") for item in active]
    if len(active_ids) != len(set(active_ids)) or set(active_ids) != set(identifiers):
        raise BrokerError("active ruleset inventory is not the exact governed set")
    active_by_id = {identifier: item for identifier, item in zip(active_ids, active, strict=True)}
    values: dict[int, dict[str, Any]] = {}
    for identifier in identifiers:
        result = api.request(
            f"repos/{config.repository}/rulesets/{identifier}",
            token=token,
        )
        if not isinstance(result.value, dict):
            raise BrokerError(f"ruleset {identifier} response is malformed")
        if result.value.get("id") != identifier:
            raise BrokerError(f"ruleset {identifier} response has the wrong provider ID")
        summary = active_by_id[identifier]
        for field in ("enforcement", "name", "source", "source_type", "target"):
            if result.value.get(field) != summary.get(field):
                raise BrokerError(f"ruleset {identifier} inventory and detail {field} differ")
        values[identifier] = result.value
    return values


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _local_authority_blob(path: str) -> tuple[bytes, str]:
    root = Path(__file__).resolve().parents[1]
    candidate = root / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise BrokerError(f"local publish authority path is invalid: {path}") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise BrokerError(f"local publish authority path is not a regular file: {path}")
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise BrokerError(f"cannot read local publish authority path: {path}") from exc
    header = f"blob {len(content)}\0".encode()
    blob_sha = hashlib.sha1(header + content, usedforsecurity=False).hexdigest()
    return content, blob_sha


def _validate_publish_authority(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    release_sha: str,
    token: str,
) -> dict[str, str]:
    release_sha = _require_sha(release_sha, "publish authority release SHA")
    digests: dict[str, str] = {}
    for path in PUBLISH_AUTHORITY_PATHS:
        local_content, local_blob_sha = _local_authority_blob(path)
        encoded_path = urllib.parse.quote(path, safe="/")
        query = urllib.parse.urlencode({"ref": release_sha})
        result = api.request(
            f"repos/{config.repository}/contents/{encoded_path}?{query}",
            token=token,
        )
        value = result.value
        if not isinstance(value, dict):
            raise BrokerError(f"provider publish authority is malformed: {path}")
        encoded_content = value.get("content")
        if not isinstance(encoded_content, str):
            raise BrokerError(f"provider publish authority content is missing: {path}")
        try:
            provider_content = base64.b64decode(
                "".join(encoded_content.splitlines()).encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise BrokerError(f"provider publish authority content is invalid: {path}") from exc
        if (
            value.get("type") != "file"
            or value.get("path") != path
            or value.get("sha") != local_blob_sha
            or value.get("size") != len(local_content)
            or value.get("encoding") != "base64"
            or provider_content != local_content
        ):
            raise BrokerError(f"provider publish authority differs from deployed broker: {path}")
        digests[path] = hashlib.sha256(local_content).hexdigest()
    return digests


def _require_owner_actor(value: Any, *, label: str, owner_id: int) -> None:
    if not isinstance(value, dict):
        raise BrokerError(f"{label} is malformed")
    if (
        value.get("id") != owner_id
        or value.get("login") != REPOSITORY_OWNER
        or value.get("type") != "User"
    ):
        raise BrokerError(f"{label} is not the canonical repository owner")


def _validate_publish_workflow(api: GitHubApi, *, config: BrokerConfig, token: str) -> int:
    result = api.request(
        f"repos/{config.repository}/actions/workflows/publish-pypi.yml",
        token=token,
    )
    value = result.value
    if not isinstance(value, dict):
        raise BrokerError("production workflow identity is malformed")
    workflow_id = _require_positive_int(value.get("id"), "production workflow ID")
    if (
        value.get("name") != PUBLISH_WORKFLOW_NAME
        or value.get("path") != PUBLISH_WORKFLOW_PATH
        or value.get("state") != "active"
    ):
        raise BrokerError("production workflow identity is not canonical and active")
    return workflow_id


def _publish_run_identity(
    run: dict[str, Any],
    *,
    config: BrokerConfig,
    main_sha: str,
    owner_id: int,
    workflow_id: int,
) -> tuple[int, int, datetime]:
    run_id = _require_positive_int(run.get("id"), "production workflow run ID")
    run_attempt = _require_positive_int(run.get("run_attempt"), "production workflow run attempt")
    head_sha = _require_sha(run.get("head_sha"), "production workflow head SHA")
    repository = run.get("repository")
    if not isinstance(repository, dict):
        raise BrokerError("production workflow repository identity is malformed")
    repository_owner = repository.get("owner")
    if not isinstance(repository_owner, dict):
        raise BrokerError("production workflow repository owner is malformed")
    _require_owner_actor(
        repository_owner, label="production workflow repository owner", owner_id=owner_id
    )
    if (
        run.get("name") != PUBLISH_WORKFLOW_NAME
        or run.get("path") != PUBLISH_WORKFLOW_PATH
        or run.get("workflow_id") != workflow_id
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != MAIN_BRANCH
        or head_sha != main_sha
        or repository.get("full_name") != config.repository
        or run.get("url")
        != f"https://api.github.com/repos/{config.repository}/actions/runs/{run_id}"
        or run.get("html_url") != f"https://github.com/{config.repository}/actions/runs/{run_id}"
    ):
        raise BrokerError("production workflow run identity is not canonical")
    _require_owner_actor(run.get("actor"), label="production workflow actor", owner_id=owner_id)
    _require_owner_actor(
        run.get("triggering_actor"),
        label="production workflow triggering actor",
        owner_id=owner_id,
    )
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status not in PROVIDER_ACTION_STATUSES:
        raise BrokerError("production workflow run status is invalid")
    if (status == "completed") != isinstance(conclusion, str):
        raise BrokerError("production workflow run conclusion is inconsistent")
    started_raw = run.get("run_started_at")
    created_raw = run.get("created_at")
    updated_raw = run.get("updated_at")
    if not all(isinstance(value, str) for value in (started_raw, created_raw, updated_raw)):
        raise BrokerError("production workflow run timestamps are malformed")
    assert (
        isinstance(started_raw, str)
        and isinstance(created_raw, str)
        and isinstance(updated_raw, str)
    )
    started_at = _timestamp(started_raw)
    created_at = _timestamp(created_raw)
    updated_at = _timestamp(updated_raw)
    if created_at > started_at or updated_at < started_at:
        raise BrokerError("production workflow run timestamps are inconsistent")
    return run_id, run_attempt, started_at


def _publish_jobs(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    lease: PublishLeaseRecord,
    token: str,
) -> list[dict[str, Any]]:
    jobs = api.list_items(
        (
            f"repos/{config.repository}/actions/runs/{lease.run_id}/attempts/"
            f"{lease.run_attempt}/jobs"
        ),
        key="jobs",
        token=token,
    )
    seen_ids: set[int] = set()
    for job in jobs:
        job_id = _require_positive_int(job.get("id"), "production workflow job ID")
        if job_id in seen_ids:
            raise BrokerError("production workflow job inventory contains duplicate IDs")
        seen_ids.add(job_id)
        if (
            job.get("run_id") != lease.run_id
            or job.get("run_url")
            != f"https://api.github.com/repos/{config.repository}/actions/runs/{lease.run_id}"
            or job.get("head_sha") != lease.release_sha
            or job.get("head_branch") != MAIN_BRANCH
            or job.get("workflow_name") != PUBLISH_WORKFLOW_NAME
            or not isinstance(job.get("name"), str)
            or job.get("status") not in PROVIDER_ACTION_STATUSES
        ):
            raise BrokerError("production workflow job identity is malformed")
        status = job["status"]
        if (status == "completed") != isinstance(job.get("conclusion"), str):
            raise BrokerError("production workflow job conclusion is inconsistent")
    return jobs


def _named_publish_job(
    jobs: list[dict[str, Any]], name: str, *, required: bool = True
) -> dict[str, Any] | None:
    matches = [job for job in jobs if job.get("name") == name]
    if len(matches) > 1 or (required and len(matches) != 1):
        raise BrokerError(f"production workflow job identity is not unique: {name}")
    return matches[0] if matches else None


def _named_publish_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    raw_steps = job.get("steps")
    if not isinstance(raw_steps, list) or not all(isinstance(step, dict) for step in raw_steps):
        raise BrokerError(f"production workflow job steps are malformed: {job.get('name')}")
    steps: list[dict[str, Any]] = [step for step in raw_steps if isinstance(step, dict)]
    numbers: set[int] = set()
    for step in steps:
        number = _require_positive_int(step.get("number"), "production workflow step number")
        if number in numbers:
            raise BrokerError("production workflow step inventory contains duplicate numbers")
        numbers.add(number)
        status = step.get("status")
        if status not in {"completed", "in_progress", "queued"}:
            raise BrokerError("production workflow step status is invalid")
        if (status == "completed") != isinstance(step.get("conclusion"), str):
            raise BrokerError("production workflow step conclusion is inconsistent")
    matches = [step for step in steps if step.get("name") == name]
    if len(matches) != 1:
        raise BrokerError(f"production workflow step identity is not unique: {name}")
    return matches[0]


def _completed_success(value: dict[str, Any]) -> bool:
    return value.get("status") == "completed" and value.get("conclusion") == "success"


def _publish_phase(jobs: list[dict[str, Any]]) -> tuple[str, datetime | None]:
    validate_job = _named_publish_job(jobs, PUBLISH_VALIDATE_JOB)
    artifact_job = _named_publish_job(jobs, PUBLISH_ARTIFACT_JOB)
    publish_job = _named_publish_job(jobs, PUBLISH_JOB)
    assert validate_job is not None and artifact_job is not None and publish_job is not None
    blocker_dispatch = _named_publish_step(validate_job, PUBLISH_DISPATCH_BLOCKER_STEP)
    prerequisites = (validate_job, artifact_job, blocker_dispatch)
    if any(
        item.get("status") == "completed" and not _completed_success(item) for item in prerequisites
    ):
        return "failed", None
    if not all(_completed_success(item) for item in prerequisites):
        return "not_ready", None

    wait_step = _named_publish_step(publish_job, PUBLISH_WAIT_STEP)
    blocker_step = _named_publish_step(publish_job, PUBLISH_FENCED_BLOCKER_STEP)
    reassert_step = _named_publish_step(publish_job, PUBLISH_REASSERT_STEP)
    upload_step = _named_publish_step(publish_job, PUBLISH_UPLOAD_STEP)
    ordered_steps = (wait_step, blocker_step, reassert_step, upload_step)
    if any(
        item.get("status") == "completed" and not _completed_success(item) for item in ordered_steps
    ):
        return "failed", None
    started_raw = wait_step.get("started_at")
    wait_started = _timestamp(started_raw) if isinstance(started_raw, str) else None
    if (
        publish_job.get("status") == "in_progress"
        and wait_step.get("status") == "in_progress"
        and all(step.get("status") == "queued" for step in ordered_steps[1:])
    ):
        if wait_started is None:
            raise BrokerError("production publish-lease wait step has no start time")
        return "awaiting", wait_started

    if not _completed_success(wait_step):
        if publish_job.get("status") == "completed":
            return "failed", wait_started
        return "not_ready", wait_started

    ranks = {"queued": 0, "in_progress": 1, "completed": 2}
    ordered_ranks = [ranks[str(step["status"])] for step in ordered_steps]
    if ordered_ranks != sorted(ordered_ranks, reverse=True):
        raise BrokerError("production publication steps are not monotonic")
    if sum(step.get("status") == "in_progress" for step in ordered_steps) > 1:
        raise BrokerError("production publication has concurrent critical steps")
    if publish_job.get("status") == "in_progress":
        return "publishing", wait_started
    if not _completed_success(publish_job):
        return "failed", wait_started
    if not all(_completed_success(step) for step in ordered_steps):
        raise BrokerError("successful production job omits a successful fenced publication step")

    verify_job = _named_publish_job(jobs, PUBLISH_VERIFY_JOB, required=False)
    if verify_job is None or verify_job.get("status") in PROVIDER_PENDING_ACTION_STATUSES:
        return "verifying", wait_started
    if not _completed_success(verify_job):
        return "failed", wait_started
    reconcile_job = _named_publish_job(jobs, PUBLISH_RECONCILE_JOB, required=False)
    if reconcile_job is None or reconcile_job.get("status") in (
        PROVIDER_PENDING_ACTION_STATUSES - {"in_progress"}
    ):
        return "verifying", wait_started
    if reconcile_job.get("status") == "completed":
        return ("completed" if _completed_success(reconcile_job) else "failed"), wait_started
    guard_step = _named_publish_step(reconcile_job, PUBLISH_RECONCILE_GUARD_STEP)
    observe_step = _named_publish_step(reconcile_job, PUBLISH_RECONCILE_OBSERVE_STEP)
    if _completed_success(guard_step) and observe_step.get("status") == "in_progress":
        return "reconciling", wait_started
    if guard_step.get("status") == "completed" and not _completed_success(guard_step):
        return "failed", wait_started
    if (
        guard_step.get("status") in {"queued", "in_progress"}
        and observe_step.get("status") == "queued"
    ):
        return "verifying", wait_started
    raise BrokerError("production reconciliation steps are not monotonic")


def _publish_lease_refs(api: GitHubApi, *, config: BrokerConfig, token: str) -> dict[str, str]:
    result = api.request(
        f"repos/{config.repository}/git/matching-refs/heads/release-leases/",
        token=token,
    )
    if not isinstance(result.value, list) or not all(
        isinstance(item, dict) for item in result.value
    ):
        raise BrokerError("provider publish-lease ref inventory is malformed")
    refs: dict[str, str] = {}
    pattern = re.compile(rf"{re.escape(PUBLISH_LEASE_REF_PREFIX)}[1-9][0-9]*-[1-9][0-9]*")
    for item in result.value:
        ref = item.get("ref")
        provider_object = item.get("object")
        if (
            not isinstance(ref, str)
            or pattern.fullmatch(ref) is None
            or not isinstance(provider_object, dict)
            or provider_object.get("type") != "commit"
        ):
            raise BrokerError("provider publish-lease ref identity is malformed")
        sha = _require_sha(provider_object.get("sha"), "provider publish-lease ref SHA")
        if ref in refs:
            raise BrokerError("provider publish-lease ref inventory contains duplicates")
        refs[ref] = sha
    if len(refs) > 1:
        raise BrokerError("provider contains concurrent publish-lease refs")
    return refs


def _publish_lease_output(
    record: PublishLeaseRecord, *, state: str, reason: str | None = None
) -> dict[str, str]:
    if state not in {"active", "quarantined", "released"}:
        raise BrokerError("publish-lease check output state is invalid")
    identity: dict[str, Any] = {
        "external_id": record.external_id,
        "lease_ref": record.lease_ref,
        "release_sha": record.release_sha,
        "repository": REPOSITORY,
        "run_attempt": record.run_attempt,
        "run_id": record.run_id,
        "schema_version": 1,
        "state": state,
    }
    if reason is not None:
        identity["reason"] = reason
    titles = {
        "active": "Production publication lease active",
        "quarantined": "Production publication lease quarantined",
        "released": "Production publication lease released",
    }
    return {
        "summary": canonical_bytes(identity).decode().rstrip("\n"),
        "title": titles[state],
    }


def _publish_lease_details_url(config: BrokerConfig, record: PublishLeaseRecord) -> str:
    return (
        f"https://github.com/{config.repository}/actions/runs/{record.run_id}/attempts/"
        f"{record.run_attempt}"
    )


def _validate_publish_lease_check(
    value: Any,
    *,
    config: BrokerConfig,
    record: PublishLeaseRecord,
    state: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrokerError("publish-lease check-run response is malformed")
    app = value.get("app")
    output = value.get("output")
    check_run_id = _require_positive_int(value.get("id"), "publish-lease check-run ID")
    expected_status = "in_progress" if state == "active" else "completed"
    expected_conclusion = (
        None if state == "active" else ("success" if state == "released" else "failure")
    )
    expected_output = _publish_lease_output(record, state=state, reason=reason)
    if (
        value.get("name") != PUBLISH_LEASE_CHECK
        or value.get("head_sha") != record.release_sha
        or value.get("external_id") != record.external_id
        or value.get("details_url") != _publish_lease_details_url(config, record)
        or value.get("status") != expected_status
        or value.get("conclusion") != expected_conclusion
        or not isinstance(output, dict)
        or output.get("summary") != expected_output["summary"]
        or output.get("title") != expected_output["title"]
        or not isinstance(app, dict)
        or app.get("id") != config.app_id
        or app.get("slug") != config.app_slug
    ):
        raise BrokerError("publish-lease check-run response is not provider-bound")
    if record.check_run_id is not None and check_run_id != record.check_run_id:
        raise BrokerError("publish-lease check-run identity changed")
    return value


def _publish_lease_check(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    record: PublishLeaseRecord,
    token: str,
) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"check_name": PUBLISH_LEASE_CHECK, "filter": "all"})
    runs = api.list_items(
        f"repos/{config.repository}/commits/{record.release_sha}/check-runs?{query}",
        key="check_runs",
        token=token,
    )
    matches = [run for run in runs if run.get("external_id") == record.external_id]
    if len(runs) > 100 or (not matches and len(runs) >= 100):
        raise BrokerError("provider publish-lease checks exceed the consumer inventory bound")
    if len(matches) > 1:
        raise BrokerError("provider contains duplicate publish-lease acknowledgments")
    return matches[0] if matches else None


def _publish_check_payload(
    *,
    config: BrokerConfig,
    record: PublishLeaseRecord,
    state: str,
    provider_now: datetime,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "details_url": _publish_lease_details_url(config, record),
        "external_id": record.external_id,
        "name": PUBLISH_LEASE_CHECK,
        "output": _publish_lease_output(record, state=state, reason=reason),
    }
    if state == "active":
        payload.update({"started_at": _format_timestamp(provider_now), "status": "in_progress"})
    else:
        payload.update(
            {
                "completed_at": _format_timestamp(provider_now),
                "conclusion": "success" if state == "released" else "failure",
                "status": "completed",
            }
        )
    return payload


def _create_publish_lease_check(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    record: PublishLeaseRecord,
    state: str,
    provider_now: datetime,
    token: str,
    reason: str | None = None,
) -> dict[str, Any]:
    result = api.request(
        f"repos/{config.repository}/check-runs",
        token=token,
        method="POST",
        payload={
            "head_sha": record.release_sha,
            **_publish_check_payload(
                config=config,
                record=record,
                state=state,
                provider_now=provider_now,
                reason=reason,
            ),
        },
        expected=(201,),
    )
    return _validate_publish_lease_check(
        result.value,
        config=config,
        record=record,
        state=state,
        reason=reason,
    )


def _complete_publish_lease_check(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    record: PublishLeaseRecord,
    state: str,
    provider_now: datetime,
    token: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if record.check_run_id is None:
        return _create_publish_lease_check(
            api,
            config=config,
            record=record,
            state=state,
            provider_now=provider_now,
            token=token,
            reason=reason,
        )
    result = api.request(
        f"repos/{config.repository}/check-runs/{record.check_run_id}",
        token=token,
        method="PATCH",
        payload=_publish_check_payload(
            config=config,
            record=record,
            state=state,
            provider_now=provider_now,
            reason=reason,
        ),
    )
    return _validate_publish_lease_check(
        result.value,
        config=config,
        record=record,
        state=state,
        reason=reason,
    )


class PublishLeaseController:
    def __init__(
        self,
        *,
        api: GitHubApi,
        config: BrokerConfig,
        spool: DurableSpool,
        token: str,
    ) -> None:
        self.api = api
        self.config = config
        self.spool = spool
        self.token = token

    def _validate_live_authority(
        self,
        record: PublishLeaseRecord,
        *,
        settings_token: str,
    ) -> None:
        validate_hosted_rulesets(
            config=self.config,
            rulesets=_rulesets(self.api, config=self.config, token=settings_token),
        )
        if _main_ref(self.api, config=self.config, token=self.token) != record.release_sha:
            raise BrokerError("main differs from the production publication commit")
        _validate_publish_authority(
            self.api,
            config=self.config,
            release_sha=record.release_sha,
            token=self.token,
        )
        if _main_ref(self.api, config=self.config, token=self.token) != record.release_sha:
            raise BrokerError("main changed while validating publication authority")

    def _snapshot(
        self,
        record: PublishLeaseRecord,
        *,
        owner_id: int,
        workflow_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str, datetime | None]:
        result = self.api.request(
            f"repos/{self.config.repository}/actions/runs/{record.run_id}",
            token=self.token,
        )
        if not isinstance(result.value, dict):
            raise BrokerError("production workflow run response is malformed")
        run = result.value
        run_id, run_attempt, _started_at = _publish_run_identity(
            run,
            config=self.config,
            main_sha=record.release_sha,
            owner_id=owner_id,
            workflow_id=workflow_id,
        )
        if run_id != record.run_id or run_attempt != record.run_attempt:
            raise BrokerError("production workflow run identity changed")
        jobs = _publish_jobs(
            self.api,
            config=self.config,
            lease=record,
            token=self.token,
        )
        phase, wait_started = _publish_phase(jobs)
        return run, jobs, phase, wait_started

    def _discover_candidate(
        self,
        *,
        owner_id: int,
        provider_now: datetime,
        settings_token: str,
        workflow_id: int,
    ) -> PublishLeaseRecord | None:
        main_sha = _main_ref(self.api, config=self.config, token=self.token)
        runs = self.api.list_items(
            (
                f"repos/{self.config.repository}/actions/workflows/publish-pypi.yml/runs"
                "?event=workflow_dispatch&status=in_progress"
            ),
            key="workflow_runs",
            token=self.token,
        )
        candidates: list[PublishLeaseRecord] = []
        for run in runs:
            if run.get("status") != "in_progress":
                raise BrokerError("active production workflow inventory contains a non-active run")
            run_id, run_attempt, run_started = _publish_run_identity(
                run,
                config=self.config,
                main_sha=main_sha,
                owner_id=owner_id,
                workflow_id=workflow_id,
            )
            provisional = PublishLeaseRecord.create(
                release_sha=main_sha,
                run_attempt=run_attempt,
                run_id=run_id,
                created_at=_format_timestamp(run_started),
                expires_at=_format_timestamp(run_started + PUBLISH_REQUEST_MAX_AGE),
            )
            jobs = _publish_jobs(
                self.api,
                config=self.config,
                lease=provisional,
                token=self.token,
            )
            publish_job = _named_publish_job(jobs, PUBLISH_JOB, required=False)
            if publish_job is None or publish_job.get("status") != "in_progress":
                continue
            phase, wait_started = _publish_phase(jobs)
            if phase != "awaiting":
                continue
            if wait_started is None:
                raise BrokerError("eligible production run has no publish-lease wait start")
            if wait_started > provider_now + timedelta(seconds=self.config.max_clock_skew_seconds):
                raise BrokerError("production publish-lease wait begins in the future")
            record = PublishLeaseRecord.create(
                release_sha=main_sha,
                run_attempt=run_attempt,
                run_id=run_id,
                created_at=_format_timestamp(wait_started),
                expires_at=_format_timestamp(wait_started + PUBLISH_REQUEST_MAX_AGE),
            )
            if provider_now >= _timestamp(record.expires_at):
                continue
            candidates.append(record)
        if len(candidates) > 1:
            raise BrokerError("multiple production runs concurrently request the publication fence")
        if not candidates:
            return None
        candidate = candidates[0]

        self._validate_live_authority(candidate, settings_token=settings_token)
        _run, _jobs, phase, wait_started = self._snapshot(
            candidate,
            owner_id=owner_id,
            workflow_id=workflow_id,
        )
        if (
            phase != "awaiting"
            or wait_started is None
            or _format_timestamp(wait_started) != candidate.created_at
        ):
            raise BrokerError("production workflow changed before publish-lease reservation")
        if _main_ref(self.api, config=self.config, token=self.token) != candidate.release_sha:
            raise BrokerError("main changed before publish-lease reservation")
        if _publish_lease_refs(self.api, config=self.config, token=self.token):
            raise BrokerError("provider publish-lease ref appeared before durable reservation")
        if (
            _publish_lease_check(
                self.api,
                config=self.config,
                record=candidate,
                token=self.token,
            )
            is not None
        ):
            raise BrokerError("provider publish-lease check appeared before durable reservation")
        return candidate

    def _create_ref(self, record: PublishLeaseRecord) -> None:
        result = self.api.request(
            f"repos/{self.config.repository}/git/refs",
            token=self.token,
            method="POST",
            payload={"ref": record.lease_ref, "sha": record.release_sha},
            expected=(201,),
        )
        value = result.value
        provider_object = value.get("object") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or value.get("ref") != record.lease_ref
            or not isinstance(provider_object, dict)
            or provider_object.get("type") != "commit"
            or provider_object.get("sha") != record.release_sha
        ):
            raise ProviderTransportError("publish-lease ref creation response is ambiguous")

    def _activate(
        self, record: PublishLeaseRecord, *, provider_now: datetime
    ) -> PublishLeaseRecord:
        refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        if refs and refs != {record.lease_ref: record.release_sha}:
            raise BrokerError("provider publish-lease ref conflicts with durable reservation")
        check = _publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            token=self.token,
        )
        if not refs:
            if check is not None:
                raise BrokerError("publish-lease acknowledgment exists without its durable ref")
            self._create_ref(record)
            refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
            if refs != {record.lease_ref: record.release_sha}:
                raise BrokerError("publish-lease ref creation was not read back exactly")
        if check is None:
            check = _create_publish_lease_check(
                self.api,
                config=self.config,
                record=record,
                state="active",
                provider_now=provider_now,
                token=self.token,
            )
        else:
            _validate_publish_lease_check(
                check,
                config=self.config,
                record=record,
                state="active",
            )
        check_id = _require_positive_int(check.get("id"), "publish-lease check-run ID")
        active = self.spool.transition_publish_lease(
            external_id=record.external_id,
            status="active",
            updated_at=_format_timestamp(provider_now),
            check_run_id=check_id,
        )
        final_refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        final_check = _publish_lease_check(
            self.api,
            config=self.config,
            record=active,
            token=self.token,
        )
        if final_refs != {active.lease_ref: active.release_sha}:
            raise BrokerError("publish-lease ref changed across acknowledgment")
        _validate_publish_lease_check(
            final_check,
            config=self.config,
            record=active,
            state="active",
        )
        return active

    def _abandon(
        self, record: PublishLeaseRecord, *, provider_now: datetime, reason: str
    ) -> PublishLeaseRecord:
        if _publish_lease_refs(self.api, config=self.config, token=self.token):
            raise BrokerError("cannot abandon a publish lease after provider mutation")
        if (
            _publish_lease_check(
                self.api,
                config=self.config,
                record=record,
                token=self.token,
            )
            is not None
        ):
            raise BrokerError("cannot abandon a publish lease with an App acknowledgment")
        return self.spool.transition_publish_lease(
            external_id=record.external_id,
            status="abandoned",
            updated_at=_format_timestamp(provider_now),
            reason=reason,
        )

    def _quarantine(
        self, record: PublishLeaseRecord, *, provider_now: datetime, reason: str
    ) -> PublishLeaseRecord:
        if record.status == "quarantined":
            assert record.reason is not None
            reason = record.reason
        check = _publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            token=self.token,
        )
        check_id: int | None = None
        if check is not None:
            check_id = _require_positive_int(check.get("id"), "publish-lease check-run ID")
            if check.get("status") == "in_progress":
                _validate_publish_lease_check(
                    check,
                    config=self.config,
                    record=record,
                    state="active",
                )
            elif not (check.get("status") == "completed" and check.get("conclusion") == "failure"):
                raise BrokerError("publish-lease acknowledgment cannot be quarantined safely")
        quarantined = self.spool.transition_publish_lease(
            external_id=record.external_id,
            status="quarantined",
            updated_at=_format_timestamp(provider_now),
            check_run_id=check_id,
            reason=reason,
        )
        if check is None or check.get("status") == "in_progress":
            check = _complete_publish_lease_check(
                self.api,
                config=self.config,
                record=quarantined,
                state="quarantined",
                provider_now=provider_now,
                token=self.token,
                reason=reason,
            )
            check_id = _require_positive_int(check.get("id"), "publish-lease check-run ID")
            quarantined = self.spool.transition_publish_lease(
                external_id=quarantined.external_id,
                status="quarantined",
                updated_at=_format_timestamp(provider_now),
                check_run_id=check_id,
                reason=reason,
            )
        _validate_publish_lease_check(
            check,
            config=self.config,
            record=quarantined,
            state="quarantined",
            reason=reason,
        )
        return quarantined

    def _release(
        self,
        record: PublishLeaseRecord,
        *,
        owner_id: int,
        provider_now: datetime,
        settings_token: str,
        workflow_id: int,
    ) -> PublishLeaseRecord:
        refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        check = _publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            token=self.token,
        )
        if (
            record.status == "releasing"
            and check is not None
            and check.get("status") == "completed"
        ):
            _validate_publish_lease_check(
                check,
                config=self.config,
                record=record,
                state="released",
            )
            if refs:
                raise BrokerError("successful publish-lease check still has a provider ref")
            return self.spool.transition_publish_lease(
                external_id=record.external_id,
                status="released",
                updated_at=_format_timestamp(provider_now),
                check_run_id=record.check_run_id,
            )

        if record.status in {"active", "releasing"}:
            try:
                self._validate_live_authority(record, settings_token=settings_token)
                _run, _jobs, phase, _wait_started = self._snapshot(
                    record,
                    owner_id=owner_id,
                    workflow_id=workflow_id,
                )
            except ProviderTransportError:
                raise
            except BrokerError as exc:
                return self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason=f"publication reconciliation authority is invalid: {exc}",
                )
            if phase != "reconciling":
                return self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason="production workflow left reconciliation before lease release",
                )
            if _main_ref(self.api, config=self.config, token=self.token) != record.release_sha:
                return self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason="main changed before successful publication reconciliation",
                )
            if record.status != "releasing":
                record = self.spool.transition_publish_lease(
                    external_id=record.external_id,
                    status="releasing",
                    updated_at=_format_timestamp(provider_now),
                    check_run_id=record.check_run_id,
                )

        refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        if refs and refs != {record.lease_ref: record.release_sha}:
            raise BrokerError("publish-lease ref changed before release")
        check = _publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            token=self.token,
        )
        if check is None:
            raise BrokerError("publish-lease acknowledgment disappeared before release")
        if check.get("status") == "completed":
            _validate_publish_lease_check(
                check,
                config=self.config,
                record=record,
                state="released",
            )
            if refs:
                raise BrokerError("successful publish-lease check still has a provider ref")
            return self.spool.transition_publish_lease(
                external_id=record.external_id,
                status="released",
                updated_at=_format_timestamp(provider_now),
                check_run_id=record.check_run_id,
            )
        _validate_publish_lease_check(
            check,
            config=self.config,
            record=record,
            state="active",
        )
        if refs:
            encoded_ref = urllib.parse.quote(record.lease_ref.removeprefix("refs/"), safe="/")
            self.api.request(
                f"repos/{self.config.repository}/git/refs/{encoded_ref}",
                token=self.token,
                method="DELETE",
                expected=(204,),
            )
        if _publish_lease_refs(self.api, config=self.config, token=self.token):
            raise BrokerError("publish-lease ref deletion was not read back exactly")
        check = _complete_publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            state="released",
            provider_now=provider_now,
            token=self.token,
        )
        check_id = _require_positive_int(check.get("id"), "publish-lease check-run ID")
        if _publish_lease_refs(self.api, config=self.config, token=self.token):
            raise BrokerError("publish-lease ref reappeared after terminal acknowledgment")
        return self.spool.transition_publish_lease(
            external_id=record.external_id,
            status="released",
            updated_at=_format_timestamp(provider_now),
            check_run_id=check_id,
        )

    def _restore_ref(
        self,
        *,
        owner_id: int,
        provider_now: datetime,
        ref: str,
        release_sha: str,
        workflow_id: int,
    ) -> PublishLeaseRecord:
        match = re.fullmatch(
            rf"{re.escape(PUBLISH_LEASE_REF_PREFIX)}([1-9][0-9]*)-([1-9][0-9]*)",
            ref,
        )
        if match is None:
            raise BrokerError("provider publish-lease ref cannot be restored")
        run_id, run_attempt = (int(match.group(1)), int(match.group(2)))
        provisional = PublishLeaseRecord.create(
            release_sha=release_sha,
            run_attempt=run_attempt,
            run_id=run_id,
            created_at=_format_timestamp(provider_now),
            expires_at=_format_timestamp(provider_now + PUBLISH_REQUEST_MAX_AGE),
        )
        _run, _jobs, _phase, wait_started = self._snapshot(
            provisional,
            owner_id=owner_id,
            workflow_id=workflow_id,
        )
        if wait_started is None:
            raise BrokerError("provider publish-lease ref has no workflow wait identity")
        if wait_started > provider_now + timedelta(seconds=self.config.max_clock_skew_seconds):
            raise BrokerError("provider publish-lease ref has a future workflow wait identity")
        restored = PublishLeaseRecord.create(
            release_sha=release_sha,
            run_attempt=run_attempt,
            run_id=run_id,
            created_at=_format_timestamp(wait_started),
            expires_at=_format_timestamp(wait_started + PUBLISH_REQUEST_MAX_AGE),
        )
        return self.spool.begin_publish_lease(restored)

    def reconcile(self, *, provider_now: datetime, settings_token: str) -> bool:
        owner_id = _validate_runtime_repository(
            self.api,
            config=self.config,
            token=self.token,
        )
        workflow_id = _validate_publish_workflow(
            self.api,
            config=self.config,
            token=self.token,
        )
        refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        record = self.spool.publish_lease_fence()
        if record is None and refs:
            ref, release_sha = next(iter(refs.items()))
            record = self._restore_ref(
                owner_id=owner_id,
                provider_now=provider_now,
                ref=ref,
                release_sha=release_sha,
                workflow_id=workflow_id,
            )
        if record is None:
            candidate = self._discover_candidate(
                owner_id=owner_id,
                provider_now=provider_now,
                settings_token=settings_token,
                workflow_id=workflow_id,
            )
            if candidate is None:
                return False
            record = self.spool.begin_publish_lease(candidate)

        if refs and refs != {record.lease_ref: record.release_sha}:
            raise BrokerError("provider and durable publish-lease identities differ")
        if record.status == "quarantined":
            self._quarantine(
                record,
                provider_now=provider_now,
                reason=record.reason or "durable publication quarantine",
            )
            return True
        if record.status == "releasing":
            try:
                released = self._release(
                    record,
                    owner_id=owner_id,
                    provider_now=provider_now,
                    settings_token=settings_token,
                    workflow_id=workflow_id,
                )
            except ProviderTransportError:
                raise
            except BrokerError as exc:
                self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason=f"publication reconciliation became invalid: {exc}",
                )
                return True
            return released.status != "released"

        main_sha = _main_ref(self.api, config=self.config, token=self.token)
        authority_validated = False
        try:
            _run, _jobs, phase, _wait_started = self._snapshot(
                record,
                owner_id=owner_id,
                workflow_id=workflow_id,
            )
        except ProviderTransportError:
            raise
        except BrokerError as exc:
            if (
                record.status == "creating"
                and not refs
                and _publish_lease_check(
                    self.api,
                    config=self.config,
                    record=record,
                    token=self.token,
                )
                is None
            ):
                self._abandon(record, provider_now=provider_now, reason=str(exc))
                return False
            self._quarantine(record, provider_now=provider_now, reason=str(exc))
            return True
        if record.status == "creating":
            check = _publish_lease_check(
                self.api,
                config=self.config,
                record=record,
                token=self.token,
            )
            resumable = phase in {"awaiting", "publishing", "reconciling", "verifying"}
            objects_exact = refs == {record.lease_ref: record.release_sha} and check is not None
            if (
                resumable
                and main_sha == record.release_sha
                and (phase == "awaiting" or objects_exact)
            ):
                if provider_now >= _timestamp(record.expires_at):
                    if not refs and check is None:
                        self._abandon(
                            record,
                            provider_now=provider_now,
                            reason="publish-lease request expired before provider acknowledgment",
                        )
                        return False
                    self._quarantine(
                        record,
                        provider_now=provider_now,
                        reason="publish-lease request expired during provider acknowledgment",
                    )
                    return True
                try:
                    self._validate_live_authority(record, settings_token=settings_token)
                except ProviderTransportError:
                    raise
                except BrokerError as exc:
                    if refs or check is not None:
                        self._quarantine(record, provider_now=provider_now, reason=str(exc))
                        return True
                    self._abandon(record, provider_now=provider_now, reason=str(exc))
                    return False
                authority_validated = True
                record = self._activate(record, provider_now=provider_now)
                refs = {record.lease_ref: record.release_sha}
            elif refs or check is not None:
                self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason="production workflow changed during publish-lease acknowledgment",
                )
                return True
            else:
                self._abandon(
                    record,
                    provider_now=provider_now,
                    reason="production workflow left the lease wait before acknowledgment",
                )
                return False

        if main_sha != record.release_sha:
            self._quarantine(
                record,
                provider_now=provider_now,
                reason="main changed while the production publication fence was active",
            )
            return True
        if provider_now >= _timestamp(record.expires_at):
            self._quarantine(
                record,
                provider_now=provider_now,
                reason="production publication lease expired before reconciliation",
            )
            return True
        if not authority_validated:
            try:
                self._validate_live_authority(record, settings_token=settings_token)
            except ProviderTransportError:
                raise
            except BrokerError as exc:
                self._quarantine(record, provider_now=provider_now, reason=str(exc))
                return True
        refs = _publish_lease_refs(self.api, config=self.config, token=self.token)
        check = _publish_lease_check(
            self.api,
            config=self.config,
            record=record,
            token=self.token,
        )
        if refs != {record.lease_ref: record.release_sha} or check is None:
            self._quarantine(
                record,
                provider_now=provider_now,
                reason="production publication fence changed before reconciliation",
            )
            return True
        _validate_publish_lease_check(
            check,
            config=self.config,
            record=record,
            state="active",
        )
        if phase == "reconciling":
            try:
                released = self._release(
                    record,
                    owner_id=owner_id,
                    provider_now=provider_now,
                    settings_token=settings_token,
                    workflow_id=workflow_id,
                )
            except ProviderTransportError:
                raise
            except BrokerError as exc:
                self._quarantine(
                    record,
                    provider_now=provider_now,
                    reason=f"publication reconciliation became invalid: {exc}",
                )
                return True
            return released.status != "released"
        if phase in {"awaiting", "publishing", "verifying"}:
            return True
        self._quarantine(
            record,
            provider_now=provider_now,
            reason=f"production workflow entered terminal phase {phase!r} before reconciliation",
        )
        return True


def validate_clock(
    *, local_now: datetime, provider_now: datetime, max_clock_skew_seconds: int
) -> None:
    skew = abs((provider_now - local_now).total_seconds())
    if skew > max_clock_skew_seconds:
        raise BrokerError(f"provider clock skew {skew:.3f}s exceeds the configured boundary")


class HealthReconciler:
    """Observe exact Actions attempts and append current-main health through branch CAS."""

    def __init__(
        self,
        *,
        api: GitHubApi,
        config: BrokerConfig,
        spool: DurableSpool,
        state_branch: StateBranch,
        token: str,
    ) -> None:
        self.api = api
        self.config = config
        self.spool = spool
        self.state_branch = state_branch
        self.token = token

    def _workflow_runs(self, head_sha: str) -> list[dict[str, Any]]:
        return self.api.list_items(
            f"repos/{self.config.repository}/actions/runs?head_sha={head_sha}",
            key="workflow_runs",
            token=self.token,
        )

    def _jobs(self, run: observe_main_health.SelectedRun) -> list[dict[str, Any]]:
        return self.api.list_items(
            (
                f"repos/{self.config.repository}/actions/runs/{run['id']}"
                f"/attempts/{run['run_attempt']}/jobs"
            ),
            key="jobs",
            token=self.token,
        )

    def _current_ci(self, main_sha: str) -> dict[str, Any] | None:
        runs = self.api.list_items(
            (
                f"repos/{self.config.repository}/actions/workflows/ci.yml/runs"
                "?branch=main&event=push"
            ),
            key="workflow_runs",
            token=self.token,
        )
        expected_scope = {
            "event": "push",
            "head_branch": "main",
            "head_sha": main_sha,
        }
        exact = [
            run
            for run in runs
            if all(run.get(field) == expected for field, expected in expected_scope.items())
        ]
        if not exact:
            return None
        governed_ids = {
            run_id
            for run in exact
            if isinstance((run_id := run.get("id")), int)
            and not isinstance(run_id, bool)
            and run_id > 0
        }
        governed = [
            run
            for run in runs
            if run in exact
            or (
                isinstance((run_id := run.get("id")), int)
                and not isinstance(run_id, bool)
                and run_id in governed_ids
            )
        ]
        for run in governed:
            for field, expected in expected_scope.items():
                if run.get(field) != expected:
                    raise BrokerError(
                        f"current CI provider run field {field!r} does not bind protected main"
                    )
        try:
            return observe_main_health.select_latest_provider_run(governed, workflow="CI")
        except observe_main_health.ObservationError as exc:
            raise BrokerError(f"current CI run chronology is malformed: {exc}") from exc

    def _observe_main(
        self, provider_now: datetime
    ) -> tuple[str, str, int, observe_main_health.Observation]:
        main_sha = _main_ref(self.api, config=self.config, token=self.token)
        ci_run = self._current_ci(main_sha)
        if ci_run is None:
            raise BrokerError("current main has no exact CI run")
        run_id = _require_positive_int(ci_run.get("id"), "CI run ID")
        run_attempt = _require_positive_int(ci_run.get("run_attempt"), "CI run attempt")
        run_status = ci_run.get("status")
        if not isinstance(run_status, str):
            raise BrokerError("current main CI status is malformed")
        if run_status != "completed":
            raise BrokerError("current main latest CI attempt is still active")
        run_conclusion = ci_run.get("conclusion")
        if not isinstance(run_conclusion, str):
            raise BrokerError("current main CI conclusion is malformed")
        workflow_runs = self._workflow_runs(main_sha)
        selection = observe_main_health.select_runs(
            workflow_runs=workflow_runs,
            run_id=run_id,
            run_attempt=run_attempt,
            run_conclusion=run_conclusion,
            sha=main_sha,
        )
        identity = _protected_main_selection_identity(selection)
        if selection["ready"]:
            jobs_by_key = {run["key"]: self._jobs(run) for run in selection["runs"]}
            observation = observe_main_health.observe_jobs(
                selection=selection,
                jobs_by_key=jobs_by_key,
                repository=self.config.repository,
            )
        else:
            created_at = ci_run.get("created_at")
            if not isinstance(created_at, str):
                raise BrokerError("current main CI creation time is malformed")
            if provider_now - _timestamp(created_at) < timedelta(minutes=15):
                raise BrokerError("current main companion workflows are still pending")
            observation = observe_main_health.invalidate_selection(selection)
        verification = observe_main_health.select_runs(
            workflow_runs=self._workflow_runs(main_sha),
            run_id=run_id,
            run_attempt=run_attempt,
            run_conclusion=run_conclusion,
            sha=main_sha,
        )
        if verification != selection:
            identity = _protected_main_selection_identity(verification)
            observation = observe_main_health.invalidate_selection(verification)
        if _main_ref(self.api, config=self.config, token=self.token) != main_sha:
            raise BrokerError("main changed during health observation")
        return main_sha, identity, run_id, observation

    def reconcile_main(self, provider_now: datetime) -> dict[str, Any]:
        main_sha, identity, run_id, observation = self._observe_main(provider_now)
        state, result_identities = self.state_branch.read_with_result_identities()
        recorded = ("protected-main", identity) in result_identities
        if recorded:
            self.spool.set_cursor("main_ci_run_id", str(run_id))
            if state.get("status") == "red":
                return state
            if observation["ready"] and observation["conclusion"] == "success":
                return state
            raise BrokerError("recorded protected-main provider evidence changed")
        recorded_at = provider_now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        summary = {
            "cadence": "protected-main",
            "conclusion": observation["conclusion"],
            "obligations": observation["obligations"],
            "recorded_at": recorded_at,
            "run_id": identity,
            "schema_version": 1,
            "sha": main_sha,
        }
        appended = self.state_branch.append(
            expected_generation=_require_positive_int(state.get("generation"), "state generation"),
            scope="main",
            summary=summary,
        )
        self.spool.set_cursor("main_ci_run_id", str(run_id))
        return appended

    @staticmethod
    def _deep_cadence(run: dict[str, Any]) -> str | None:
        title = run.get("display_title")
        if not isinstance(title, str):
            raise BrokerError("deep-health workflow title is malformed")
        if " / main-health-nightly / " in title or " / 23 3 * * 1-6 / " in title:
            return "nightly"
        if " / main-health-weekly / " in title or " / 23 3 * * 0 / " in title:
            return "weekly"
        return None

    def _observe_current_deep(
        self,
        main_sha: str,
        recorded: dict[str, set[tuple[int, int]]],
    ) -> dict[str, dict[str, Any]]:
        runs = self.api.list_items(
            (f"repos/{self.config.repository}/actions/workflows/main-health.yml/runs?branch=main"),
            key="workflow_runs",
            token=self.token,
        )
        candidates: dict[str, list[dict[str, Any]]] = {"nightly": [], "weekly": []}
        identities: set[tuple[str, int, int]] = set()
        for run in runs:
            cadence = self._deep_cadence(run)
            if cadence is None:
                continue
            run_id = _require_positive_int(run.get("id"), "current deep-health run ID")
            attempt = _require_positive_int(
                run.get("run_attempt"), "current deep-health run attempt"
            )
            if attempt > 100:
                raise BrokerError("current deep-health run attempt exceeds the governed bound")
            identity = (cadence, run_id, attempt)
            if identity in identities:
                raise BrokerError("provider repeated a deep-health run attempt")
            identities.add(identity)
            if (run_id, attempt) not in recorded[cadence]:
                raise BrokerError(f"provider exposes an unreconciled {cadence} deep-health attempt")
            if run.get("head_sha") != main_sha:
                continue
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                raise BrokerError(f"current-main {cadence} deep-health attempt is not successful")
            candidates[cadence].append(run)

        proof: dict[str, dict[str, Any]] = {}
        for cadence in ("nightly", "weekly"):
            if not candidates[cadence]:
                continue
            run = max(
                candidates[cadence],
                key=lambda item: (
                    _require_positive_int(item.get("id"), "current deep-health run ID"),
                    _require_positive_int(
                        item.get("run_attempt"), "current deep-health run attempt"
                    ),
                ),
            )
            run_id = _require_positive_int(run.get("id"), "current deep-health run ID")
            attempt = _require_positive_int(
                run.get("run_attempt"), "current deep-health run attempt"
            )
            jobs = self.api.list_items(
                (f"repos/{self.config.repository}/actions/runs/{run_id}/attempts/{attempt}/jobs"),
                key="jobs",
                token=self.token,
            )
            expected_name = f"Main health deep / {cadence}"
            exact_jobs = [job for job in jobs if job.get("name") == expected_name]
            if len(exact_jobs) != 1:
                raise BrokerError(f"current-main {cadence} deep-health job is not unique")
            job = exact_jobs[0]
            job_id = _require_positive_int(job.get("id"), f"{cadence} deep-health job ID")
            if not (
                job.get("status") == "completed"
                and job.get("conclusion") == "success"
                and job.get("run_id") == run_id
                and job.get("run_attempt") == attempt
                and job.get("head_sha") == main_sha
            ):
                raise BrokerError(f"current-main {cadence} deep-health job is not exact")
            proof[cadence] = {
                "job_id": job_id,
                "run_attempt": attempt,
                "run_id": run_id,
            }
        return proof

    def verify_current_health(self, provider_now: datetime) -> dict[str, Any]:
        main_sha, identity, _run_id, observation = self._observe_main(provider_now)
        if not observation["ready"] or observation["conclusion"] != "success":
            raise BrokerError("current protected-main aggregate is not successful")
        state, result_identities = self.state_branch.read_with_result_identities()
        deep_state, deep_identities = self.state_branch.read_with_deep_identities()
        if deep_state.get("state_commit") != state.get("state_commit") or deep_state.get(
            "generation"
        ) != state.get("generation"):
            raise BrokerError("main-health state changed during final provider verification")
        deep_before = self._observe_current_deep(main_sha, deep_identities)
        updated_at = state.get("updated_at")
        if not isinstance(updated_at, str):
            raise BrokerError("protected main state update time is malformed")
        age = (provider_now - _timestamp(updated_at)).total_seconds()
        if age < -self.config.max_clock_skew_seconds:
            raise BrokerError("protected main state update time is in the future")
        if (
            state.get("status") != "green"
            or state.get("last_good_sha") != main_sha
            or ("protected-main", identity) not in result_identities
        ):
            raise BrokerError("protected main state does not retain the current aggregate evidence")
        for cadence, value in deep_before.items():
            deep_identity = (value["run_id"], value["run_attempt"])
            if deep_identity not in deep_identities[cadence]:
                raise BrokerError(
                    f"protected main state does not retain current {cadence} evidence"
                )

        main_sha_after, identity_after, _run_id_after, observation_after = self._observe_main(
            provider_now
        )
        deep_after = self._observe_current_deep(main_sha, deep_identities)
        if (
            main_sha_after != main_sha
            or identity_after != identity
            or observation_after != observation
            or deep_after != deep_before
        ):
            raise BrokerError("provider health evidence changed at the final merge boundary")
        state_after = self.state_branch.read()
        if (
            state_after.get("state_commit") != state.get("state_commit")
            or state_after.get("generation") != state.get("generation")
            or _main_ref(self.api, config=self.config, token=self.token) != main_sha
        ):
            raise BrokerError("main or protected health state changed after final verification")
        return state

    def reconcile_deep(self, provider_now: datetime) -> dict[str, Any]:
        main_sha = _main_ref(self.api, config=self.config, token=self.token)
        runs = self.api.list_items(
            (f"repos/{self.config.repository}/actions/workflows/main-health.yml/runs?branch=main"),
            key="workflow_runs",
            token=self.token,
        )
        state, recorded = self.state_branch.read_with_deep_identities()
        for deep_cadence in ("nightly", "weekly"):
            latest = max(recorded[deep_cadence], default=(0, 0))
            self.spool.set_cursor(f"deep_{deep_cadence}_run_id", f"{latest[0]}:{latest[1]}")

        governed: list[tuple[datetime, int, int, str, dict[str, Any]]] = []
        provider_identities: set[tuple[str, int, int]] = set()
        for run in runs:
            cadence = self._deep_cadence(run)
            if cadence is None:
                continue
            run_id = _require_positive_int(run.get("id"), "deep-health run ID")
            latest_attempt = _require_positive_int(
                run.get("run_attempt"), "deep-health run attempt"
            )
            if latest_attempt > 100:
                raise BrokerError("deep-health run attempt exceeds the governed bound")
            for run_attempt in range(1, latest_attempt + 1):
                identity = (run_id, run_attempt)
                if identity in recorded[cadence]:
                    continue
                if run_attempt == latest_attempt:
                    attempt = run
                else:
                    attempt_result = self.api.request(
                        (
                            f"repos/{self.config.repository}/actions/runs/{run_id}"
                            f"/attempts/{run_attempt}"
                        ),
                        token=self.token,
                    )
                    if not isinstance(attempt_result.value, dict):
                        raise BrokerError("deep-health attempt response is malformed")
                    attempt = attempt_result.value
                if (
                    attempt.get("id") != run_id
                    or attempt.get("run_attempt") != run_attempt
                    or self._deep_cadence(attempt) != cadence
                ):
                    raise BrokerError("deep-health attempt identity changed at the provider")
                updated_at = attempt.get("updated_at")
                if not isinstance(updated_at, str):
                    raise BrokerError("deep-health attempt update time is malformed")
                provider_identity = (cadence, run_id, run_attempt)
                if provider_identity in provider_identities:
                    raise BrokerError("provider repeated a deep-health run attempt")
                provider_identities.add(provider_identity)
                governed.append((_timestamp(updated_at), run_id, run_attempt, cadence, attempt))
                if attempt.get("head_sha") == main_sha and attempt.get("status") != "completed":
                    raise BrokerError("a current-main deep-health run is still active")

        governed.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        for _updated_at, run_id, run_attempt, cadence, run in governed:
            head_sha = _require_sha(run.get("head_sha"), "deep-health head SHA")
            if head_sha != main_sha:
                raise BrokerError("unreconciled deep-health run does not bind current main")
            jobs = self.api.list_items(
                (
                    f"repos/{self.config.repository}/actions/runs/{run_id}"
                    f"/attempts/{run_attempt}/jobs"
                ),
                key="jobs",
                token=self.token,
            )
            expected_name = f"Main health deep / {cadence}"
            exact_jobs = [job for job in jobs if job.get("name") == expected_name]
            success = (
                run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and len(exact_jobs) == 1
                and exact_jobs[0].get("status") == "completed"
                and exact_jobs[0].get("conclusion") == "success"
                and exact_jobs[0].get("run_id") == run_id
                and exact_jobs[0].get("run_attempt") == run_attempt
                and exact_jobs[0].get("head_sha") == head_sha
            )
            recorded_at = provider_now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            conclusion = "success" if success else "failure"
            summary = {
                "cadence": cadence,
                "conclusion": conclusion,
                "obligations": [{"id": expected_name, "result": conclusion}],
                "recorded_at": recorded_at,
                "run_id": f"github-actions:{run_id}:{run_attempt}",
                "schema_version": 1,
                "sha": head_sha,
            }
            state = self.state_branch.append(
                expected_generation=_require_positive_int(
                    state.get("generation"), "state generation"
                ),
                scope=cadence,
                summary=summary,
            )
            recorded[cadence].add((run_id, run_attempt))
            latest = max(recorded[cadence])
            self.spool.set_cursor(f"deep_{cadence}_run_id", f"{latest[0]}:{latest[1]}")
        return state


def _provider_list(
    api: GitHubApi,
    path: str,
    *,
    token: str,
) -> list[dict[str, Any]]:
    separator = "&" if "?" in path else "?"
    items: list[dict[str, Any]] = []
    for page in range(1, 101):
        result = api.request(f"{path}{separator}per_page=100&page={page}", token=token)
        if not isinstance(result.value, list) or not all(
            isinstance(item, dict) for item in result.value
        ):
            raise BrokerError(f"GitHub list response for {path} is malformed")
        items.extend(result.value)
        if len(result.value) < 100:
            return items
    raise BrokerError(f"GitHub list response for {path} exceeded 100 pages")


def _provider_manifest(
    api: GitHubApi, *, config: BrokerConfig, head_sha: str, token: str
) -> dict[str, Any]:
    encoded_ref = urllib.parse.quote(head_sha, safe="")
    result = api.request(
        (
            f"repos/{config.repository}/contents/"
            f"docs/status/main-health-owner-emergency.json?ref={encoded_ref}"
        ),
        token=token,
    )
    value = result.value
    if not isinstance(value, dict):
        raise BrokerError("owner-emergency manifest response is malformed")
    content = value.get("content")
    if (
        value.get("type") != "file"
        or value.get("path") != "docs/status/main-health-owner-emergency.json"
        or value.get("encoding") != "base64"
        or not isinstance(content, str)
        or not isinstance(value.get("size"), int)
        or value["size"] < 0
        or not isinstance(value.get("sha"), str)
        or SHA_RE.fullmatch(value["sha"]) is None
    ):
        raise BrokerError("owner-emergency manifest response is not provider-bound")
    try:
        decoded = base64.b64decode(content, validate=False)
        manifest = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("owner-emergency manifest content is invalid") from exc
    if len(decoded) != value["size"] or not isinstance(manifest, dict):
        raise BrokerError("owner-emergency manifest size or shape is invalid")
    return manifest


def _provider_collaboration_snapshot(
    api: GitHubApi, *, config: BrokerConfig, token: str
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    snapshots: list[
        tuple[
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, str]],
            list[dict[str, str]],
        ]
    ] = []
    for _ in range(2):
        collaborators = _provider_list(
            api,
            f"repos/{config.repository}/collaborators?affiliation=all",
            token=token,
        )
        invitations = _provider_list(
            api,
            f"repos/{config.repository}/invitations",
            token=token,
        )
        try:
            normalized = stop_the_line._github_collaboration_inventory(collaborators, invitations)
        except stop_the_line.HealthError as exc:
            raise BrokerError(f"collaboration inventory validation failed: {exc}") from exc
        snapshots.append((collaborators, invitations, *normalized))
    if snapshots[0][2:] != snapshots[1][2:]:
        raise BrokerError("collaboration inventory changed during provider admission")
    return snapshots[1]


def _provider_changed_paths(
    api: GitHubApi, *, config: BrokerConfig, pull: dict[str, Any], token: str
) -> tuple[list[dict[str, Any]], list[str]]:
    number = _require_positive_int(pull.get("number"), "changed-path pull request number")
    files = _provider_list(
        api,
        f"repos/{config.repository}/pulls/{number}/files",
        token=token,
    )
    try:
        paths = stop_the_line._github_changed_paths(pull, files)
    except stop_the_line.HealthError as exc:
        raise BrokerError(f"changed-path inventory validation failed: {exc}") from exc
    return files, paths


def _owner_provider_context(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    provider_now: datetime,
    pull: dict[str, Any],
    repair: bool,
    settings_token: str,
    state: dict[str, Any],
    state_branch: StateBranch,
    token: str,
) -> dict[str, Any]:
    files, changed_paths = _provider_changed_paths(api, config=config, pull=pull, token=token)
    raw_collaborators, raw_invitations, collaborators, invitations = (
        _provider_collaboration_snapshot(api, config=config, token=settings_token)
    )
    owner_entries = [
        item for item in collaborators if item["login"].casefold() == REPOSITORY_OWNER.casefold()
    ]
    if len(owner_entries) != 1 or owner_entries[0]["permission"] != "admin":
        raise BrokerError("collaboration inventory does not identify one admin repository owner")
    owner_id = _require_positive_decimal(owner_entries[0]["id"], "repository owner ID")
    ruleset_digests = validate_hosted_rulesets(
        config=config,
        rulesets=_rulesets(api, config=config, token=settings_token),
    )
    context: dict[str, Any] = {
        "changed_paths_digest": digest(changed_paths),
        "collaboration_digest": digest(
            {"collaborators": collaborators, "pending_invitations": invitations}
        ),
        "collaborators": collaborators,
        "owner_id": owner_id,
        "owner_login": owner_entries[0]["login"],
        "owner_permission": "admin",
        "pending_invitations": invitations,
        "ruleset_digests": dict(sorted(ruleset_digests.items(), key=lambda item: int(item[0]))),
        "state_commit": _require_sha(state.get("state_commit"), "owner request state commit"),
    }
    if repair:
        head = pull.get("head")
        if not isinstance(head, dict):
            raise BrokerError("owner-emergency pull request head is malformed")
        head_sha = _require_sha(head.get("sha"), "owner-emergency head SHA")
        manifest = _provider_manifest(api, config=config, head_sha=head_sha, token=token)
        candidate = state_branch.validate_owner_emergency_candidate(
            checked_at=provider_now.isoformat().replace("+00:00", "Z"),
            collaborators=raw_collaborators,
            expected_head_sha=head_sha,
            files=files,
            invitations=raw_invitations,
            manifest=manifest,
            pull=pull,
        )
        if (
            candidate.get("changed_paths") != changed_paths
            or candidate.get("collaborators") != collaborators
            or candidate.get("pending_invitations") != invitations
        ):
            raise BrokerError("owner-emergency candidate changed during normalization")
        policy_amendment = manifest.get("policy_amendment")
        if not isinstance(policy_amendment, dict):
            raise BrokerError("owner-emergency policy amendment is malformed")
        context.update(
            {
                "manifest_expires_at": manifest["expires_at"],
                "manifest_digest": digest(manifest),
                "policy_amendment_digest": digest(policy_amendment),
            }
        )
    _validate_owner_context(context, repair=repair)
    return context


def _owner_repair_evidence_context(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    pull: dict[str, Any],
    settings_token: str,
    token: str,
) -> dict[str, Any]:
    files, changed_paths = _provider_changed_paths(api, config=config, pull=pull, token=token)
    raw_collaborators, raw_invitations, collaborators, invitations = (
        _provider_collaboration_snapshot(api, config=config, token=settings_token)
    )
    owner_entries = [
        item for item in collaborators if item["login"].casefold() == REPOSITORY_OWNER.casefold()
    ]
    if len(owner_entries) != 1 or owner_entries[0]["permission"] != "admin":
        raise BrokerError("repair evidence does not identify one admin repository owner")
    head = pull.get("head")
    if not isinstance(head, dict):
        raise BrokerError("merged owner-repair head is malformed")
    head_sha = _require_sha(head.get("sha"), "merged owner-repair head SHA")
    manifest = _provider_manifest(api, config=config, head_sha=head_sha, token=token)
    ruleset_digests = validate_hosted_rulesets(
        config=config,
        rulesets=_rulesets(api, config=config, token=settings_token),
    )
    return {
        "changed_paths": changed_paths,
        "collaborators": collaborators,
        "files": files,
        "manifest": manifest,
        "owner_id": _require_positive_decimal(owner_entries[0]["id"], "repository owner ID"),
        "owner_login": owner_entries[0]["login"],
        "owner_permission": "admin",
        "pending_invitations": invitations,
        "raw_collaborators": raw_collaborators,
        "raw_invitations": raw_invitations,
        "ruleset_digests": dict(sorted(ruleset_digests.items(), key=lambda item: int(item[0]))),
    }


def _pull_snapshot(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    number: int,
    token: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    pull_result = api.request(
        f"repos/{config.repository}/pulls/{number}",
        token=token,
    )
    if not isinstance(pull_result.value, dict):
        raise BrokerError("pull request response is malformed")
    reviews = _provider_list(
        api,
        f"repos/{config.repository}/pulls/{number}/reviews",
        token=token,
    )
    commits = _provider_list(
        api,
        f"repos/{config.repository}/pulls/{number}/commits",
        token=token,
    )
    reported_commit_count = _require_positive_int(
        pull_result.value.get("commits"), "pull request commit count"
    )
    if reported_commit_count > MAX_PULL_COMMITS:
        raise BrokerError("pull request exceeds the complete provider commit-inventory bound")
    commit_shas = [_require_sha(commit.get("sha"), "pull request commit SHA") for commit in commits]
    head = pull_result.value.get("head")
    if (
        len(commits) != reported_commit_count
        or len(set(commit_shas)) != reported_commit_count
        or not isinstance(head, dict)
        or commit_shas[-1] != _require_sha(head.get("sha"), "pull request head SHA")
    ):
        raise BrokerError("pull request commit inventory is incomplete or inconsistent")
    return pull_result.value, reviews, commits


def _provider_review_permissions(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    reviews: list[dict[str, Any]],
    token: str,
) -> dict[str, str]:
    logins: set[str] = set()
    for review in reviews:
        if review.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        _actor_id, login = _review_actor(review)
        logins.add(login)
    permissions: dict[str, str] = {}
    for login in sorted(logins):
        encoded = urllib.parse.quote(login, safe="")
        try:
            result = api.request(
                f"repos/{config.repository}/collaborators/{encoded}/permission",
                token=token,
            )
        except ProviderError as exc:
            if exc.status == 404:
                permissions[login] = "none"
                continue
            raise
        if not isinstance(result.value, dict):
            raise BrokerError("reviewer permission response is malformed")
        permission = result.value.get("permission")
        if permission not in {"admin", "none", "read", "write"}:
            raise BrokerError("reviewer permission response is not canonical")
        permissions[login] = permission
    return permissions


def _provider_review_snapshot(reviews: list[dict[str, Any]]) -> dict[int, str]:
    snapshot: dict[int, str] = {}
    for review in reviews:
        review_id = _require_positive_int(review.get("id"), "provider review ID")
        if review_id in snapshot:
            raise BrokerError("provider review inventory repeats an ID")
        snapshot[review_id] = digest(review)
    return snapshot


def _validate_state_for_admission(
    *,
    admission: dict[str, Any],
    config: BrokerConfig,
    provider_now: datetime,
    state: dict[str, Any],
) -> None:
    if (
        state.get("status") != "green"
        or state.get("last_good_sha") != admission["base_sha"]
        or state.get("generation") != admission["health_generation"]
    ):
        raise BrokerError("merge request does not bind current green main-health state")
    updated_at = state.get("updated_at")
    if not isinstance(updated_at, str):
        raise BrokerError("main-health state update time is malformed")
    age = (provider_now - _timestamp(updated_at)).total_seconds()
    if age < -config.max_clock_skew_seconds:
        raise BrokerError("merge request main-health state update time is in the future")


def _merged_repair_binding(
    *,
    commits: list[dict[str, Any]],
    now: datetime,
    pull: dict[str, Any],
    repository: str,
    reviewer_permissions: dict[str, str],
    reviews: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    pull_number = _require_positive_int(pull.get("number"), "merged repair pull request number")
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not isinstance(base, dict) or not isinstance(head, dict) or not isinstance(author, dict):
        raise BrokerError("merged repair pull identity is malformed")
    head_repository = head.get("repo")
    if (
        pull.get("state") != "closed"
        or pull.get("merged") is not True
        or base.get("ref") != "main"
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
    ):
        raise BrokerError("merged repair pull is not an exact same-repository main repair")
    base_sha = _require_sha(base.get("sha"), "merged repair base SHA")
    head_sha = _require_sha(head.get("sha"), "merged repair head SHA")
    author_id = _require_positive_int(author.get("id"), "merged repair author ID")
    author_login = author.get("login")
    if not isinstance(author_login, str) or not author_login:
        raise BrokerError("merged repair author login is malformed")
    merged_at_raw = pull.get("merged_at")
    if not isinstance(merged_at_raw, str):
        raise BrokerError("merged repair time is malformed")
    merged_at = _timestamp(merged_at_raw)

    state_generation = _require_positive_int(state.get("generation"), "state generation")
    if state.get("status") != "red" or not isinstance(state.get("incident_digest"), str):
        raise BrokerError("merged repair requires one open red incident")
    requests: list[tuple[int, datetime, dict[str, Any], int, str]] = []
    for review in reviews:
        body = review.get("body")
        if not isinstance(body, str) or not body.startswith(REPAIR_REQUEST_MARKER):
            continue
        if review.get("state") != "COMMENTED":
            raise BrokerError("merged repair request is no longer COMMENTED")
        requester_id, requester_login = _review_actor(review)
        request = parse_repair_request(body, reviewer_id=requester_id)
        review_id = _require_positive_int(review.get("id"), "merged repair request review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("merged repair request time is malformed")
        submitted_at = _timestamp(submitted_raw)
        expires_at = _timestamp(request["expires_at"])
        if (
            request["repository"] != repository
            or request["pull_request"] != pull_number
            or request["base_sha"] != base_sha
            or request["head_sha"] != head_sha
            or review.get("commit_id") != head_sha
            or request["incident_digest"] != state.get("incident_digest")
            or request["state_generation"] > state_generation
            or expires_at <= submitted_at
            or expires_at - submitted_at > timedelta(minutes=10)
            or merged_at < submitted_at
            or merged_at >= expires_at
        ):
            raise BrokerError("merged repair request is not provider- and incident-bound")
        requests.append((review_id, submitted_at, request, requester_id, requester_login))
    if not requests:
        raise BrokerError("merged repair has no retained request review")
    request_review_id, submitted_at, request, requester_id, requester_login = max(
        requests, key=lambda item: item[0]
    )
    marker = (
        f"Main-health repair authorization: {request['issue']}\n"
        f"Incident: {request['incident_digest']}"
    )
    commit_ids, commit_logins = _commit_actor_ids(commits)
    disallowed_ids = {author_id, requester_id, *commit_ids}
    disallowed_logins = {author_login.casefold(), requester_login, *commit_logins}
    latest_decisive: dict[int, tuple[int, dict[str, Any], datetime, str]] = {}
    for review in reviews:
        review_state = review.get("state")
        if review_state not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        reviewer_id, reviewer_login = _review_actor(review)
        review_id = _require_positive_int(review.get("id"), "merged repair decisive review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("merged repair decisive review time is malformed")
        review_time = _timestamp(submitted_raw)
        if review_time <= submitted_at:
            continue
        previous = latest_decisive.get(reviewer_id)
        if previous is None or review_id > previous[0]:
            latest_decisive[reviewer_id] = (review_id, review, review_time, reviewer_login)
    approvals: list[tuple[int, datetime]] = []
    for reviewer_id, (review_id, review, approved_at, reviewer_login) in latest_decisive.items():
        permission = reviewer_permissions.get(reviewer_login)
        if (
            review.get("state") == "CHANGES_REQUESTED"
            and permission in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS
        ):
            raise BrokerError("merged repair has current requested changes")
        if (
            review.get("state") == "APPROVED"
            and (review.get("body") or "").strip() == marker
            and review.get("commit_id") == head_sha
            and approved_at <= merged_at
            and reviewer_id not in disallowed_ids
            and reviewer_login not in disallowed_logins
            and permission in stop_the_line.AUTHORIZED_REVIEWER_PERMISSIONS
        ):
            approvals.append((review_id, approved_at))
    if not approvals:
        raise BrokerError("merged repair has no exact retained independent approval")
    approval_review_id, _approved_at = max(approvals, key=lambda item: item[0])
    if now < merged_at:
        raise BrokerError("provider time predates the merged repair")
    return {
        "approval_review_id": approval_review_id,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "incident_digest": request["incident_digest"],
        "issue": request["issue"],
        "pull_request": pull_number,
        "request": request,
        "request_digest": digest(request),
        "request_review_id": request_review_id,
    }


def _merged_owner_repair_binding(
    *,
    commits: list[dict[str, Any]],
    context: dict[str, Any],
    now: datetime,
    pull: dict[str, Any],
    repository: str,
    reviews: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    _commit_actor_ids(commits)
    pull_number = _require_positive_int(
        pull.get("number"), "merged owner-repair pull request number"
    )
    base = pull.get("base")
    head = pull.get("head")
    author = pull.get("user")
    if not isinstance(base, dict) or not isinstance(head, dict) or not isinstance(author, dict):
        raise BrokerError("merged owner-repair pull identity is malformed")
    head_repository = head.get("repo")
    base_sha = _require_sha(base.get("sha"), "merged owner-repair base SHA")
    head_sha = _require_sha(head.get("sha"), "merged owner-repair head SHA")
    author_id = _require_positive_int(author.get("id"), "merged owner-repair author ID")
    author_login = author.get("login")
    merged_at_raw = pull.get("merged_at")
    if (
        pull.get("state") != "closed"
        or pull.get("merged") is not True
        or base.get("ref") != "main"
        or not isinstance(head_repository, dict)
        or head_repository.get("full_name") != repository
        or not isinstance(author_login, str)
        or author_login.casefold() != str(context.get("owner_login", "")).casefold()
        or author_id != context.get("owner_id")
        or not isinstance(merged_at_raw, str)
    ):
        raise BrokerError("merged owner repair is not an exact owner-authored main repair")
    merged_at = _timestamp(merged_at_raw)
    state_generation = _require_positive_int(state.get("generation"), "state generation")
    if state.get("status") != "red" or not isinstance(state.get("incident_digest"), str):
        raise BrokerError("merged owner repair requires one open red incident")
    requests: list[tuple[int, datetime, dict[str, Any], dict[str, Any]]] = []
    for review in reviews:
        body = review.get("body")
        if not isinstance(body, str) or not body.startswith(OWNER_REPAIR_REQUEST_MARKER):
            continue
        review_head_sha = _require_sha(
            review.get("commit_id"), "merged owner request review commit SHA"
        )
        if review_head_sha != head_sha:
            continue
        if review.get("state") != "COMMENTED":
            raise BrokerError("merged owner request is no longer COMMENTED")
        requester_id, requester_login = _review_actor(review)
        request = parse_owner_repair_request(body, reviewer_id=requester_id)
        review_id = _require_positive_int(review.get("id"), "merged owner request review ID")
        submitted_raw = review.get("submitted_at")
        if not isinstance(submitted_raw, str):
            raise BrokerError("merged owner request time is malformed")
        submitted_at = _timestamp(submitted_raw)
        expires_at = _timestamp(request["expires_at"])
        manifest = context.get("manifest")
        collaborators = context.get("collaborators")
        invitations = context.get("pending_invitations")
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("expires_at"), str)
            or not isinstance(collaborators, list)
            or not isinstance(invitations, list)
        ):
            raise BrokerError("merged owner repair context is malformed")
        if (
            request["repository"] != repository
            or request["pull_request"] != pull_number
            or request["base_sha"] != base_sha
            or request["head_sha"] != head_sha
            or requester_id != author_id
            or requester_login != author_login.casefold()
            or request["incident_digest"] != state.get("incident_digest")
            or request["state_generation"] > state_generation
            or request["changed_paths_digest"] != digest(context.get("changed_paths"))
            or request["collaboration_digest"]
            != digest({"collaborators": collaborators, "pending_invitations": invitations})
            or request["manifest_digest"] != digest(manifest)
            or request["policy_amendment_digest"] != digest(manifest.get("policy_amendment"))
            or request["ruleset_digests"] != context.get("ruleset_digests")
            or expires_at <= submitted_at
            or expires_at - submitted_at > timedelta(minutes=10)
            or expires_at > _timestamp(manifest["expires_at"])
            or merged_at < submitted_at
            or merged_at >= expires_at
        ):
            raise BrokerError("merged owner repair request is not provider- and incident-bound")
        requests.append((review_id, submitted_at, request, review))
    if not requests:
        raise BrokerError("merged owner repair has no retained owner request")
    request_review_id, _submitted_at, request, review = max(requests, key=lambda item: item[0])
    if now < merged_at:
        raise BrokerError("provider time predates the merged owner repair")
    return {
        "approval_review_id": request_review_id,
        "authorization_mode": OWNER_EMERGENCY_MODE,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "incident_digest": request["incident_digest"],
        "issue": request["issue"],
        "pull_request": pull_number,
        "request": request,
        "request_digest": digest(request),
        "request_review_id": request_review_id,
        "review": review,
    }


def _capture_app_owner_repair_evidence(
    api: GitHubApi,
    *,
    config: BrokerConfig,
    number: int,
    settings_token: str,
    state: dict[str, Any],
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pull, reviews, commits = _pull_snapshot(
        api,
        config=config,
        number=number,
        token=token,
    )
    context = _owner_repair_evidence_context(
        api,
        config=config,
        pull=pull,
        settings_token=settings_token,
        token=token,
    )
    binding = _merged_owner_repair_binding(
        commits=commits,
        context=context,
        now=api.provider_now(token),
        pull=pull,
        repository=config.repository,
        reviews=reviews,
        state=state,
    )
    verify_merge_proof(
        admission=binding,
        api=api,
        config=config,
        token=token,
    )
    matching_checks = [
        check
        for check in _check_runs(
            api,
            config=config,
            head_sha=binding["head_sha"],
            token=token,
        )
        if check.get("name") == MAIN_HEALTH_CHECK
        and check.get("head_sha") == binding["head_sha"]
        and check.get("external_id") == f"mhb1:merge:{binding['request_digest']}"
        and check.get("status") == "completed"
        and check.get("conclusion") == "success"
        and isinstance(check.get("app"), dict)
        and check["app"].get("id") == config.app_id
        and check["app"].get("slug") == config.app_slug
    ]
    if len(matching_checks) != 1:
        raise BrokerError("owner-repair merge check is not unique and exact")
    merge_sha = _require_sha(pull.get("merge_commit_sha"), "owner merge commit SHA")
    head_commit_result = api.request(
        f"repos/{config.repository}/git/commits/{binding['head_sha']}",
        token=token,
    )
    merge_commit_result = api.request(
        f"repos/{config.repository}/git/commits/{merge_sha}",
        token=token,
    )
    if not isinstance(head_commit_result.value, dict) or not isinstance(
        merge_commit_result.value, dict
    ):
        raise BrokerError("owner-repair Git commit evidence is malformed")
    try:
        evidence = stop_the_line.github_app_owner_emergency_evidence(
            captured_at=api.provider_now(token)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            check_run=matching_checks[0],
            collaborators=context["raw_collaborators"],
            files=context["files"],
            head_commit=head_commit_result.value,
            incident_digest=binding["incident_digest"],
            invitations=context["raw_invitations"],
            issue=binding["issue"],
            manifest=context["manifest"],
            merge_commit=merge_commit_result.value,
            owner_permission=context["owner_permission"],
            pull=pull,
            pull_request=str(number),
            repository=config.repository,
            review=binding["review"],
            ruleset_digests=context["ruleset_digests"],
        )
    except stop_the_line.HealthError as exc:
        raise BrokerError(f"repair approval capture failed: {exc}") from exc
    return binding, evidence


def verify_merge_proof(
    *,
    admission: dict[str, Any],
    api: GitHubApi,
    config: BrokerConfig,
    token: str,
) -> dict[str, Any]:
    pull_result = api.request(
        f"repos/{config.repository}/pulls/{admission['pull_request']}",
        token=token,
    )
    if not isinstance(pull_result.value, dict):
        raise BrokerError("post-merge pull request response is malformed")
    pull = pull_result.value
    merge_sha = _require_sha(pull.get("merge_commit_sha"), "merge commit SHA")
    if pull.get("state") != "closed" or pull.get("merged") is not True:
        raise BrokerError("pull request is not provider-confirmed merged")
    if _main_ref(api, config=config, token=token) != merge_sha:
        raise BrokerError("post-merge main ref does not bind the merge commit")
    head_result = api.request(
        f"repos/{config.repository}/commits/{admission['head_sha']}",
        token=token,
    )
    merge_result = api.request(
        f"repos/{config.repository}/commits/{merge_sha}",
        token=token,
    )
    if not isinstance(head_result.value, dict) or not isinstance(merge_result.value, dict):
        raise BrokerError("post-merge commit response is malformed")
    head = head_result.value
    merge = merge_result.value
    parents = merge.get("parents")
    if not isinstance(parents, list) or len(parents) != 2:
        raise BrokerError("merge commit does not have exactly two parents")
    parent_shas = [
        _require_sha(parent.get("sha"), "merge parent SHA")
        if isinstance(parent, dict)
        else _require_sha(parent, "merge parent SHA")
        for parent in parents
    ]
    if parent_shas != [admission["base_sha"], admission["head_sha"]]:
        raise BrokerError("merge commit parents do not bind the admitted base and head")
    head_commit = head.get("commit")
    merge_commit = merge.get("commit")
    if not isinstance(head_commit, dict) or not isinstance(merge_commit, dict):
        raise BrokerError("post-merge commit metadata is malformed")
    head_tree = head_commit.get("tree")
    merge_tree = merge_commit.get("tree")
    if not isinstance(head_tree, dict) or not isinstance(merge_tree, dict):
        raise BrokerError("post-merge tree metadata is malformed")
    head_tree_sha = _require_sha(head_tree.get("sha"), "head tree SHA")
    merge_tree_sha = _require_sha(merge_tree.get("sha"), "merge tree SHA")
    if head_tree_sha != merge_tree_sha:
        raise BrokerError("merge commit tree differs from the admitted head tree")
    return {
        "base_sha": admission["base_sha"],
        "head_sha": admission["head_sha"],
        "head_tree_sha": head_tree_sha,
        "merge_sha": merge_sha,
        "request_digest": admission["request_digest"],
        "schema_version": 1,
    }


class Broker:
    def __init__(
        self,
        *,
        api: GitHubApi,
        authenticator: AppAuthenticator,
        config: BrokerConfig,
        settings_authenticator: AppAuthenticator | None = None,
        sleep: Callable[[float], None] = time.sleep,
        spool: DurableSpool,
    ) -> None:
        self.api = api
        self.authenticator = authenticator
        self.config = config
        self.settings_authenticator = settings_authenticator or AppAuthenticator(
            api, config, purpose="settings"
        )
        self.sleep = sleep
        self.spool = spool

    @staticmethod
    def _pull_is_merge_ready(*, admission: dict[str, Any], pull: dict[str, Any]) -> bool:
        base = pull.get("base")
        head = pull.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise BrokerError("provider merge-readiness pull identity is malformed")
        pull_number = _require_positive_int(
            pull.get("number"), "provider merge-readiness pull request number"
        )
        if (
            pull_number != admission["pull_request"]
            or pull.get("state") != "open"
            or pull.get("merged") is not False
            or pull.get("draft") is not False
            or base.get("ref") != "main"
            or base.get("sha") != admission["base_sha"]
            or head.get("sha") != admission["head_sha"]
        ):
            raise BrokerError("provider merge-readiness pull identity changed")
        mergeable = pull.get("mergeable")
        mergeable_state = pull.get("mergeable_state")
        # The App-only update rule keeps the provider state blocked for every other actor.
        if mergeable is True and mergeable_state in {"blocked", "clean"}:
            return True
        if (
            (mergeable is None or mergeable is True)
            and isinstance(mergeable_state, str)
            and mergeable_state in {"blocked", "unknown", "unstable"}
        ):
            return False
        raise BrokerError("provider reports the exact pull request is not merge-ready")

    def _wait_for_provider_merge_ready(
        self,
        *,
        admission: dict[str, Any],
        token: str,
    ) -> None:
        started_at = self.api.provider_now(token)
        request_expires_at = _timestamp(admission["request"]["expires_at"])
        deadline = min(
            started_at + timedelta(seconds=MERGE_READINESS_TIMEOUT_SECONDS),
            request_expires_at - timedelta(seconds=MERGE_READINESS_LEASE_MARGIN_SECONDS),
        )
        for attempt in range(MERGE_READINESS_MAX_ATTEMPTS):
            result = self.api.request(
                f"repos/{self.config.repository}/pulls/{admission['pull_request']}",
                token=token,
            )
            if not isinstance(result.value, dict):
                raise BrokerError("provider merge-readiness response is malformed")
            provider_now = self.api.provider_now(token)
            if provider_now >= deadline:
                raise BrokerError(
                    "provider did not report the exact pull request merge-ready within its lease"
                )
            if self._pull_is_merge_ready(admission=admission, pull=result.value):
                return
            if attempt == MERGE_READINESS_MAX_ATTEMPTS - 1:
                break
            self.sleep(
                min(
                    float(MERGE_READINESS_POLL_SECONDS),
                    (deadline - provider_now).total_seconds(),
                )
            )
        raise BrokerError(
            "provider did not report the exact pull request merge-ready within bounded polling"
        )

    def _post_success_admission_seal(
        self,
        *,
        admission: dict[str, Any],
        expected_reviews: list[dict[str, Any]],
        expected_state: dict[str, Any],
        settings_token: str,
        state_branch: StateBranch,
        token: str,
    ) -> None:
        pull, reviews, commits = _pull_snapshot(
            self.api,
            config=self.config,
            number=admission["pull_request"],
            token=token,
        )
        if not self._pull_is_merge_ready(admission=admission, pull=pull):
            raise BrokerError("provider merge readiness changed before the post-success seal")
        if _provider_review_snapshot(reviews) != _provider_review_snapshot(expected_reviews):
            raise BrokerError("provider reviews changed after success publication")
        state = state_branch.read()
        if state.get("state_commit") != expected_state.get("state_commit") or state.get(
            "generation"
        ) != expected_state.get("generation"):
            raise BrokerError("main-health state changed after success publication")
        reviewer_permissions = _provider_review_permissions(
            self.api,
            config=self.config,
            reviews=reviews,
            token=token,
        )
        provider_now = self.api.provider_now(token)
        sealed_admission = self._select_provider_admission(
            commits=commits,
            provider_now=provider_now,
            pull=pull,
            reviewer_permissions=reviewer_permissions,
            reviews=reviews,
            settings_token=settings_token,
            state=state,
            state_branch=state_branch,
            token=token,
        )
        if sealed_admission["kind"] in {"normal", "owner-normal"}:
            _validate_state_for_admission(
                admission=sealed_admission,
                config=self.config,
                provider_now=provider_now,
                state=state,
            )
        if sealed_admission != admission:
            raise BrokerError("provider admission changed after success publication")
        validate_core_checks(
            check_runs=_check_runs(
                self.api,
                config=self.config,
                head_sha=admission["head_sha"],
                token=token,
            ),
            head_sha=admission["head_sha"],
        )
        validate_hosted_rulesets(
            config=self.config,
            rulesets=_rulesets(self.api, config=self.config, token=settings_token),
        )
        if sealed_admission["kind"] in {"normal", "owner-normal"}:
            verified_state = HealthReconciler(
                api=self.api,
                config=self.config,
                spool=self.spool,
                state_branch=state_branch,
                token=token,
            ).verify_current_health(self.api.provider_now(token))
            if verified_state.get("state_commit") != expected_state.get(
                "state_commit"
            ) or verified_state.get("generation") != expected_state.get("generation"):
                raise BrokerError("main-health state changed during post-success verification")
        trailing_reviews = _provider_list(
            self.api,
            f"repos/{self.config.repository}/pulls/{admission['pull_request']}/reviews",
            token=token,
        )
        if _provider_review_snapshot(trailing_reviews) != _provider_review_snapshot(reviews):
            raise BrokerError("provider reviews changed during the post-success seal")
        trailing_state = state_branch.read()
        if trailing_state.get("state_commit") != expected_state.get(
            "state_commit"
        ) or trailing_state.get("generation") != expected_state.get("generation"):
            raise BrokerError("main-health state changed during the post-success seal")
        if _main_ref(self.api, config=self.config, token=token) != admission["base_sha"]:
            raise BrokerError("main ref changed during the post-success seal")
        final_pull = self.api.request(
            f"repos/{self.config.repository}/pulls/{admission['pull_request']}",
            token=token,
        )
        if not isinstance(final_pull.value, dict) or not self._pull_is_merge_ready(
            admission=admission, pull=final_pull.value
        ):
            raise BrokerError("provider merge readiness changed during the post-success seal")
        provider_now = self.api.provider_now(token)
        if provider_now >= _timestamp(admission["request"]["expires_at"]):
            raise BrokerError("merge request expired during the post-success seal")
        if admission["kind"] == "owner-repair" and provider_now >= _timestamp(
            admission["manifest_expires_at"]
        ):
            raise BrokerError("owner emergency manifest expired during the post-success seal")

    def _reconcile_orphans(self, token: str) -> list[dict[str, Any]]:
        proofs: list[dict[str, Any]] = []
        check_controller = CheckController(
            api=self.api,
            config=self.config,
            spool=self.spool,
            token=token,
        )
        for admission in self.spool.requests_with_status("merging"):
            try:
                proof = verify_merge_proof(
                    admission=admission,
                    api=self.api,
                    config=self.config,
                    token=token,
                )
            except BrokerError:
                check_controller.ensure_failed(
                    head_sha=admission["head_sha"],
                    reason="Interrupted merge could not be proved and is quarantined.",
                )
                status = "uncertain"
            else:
                status = "merged"
                proofs.append(proof)
            self.spool.record_request(
                request_digest=admission["request_digest"],
                nonce=admission["nonce"],
                pull_request=admission["pull_request"],
                request=admission["request"],
                status=status,
                updated_at=self.api.provider_now(token).isoformat().replace("+00:00", "Z"),
            )
        return proofs

    def _reconcile_repair(
        self, *, state_branch: StateBranch, token: str, settings_token: str | None = None
    ) -> dict[str, Any]:
        state, incident, passing = state_branch.repair_context()
        if state.get("status") != "red" or incident is None:
            return state
        main_sha = _main_ref(self.api, config=self.config, token=token)
        required = {
            (main_sha, "protected-main"),
            (main_sha, "nightly"),
            (main_sha, "weekly"),
        }
        if not required <= set(passing):
            return state
        pulls = _provider_list(
            self.api,
            (
                f"repos/{self.config.repository}/pulls?state=closed&base=main"
                "&sort=updated&direction=desc"
            ),
            token=token,
        )
        candidates = [pull for pull in pulls if pull.get("merge_commit_sha") == main_sha]
        provider_now = self.api.provider_now(token)
        governed: list[
            tuple[
                int,
                dict[str, Any],
                dict[str, Any],
                list[dict[str, Any]],
                dict[str, Any] | None,
            ]
        ] = []
        for candidate in candidates:
            number = _require_positive_int(candidate.get("number"), "repaired pull request number")
            pull, reviews, commits = _pull_snapshot(
                self.api,
                config=self.config,
                number=number,
                token=token,
            )
            has_independent_request = any(
                isinstance(review.get("body"), str)
                and review["body"].startswith(REPAIR_REQUEST_MARKER)
                for review in reviews
            )
            has_owner_request = any(
                isinstance(review.get("body"), str)
                and review["body"].startswith(OWNER_REPAIR_REQUEST_MARKER)
                for review in reviews
            )
            if not has_independent_request and not has_owner_request:
                continue
            context: dict[str, Any] | None = None
            try:
                if not has_independent_request:
                    raise BrokerError("merged repair has no independent request")
                reviewer_permissions = _provider_review_permissions(
                    self.api,
                    config=self.config,
                    reviews=reviews,
                    token=token,
                )
                binding = _merged_repair_binding(
                    commits=commits,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                    state=state,
                )
            except BrokerError:
                if not has_owner_request:
                    raise
                if settings_token is None:
                    raise BrokerError("owner-repair reconciliation requires the settings App")
                context = _owner_repair_evidence_context(
                    self.api,
                    config=self.config,
                    pull=pull,
                    settings_token=settings_token,
                    token=token,
                )
                binding = _merged_owner_repair_binding(
                    commits=commits,
                    context=context,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviews=reviews,
                    state=state,
                )
            governed.append((number, binding, pull, reviews, context))
        if not governed:
            return state
        if len(governed) != 1:
            raise BrokerError("repaired main identifies multiple governed provider pull requests")
        number, binding, pull, reviews, owner_context = governed[0]
        verify_merge_proof(
            admission=binding,
            api=self.api,
            config=self.config,
            token=token,
        )
        if binding.get("authorization_mode") == OWNER_EMERGENCY_MODE:
            if owner_context is None or settings_token is None:
                raise BrokerError("owner-repair resolution has no provider context")
            first_binding, first_evidence = _capture_app_owner_repair_evidence(
                self.api,
                config=self.config,
                number=number,
                settings_token=settings_token,
                state=state,
                token=token,
            )
            second_binding, second_evidence = _capture_app_owner_repair_evidence(
                self.api,
                config=self.config,
                number=number,
                settings_token=settings_token,
                state=state,
                token=token,
            )
            first_stable = {
                key: value for key, value in first_evidence.items() if key != "captured_at"
            }
            second_stable = {
                key: value for key, value in second_evidence.items() if key != "captured_at"
            }
            if (
                first_binding != binding
                or second_binding != binding
                or first_stable != second_stable
                or _timestamp(second_evidence["captured_at"])
                < _timestamp(first_evidence["captured_at"])
            ):
                raise BrokerError("owner-repair provider evidence changed during final capture")
            binding = second_binding
            approval_evidence = second_evidence
        else:
            try:
                approval_evidence = stop_the_line.capture_github_approval(
                    repository=self.config.repository,
                    pull_request=str(number),
                    review_id=str(binding["approval_review_id"]),
                    issue=binding["issue"],
                    incident_digest=binding["incident_digest"],
                    token=token,
                )
            except stop_the_line.HealthError as exc:
                raise BrokerError(f"repair approval capture failed: {exc}") from exc
        if (
            approval_evidence.get("merge_commit_sha") != main_sha
            or approval_evidence.get("head_sha") != binding["head_sha"]
            or approval_evidence.get("incident_digest") != state.get("incident_digest")
        ):
            raise BrokerError("repair approval capture changed at the resolution boundary")
        sealed_state, sealed_incident, sealed_passing = state_branch.repair_context()
        if (
            sealed_state != state
            or sealed_incident != incident
            or sealed_passing != passing
            or not required <= set(sealed_passing)
        ):
            raise BrokerError("protected repair state changed during final evidence capture")
        resolved_at_dt = self.api.provider_now(token).replace(microsecond=0)
        resolved_at = resolved_at_dt.isoformat().replace("+00:00", "Z")
        manifest = approval_evidence.get("manifest")
        if approval_evidence["authorization_mode"] == OWNER_EMERGENCY_MODE:
            if not isinstance(manifest, dict) or not isinstance(manifest.get("expires_at"), str):
                raise BrokerError("owner-repair evidence has no manifest expiry")
            expires_at = manifest["expires_at"]
            manifest_digest: str | None = digest(manifest)
            policy_amendment = manifest.get("policy_amendment")
            if not isinstance(policy_amendment, dict):
                raise BrokerError("owner-repair evidence has no policy amendment")
            policy_amendment_digest: str | None = digest(policy_amendment)
        else:
            expires_at = (resolved_at_dt + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            manifest_digest = None
            policy_amendment_digest = None
        changed_paths = approval_evidence.get("changed_paths")
        failing_obligations = incident.get("failing_obligations")
        if (
            not isinstance(changed_paths, list)
            or not changed_paths
            or not isinstance(failing_obligations, list)
            or not failing_obligations
        ):
            raise BrokerError("repair approval paths or incident obligations are malformed")
        authorization = {
            "authorization_mode": approval_evidence["authorization_mode"],
            "approval_digest": digest(approval_evidence),
            "approval_id": approval_evidence["approval_id"],
            "approval_provider": approval_evidence["approval_provider"],
            "allowed_paths": changed_paths,
            "author": approval_evidence["author"],
            "author_id": approval_evidence["author_id"],
            "changed_paths_digest": digest(sorted(changed_paths)),
            "expires_at": expires_at,
            "failing_obligations": failing_obligations,
            "incident_digest": binding["incident_digest"],
            "issue": binding["issue"],
            "manifest_digest": manifest_digest,
            "policy_amendment_digest": policy_amendment_digest,
            "proposed_repair_sha": approval_evidence["head_sha"],
            "pull_request": str(number),
            "repository": self.config.repository,
            "required_cadences": ["nightly", "weekly"],
            "reviewer": approval_evidence["reviewer"],
            "reviewer_id": approval_evidence["reviewer_id"],
            "reviewer_permission": approval_evidence["reviewer_permission"],
            "schema_version": 1,
        }
        return state_branch.resolve_repair(
            approval_evidence=approval_evidence,
            authorization=authorization,
            expected_generation=_require_positive_int(state.get("generation"), "state generation"),
            repaired_main=passing[(main_sha, "protected-main")],
            resolved_at=resolved_at,
        )

    def _select_provider_admission(
        self,
        *,
        commits: list[dict[str, Any]],
        provider_now: datetime,
        pull: dict[str, Any],
        reviewer_permissions: dict[str, str],
        reviews: list[dict[str, Any]],
        settings_token: str,
        state: dict[str, Any],
        state_branch: StateBranch,
        token: str,
    ) -> dict[str, Any]:
        if state.get("status") == "green":
            try:
                return select_admission(
                    commits=commits,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                )
            except BrokerError:
                if not any(
                    isinstance(review.get("body"), str)
                    and review["body"].startswith(OWNER_REQUEST_MARKER)
                    for review in reviews
                ):
                    raise
                owner_context = _owner_provider_context(
                    self.api,
                    config=self.config,
                    provider_now=provider_now,
                    pull=pull,
                    repair=False,
                    settings_token=settings_token,
                    state=state,
                    state_branch=state_branch,
                    token=token,
                )
                return select_admission(
                    commits=commits,
                    now=provider_now,
                    owner_context=owner_context,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                )
        if state.get("status") == "red":
            try:
                return select_repair_admission(
                    commits=commits,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                    state=state,
                )
            except BrokerError:
                if not any(
                    isinstance(review.get("body"), str)
                    and review["body"].startswith(OWNER_REPAIR_REQUEST_MARKER)
                    for review in reviews
                ):
                    raise
                owner_context = _owner_provider_context(
                    self.api,
                    config=self.config,
                    provider_now=provider_now,
                    pull=pull,
                    repair=True,
                    settings_token=settings_token,
                    state=state,
                    state_branch=state_branch,
                    token=token,
                )
                return select_repair_admission(
                    commits=commits,
                    now=provider_now,
                    owner_context=owner_context,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                    state=state,
                )
        raise BrokerError("main-health state cannot admit a pull request")

    def _process_pull(
        self,
        *,
        check_controller: CheckController,
        number: int,
        provider_now: datetime,
        settings_token: str,
        state_branch: StateBranch,
        token: str,
    ) -> dict[str, Any] | None:
        pull, reviews, commits = _pull_snapshot(
            self.api,
            config=self.config,
            number=number,
            token=token,
        )
        state = state_branch.read()
        reviewer_permissions = _provider_review_permissions(
            self.api,
            config=self.config,
            reviews=reviews,
            token=token,
        )
        try:
            admission = self._select_provider_admission(
                commits=commits,
                provider_now=provider_now,
                pull=pull,
                reviewer_permissions=reviewer_permissions,
                reviews=reviews,
                settings_token=settings_token,
                state=state,
                state_branch=state_branch,
                token=token,
            )
        except BrokerError:
            return None
        status = self.spool.request_status(admission["request_digest"])
        if status is not None:
            return None
        if self.spool.get_check_external_id(admission["head_sha"]) in {
            f"mhb1:consumed:{admission['request_digest']}",
            f"mhb1:merge:{admission['request_digest']}",
        }:
            return None
        check_run_id = self.spool.get_check_id(admission["head_sha"])
        if check_run_id is None:
            raise BrokerError("pull request has no canonical failed broker check")
        if admission["kind"] in {"normal", "owner-normal"}:
            _validate_state_for_admission(
                admission=admission,
                config=self.config,
                provider_now=provider_now,
                state=state,
            )
        elif (
            state.get("status") != "red"
            or state.get("incident_digest") != admission["incident_digest"]
            or state.get("generation") != admission["state_generation"]
        ):
            raise BrokerError("repair admission state changed before validation")
        if _main_ref(self.api, config=self.config, token=token) != admission["base_sha"]:
            raise BrokerError("main ref changed before merge admission")
        validate_core_checks(
            check_runs=_check_runs(
                self.api,
                config=self.config,
                head_sha=admission["head_sha"],
                token=token,
            ),
            head_sha=admission["head_sha"],
        )
        validate_hosted_rulesets(
            config=self.config,
            rulesets=_rulesets(self.api, config=self.config, token=settings_token),
        )
        pull_again, reviews_again, commits_again = _pull_snapshot(
            self.api,
            config=self.config,
            number=number,
            token=token,
        )
        state_again = state_branch.read()
        reviewer_permissions_again = _provider_review_permissions(
            self.api,
            config=self.config,
            reviews=reviews_again,
            token=token,
        )
        final_now = self.api.provider_now(token)
        admission_again = self._select_provider_admission(
            commits=commits_again,
            provider_now=final_now,
            pull=pull_again,
            reviewer_permissions=reviewer_permissions_again,
            reviews=reviews_again,
            settings_token=settings_token,
            state=state_again,
            state_branch=state_branch,
            token=token,
        )
        if admission["kind"] in {"normal", "owner-normal"}:
            _validate_state_for_admission(
                admission=admission_again,
                config=self.config,
                provider_now=final_now,
                state=state_again,
            )
        if admission_again != admission:
            raise BrokerError("provider admission changed at the final merge boundary")
        if state_again.get("state_commit") != state.get("state_commit") or state_again.get(
            "generation"
        ) != state.get("generation"):
            raise BrokerError("main-health state changed at the final merge boundary")
        if _main_ref(self.api, config=self.config, token=token) != admission["base_sha"]:
            raise BrokerError("main ref changed at the final merge boundary")
        validate_core_checks(
            check_runs=_check_runs(
                self.api,
                config=self.config,
                head_sha=admission["head_sha"],
                token=token,
            ),
            head_sha=admission["head_sha"],
        )
        validate_hosted_rulesets(
            config=self.config,
            rulesets=_rulesets(self.api, config=self.config, token=settings_token),
        )
        if admission["kind"] in {"normal", "owner-normal"}:
            verified_state = HealthReconciler(
                api=self.api,
                config=self.config,
                spool=self.spool,
                state_branch=state_branch,
                token=token,
            ).verify_current_health(self.api.provider_now(token))
            if verified_state.get("state_commit") != state.get(
                "state_commit"
            ) or verified_state.get("generation") != state.get("generation"):
                raise BrokerError("main-health state changed during final provider verification")
        boundary_state = state_branch.read()
        if boundary_state.get("state_commit") != state.get("state_commit") or boundary_state.get(
            "generation"
        ) != state.get("generation"):
            raise BrokerError("main-health state changed before final admission")
        final_pull, final_reviews, final_commits = _pull_snapshot(
            self.api,
            config=self.config,
            number=number,
            token=token,
        )
        final_reviewer_permissions = _provider_review_permissions(
            self.api,
            config=self.config,
            reviews=final_reviews,
            token=token,
        )
        final_provider_now = self.api.provider_now(token)
        stable_reviews = _provider_list(
            self.api,
            f"repos/{self.config.repository}/pulls/{number}/reviews",
            token=token,
        )
        if _provider_review_snapshot(stable_reviews) != _provider_review_snapshot(final_reviews):
            raise BrokerError("provider reviews changed before the final provider review read")
        final_admission = self._select_provider_admission(
            commits=final_commits,
            provider_now=final_provider_now,
            pull=final_pull,
            reviewer_permissions=final_reviewer_permissions,
            reviews=stable_reviews,
            settings_token=settings_token,
            state=boundary_state,
            state_branch=state_branch,
            token=token,
        )
        if admission["kind"] in {"normal", "owner-normal"}:
            _validate_state_for_admission(
                admission=final_admission,
                config=self.config,
                provider_now=final_provider_now,
                state=boundary_state,
            )
        if final_admission != admission:
            raise BrokerError("provider admission changed immediately before merge")
        if final_admission["kind"] in {"owner-normal", "owner-repair"}:
            sealed_pull, sealed_reviews, sealed_commits = _pull_snapshot(
                self.api,
                config=self.config,
                number=number,
                token=token,
            )
            sealed_state = state_branch.read()
            if sealed_state.get("state_commit") != state.get("state_commit") or sealed_state.get(
                "generation"
            ) != state.get("generation"):
                raise BrokerError("main-health state changed during owner admission seal")
            sealed_permissions = _provider_review_permissions(
                self.api,
                config=self.config,
                reviews=sealed_reviews,
                token=token,
            )
            sealed_now = self.api.provider_now(token)
            sealed_admission = self._select_provider_admission(
                commits=sealed_commits,
                provider_now=sealed_now,
                pull=sealed_pull,
                reviewer_permissions=sealed_permissions,
                reviews=sealed_reviews,
                settings_token=settings_token,
                state=sealed_state,
                state_branch=state_branch,
                token=token,
            )
            if sealed_admission["kind"] == "owner-normal":
                _validate_state_for_admission(
                    admission=sealed_admission,
                    config=self.config,
                    provider_now=sealed_now,
                    state=sealed_state,
                )
            if sealed_admission != admission:
                raise BrokerError("owner provider context changed during admission seal")
            validate_core_checks(
                check_runs=_check_runs(
                    self.api,
                    config=self.config,
                    head_sha=admission["head_sha"],
                    token=token,
                ),
                head_sha=admission["head_sha"],
            )
            trailing_reviews = _provider_list(
                self.api,
                f"repos/{self.config.repository}/pulls/{number}/reviews",
                token=token,
            )
            if _provider_review_snapshot(trailing_reviews) != _provider_review_snapshot(
                sealed_reviews
            ):
                raise BrokerError("provider reviews changed during owner admission seal")
            trailing_state = state_branch.read()
            if trailing_state.get("state_commit") != state.get(
                "state_commit"
            ) or trailing_state.get("generation") != state.get("generation"):
                raise BrokerError("main-health state changed after owner admission seal")
            if _main_ref(self.api, config=self.config, token=token) != admission["base_sha"]:
                raise BrokerError("main ref changed during owner admission seal")
            final_provider_now = self.api.provider_now(token)
            if final_provider_now >= _timestamp(admission["request"]["expires_at"]):
                raise BrokerError("owner request expired during admission seal")
            if final_admission["kind"] == "owner-repair" and final_provider_now >= _timestamp(
                admission["manifest_expires_at"]
            ):
                raise BrokerError("owner emergency manifest expired during admission seal")
        self.spool.record_request(
            request_digest=admission["request_digest"],
            nonce=admission["nonce"],
            pull_request=number,
            request=admission["request"],
            status="merging",
            updated_at=final_provider_now.isoformat().replace("+00:00", "Z"),
        )
        check_controller.succeed(
            check_run_id=check_run_id,
            head_sha=admission["head_sha"],
            request=admission["request"],
            request_digest=admission["request_digest"],
            summary=(
                f"Exact-head {admission['kind']} merge admission for PR {number}; state "
                f"generation {state['generation']}."
            ),
        )
        self._wait_for_provider_merge_ready(admission=admission, token=token)
        self._post_success_admission_seal(
            admission=admission,
            expected_reviews=stable_reviews,
            expected_state=state,
            settings_token=settings_token,
            state_branch=state_branch,
            token=token,
        )
        merge_result: ApiResult | None = None
        ambiguous_response = False
        try:
            merge_result = self.api.request(
                f"repos/{self.config.repository}/pulls/{number}/merge",
                token=token,
                method="PUT",
                payload={"merge_method": "merge", "sha": admission["head_sha"]},
            )
        except ProviderTransportError:
            ambiguous_response = True
        except ProviderError:
            check_controller.ensure_failed(
                head_sha=admission["head_sha"],
                reason="Provider rejected the exact-head merge request.",
            )
            self.spool.record_request(
                request_digest=admission["request_digest"],
                nonce=admission["nonce"],
                pull_request=number,
                request=admission["request"],
                status="rejected",
                updated_at=provider_now.isoformat().replace("+00:00", "Z"),
            )
            raise
        response_merge_sha: str | None = None
        if not ambiguous_response:
            if (
                not isinstance(merge_result, ApiResult)
                or not isinstance(merge_result.value, dict)
                or merge_result.value.get("merged") is not True
            ):
                ambiguous_response = True
            else:
                try:
                    response_merge_sha = _require_sha(
                        merge_result.value.get("sha"), "merge response SHA"
                    )
                except BrokerError:
                    ambiguous_response = True
        if ambiguous_response:
            try:
                proof = verify_merge_proof(
                    admission=admission,
                    api=self.api,
                    config=self.config,
                    token=token,
                )
            except BrokerError as exc:
                check_controller.ensure_failed(
                    head_sha=admission["head_sha"],
                    reason="Ambiguous merge response could not be proved.",
                )
                self.spool.record_request(
                    request_digest=admission["request_digest"],
                    nonce=admission["nonce"],
                    pull_request=number,
                    request=admission["request"],
                    status="uncertain",
                    updated_at=provider_now.isoformat().replace("+00:00", "Z"),
                )
                raise BrokerError(
                    f"merge response was ambiguous and reconciliation did not prove success: {exc}"
                ) from None
        else:
            try:
                proof = verify_merge_proof(
                    admission=admission,
                    api=self.api,
                    config=self.config,
                    token=token,
                )
            except BrokerError:
                check_controller.ensure_failed(
                    head_sha=admission["head_sha"],
                    reason="Provider merge confirmation failed exact post-merge proof.",
                )
                self.spool.record_request(
                    request_digest=admission["request_digest"],
                    nonce=admission["nonce"],
                    pull_request=number,
                    request=admission["request"],
                    status="uncertain",
                    updated_at=provider_now.isoformat().replace("+00:00", "Z"),
                )
                raise
            if proof["merge_sha"] != response_merge_sha:
                check_controller.ensure_failed(
                    head_sha=admission["head_sha"],
                    reason="Provider merge response SHA failed exact post-merge proof.",
                )
                self.spool.record_request(
                    request_digest=admission["request_digest"],
                    nonce=admission["nonce"],
                    pull_request=number,
                    request=admission["request"],
                    status="uncertain",
                    updated_at=provider_now.isoformat().replace("+00:00", "Z"),
                )
                raise BrokerError("merge response SHA differs from exact post-merge proof")
        self.spool.record_request(
            request_digest=admission["request_digest"],
            nonce=admission["nonce"],
            pull_request=number,
            request=admission["request"],
            status="merged",
            updated_at=self.api.provider_now(token).isoformat().replace("+00:00", "Z"),
        )
        return proof

    def run_once(self) -> list[dict[str, Any]]:
        installation = self.authenticator.mint()
        token = installation.token
        provider_now = self.api.provider_now(token)
        validate_clock(
            local_now=datetime.now(UTC),
            provider_now=provider_now,
            max_clock_skew_seconds=self.config.max_clock_skew_seconds,
        )
        if installation.expires_at - provider_now < timedelta(minutes=10):
            raise BrokerError("installation token lifetime is unexpectedly short")
        proofs = self._reconcile_orphans(token)
        pulls = _provider_list(
            self.api,
            f"repos/{self.config.repository}/pulls?state=open&base=main",
            token=token,
        )
        check_controller = CheckController(
            api=self.api,
            config=self.config,
            spool=self.spool,
            token=token,
        )
        for pull in pulls:
            head = pull.get("head")
            if not isinstance(head, dict):
                raise BrokerError("open pull request head is malformed")
            head_sha = _require_sha(head.get("sha"), "open pull request head SHA")
            check_controller.ensure_failed(
                head_sha=head_sha,
                reason="Broker startup or polling boundary is fail-closed.",
            )
        settings_installation = self.settings_authenticator.mint()
        settings_token = settings_installation.token
        settings_now = self.api.provider_now(settings_token)
        validate_clock(
            local_now=datetime.now(UTC),
            provider_now=settings_now,
            max_clock_skew_seconds=self.config.max_clock_skew_seconds,
        )
        if settings_installation.expires_at - settings_now < timedelta(minutes=10):
            raise BrokerError("ruleset-witness token lifetime is unexpectedly short")
        validate_hosted_rulesets(
            config=self.config,
            rulesets=_rulesets(self.api, config=self.config, token=settings_token),
        )
        lease_controller = PublishLeaseController(
            api=self.api,
            config=self.config,
            spool=self.spool,
            token=token,
        )
        lease_fenced = lease_controller.reconcile(
            provider_now=self.api.provider_now(token),
            settings_token=settings_token,
        )
        state_branch = StateBranch(api=self.api, config=self.config, token=token)
        reconciler = HealthReconciler(
            api=self.api,
            config=self.config,
            spool=self.spool,
            state_branch=state_branch,
            token=token,
        )
        reconciler.reconcile_main(provider_now)
        reconciler.reconcile_deep(self.api.provider_now(token))
        self._reconcile_repair(
            settings_token=settings_token,
            state_branch=state_branch,
            token=token,
        )
        lease_fenced = lease_controller.reconcile(
            provider_now=self.api.provider_now(token),
            settings_token=settings_token,
        )
        if lease_fenced:
            return proofs
        for pull in pulls:
            number = _require_positive_int(pull.get("number"), "open pull request number")
            proof = self._process_pull(
                check_controller=check_controller,
                number=number,
                provider_now=self.api.provider_now(token),
                settings_token=settings_token,
                state_branch=state_branch,
                token=token,
            )
            if proof is not None:
                proofs.append(proof)
                break
        return proofs


def _acquire_lock(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "broker.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise BrokerError("another broker process already holds the singleton lock") from exc
    return descriptor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("once", "run", "validate-config"))
    parser.add_argument("--config", type=Path, required=True)
    return parser


def _fatal(message: str) -> NoReturn:
    raise SystemExit(f"main-health broker failed: {message}")


def _sd_notify(message: str) -> None:
    address = os.getenv("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
            notifier.connect(address)
            notifier.send(message.encode("utf-8"))
    except OSError as exc:
        raise BrokerError(f"systemd readiness notification failed: {exc}") from exc


def _serve(broker: Broker, *, poll_seconds: int) -> NoReturn:
    broker.run_once()
    _sd_notify("READY=1\nSTATUS=Last full broker cycle succeeded")
    print("main-health broker ready after one successful full cycle", flush=True)
    while True:
        time.sleep(poll_seconds)
        broker.run_once()
        _sd_notify("STATUS=Last full broker cycle succeeded")


def main() -> int:
    args = _parser().parse_args()
    try:
        config = BrokerConfig.from_mapping(_load_object(args.config))
        if args.command == "validate-config":
            print(json.dumps({"ok": True, "repository": config.repository}, sort_keys=True))
            return 0
        spool = DurableSpool(config.state_root)
        lock_descriptor = _acquire_lock(config.state_root)
        api = GitHubApi()
        broker = Broker(
            api=api,
            authenticator=AppAuthenticator(api, config),
            config=config,
            settings_authenticator=AppAuthenticator(api, config, purpose="settings"),
            spool=spool,
        )
        try:
            if args.command == "once":
                print(json.dumps(broker.run_once(), sort_keys=True, separators=(",", ":")))
                return 0
            _serve(broker, poll_seconds=config.poll_seconds)
        finally:
            os.close(lock_descriptor)
    except (BrokerError, OSError, sqlite3.Error) as exc:
        _fatal(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
