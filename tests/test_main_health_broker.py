# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools import main_health_broker as broker
from tools import stop_the_line
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
            "health_max_age_seconds": 300,
            "main_update_ruleset_id": 21600001,
            "max_clock_skew_seconds": 30,
            "poll_seconds": 60,
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


def _repair_reviews() -> list[dict[str, Any]]:
    request = _repair_request()
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
            "body": f"{broker.APPROVAL_MARKER} {broker.digest(request)}\n",
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
        headers: dict[str, str] = {}
        status = 200

        def __enter__(self) -> MalformedResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b"not-json"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: MalformedResponse())
    with pytest.raises(broker.ProviderTransportError, match="malformed JSON"):
        broker.GitHubApi().request("merge", token="token", method="PUT", payload={})
    with pytest.raises(broker.BrokerError, match="malformed JSON") as exc_info:
        broker.GitHubApi().request("read", token="token")
    assert not isinstance(exc_info.value, broker.ProviderTransportError)


def test_config_rejects_noncanonical_app_and_permissive_clock(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config.state_root == tmp_path / "state"
    value = {field: getattr(config, field) for field in broker.CONFIG_FIELDS}
    value["credential_path"] = str(value["credential_path"])
    value["settings_credential_path"] = str(value["settings_credential_path"])
    value["state_root"] = str(value["state_root"])
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
    assert example["settings_app_id"] == 0
    assert example["poll_seconds"] == 60
    assert Path(example["state_root"]) == Path("/home/metriplane-health/state")
    with pytest.raises(broker.BrokerError, match="settings_app_id"):
        broker.BrokerConfig.from_mapping(example)
    example_with_witness = {**example, "settings_app_id": 9876543}
    with pytest.raises(broker.BrokerError, match="main_update_ruleset_id"):
        broker.BrokerConfig.from_mapping(example_with_witness)
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
        "ReadWritePaths=/home/metriplane-health/state",
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
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(broker.BrokerError, match="schema version is incompatible"):
        broker.DurableSpool(future_root)


class FakeCheckApi(broker.GitHubApi):
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        super().__init__()
        self.runs = runs
        self.calls: list[tuple[str, str]] = []

    def provider_now(self, token: str) -> datetime:
        assert token == "token"
        return NOW

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
    controller.succeed(
        check_run_id=42,
        head_sha=HEAD_SHA,
        request_digest="4" * 64,
        summary="exact merge",
    )
    assert canonical["conclusion"] == "success"
    assert spool.get_check_id(HEAD_SHA) == 42
    assert spool.get_check_external_id(HEAD_SHA) == f"mhb1:merge:{'4' * 64}"

    restored_spool = broker.DurableSpool(tmp_path / "restored-spool")
    restored = broker.CheckController(
        api=api,
        config=_config(tmp_path),
        spool=restored_spool,
        token="token",
    )
    assert restored.ensure_failed(head_sha=HEAD_SHA, reason="restored startup") == 42
    assert restored_spool.get_check_external_id(HEAD_SHA) == f"mhb1:consumed:{'4' * 64}"


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
        self.weekly_conclusion: str | None = "success"
        self.weekly_run_id = 602
        self.weekly_status = "completed"
        self.drift_on_final_ruleset = False
        self.extra_active_ruleset = False
        self.inventory_source_drift = False
        self.merged = False
        self.merge_calls = 0
        self.reported_commits = 1
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
            return broker.ApiResult(
                {},
                200,
                {**_repository_response(), "default_branch": self.default_branch},
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
            return broker.ApiResult({}, 200, _reviews())
        if "/pulls/81/commits?" in path:
            return broker.ApiResult({}, 200, _commits())
        if path.endswith("/pulls/81"):
            value = _pull()
            value["commits"] = self.reported_commits
            if self.merged:
                value = {**value, "merge_commit_sha": MERGE_SHA, "merged": True, "state": "closed"}
            return broker.ApiResult({}, 200, value)
        if path.endswith("/git/ref/heads/main"):
            sha = MERGE_SHA if self.merged else BASE_SHA
            return broker.ApiResult(
                {}, 200, {"object": {"sha": sha, "type": "commit"}, "ref": "refs/heads/main"}
            )
        if "/collaborators/" in path and path.endswith("/permission"):
            return broker.ApiResult({}, 200, {"permission": "write"})
        if "/rulesets?includes_parents=true" in path:
            self.ruleset_inventory_calls += 1
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
            return broker.ApiResult({}, 200, _rulesets(self.config)[ruleset_id])
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
            return [
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
                    ("nightly", 601, "completed", "success"),
                    (
                        "weekly",
                        self.weekly_run_id,
                        self.weekly_status,
                        self.weekly_conclusion,
                    ),
                )
            ]
        if "/actions/runs/" in path and path.endswith("/jobs"):
            assert key == "jobs"
            run_id = int(path.split("/runs/", 1)[1].split("/", 1)[0])
            attempt = int(path.split("/attempts/", 1)[1].split("/", 1)[0])
            if run_id in {601, self.weekly_run_id}:
                cadence = "nightly" if run_id == 601 else "weekly"
                status = self.weekly_status if cadence == "weekly" else "completed"
                conclusion = self.weekly_conclusion if cadence == "weekly" else "success"
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
        self, *, check_run_id: int, head_sha: str, request_digest: str, summary: str
    ) -> dict[str, Any]:
        assert summary
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


def test_health_freshness_is_rechecked_at_exact_merge_boundary(tmp_path: Path) -> None:
    service, api, checks, _spool = _transaction_fixture(tmp_path, "success")

    class BoundaryState(FakeAdmissionState):
        def read(self) -> dict[str, Any]:
            return {**super().read(), "updated_at": "2026-08-26T11:59:00Z"}

    api.current_now = NOW + timedelta(minutes=4, seconds=30)
    with pytest.raises(broker.BrokerError, match="state is stale"):
        service._process_pull(
            check_controller=checks,  # type: ignore[arg-type]
            number=81,
            provider_now=NOW + timedelta(minutes=2),
            settings_token="token",
            state_branch=BoundaryState(),  # type: ignore[arg-type]
            token="token",
        )
    assert api.merge_calls == 0
    assert checks.succeeded == []


@pytest.mark.parametrize(
    ("status", "conclusion", "message"),
    [
        ("in_progress", None, "companion workflows are still pending"),
        ("completed", "failure", "aggregate is not successful"),
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
    [("in_progress", None), ("completed", "failure")],
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

    with pytest.raises(broker.BrokerError, match="weekly deep-health attempt is not successful"):
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
            return broker.ApiResult({}, 200, [{"merge_commit_sha": MERGE_SHA, "number": 81}])
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


def test_current_ci_selects_a_newer_active_rerun(tmp_path: Path) -> None:
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
                "id": 20,
            }
            return [
                {
                    **common,
                    "conclusion": "success",
                    "run_attempt": 1,
                    "status": "completed",
                },
                {
                    **common,
                    "conclusion": None,
                    "run_attempt": 2,
                    "status": "in_progress",
                },
            ]

    reconciler = broker.HealthReconciler(
        api=CurrentCiApi(),
        config=_config(tmp_path),
        spool=broker.DurableSpool(tmp_path / "spool"),
        state_branch=FakeStateBranch(),  # type: ignore[arg-type]
        token="token",
    )

    assert reconciler._current_ci(BASE_SHA)["run_attempt"] == 2  # type: ignore[index]
    assert "status=" not in paths[0]


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
