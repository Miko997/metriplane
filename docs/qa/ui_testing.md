<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Testing

The core UI audit uses Python-only static analysis and runner/operator API
tests. Playwright smoke coverage is optional because browser binaries are not a
runtime dependency of MetriPlane.

Install optional browser test dependencies:

```bash
python -m pip install playwright pytest
python -m playwright install chromium
```

Run the optional smoke test with the local dashboard server already started:

```bash
python -m metriplane.cli start --no-open
python -m pytest tests/e2e -q
```

If Playwright is not installed, `tests/e2e/test_dashboard_playwright_smoke.py`
is skipped automatically.

A skipped Playwright run is not final browser release evidence. Use it as an
environment note, then capture browser evidence from an environment with
Playwright and Chromium installed.
