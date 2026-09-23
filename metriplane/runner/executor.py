# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Command executor for Dashboard V2 Runner

Executes allowlisted commands with timeout, output capture, and cancellation support.
Uses subprocess without shell=True for security.
"""

import ctypes
import subprocess
import signal
import struct
import sys
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from collections import deque
import os
import pathlib

from metriplane.paths import PlatformPaths


_MAX_CAPTURE_CHARS = 1_048_576
_OUTPUT_TRUNCATED = "\n[OUTPUT TRUNCATED: retained the first 1048576 characters]\n"
_MAX_CHILD_PROCESSES = 64
_MAX_CHILD_OPEN_FILES = 512
_POSIX_SUPERVISOR = """\
import os
import resource
import subprocess
import sys

nofile = int(sys.argv[2])
cpu = int(sys.argv[3])
gate_fd = int(sys.argv[4])
inherited_fds = tuple(int(value) for value in sys.argv[5].split(",") if value)
command = sys.argv[6:]
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
if nofile_hard != resource.RLIM_INFINITY:
    nofile = min(nofile, nofile_hard)
resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)[1]
if cpu_hard != resource.RLIM_INFINITY:
    cpu = min(cpu, cpu_hard)
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
if os.read(gate_fd, 1) != b"\\n":
    raise SystemExit(125)
os.close(gate_fd)
try:
    child = subprocess.Popen(command, pass_fds=inherited_fds)
finally:
    for inherited_fd in inherited_fds:
        try:
            os.close(inherited_fd)
        except OSError:
            pass
