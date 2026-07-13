<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Full Maintainer Test Gate

This gate is separate from the camera-free core artifact reproduction. It adds
pytest, Playwright, Chromium, and browser system dependencies. The exact
`v0.2.0` tag does not define a development dependency extra, so use the explicit
sequence retained by the archived Linux CI workflow:

```bash
python -m pip install -e .
python -m pip install pytest playwright
python -m playwright install chromium --with-deps
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

The included author-run evidence records `580 passed` on Ubuntu 24.04 with
Python 3.12.3. A public macOS/Python 3.13.7 reproduction completed the core
workflow but reported `575 passed, 3 skipped, 2 failed` for the full suite. That
public run is therefore classified as independent reproduction of the core
workflow with test-suite caveats, not an independently passing full maintainer
gate.
