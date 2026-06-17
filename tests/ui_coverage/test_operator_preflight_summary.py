# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


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

const stdout = `Metriplane Doctor - Environment Check
==================================================
✅ PASS: Python 3.12.3
✅ PASS: metriplane import successful
✅ PASS: Git commit 31dfe7d
✅ PASS: tools/mp.sh exists
✅ PASS: configs/fusion_health_300fps.yaml exists
✅ PASS: Ports 8000, 8001, 8765 available
✅ PASS: Camera devices found: /dev/video0, /dev/video1
✅ PASS: GPU available: NVIDIA GeForce RTX 5070 Ti
==================================================
Summary: 8 passed, 0 warnings, 0 failed

✅ All checks passed! Metriplane is ready.`;

console.log(JSON.stringify(parsePreflightSummaryCounts(stdout)));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {"passed": 8, "warned": 0, "failed": 0}