raise SystemExit(child.wait())
"""


class _DarwinProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _BoundedTextCapture:
    """Drain a child stream without permitting unbounded retained output."""

    def __init__(self, limit: int = _MAX_CAPTURE_CHARS) -> None:
        self._limit = limit
        self._parts: list[str] = []
        self._size = 0
        self._truncated = False

    def append(self, value: str) -> None:
        remaining = self._limit - self._size
        if remaining > 0:
            retained = value[:remaining]
            self._parts.append(retained)
            self._size += len(retained)
        if len(value) > max(0, remaining):
            self._truncated = True

    def value(self) -> str:
        text = "".join(self._parts)
        return text + _OUTPUT_TRUNCATED if self._truncated else text


def _drain_stream(
    stream: Any,
    capture: _BoundedTextCapture,
    errors: list[str],
) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            capture.append(chunk)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        stream.close()


def _parse_linux_proc_stat(value: str) -> tuple[str, int, str] | None:
    """Return state, process group and birth token from one procfs stat row."""
    close = value.rfind(") ")
    if close < 0:
        return None
    fields = value[close + 2 :].split()
    if len(fields) <= 19:
        return None
    try:
        return fields[0], int(fields[2]), fields[19]
    except ValueError:
        return None


def _parse_darwin_procargs(value: bytes) -> list[str] | None:
    """Decode exact KERN_PROCARGS2 argv boundaries without display-string parsing."""
    if len(value) < 4:
        return None
    argc = struct.unpack("=i", value[:4])[0]
    if argc <= 0 or argc > 1_000_000:
        return None
    cursor = value.find(b"\0", 4)
    if cursor < 0:
        return None
    cursor += 1
    while cursor < len(value) and value[cursor] == 0:
        cursor += 1
    argv: list[str] = []
    for _ in range(argc):
        end = value.find(b"\0", cursor)
        if end < 0:
            return None
        argv.append(value[cursor:end].decode("utf-8", errors="surrogateescape"))
        cursor = end + 1
    return argv if all(argv) else None


def _darwin_process_identity(pid: int) -> dict[str, Any] | None:
    """Read exact Darwin birth/executable/argv identity through kernel APIs."""
    if sys.platform != "darwin":
        return None
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_pidinfo.restype = ctypes.c_int
        libproc.proc_pidpath.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        libproc.proc_pidpath.restype = ctypes.c_int
        info = _DarwinProcBsdInfo()
        size = ctypes.sizeof(info)
        if libproc.proc_pidinfo(int(pid), 3, 0, ctypes.byref(info), size) != size:
            return None
        if int(info.pbi_pid) != int(pid):
            return None

        path_buffer = ctypes.create_string_buffer(4096)
        path_size = libproc.proc_pidpath(int(pid), path_buffer, len(path_buffer))
        if path_size <= 0:
            return None

        libc = ctypes.CDLL(None, use_errno=True)
        libc.sysctl.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        libc.sysctl.restype = ctypes.c_int
        mib = (ctypes.c_int * 3)(1, 49, int(pid))
        args_size = ctypes.c_size_t()
        if libc.sysctl(mib, 3, None, ctypes.byref(args_size), None, 0) != 0:
            return None
        if args_size.value <= 4 or args_size.value > 16 * 1024 * 1024:
            return None
        args_buffer = ctypes.create_string_buffer(args_size.value)
        if (
            libc.sysctl(
                mib,
                3,
                args_buffer,
                ctypes.byref(args_size),
                None,
                0,
            )
            != 0
        ):
            return None
        argv = _parse_darwin_procargs(args_buffer.raw[: args_size.value])
        if argv is None:
            return None
        return {
            "pid": int(pid),
            "pgid": int(info.pbi_pgid),
            "birth": f"{int(info.pbi_start_tvsec)}.{int(info.pbi_start_tvusec):06d}",
            "executable": path_buffer.value.decode("utf-8", errors="surrogateescape"),
            "argv": argv,
        }
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def _darwin_process_group_size(pgid: int) -> int | None:
    """Count live Darwin group members through libproc, never display text."""
    if sys.platform != "darwin":
        return None
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_listpgrppids.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_listpgrppids.restype = ctypes.c_int
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_pidinfo.restype = ctypes.c_int
        capacity = libproc.proc_listpgrppids(int(pgid), None, 0)
        if capacity < 0:
            return None
        if capacity == 0:
            return 0
        pids = (ctypes.c_int * (capacity + 16))()
        count = libproc.proc_listpgrppids(int(pgid), pids, ctypes.sizeof(pids))
        if count < 0 or count >= len(pids):
            return None
        members = 0
        for listed_pid in pids[:count]:
            if listed_pid <= 0:
                continue
            info = _DarwinProcBsdInfo()
            size = ctypes.sizeof(info)
            read = libproc.proc_pidinfo(int(listed_pid), 3, 0, ctypes.byref(info), size)
            if read == 0:
                continue
            if read != size:
                return None
            if int(info.pbi_pgid) != int(pgid):
                return None
            if int(info.pbi_status) != 5:
                members += 1
        return members
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


def _process_identity(pid: int) -> dict[str, Any] | None:
    """Read a PID-reuse-resistant POSIX identity for a live process."""
    if os.name != "posix":
        return None
    if sys.platform == "darwin":
        return _darwin_process_identity(pid)
    if pathlib.Path("/proc").is_dir():
        try:
            stat_value = pathlib.Path(f"/proc/{pid}/stat").read_text()
            raw_argv = pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            executable = os.readlink(f"/proc/{pid}/exe")
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError):
            return None
        parsed = _parse_linux_proc_stat(stat_value)
        if parsed is None:
            return None
        _, pgid, birth = parsed
        argv = [item.decode("utf-8", errors="surrogateescape") for item in raw_argv if item]
    else:
        return None
    if not birth or not executable or not argv:
        return None
    return {
        "pid": int(pid),
        "pgid": int(pgid),
        "birth": birth,
        "executable": executable,
        "argv": argv,
    }


def _identity_matches(expected: dict[str, Any] | None) -> bool:
    if expected is None:
        return os.name != "posix"
    current = _process_identity(int(expected["pid"]))
    return current == expected


class _ProcessLimitExceeded(RuntimeError):
    pass


class _ProcessInventoryUnavailable(RuntimeError):
    pass


def _process_group_size(pgid: int) -> int | None:
    if os.name != "posix":
        return None
    if sys.platform == "darwin":
        return _darwin_process_group_size(pgid)
    if not pathlib.Path("/proc").is_dir():
        return None
    count = 0
    try:
        entries = pathlib.Path("/proc").iterdir()
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                parsed = _parse_linux_proc_stat((entry / "stat").read_text())
                if parsed is not None and parsed[0] != "Z" and parsed[1] == pgid:
                    count += 1
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError):
                continue
    except OSError:
        return None
    return count


def _wait_with_limits(
    process: subprocess.Popen[str],
    identity: dict[str, Any] | None,
    timeout_s: int,
) -> None:
    deadline = time.monotonic() + max(0, timeout_s)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout_s)
        try:
            process.wait(timeout=min(0.1, remaining))
            return
        except subprocess.TimeoutExpired:
            if identity is not None:
                size = _process_group_size(int(identity["pgid"]))
                if size is None:
                    raise _ProcessInventoryUnavailable(
                        "child process-group inventory could not be verified"
                    )
                if size > _MAX_CHILD_PROCESSES:
                    raise _ProcessLimitExceeded(
                        f"child process group exceeded {_MAX_CHILD_PROCESSES} processes"
                    )


def _limited_command(
    command: list[str],
    timeout_s: int,
    gate_fd: int | None,
    inherited_fds: tuple[int, ...],
) -> list[str]:
    """Apply limits in a retained supervisor gated before user code starts."""
    if os.name != "posix":
        return command
    if gate_fd is None:
        raise ValueError("POSIX child supervisor requires an identity gate")
    return [
        sys.executable,
        "-c",
        _POSIX_SUPERVISOR,
        "metriplane-child-limit",
        str(_MAX_CHILD_OPEN_FILES),
        str(max(1, int(timeout_s) + 1)),
        str(gate_fd),
        ",".join(str(value) for value in inherited_fds),
        *command,
    ]


def _await_process_identity(
    process: subprocess.Popen[str],
    *,
    timeout: float = 0.5,
) -> dict[str, Any] | None:
    """Retain the gated supervisor identity before any user code can execute."""
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        identity = _process_identity(process.pid)
        if identity is not None:
            return identity
        time.sleep(0.005)
    return None


def _wait_for_group_exit(pgid: int, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        size = _process_group_size(pgid)
        if size == 0:
            return True
        time.sleep(0.02)
    return _process_group_size(pgid) == 0


def _popen_group_options() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))}
    return {}


def _signal_process_group(
    process: subprocess.Popen[str],
    identity: dict[str, Any] | None,
    *,
    force: bool,
) -> None:
    """Stop a job and its children on POSIX, with portable fallbacks."""
    leader_exited = process.poll() is not None
    group_size = _process_group_size(int(identity["pgid"])) if identity is not None else None
    if leader_exited and group_size == 0:
        return
    current_identity = _process_identity(process.pid) if identity is not None else None
    if not leader_exited and current_identity != identity:
        raise RuntimeError(
            "child identity changed before signal; refusing numeric PID/PGID cleanup"
        )
    if leader_exited and current_identity not in (None, identity):
        raise RuntimeError(
            "child PID was reused before process-group cleanup; refusing numeric signal"
        )
    if os.name == "posix":
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            pgid = int(identity["pgid"]) if identity is not None else os.getpgid(process.pid)
            os.killpg(pgid, sig)
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


def _terminate_process_group(
    process: subprocess.Popen[str],
    identity: dict[str, Any] | None,
    *,
    grace_s: float = 0.5,
) -> None:
    _signal_process_group(process, identity, force=False)
    try:
        process.wait(timeout=max(0.0, grace_s))
    except subprocess.TimeoutExpired:
        pass
    pgid = int(identity["pgid"]) if identity is not None else None
    if pgid is None:
        return
    group_size = _process_group_size(pgid)
    if group_size == 0:
        return
    _signal_process_group(process, identity, force=True)
    if not _wait_for_group_exit(pgid):
        raise RuntimeError("child process-group exit could not be verified")


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
        environment: dict[str, str] = {}
        for name in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        paths = self.platform_paths
        if paths is not None:
            home = paths.state_dir / "runner-home"
            home.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(home, 0o700)
            environment.update(
                {
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(paths.config_dir),
                    "XDG_DATA_HOME": str(paths.data_dir),
                    "XDG_CACHE_HOME": str(paths.cache_dir),
                    "XDG_STATE_HOME": str(paths.state_dir),
                }
            )
            environment["RUNS"] = str(paths.runs_dir)
        else:
            environment["HOME"] = str(self.repo_root)
        environment["PYTHONIOENCODING"] = "utf-8"
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

        process: subprocess.Popen[str] | None = None
        identity: dict[str, Any] | None = None
        gate_write_fd: int | None = None
        try:
            print(f"[Executor] Subprocess starting: {' '.join(command)}")
            # Execute without shell=True (security: no shell injection)
            popen_options: dict[str, Any] = _popen_group_options()
            child_fds = list(pass_fds)
            gate_read_fd: int | None = None
            if os.name == "posix":
                gate_read_fd, gate_write_fd = os.pipe()
                child_fds.append(gate_read_fd)
            if child_fds:
                popen_options["pass_fds"] = tuple(child_fds)
            try:
                process = subprocess.Popen(
                    _limited_command(command, timeout_s, gate_read_fd, pass_fds),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="backslashreplace",
                    cwd=str(self.repo_root),
                    env=self._command_environment(),
                    **popen_options,
                )
            finally:
                for file_fd in child_fds:
                    os.close(file_fd)
            print(f"[Executor] Subprocess spawned, PID: {process.pid}")
            identity = _await_process_identity(process)
            if os.name == "posix" and identity is None:
                if gate_write_fd is not None:
                    os.close(gate_write_fd)
                    gate_write_fd = None
                process.kill()
                process.communicate(timeout=5)
                raise RuntimeError("could not retain child birth/executable/argv identity")

            # Store process for cancellation
            with self.lock:
                if job["status"] == "running":
                    job["process"] = process
                    job["process_identity"] = identity
                    cancelled_before_start = False
                else:
                    cancelled_before_start = job["status"] == "cancelled"

            if cancelled_before_start:
                if gate_write_fd is not None:
                    os.close(gate_write_fd)
                    gate_write_fd = None
                _terminate_process_group(process, identity)
                stdout, stderr = process.communicate(timeout=5)
                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = process.returncode
                return

            stdout_capture = _BoundedTextCapture()
            stderr_capture = _BoundedTextCapture()
            reader_errors: list[str] = []
            assert process.stdout is not None
            assert process.stderr is not None
            readers = [
                threading.Thread(
                    target=_drain_stream,
                    args=(process.stdout, stdout_capture, reader_errors),
                    daemon=True,
                ),
                threading.Thread(
                    target=_drain_stream,
                    args=(process.stderr, stderr_capture, reader_errors),
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()
            if gate_write_fd is not None:
                os.write(gate_write_fd, b"\n")
                os.close(gate_write_fd)
                gate_write_fd = None

            # Wait with a wall-clock timeout while reader threads continuously drain.
            try:
                _wait_with_limits(process, identity, timeout_s)
                residual_group = (
                    _process_group_size(int(identity["pgid"]))
                    if identity is not None
                    else (0 if os.name != "posix" else None)
                )
                if residual_group is None:
                    raise _ProcessInventoryUnavailable(
                        "child process-group inventory could not be verified after exit"
                    )
                if residual_group:
                    assert identity is not None
                    _signal_process_group(process, identity, force=True)
                    if not _wait_for_group_exit(int(identity["pgid"])):
                        raise _ProcessInventoryUnavailable(
                            "residual child process-group exit could not be verified"
                        )
                for reader in readers:
                    reader.join(timeout=5)
                if any(reader.is_alive() for reader in readers):
                    raise RuntimeError("child output reader did not reach EOF")
                if reader_errors:
                    raise RuntimeError("child output reader failed: " + "; ".join(reader_errors))
                stdout = stdout_capture.value()
                stderr = stderr_capture.value()
                exit_code = process.returncode
                print(f"[Executor] Subprocess completed: {job_id}, exit_code={exit_code}")

                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = exit_code
                    if job["status"] != "cancelled":
                        if residual_group:
                            job["stderr"] += (
                                "\n[PROCESS LEAK: descendants remained after group leader exit; "
                                "the retained group was force-stopped]"
                            )
                            job["status"] = "failed"
                        else:
                            job["status"] = "succeeded" if exit_code == 0 else "failed"
                        job["completed_at"] = datetime.now()

            except (
                subprocess.TimeoutExpired,
                _ProcessLimitExceeded,
                _ProcessInventoryUnavailable,
            ) as limit_error:
                # Kill on timeout
                cleanup_error: str | None = None
                try:
                    _terminate_process_group(process, identity)
                except Exception as exc:
                    cleanup_error = f"{type(exc).__name__}: {exc}"
                try:
                    process.wait(timeout=5)
                except subprocess.SubprocessError:
                    pass
                for reader in readers:
                    reader.join(timeout=5)
                stdout, stderr = stdout_capture.value(), stderr_capture.value()

                with self.lock:
                    job["stdout"] = stdout
                    job["stderr"] += stderr
                    job["exit_code"] = -1
                    if job["status"] != "cancelled":
                        if isinstance(limit_error, _ProcessLimitExceeded):
                            job["stderr"] += f"\n[PROCESS LIMIT: {limit_error}]"
                            job["status"] = "failed"
                        elif isinstance(limit_error, _ProcessInventoryUnavailable):
                            job["stderr"] += f"\n[PROCESS INVENTORY: {limit_error}]"
                            job["status"] = "failed"
                        else:
                            job["stderr"] += "\n[TIMEOUT: Command exceeded {}s limit]".format(
                                timeout_s
                            )
                            job["status"] = "timed_out"
                        if cleanup_error is not None:
                            job["stderr"] += f"\n[CLEANUP UNVERIFIED: {cleanup_error}]"
                        job["completed_at"] = datetime.now()

        except Exception as e:
            if gate_write_fd is not None:
                try:
                    os.close(gate_write_fd)
                except OSError:
                    pass
            if process is not None:
                try:
                    _terminate_process_group(process, identity)
                except Exception:
                    pass
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
        identity: dict[str, Any] | None
        with self.lock:
            if not self.current_job or self.current_job["job_id"] != job_id:
                return False

            if self.current_job["status"] != "running":
                return False

            process = self.current_job.get("process")
            identity = self.current_job.get("process_identity")
            self.current_job["status"] = "cancelled"
            self.current_job["completed_at"] = datetime.now()
            self.current_job["stderr"] += "\n[CANCELLED by user]"

        if process is not None:
            try:
                _terminate_process_group(process, identity)
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
