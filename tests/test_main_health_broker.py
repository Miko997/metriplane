# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import copy
import json
import os
import sqlite3
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Self

import pytest

from tools import main_health_broker as broker
from tools import release_artifacts, stop_the_line
from tools.baseline_snapshot import _internal_validate

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Miko997/metriplane"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
TREE_SHA = "d" * 40
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _config(tmp_path: Path) -> broker.BrokerConfig:
    return broker.BrokerConfig.from_mapping(
        {
            "admission_ruleset_id": 21500579,
            "app_id": 4722589,
            "app_slug": "metriplane-main-health-publisher",
            "core_ruleset_id": 20613848,
            "credential_path": str(tmp_path / "credentials" / "app.pem"),
            "main_update_ruleset_id": 21600001,
            "max_clock_skew_seconds": 30,
            "poll_seconds": 60,
            "release_lease_ruleset_id": 21600002,
            "release_tag_ruleset_id": 21600003,
            "repository": REPOSITORY,
            "settings_app_id": 9876543,
            "settings_app_slug": "metriplane-ruleset-witness",
            "settings_credential_path": str(tmp_path / "credentials" / "settings.pem"),
            "state_branch": "metriplane-main-health-state",
            "state_protection_ruleset_id": 21487681,
            "state_root": str(tmp_path / "state"),
            "state_writer_ruleset_id": 21533351,
        }
    )


def _rulesets(config: broker.BrokerConfig) -> dict[int, dict[str, Any]]:
    values = {
        config.core_ruleset_id: broker._core_ruleset(),
        config.admission_ruleset_id: broker._admission_ruleset(),
        config.main_update_ruleset_id: broker._app_update_ruleset(
            name="Restrict main updates to broker", include=[broker.MAIN_REF]
        ),
        config.state_protection_ruleset_id: broker._state_protection_ruleset(config.state_branch),
        config.state_writer_ruleset_id: broker._app_update_ruleset(
            name="Restrict main health state writers",
            include=[f"refs/heads/{config.state_branch}"],
        ),
        config.release_lease_ruleset_id: broker._release_lease_ruleset(),
        config.release_tag_ruleset_id: broker._release_tag_ruleset(),
    }
    return {
        identifier: {"id": identifier, **broker._provider_ruleset(value)}
        for identifier, value in values.items()
    }


def _request() -> dict[str, Any]:
    return {
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "expires_at": "2026-08-26T12:05:00Z",
        "head_sha": HEAD_SHA,
        "health_generation": 42,
        "nonce": "e" * 32,
        "pull_request": 81,
        "repository": REPOSITORY,
        "requester_id": 20,
        "schema_version": 1,
    }


def _request_body(request: dict[str, Any]) -> str:
    return broker.REQUEST_MARKER + "\n" + broker.canonical_bytes(request).decode().rstrip("\n")


def _repair_request() -> dict[str, Any]:
    return {
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "expires_at": "2026-08-26T12:05:00Z",
        "head_sha": HEAD_SHA,
        "incident_digest": "f" * 64,
        "issue": "MET-77",
        "nonce": "9" * 32,
        "pull_request": 81,
        "repository": REPOSITORY,
        "requester_id": 20,
        "schema_version": 1,
        "state_generation": 7,
    }


def _repair_reviews_for(pull_number: int) -> list[dict[str, Any]]:
    request = _repair_request()
    request["pull_request"] = pull_number
    return [
        {
            "body": (
                broker.REPAIR_REQUEST_MARKER
                + "\n"
                + broker.canonical_bytes(request).decode().rstrip("\n")
            ),
            "commit_id": HEAD_SHA,
            "id": 200,
            "state": "COMMENTED",
            "submitted_at": "2026-08-26T12:00:00Z",
            "user": {"id": 20, "login": "requester"},
        },
        {
            "body": "Main-health repair authorization: MET-77\nIncident: " + "f" * 64,
            "commit_id": HEAD_SHA,
            "id": 201,
            "state": "APPROVED",
            "submitted_at": "2026-08-26T12:01:00Z",
            "user": {"id": 40, "login": "reviewer"},
        },
    ]


def _repair_reviews() -> list[dict[str, Any]]:
    return _repair_reviews_for(81)


def _owner_ruleset_digests() -> dict[str, str]:
    return {
        "20613848": "1" * 64,
        "21487681": "2" * 64,
        "21500579": "3" * 64,
        "21533351": "4" * 64,
        "21600001": "5" * 64,
        "21600002": "6" * 64,
        "21600003": "7" * 64,
    }


def _owner_context(*, repair: bool = False) -> dict[str, Any]:
    collaborators = [{"id": "10", "login": "Miko997", "permission": "admin"}]
    context: dict[str, Any] = {
        "changed_paths_digest": broker.digest(["metriplane/fix.py", "tests/test_fix.py"]),
        "collaboration_digest": broker.digest(
            {"collaborators": collaborators, "pending_invitations": []}
        ),
        "collaborators": collaborators,
        "owner_id": 10,
        "owner_login": "Miko997",
        "owner_permission": "admin",
        "pending_invitations": [],
        "ruleset_digests": _owner_ruleset_digests(),
        "state_commit": "6" * 40,
    }
    if repair:
        context.update(
            {
                "manifest_expires_at": "2026-08-26T12:10:00Z",
                "manifest_digest": "7" * 64,
                "policy_amendment_digest": "8" * 64,
            }
        )
    return context


def _owner_request(*, repair: bool = False) -> dict[str, Any]:
    context = _owner_context(repair=repair)
    request: dict[str, Any] = {
        "authorization_mode": (
            broker.OWNER_EMERGENCY_MODE if repair else broker.OWNER_AUTHORIZATION_MODE
        ),
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "changed_paths_digest": context["changed_paths_digest"],
        "collaboration_digest": context["collaboration_digest"],
        "expires_at": "2026-08-26T12:05:00Z",
        "head_sha": HEAD_SHA,
        "health_generation": 42,
        "nonce": "7" * 32,
        "pull_request": 81,
        "repository": REPOSITORY,
        "requester_id": 10,
        "ruleset_digests": context["ruleset_digests"],
        "schema_version": 1,
        "state_commit": context["state_commit"],
    }
    if repair:
        request.pop("health_generation")
        request.update(
            {
                "incident_digest": "f" * 64,
                "issue": "MET-77",
                "manifest_digest": context["manifest_digest"],
                "policy_amendment_digest": context["policy_amendment_digest"],
                "state_generation": 7,
            }
        )
    return request


def _owner_reviews(*, repair: bool = False) -> list[dict[str, Any]]:
    request = _owner_request(repair=repair)
    marker = broker.OWNER_REPAIR_REQUEST_MARKER if repair else broker.OWNER_REQUEST_MARKER
    return [
        {
            "body": marker + "\n" + broker.canonical_bytes(request).decode().rstrip("\n"),
            "commit_id": HEAD_SHA,
            "id": 301,
            "state": "COMMENTED",
            "submitted_at": "2026-08-26T12:00:00Z",
            "user": {"id": 10, "login": "Miko997"},
        }
    ]


def _owner_pull() -> dict[str, Any]:
    return {**_pull(), "user": {"id": 10, "login": "Miko997"}}


def _reviews(*, approver_id: int = 40, approver_login: str = "reviewer") -> list[dict[str, Any]]:
    request = _request()
    return [
        {
            "body": _request_body(request),
            "commit_id": HEAD_SHA,
            "id": 100,
            "state": "COMMENTED",
            "submitted_at": "2026-08-26T12:00:00Z",
            "user": {"id": 20, "login": "requester"},
        },
        {
            "body": f"{broker.APPROVAL_MARKER} {broker.digest(request)}",
            "commit_id": HEAD_SHA,
            "id": 101,
            "state": "APPROVED",
            "submitted_at": "2026-08-26T12:01:00Z",
            "user": {"id": approver_id, "login": approver_login},
        },
    ]


def _pull() -> dict[str, Any]:
    return {
        "base": {"ref": "main", "sha": BASE_SHA},
        "commits": 1,
        "draft": False,
        "head": {"repo": {"full_name": REPOSITORY}, "sha": HEAD_SHA},
        "mergeable": True,
        "mergeable_state": "clean",
        "merged": False,
        "number": 81,
        "state": "open",
        "user": {"id": 10, "login": "author"},
    }


def _commits() -> list[dict[str, Any]]:
    return [
        {
            "author": {"id": 30, "login": "commit-author"},
            "committer": {"id": 31, "login": "commit-committer"},
            "sha": HEAD_SHA,
        }
    ]


def _decode_segment(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode(value + padding)
    result = json.loads(decoded)
    assert isinstance(result, dict)
    return result


def test_app_jwt_is_short_lived_and_provider_bound() -> None:
    signed: list[bytes] = []

    def signer(value: bytes) -> bytes:
        signed.append(value)
        return b"signature"

    token = broker.build_app_jwt(app_id=4722589, now=1_725_000_000, signer=signer)
    header, claims, signature = token.split(".")
    assert _decode_segment(header) == {"alg": "RS256", "typ": "JWT"}
    assert _decode_segment(claims) == {
        "exp": 1_725_000_540,
        "iat": 1_724_999_940,
        "iss": "4722589",
    }
    assert signed == [f"{header}.{claims}".encode()]
    assert signature == base64.urlsafe_b64encode(b"signature").rstrip(b"=").decode()


def test_app_token_permissions_are_exact() -> None:
    assert broker.APP_TOKEN_PERMISSIONS == {
        "actions": "read",
        "checks": "write",
        "contents": "write",
        "metadata": "read",
        "pull_requests": "read",
    }
    assert broker.SETTINGS_TOKEN_PERMISSIONS == {
        "administration": "write",
        "metadata": "read",
    }
    assert set(broker.APP_TOKEN_PERMISSIONS).isdisjoint({"administration"})
    assert set(broker.SETTINGS_TOKEN_PERMISSIONS).isdisjoint(
        {"actions", "checks", "contents", "pull_requests"}
    )


class FakeTokenApi(broker.GitHubApi):
    def __init__(
        self,
        *,
        installation: dict[str, Any] | None = None,
        repository: dict[str, Any] | None = None,
        token_response: dict[str, Any] | None = None,
        expected_permissions: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.calls = 0
        self.installation = _installation_response() if installation is None else installation
        self.repository = _repository_response() if repository is None else repository
        self.token_response = _token_response() if token_response is None else token_response
        self.expected_permissions = (
            broker.APP_TOKEN_PERMISSIONS if expected_permissions is None else expected_permissions
        )

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token
        self.calls += 1
        if path == f"repos/{REPOSITORY}/installation":
            assert method == "GET"
            return broker.ApiResult({}, 200, self.installation)
        if path.startswith("app/installations/"):
            assert path == "app/installations/7/access_tokens"
            assert method == "POST"
            assert expected == (201,)
            assert payload == {
                "permissions": self.expected_permissions,
                "repositories": ["metriplane"],
            }
            return broker.ApiResult({}, 201, self.token_response)
        assert path == f"repos/{REPOSITORY}"
        assert token == "installation-token"
        assert method == "GET"
        return broker.ApiResult({}, 200, self.repository)


def _installation_response(
    *,
    app_id: int = broker.APP_INTEGRATION_ID,
    app_slug: str = broker.APP_SLUG,
    permissions: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "access_tokens_url": "https://api.github.com/app/installations/7/access_tokens",
        "account": {"id": 997, "login": "Miko997", "type": "User"},
        "app_id": app_id,
        "app_slug": app_slug,
        "id": 7,
        "permissions": dict(broker.APP_TOKEN_PERMISSIONS if permissions is None else permissions),
        "repository_selection": "selected",
        "suspended_at": None,
        "target_id": 997,
        "target_type": "User",
    }


def _repository_response(*, repository_id: int = 1234) -> dict[str, Any]:
    return {
        "default_branch": "main",
        "full_name": REPOSITORY,
        "id": repository_id,
        "name": "metriplane",
        "owner": {"id": 997, "login": "Miko997", "type": "User"},
    }


def _token_response(*, permissions: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "expires_at": "2026-08-26T13:00:00Z",
        "permissions": dict(broker.APP_TOKEN_PERMISSIONS if permissions is None else permissions),
        "repositories": [_repository_response()],
        "repository_selection": "selected",
        "token": "installation-token",
    }


def _authenticator(tmp_path: Path, api: FakeTokenApi) -> broker.AppAuthenticator:
    authenticator = broker.AppAuthenticator(api, _config(tmp_path), clock=lambda: NOW)
    authenticator.signer = lambda _value: b"signature"
    return authenticator


def _root_owned_stat(value: os.stat_result, *, mode: int) -> os.stat_result:
    fields = list(value)
    fields[0] = stat.S_IFMT(value.st_mode) | mode
    fields[4] = 0
    fields[5] = 0
    return os.stat_result(fields)


def test_openssl_signer_accepts_only_private_credential_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = tmp_path / "app.pem"
    credential.write_text("key", encoding="utf-8")
    credential.chmod(0o600)
    assert broker._credential_is_private(credential)

    credential.chmod(0o640)
    assert not broker._credential_is_private(credential)
    link = tmp_path / "link.pem"
    link.symlink_to(credential)
    assert not broker._credential_is_private(link)

    directory = tmp_path / "systemd-credentials"
    directory.mkdir(mode=0o700)
    systemd_credential = directory / "app.pem"
    systemd_credential.write_text("key", encoding="utf-8")
    systemd_credential.chmod(0o440)
    directory.chmod(0o550)
    original_lstat = Path.lstat

    def root_owned_lstat(path: Path) -> os.stat_result:
        value = original_lstat(path)
        if path == directory:
            return _root_owned_stat(value, mode=0o550)
        if path == systemd_credential:
            return _root_owned_stat(value, mode=0o440)
        return value

    monkeypatch.setattr(Path, "lstat", root_owned_lstat)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(directory))
    assert broker._credential_is_private(systemd_credential)

    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    assert not broker._credential_is_private(systemd_credential)


def test_ruleset_witness_uses_a_distinct_repository_scoped_authority(tmp_path: Path) -> None:
    config = _config(tmp_path)
    installation = _installation_response(
        app_id=config.settings_app_id,
        app_slug=config.settings_app_slug,
        permissions=broker.SETTINGS_TOKEN_PERMISSIONS,
    )
    token_response = _token_response(permissions=broker.SETTINGS_TOKEN_PERMISSIONS)
    api = FakeTokenApi(
        installation=installation,
        token_response=token_response,
        expected_permissions=broker.SETTINGS_TOKEN_PERMISSIONS,
    )
    authenticator = broker.AppAuthenticator(
        api,
        config,
        clock=lambda: NOW,
        purpose="settings",
    )
    authenticator.signer = lambda _value: b"signature"

    assert authenticator.mint().token == "installation-token"
    assert authenticator.app_id != config.app_id
    assert authenticator.permissions == broker.SETTINGS_TOKEN_PERMISSIONS


def test_authenticator_rejects_permission_expansion(tmp_path: Path) -> None:
    exact_api = FakeTokenApi()
    exact = _authenticator(tmp_path, exact_api)
    assert exact.mint().token == "installation-token"
    assert exact.mint().token == "installation-token"
    assert exact_api.calls == 3

    response = _token_response()
    response["permissions"] = {**broker.APP_TOKEN_PERMISSIONS, "administration": "write"}
    expanded = _authenticator(tmp_path, FakeTokenApi(token_response=response))
    with pytest.raises(broker.BrokerError, match="permissions are not exact"):
        expanded.mint()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("app_id", 1, "App identity"),
        ("app_slug", "wrong-app", "App identity"),
        ("id", True, "installation ID"),
        ("target_id", 998, "target identity"),
        ("target_type", "Organization", "target identity"),
        ("repository_selection", "all", "repository selection"),
        ("suspended_at", "2026-08-26T11:00:00Z", "suspended"),
        (
            "access_tokens_url",
            "https://api.github.com/app/installations/8/access_tokens",
            "installation ID",
        ),
    ],
)
def test_authenticator_rejects_wrong_installation_identity(
    tmp_path: Path, field: str, value: Any, message: str
) -> None:
    installation = _installation_response()
    installation[field] = value
    with pytest.raises(broker.BrokerError, match=message):
        _authenticator(tmp_path, FakeTokenApi(installation=installation)).mint()


@pytest.mark.parametrize(
    "account",
    [
        {"id": 997, "login": "other", "type": "User"},
        {"id": 997, "login": "Miko997", "type": "Organization"},
        {"id": True, "login": "Miko997", "type": "User"},
    ],
)
def test_authenticator_rejects_wrong_installation_account(
    tmp_path: Path, account: dict[str, Any]
) -> None:
    installation = _installation_response()
    installation["account"] = account
    with pytest.raises(broker.BrokerError, match="account"):
        _authenticator(tmp_path, FakeTokenApi(installation=installation)).mint()


def test_authenticator_rejects_suspended_state_without_provider_field(tmp_path: Path) -> None:
    installation = _installation_response()
    del installation["suspended_at"]
    with pytest.raises(broker.BrokerError, match="suspension is unresolved"):
        _authenticator(tmp_path, FakeTokenApi(installation=installation)).mint()


def test_authenticator_rejects_installation_permission_drift(tmp_path: Path) -> None:
    installation = _installation_response()
    installation["permissions"] = {
        **broker.APP_TOKEN_PERMISSIONS,
        "administration": "write",
    }
    with pytest.raises(broker.BrokerError, match="installation permissions are not exact"):
        _authenticator(tmp_path, FakeTokenApi(installation=installation)).mint()


@pytest.mark.parametrize("selection", ["all", None])
def test_authenticator_rejects_wrong_token_selection(tmp_path: Path, selection: str | None) -> None:
    response = _token_response()
    response["repository_selection"] = selection
    with pytest.raises(broker.BrokerError, match="token repository selection is not exact"):
        _authenticator(tmp_path, FakeTokenApi(token_response=response)).mint()


def test_authenticator_rejects_repository_overbreadth(tmp_path: Path) -> None:
    response = _token_response()
    response["repositories"].append(
        {
            "full_name": "Miko997/other",
            "id": 5678,
            "name": "other",
            "owner": {"id": 997, "login": "Miko997", "type": "User"},
        }
    )
    with pytest.raises(broker.BrokerError, match="repository inventory is not exact"):
        _authenticator(tmp_path, FakeTokenApi(token_response=response)).mint()


def test_authenticator_rejects_wrong_repository_inventory_identity(tmp_path: Path) -> None:
    response = _token_response()
    response["repositories"] = [
        {
            "full_name": "Miko997/other",
            "id": 5678,
            "name": "other",
            "owner": {"id": 997, "login": "Miko997", "type": "User"},
        }
    ]
    with pytest.raises(broker.BrokerError, match="identity is not canonical"):
        _authenticator(tmp_path, FakeTokenApi(token_response=response)).mint()


@pytest.mark.parametrize("repositories", [None, [], {}])
def test_authenticator_rejects_missing_repository_inventory(
    tmp_path: Path, repositories: Any
) -> None:
    response = _token_response()
    response["repositories"] = repositories
    with pytest.raises(broker.BrokerError, match="repository inventory is not exact"):
        _authenticator(tmp_path, FakeTokenApi(token_response=response)).mint()


def test_authenticator_binds_inventory_to_canonical_repository(tmp_path: Path) -> None:
    wrong_owner = _repository_response()
    wrong_owner["owner"] = {"id": 998, "login": "Miko997", "type": "User"}
    with pytest.raises(broker.BrokerError, match="identity is not canonical"):
        _authenticator(tmp_path, FakeTokenApi(repository=wrong_owner)).mint()

    with pytest.raises(broker.BrokerError, match="repository ID is not exact"):
        _authenticator(
            tmp_path,
            FakeTokenApi(repository=_repository_response(repository_id=5678)),
        ).mint()


def test_authenticator_rejects_a_non_main_default_branch(tmp_path: Path) -> None:
    repository = _repository_response()
    repository["default_branch"] = "develop"
    with pytest.raises(broker.BrokerError, match="identity is not canonical"):
        _authenticator(tmp_path, FakeTokenApi(repository=repository)).mint()


def test_authenticator_accepts_minimal_inventory_when_full_repository_is_main(
    tmp_path: Path,
) -> None:
    response = _token_response()
    del response["repositories"][0]["default_branch"]
    assert _authenticator(tmp_path, FakeTokenApi(token_response=response)).mint().token == (
        "installation-token"
    )


def test_provider_server_error_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            "https://api.github.com/test",
            503,
            "unavailable",
            {"X-GitHub-Request-Id": "request"},
            None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(broker.ProviderTransportError, match="ambiguous HTTP 503"):
        broker.GitHubApi().request("test", token="token", method="PUT", payload={})


