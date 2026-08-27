<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Testing

Generated deterministically by `python tools/audit_ui_functionality.py --write`.

Canonical projection SHA-256: `599b8d03e68dc6f6c3027e7544951f4eee0aff67bc916918feaf87fd2451ff76`

Check committed current status without writing:

```bash
python tools/audit_ui_functionality.py --check
```

Regenerate the functional registry, support profile, and five QA documents:

```bash
python tools/audit_ui_functionality.py --write
```

Run the complete 12-page browser smoke:

```bash
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
python -m playwright install chromium
python -m pytest -q tests/e2e/test_dashboard_playwright_smoke.py
```

The static census does not establish runtime behavior or browser, platform, environment, ROS 2, simulator, or container support. A skipped browser test is an environment note, not final MP2-012 browser evidence.

The checksum-bound v0.2 files `evidence/experiments/ui_coverage_latest.csv` and `evidence/experiments/ui_coverage_latest.json` are historical evidence. The generator rejects them as output destinations and never updates their manifest or checksums.
