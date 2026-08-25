# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_operator_refreshes_run_root_when_runner_connects_late():
    text = (ROOT / "web" / "dashboard" / "operator.js").read_text(encoding="utf-8")
    match = re.search(
        r"async function checkRunner\(\) \{(?P<body>.*?)\n\}\n\nfunction setRunnerDisconnected",
        text,
        re.DOTALL,
    )

    assert match is not None
    body = match.group("body")
    assert "const wasConnected = state.runnerConnected;" in body
    assert "if (!wasConnected) await refreshLatestRun();" in body


def test_operator_doctor_summary_chips_use_explicit_summary_counts():
    if shutil.which("node") is None:
        pytest.skip("node is required to exercise dashboard JavaScript")

    script = r"""
const fs = require('fs');
const text = fs.readFileSync('web/dashboard/operator.js', 'utf8');
const start = text.indexOf('function parsePreflightSummaryCounts');
const end = text.indexOf('/** Parse pass/warn/fail counts', start);
if (start < 0 || end < 0) process.exit(2);
eval(text.slice(start, end));

const stdout = `Metriplane Doctor - Installation Readiness
==================================================
Installation: installed distribution
Required for the bundled camera-free demo:
✅ PASS: Python 3.12.3
✅ PASS: metriplane import successful
✅ PASS: Required dependencies available (5 modules)
✅ PASS: Bundled demo resources available (6 files)
Summary: 4 passed, 0 warnings, 0 failed

Optional capabilities:
○ OPTIONAL: Source-checkout development checks skipped for installed distribution
✅ AVAILABLE: Ports 8000, 8001, 8765 available
○ OPTIONAL: No /dev/video* devices found (not needed for the bundled camera-free demo)
○ OPTIONAL: nvidia-smi not available (GPU is optional for the bundled demo)
Optional: 1 available, 3 unavailable or not configured
==================================================

Ready for the bundled camera-free demo.`;

console.log(JSON.stringify(parsePreflightSummaryCounts(stdout)));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {"passed": 4, "warned": 0, "failed": 0}
