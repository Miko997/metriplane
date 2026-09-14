# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.audit_ui_functionality import discover_pages


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PAGE_COUNT = 12


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
        chromium_executable = Path(pw.chromium.executable_path)
        if not chromium_executable.is_file():
            pytest.skip("Playwright Chromium browser is not installed")
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda exc: errors.append(f"{current_page[0]}: {exc}"))
        for dashboard_page in pages:
            current_page[0] = dashboard_page
            page.goto(f"{base_url}/web/dashboard/{dashboard_page}")
            page.wait_for_load_state("domcontentloaded")
            assert page.locator("body").is_visible()
        browser.close()
    assert errors == []
