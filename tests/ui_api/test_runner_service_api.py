# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from metriplane.runner import service
from metriplane.runner.executor import CommandExecutor


@contextmanager
def runner_server():
    original_executor = service.executor
    service.executor = CommandExecutor()
    server = service.LocalHTTPServer(("127.0.0.1", 0), service.RunnerHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.executor = original_executor


def request_json(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_status_shape_is_stable():
    with runner_server() as base:
        status, payload = request_json(f"{base}/status")
    assert status == 200
    assert payload["service"] == "metriplane-runner"
    assert payload["status"] in {"idle", "running"}
    assert "repo_root" in payload
    assert "job_history_size" in payload
    assert payload["session_token"]


def test_commands_shape_exposes_allowlist_metadata():
    with runner_server() as base:
        status, payload = request_json(f"{base}/commands")
    assert status == 200
    assert payload["commands"]
    first = payload["commands"][0]
    assert {"id", "title", "enabled", "timeout_s", "requires_gpu", "requires_cameras"} <= set(first)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, "Missing command_id"),
        ({"command_id": "../doctor"}, "Invalid or unknown command_id"),
        ({"command_id": "health-degrade-cam1"}, "disabled"),
    ],
)
def test_execute_rejects_bad_or_disabled_command_ids(payload: dict, expected: str):
    with runner_server() as base:
        _, runner_status = request_json(f"{base}/status")
        status, body = request_json(
            f"{base}/execute",
            method="POST",
            payload=payload,
            headers={service.TOKEN_HEADER: runner_status["session_token"]},
        )
    assert status == 400
    assert expected in body["error"]


def test_mutating_request_requires_session_token():
    with runner_server() as base:
        request = urllib.request.Request(
            f"{base}/execute",
            data=json.dumps({"command_id": "doctor"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=5)
        response = exc_info.value
        payload = response.read()
        status = response.code
        body = json.loads(payload)
    assert status == 403
    assert int(response.headers["Content-Length"]) == len(payload)
    assert "session token" in body["error"]


def test_trusted_origin_is_echoed_and_untrusted_origin_is_rejected():
    trusted = "http://127.0.0.1:8088"
    with runner_server() as base:
        request = urllib.request.Request(f"{base}/status", headers={"Origin": trusted})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.headers["Access-Control-Allow-Origin"] == trusted
            token = json.loads(response.read())["session_token"]

        status, body = request_json(
            f"{base}/execute",
            method="POST",
            payload={"command_id": "doctor"},
            headers={
                "Origin": "https://attacker.example",
                service.TOKEN_HEADER: token,
            },
        )
    assert status == 403
    assert body["error"] == "Untrusted browser origin"


def test_request_body_size_is_limited():
    with runner_server() as base:
        _, runner_status = request_json(f"{base}/status")
        status, body = request_json(
            f"{base}/execute",
            method="POST",
            headers={
                service.TOKEN_HEADER: runner_status["session_token"],
                "Content-Length": str(service.MAX_REQUEST_BODY_BYTES + 1),
            },
        )
    assert status == 413
    assert "too large" in body["error"]


def test_runner_refuses_non_loopback_bind():
    assert service.start_runner("0.0.0.0", 0) == 64


def test_numeric_loopback_validation_does_not_require_name_resolution(monkeypatch):
    monkeypatch.setattr(
        service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("resolver unavailable")),
    )

    assert service._is_loopback_bind_host("127.0.0.1", 9000) is True
    assert service._is_loopback_bind_host("::1", 9000) is True
    assert service._is_loopback_bind_host("::ffff:127.0.0.1", 9000) is True


def test_local_runner_bind_does_not_require_reverse_dns(monkeypatch):
    def fail_lookup(_host):
        raise AssertionError("reverse DNS must not run for a loopback server")

    monkeypatch.setattr(service.socket, "getfqdn", fail_lookup)
    server = service.LocalHTTPServer(("127.0.0.1", 0), service.RunnerHTTPHandler)
    try:
        assert server.server_name == "127.0.0.1"
        assert server.server_port > 0
    finally:
        server.server_close()
