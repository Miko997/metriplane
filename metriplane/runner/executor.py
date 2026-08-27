# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Command executor for Dashboard V2 Runner

Executes allowlisted commands with timeout, output capture, and cancellation support.
Uses subprocess without shell=True for security.
"""

import subprocess
import signal
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from collections import deque
import os
import pathlib

from metriplane.paths import PlatformPaths


def _popen_group_options() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))}
    return {}


def _signal_process_group(process: subprocess.Popen[str], *, force: bool) -> None:
    """Stop a job and its children on POSIX, with portable fallbacks."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(os.getpgid(process.pid), sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    elif os.name == "nt":
        taskkill = ["taskkill", "/PID", str(process.pid), "/T"]
        if force:
            taskkill.append("/F")
        try:
            subprocess.run(taskkill, capture_output=True, timeout=5, check=False)
            return
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        process.kill() if force else process.terminate()
    except (ProcessLookupError, OSError):
        pass


def _terminate_process_group(process: subprocess.Popen[str], *, grace_s: float = 0.5) -> None:
    _signal_process_group(process, force=False)
    try:
        process.wait(timeout=max(0.0, grace_s))
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_process_group(process, force=True)


def find_repo_root() -> pathlib.Path:
    """
    Find repository root by walking upward until we find pyproject.toml and tools/mp.sh.
    Returns absolute path to repo root.
    """
    current = pathlib.Path(__file__).resolve()

    # Walk up from metriplane/runner/executor.py
    for parent in current.parents:
        if (parent / "pyproject.toml").exists() and (parent / "tools" / "mp.sh").exists():
            return parent

    # Fallback: assume current working directory
    return pathlib.Path.cwd()