def test_mutating_malformed_json_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    class MalformedResponse:
        status = 200

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: MalformedResponse())
    with pytest.raises(broker.ProviderTransportError, match="malformed JSON"):
        broker.GitHubApi().request("merge", token="token", method="PUT", payload={})
    with pytest.raises(broker.BrokerError, match="malformed JSON") as exc_info:
        broker.GitHubApi().request("read", token="token")
    assert not isinstance(exc_info.value, broker.ProviderTransportError)


def test_git_environment_uses_noninteractive_github_app_basic_auth() -> None:
    environment = broker._git_environment("installation-token")
    expected = base64.b64encode(b"x-access-token:installation-token").decode("ascii")
    assert environment["GIT_CONFIG_COUNT"] == "1"
    assert environment["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert environment["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected}"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"

    with pytest.raises(broker.BrokerError, match="token is not ASCII"):
        broker._git_environment("not-ascii-\N{SNOWMAN}")


def test_config_rejects_noncanonical_app_and_permissive_clock(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert broker.GOVERNED_RULESET_COUNT == 7
    assert config.release_tag_ruleset_id == 21600003
    assert config.state_root == tmp_path / "state"
    value = {field: getattr(config, field) for field in broker.CONFIG_FIELDS}
    value["credential_path"] = str(value["credential_path"])
    value["settings_credential_path"] = str(value["settings_credential_path"])
    value["state_root"] = str(value["state_root"])
    legacy_six_rule_value = dict(value)
    del legacy_six_rule_value["release_tag_ruleset_id"]
    with pytest.raises(broker.BrokerError, match="fields are not exact"):
        broker.BrokerConfig.from_mapping(legacy_six_rule_value)
    for invalid in (0, -1, True):
        value["release_tag_ruleset_id"] = invalid
        with pytest.raises(broker.BrokerError, match="release_tag_ruleset_id"):
            broker.BrokerConfig.from_mapping(value)
    value["release_tag_ruleset_id"] = config.release_tag_ruleset_id
    value["app_id"] = 999
    with pytest.raises(broker.BrokerError, match="App ID"):
        broker.BrokerConfig.from_mapping(value)
    value["app_id"] = 4722589
    value["max_clock_skew_seconds"] = 61
    with pytest.raises(broker.BrokerError, match="must not exceed"):
        broker.BrokerConfig.from_mapping(value)
    value["max_clock_skew_seconds"] = 30
    value["repository"] = "other/repository"
    with pytest.raises(broker.BrokerError, match="repository is not canonical"):
        broker.BrokerConfig.from_mapping(value)
    value["repository"] = REPOSITORY
    value["settings_app_id"] = broker.APP_INTEGRATION_ID
    with pytest.raises(broker.BrokerError, match="must be distinct"):
        broker.BrokerConfig.from_mapping(value)
    value["settings_app_id"] = config.settings_app_id
    value["state_root"] = 7
    with pytest.raises(broker.BrokerError, match="paths must be strings"):
        broker.BrokerConfig.from_mapping(value)


def test_committed_config_and_system_service_are_hardened() -> None:
    status = ROOT / "docs" / "status"
    example = json.loads(
        (status / "examples" / "main-health-broker-config.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (status / "schemas" / "main-health-broker-config.schema.json").read_text(encoding="utf-8")
    )
    _internal_validate(example, schema)
    assert example["main_update_ruleset_id"] == 0
    assert example["release_lease_ruleset_id"] == 0
    assert example["release_tag_ruleset_id"] == 0
    assert example["settings_app_id"] == 0
    assert example["poll_seconds"] == 60
    assert Path(example["state_root"]) == Path("/home/metriplane-health/state")
    with pytest.raises(broker.BrokerError, match="settings_app_id"):
        broker.BrokerConfig.from_mapping(example)
    example_with_witness = {**example, "settings_app_id": 9876543}
    with pytest.raises(broker.BrokerError, match="main_update_ruleset_id"):
        broker.BrokerConfig.from_mapping(example_with_witness)
    example_with_main_rule = {**example_with_witness, "main_update_ruleset_id": 21600001}
    with pytest.raises(broker.BrokerError, match="release_lease_ruleset_id"):
        broker.BrokerConfig.from_mapping(example_with_main_rule)
    example_with_lease_rule = {
        **example_with_main_rule,
        "release_lease_ruleset_id": 21600002,
    }
    with pytest.raises(broker.BrokerError, match="release_tag_ruleset_id"):
        broker.BrokerConfig.from_mapping(example_with_lease_rule)
    unit = (ROOT / "scripts" / "systemd" / "metriplane-main-health-broker.service").read_text(
        encoding="utf-8"
    )
    for boundary in (
        "User=metriplane-health",
        "Type=notify",
        "NotifyAccess=main",
        "python -m tools.main_health_broker run",
        "LoadCredentialEncrypted=github-app-private-key.pem:",
        "LoadCredentialEncrypted=github-ruleset-witness-private-key.pem:",
        "NoNewPrivileges=true",
        "PYTHONDONTWRITEBYTECODE=1",
        "ProtectProc=invisible",
        "ProtectSystem=strict",
        "WorkingDirectory=/home/metriplane-main-health-broker",
        "ExecStart=/home/metriplane-main-health-broker/.venv/bin/python",
        "ReadWritePaths=/home/metriplane-health/state",
        "ReadOnlyPaths=/etc/metriplane /home/metriplane-main-health-broker",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "RestrictNamespaces=true",
        "CapabilityBoundingSet=",
    ):
        assert boundary in unit
    completed = subprocess.run(
        [sys.executable, "-m", "tools.main_health_broker", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "validate-config" in completed.stdout


def test_run_once_quarantines_before_ruleset_witness_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    now = datetime.now(UTC)

    class Authenticator:
        def __init__(self, event: str, token: str) -> None:
            self.event = event
            self.token = token

        def mint(self) -> broker.InstallationToken:
            events.append(self.event)
            return broker.InstallationToken(
                expires_at=now + timedelta(hours=1),
                installation_id=1,
                token=self.token,
            )

    class Api(broker.GitHubApi):
        def provider_now(self, token: str) -> datetime:
            assert token in {"merge-token", "settings-token"}
            return now

    class FailedChecks:
        def __init__(self, **_values: Any) -> None:
            return None

        def ensure_failed(self, *, head_sha: str, reason: str) -> int:
            assert head_sha == HEAD_SHA and reason
            events.append("failed-open-check")
            return 1

    api = Api()
    service = broker.Broker(
        api=api,
        authenticator=Authenticator("merge-mint", "merge-token"),  # type: ignore[arg-type]
        config=_config(tmp_path),
        settings_authenticator=Authenticator(  # type: ignore[arg-type]
            "settings-mint", "settings-token"
        ),
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    monkeypatch.setattr(
        service,
        "_reconcile_orphans",
        lambda token: events.append("reconcile-orphans") or [],
    )
    monkeypatch.setattr(
        broker,
        "_provider_list",
        lambda *_args, **_kwargs: (
            events.append("list-open-pulls") or [{"head": {"sha": HEAD_SHA}, "number": 81}]
        ),
    )
    monkeypatch.setattr(broker, "CheckController", FailedChecks)

    def fail_settings(*_args: Any, **kwargs: Any) -> dict[int, dict[str, Any]]:
        assert kwargs["token"] == "settings-token"
        events.append("validate-rulesets")
        raise broker.BrokerError("settings unavailable")

    monkeypatch.setattr(broker, "_rulesets", fail_settings)

    with pytest.raises(broker.BrokerError, match="settings unavailable"):
        service.run_once()
    assert events == [
        "merge-mint",
        "reconcile-orphans",
        "list-open-pulls",
        "failed-open-check",
        "settings-mint",
        "validate-rulesets",
    ]


def test_service_readiness_requires_success_and_later_failure_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[str] = []

    class Service:
        calls = 0

        def run_once(self) -> list[dict[str, Any]]:
            self.calls += 1
            if self.calls == 2:
                raise broker.BrokerError("persistent provider failure")
            return []

    service = Service()
    monkeypatch.setattr(broker, "_sd_notify", notifications.append)
    monkeypatch.setattr(broker.time, "sleep", lambda _seconds: None)

    with pytest.raises(broker.BrokerError, match="persistent provider failure"):
        broker._serve(service, poll_seconds=1)  # type: ignore[arg-type]
    assert service.calls == 2
    assert notifications == ["READY=1\nSTATUS=Last full broker cycle succeeded"]


def test_service_never_reports_ready_when_first_cycle_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[str] = []

    class Service:
        def run_once(self) -> list[dict[str, Any]]:
            raise broker.BrokerError("first cycle failed")

    monkeypatch.setattr(broker, "_sd_notify", notifications.append)
    with pytest.raises(broker.BrokerError, match="first cycle failed"):
        broker._serve(Service(), poll_seconds=1)  # type: ignore[arg-type]
    assert notifications == []


def test_owner_emergency_cli_is_retired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    admission = tmp_path / "admission.json"
    admission.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stop_the_line.py",
            "merge-owner-emergency",
            "--root",
            str(tmp_path),
            "--repository",
            REPOSITORY,
            "--pull-request",
            "81",
            "--issue",
            "MET-77",
            "--incident-digest",
            "1" * 64,
            "--admission-json",
            str(admission),
        ],
    )
    with pytest.raises(SystemExit, match="owner emergency is retired"):
        stop_the_line.main()


def test_rulesets_require_app_only_updates_and_no_human_bypass(tmp_path: Path) -> None:
    config = _config(tmp_path)
    values = _rulesets(config)
    digests = broker.validate_hosted_rulesets(config=config, rulesets=values)
    assert set(digests) == {str(identifier) for identifier in values}
    for identifier in (
        config.core_ruleset_id,
        config.admission_ruleset_id,
        config.main_update_ruleset_id,
    ):
        assert values[identifier]["conditions"]["ref_name"] == {
            "exclude": [],
            "include": [broker.MAIN_REF],
        }
    assert values[config.release_lease_ruleset_id]["conditions"]["ref_name"] == {
        "exclude": [],
        "include": [broker.PUBLISH_LEASE_REF_GLOB],
    }
    assert values[config.release_lease_ruleset_id]["bypass_actors"] == [
        {
            "actor_id": broker.APP_INTEGRATION_ID,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    assert values[config.release_lease_ruleset_id]["rules"] == [
        {"type": "creation"},
        {"type": "update"},
        {"type": "deletion"},
    ]
    assert values[config.release_tag_ruleset_id] == {
        "bypass_actors": [],
        "conditions": {"ref_name": {"exclude": [], "include": [broker.RELEASE_TAG_REF_GLOB]}},
        "enforcement": "active",
        "id": config.release_tag_ruleset_id,
        "name": "Protect release tags",
        "rules": [{"type": "update"}, {"type": "deletion"}],
        "source": REPOSITORY,
        "source_type": "Repository",
        "target": "tag",
    }

    changed = _rulesets(config)
    changed[config.release_lease_ruleset_id]["rules"].remove({"type": "creation"})
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.admission_ruleset_id]["bypass_actors"] = [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}
    ]
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.state_writer_ruleset_id]["bypass_actors"].append(
        {"actor_id": 141511110, "actor_type": "User", "bypass_mode": "always"}
    )
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.core_ruleset_id]["source"] = "Miko997/other"
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)


def test_release_tag_ruleset_is_exact_and_fail_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)

    missing = _rulesets(config)
    del missing[config.release_tag_ruleset_id]
    with pytest.raises(broker.BrokerError, match="ID inventory is not exact"):
        broker.validate_hosted_rulesets(config=config, rulesets=missing)

    changed = _rulesets(config)
    changed[config.release_tag_ruleset_id]["enforcement"] = "disabled"
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.release_tag_ruleset_id]["target"] = "branch"
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.release_tag_ruleset_id]["conditions"]["ref_name"]["include"] = ["refs/tags/v**"]
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    for missing_rule in ({"type": "update"}, {"type": "deletion"}):
        changed = _rulesets(config)
        changed[config.release_tag_ruleset_id]["rules"].remove(missing_rule)
        with pytest.raises(broker.BrokerError, match="not the governed"):
            broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.release_tag_ruleset_id]["rules"].append({"type": "creation"})
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)

    changed = _rulesets(config)
    changed[config.release_tag_ruleset_id]["bypass_actors"] = [
        {
            "actor_id": broker.APP_INTEGRATION_ID,
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    with pytest.raises(broker.BrokerError, match="not the governed"):
        broker.validate_hosted_rulesets(config=config, rulesets=changed)


def test_admission_binds_exact_provider_request_and_independent_approval() -> None:
    admission = broker.select_admission(
        commits=_commits(),
        now=NOW + timedelta(minutes=2),
        pull=_pull(),
        repository=REPOSITORY,
        reviewer_permissions={"reviewer": "write"},
        reviews=_reviews(),
    )
    assert admission["request_digest"] == broker.digest(_request())
    assert admission["approval_review_id"] == 101
    assert admission["health_generation"] == 42


@pytest.mark.parametrize("suffix", ["", "\n"])
def test_approval_parser_accepts_the_visible_documented_form(suffix: str) -> None:
    request_digest = broker.digest(_request())
    assert (
        broker.parse_approval(f"{broker.APPROVAL_MARKER} {request_digest}{suffix}")
        == request_digest
    )


@pytest.mark.parametrize("suffix", [" ", "\r\n", "\n\n", "\nextra"])
def test_approval_parser_rejects_noncanonical_trailing_content(suffix: str) -> None:
    request_digest = broker.digest(_request())
    with pytest.raises(broker.BrokerError, match="digest is invalid"):
        broker.parse_approval(f"{broker.APPROVAL_MARKER} {request_digest}{suffix}")


def test_admission_rejects_noncomment_request_and_revoked_approval() -> None:
    reviews = _reviews()
    reviews[0]["state"] = "DISMISSED"
    with pytest.raises(broker.BrokerError, match="must be a COMMENTED"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=reviews,
        )

    reviews = _reviews()
    reviews.append(
        {
            "body": "request changes",
            "id": 102,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-08-26T12:02:00Z",
            "user": {"id": 40, "login": "reviewer"},
        }
    )
    with pytest.raises(broker.BrokerError, match="current requested changes"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=3),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=reviews,
        )


@pytest.mark.parametrize(
    ("approver_id", "approver_login"),
    [(10, "author"), (20, "requester"), (30, "commit-author"), (31, "commit-committer")],
)
def test_admission_rejects_author_requester_and_commit_actors(
    approver_id: int, approver_login: str
) -> None:
    with pytest.raises(broker.BrokerError, match="no current independent"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={approver_login.casefold(): "write"},
            reviews=_reviews(approver_id=approver_id, approver_login=approver_login),
        )


@pytest.mark.parametrize("actor_key", ["author", "committer"])
@pytest.mark.parametrize(
    ("form", "actor"),
    [
        ("missing", None),
        ("null", None),
        ("non-object", []),
        ("empty", {}),
        ("missing-login", {"id": 30}),
        ("missing-id", {"login": "commit-actor"}),
        ("boolean-id", {"id": True, "login": "commit-actor"}),
        ("zero-id", {"id": 0, "login": "commit-actor"}),
        ("negative-id", {"id": -1, "login": "commit-actor"}),
        ("string-id", {"id": "30", "login": "commit-actor"}),
        ("empty-login", {"id": 30, "login": ""}),
        ("non-string-login", {"id": 30, "login": 30}),
    ],
)
def test_admission_rejects_unresolved_or_partial_commit_actors(
    actor_key: str, form: str, actor: Any
) -> None:
    commits = _commits()
    if form == "missing":
        del commits[0][actor_key]
    else:
        commits[0][actor_key] = actor
    with pytest.raises(broker.BrokerError, match=f"provider commit {actor_key} actor"):
        broker.select_admission(
            commits=commits,
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_reviews(),
        )


def test_admission_rejects_expiry_head_change_and_fork() -> None:
    with pytest.raises(broker.BrokerError, match="not currently valid"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=6),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_reviews(),
        )

    stale_request = _reviews()
    stale_request[0]["commit_id"] = BASE_SHA
    with pytest.raises(broker.BrokerError, match="request review is not anchored"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=stale_request,
        )

    stale_approval = _reviews()
    stale_approval[1]["commit_id"] = BASE_SHA
    with pytest.raises(broker.BrokerError, match="no current independent"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=stale_approval,
        )
    changed = _pull()
    changed["head"]["sha"] = "f" * 40
    with pytest.raises(broker.BrokerError, match="head or base changed"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=changed,
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_reviews(),
        )
    fork = _pull()
    fork["head"]["repo"]["full_name"] = "fork/metriplane"
    with pytest.raises(broker.BrokerError, match="fork"):
        broker.select_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=fork,
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_reviews(),
        )


def test_repair_admission_binds_red_incident_and_write_approval() -> None:
    admission = broker.select_repair_admission(
        commits=_commits(),
        now=NOW + timedelta(minutes=2),
        pull=_pull(),
        repository=REPOSITORY,
        reviewer_permissions={"reviewer": "write"},
        reviews=_repair_reviews(),
        state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
    )
    assert admission["kind"] == "repair"
    assert admission["approval_review_id"] == 201
    assert admission["incident_digest"] == "f" * 64

    with pytest.raises(broker.BrokerError, match="no current independent"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "read"},
            reviews=_repair_reviews(),
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )


def test_repair_admission_rejects_stale_generation_and_requested_changes() -> None:
    with pytest.raises(broker.BrokerError, match="incident generation"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_repair_reviews(),
            state={"generation": 8, "incident_digest": "f" * 64, "status": "red"},
        )

    stale_request = _repair_reviews()
    stale_request[0]["commit_id"] = BASE_SHA
    with pytest.raises(broker.BrokerError, match="request review is not anchored"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=stale_request,
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )

    reviews = _repair_reviews()
    reviews.append(
        {
            "body": "request changes",
            "commit_id": HEAD_SHA,
            "id": 202,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-08-26T12:02:00Z",
            "user": {"id": 40, "login": "reviewer"},
        }
    )
    with pytest.raises(broker.BrokerError, match="current requested changes"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=3),
            pull=_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=reviews,
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )


def test_single_maintainer_owner_requests_bind_exact_provider_context() -> None:
    normal = broker.select_admission(
        commits=_commits(),
        now=NOW + timedelta(minutes=2),
        owner_context=_owner_context(),
        pull=_owner_pull(),
        repository=REPOSITORY,
        reviewer_permissions={},
        reviews=_owner_reviews(),
    )
    assert normal["kind"] == "owner-normal"
    assert normal["authorization_mode"] == broker.OWNER_AUTHORIZATION_MODE
    assert normal["request_digest"] == broker.digest(_owner_request())

    repair = broker.select_repair_admission(
        commits=_commits(),
        now=NOW + timedelta(minutes=2),
        owner_context=_owner_context(repair=True),
        pull=_owner_pull(),
        repository=REPOSITORY,
        reviewer_permissions={},
        reviews=_owner_reviews(repair=True),
        state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
    )
    assert repair["kind"] == "owner-repair"
    assert repair["authorization_mode"] == broker.OWNER_EMERGENCY_MODE
    assert repair["manifest_digest"] == "7" * 64


@pytest.mark.parametrize("repair", [False, True])
def test_single_maintainer_owner_requests_ignore_prior_head_reviews(repair: bool) -> None:
    prior_head = "e" * 40
    prior_request = _owner_request(repair=repair)
    prior_request["head_sha"] = prior_head
    marker = broker.OWNER_REPAIR_REQUEST_MARKER if repair else broker.OWNER_REQUEST_MARKER
    prior_review = {
        **_owner_reviews(repair=repair)[0],
        "body": marker + "\n" + broker.canonical_bytes(prior_request).decode().rstrip("\n"),
        "commit_id": prior_head,
        "id": 300,
    }
    state = {"generation": 7, "incident_digest": "f" * 64, "status": "red"} if repair else None

    admission = broker._select_owner_admission(
        commits=_commits(),
        now=NOW + timedelta(minutes=2),
        owner_context=_owner_context(repair=repair),
        pull=_owner_pull(),
        repository=REPOSITORY,
        repair=repair,
        reviews=[prior_review, *_owner_reviews(repair=repair)],
        state=state,
    )
    assert admission["request_review_id"] == 301
    assert admission["head_sha"] == HEAD_SHA

    with pytest.raises(broker.BrokerError, match="no exact single-maintainer owner request"):
        broker._select_owner_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            owner_context=_owner_context(repair=repair),
            pull=_owner_pull(),
            repository=REPOSITORY,
            repair=repair,
            reviews=[prior_review],
            state=state,
        )


