# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.audit_ui_functionality import discover_pages


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PAGE_COUNT = 12


def chromium_executable(playwright) -> Path | None:
    bundled = Path(playwright.chromium.executable_path)
    if bundled.is_file():
        return bundled
    system = shutil.which("google-chrome") or shutil.which("chromium")
    return Path(system) if system else None


@contextmanager
def static_dashboard_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_pages_render_without_uncaught_js_errors():
    playwright = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright.sync_playwright
    pages = [page.name for page in discover_pages(ROOT)]
    assert len(pages) == EXPECTED_PAGE_COUNT
    errors: list[str] = []
    current_page = [""]
    with static_dashboard_server() as base_url, sync_playwright() as pw:
        executable = chromium_executable(pw)
        if executable is None:
            pytest.skip("Playwright Chromium browser is not installed")
        browser = pw.chromium.launch(executable_path=str(executable))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda exc: errors.append(f"{current_page[0]}: {exc}"))
        for dashboard_page in pages:
            current_page[0] = dashboard_page
            page.goto(f"{base_url}/web/dashboard/{dashboard_page}")
            page.wait_for_load_state("domcontentloaded")
            assert page.locator("body").is_visible()
        browser.close()
    assert errors == []


def test_hostile_run_fields_cannot_execute_or_read_runner_capability():
    playwright = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright.sync_playwright
    payload = (
        '<img src="x" onerror="window.__metriplane_xss = '
        "sessionStorage.getItem('metriplane.runner.capability')\">"
    )
    responses = {
        "/operator/live-summary": {
            "run_id": payload,
            "objects_count": 1,
            "alerts_count": 1,
            "health": {"overall": payload},
        },
        "/operator/incidents": {
            "incidents": [
                {
                    "incident_id": payload,
                    "rule_id": payload,
                    "severity": payload,
                    "object_ids": [payload],
                    "opened_ts": 0.0,
                }
            ]
        },
        "/operator/camera-trust": {
            "camera_trust": {
                "camera_scores": {
                    "hostile": {
                        "camera_id": payload,
                        "status": payload,
                        "score": payload,
                    }
                },
                "recommendations": [payload],
            }
        },
        "/operator/frames": {"frames": [], "incidents": [], "workspace": None},
        "/operator/traces": {"traces": [{"object_id": payload, "marker_id": payload}]},
        "/operator/objects": {
            "objects": [{"object_id": payload, "type": payload, "zone": payload}]
        },
    }

    with static_dashboard_server() as base_url, sync_playwright() as pw:
        executable = chromium_executable(pw)
        if executable is None:
            pytest.skip("Playwright Chromium browser is not installed")
        browser = pw.chromium.launch(executable_path=str(executable))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        def route_runner(route):
            from urllib.parse import urlsplit

            path = urlsplit(route.request.url).path
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
                body=json.dumps(responses.get(path, {})),
            )

        page.route("http://localhost:9000/**", route_runner)
        page.goto(
            f"{base_url}/web/dashboard/command_center_live.html"
            "#capability=private-browser-capability"
        )
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function("document.querySelector('#stats')?.textContent.includes('<img')")

        assert page.evaluate("window.__metriplane_xss") is None
        assert page.locator("img[src='x']").count() == 0
        assert page.locator("#stats").text_content() is not None
        assert payload in page.locator("#stats").text_content()
        browser.close()


def test_hostile_runtime_and_job_fields_remain_text():
    playwright = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright.sync_playwright
    payload = (
        '<img src="x" onerror="window.__metriplane_xss = '
        "sessionStorage.getItem('metriplane.runner.capability')\">"
    )

    with static_dashboard_server() as base_url, sync_playwright() as pw:
        executable = chromium_executable(pw)
        if executable is None:
            pytest.skip("Playwright Chromium browser is not installed")
        browser = pw.chromium.launch(executable_path=str(executable))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{base_url}/web/dashboard/runtime.html#capability=private-browser-capability")
        page.wait_for_load_state("domcontentloaded")
        page.evaluate(
            """payload => {
                updateObjectsTable([{id: payload, x_m: 1, y_m: 2, confidence: 1}]);
                updateZoneEvents([{event_type: payload, zone_id: payload, object_id: payload}]);
                updateHealth({overall: 'OK', components: {[payload]: {status: payload}}});
                parseManifest(`demo_id,sha,status,c3,c4,c5,c6,c7,c8,c9,metric_key,metric_value\n${payload},sha,${payload},,,,,,,,${payload},${payload}`);
                updateCameraTelemetry([{camera_id: payload, detections: payload}]);
            }""",
            payload,
        )

        assert page.evaluate("window.__metriplane_xss") is None
        assert page.locator("img[src='x']").count() == 0
        assert payload in (page.locator("#objects-tbody").text_content() or "")

        def route_runner(route):
            from urllib.parse import urlsplit

            path = urlsplit(route.request.url).path
            if path == "/jobs":
                body = {"jobs": [{"command_id": payload, "status": payload}]}
            elif path == "/status":
                body = {"status": "idle", "current_job": None}
            elif path == "/commands":
                body = {"commands": []}
            else:
                body = {}
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
                body=json.dumps(body),
            )

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("http://localhost:9000/**", route_runner)
        page.goto(f"{base_url}/web/dashboard/settings.html#capability=private-browser-capability")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_function(
            "document.querySelector('[data-jobs-list]')?.textContent.includes('<img')"
        )

        assert page.evaluate("window.__metriplane_xss") is None
        assert page.locator("img[src='x']").count() == 0
        assert payload in (page.locator("[data-jobs-list]").text_content() or "")
        browser.close()