class CommandExecutor:
    """Executes allowlisted commands with timeout and output capture"""

    def __init__(
        self,
        max_history: int = 20,
        *,
        paths: PlatformPaths | None = None,
    ):
        self.current_job: Optional[Dict[str, Any]] = None
        self.job_history: deque[dict[str, Any]] = deque(
            maxlen=max_history
        )  # Keep last N completed jobs
        self.lock = threading.Lock()
        self.repo_root = find_repo_root()
        self._platform_paths = paths

    @property
    def platform_paths(self) -> PlatformPaths | None:
        with self.lock:
            return self._platform_paths

    def configure_platform_paths(self, paths: PlatformPaths) -> None:
        with self.lock:
            self._platform_paths = paths

    def _command_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        paths = self.platform_paths
        if paths is not None:
            environment["RUNS"] = str(paths.runs_dir)
        return environment

    def is_running(self) -> bool:
        """Check if a command is currently running"""
        with self.lock:
            if self.current_job is None:
                return False
            # Check if still running or completed
            status = self.current_job.get("status")
            return status == "running"

    def get_current_job_id(self) -> Optional[str]:
        """Get current job ID if running"""
        with self.lock:
            if self.current_job:
                return self.current_job.get("job_id")
            return None

    def execute(
        self,
        command_id: str,
        command: list[str],
        timeout_s: int,
        *,
        pass_fds: tuple[int, ...] = (),
    ) -> str:
        """
        Execute command and return job_id immediately.
        Raises ValueError if already running.

        Args:
            command_id: Identifier for the command
            command: Command as list of arguments (not shell string)
            timeout_s: Maximum execution time in seconds
            pass_fds: POSIX descriptors whose ownership transfers after the
                background thread starts successfully

        Returns:
            job_id: Unique identifier for this execution
        """
        inherited_fds = tuple(dict.fromkeys(pass_fds))
        if inherited_fds and os.name != "posix":
            raise OSError("inherited descriptors require a POSIX subprocess")
        for file_fd in inherited_fds:
            if not isinstance(file_fd, int) or file_fd < 0:
                raise ValueError("pass_fds must contain open non-negative descriptors")
            os.fstat(file_fd)

        print(f"[Executor] execute() called for command_id: {command_id}")
        print("[Executor] Before acquiring lock")

        # Check and create job atomically
        # CRITICAL: Do NOT call self.is_running() here - it will deadlock!
        with self.lock:
            print("[Executor] Lock acquired")

            # Check directly without calling is_running() to avoid deadlock
            if self.current_job is not None and self.current_job.get("status") == "running":
                print("[Executor] Another command already running, rejecting")
                raise ValueError("Another command is already running")

            # Move completed job to history before starting new one
            if self.current_job is not None:
                status = self.current_job.get("status")
                if status in ("succeeded", "failed", "timed_out", "cancelled"):
                    print(
                        f"[Executor] Moving completed job {self.current_job['job_id']} to history"
                    )
                    # Remove process handle before archiving (not serializable/relevant)
                    archived_job = self.current_job.copy()
                    archived_job.pop("process", None)
                    archived_job.pop("command", None)  # Don't need command list in history
                    self.job_history.append(archived_job)
                    print(f"[Executor] Job history size: {len(self.job_history)}")

            # Generate unique job ID
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            job_id = f"job_{timestamp}_{command_id}"
            print(f"[Executor] Job created: {job_id}")

            # Initialize job record
            self.current_job = {
                "job_id": job_id,
                "command_id": command_id,
                "command": command,
                "started_at": datetime.now(),
                "completed_at": None,
                "status": "running",
                "process": None,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "timeout_s": timeout_s,
            }
            print("[Executor] Job record created")
        # Lock released here - critical!
        print("[Executor] Lock released")

        # Start async execution (no lock held)
        print(f"[Executor] Starting background thread for: {job_id}")
        thread = threading.Thread(
            target=self._run_command,
            args=(job_id, command, timeout_s, inherited_fds),
            daemon=True,
        )
        try:
            thread.start()
        except BaseException:
            with self.lock:
                if self.current_job is not None and self.current_job["job_id"] == job_id:
                    self.current_job["status"] = "failed"
                    self.current_job["completed_at"] = self.current_job["started_at"]
                    self.current_job["stderr"] = "Execution thread could not be started"
                    self.current_job["exit_code"] = -1
            raise
        print(f"[Executor] Background thread started for: {job_id}")
        print(f"[Executor] Returning job_id: {job_id}")

        return job_id

    def _run_command(
        self,
        job_id: str,
        command: list[str],
        timeout_s: int,
        pass_fds: tuple[int, ...] = (),
    ) -> None:
        """Background thread for command execution"""
        print(f"[Executor] Background thread running for: {job_id}")

        job = self.current_job
        if not job or job["job_id"] != job_id:
            print(f"[Executor] Job mismatch, aborting: {job_id}")
            for file_fd in pass_fds:
                os.close(file_fd)
            return

        try:
            print(f"[Executor] Subprocess starting: {' '.join(command)}")
            # Execute without shell=True (security: no shell injection)
            popen_options: dict[str, Any] = _popen_group_options()
            if pass_fds:
                popen_options["pass_fds"] = pass_fds
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(self.repo_root),
                    env=self._command_environment(),
                    **popen_options,
                )
            finally:
                for file_fd in pass_fds:
                    os.close(file_fd)
            print(f"[Executor] Subprocess spawned, PID: {process.pid}")

            # Store process for cancellation
            with self.lock:
                if job["status"] == "running":
                    job["process"] = process
                    cancelled_before_start = False
                else:
                    cancelled_before_start = job["status"] == "cancelled"

            if cancelled_before_start:
                _terminate_process_group(process)
                stdout, stderr = process.communicate()
                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = process.returncode
                return

            # Wait with timeout
            try:
                stdout, stderr = process.communicate(timeout=timeout_s)
                exit_code = process.returncode
                print(f"[Executor] Subprocess completed: {job_id}, exit_code={exit_code}")

                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = exit_code
                    if job["status"] != "cancelled":
                        job["status"] = "succeeded" if exit_code == 0 else "failed"
                        job["completed_at"] = datetime.now()

            except subprocess.TimeoutExpired:
                # Kill on timeout
                _terminate_process_group(process)
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.SubprocessError:
                    stdout, stderr = "", ""

                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = -1
                    if job["status"] != "cancelled":
                        job["stderr"] += "\n[TIMEOUT: Command exceeded {}s limit]".format(timeout_s)
                        job["status"] = "timed_out"
                        job["completed_at"] = datetime.now()

        except Exception as e:
            with self.lock:
                if job["status"] != "cancelled":
                    job["status"] = "failed"
                    job["stderr"] = f"Execution error: {str(e)}"
                    job["exit_code"] = -1
                    job["completed_at"] = datetime.now()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job status by job_id.
        Searches current job first, then job history.
        Returns None if job not found.
        """
        with self.lock:
            # Check current job first
            if self.current_job and self.current_job["job_id"] == job_id:
                # Return a copy to avoid external mutation
                return self.current_job.copy()

            # Search job history (newest to oldest)
            for job in reversed(self.job_history):
                if job["job_id"] == job_id:
                    return job.copy()

            return None

    def get_recent_jobs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get recent jobs (newest first).

        Args:
            limit: Maximum number of jobs to return (None = all)

        Returns:
            List of job summaries (no stdout/stderr)
        """
        with self.lock:
            jobs: list[dict[str, Any]] = []

            # Add current job if exists
            if self.current_job:
                job_summary = {
                    "job_id": self.current_job["job_id"],
                    "command_id": self.current_job["command_id"],
                    "status": self.current_job["status"],
                    "started_at": self.current_job["started_at"],
                    "completed_at": self.current_job.get("completed_at"),
                    "exit_code": self.current_job.get("exit_code"),
                }
                jobs.append(job_summary)

            # Add history (newest first)
            for job in reversed(self.job_history):
                job_summary = {
                    "job_id": job["job_id"],
                    "command_id": job["command_id"],
                    "status": job["status"],
                    "started_at": job["started_at"],
                    "completed_at": job.get("completed_at"),
                    "exit_code": job.get("exit_code"),
                }
                jobs.append(job_summary)

            # Apply limit if specified
            if limit:
                jobs = jobs[:limit]

            return jobs

    def get_last_completed_job(self) -> Optional[Dict[str, Any]]:
        """Get the most recent completed job (for status display)"""
        with self.lock:
            # Check if current job is completed
            if self.current_job:
                status = self.current_job.get("status")
                if status in ("succeeded", "failed", "timed_out", "cancelled"):
                    return {
                        "job_id": self.current_job["job_id"],
                        "command_id": self.current_job["command_id"],
                        "status": status,
                        "completed_at": self.current_job.get("completed_at"),
                        "exit_code": self.current_job.get("exit_code"),
                    }

            # Otherwise return most recent from history
            if len(self.job_history) > 0:
                job = self.job_history[-1]  # Most recent
                return {
                    "job_id": job["job_id"],
                    "command_id": job["command_id"],
                    "status": job["status"],
                    "completed_at": job.get("completed_at"),
                    "exit_code": job.get("exit_code"),
                }

            return None

    def cancel(self, job_id: str) -> bool:
        """
        Cancel running job by job_id.
        Returns True if cancelled, False if not found or not running.
        """
        process: subprocess.Popen[str] | None
        with self.lock:
            if not self.current_job or self.current_job["job_id"] != job_id:
                return False

            if self.current_job["status"] != "running":
                return False

            process = self.current_job.get("process")
            self.current_job["status"] = "cancelled"
            self.current_job["completed_at"] = datetime.now()
            self.current_job["stderr"] += "\n[CANCELLED by user]"

        if process is not None:
            try:
                _terminate_process_group(process)
            except Exception as exc:
                with self.lock:
                    if self.current_job and self.current_job["job_id"] == job_id:
                        self.current_job["stderr"] += f"\n[Cancel cleanup failed: {exc}]"
        return True

    def clear_completed_job(self) -> None:
        """Clear current job if it's completed (for cleanup)"""
        with self.lock:
            if self.current_job:
                status = self.current_job.get("status")
                if status in ("succeeded", "failed", "timed_out", "cancelled"):
                    # Keep for a bit for polling, but flag as clearable
                    pass
