# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from metriplane.paths import PlatformPaths
from metriplane.runner.executor import CommandExecutor


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _process_is_gone_or_zombie(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text().split()
    except (FileNotFoundError, ProcessLookupError):
        return True
    return len(fields) > 2 and fields[2] == "Z"


def test_process_disappearance_during_proc_read_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def vanished(_path: Path) -> str:
        raise ProcessLookupError

    monkeypatch.setattr(Path, "read_text", vanished)
    assert _process_is_gone_or_zombie(12345) is True


def test_cancelled_job_remains_cancelled_after_process_exits(tmp_path: Path) -> None:
    executor = CommandExecutor()
    executor.repo_root = tmp_path
    job_id = executor.execute(
        "cancel-test",
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_s=60,
    )
    assert _wait_until(
        lambda: executor.current_job is not None and executor.current_job.get("process") is not None
    )

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
    assert _wait_until(lambda: _process_is_gone_or_zombie(child_pid))
    assert executor.get_job(job_id)["status"] == "cancelled"  # type: ignore[index]


def test_injected_runner_paths_override_ambient_runs_for_subprocess(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    ).with_runs_dir(tmp_path / "launcher-recordings")
    monkeypatch.setenv("RUNS", str(tmp_path / "ambient-recordings"))
    executor = CommandExecutor(paths=paths)
    executor.repo_root = tmp_path

    job_id = executor.execute(
        "print-runs",
        [sys.executable, "-c", "import os; print(os.environ['RUNS'])"],
        timeout_s=10,
    )

    assert _wait_until(
        lambda: (
            executor.get_job(job_id) is not None and executor.get_job(job_id)["status"] != "running"
        )  # type: ignore[index]
    )
    job = executor.get_job(job_id)
    assert job is not None
    assert job["status"] == "succeeded"
    assert job["stdout"].strip() == str(paths.runs_dir)
