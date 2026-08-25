# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Tests that the metrics/health HTTP server returns CORS headers on all responses.

Covers:
- GET /metrics  → 200 + Access-Control-Allow-Origin: *
- GET /health   → 200 + Access-Control-Allow-Origin: *
- OPTIONS /metrics → 204 + Access-Control-Allow-Origin: *
- GET /notfound → 404 + Access-Control-Allow-Origin: *

Uses start_metrics_server from metriplane/metrics.py (the live-fusion path).
"""
from __future__ import annotations

import socket
import threading
import urllib.request
from typing import Callable

import pytest

from metriplane.metrics import MetricsRegistry, start_metrics_server


def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_server(*, get_health: Callable | None = None):
    """Start a test server instance and return (server, port)."""
    registry = MetricsRegistry()
    registry.update(fps=10.0, objects_tracked=1, frames_total=5, frames_dropped_total=0)
    port = _free_port()
    server = start_metrics_server(
        host="127.0.0.1",
        port=port,
        registry=registry,
        get_ws_clients=lambda: 0,
        get_health=get_health,
    )
    return server, port


def _head_request(url: str) -> dict[str, str]:
    """Return response headers (lowercase keys) for a GET request."""
    with urllib.request.urlopen(url, timeout=3) as resp:
        return {k.lower(): v for k, v in resp.headers.items()}


def _options_request(url: str) -> tuple[int, dict[str, str]]:
    """Issue an OPTIONS request; return (status, headers)."""
    req = urllib.request.Request(url, method="OPTIONS")
    # urllib follows redirects but 204 is not a redirect; disable error raising for 4xx/2xx manually
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def _get_request_status_and_headers(url: str) -> tuple[int, dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def metrics_server():
    """Server with health endpoint enabled."""
    health_payload = {"overall": "OK", "components": {"camera": {"status": "OK"}}}
    server, port = _make_server(get_health=lambda: health_payload)
    yield port
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def metrics_server_no_health():
    """Server without health endpoint (get_health=None)."""
    server, port = _make_server(get_health=None)
    yield port
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# /metrics CORS
# ---------------------------------------------------------------------------

class TestMetricsEndpointCORS:
    def test_metrics_ok(self, metrics_server):
        port = metrics_server
        status, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/metrics")
        assert status == 200

    def test_metrics_cors_origin(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/metrics")
        assert headers.get("access-control-allow-origin") == "*", (
            f"Expected Access-Control-Allow-Origin: * on /metrics, got headers: {headers}"
        )

    def test_metrics_cors_methods(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/metrics")
        assert "GET" in headers.get("access-control-allow-methods", "")

    def test_metrics_cache_control(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/metrics")
        assert headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# /health CORS
# ---------------------------------------------------------------------------

class TestHealthEndpointCORS:
    def test_health_ok(self, metrics_server):
        port = metrics_server
        status, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert status == 200

    def test_health_cors_origin(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert headers.get("access-control-allow-origin") == "*", (
            f"Expected Access-Control-Allow-Origin: * on /health, got headers: {headers}"
        )

    def test_health_cors_methods(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert "GET" in headers.get("access-control-allow-methods", "")

    def test_health_cache_control(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert headers.get("cache-control") == "no-store"

    def test_health_content_type_json(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert "application/json" in headers.get("content-type", "")


# ---------------------------------------------------------------------------
# OPTIONS preflight CORS
# ---------------------------------------------------------------------------

class TestOptionsPreflightCORS:
    def test_options_metrics_204(self, metrics_server):
        port = metrics_server
        status, _ = _options_request(f"http://127.0.0.1:{port}/metrics")
        assert status == 204

    def test_options_metrics_cors_origin(self, metrics_server):
        port = metrics_server
        _, headers = _options_request(f"http://127.0.0.1:{port}/metrics")
        assert headers.get("access-control-allow-origin") == "*"

    def test_options_health_204(self, metrics_server):
        port = metrics_server
        status, _ = _options_request(f"http://127.0.0.1:{port}/health")
        assert status == 204

    def test_options_health_cors_origin(self, metrics_server):
        port = metrics_server
        _, headers = _options_request(f"http://127.0.0.1:{port}/health")
        assert headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# 404 paths also include CORS headers
# ---------------------------------------------------------------------------

class TestNotFoundCORS:
    def test_notfound_404(self, metrics_server):
        port = metrics_server
        status, _ = _get_request_status_and_headers(f"http://127.0.0.1:{port}/notfound")
        assert status == 404

    def test_notfound_cors_origin(self, metrics_server):
        port = metrics_server
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/notfound")
        assert headers.get("access-control-allow-origin") == "*"


# ---------------------------------------------------------------------------
# Server without health: /health returns 404 but still has CORS
# ---------------------------------------------------------------------------

class TestNoHealthServerCORS:
    def test_health_404_when_no_get_health(self, metrics_server_no_health):
        port = metrics_server_no_health
        status, _ = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert status == 404

    def test_health_404_still_has_cors(self, metrics_server_no_health):
        port = metrics_server_no_health
        _, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/health")
        assert headers.get("access-control-allow-origin") == "*"

    def test_metrics_still_ok_without_health(self, metrics_server_no_health):
        port = metrics_server_no_health
        status, headers = _get_request_status_and_headers(f"http://127.0.0.1:{port}/metrics")
        assert status == 200
        assert headers.get("access-control-allow-origin") == "*"
