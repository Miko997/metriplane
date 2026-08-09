# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from metriplane.runner.executor import CommandExecutor


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_cancelled_job_remains_cancelled_after_process_exits(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "cancel-test",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=60,
    )
    assert _wait_until(lambda: executor.current_job is not None and executor.current_job.get("process") is not None)

    assert executor.cancel(job_id) is True
    assert _wait_until(lambda: executor.get_job(job_id)["exit_code"] is not None)  # type: ignore[index]
    time.sleep(0.05)

    job = executor.get_job(job_id)
    assert job is not None
    assert job["status"] == "cancelled"
    assert "CANCELLED by user" in job["stderr"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_cancel_terminates_child_process_group(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    code = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute("group-cancel-test", [sys.executable, "-c", code], timeout_s=60)
    assert _wait_until(child_pid_file.exists)
    child_pid = int(child_pid_file.read_text())

    assert executor.cancel(job_id) is True
    assert _wait_until(
        lambda: not Path(f"/proc/{child_pid}").exists()
        or Path(f"/proc/{child_pid}/stat").read_text().split()[2] == "Z"
    )
    assert executor.get_job(job_id)["status"] == "cancelled"  # type: ignore[index]
