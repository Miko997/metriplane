# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_functional_inventory.py"


def _run(tmp_path: Path, base_sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repository-root",
            str(ROOT),
            "--task-id",
            "MP2-016",
            "--base-sha",
            base_sha,
            "--inventory",
            "docs/status/functional-inventory.json",
            "--profiles",
            "docs/status/support-profiles.json",
            "--out",
            str(tmp_path / "result.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_current_exact_base_is_ready_and_read_only(tmp_path: Path) -> None:
    before = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = _run(tmp_path, head)
    assert result.returncode == 0
    assert json.loads((tmp_path / "result.json").read_text())["verdict"] == "READY"
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT) == before


def test_wrong_base_is_blocked_before_inventory_use(tmp_path: Path) -> None:
    result = _run(tmp_path, "0" * 40)
    assert result.returncode == 3
    payload = json.loads((tmp_path / "result.json").read_text())
    assert payload["verdict"] == "BLOCKED_NOT_READY"
    assert payload["checks"] == {"base_is_head": False, "functional_inventory_current": False}


def test_result_is_never_overwritten(tmp_path: Path) -> None:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert _run(tmp_path, head).returncode == 0
    assert _run(tmp_path, head).returncode == 2


def test_malformed_base_is_invalid_input(tmp_path: Path) -> None:
    assert _run(tmp_path, "x" * 40).returncode == 2
    assert not (tmp_path / "result.json").exists()
