# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

import pytest

from metriplane.runner import service
from metriplane.runner.executor import CommandExecutor


@contextmanager
def runner_server():
    original_executor = service.executor
    service.executor = CommandExecutor()
    server = ThreadingHTTPServer(("127.0.0.1", 0), service.RunnerHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.executor = original_executor


def request_json(url: str, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
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
        status, body = request_json(f"{base}/execute", method="POST", payload=payload)
    assert status == 400
    assert expected in body["error"]
