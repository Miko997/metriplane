# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_sentinel_summary(summary: dict[str, Any], run_dir: str | Path) -> Path:
    """Write a sentinel_summary.json into run_dir and return its path."""
    d = Path(run_dir)
    d.mkdir(parents=True, exist_ok=True)
    out = d / "sentinel_summary.json"
    out.write_text(json.dumps(summary, indent=2))
    return out


def read_sentinel_summary(run_dir: str | Path) -> dict[str, Any]:
    value = json.loads((Path(run_dir) / "sentinel_summary.json").read_text())
    if not isinstance(value, dict):
        raise ValueError("sentinel summary must contain a JSON object")
    return value
