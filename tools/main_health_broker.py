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
MAIN_HEALTH_CHECK = "Main health / required"
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
SPOOL_SCHEMA_VERSION = 1
REQUEST_STATUSES = {"merged", "merging", "rejected", "uncertain"}
REQUEST_MARKER = "metriplane-merge-request:v1"
APPROVAL_MARKER = "metriplane-merge-approval:v1"
REPAIR_REQUEST_MARKER = "metriplane-repair-request:v1"
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
CONFIG_FIELDS = {
    "admission_ruleset_id",
    "app_id",
    "app_slug",
    "core_ruleset_id",
    "credential_path",
    "main_update_ruleset_id",
    "max_clock_skew_seconds",
    "poll_seconds",
    "repository",
    "settings_app_id",
    "settings_app_slug",
    "settings_credential_path",
    "state_branch",
    "state_protection_ruleset_id",
    "state_root",
    "state_writer_ruleset_id",
}
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
NONCE_RE = re.compile(r"[0-9a-f]{32}")


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
            mode = self.credential_path.stat().st_mode & 0o777
        except OSError as exc:
            raise BrokerError(f"cannot stat App credential: {exc}") from exc
        if mode & 0o077:
            raise BrokerError("App credential must not be group- or world-accessible")
        completed = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(self.credential_path)],
            input=value,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            raise BrokerError("OpenSSL could not sign the App JWT")
        return completed.stdout


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
                """
            )
            self._validate_schema(connection)
        os.chmod(self.path, 0o600)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        version_row = connection.execute("PRAGMA user_version").fetchone()
        if version_row is None or int(version_row[0]) not in {0, SPOOL_SCHEMA_VERSION}:
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
        if int(version_row[0]) == 0:
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


def select_admission(
    *,
    commits: list[dict[str, Any]],
    now: datetime,
    pull: dict[str, Any],
    repository: str,
    reviewer_permissions: dict[str, str],
    reviews: list[dict[str, Any]],
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
        conclusion: str,
        external_id: str,
        head_sha: str,
        summary: str,
        title: str,
    ) -> dict[str, Any]:
        completed_at = self.api.provider_now(self.token).replace(microsecond=0)
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
        self, *, check_run_id: int, head_sha: str, request_digest: str, summary: str
    ) -> dict[str, Any]:
        if DIGEST_RE.fullmatch(request_digest) is None:
            raise BrokerError("App check request digest is invalid")
        if self.spool.get_check_id(head_sha) != check_run_id:
            raise BrokerError("App check ID changed before success publication")
        external_id = f"mhb1:merge:{request_digest}"
        result = self.api.request(
            f"repos/{self.config.repository}/check-runs/{check_run_id}",
            token=self.token,
            method="PATCH",
            payload=self._payload(
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
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
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
        return f"github-actions:{run_id}:1"
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
                identity = _protected_main_result_identity(result.get("run_id"))
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

    def append(
        self,
        *,
        expected_generation: int,
        scope: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
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


def _validate_runtime_repository(api: GitHubApi, *, config: BrokerConfig, token: str) -> None:
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


def _rulesets(api: GitHubApi, *, config: BrokerConfig, token: str) -> dict[int, dict[str, Any]]:
    _validate_runtime_repository(api, config=config, token=token)
    identifiers = (
        config.core_ruleset_id,
        config.admission_ruleset_id,
        config.main_update_ruleset_id,
        config.state_protection_ruleset_id,
        config.state_writer_ruleset_id,
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
        exact = [
            run
            for run in runs
            if run.get("head_sha") == main_sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
        ]
        if not exact:
            return None
        try:
            return max(
                exact,
                key=lambda run: observe_main_health.provider_run_order(run, workflow="CI"),
            )
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
        spool: DurableSpool,
    ) -> None:
        self.api = api
        self.authenticator = authenticator
        self.config = config
        self.settings_authenticator = settings_authenticator or AppAuthenticator(
            api, config, purpose="settings"
        )
        self.spool = spool

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

    def _reconcile_repair(self, *, state_branch: StateBranch, token: str) -> dict[str, Any]:
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
        if len(candidates) != 1:
            raise BrokerError("repaired main does not identify one provider pull request")
        number = _require_positive_int(candidates[0].get("number"), "repaired pull request number")
        pull, reviews, commits = _pull_snapshot(
            self.api,
            config=self.config,
            number=number,
            token=token,
        )
        reviewer_permissions = _provider_review_permissions(
            self.api,
            config=self.config,
            reviews=reviews,
            token=token,
        )
        provider_now = self.api.provider_now(token)
        binding = _merged_repair_binding(
            commits=commits,
            now=provider_now,
            pull=pull,
            repository=self.config.repository,
            reviewer_permissions=reviewer_permissions,
            reviews=reviews,
            state=state,
        )
        verify_merge_proof(
            admission=binding,
            api=self.api,
            config=self.config,
            token=token,
        )
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
        resolved_at_dt = self.api.provider_now(token).replace(microsecond=0)
        resolved_at = resolved_at_dt.isoformat().replace("+00:00", "Z")
        expires_at = (resolved_at_dt + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
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
            "manifest_digest": None,
            "policy_amendment_digest": None,
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
            if state.get("status") == "green":
                admission = select_admission(
                    commits=commits,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                )
            elif state.get("status") == "red":
                admission = select_repair_admission(
                    commits=commits,
                    now=provider_now,
                    pull=pull,
                    repository=self.config.repository,
                    reviewer_permissions=reviewer_permissions,
                    reviews=reviews,
                    state=state,
                )
            else:
                return None
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
        if admission["kind"] == "normal":
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
        if admission["kind"] == "normal":
            admission_again = select_admission(
                commits=commits_again,
                now=final_now,
                pull=pull_again,
                repository=self.config.repository,
                reviewer_permissions=reviewer_permissions_again,
                reviews=reviews_again,
            )
            _validate_state_for_admission(
                admission=admission_again,
                config=self.config,
                provider_now=final_now,
                state=state_again,
            )
        else:
            admission_again = select_repair_admission(
                commits=commits_again,
                now=final_now,
                pull=pull_again,
                repository=self.config.repository,
                reviewer_permissions=reviewer_permissions_again,
                reviews=reviews_again,
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
        if admission["kind"] == "normal":
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
        self.spool.record_request(
            request_digest=admission["request_digest"],
            nonce=admission["nonce"],
            pull_request=number,
            request=admission["request"],
            status="merging",
            updated_at=provider_now.isoformat().replace("+00:00", "Z"),
        )
        check_controller.succeed(
            check_run_id=check_run_id,
            head_sha=admission["head_sha"],
            request_digest=admission["request_digest"],
            summary=(
                f"Exact-head {admission['kind']} merge admission for PR {number}; state "
                f"generation {state['generation']}."
            ),
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
        self._reconcile_repair(state_branch=state_branch, token=token)
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