def test_single_maintainer_owner_request_rejects_malformed_review_head() -> None:
    review = _owner_reviews()[0]
    review["commit_id"] = 81.0

    with pytest.raises(broker.BrokerError, match="owner request review commit SHA"):
        broker._select_owner_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            owner_context=_owner_context(),
            pull=_owner_pull(),
            repository=REPOSITORY,
            repair=False,
            reviews=[review],
        )


def test_single_maintainer_owner_request_fails_closed_on_context_drift() -> None:
    context = _owner_context(repair=True)
    context["pending_invitations"] = [{"id": "99", "invitee": "reviewer", "permission": "write"}]
    context["collaboration_digest"] = broker.digest(
        {
            "collaborators": context["collaborators"],
            "pending_invitations": context["pending_invitations"],
        }
    )
    with pytest.raises(broker.BrokerError, match="eligible independent collaborator"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            owner_context=context,
            pull=_owner_pull(),
            repository=REPOSITORY,
            reviewer_permissions={},
            reviews=_owner_reviews(repair=True),
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )

    stale = _owner_context(repair=True)
    stale["state_commit"] = "9" * 40
    with pytest.raises(broker.BrokerError, match="live provider context"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            owner_context=stale,
            pull=_owner_pull(),
            repository=REPOSITORY,
            reviewer_permissions={},
            reviews=_owner_reviews(repair=True),
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )

    short_manifest = _owner_context(repair=True)
    short_manifest["manifest_expires_at"] = "2026-08-26T12:04:00Z"
    with pytest.raises(broker.BrokerError, match="outlives the emergency manifest"):
        broker.select_repair_admission(
            commits=_commits(),
            now=NOW + timedelta(minutes=2),
            owner_context=short_manifest,
            pull=_owner_pull(),
            repository=REPOSITORY,
            reviewer_permissions={},
            reviews=_owner_reviews(repair=True),
            state={"generation": 7, "incident_digest": "f" * 64, "status": "red"},
        )


def test_core_checks_use_latest_exact_actions_identity() -> None:
    runs = []
    for offset, name in enumerate(broker.CORE_CHECKS, start=1):
        runs.extend(
            [
                {
                    "app": {"id": 15368},
                    "conclusion": "failure",
                    "head_sha": HEAD_SHA,
                    "id": offset,
                    "name": name,
                    "status": "completed",
                },
                {
                    "app": {"id": 15368},
                    "conclusion": "success",
                    "head_sha": HEAD_SHA,
                    "id": offset + 100,
                    "name": name,
                    "status": "completed",
                },
            ]
        )
    selected = broker.validate_core_checks(check_runs=runs, head_sha=HEAD_SHA)
    assert selected == {
        "Metriplane / required": 101,
        "Documentation / required": 102,
        "Security / required": 103,
    }
    runs[-1]["conclusion"] = "cancelled"
    with pytest.raises(broker.BrokerError, match="not successful"):
        broker.validate_core_checks(check_runs=runs, head_sha=HEAD_SHA)


def test_spool_is_durable_and_nonce_is_single_use(tmp_path: Path) -> None:
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="closed",
        updated_at="2026-08-26T12:00:00Z",
    )
    assert broker.DurableSpool(tmp_path / "spool").get_check_id(HEAD_SHA) == 42
    first_request = {**_request(), "nonce": "2" * 32}
    spool.record_request(
        request_digest=broker.digest(first_request),
        nonce="2" * 32,
        pull_request=81,
        request=first_request,
        status="merging",
        updated_at="2026-08-26T12:00:00Z",
    )
    second_request = {**_request(), "nonce": "2" * 32, "pull_request": 82}
    with pytest.raises(sqlite3.IntegrityError):
        spool.record_request(
            request_digest=broker.digest(second_request),
            nonce="2" * 32,
            pull_request=82,
            request=second_request,
            status="merging",
            updated_at="2026-08-26T12:00:01Z",
        )
    spool.record_request(
        request_digest=broker.digest(first_request),
        nonce="2" * 32,
        pull_request=81,
        request=first_request,
        status="rejected",
        updated_at="2026-08-26T12:00:02Z",
    )
    with pytest.raises(broker.BrokerError, match="status is terminal"):
        spool.record_request(
            request_digest=broker.digest(first_request),
            nonce="2" * 32,
            pull_request=81,
            request=first_request,
            status="merging",
            updated_at="2026-08-26T12:00:03Z",
        )


def test_spool_closes_every_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = sqlite3.connect

    class TrackingConnection(sqlite3.Connection):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    connections: list[TrackingConnection] = []

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        kwargs["factory"] = TrackingConnection
        connection = real_connect(*args, **kwargs)
        assert isinstance(connection, TrackingConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(broker.sqlite3, "connect", connect)
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="closed",
        updated_at="2026-08-26T12:00:00Z",
    )
    assert spool.get_check_id(HEAD_SHA) == 42
    assert connections
    assert all(connection.closed for connection in connections)


