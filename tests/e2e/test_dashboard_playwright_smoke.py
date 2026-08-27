# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright


@contextmanager
def static_dashboard_server():
    root = Path(__file__).resolve().parents[2]
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
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
    pages = [
        "index.html",
        "operator.html",
        "runtime.html",
        "atlas.html",
        "integrations.html",
        "benchmarks.html",
        "settings.html",
        "help.html",
    ]
    errors: list[str] = []
    with static_dashboard_server() as base_url, sync_playwright() as pw:
        chromium_executable = Path(pw.chromium.executable_path)
        if not chromium_executable.is_file():
            pytest.skip("Playwright Chromium browser is not installed")
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        for dashboard_page in pages:
            page.goto(f"{base_url}/web/dashboard/{dashboard_page}")
            page.wait_for_load_state("domcontentloaded")
            assert page.locator("body").is_visible()
        browser.close()
    assert errors == []