def test_spool_rejects_incompatible_or_future_schema(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy-spool"
    legacy_root.mkdir()
    with closing(sqlite3.connect(legacy_root / "broker.sqlite3")) as connection, connection:
        connection.execute(
            """
            CREATE TABLE requests (
                request_digest TEXT PRIMARY KEY,
                nonce TEXT NOT NULL UNIQUE,
                pull_request INTEGER NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    with pytest.raises(broker.BrokerError, match="requests schema is incompatible"):
        broker.DurableSpool(legacy_root)

    future_root = tmp_path / "future-spool"
    future = broker.DurableSpool(future_root)
    with closing(sqlite3.connect(future.path)) as connection, connection:
        connection.execute(f"PRAGMA user_version = {broker.SPOOL_SCHEMA_VERSION + 1}")
    with pytest.raises(broker.BrokerError, match="schema version is incompatible"):
        broker.DurableSpool(future_root)


class FakeCheckApi(broker.GitHubApi):
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        super().__init__()
        self.current_now = NOW
        self.runs = runs
        self.calls: list[tuple[str, str]] = []

    def provider_now(self, token: str) -> datetime:
        assert token == "token"
        return self.current_now

    def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
        assert key == "check_runs"
        assert token == "token"
        return [dict(item) for item in self.runs]

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        assert payload is not None
        self.calls.append((method, path))
        if method == "POST":
            value = {"id": 900, "app": {"id": 4722589, "slug": broker.APP_SLUG}, **payload}
            self.runs.append(value)
            return broker.ApiResult({}, 201, value)
        check_run_id = int(path.rsplit("/", 1)[1])
        run = next(item for item in self.runs if item["id"] == check_run_id)
        run.update(payload)
        return broker.ApiResult({}, 200, dict(run))


def _app_check(check_run_id: int, conclusion: str = "success") -> dict[str, Any]:
    return {
        "app": {"id": 4722589, "slug": broker.APP_SLUG},
        "completed_at": "2026-08-26T11:59:00Z",
        "conclusion": conclusion,
        "external_id": "old",
        "head_sha": HEAD_SHA,
        "id": check_run_id,
        "name": broker.MAIN_HEALTH_CHECK,
        "status": "completed",
    }


def test_check_controller_reuses_one_id_and_quarantines_duplicates(tmp_path: Path) -> None:
    api = FakeCheckApi([_app_check(42), _app_check(43)])
    spool = broker.DurableSpool(tmp_path / "spool")
    controller = broker.CheckController(
        api=api,
        config=_config(tmp_path),
        spool=spool,
        token="token",
    )
    assert controller.ensure_failed(head_sha=HEAD_SHA, reason="startup") == 42
    assert spool.get_check_id(HEAD_SHA) == 42
    canonical = next(item for item in api.runs if item["id"] == 42)
    duplicate = next(item for item in api.runs if item["id"] == 43)
    assert canonical["conclusion"] == "failure"
    assert duplicate["name"] == f"{broker.MAIN_HEALTH_CHECK} [superseded 43]"
    request = _request()
    request_digest = broker.digest(request)
    controller.succeed(
        check_run_id=42,
        head_sha=HEAD_SHA,
        request=request,
        request_digest=request_digest,
        summary="exact merge",
    )
    assert canonical["conclusion"] == "success"
    assert spool.get_check_id(HEAD_SHA) == 42
    assert spool.get_check_external_id(HEAD_SHA) == f"mhb1:merge:{request_digest}"

    restored_spool = broker.DurableSpool(tmp_path / "restored-spool")
    restored = broker.CheckController(
        api=api,
        config=_config(tmp_path),
        spool=restored_spool,
        token="token",
    )
    assert restored.ensure_failed(head_sha=HEAD_SHA, reason="restored startup") == 42
    assert restored_spool.get_check_external_id(HEAD_SHA) == f"mhb1:consumed:{request_digest}"


@pytest.mark.parametrize("admission_request", [_request(), _repair_request()])
def test_check_controller_refuses_expired_admission_before_success_publication(
    tmp_path: Path, admission_request: dict[str, Any]
) -> None:
    run = _app_check(42, conclusion="failure")
    api = FakeCheckApi([run])
    api.current_now = broker._timestamp(admission_request["expires_at"])
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="mhb1:closed:test",
        updated_at="2026-08-26T12:04:59Z",
    )
    controller = broker.CheckController(
        api=api,
        config=_config(tmp_path),
        spool=spool,
        token="token",
    )

    with pytest.raises(broker.BrokerError, match="lease expired before success publication"):
        controller.succeed(
            check_run_id=42,
            head_sha=HEAD_SHA,
            request=admission_request,
            request_digest=broker.digest(admission_request),
            summary="must remain closed",
        )

    assert api.calls == []
    assert run["conclusion"] == "failure"
    assert spool.get_check_external_id(HEAD_SHA) == "mhb1:closed:test"


class FakeProofApi(broker.GitHubApi):
    def __init__(self) -> None:
        super().__init__()
        self.tree_sha = TREE_SHA
        self.calls: list[tuple[str, str]] = []

    def provider_now(self, token: str) -> datetime:
        assert token == "token"
        return NOW

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        self.calls.append((method, path))
        assert method == "GET"
        if path.endswith("/pulls/81"):
            value = {"merge_commit_sha": MERGE_SHA, "merged": True, "state": "closed"}
        elif path.endswith("/git/ref/heads/main"):
            value = {"object": {"sha": MERGE_SHA, "type": "commit"}, "ref": "refs/heads/main"}
        elif path.endswith(f"/commits/{HEAD_SHA}"):
            value = {"commit": {"tree": {"sha": TREE_SHA}}, "sha": HEAD_SHA}
        elif path.endswith(f"/commits/{MERGE_SHA}"):
            value = {
                "commit": {"tree": {"sha": self.tree_sha}},
                "parents": [{"sha": BASE_SHA}, {"sha": HEAD_SHA}],
                "sha": MERGE_SHA,
            }
        else:
            raise AssertionError(path)
        return broker.ApiResult({}, 200, value)


def test_post_merge_proof_binds_parents_tree_and_main(tmp_path: Path) -> None:
    admission = {
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "pull_request": 81,
        "request_digest": "5" * 64,
    }
    api = FakeProofApi()
    proof = broker.verify_merge_proof(
        admission=admission,
        api=api,
        config=_config(tmp_path),
        token="token",
    )
    assert proof["merge_sha"] == MERGE_SHA
    assert proof["head_tree_sha"] == TREE_SHA
    api.tree_sha = "e" * 40
    with pytest.raises(broker.BrokerError, match="tree differs"):
        broker.verify_merge_proof(
            admission=admission,
            api=api,
            config=_config(tmp_path),
            token="token",
        )


class FakeTransactionApi(broker.GitHubApi):
    def __init__(self, config: broker.BrokerConfig, behavior: str) -> None:
        super().__init__()
        self.behavior = behavior
        self.config = config
        self.current_now = NOW + timedelta(minutes=2)
        self.default_branch = "main"
        self.documentation_conclusion: str | None = "success"
        self.documentation_run_id = 502
        self.documentation_status = "completed"
        self.drift_default_on_final = False
        self.nightly_conclusion: str | None = "success"
        self.nightly_run_id = 601
        self.nightly_status = "completed"
        self.weekly_conclusion: str | None = "success"
        self.weekly_run_id = 602
        self.weekly_status = "completed"
        self.drift_on_final_ruleset = False
        self.drift_tag_identity_on_final_ruleset = False
        self.drift_tag_semantics_on_final_ruleset = False
        self.drift_update_bypass = False
        self.inject_older_rerun_on_final_ruleset = False
        self.extra_active_ruleset = False
        self.inventory_source_drift = False
        self.include_deep_runs = True
        self.older_weekly_rerun: dict[str, Any] | None = None
        self.reviews = _reviews()
        self.review_change_on_final_permission: str | None = None
        self.reviewer_permission_calls = 0
        self.merged = False
        self.merge_calls = 0
        self.mergeable_states: list[str] = []
        self.merge_readiness_calls = 0
        self.reported_commits = 1
        self.repository_identity_calls = 0
        self.ruleset_inventory_calls = 0

    def provider_now(self, token: str) -> datetime:
        assert token == "token"
        return self.current_now

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        if path == f"repos/{REPOSITORY}":
            self.repository_identity_calls += 1
            default_branch = (
                "develop"
                if self.drift_default_on_final and self.repository_identity_calls >= 2
                else self.default_branch
            )
            return broker.ApiResult(
                {},
                200,
                {**_repository_response(), "default_branch": default_branch},
            )
        if path.endswith("/pulls/81/merge"):
            assert method == "PUT"
            assert payload == {"merge_method": "merge", "sha": HEAD_SHA}
            self.merge_calls += 1
            if self.behavior == "reject":
                raise broker.ProviderError("rejected", status=409)
            if self.behavior == "transport-open":
                raise broker.ProviderTransportError("response lost")
            if self.behavior == "nonexact-open":
                return broker.ApiResult({}, 200, {"merged": False})
            self.merged = True
            if self.behavior == "transport-merged":
                raise broker.ProviderTransportError("response lost")
            if self.behavior == "nonexact-merged":
                return broker.ApiResult({}, 200, {"merged": True})
            return broker.ApiResult({}, 200, {"merged": True, "sha": MERGE_SHA})
        if "/pulls/81/reviews?" in path:
            return broker.ApiResult(
                {},
                200,
                [
                    {
                        **review,
                        "user": dict(review["user"]),
                    }
                    for review in self.reviews
                ],
            )
        if "/pulls/81/commits?" in path:
            return broker.ApiResult({}, 200, _commits())
        if path.endswith("/pulls/81"):
            value = _pull()
            value["commits"] = self.reported_commits
            if self.mergeable_states:
                self.merge_readiness_calls += 1
                mergeable_state = self.mergeable_states.pop(0)
                value["mergeable"] = None if mergeable_state == "unknown" else True
                value["mergeable_state"] = mergeable_state
            if self.merged:
                value = {**value, "merge_commit_sha": MERGE_SHA, "merged": True, "state": "closed"}
            return broker.ApiResult({}, 200, value)
        if path.endswith("/git/ref/heads/main"):
            sha = MERGE_SHA if self.merged else BASE_SHA
            return broker.ApiResult(
                {}, 200, {"object": {"sha": sha, "type": "commit"}, "ref": "refs/heads/main"}
            )
        if "/collaborators/" in path and path.endswith("/permission"):
            self.reviewer_permission_calls += 1
            if self.reviewer_permission_calls == 3:
                if self.review_change_on_final_permission == "DISMISSED":
                    self.reviews[1]["state"] = "DISMISSED"
                elif self.review_change_on_final_permission == "CHANGES_REQUESTED":
                    self.reviews.append(
                        {
                            "body": "approval revoked during permission lookup",
                            "commit_id": HEAD_SHA,
                            "id": 102,
                            "state": "CHANGES_REQUESTED",
                            "submitted_at": "2026-08-26T12:03:00Z",
                            "user": {"id": 40, "login": "reviewer"},
                        }
                    )
            return broker.ApiResult({}, 200, {"permission": "write"})
        if "/rulesets?includes_parents=true" in path:
            self.ruleset_inventory_calls += 1
            if self.inject_older_rerun_on_final_ruleset and self.ruleset_inventory_calls >= 2:
                self.older_weekly_rerun = {
                    "conclusion": None,
                    "display_title": "Main Health Deep / main-health-weekly / main",
                    "head_sha": BASE_SHA,
                    "id": 600,
                    "run_attempt": 2,
                    "status": "in_progress",
                    "updated_at": "2026-08-26T12:01:00Z",
                }
            inventory = [
                {
                    field: ruleset[field]
                    for field in (
                        "enforcement",
                        "id",
                        "name",
                        "source",
                        "source_type",
                        "target",
                    )
                }
                for ruleset in _rulesets(self.config).values()
            ]
            if self.inventory_source_drift:
                inventory[0]["source"] = "Miko997/other"
            if self.extra_active_ruleset or (
                self.drift_on_final_ruleset and self.ruleset_inventory_calls >= 2
            ):
                inventory.append(
                    {
                        "enforcement": "active",
                        "id": 999,
                        "name": "Unexpected active tag policy",
                        "source": REPOSITORY,
                        "source_type": "Repository",
                        "target": "tag",
                    }
                )
            return broker.ApiResult({}, 200, inventory)
        if "/rulesets/" in path:
            ruleset_id = int(path.rsplit("/", 1)[1])
            ruleset = copy.deepcopy(_rulesets(self.config)[ruleset_id])
            if (
                self.drift_tag_identity_on_final_ruleset
                and self.ruleset_inventory_calls >= 2
                and ruleset_id == self.config.release_tag_ruleset_id
            ):
                ruleset["id"] = 999
            if (
                self.drift_tag_semantics_on_final_ruleset
                and self.ruleset_inventory_calls >= 2
                and ruleset_id == self.config.release_tag_ruleset_id
            ):
                ruleset["rules"].append({"type": "creation"})
            if self.drift_update_bypass and ruleset_id == self.config.main_update_ruleset_id:
                ruleset["bypass_actors"] = []
            return broker.ApiResult({}, 200, ruleset)
        if path.endswith(f"/commits/{HEAD_SHA}"):
            return broker.ApiResult(
                {}, 200, {"commit": {"tree": {"sha": TREE_SHA}}, "sha": HEAD_SHA}
            )
        if path.endswith(f"/commits/{MERGE_SHA}"):
            tree_sha = "e" * 40 if self.behavior == "bad-proof" else TREE_SHA
            return broker.ApiResult(
                {},
                200,
                {
                    "commit": {"tree": {"sha": tree_sha}},
                    "parents": [{"sha": BASE_SHA}, {"sha": HEAD_SHA}],
                    "sha": MERGE_SHA,
                },
            )
        raise AssertionError((method, path))

    def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
        assert token == "token"
        if key == "check_runs":
            assert path.endswith(f"/commits/{HEAD_SHA}/check-runs?filter=all")
            return [
                {
                    "app": {"id": broker.ACTIONS_INTEGRATION_ID},
                    "conclusion": "success",
                    "head_sha": HEAD_SHA,
                    "id": 100 + offset,
                    "name": name,
                    "status": "completed",
                }
                for offset, name in enumerate(broker.CORE_CHECKS)
            ]
        if "actions/workflows/ci.yml/runs" in path:
            assert key == "workflow_runs"
            return [
                {
                    "conclusion": "success",
                    "created_at": "2026-08-26T11:50:00Z",
                    "event": "push",
                    "head_branch": "main",
                    "head_sha": BASE_SHA,
                    "id": 501,
                    "run_attempt": 1,
                    "status": "completed",
                    "updated_at": "2026-08-26T11:55:00Z",
                }
            ]
        if path.endswith(f"/actions/runs?head_sha={BASE_SHA}"):
            assert key == "workflow_runs"
            return [
                {
                    "conclusion": conclusion,
                    "event": "push",
                    "head_branch": "main",
                    "head_sha": BASE_SHA,
                    "id": run_id,
                    "name": workflow,
                    "run_attempt": 1,
                    "status": status,
                    "updated_at": "2026-08-26T11:56:00Z",
                }
                for run_id, workflow, status, conclusion in (
                    (
                        self.documentation_run_id,
                        "Documentation",
                        self.documentation_status,
                        self.documentation_conclusion,
                    ),
                    (503, "CodeQL", "completed", "success"),
                )
            ]
        if "actions/workflows/main-health.yml/runs" in path:
            assert key == "workflow_runs"
            if not self.include_deep_runs:
                return []
            runs = [
                {
                    "conclusion": conclusion,
                    "display_title": f"Main Health Deep / main-health-{cadence} / main",
                    "head_sha": BASE_SHA,
                    "id": run_id,
                    "run_attempt": 1,
                    "status": status,
                    "updated_at": "2026-08-26T11:55:00Z",
                }
                for cadence, run_id, status, conclusion in (
                    (
                        "nightly",
                        self.nightly_run_id,
                        self.nightly_status,
                        self.nightly_conclusion,
                    ),
                    (
                        "weekly",
                        self.weekly_run_id,
                        self.weekly_status,
                        self.weekly_conclusion,
                    ),
                )
            ]
            if self.older_weekly_rerun is not None:
                runs.append(dict(self.older_weekly_rerun))
            return runs
        if "/actions/runs/" in path and path.endswith("/jobs"):
            assert key == "jobs"
            run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
            attempt = int(path.split("/attempts/", 1)[1].split("/", 1)[0])
            if run_id in {self.nightly_run_id, self.weekly_run_id}:
                cadence = "nightly" if run_id == self.nightly_run_id else "weekly"
                status = self.weekly_status if cadence == "weekly" else self.nightly_status
                conclusion = (
                    self.weekly_conclusion if cadence == "weekly" else self.nightly_conclusion
                )
                return [
                    {
                        "conclusion": conclusion,
                        "head_sha": BASE_SHA,
                        "id": 1_000 + run_id,
                        "name": f"Main health deep / {cadence}",
                        "run_attempt": attempt,
                        "run_id": run_id,
                        "status": status,
                    }
                ]
            key_by_run = {
                501: "metriplane",
                self.documentation_run_id: "documentation",
                503: "security",
            }
            selected_key = key_by_run[run_id]
            terminal, workflow = broker.observe_main_health.REQUIRED_WORKFLOWS[selected_key]
            job_id = 1_000 + run_id
            status = self.documentation_status if selected_key == "documentation" else "completed"
            conclusion = (
                self.documentation_conclusion if selected_key == "documentation" else "success"
            )
            return [
                {
                    "check_run_url": (
                        f"https://api.github.com/repos/{REPOSITORY}/check-runs/{job_id}"
                    ),
                    "conclusion": conclusion,
                    "head_branch": "main",
                    "head_sha": BASE_SHA,
                    "id": job_id,
                    "name": terminal,
                    "run_attempt": attempt,
                    "run_id": run_id,
                    "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
                    "status": status,
                    "workflow_name": workflow,
                }
            ]
        raise AssertionError((key, path))


class FakeOwnerTransactionApi(FakeTransactionApi):
    def __init__(self, config: broker.BrokerConfig, behavior: str) -> None:
        super().__init__(config, behavior)
        request = _owner_request()
        request["ruleset_digests"] = broker.validate_hosted_rulesets(
            config=config,
            rulesets=_rulesets(config),
        )
        request["state_commit"] = "f" * 40
        self.owner_request = request
        self.reviews = [
            {
                "body": (
                    broker.OWNER_REQUEST_MARKER
                    + "\n"
                    + broker.canonical_bytes(request).decode().rstrip("\n")
                ),
                "commit_id": HEAD_SHA,
                "id": 301,
                "state": "COMMENTED",
                "submitted_at": "2026-08-26T12:00:00Z",
                "user": {"id": 10, "login": "Miko997"},
            }
        ]
        self.collaborator_inventory_calls = 0
        self.file_inventory_calls = 0
        self.review_change_during_owner_seal = False

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        if "/collaborators?affiliation=all&" in path:
            self.collaborator_inventory_calls += 1
            if self.review_change_during_owner_seal and self.collaborator_inventory_calls == 7:
                self.reviews.append(
                    {
                        "body": "owner request revoked during final context collection",
                        "commit_id": HEAD_SHA,
                        "id": 302,
                        "state": "COMMENTED",
                        "submitted_at": "2026-08-26T12:02:30Z",
                        "user": {"id": 10, "login": "Miko997"},
                    }
                )
            return broker.ApiResult(
                {},
                200,
                [
                    {
                        "id": 10,
                        "login": "Miko997",
                        "permissions": {"admin": True},
                        "role_name": "admin",
                    }
                ],
            )
        if "/invitations?" in path:
            return broker.ApiResult({}, 200, [])
        if "/pulls/81/files?" in path:
            self.file_inventory_calls += 1
            return broker.ApiResult(
                {},
                200,
                [
                    {"filename": "metriplane/fix.py", "status": "modified"},
                    {"filename": "tests/test_fix.py", "status": "modified"},
                ],
            )
        if path.endswith("/collaborators/Miko997/permission"):
            return broker.ApiResult({}, 200, {"permission": "admin"})
        if path.endswith("/pulls/81"):
            value = {**_owner_pull(), "changed_files": 2, "commits": self.reported_commits}
            if self.merged:
                value.update(
                    {
                        "merge_commit_sha": MERGE_SHA,
                        "merged": True,
                        "state": "closed",
                    }
                )
            return broker.ApiResult({}, 200, value)
        return super().request(
            path,
            token=token,
            method=method,
            payload=payload,
            expected=expected,
        )


def test_pull_snapshot_rejects_an_incomplete_provider_commit_inventory(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    api.reported_commits = 2
    with pytest.raises(broker.BrokerError, match="incomplete or inconsistent"):
        broker._pull_snapshot(api, config=config, number=81, token="token")

    api.reported_commits = broker.MAX_PULL_COMMITS + 1
    with pytest.raises(broker.BrokerError, match="exceeds the complete provider"):
        broker._pull_snapshot(api, config=config, number=81, token="token")


def test_ruleset_fetch_rejects_an_extra_active_ruleset_of_any_target(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    api.extra_active_ruleset = True
    with pytest.raises(broker.BrokerError, match="inventory is not the exact governed set"):
        broker._rulesets(api, config=config, token="token")


def test_ruleset_fetch_revalidates_the_main_default_branch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    api.default_branch = "develop"
    with pytest.raises(broker.BrokerError, match="default branch is not canonical"):
        broker._rulesets(api, config=config, token="token")


def test_ruleset_fetch_rejects_inventory_detail_source_disagreement(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    api.inventory_source_drift = True
    with pytest.raises(broker.BrokerError, match="inventory and detail source differ"):
        broker._rulesets(api, config=config, token="token")


class FakeAdmissionState:
    def read(self) -> dict[str, Any]:
        return {
            "generation": 42,
            "last_good_sha": BASE_SHA,
            "state_commit": "f" * 40,
            "status": "green",
            "updated_at": "2026-08-26T12:01:00Z",
        }

    def read_with_result_identities(self) -> tuple[dict[str, Any], set[tuple[str, str]]]:
        return self.read(), {
            (
                "protected-main",
                "github-actions-set:v1:metriplane=501:1;documentation=502:1;security=503:1",
            )
        }

    def read_with_deep_identities(
        self,
    ) -> tuple[dict[str, Any], dict[str, set[tuple[int, int]]]]:
        return self.read(), {"nightly": {(601, 1)}, "weekly": {(602, 1)}}


class FakeRepairState:
    def read(self) -> dict[str, Any]:
        return {
            "generation": 7,
            "incident_digest": "f" * 64,
            "last_good_sha": "0" * 40,
            "state_commit": "f" * 40,
            "status": "red",
            "updated_at": "2026-08-26T12:01:00Z",
        }


class FakeRepairTransactionApi(FakeTransactionApi):
    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        if "/pulls/81/reviews?" in path:
            assert token == "token"
            return broker.ApiResult({}, 200, _repair_reviews())
        return super().request(
            path,
            token=token,
            method=method,
            payload=payload,
            expected=expected,
        )


class FakeAdmissionChecks:
    def __init__(self) -> None:
        self.failed: list[tuple[str, str]] = []
        self.succeeded: list[tuple[int, str, str]] = []

    def ensure_failed(self, *, head_sha: str, reason: str) -> int:
        self.failed.append((head_sha, reason))
        return 42

    def succeed(
        self,
        *,
        check_run_id: int,
        head_sha: str,
        request: dict[str, Any],
        request_digest: str,
        summary: str,
    ) -> dict[str, Any]:
        assert summary
        assert broker.digest(request) == request_digest
        self.succeeded.append((check_run_id, head_sha, request_digest))
        return {}


def _transaction_fixture(
    tmp_path: Path, behavior: str, *, repair: bool = False
) -> tuple[broker.Broker, FakeTransactionApi, FakeAdmissionChecks, broker.DurableSpool]:
    config = _config(tmp_path)
    api = (
        FakeRepairTransactionApi(config, behavior)
        if repair
        else FakeTransactionApi(config, behavior)
    )
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="mhb1:closed:test",
        updated_at="2026-08-26T12:00:00Z",
    )
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=spool,
    )
    return service, api, FakeAdmissionChecks(), spool


@pytest.mark.parametrize("behavior", ["success", "transport-merged", "nonexact-merged"])
def test_exact_merge_transaction_proves_success(tmp_path: Path, behavior: str) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, behavior)
    proof = service._process_pull(
        check_controller=checks,  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
        token="token",
    )
    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_calls == 1
    assert checks.failed == []
    assert len(checks.succeeded) == 1
    assert spool.request_status(broker.digest(_request())) == "merged"


def test_merge_waits_for_provider_readiness_before_final_seal(tmp_path: Path) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")
    sleeps: list[float] = []

    class ReadinessChecks(FakeAdmissionChecks):
        def succeed(self, **kwargs: Any) -> dict[str, Any]:
            result = super().succeed(**kwargs)
            api.mergeable_states = ["unknown", "blocked"]
            return result

    def advance_provider(seconds: float) -> None:
        sleeps.append(seconds)
        api.current_now += timedelta(seconds=seconds)

    service.sleep = advance_provider
    proof = service._process_pull(
        check_controller=ReadinessChecks(),  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
        token="token",
    )

    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_readiness_calls == 2
    assert sleeps == [2.0]
    assert api.merge_calls == 1


def test_provider_readiness_wait_is_bounded_by_request_lease(tmp_path: Path) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")
    api.mergeable_states = ["unknown"] * 31

    def advance_provider(seconds: float) -> None:
        api.current_now += timedelta(seconds=seconds)

    service.sleep = advance_provider
    with pytest.raises(broker.BrokerError, match="did not report.*merge-ready"):
        service._wait_for_provider_merge_ready(
            admission={
                "base_sha": BASE_SHA,
                "head_sha": HEAD_SHA,
                "pull_request": 81,
                "request": _request(),
            },
            token="token",
        )

    assert api.merge_readiness_calls == 31
    assert api.merge_calls == 0


@pytest.mark.parametrize("provider_step_seconds", [0, -1])
def test_provider_readiness_wait_has_independent_attempt_bound(
    tmp_path: Path, provider_step_seconds: int
) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")
    api.mergeable_states = ["unknown"] * broker.MERGE_READINESS_MAX_ATTEMPTS
    sleeps: list[float] = []

    def skew_provider(seconds: float) -> None:
        sleeps.append(seconds)
        api.current_now += timedelta(seconds=provider_step_seconds)

    service.sleep = skew_provider
    with pytest.raises(broker.BrokerError, match="bounded polling"):
        service._wait_for_provider_merge_ready(
            admission={
                "base_sha": BASE_SHA,
                "head_sha": HEAD_SHA,
                "pull_request": 81,
                "request": _request(),
            },
            token="token",
        )

    assert api.merge_readiness_calls == broker.MERGE_READINESS_MAX_ATTEMPTS
    assert len(sleeps) == broker.MERGE_READINESS_MAX_ATTEMPTS - 1
    assert api.merge_calls == 0


def test_provider_readiness_rejects_clean_after_lease_margin(tmp_path: Path) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")
    api.current_now = NOW + timedelta(minutes=3)
    api.mergeable_states = ["clean"]

    with pytest.raises(broker.BrokerError, match="within its lease"):
        service._wait_for_provider_merge_ready(
            admission={
                "base_sha": BASE_SHA,
                "head_sha": HEAD_SHA,
                "pull_request": 81,
                "request": _request(),
            },
            token="token",
        )

    assert api.merge_readiness_calls == 1
    assert api.merge_calls == 0


@pytest.mark.parametrize("mergeable_state", ["blocked", "clean"])
def test_provider_readiness_accepts_governed_mergeable_states(
    mergeable_state: str,
) -> None:
    pull = _pull()
    pull["mergeable_state"] = mergeable_state

    assert broker.Broker._pull_is_merge_ready(
        admission={"base_sha": BASE_SHA, "head_sha": HEAD_SHA, "pull_request": 81},
        pull=pull,
    )


@pytest.mark.parametrize("malformed_number", [81.0, True, "81", 0])
def test_provider_readiness_rejects_noninteger_pull_number(malformed_number: Any) -> None:
    pull = _pull()
    pull["number"] = malformed_number

    with pytest.raises(broker.BrokerError, match="must be a positive integer"):
        broker.Broker._pull_is_merge_ready(
            admission={"base_sha": BASE_SHA, "head_sha": HEAD_SHA, "pull_request": 81},
            pull=pull,
        )


def test_review_change_after_success_publication_blocks_merge(tmp_path: Path) -> None:
    service, api, _checks, spool = _transaction_fixture(tmp_path, "success")

    class DriftingChecks(FakeAdmissionChecks):
        def succeed(self, **kwargs: Any) -> dict[str, Any]:
            result = super().succeed(**kwargs)
            api.reviews[1]["state"] = "DISMISSED"
            return result

    with pytest.raises(broker.BrokerError, match="reviews changed after success publication"):
        service._process_pull(
            check_controller=DriftingChecks(),  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert spool.request_status(broker.digest(_request())) == "merging"


def test_blocked_provider_state_rechecks_app_bypass_after_success(tmp_path: Path) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")

    class DriftingChecks(FakeAdmissionChecks):
        def succeed(self, **kwargs: Any) -> dict[str, Any]:
            result = super().succeed(**kwargs)
            api.drift_update_bypass = True
            api.mergeable_states = ["blocked"]
            return result

    checks = DriftingChecks()
    with pytest.raises(broker.BrokerError, match="governed broker configuration"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert len(checks.succeeded) == 1
    assert api.merge_readiness_calls == 1
    assert api.merge_calls == 0


@pytest.mark.parametrize("drift", ["aggregate", "nightly", "weekly"])
def test_health_attempt_after_success_publication_blocks_merge(tmp_path: Path, drift: str) -> None:
    service, api, _checks, _spool = _transaction_fixture(tmp_path, "success")

    class DriftingChecks(FakeAdmissionChecks):
        def succeed(self, **kwargs: Any) -> dict[str, Any]:
            result = super().succeed(**kwargs)
            if drift == "aggregate":
                api.documentation_run_id = 504
                api.documentation_status = "in_progress"
                api.documentation_conclusion = None
            elif drift == "nightly":
                api.nightly_run_id = 604
                api.nightly_status = "in_progress"
                api.nightly_conclusion = None
            else:
                api.weekly_run_id = 604
                api.weekly_status = "in_progress"
                api.weekly_conclusion = None
            return result

    checks = DriftingChecks()
    with pytest.raises(broker.BrokerError):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert len(checks.succeeded) == 1
    assert api.merge_calls == 0


def test_single_maintainer_owner_request_uses_three_pass_app_transaction(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakeOwnerTransactionApi(config, "success")
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="mhb1:closed:test",
        updated_at="2026-08-26T12:00:00Z",
    )
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=spool,
    )
    checks = FakeAdmissionChecks()

    proof = service._process_pull(
        check_controller=checks,  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
        token="token",
    )

    request_digest = broker.digest(api.owner_request)
    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_calls == 1
    assert api.collaborator_inventory_calls == 10
    assert api.file_inventory_calls == 5
    assert checks.failed == []
    assert checks.succeeded == [(42, HEAD_SHA, request_digest)]
    assert spool.request_status(request_digest) == "merged"


def test_single_maintainer_review_change_during_final_context_blocks_merge(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakeOwnerTransactionApi(config, "success")
    api.review_change_during_owner_seal = True
    spool = broker.DurableSpool(tmp_path / "spool")
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id="mhb1:closed:test",
        updated_at="2026-08-26T12:00:00Z",
    )
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=spool,
    )
    checks = FakeAdmissionChecks()

    with pytest.raises(broker.BrokerError, match="reviews changed during owner admission seal"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_normal_merge_does_not_require_an_unscheduled_current_deep_run(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.include_deep_runs = False

    proof = service._process_pull(
        check_controller=checks,  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
        token="token",
    )

    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_calls == 1


def test_red_incident_uses_same_exact_single_use_merge_transaction(tmp_path: Path) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, "success", repair=True)
    proof = service._process_pull(
        check_controller=checks,  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=FakeRepairState(),  # type: ignore[arg-type]
        token="token",
    )
    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_calls == 1
    assert checks.failed == []
    assert spool.request_status(broker.digest(_repair_request())) == "merged"


def test_provider_consumed_request_blocks_retry_after_spool_restore(tmp_path: Path) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, "success")
    request_digest = broker.digest(_request())
    spool.record_check(
        head_sha=HEAD_SHA,
        check_run_id=42,
        external_id=f"mhb1:consumed:{request_digest}",
        updated_at="2026-08-26T12:02:00Z",
    )
    assert (
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )
        is None
    )
    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_old_retained_state_requires_live_health_instead_of_heartbeat_commits(
    tmp_path: Path,
) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    request = {**_request(), "expires_at": "2026-08-26T12:10:00Z"}
    api.reviews[0]["body"] = _request_body(request)
    api.reviews[1]["body"] = f"{broker.APPROVAL_MARKER} {broker.digest(request)}"

    class BoundaryState(FakeAdmissionState):
        def read(self) -> dict[str, Any]:
            return {**super().read(), "updated_at": "2026-08-26T11:59:00Z"}

    api.current_now = NOW + timedelta(minutes=4, seconds=30)
    proof = service._process_pull(
        check_controller=checks,  # type: ignore[arg-type]
        number=81,
        provider_now=NOW + timedelta(minutes=2),
        settings_token="token",
        state_branch=BoundaryState(),  # type: ignore[arg-type]
        token="token",
    )

    assert proof is not None and proof["merge_sha"] == MERGE_SHA
    assert api.merge_calls == 1
    assert len(checks.succeeded) == 1


def test_approval_expiry_during_final_health_verification_blocks_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, "success")
    verify_current_health = broker.HealthReconciler.verify_current_health

    def expire_approval(
        reconciler: broker.HealthReconciler, provider_now: datetime
    ) -> dict[str, Any]:
        verified_state = verify_current_health(reconciler, provider_now)
        api.current_now = NOW + timedelta(minutes=6)
        return verified_state

    monkeypatch.setattr(broker.HealthReconciler, "verify_current_health", expire_approval)

    with pytest.raises(broker.BrokerError, match="merge request is not currently valid"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []
    assert spool.request_status(broker.digest(_request())) is None


@pytest.mark.parametrize(
    ("replacement_state", "message"),
    [
        ("DISMISSED", "no current independent provider approval"),
        ("CHANGES_REQUESTED", "current requested changes"),
    ],
)
def test_approval_change_during_final_health_verification_blocks_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_state: str,
    message: str,
) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, "success")
    verify_current_health = broker.HealthReconciler.verify_current_health

    def change_approval(
        reconciler: broker.HealthReconciler, provider_now: datetime
    ) -> dict[str, Any]:
        verified_state = verify_current_health(reconciler, provider_now)
        if replacement_state == "DISMISSED":
            api.reviews[1]["state"] = "DISMISSED"
        else:
            api.reviews.append(
                {
                    "body": "approval revoked",
                    "commit_id": HEAD_SHA,
                    "id": 102,
                    "state": "CHANGES_REQUESTED",
                    "submitted_at": "2026-08-26T12:03:00Z",
                    "user": {"id": 40, "login": "reviewer"},
                }
            )
        return verified_state

    monkeypatch.setattr(broker.HealthReconciler, "verify_current_health", change_approval)

    with pytest.raises(broker.BrokerError, match=message):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []
    assert spool.request_status(broker.digest(_request())) is None


@pytest.mark.parametrize("replacement_state", ["DISMISSED", "CHANGES_REQUESTED"])
def test_review_change_during_final_permission_lookup_blocks_merge(
    tmp_path: Path, replacement_state: str
) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, "success")
    api.review_change_on_final_permission = replacement_state

    with pytest.raises(
        broker.BrokerError,
        match="provider reviews changed before the final provider review read",
    ):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.reviewer_permission_calls == 3
    assert api.merge_calls == 0
    assert checks.succeeded == []
    assert spool.request_status(broker.digest(_request())) is None


@pytest.mark.parametrize(
    ("status", "conclusion", "message"),
    [
        ("in_progress", None, "companion workflows are still pending"),
        ("completed", "failure", "aggregate is not successful"),
        ("completed", "success", "does not retain the current aggregate evidence"),
    ],
)
def test_documentation_rerun_blocks_at_the_exact_merge_boundary(
    tmp_path: Path,
    status: str,
    conclusion: str | None,
    message: str,
) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.documentation_run_id = 504
    api.documentation_status = status
    api.documentation_conclusion = conclusion

    with pytest.raises(broker.BrokerError, match=message):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("in_progress", None),
        ("completed", "failure"),
        ("completed", "success"),
    ],
)
def test_deep_health_rerun_blocks_at_the_exact_merge_boundary(
    tmp_path: Path,
    status: str,
    conclusion: str | None,
) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.weekly_run_id = 603
    api.weekly_status = status
    api.weekly_conclusion = conclusion

    with pytest.raises(broker.BrokerError, match="unreconciled weekly deep-health attempt"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [("in_progress", None), ("completed", "failure"), ("completed", "success")],
)
def test_older_deep_health_rerun_cannot_hide_behind_a_later_run(
    tmp_path: Path,
    status: str,
    conclusion: str | None,
) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.older_weekly_rerun = {
        "conclusion": conclusion,
        "display_title": "Main Health Deep / main-health-weekly / main",
        "head_sha": BASE_SHA,
        "id": 600,
        "run_attempt": 2,
        "status": status,
        "updated_at": "2026-08-26T12:01:00Z",
    }

    with pytest.raises(broker.BrokerError, match="unreconciled weekly deep-health attempt"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_deep_rerun_introduced_by_final_ruleset_read_blocks_merge(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.inject_older_rerun_on_final_ruleset = True

    with pytest.raises(broker.BrokerError, match="unreconciled weekly deep-health attempt"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.ruleset_inventory_calls == 2
    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_rulesets_are_rechecked_immediately_before_success(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.drift_on_final_ruleset = True

    with pytest.raises(broker.BrokerError, match="inventory is not the exact governed set"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.ruleset_inventory_calls == 2
    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_release_tag_ruleset_identity_drift_between_reads_blocks_merge(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.drift_tag_identity_on_final_ruleset = True

    with pytest.raises(broker.BrokerError, match="wrong provider ID"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.ruleset_inventory_calls == 2
    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_release_tag_ruleset_semantic_drift_between_reads_blocks_merge(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.drift_tag_semantics_on_final_ruleset = True

    with pytest.raises(broker.BrokerError, match="not the governed"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.ruleset_inventory_calls == 2
    assert api.merge_calls == 0
    assert checks.succeeded == []


def test_default_branch_is_rechecked_immediately_before_success(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")
    api.drift_default_on_final = True

    with pytest.raises(broker.BrokerError, match="default branch is not canonical"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )

    assert api.repository_identity_calls == 2
    assert api.merge_calls == 0
    assert checks.succeeded == []


def _merged_repair_pull() -> dict[str, Any]:
    return {
        **_pull(),
        "merge_commit_sha": MERGE_SHA,
        "merged": True,
        "merged_at": "2026-08-26T12:03:00Z",
        "state": "closed",
    }


def test_merged_repair_binding_retains_bounded_provider_request() -> None:
    binding = broker._merged_repair_binding(
        commits=_commits(),
        now=NOW + timedelta(minutes=4),
        pull=_merged_repair_pull(),
        repository=REPOSITORY,
        reviewer_permissions={"reviewer": "write"},
        reviews=_repair_reviews(),
        state={"generation": 10, "incident_digest": "f" * 64, "status": "red"},
    )
    assert binding["approval_review_id"] == 201
    assert binding["request_digest"] == broker.digest(_repair_request())

    expired = _merged_repair_pull()
    expired["merged_at"] = "2026-08-26T12:06:00Z"
    with pytest.raises(broker.BrokerError, match="not provider- and incident-bound"):
        broker._merged_repair_binding(
            commits=_commits(),
            now=NOW + timedelta(minutes=7),
            pull=expired,
            repository=REPOSITORY,
            reviewer_permissions={"reviewer": "write"},
            reviews=_repair_reviews(),
            state={"generation": 10, "incident_digest": "f" * 64, "status": "red"},
        )


def test_merged_repair_binding_reapplies_independent_actor_policy() -> None:
    reviews = _repair_reviews()
    reviews.append(
        {
            "body": "Main-health repair authorization: MET-77\nIncident: " + "f" * 64,
            "commit_id": HEAD_SHA,
            "id": 202,
            "state": "APPROVED",
            "submitted_at": "2026-08-26T12:02:00Z",
            "user": {"id": 30, "login": "commit-author"},
        }
    )
    binding = broker._merged_repair_binding(
        commits=_commits(),
        now=NOW + timedelta(minutes=4),
        pull=_merged_repair_pull(),
        repository=REPOSITORY,
        reviewer_permissions={"commit-author": "write", "reviewer": "write"},
        reviews=reviews,
        state={"generation": 10, "incident_digest": "f" * 64, "status": "red"},
    )
    assert binding["approval_review_id"] == 201

    reviews[1]["user"] = {"id": 30, "login": "commit-author"}
    with pytest.raises(broker.BrokerError, match="independent approval"):
        broker._merged_repair_binding(
            commits=_commits(),
            now=NOW + timedelta(minutes=4),
            pull=_merged_repair_pull(),
            repository=REPOSITORY,
            reviewer_permissions={"commit-author": "write"},
            reviews=reviews[:2],
            state={"generation": 10, "incident_digest": "f" * 64, "status": "red"},
        )


def test_merged_owner_repair_binding_rejects_request_outliving_manifest() -> None:
    policy_amendment = {"schema_version": 1}
    manifest = {
        "expires_at": "2026-08-26T12:10:00Z",
        "policy_amendment": policy_amendment,
    }
    context = {
        "changed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "collaborators": [{"id": "10", "login": "Miko997", "permission": "admin"}],
        "manifest": manifest,
        "owner_id": 10,
        "owner_login": "Miko997",
        "pending_invitations": [],
        "ruleset_digests": _owner_ruleset_digests(),
    }
    request = _owner_request(repair=True)
    request["manifest_digest"] = broker.digest(manifest)
    request["policy_amendment_digest"] = broker.digest(policy_amendment)
    review = {
        **_owner_reviews(repair=True)[0],
        "body": (
            broker.OWNER_REPAIR_REQUEST_MARKER
            + "\n"
            + broker.canonical_bytes(request).decode().rstrip("\n")
        ),
    }
    pull = {**_merged_repair_pull(), "user": {"id": 10, "login": "Miko997"}}
    state = {"generation": 10, "incident_digest": "f" * 64, "status": "red"}

    binding = broker._merged_owner_repair_binding(
        commits=_commits(),
        context=context,
        now=NOW + timedelta(minutes=4),
        pull=pull,
        repository=REPOSITORY,
        reviews=[review],
        state=state,
    )
    assert binding["request_digest"] == broker.digest(request)

    manifest["expires_at"] = "2026-08-26T12:04:00Z"
    request["manifest_digest"] = broker.digest(manifest)
    review["body"] = (
        broker.OWNER_REPAIR_REQUEST_MARKER
        + "\n"
        + broker.canonical_bytes(request).decode().rstrip("\n")
    )
    with pytest.raises(broker.BrokerError, match="not provider- and incident-bound"):
        broker._merged_owner_repair_binding(
            commits=_commits(),
            context=context,
            now=NOW + timedelta(minutes=4),
            pull=pull,
            repository=REPOSITORY,
            reviews=[review],
            state=state,
        )


def test_merged_owner_repair_binding_ignores_prior_head_requests() -> None:
    policy_amendment = {"schema_version": 1}
    manifest = {
        "expires_at": "2026-08-26T12:10:00Z",
        "policy_amendment": policy_amendment,
    }
    context = {
        "changed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "collaborators": [{"id": "10", "login": "Miko997", "permission": "admin"}],
        "manifest": manifest,
        "owner_id": 10,
        "owner_login": "Miko997",
        "pending_invitations": [],
        "ruleset_digests": _owner_ruleset_digests(),
    }
    current_request = _owner_request(repair=True)
    current_request["manifest_digest"] = broker.digest(manifest)
    current_request["policy_amendment_digest"] = broker.digest(policy_amendment)
    current_review = {
        **_owner_reviews(repair=True)[0],
        "body": broker.OWNER_REPAIR_REQUEST_MARKER
        + "\n"
        + broker.canonical_bytes(current_request).decode().rstrip("\n"),
    }
    prior_head = "e" * 40
    prior_request = {**current_request, "head_sha": prior_head}
    prior_review = {
        **current_review,
        "body": broker.OWNER_REPAIR_REQUEST_MARKER
        + "\n"
        + broker.canonical_bytes(prior_request).decode().rstrip("\n"),
        "commit_id": prior_head,
        "id": 300,
    }
    pull = {**_merged_repair_pull(), "user": {"id": 10, "login": "Miko997"}}
    state = {"generation": 10, "incident_digest": "f" * 64, "status": "red"}

    binding = broker._merged_owner_repair_binding(
        commits=_commits(),
        context=context,
        now=NOW + timedelta(minutes=4),
        pull=pull,
        repository=REPOSITORY,
        reviews=[prior_review, current_review],
        state=state,
    )
    assert binding["request_review_id"] == 301
    assert binding["request_digest"] == broker.digest(current_request)

    with pytest.raises(broker.BrokerError, match="no retained owner request"):
        broker._merged_owner_repair_binding(
            commits=_commits(),
            context=context,
            now=NOW + timedelta(minutes=4),
            pull=pull,
            repository=REPOSITORY,
            reviews=[prior_review],
            state=state,
        )

    malformed_review = {**prior_review, "commit_id": 81.0}
    with pytest.raises(broker.BrokerError, match="merged owner request review commit SHA"):
        broker._merged_owner_repair_binding(
            commits=_commits(),
            context=context,
            now=NOW + timedelta(minutes=4),
            pull=pull,
            repository=REPOSITORY,
            reviews=[malformed_review, current_review],
            state=state,
        )


class FakeRepairResolutionApi(FakeProofApi):
    def provider_now(self, token: str) -> datetime:
        assert token == "token"
        return NOW + timedelta(minutes=10)

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        if "/collaborators/reviewer/permission" in path:
            return broker.ApiResult({}, 200, {"permission": "write"})
        if "/pulls?state=closed" in path:
            return broker.ApiResult(
                {},
                200,
                [
                    {"merge_commit_sha": MERGE_SHA, "number": 80},
                    {"merge_commit_sha": MERGE_SHA, "number": 81},
                ],
            )
        if "/pulls/80/reviews?" in path:
            return broker.ApiResult({}, 200, [])
        if "/pulls/80/commits?" in path:
            return broker.ApiResult({}, 200, _commits())
        if path.endswith("/pulls/80"):
            pull = _merged_repair_pull()
            pull["number"] = 80
            return broker.ApiResult({}, 200, pull)
        if "/pulls/81/reviews?" in path:
            return broker.ApiResult({}, 200, _repair_reviews())
        if "/pulls/81/commits?" in path:
            return broker.ApiResult({}, 200, _commits())
        if path.endswith("/pulls/81"):
            return broker.ApiResult({}, 200, _merged_repair_pull())
        return super().request(
            path,
            token=token,
            method=method,
            payload=payload,
            expected=expected,
        )


class FakeOwnerRepairResolutionApi(FakeRepairResolutionApi):
    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        if "/pulls/81/reviews?" in path:
            return broker.ApiResult({}, 200, _owner_reviews(repair=True))
        return super().request(
            path,
            token=token,
            method=method,
            payload=payload,
            expected=expected,
        )


class FakeRepairResolutionState:
    def __init__(self) -> None:
        self.resolution: dict[str, Any] | None = None
        self.repaired_main = {
            "cadence": "protected-main",
            "conclusion": "success",
            "obligations": [{"id": "suite", "result": "success"}],
            "recorded_at": "2026-08-26T12:10:00Z",
            "run_id": "github-actions:300:1",
            "schema_version": 1,
            "sha": MERGE_SHA,
        }

    def repair_context(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
        state = {
            "generation": 10,
            "incident_digest": "f" * 64,
            "state_commit": "1" * 40,
            "status": "red",
        }
        incident = {"failing_obligations": ["suite"]}
        passing = {
            (MERGE_SHA, "protected-main"): self.repaired_main,
            (MERGE_SHA, "nightly"): {"cadence": "nightly"},
            (MERGE_SHA, "weekly"): {"cadence": "weekly"},
        }
        return state, incident, passing

    def resolve_repair(self, **values: Any) -> dict[str, Any]:
        self.resolution = values
        return {"generation": 11, "status": "green"}


def _owner_resolution_binding() -> dict[str, Any]:
    request = _owner_request(repair=True)
    return {
        "approval_review_id": 301,
        "authorization_mode": broker.OWNER_EMERGENCY_MODE,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "incident_digest": "f" * 64,
        "issue": "MET-77",
        "pull_request": 81,
        "request": request,
        "request_digest": broker.digest(request),
        "request_review_id": 301,
        "review": _owner_reviews(repair=True)[0],
    }


def _owner_resolution_evidence(*, captured_at: str) -> dict[str, Any]:
    return {
        "authorization_mode": broker.OWNER_EMERGENCY_MODE,
        "approval_id": "301",
        "approval_provider": "github-app-broker",
        "author": "Miko997",
        "author_id": "10",
        "captured_at": captured_at,
        "changed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "head_sha": HEAD_SHA,
        "incident_digest": "f" * 64,
        "issue": "MET-77",
        "manifest": {
            "expires_at": "2026-08-26T12:20:00Z",
            "policy_amendment": {"schema_version": 1},
        },
        "merge_commit_sha": MERGE_SHA,
        "pull_request": "81",
        "reviewer": "Miko997",
        "reviewer_id": "10",
        "reviewer_permission": "admin",
    }


def test_repair_resolution_is_rebuilt_from_provider_and_protected_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = {
        "authorization_mode": "independent-review",
        "approval_id": "201",
        "approval_provider": "github",
        "author": "author",
        "author_id": "10",
        "changed_paths": ["metriplane/fix.py", "tests/test_fix.py"],
        "head_sha": HEAD_SHA,
        "incident_digest": "f" * 64,
        "merge_commit_sha": MERGE_SHA,
        "pull_request": "81",
        "reviewer": "reviewer",
        "reviewer_id": "40",
        "reviewer_permission": "write",
    }

    def capture(**_values: Any) -> dict[str, Any]:
        return dict(evidence)

    monkeypatch.setattr(broker.stop_the_line, "capture_github_approval", capture)
    config = _config(tmp_path)
    api = FakeRepairResolutionApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    state_branch = FakeRepairResolutionState()
    assert service._reconcile_repair(
        state_branch=state_branch,  # type: ignore[arg-type]
        token="token",
    ) == {"generation": 11, "status": "green"}
    assert state_branch.resolution is not None
    authorization = state_branch.resolution["authorization"]
    assert authorization["approval_digest"] == broker.digest(evidence)
    assert authorization["allowed_paths"] == evidence["changed_paths"]
    assert authorization["required_cadences"] == ["nightly", "weekly"]
    assert state_branch.resolution["repaired_main"] == state_branch.repaired_main


def test_owner_repair_resolution_uses_two_complete_provider_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _owner_resolution_binding()
    evidence = _owner_resolution_evidence(captured_at="2026-08-26T12:10:00Z")
    capture_calls: list[int] = []

    monkeypatch.setattr(
        broker,
        "_owner_repair_evidence_context",
        lambda *_args, **_kwargs: {"captured": True},
    )
    monkeypatch.setattr(
        broker,
        "_merged_owner_repair_binding",
        lambda **_kwargs: copy.deepcopy(binding),
    )

    def capture(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        capture_calls.append(len(capture_calls) + 1)
        captured = copy.deepcopy(evidence)
        captured["captured_at"] = f"2026-08-26T12:1{len(capture_calls) - 1}:00Z"
        return copy.deepcopy(binding), captured

    monkeypatch.setattr(broker, "_capture_app_owner_repair_evidence", capture)
    config = _config(tmp_path)
    api = FakeOwnerRepairResolutionApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    state_branch = FakeRepairResolutionState()

    assert service._reconcile_repair(
        state_branch=state_branch,  # type: ignore[arg-type]
        token="token",
        settings_token="settings-token",
    ) == {"generation": 11, "status": "green"}
    assert capture_calls == [1, 2]
    assert state_branch.resolution is not None
    assert state_branch.resolution["approval_evidence"]["captured_at"] == ("2026-08-26T12:11:00Z")


def test_owner_repair_resolution_rejects_second_provider_capture_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _owner_resolution_binding()
    evidence = _owner_resolution_evidence(captured_at="2026-08-26T12:10:00Z")
    capture_calls = 0

    monkeypatch.setattr(
        broker,
        "_owner_repair_evidence_context",
        lambda *_args, **_kwargs: {"captured": True},
    )
    monkeypatch.setattr(
        broker,
        "_merged_owner_repair_binding",
        lambda **_kwargs: copy.deepcopy(binding),
    )

    def capture(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal capture_calls
        capture_calls += 1
        captured = copy.deepcopy(evidence)
        captured["captured_at"] = f"2026-08-26T12:1{capture_calls - 1}:00Z"
        if capture_calls == 2:
            captured["reviewer"] = "changed-owner"
        return copy.deepcopy(binding), captured

    monkeypatch.setattr(broker, "_capture_app_owner_repair_evidence", capture)
    config = _config(tmp_path)
    api = FakeOwnerRepairResolutionApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    state_branch = FakeRepairResolutionState()

    with pytest.raises(broker.BrokerError, match="provider evidence changed during final capture"):
        service._reconcile_repair(
            state_branch=state_branch,  # type: ignore[arg-type]
            token="token",
            settings_token="settings-token",
        )
    assert capture_calls == 2
    assert state_branch.resolution is None


def test_repair_resolution_waits_when_current_main_has_no_governed_merge(
    tmp_path: Path,
) -> None:
    class UngovernedRepairApi(FakeRepairResolutionApi):
        def request(
            self,
            path: str,
            *,
            token: str,
            method: str = "GET",
            payload: dict[str, Any] | None = None,
            expected: tuple[int, ...] = (200,),
        ) -> broker.ApiResult:
            if "/pulls/81/reviews?" in path:
                return broker.ApiResult({}, 200, [])
            return super().request(
                path,
                token=token,
                method=method,
                payload=payload,
                expected=expected,
            )

    config = _config(tmp_path)
    api = UngovernedRepairApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    state_branch = FakeRepairResolutionState()

    state = service._reconcile_repair(
        state_branch=state_branch,  # type: ignore[arg-type]
        token="token",
    )

    assert state["status"] == "red"
    assert state["generation"] == 10
    assert state_branch.resolution is None


def test_repair_resolution_rejects_multiple_governed_merges(tmp_path: Path) -> None:
    class DuplicateGovernedRepairApi(FakeRepairResolutionApi):
        def request(
            self,
            path: str,
            *,
            token: str,
            method: str = "GET",
            payload: dict[str, Any] | None = None,
            expected: tuple[int, ...] = (200,),
        ) -> broker.ApiResult:
            if "/pulls/80/reviews?" in path:
                return broker.ApiResult({}, 200, _repair_reviews_for(80))
            return super().request(
                path,
                token=token,
                method=method,
                payload=payload,
                expected=expected,
            )

    config = _config(tmp_path)
    api = DuplicateGovernedRepairApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
    )

    with pytest.raises(broker.BrokerError, match="multiple governed provider pull requests"):
        service._reconcile_repair(
            state_branch=FakeRepairResolutionState(),  # type: ignore[arg-type]
            token="token",
        )


@pytest.mark.parametrize(
    ("behavior", "status", "message"),
    [
        ("transport-open", "uncertain", "ambiguous"),
        ("nonexact-open", "uncertain", "ambiguous"),
        ("reject", "rejected", "rejected"),
        ("bad-proof", "uncertain", "tree differs"),
    ],
)
def test_failed_merge_transaction_closes_check_and_never_retries(
    tmp_path: Path, behavior: str, status: str, message: str
) -> None:
    service, api, checks, spool = _transaction_fixture(tmp_path, behavior)
    with pytest.raises(broker.BrokerError, match=message):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
            token="token",
        )
    assert api.merge_calls == 1
    assert len(checks.failed) == 1
    assert spool.request_status(broker.digest(_request())) == status
    if not api.merged:
        assert (
            service._process_pull(
                check_controller=checks,  # type: ignore[arg-type]
                number=81,
                provider_now=NOW + timedelta(minutes=2),
                settings_token="token",
                state_branch=FakeAdmissionState(),  # type: ignore[arg-type]
                token="token",
            )
            is None
        )
        assert api.merge_calls == 1


def test_restart_reconciles_orphaned_merge_without_retry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    spool = broker.DurableSpool(tmp_path / "spool")
    request = _request()
    request_digest = broker.digest(request)
    spool.record_request(
        request_digest=request_digest,
        nonce=request["nonce"],
        pull_request=request["pull_request"],
        request=request,
        status="merging",
        updated_at="2026-08-26T12:00:00Z",
    )
    api = FakeProofApi()
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=spool,
    )
    proofs = service._reconcile_orphans("token")
    assert proofs == [
        {
            "base_sha": BASE_SHA,
            "head_sha": HEAD_SHA,
            "head_tree_sha": TREE_SHA,
            "merge_sha": MERGE_SHA,
            "request_digest": request_digest,
            "schema_version": 1,
        }
    ]
    assert spool.request_status(request_digest) == "merged"
    calls = list(api.calls)
    assert service._reconcile_orphans("token") == []
    assert api.calls == calls


def test_restart_quarantines_unproven_orphan_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    spool = broker.DurableSpool(tmp_path / "spool")
    request = _request()
    request_digest = broker.digest(request)
    spool.record_request(
        request_digest=request_digest,
        nonce=request["nonce"],
        pull_request=request["pull_request"],
        request=request,
        status="merging",
        updated_at="2026-08-26T12:00:00Z",
    )
    api = FakeProofApi()
    api.tree_sha = "e" * 40
    service = broker.Broker(
        api=api,
        authenticator=broker.AppAuthenticator(api, config),
        config=config,
        spool=spool,
    )
    closed: list[tuple[str, str]] = []

    def close_check(_controller: broker.CheckController, *, head_sha: str, reason: str) -> int:
        closed.append((head_sha, reason))
        return 42

    monkeypatch.setattr(broker.CheckController, "ensure_failed", close_check)
    assert service._reconcile_orphans("token") == []
    assert spool.request_status(request_digest) == "uncertain"
    assert closed == [(HEAD_SHA, "Interrupted merge could not be proved and is quarantined.")]
    calls = list(api.calls)
    assert service._reconcile_orphans("token") == []
    assert api.calls == calls


def test_provider_clock_skew_fails_closed() -> None:
    broker.validate_clock(
        local_now=NOW,
        provider_now=NOW + timedelta(seconds=30),
        max_clock_skew_seconds=30,
    )
    with pytest.raises(broker.BrokerError, match="clock skew"):
        broker.validate_clock(
            local_now=NOW,
            provider_now=NOW + timedelta(seconds=31),
            max_clock_skew_seconds=30,
        )


class FakeDeepApi(broker.GitHubApi):
    def __init__(self) -> None:
        super().__init__()
        self.runs = [
            {
                "conclusion": "success",
                "display_title": "Main Health Deep / main-health-nightly / main",
                "head_sha": BASE_SHA,
                "id": 10,
                "run_attempt": 1,
                "status": "completed",
                "updated_at": "2026-08-26T11:50:00Z",
            },
            {
                "conclusion": "success",
                "display_title": "Main Health Deep / 23 3 * * 0 / main",
                "head_sha": BASE_SHA,
                "id": 11,
                "run_attempt": 1,
                "status": "completed",
                "updated_at": "2026-08-26T11:51:00Z",
            },
        ]

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token == "token"
        if path.endswith("/git/ref/heads/main"):
            return broker.ApiResult(
                {},
                200,
                {"object": {"sha": BASE_SHA, "type": "commit"}, "ref": "refs/heads/main"},
            )
        if "/actions/runs/" in path and "/attempts/" in path:
            run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
            run_attempt = int(path.rsplit("/", 1)[1])
            value = next(item for item in self.runs if item["id"] == run_id)
            return broker.ApiResult({}, 200, {**value, "run_attempt": run_attempt})
        raise AssertionError(path)

    def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
        assert token == "token"
        if "actions/workflows/main-health.yml/runs" in path:
            assert key == "workflow_runs"
            return [dict(item) for item in self.runs]
        assert key == "jobs"
        run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
        run_attempt = int(path.split("/attempts/", 1)[1].split("/", 1)[0])
        cadence = "nightly" if run_id in {10, 12} else "weekly"
        return [
            {
                "conclusion": "success",
                "head_sha": BASE_SHA,
                "id": 1_000 + run_id,
                "name": f"Main health deep / {cadence}",
                "run_attempt": run_attempt,
                "run_id": run_id,
                "status": "completed",
            }
        ]


class FakeStateBranch:
    def __init__(self, *, deep_identities: dict[str, set[tuple[int, int]]] | None = None) -> None:
        self.state = {
            "generation": 5,
            "last_good_sha": BASE_SHA,
            "state_commit": "f" * 40,
            "status": "green",
            "updated_at": "2026-08-26T11:59:00Z",
        }
        self.appends: list[tuple[str, dict[str, Any]]] = []
        source = deep_identities or {"nightly": set(), "weekly": set()}
        self.deep_identities = {cadence: set(values) for cadence, values in source.items()}
        self.result_identities = {
            (cadence, f"github-actions:{identity[0]}:{identity[1]}")
            for cadence, identities in self.deep_identities.items()
            for identity in identities
        }

    def read(self) -> dict[str, Any]:
        return dict(self.state)

    def read_with_deep_identities(
        self,
    ) -> tuple[dict[str, Any], dict[str, set[tuple[int, int]]]]:
        return dict(self.state), {
            cadence: set(values) for cadence, values in self.deep_identities.items()
        }

    def read_with_result_identities(
        self,
    ) -> tuple[dict[str, Any], set[tuple[str, str]]]:
        return dict(self.state), set(self.result_identities)

    def append(
        self,
        *,
        expected_generation: int,
        scope: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        assert expected_generation == self.state["generation"]
        self.appends.append((scope, summary))
        self.state["generation"] += 1
        self.state["updated_at"] = summary["recorded_at"]
        cadence = "protected-main" if scope == "main" else scope
        if cadence == "protected-main":
            result_identity = broker._protected_main_result_identity(summary["run_id"])
            self.result_identities.add((cadence, result_identity))
        else:
            identity = broker._deep_result_identity(summary["run_id"])
            self.result_identities.add((cadence, f"github-actions:{identity[0]}:{identity[1]}"))
        if scope in self.deep_identities:
            self.deep_identities[scope].add(identity)
        return dict(self.state)


def test_protected_state_rejects_duplicate_aggregate_identity(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    run_id = "github-actions-set:v1:metriplane=501:1;documentation=502:1;security=503:1"
    first = {"cadence": "protected-main", "recorded_at": "first", "run_id": run_id}
    second = {"cadence": "protected-main", "recorded_at": "second", "run_id": run_id}
    (results / "first.json").write_text(json.dumps(first), encoding="utf-8")
    (results / "second.json").write_text(json.dumps(second), encoding="utf-8")

    with pytest.raises(broker.BrokerError, match="repeats a result identity"):
        broker.StateBranch._result_identities(tmp_path)


def test_protected_state_rejects_duplicate_attempt_qualified_identity(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    run_id = "github-actions:501:1"
    first = {"cadence": "protected-main", "recorded_at": "first", "run_id": run_id}
    second = {"cadence": "protected-main", "recorded_at": "second", "run_id": run_id}
    (results / "first.json").write_bytes(broker.canonical_bytes(first))
    (results / "second.json").write_bytes(broker.canonical_bytes(second))

    with pytest.raises(broker.BrokerError, match="repeats a result identity"):
        broker.StateBranch._result_identities(tmp_path)


def _legacy_protected_main_rerun_results() -> list[dict[str, Any]]:
    return [
        {
            "cadence": "protected-main",
            "conclusion": "failure",
            "obligations": [
                {"id": "Metriplane / required", "result": "failure"},
                {"id": "Documentation / required", "result": "success"},
                {"id": "Security / required", "result": "success"},
            ],
            "recorded_at": "2026-08-25T20:15:34Z",
            "run_id": "32893499507",
            "schema_version": 1,
            "sha": "9d5b4ffa5236521423196a84acc6a613f7f13108",
        },
        {
            "cadence": "protected-main",
            "conclusion": "success",
            "obligations": [
                {"id": "Metriplane / required", "result": "success"},
                {"id": "Documentation / required", "result": "success"},
                {"id": "Security / required", "result": "success"},
            ],
            "recorded_at": "2026-08-25T20:21:53Z",
            "run_id": "32893499507",
            "schema_version": 1,
            "sha": "9d5b4ffa5236521423196a84acc6a613f7f13108",
        },
    ]


def test_protected_state_preserves_digest_bound_legacy_rerun_results(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    legacy = _legacy_protected_main_rerun_results()
    digests = {broker.digest(result) for result in legacy}
    assert digests == {
        "83da378f0d804e10480282b49c1dada4573cfc6ead2ea9810de7c5d8057d4f7f",
        "f0eb90f3ff235434304b71ffe1b4b52606537734453f0211063601424dc4c976",
    }
    for result in legacy:
        result_digest = broker.digest(result)
        (results / f"{result_digest}.json").write_bytes(broker.canonical_bytes(result))

    identities = broker.StateBranch._result_identities(tmp_path)

    assert identities == {
        (
            "protected-main",
            f"legacy-result:32893499507:{result_digest}",
        )
        for result_digest in digests
    }


@pytest.mark.parametrize("run_id", ["32893499507", "99999999999"])
def test_protected_state_rejects_unapproved_legacy_result(tmp_path: Path, run_id: str) -> None:
    results = tmp_path / "results"
    results.mkdir()
    result = {
        "cadence": "protected-main",
        "conclusion": "success",
        "recorded_at": "2026-08-25T20:22:00Z",
        "run_id": run_id,
    }
    result_digest = broker.digest(result)
    (results / f"{result_digest}.json").write_bytes(broker.canonical_bytes(result))

    with pytest.raises(
        broker.BrokerError, match="legacy protected-main result is not an approved immutable record"
    ):
        broker.StateBranch._result_identities(tmp_path)


def test_protected_state_rejects_unbound_legacy_result_filename(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    result = {
        "cadence": "protected-main",
        "conclusion": "success",
        "recorded_at": "2026-08-25T20:21:53Z",
        "run_id": "32893499507",
    }
    (results / "wrong.json").write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(
        broker.BrokerError, match="legacy protected-main result is not digest-bound"
    ):
        broker.StateBranch._result_identities(tmp_path)


class SequenceStateRefApi(broker.GitHubApi):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__()
        self.responses = iter(responses)
        self.observed: list[Any] = []

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert path == f"repos/{REPOSITORY}/git/ref/heads/metriplane-main-health-state"
        assert token == "token"
        assert method == "GET"
        assert payload is None
        assert expected == (200,)
        response = next(self.responses)
        self.observed.append(response)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, str):
            response = {
                "object": {"sha": response, "type": "commit"},
                "ref": "refs/heads/metriplane-main-health-state",
                "url": (
                    f"https://api.github.com/repos/{REPOSITORY}/git/refs/heads/"
                    "metriplane-main-health-state"
                ),
            }
            response["object"]["url"] = (
                f"https://api.github.com/repos/{REPOSITORY}/git/commits/{response['object']['sha']}"
            )
        return broker.ApiResult({}, 200, response)


def _state_branch_for_convergence(
    tmp_path: Path,
    *,
    api: broker.GitHubApi,
    monotonic: Callable[[], float] = lambda: 0.0,
    sleep: Callable[[float], None] = lambda _seconds: None,
) -> broker.StateBranch:
    return broker.StateBranch(
        api=api,
        config=_config(tmp_path),
        monotonic=monotonic,
        sleep=sleep,
        token="token",
    )


@pytest.mark.parametrize("run_id", ["32893499507", "github-actions:501:1"])
def test_state_branch_rejects_new_nonaggregate_protected_main_result(
    tmp_path: Path, run_id: str
) -> None:
    class NoProviderApi(broker.GitHubApi):
        def request(self, *_args: Any, **_kwargs: Any) -> broker.ApiResult:
            raise AssertionError("provider must not be called for a rejected result identity")

    state = broker.StateBranch(api=NoProviderApi(), config=_config(tmp_path), token="token")

    with pytest.raises(broker.BrokerError, match="must use an aggregate identity"):
        state.append(
            expected_generation=7,
            scope="main",
            summary={"run_id": run_id},
        )


def test_state_ref_convergence_accepts_immediate_expected_commit(tmp_path: Path) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([expected_commit])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    state._await_state_ref_convergence(
        expected_state_commit=expected_commit,
        operation="state branch push",
        previous_state_commit=previous_commit,
    )

    assert api.observed == [expected_commit]
    assert sleeps == []


def test_state_ref_convergence_accepts_several_stale_reads_within_bound(
    tmp_path: Path,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([previous_commit, previous_commit, previous_commit, expected_commit])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    state._await_state_ref_convergence(
        expected_state_commit=expected_commit,
        operation="state branch push",
        previous_state_commit=previous_commit,
    )

    assert api.observed == [previous_commit, previous_commit, previous_commit, expected_commit]
    assert sleeps == [1.0, 1.0, 1.0]


def test_state_ref_convergence_accepts_expected_commit_on_final_bounded_read(
    tmp_path: Path,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi(
        [previous_commit] * (broker.STATE_REF_CONVERGENCE_MAX_READS - 1) + [expected_commit]
    )
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    state._await_state_ref_convergence(
        expected_state_commit=expected_commit,
        operation="state branch push",
        previous_state_commit=previous_commit,
    )

    assert api.observed == [previous_commit] * (broker.STATE_REF_CONVERGENCE_MAX_READS - 1) + [
        expected_commit
    ]
    assert sleeps == [1.0] * (broker.STATE_REF_CONVERGENCE_MAX_READS - 1)


def test_state_ref_convergence_fails_closed_when_previous_commit_never_advances(
    tmp_path: Path,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([previous_commit] * broker.STATE_REF_CONVERGENCE_MAX_READS)
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.BrokerError) as exc_info:
        state._await_state_ref_convergence(
            expected_state_commit=expected_commit,
            operation="state branch push",
            previous_state_commit=previous_commit,
        )

    assert str(exc_info.value) == (
        "state branch push was not read back exactly: "
        f"expected new SHA {expected_commit}; last observed SHA {previous_commit}; "
        f"timeout {broker.STATE_REF_CONVERGENCE_TIMEOUT_SECONDS}s; "
        f"reads {broker.STATE_REF_CONVERGENCE_MAX_READS}"
    )
    assert api.observed == [previous_commit] * broker.STATE_REF_CONVERGENCE_MAX_READS
    assert sleeps == [1.0] * (broker.STATE_REF_CONVERGENCE_MAX_READS - 1)


def test_state_ref_convergence_obeys_elapsed_deadline(tmp_path: Path) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([previous_commit])
    clock = iter([0.0, float(broker.STATE_REF_CONVERGENCE_TIMEOUT_SECONDS)])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(
        tmp_path,
        api=api,
        monotonic=lambda: next(clock),
        sleep=sleeps.append,
    )

    with pytest.raises(broker.BrokerError, match=r"timeout 10s; reads 1$"):
        state._await_state_ref_convergence(
            expected_state_commit=expected_commit,
            operation="state branch push",
            previous_state_commit=previous_commit,
        )

    assert api.observed == [previous_commit]
    assert sleeps == []


def test_state_ref_convergence_rejects_unrelated_commit_immediately(tmp_path: Path) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    unrelated_commit = "3" * 40
    api = SequenceStateRefApi([unrelated_commit, expected_commit])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.BrokerError) as exc_info:
        state._await_state_ref_convergence(
            expected_state_commit=expected_commit,
            operation="state branch push",
            previous_state_commit=previous_commit,
        )

    assert str(exc_info.value) == (
        "state branch push observed concurrent/provider state drift: "
        f"expected new SHA {expected_commit}; previous SHA {previous_commit}; "
        f"observed SHA {unrelated_commit}; reads 1"
    )
    assert api.observed == [unrelated_commit]
    assert sleeps == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (None, "state-branch ref response is malformed"),
        ({"object": {"sha": "2" * 40, "type": "commit"}}, "not provider-bound"),
        (
            {
                "object": {"sha": "2" * 40, "type": "commit"},
                "ref": "refs/heads/wrong-state-branch",
            },
            "not provider-bound",
        ),
        (
            {
                "object": {"sha": "2" * 40, "type": "tag"},
                "ref": "refs/heads/metriplane-main-health-state",
            },
            "not provider-bound",
        ),
        (
            {
                "object": {"sha": 2, "type": "commit"},
                "ref": "refs/heads/metriplane-main-health-state",
            },
            "is not a lowercase 40-hex SHA",
        ),
    ],
)
def test_state_ref_convergence_rejects_malformed_or_unbound_provider_response(
    tmp_path: Path, response: Any, message: str
) -> None:
    api = SequenceStateRefApi([response])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.BrokerError, match=message):
        state._await_state_ref_convergence(
            expected_state_commit="2" * 40,
            operation="state branch push",
            previous_state_commit="1" * 40,
        )

    assert api.observed == [response]
    assert sleeps == []


def test_state_ref_convergence_does_not_retry_transport_or_provider_errors(
    tmp_path: Path,
) -> None:
    error = broker.ProviderTransportError("ref read transport failed")
    api = SequenceStateRefApi([error, "2" * 40])
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.ProviderTransportError, match="ref read transport failed"):
        state._await_state_ref_convergence(
            expected_state_commit="2" * 40,
            operation="state branch push",
            previous_state_commit="1" * 40,
        )

    assert api.observed == [error]
    assert sleeps == []


def _install_state_write_git_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_commit: str,
    previous_commit: str,
) -> list[tuple[str, ...]]:
    push_calls: list[tuple[str, ...]] = []

    def git(
        _root: Path,
        *arguments: str,
        token: str,
        check: bool = True,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        assert token == "token"
        del check, environment
        if arguments == ("diff", "--cached", "--quiet"):
            return subprocess.CompletedProcess(["git", *arguments], 1, b"", b"")
        if arguments == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(
                ["git", *arguments], 0, expected_commit.encode(), b""
            )
        if arguments == ("rev-parse", "HEAD^"):
            return subprocess.CompletedProcess(
                ["git", *arguments], 0, previous_commit.encode(), b""
            )
        if arguments[:2] == ("push", "--quiet"):
            push_calls.append(arguments)
        return subprocess.CompletedProcess(["git", *arguments], 0, b"", b"")

    monkeypatch.setattr(broker, "_git", git)
    monkeypatch.setattr(broker.StateBranch, "_checkout", lambda *_args, **_kwargs: None)
    return push_calls


def test_state_append_converges_after_accepted_push_with_one_stale_ref_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    observed_refs = iter(
        [
            previous_commit,
            previous_commit,
            previous_commit,
            expected_commit,
            expected_commit,
            expected_commit,
        ]
    )
    ref_reads: list[str] = []

    class StateRefApi(broker.GitHubApi):
        def request(
            self,
            path: str,
            *,
            token: str,
            method: str = "GET",
            payload: dict[str, Any] | None = None,
            expected: tuple[int, ...] = (200,),
        ) -> broker.ApiResult:
            assert path == (f"repos/{REPOSITORY}/git/ref/heads/metriplane-main-health-state")
            assert token == "token"
            assert method == "GET"
            assert payload is None
            assert expected == (200,)
            observed = next(observed_refs)
            ref_reads.append(observed)
            return broker.ApiResult(
                {},
                200,
                {
                    "object": {"sha": observed, "type": "commit"},
                    "ref": "refs/heads/metriplane-main-health-state",
                },
            )

    histories = iter(
        [
            {"generation": 7, "state_commit": previous_commit},
            {"generation": 8, "state_commit": expected_commit},
        ]
    )
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    monkeypatch.setattr(broker.stop_the_line, "validate_git_history", lambda _root: next(histories))
    monkeypatch.setattr(
        broker.stop_the_line,
        "ingest",
        lambda *_args, **_kwargs: {"generation": 8, "state_commit": expected_commit},
    )
    sleeps: list[float] = []
    state = broker.StateBranch(
        api=StateRefApi(),
        config=_config(tmp_path),
        monotonic=lambda: 0.0,
        sleep=sleeps.append,
        token="token",
    )

    assert state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"}) == {
        "generation": 8,
        "state_commit": expected_commit,
    }
    assert ref_reads == [
        previous_commit,
        previous_commit,
        previous_commit,
        expected_commit,
        expected_commit,
        expected_commit,
    ]
    assert len(push_calls) == 1
    assert push_calls == [
        (
            "push",
            "--quiet",
            "origin",
            "HEAD:refs/heads/metriplane-main-health-state",
        )
    ]
    assert sleeps == [1.0]


def test_state_append_never_repeats_push_when_stale_ref_exhausts_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi(
        [previous_commit, previous_commit]
        + [previous_commit] * broker.STATE_REF_CONVERGENCE_MAX_READS
    )
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "validate_git_history",
        lambda _root: {"generation": 7, "state_commit": previous_commit},
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "ingest",
        lambda *_args, **_kwargs: {"generation": 8, "state_commit": expected_commit},
    )
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.BrokerError, match=r"timeout 10s; reads 11$"):
        state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"})

    assert push_calls == [
        (
            "push",
            "--quiet",
            "origin",
            "HEAD:refs/heads/metriplane-main-health-state",
        )
    ]
    assert api.observed == [previous_commit] * (broker.STATE_REF_CONVERGENCE_MAX_READS + 2)
    assert sleeps == [1.0] * (broker.STATE_REF_CONVERGENCE_MAX_READS - 1)


def test_state_append_fails_immediately_on_third_sha_after_single_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    unrelated_commit = "3" * 40
    api = SequenceStateRefApi([previous_commit, previous_commit, unrelated_commit])
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "validate_git_history",
        lambda _root: {"generation": 7, "state_commit": previous_commit},
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "ingest",
        lambda *_args, **_kwargs: {"generation": 8, "state_commit": expected_commit},
    )
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    with pytest.raises(broker.BrokerError, match="concurrent/provider state drift"):
        state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"})

    assert len(push_calls) == 1
    assert api.observed == [previous_commit, previous_commit, unrelated_commit]
    assert sleeps == []


@pytest.mark.parametrize(
    ("read_back", "message"),
    [
        (
            {"generation": 8, "state_commit": "3" * 40},
            "state branch changed during read-back validation",
        ),
        (
            {"generation": 9, "state_commit": "2" * 40},
            "state branch append read-back is not exact",
        ),
    ],
)
def test_state_append_rejects_nonexact_state_after_ref_convergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_back: dict[str, Any],
    message: str,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi(
        [previous_commit, previous_commit, expected_commit, expected_commit, expected_commit]
    )
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    histories = iter(
        [
            {"generation": 7, "state_commit": previous_commit},
            read_back,
        ]
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "validate_git_history",
        lambda _root: next(histories),
    )
    monkeypatch.setattr(
        broker.stop_the_line,
        "ingest",
        lambda *_args, **_kwargs: {"generation": 8, "state_commit": expected_commit},
    )
    state = _state_branch_for_convergence(tmp_path, api=api)

    with pytest.raises(broker.BrokerError, match=message):
        state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"})

    assert len(push_calls) == 1


@pytest.mark.parametrize("failure_stage", ["checkout", "history"])
def test_state_append_rejects_invalid_checkout_or_history_after_ref_convergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([previous_commit, previous_commit, expected_commit, expected_commit])
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    checkout_calls = 0

    def checkout(_state: broker.StateBranch, _root: Path, _expected_ref: str) -> None:
        nonlocal checkout_calls
        checkout_calls += 1
        if checkout_calls == 2 and failure_stage == "checkout":
            raise broker.BrokerError("state checkout does not match the provider ref")

    history_calls = 0

    def validate(_root: Path) -> dict[str, Any]:
        nonlocal history_calls
        history_calls += 1
        if history_calls == 2 and failure_stage == "history":
            raise broker.BrokerError("state history tree identity is invalid")
        return {"generation": 7, "state_commit": previous_commit}

    monkeypatch.setattr(broker.StateBranch, "_checkout", checkout)
    monkeypatch.setattr(broker.stop_the_line, "validate_git_history", validate)
    monkeypatch.setattr(
        broker.stop_the_line,
        "ingest",
        lambda *_args, **_kwargs: {"generation": 8, "state_commit": expected_commit},
    )
    state = _state_branch_for_convergence(tmp_path, api=api)

    with pytest.raises(
        broker.BrokerError,
        match=(
            "state checkout does not match"
            if failure_stage == "checkout"
            else "state history tree identity is invalid"
        ),
    ):
        state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"})

    assert len(push_calls) == 1


@pytest.mark.parametrize(
    ("history", "message"),
    [
        ({"generation": 8, "state_commit": "1" * 40}, "generation changed"),
        (broker.BrokerError("invalid state history linkage"), "invalid state history linkage"),
    ],
)
def test_state_append_rejects_invalid_generation_or_history_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    history: dict[str, Any] | Exception,
    message: str,
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi([previous_commit])
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )

    def validate(_root: Path) -> dict[str, Any]:
        if isinstance(history, Exception):
            raise history
        return history

    monkeypatch.setattr(broker.stop_the_line, "validate_git_history", validate)
    state = _state_branch_for_convergence(tmp_path, api=api)

    with pytest.raises(broker.BrokerError, match=message):
        state.append(expected_generation=7, scope="nightly", summary={"run_id": "1"})

    assert push_calls == []


def test_repair_resolution_uses_same_single_push_ref_convergence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous_commit = "1" * 40
    expected_commit = "2" * 40
    api = SequenceStateRefApi(
        [
            previous_commit,
            previous_commit,
            previous_commit,
            expected_commit,
            expected_commit,
            expected_commit,
        ]
    )
    push_calls = _install_state_write_git_fakes(
        monkeypatch,
        expected_commit=expected_commit,
        previous_commit=previous_commit,
    )
    histories = iter(
        [
            {"generation": 7, "state_commit": previous_commit, "status": "red"},
            {"generation": 8, "state_commit": expected_commit, "status": "green"},
        ]
    )
    monkeypatch.setattr(broker.stop_the_line, "validate_git_history", lambda _root: next(histories))
    monkeypatch.setattr(
        broker.stop_the_line,
        "resolve",
        lambda *_args, **_kwargs: {
            "generation": 8,
            "state_commit": expected_commit,
            "status": "green",
        },
    )
    sleeps: list[float] = []
    state = _state_branch_for_convergence(tmp_path, api=api, sleep=sleeps.append)

    assert state.resolve_repair(
        approval_evidence={},
        authorization={},
        expected_generation=7,
        repaired_main={},
        resolved_at="2026-09-03T12:00:00Z",
    ) == {"generation": 8, "state_commit": expected_commit, "status": "green"}
    assert len(push_calls) == 1
    assert sleeps == [1.0]


def test_current_ci_selects_a_later_active_rerun_of_an_older_id(tmp_path: Path) -> None:
    paths: list[str] = []

    class CurrentCiApi(broker.GitHubApi):
        def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
            assert key == "workflow_runs"
            assert token == "token"
            paths.append(path)
            common = {
                "event": "push",
                "head_branch": "main",
                "head_sha": BASE_SHA,
            }
            return [
                {
                    **common,
                    "conclusion": "success",
                    "id": 21,
                    "run_attempt": 1,
                    "status": "completed",
                    "updated_at": "2026-08-26T12:00:00Z",
                },
                {
                    **common,
                    "conclusion": None,
                    "id": 20,
                    "run_attempt": 2,
                    "status": "in_progress",
                    "updated_at": "2026-08-26T12:01:00Z",
                },
            ]

    reconciler = broker.HealthReconciler(
        api=CurrentCiApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=FakeStateBranch(),  # type: ignore[arg-type]
        token="token",
    )

    selected = reconciler._current_ci(BASE_SHA)
    assert selected is not None
    assert (selected["id"], selected["run_attempt"]) == (20, 2)
    assert "status=" not in paths[0]


def test_current_ci_rejects_malformed_provider_chronology(tmp_path: Path) -> None:
    class MalformedChronologyApi(broker.GitHubApi):
        def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
            assert "actions/workflows/ci.yml/runs" in path
            assert key == "workflow_runs"
            assert token == "token"
            return [
                {
                    "conclusion": "success",
                    "event": "push",
                    "head_branch": "main",
                    "head_sha": BASE_SHA,
                    "id": 20,
                    "run_attempt": 1,
                    "status": "completed",
                    "updated_at": "not-a-timestamp",
                }
            ]

    reconciler = broker.HealthReconciler(
        api=MalformedChronologyApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=FakeStateBranch(),  # type: ignore[arg-type]
        token="token",
    )

    with pytest.raises(broker.BrokerError, match="run chronology is malformed"):
        reconciler._current_ci(BASE_SHA)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", None),
        ("head_branch", "release"),
        ("head_sha", "f" * 40),
    ],
)
def test_current_ci_rejects_malformed_newer_attempt_with_stable_run_id(
    tmp_path: Path, field: str, value: object
) -> None:
    class MalformedNewerAttemptApi(broker.GitHubApi):
        def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
            assert "actions/workflows/ci.yml/runs" in path
            assert key == "workflow_runs"
            assert token == "token"
            common = {
                "event": "push",
                "head_branch": "main",
                "head_sha": BASE_SHA,
                "id": 20,
            }
            newer = {
                **common,
                "conclusion": None,
                "run_attempt": 2,
                "status": "in_progress",
                "updated_at": "2026-08-26T12:01:00Z",
            }
            newer[field] = value
            return [
                {
                    **common,
                    "conclusion": "success",
                    "run_attempt": 1,
                    "status": "completed",
                    "updated_at": "2026-08-26T12:00:00Z",
                },
                newer,
            ]

    reconciler = broker.HealthReconciler(
        api=MalformedNewerAttemptApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=FakeStateBranch(),  # type: ignore[arg-type]
        token="token",
    )

    with pytest.raises(broker.BrokerError, match=rf"field '{field}'.*protected main"):
        reconciler._current_ci(BASE_SHA)


def test_fresh_cached_green_cannot_hide_a_newer_active_ci_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = FakeStateBranch()
    state.result_identities.add(("protected-main", "github-actions:20:1"))
    reconciler = broker.HealthReconciler(
        api=FakeDeepApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )
    monkeypatch.setattr(
        reconciler,
        "_current_ci",
        lambda _sha: {
            "conclusion": None,
            "id": 20,
            "run_attempt": 2,
            "status": "in_progress",
        },
    )

    with pytest.raises(broker.BrokerError, match="latest CI attempt is still active"):
        reconciler.reconcile_main(NOW)
    assert state.appends == []


def test_recorded_aggregate_is_not_appended_again_as_a_freshness_heartbeat(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    state = FakeStateBranch()
    state.state["updated_at"] = "2025-01-01T00:00:00Z"
    state.result_identities.add(
        (
            "protected-main",
            "github-actions-set:v1:metriplane=501:1;documentation=502:1;security=503:1",
        )
    )
    spool = broker.DurableSpool(tmp_path / "spool")
    reconciler = broker.HealthReconciler(
        api=api,
        config=config,
        spool=spool,
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )

    assert reconciler.reconcile_main(NOW) == state.state
    assert state.appends == []
    assert spool.get_cursor("main_ci_run_id") == "501"


def test_fresh_cached_green_records_a_new_documentation_failure(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakeTransactionApi(config, "success")
    api.documentation_run_id = 504
    api.documentation_conclusion = "failure"
    state = FakeStateBranch()
    state.result_identities.add(
        (
            "protected-main",
            "github-actions-set:v1:metriplane=501:1;documentation=502:1;security=503:1",
        )
    )
    reconciler = broker.HealthReconciler(
        api=api,
        config=config,
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )

    reconciler.reconcile_main(NOW)

    assert len(state.appends) == 1
    scope, summary = state.appends[0]
    assert scope == "main"
    assert summary["conclusion"] == "failure"
    assert summary["run_id"] == (
        "github-actions-set:v1:metriplane=501:1;documentation=504:1;security=503:1"
    )


def test_red_state_records_each_protected_main_attempt_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeDeepApi()
    state = FakeStateBranch()
    state.state["status"] = "red"
    reconciler = broker.HealthReconciler(
        api=api,
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )
    ci_run = {
        "conclusion": "success",
        "created_at": "2026-08-26T11:50:00Z",
        "id": 20,
        "run_attempt": 1,
        "status": "completed",
    }
    selection = {
        "ready": True,
        "runs": [
            {"id": 20, "key": "metriplane", "run_attempt": 1},
            {"id": 21, "key": "documentation", "run_attempt": 1},
            {"id": 22, "key": "security", "run_attempt": 1},
        ],
    }
    monkeypatch.setattr(reconciler, "_current_ci", lambda _sha: ci_run)
    monkeypatch.setattr(reconciler, "_workflow_runs", lambda _sha: [])
    monkeypatch.setattr(
        broker.observe_main_health,
        "select_runs",
        lambda **_values: selection,
    )
    monkeypatch.setattr(
        broker.observe_main_health,
        "observe_jobs",
        lambda **_values: {"conclusion": "success", "obligations": []},
    )

    reconciler.reconcile_main(NOW)
    reconciler.reconcile_main(NOW + timedelta(minutes=1))

    assert [(scope, summary["run_id"]) for scope, summary in state.appends] == [
        (
            "main",
            "github-actions-set:v1:metriplane=20:1;documentation=21:1;security=22:1",
        )
    ]


def test_repair_results_require_latest_observation_to_pass(tmp_path: Path) -> None:
    history = tmp_path / "history"
    results = tmp_path / "results"
    history.mkdir()
    results.mkdir()
    successful = {
        "cadence": "nightly",
        "conclusion": "success",
        "recorded_at": "2026-08-26T12:00:00Z",
        "sha": MERGE_SHA,
    }
    failed = {
        "cadence": "nightly",
        "conclusion": "failure",
        "recorded_at": "2026-08-26T12:01:00Z",
        "sha": MERGE_SHA,
    }
    for generation, result in enumerate((successful, failed), start=1):
        result_digest = broker.digest(result)
        (results / f"{result_digest}.json").write_bytes(broker.canonical_bytes(result))
        (history / f"{generation:08d}.json").write_bytes(
            broker.canonical_bytes(
                {
                    "cadence": "nightly",
                    "result_digest": result_digest,
                }
            )
        )

    assert (MERGE_SHA, "nightly") not in broker._repair_passing_results(tmp_path)


def test_repair_results_exclude_legacy_protected_main_success(tmp_path: Path) -> None:
    history = tmp_path / "history"
    results = tmp_path / "results"
    history.mkdir()
    results.mkdir()
    result = _legacy_protected_main_rerun_results()[1]
    result_digest = broker.digest(result)
    (results / f"{result_digest}.json").write_bytes(broker.canonical_bytes(result))
    (history / "00000006.json").write_bytes(
        broker.canonical_bytes(
            {
                "cadence": "protected-main",
                "result_digest": result_digest,
            }
        )
    )

    assert (result["sha"], "protected-main") not in broker._repair_passing_results(tmp_path)


def test_deep_reconciler_seeds_cursor_then_appends_every_new_run(tmp_path: Path) -> None:
    api = FakeDeepApi()
    state = FakeStateBranch(deep_identities={"nightly": {(10, 1)}, "weekly": {(11, 1)}})
    spool = broker.DurableSpool(tmp_path / "spool")
    reconciler = broker.HealthReconciler(
        api=api,
        config=_config(tmp_path),
        spool=spool,
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )
    reconciler.reconcile_deep(NOW)
    assert state.appends == []
    assert spool.get_cursor("deep_nightly_run_id") == "10:1"
    assert spool.get_cursor("deep_weekly_run_id") == "11:1"

    api.runs.append(
        {
            "conclusion": "success",
            "display_title": "Main Health Deep / 23 3 * * 1-6 / main",
            "head_sha": BASE_SHA,
            "id": 12,
            "run_attempt": 1,
            "status": "completed",
            "updated_at": "2026-08-26T12:01:00Z",
        }
    )
    reconciler.reconcile_deep(NOW + timedelta(minutes=1))
    assert [(scope, summary["run_id"]) for scope, summary in state.appends] == [
        ("nightly", "github-actions:12:1")
    ]
    assert spool.get_cursor("deep_nightly_run_id") == "12:1"

    api.runs[0]["run_attempt"] = 2
    api.runs[0]["updated_at"] = "2026-08-26T12:02:00Z"
    reconciler.reconcile_deep(NOW + timedelta(minutes=2))
    assert [(scope, summary["run_id"]) for scope, summary in state.appends] == [
        ("nightly", "github-actions:12:1"),
        ("nightly", "github-actions:10:2"),
    ]


def test_deep_reconciler_never_skips_first_governed_runs(tmp_path: Path) -> None:
    state = FakeStateBranch()
    reconciler = broker.HealthReconciler(
        api=FakeDeepApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=state,  # type: ignore[arg-type]
        token="token",
    )
    reconciler.reconcile_deep(NOW)
    assert [(scope, summary["run_id"]) for scope, summary in state.appends] == [
        ("nightly", "github-actions:10:1"),
        ("weekly", "github-actions:11:1"),
    ]


def test_active_current_main_deep_run_blocks_merge_reconciliation(tmp_path: Path) -> None:
    api = FakeDeepApi()
    api.runs.append(
        {
            "conclusion": None,
            "display_title": "Main Health Deep / main-health-weekly / main",
            "head_sha": BASE_SHA,
            "id": 12,
            "run_attempt": 1,
            "status": "in_progress",
            "updated_at": "2026-08-26T12:00:00Z",
        }
    )
    reconciler = broker.HealthReconciler(
        api=api,
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=FakeStateBranch(),  # type: ignore[arg-type]
        token="token",
    )
    with pytest.raises(broker.BrokerError, match="still active"):
        reconciler.reconcile_deep(NOW)


def _publish_step(
    name: str,
    number: int,
    status: str,
    *,
    conclusion: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    return {
        "conclusion": conclusion,
        "name": name,
        "number": number,
        "started_at": started_at,
        "status": status,
    }


def _publish_job(
    *,
    conclusion: str | None,
    job_id: int,
    name: str,
    run_id: int,
    status: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "conclusion": conclusion,
        "head_branch": "main",
        "head_sha": HEAD_SHA,
        "id": job_id,
        "name": name,
        "run_id": run_id,
        "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
        "status": status,
        "steps": steps,
        "workflow_name": broker.PUBLISH_WORKFLOW_NAME,
    }


class FakePublishLeaseApi(broker.GitHubApi):
    def __init__(self, config: broker.BrokerConfig) -> None:
        super().__init__()
        self.config = config
        self.current_now = NOW
        self.main_sha = HEAD_SHA
        self.owner_id = 20
        self.workflow_id = 9001
        self.phase = "awaiting"
        self.wait_started_at = "2026-08-26T12:00:00Z"
        self.dispatch_blocker_success = True
        self.authority_mutation: str | None = None
        self.ambiguous_check_create = False
        self.ambiguous_ref_delete = False
        self.reconciliation_failed = False
        self.refs: dict[str, str] = {}
        self.check: dict[str, Any] | None = None
        self.runs = [self._run(8001, 1)]
        self.calls: list[tuple[str, str]] = []

    def _actor(self) -> dict[str, Any]:
        return {"id": self.owner_id, "login": "Miko997", "type": "User"}

    def _run(self, run_id: int, run_attempt: int) -> dict[str, Any]:
        return {
            "actor": self._actor(),
            "conclusion": None,
            "created_at": "2026-08-26T11:54:00Z",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": HEAD_SHA,
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}",
            "id": run_id,
            "name": broker.PUBLISH_WORKFLOW_NAME,
            "path": ".github/workflows/publish-pypi.yml",
            "repository": {"full_name": REPOSITORY, "owner": self._actor()},
            "run_attempt": run_attempt,
            "run_started_at": "2026-08-26T11:55:00Z",
            "status": "in_progress",
            "triggering_actor": self._actor(),
            "updated_at": "2026-08-26T12:00:00Z",
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
            "workflow_id": self.workflow_id,
        }

    def _jobs(self, run_id: int, run_attempt: int) -> list[dict[str, Any]]:
        run = next(value for value in self.runs if value["id"] == run_id)
        assert run["run_attempt"] == run_attempt
        blocker_conclusion = "success" if self.dispatch_blocker_success else "failure"
        validate = _publish_job(
            conclusion="success" if self.dispatch_blocker_success else "failure",
            job_id=run_id * 10 + 1,
            name=broker.PUBLISH_VALIDATE_JOB,
            run_id=run_id,
            status="completed",
            steps=[
                _publish_step(
                    broker.PUBLISH_DISPATCH_BLOCKER_STEP,
                    8,
                    "completed",
                    conclusion=blocker_conclusion,
                )
            ],
        )
        artifact = _publish_job(
            conclusion="success",
            job_id=run_id * 10 + 2,
            name=broker.PUBLISH_ARTIFACT_JOB,
            run_id=run_id,
            status="completed",
            steps=[],
        )
        step_states = {
            "awaiting": (
                ("in_progress", None),
                ("queued", None),
                ("queued", None),
                ("queued", None),
            ),
            "publishing": (
                ("completed", "success"),
                ("in_progress", None),
                ("queued", None),
                ("queued", None),
            ),
            "verifying": (
                ("completed", "success"),
                ("completed", "success"),
                ("completed", "success"),
                ("completed", "success"),
            ),
            "reconciling": (
                ("completed", "success"),
                ("completed", "success"),
                ("completed", "success"),
                ("completed", "success"),
            ),
        }[self.phase]
        critical_names = (
            broker.PUBLISH_WAIT_STEP,
            broker.PUBLISH_FENCED_BLOCKER_STEP,
            broker.PUBLISH_REASSERT_STEP,
            broker.PUBLISH_UPLOAD_STEP,
        )
        critical = [
            _publish_step(
                name,
                number + 4,
                state,
                conclusion=conclusion,
                started_at=self.wait_started_at if number == 1 else None,
            )
            for number, (name, (state, conclusion)) in enumerate(
                zip(critical_names, step_states, strict=True), start=1
            )
        ]
        publish_complete = self.phase in {"verifying", "reconciling"}
        publish = _publish_job(
            conclusion="success" if publish_complete else None,
            job_id=run_id * 10 + 3,
            name=broker.PUBLISH_JOB,
            run_id=run_id,
            status="completed" if publish_complete else "in_progress",
            steps=critical,
        )
        if self.phase == "reconciling":
            verify_status = "completed"
        elif self.phase == "verifying":
            verify_status = "in_progress"
        else:
            verify_status = "queued"
        verify = _publish_job(
            conclusion="success" if verify_status == "completed" else None,
            job_id=run_id * 10 + 4,
            name=broker.PUBLISH_VERIFY_JOB,
            run_id=run_id,
            status=verify_status,
            steps=[],
        )
        reconcile_steps: list[dict[str, Any]] = []
        reconcile_status = "queued"
        if self.phase == "reconciling":
            reconcile_status = "in_progress"
            reconcile_steps = [
                _publish_step(
                    broker.PUBLISH_RECONCILE_GUARD_STEP,
                    1,
                    "completed",
                    conclusion="success",
                ),
                _publish_step(
                    broker.PUBLISH_RECONCILE_OBSERVE_STEP,
                    2,
                    "in_progress",
                ),
            ]
        reconcile = _publish_job(
            conclusion="failure" if self.reconciliation_failed else None,
            job_id=run_id * 10 + 5,
            name=broker.PUBLISH_RECONCILE_JOB,
            run_id=run_id,
            status="completed" if self.reconciliation_failed else reconcile_status,
            steps=reconcile_steps,
        )
        return [validate, artifact, publish, verify, reconcile]

    def provider_now(self, token: str) -> datetime:
        assert token in {"settings-token", "token"}
        return self.current_now

    def list_items(self, path: str, *, key: str, token: str) -> list[dict[str, Any]]:
        assert token in {"settings-token", "token"}
        if "/rulesets?includes_parents=true" in path:
            assert key == "items"
            return [
                {
                    field: value[field]
                    for field in ("enforcement", "id", "name", "source", "source_type", "target")
                }
                for value in _rulesets(self.config).values()
            ]
        if "actions/workflows/publish-pypi.yml/runs" in path:
            assert key == "workflow_runs"
            return [dict(run) for run in self.runs]
        if "/attempts/" in path and path.endswith("/jobs"):
            assert key == "jobs"
            run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
            attempt = int(path.split("/attempts/", 1)[1].split("/", 1)[0])
            return self._jobs(run_id, attempt)
        if "/check-runs?" in path:
            assert key == "check_runs"
            return [] if self.check is None else [dict(self.check)]
        raise AssertionError((key, path))

    def request(
        self,
        path: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> broker.ApiResult:
        assert token in {"settings-token", "token"}
        self.calls.append((method, path))
        if path == f"repos/{REPOSITORY}":
            return broker.ApiResult(
                {},
                200,
                {
                    "default_branch": "main",
                    "full_name": REPOSITORY,
                    "id": 100,
                    "name": "metriplane",
                    "owner": self._actor(),
                },
            )
        if path == f"repos/{REPOSITORY}/actions/workflows/publish-pypi.yml":
            return broker.ApiResult(
                {},
                200,
                {
                    "id": self.workflow_id,
                    "name": broker.PUBLISH_WORKFLOW_NAME,
                    "path": broker.PUBLISH_WORKFLOW_PATH,
                    "state": "active",
                },
            )
        if path.startswith(f"repos/{REPOSITORY}/actions/runs/"):
            run_id = int(path.rsplit("/", 1)[1])
            match = next(run for run in self.runs if run["id"] == run_id)
            return broker.ApiResult({}, 200, dict(match))
        if "/rulesets?includes_parents=true" in path:
            return broker.ApiResult(
                {},
                200,
                [
                    {
                        field: value[field]
                        for field in (
                            "enforcement",
                            "id",
                            "name",
                            "source",
                            "source_type",
                            "target",
                        )
                    }
                    for value in _rulesets(self.config).values()
                ],
            )
        if path == f"repos/{REPOSITORY}/git/ref/heads/main":
            return broker.ApiResult(
                {},
                200,
                {"object": {"sha": self.main_sha, "type": "commit"}, "ref": "refs/heads/main"},
            )
        if path == f"repos/{REPOSITORY}/git/matching-refs/heads/release-leases/":
            return broker.ApiResult(
                {},
                200,
                [
                    {"object": {"sha": sha, "type": "commit"}, "ref": ref}
                    for ref, sha in sorted(self.refs.items())
                ],
            )
        if path.startswith(f"repos/{REPOSITORY}/contents/"):
            encoded_path = path.split("/contents/", 1)[1].split("?", 1)[0]
            authority_path = urllib.parse.unquote(encoded_path)
            content, blob_sha = broker._local_authority_blob(authority_path)
            if authority_path == self.authority_mutation:
                content += b"\nmutated\n"
                blob_sha = "f" * 40
            return broker.ApiResult(
                {},
                200,
                {
                    "content": base64.b64encode(content).decode(),
                    "encoding": "base64",
                    "path": authority_path,
                    "sha": blob_sha,
                    "size": len(content),
                    "type": "file",
                },
            )
        if "/rulesets/" in path:
            ruleset_id = int(path.rsplit("/", 1)[1])
            return broker.ApiResult({}, 200, _rulesets(self.config)[ruleset_id])
        if path == f"repos/{REPOSITORY}/git/refs" and method == "POST":
            assert payload is not None
            ref = str(payload["ref"])
            sha = str(payload["sha"])
            if self.refs:
                raise broker.ProviderError("ref exists", status=422)
            self.refs[ref] = sha
            return broker.ApiResult({}, 201, {"object": {"sha": sha, "type": "commit"}, "ref": ref})
        if path.startswith(f"repos/{REPOSITORY}/git/refs/") and method == "DELETE":
            encoded_ref = path.split("/git/refs/", 1)[1]
            ref = "refs/" + urllib.parse.unquote(encoded_ref)
            del self.refs[ref]
            if self.ambiguous_ref_delete:
                self.ambiguous_ref_delete = False
                raise broker.ProviderTransportError("ambiguous ref deletion")
            return broker.ApiResult({}, 204, None)
        if path == f"repos/{REPOSITORY}/check-runs" and method == "POST":
            assert payload is not None
            self.check = {
                **payload,
                "app": {"id": self.config.app_id, "slug": self.config.app_slug},
                "conclusion": payload.get("conclusion"),
                "id": 7001,
            }
            if self.ambiguous_check_create:
                self.ambiguous_check_create = False
                raise broker.ProviderTransportError("ambiguous check creation")
            return broker.ApiResult({}, 201, dict(self.check))
        if path == f"repos/{REPOSITORY}/check-runs/7001" and method == "PATCH":
            assert payload is not None and self.check is not None
            self.check.update(payload)
            return broker.ApiResult({}, 200, dict(self.check))
        raise AssertionError((method, path, expected))


def _publish_controller(
    api: FakePublishLeaseApi, spool: broker.DurableSpool
) -> broker.PublishLeaseController:
    return broker.PublishLeaseController(
        api=api,
        config=api.config,
        spool=spool,
        token="token",
    )


def test_publish_lease_identity_is_the_exact_read_only_consumer_contract() -> None:
    record = broker.PublishLeaseRecord.create(
        release_sha=HEAD_SHA,
        run_attempt=3,
        run_id=8001,
        created_at="2026-08-26T12:00:00Z",
        expires_at="2026-08-26T14:00:00Z",
    )
    consumer = release_artifacts._publish_lease(REPOSITORY, HEAD_SHA, "8001", "3")
    assert broker.APP_INTEGRATION_ID == release_artifacts.PUBLISH_BROKER_APP_ID
    assert broker.APP_SLUG == release_artifacts.PUBLISH_BROKER_APP_SLUG
    assert broker.PUBLISH_LEASE_CHECK == release_artifacts.PUBLISH_LEASE_CHECK_NAME
    assert record.lease_ref == consumer.ref
    assert record.external_id == consumer.external_id


def test_publish_lease_activation_restart_and_successful_reconciliation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    spool = broker.DurableSpool(tmp_path / "spool")

    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    active = spool.publish_lease_fence()
    assert active is not None and active.status == "active" and active.check_run_id == 7001
    assert api.refs == {active.lease_ref: HEAD_SHA}
    assert api.check is not None
    assert api.check["external_id"] == f"metriplane-publish-lease.v1:8001:1:{HEAD_SHA}"
    assert api.check["status"] == "in_progress"

    api.phase = "reconciling"
    restored = broker.DurableSpool(tmp_path / "spool")
    assert not _publish_controller(api, restored).reconcile(
        provider_now=NOW + timedelta(minutes=10),
        settings_token="settings-token",
    )
    assert restored.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check["status"] == "completed"
    assert api.check["conclusion"] == "success"
    delete_index = next(index for index, call in enumerate(api.calls) if call[0] == "DELETE")
    success_index = max(
        index
        for index, call in enumerate(api.calls)
        if call == ("PATCH", f"repos/{REPOSITORY}/check-runs/7001")
    )
    assert delete_index < success_index


def test_publish_lease_rejects_nonprovider_workflow_path_before_provider_write(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    api.runs[0]["path"] = ".github/workflows/publish-pypi.yml@main"
    spool = broker.DurableSpool(tmp_path / "spool")

    with pytest.raises(broker.BrokerError, match="run identity is not canonical"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW,
            settings_token="settings-token",
        )

    assert spool.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check is None


def test_publish_lease_recovers_ambiguous_check_creation_after_restart(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    api.ambiguous_check_create = True
    spool = broker.DurableSpool(tmp_path / "spool")
    with pytest.raises(broker.ProviderTransportError, match="ambiguous check creation"):
        _publish_controller(api, spool).reconcile(provider_now=NOW, settings_token="settings-token")
    creating = spool.publish_lease_fence()
    assert creating is not None and creating.status == "creating"
    assert api.refs == {creating.lease_ref: HEAD_SHA}
    assert api.check is not None and api.check["status"] == "in_progress"

    restored = broker.DurableSpool(tmp_path / "spool")
    assert _publish_controller(api, restored).reconcile(
        provider_now=NOW + timedelta(minutes=1),
        settings_token="settings-token",
    )
    active = restored.publish_lease_fence()
    assert active is not None and active.status == "active" and active.check_run_id == 7001


def test_publish_lease_recovers_ambiguous_ref_deletion_after_restart(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    spool = broker.DurableSpool(tmp_path / "spool")
    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    api.phase = "reconciling"
    api.ambiguous_ref_delete = True
    with pytest.raises(broker.ProviderTransportError, match="ambiguous ref deletion"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW + timedelta(minutes=10),
            settings_token="settings-token",
        )
    releasing = spool.publish_lease_fence()
    assert releasing is not None and releasing.status == "releasing"
    assert api.refs == {}
    assert api.check is not None and api.check["status"] == "in_progress"

    restored = broker.DurableSpool(tmp_path / "spool")
    assert not _publish_controller(api, restored).reconcile(
        provider_now=NOW + timedelta(minutes=11),
        settings_token="settings-token",
    )
    assert restored.publish_lease_fence() is None
    assert api.check["conclusion"] == "success"


def test_publish_lease_quarantines_when_observer_loses_ref_deletion_race(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    spool = broker.DurableSpool(tmp_path / "spool")
    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    api.phase = "reconciling"
    api.ambiguous_ref_delete = True
    with pytest.raises(broker.ProviderTransportError, match="ambiguous ref deletion"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW + timedelta(minutes=10),
            settings_token="settings-token",
        )

    api.reconciliation_failed = True
    assert _publish_controller(api, broker.DurableSpool(tmp_path / "spool")).reconcile(
        provider_now=NOW + timedelta(minutes=11),
        settings_token="settings-token",
    )
    quarantined = broker.DurableSpool(tmp_path / "spool").publish_lease_fence()
    assert quarantined is not None and quarantined.status == "quarantined"
    assert api.refs == {}
    assert api.check is not None and api.check["conclusion"] == "failure"
    assert "left reconciliation before lease release" in str(quarantined.reason)


def test_publish_lease_expiry_quarantines_and_retains_the_ref(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    spool = broker.DurableSpool(tmp_path / "spool")
    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    active = spool.publish_lease_fence()
    assert active is not None
    api.phase = "publishing"
    api.current_now = NOW + timedelta(hours=3)
    assert _publish_controller(api, spool).reconcile(
        provider_now=api.current_now,
        settings_token="settings-token",
    )
    quarantined = spool.publish_lease_fence()
    assert quarantined is not None and quarantined.status == "quarantined"
    assert api.refs == {active.lease_ref: HEAD_SHA}
    assert api.check is not None and api.check["conclusion"] == "failure"
    assert "expired" in str(quarantined.reason)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("actor", "canonical repository owner"),
        ("authority", "differs from deployed broker"),
    ],
)
def test_publish_lease_rejects_identity_and_authority_mutation_before_provider_write(
    tmp_path: Path, mutation: str, message: str
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    if mutation == "actor":
        api.runs[0]["actor"] = {"id": 999, "login": "attacker", "type": "User"}
    else:
        api.authority_mutation = broker.PUBLISH_WORKFLOW_PATH
    spool = broker.DurableSpool(tmp_path / "spool")
    with pytest.raises(broker.BrokerError, match=message):
        _publish_controller(api, spool).reconcile(provider_now=NOW, settings_token="settings-token")
    assert spool.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check is None


def test_publish_lease_rejects_failed_blocker_authority_without_provider_write(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    api.dispatch_blocker_success = False
    spool = broker.DurableSpool(tmp_path / "spool")
    assert not _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    assert spool.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check is None


def test_publish_lease_rejects_a_future_wait_identity_before_provider_write(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    api.wait_started_at = "2026-08-26T12:01:00Z"
    spool = broker.DurableSpool(tmp_path / "spool")
    with pytest.raises(broker.BrokerError, match="wait begins in the future"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW,
            settings_token="settings-token",
        )
    assert spool.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check is None


def test_publish_lease_orphan_ref_revalidates_authority_before_acknowledgment(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    lease_ref = f"{broker.PUBLISH_LEASE_REF_PREFIX}8001-1"
    api.refs[lease_ref] = HEAD_SHA
    api.authority_mutation = broker.PUBLISH_WORKFLOW_PATH
    spool = broker.DurableSpool(tmp_path / "spool")

    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW,
        settings_token="settings-token",
    )
    quarantined = spool.publish_lease_fence()
    assert quarantined is not None and quarantined.status == "quarantined"
    assert api.refs == {lease_ref: HEAD_SHA}
    assert api.check is not None and api.check["conclusion"] == "failure"
    assert "differs from deployed broker" in str(quarantined.reason)


def test_publish_lease_rejects_two_provider_contenders_before_reservation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    api.runs.append(api._run(8002, 1))
    spool = broker.DurableSpool(tmp_path / "spool")
    with pytest.raises(broker.BrokerError, match="multiple production runs"):
        _publish_controller(api, spool).reconcile(provider_now=NOW, settings_token="settings-token")
    assert spool.publish_lease_fence() is None
    assert api.refs == {}
    assert api.check is None


def test_publish_lease_ref_or_check_mutation_keeps_the_durable_fence(tmp_path: Path) -> None:
    config = _config(tmp_path)
    api = FakePublishLeaseApi(config)
    spool = broker.DurableSpool(tmp_path / "spool")
    assert _publish_controller(api, spool).reconcile(
        provider_now=NOW, settings_token="settings-token"
    )
    active = spool.publish_lease_fence()
    assert active is not None
    api.refs[active.lease_ref] = BASE_SHA
    with pytest.raises(broker.BrokerError, match="identities differ"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW + timedelta(minutes=1),
            settings_token="settings-token",
        )
    assert spool.publish_lease_fence() == active

    api.refs[active.lease_ref] = HEAD_SHA
    assert api.check is not None
    api.check["output"]["summary"] = "mutated"
    with pytest.raises(broker.BrokerError, match="not provider-bound"):
        _publish_controller(api, spool).reconcile(
            provider_now=NOW + timedelta(minutes=2),
            settings_token="settings-token",
        )
    assert spool.publish_lease_fence() == active


def test_durable_publish_lease_database_serializes_racing_contenders(tmp_path: Path) -> None:
    root = tmp_path / "spool"
    first = broker.PublishLeaseRecord.create(
        release_sha=HEAD_SHA,
        run_attempt=1,
        run_id=8001,
        created_at="2026-08-26T12:00:00Z",
        expires_at="2026-08-26T14:00:00Z",
    )
    second = broker.PublishLeaseRecord.create(
        release_sha=HEAD_SHA,
        run_attempt=1,
        run_id=8002,
        created_at="2026-08-26T12:00:00Z",
        expires_at="2026-08-26T14:00:00Z",
    )
    broker.DurableSpool(root)

    def contend(record: broker.PublishLeaseRecord) -> str:
        try:
            broker.DurableSpool(root).begin_publish_lease(record)
        except broker.BrokerError:
            return "blocked"
        return "entered"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(contend, (first, second)))
    assert sorted(outcomes) == ["blocked", "entered"]
    fence = broker.DurableSpool(root).publish_lease_fence()
    assert fence is not None and fence.external_id in {first.external_id, second.external_id}


def test_durable_spool_migrates_v1_for_publish_lease_restart_state(tmp_path: Path) -> None:
    root = tmp_path / "spool"
    original = broker.DurableSpool(root)
    with closing(sqlite3.connect(original.path)) as connection, connection:
        connection.execute("DROP TABLE publish_leases")
        connection.execute("PRAGMA user_version = 1")
    migrated = broker.DurableSpool(root)
    with closing(sqlite3.connect(migrated.path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'publish_leases'"
        ).fetchone()
    assert version == (broker.SPOOL_SCHEMA_VERSION,)
    assert table == ("publish_leases",)


def test_run_once_never_processes_a_pull_while_publication_is_fenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    events: list[str] = []

    class Authenticator:
        def mint(self) -> broker.InstallationToken:
            return broker.InstallationToken(
                expires_at=now + timedelta(hours=1),
                installation_id=1,
                token="token",
            )

    class Api(broker.GitHubApi):
        def provider_now(self, token: str) -> datetime:
            assert token == "token"
            return now

    class Checks:
        def __init__(self, **_values: Any) -> None:
            return None

        def ensure_failed(self, *, head_sha: str, reason: str) -> int:
            assert head_sha == HEAD_SHA and reason
            return 1

    class Leases:
        def __init__(self, **_values: Any) -> None:
            return None

        def reconcile(self, *, provider_now: datetime, settings_token: str) -> bool:
            assert provider_now == now and settings_token == "token"
            events.append("lease-fenced")
            return True

    class State:
        def __init__(self, **_values: Any) -> None:
            return None

    class Health:
        def __init__(self, **_values: Any) -> None:
            return None

        def reconcile_main(self, provider_now: datetime) -> None:
            assert provider_now == now

        def reconcile_deep(self, provider_now: datetime) -> None:
            assert provider_now == now

    service = broker.Broker(
        api=Api(),
        authenticator=Authenticator(),  # type: ignore[arg-type]
        config=_config(tmp_path),
        settings_authenticator=Authenticator(),  # type: ignore[arg-type]
        spool=broker.DurableSpool(tmp_path / "spool"),
    )
    monkeypatch.setattr(service, "_reconcile_orphans", lambda _token: [])
    monkeypatch.setattr(service, "_reconcile_repair", lambda **_values: {})
    monkeypatch.setattr(
        service,
        "_process_pull",
        lambda **_values: pytest.fail("pull processing ran while publication was fenced"),
    )
    monkeypatch.setattr(
        broker,
        "_provider_list",
        lambda *_args, **_kwargs: [{"head": {"sha": HEAD_SHA}, "number": 81}],
    )
    monkeypatch.setattr(broker, "CheckController", Checks)
    monkeypatch.setattr(broker, "PublishLeaseController", Leases)
    monkeypatch.setattr(broker, "StateBranch", State)
    monkeypatch.setattr(broker, "HealthReconciler", Health)
    monkeypatch.setattr(broker, "_rulesets", lambda *_args, **_kwargs: _rulesets(_config(tmp_path)))
    monkeypatch.setattr(broker, "validate_hosted_rulesets", lambda **_values: {})

    assert service.run_once() == []
    assert events == ["lease-fenced", "lease-fenced"]
