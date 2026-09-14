# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Metriplane Local Stack Launcher — v2

Manages the three local processes:
  - dashboard runner service  (127.0.0.1:9000)
  - static dashboard web server (127.0.0.1:8088, serves from repo root)
  - optional runtime stream (127.0.0.1:8000 metrics/health, ws://127.0.0.1:8765)

State and logs use the injected platform state and data directories.

Key design decisions (v2):
- POSIX children run in their own session and process group (PGID = PID)
- Windows children use CREATE_NEW_PROCESS_GROUP and taskkill /T lifecycle control
- state stores both pid and pgid
- stop: SIGTERM → wait 5s → SIGKILL → poll port-free before clearing state
- status: shows port owners via ss -tlnp even when state file is absent
- cleanup: kills only identifiable Metriplane orphans on known ports
"""

from __future__ import annotations

import csv
import errno
import hashlib
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from metriplane.paths import (
    PlatformPathError,
    PlatformPaths,
    normalize_runs_dir,
    resolve_platform_paths,
)
from metriplane.run_ids import validate_portable_run_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RUNNER_HOST = "127.0.0.1"
_DEFAULT_RUNNER_PORT = 9000
_DEFAULT_DASHBOARD_PORT = 8088
_DEFAULT_DASHBOARD_HOST = "127.0.0.1"
_DEFAULT_FUSION_CONFIG = "configs/local_demo_replay.yaml"
_DEFAULT_DURATION_S = 7200

_STATE_SCHEMA_VERSION = 1
_STATE_FILE_MODE = 0o600
_STATE_LOCK_TIMEOUT_S = 30.0
_STATE_LOCKS_HELD: ContextVar[frozenset[str]] = ContextVar(
    "metriplane_launcher_state_locks_held",
    default=frozenset(),
)

# Ports known to be owned by Metriplane services (in priority order for cleanup)
_METRIPLANE_KNOWN_PORTS = [8000, 8765, 9000, 8088]

# Safe-to-kill cmdline patterns (partial match on any argument)
# Note: cleanup only runs on _METRIPLANE_KNOWN_PORTS so http.server here means
# our dashboard server on port 8088, not arbitrary http servers.
_METRIPLANE_SAFE_PATTERNS = [
    "metriplane.runner.service",
    "metriplane.run",
    "metriplane.run_fusion",
    "run_fusion",
    "metriplane.cli",
    "http.server",  # dashboard static server (scoped to known port 8088)
]


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


class _LauncherStateError(RuntimeError):
    """Base class for launcher-state failures that are safe to show to users."""


class _LauncherStateCorruptionError(_LauncherStateError):
    """Raised when retained launcher state cannot satisfy its declared schema."""


class _LauncherStateLockError(_LauncherStateError):
    """Raised when another writer retains the launcher-state lock."""


def _effective_paths(paths: PlatformPaths | None) -> PlatformPaths:
    return paths if paths is not None else resolve_platform_paths()


def _state_file(paths: PlatformPaths | None = None) -> Path:
    return _effective_paths(paths).launcher_state_file


def _state_dir(paths: PlatformPaths | None = None) -> Path:
    d = _state_file(paths).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_lock_file(paths: PlatformPaths | None = None) -> Path:
    state_file = _state_file(paths)
    return state_file.with_name(f".{state_file.name}.lock")


def _chmod_private(path: Path) -> None:
    """Apply the private launcher-state mode without relying on the process umask."""
    os.chmod(path, _STATE_FILE_MODE)


def _acquire_state_lock(descriptor: int, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    if os.name == "nt":
        import msvcrt

        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(  # type: ignore[attr-defined]
                    descriptor, getattr(msvcrt, "LK_NBLCK"), 1
                )
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise _LauncherStateLockError(
                        "timed out waiting for another launcher-state writer"
                    ) from exc
                time.sleep(0.01)

    import fcntl

    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as exc:
            if time.monotonic() >= deadline:
                raise _LauncherStateLockError(
                    "timed out waiting for another launcher-state writer"
                ) from exc
            time.sleep(0.01)


def _release_state_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _state_write_lock(
    paths: PlatformPaths | None = None,
    *,
    timeout: float = _STATE_LOCK_TIMEOUT_S,
) -> Iterator[None]:
    """Serialize state lifecycles and permit nested helpers in the lock owner."""
    lock_file = _state_lock_file(paths)
    lock_key = os.fspath(lock_file)
    held = _STATE_LOCKS_HELD.get()
    if lock_key in held:
        yield
        return

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_file, flags, _STATE_FILE_MODE)
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _LauncherStateError(f"launcher-state lock is not a regular file: {lock_file}")
        _chmod_private(lock_file)
        _acquire_state_lock(descriptor, timeout=timeout)
        acquired = True
        token = _STATE_LOCKS_HELD.set(held | {lock_key})
        try:
            yield
        finally:
            _STATE_LOCKS_HELD.reset(token)
    finally:
        try:
            if acquired:
                _release_state_lock(descriptor)
        finally:
            os.close(descriptor)


def _state_corruption(message: str) -> _LauncherStateCorruptionError:
    return _LauncherStateCorruptionError(
        f"{message}; run `metriplane cleanup` to preserve and recover the corrupt state"
    )


def _validate_process_entry(name: str, value: object) -> None:
    if not isinstance(value, dict):
        raise _state_corruption(f"launcher state field {name!r} is not an object")
    for key in ("pid", "pgid"):
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise _state_corruption(f"launcher state field {name}.{key} is invalid")
    if "port" in value:
        port = value["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise _state_corruption(f"launcher state field {name}.port is invalid")
    if "host" in value and (not isinstance(value["host"], str) or not value["host"]):
        raise _state_corruption(f"launcher state field {name}.host is invalid")


def _validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise _state_corruption("launcher state root is not an object")
    version = state.get("schema_version")
    if isinstance(version, bool) or version != _STATE_SCHEMA_VERSION:
        raise _state_corruption(f"launcher state schema_version must be {_STATE_SCHEMA_VERSION}")
    for name in ("runner", "dashboard", "fusion"):
        if name in state:
            _validate_process_entry(name, state[name])
    return state


def _decode_state(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate object key {key!r}")
            result[key] = value
        return result

    try:
        decoded = raw.decode("utf-8")
        state = json.loads(
            decoded,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _state_corruption(f"launcher state is not strict UTF-8 JSON ({exc})") from exc
    return _validate_state(state)


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            unsupported = {errno.EBADF, errno.EINVAL, errno.ENOTSUP}
            if hasattr(errno, "EOPNOTSUPP"):
                unsupported.add(errno.EOPNOTSUPP)
            if exc.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def _load_state(paths: PlatformPaths | None = None) -> dict[str, Any]:
    state_file = _state_file(paths)
    try:
        raw = state_file.read_bytes()
    except FileNotFoundError:
        return {}
    return _decode_state(raw)


def _save_state(state: dict[str, Any], paths: PlatformPaths | None = None) -> None:
    state_file = _state_file(paths)
    payload = dict(state)
    existing_version = payload.get("schema_version", _STATE_SCHEMA_VERSION)
    if isinstance(existing_version, bool) or existing_version != _STATE_SCHEMA_VERSION:
        raise _LauncherStateError(
            f"cannot write launcher state schema_version {existing_version!r}; "
            f"expected {_STATE_SCHEMA_VERSION}"
        )
    payload["schema_version"] = _STATE_SCHEMA_VERSION
    _validate_state(payload)
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    state_dir = _state_dir(paths)
    temporary: Path | None = None
    with _state_write_lock(paths):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{state_file.name}.",
            suffix=".tmp",
            dir=state_dir,
        )
        temporary = Path(temporary_name)
        try:
            _chmod_private(temporary)
            handle = os.fdopen(descriptor, "wb", closefd=True)
            descriptor = -1
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, state_file)
            temporary = None
            _chmod_private(state_file)
            _fsync_directory(state_dir)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _clear_state(paths: PlatformPaths | None = None) -> None:
    state_file = _state_file(paths)
    with _state_write_lock(paths):
        try:
            state_file.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(state_file.parent)


def _recover_corrupt_state(paths: PlatformPaths | None = None) -> Path | None:
    """Quarantine invalid bytes under a digest-bound name; valid state is untouched."""
    state_file = _state_file(paths)
    with _state_write_lock(paths):
        try:
            raw = state_file.read_bytes()
        except FileNotFoundError:
            return None
        try:
            _decode_state(raw)
        except _LauncherStateCorruptionError:
            digest = hashlib.sha256(raw).hexdigest()
            quarantine = state_file.with_name(f"{state_file.name}.corrupt-{digest}")
            if quarantine.exists():
                if quarantine.read_bytes() != raw:
                    raise _LauncherStateError(f"corrupt-state quarantine collision at {quarantine}")
                state_file.unlink()
            else:
                os.replace(state_file, quarantine)
                _chmod_private(quarantine)
            _fsync_directory(state_file.parent)
            return quarantine
    return None


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_process_is_running(pid: int) -> bool:
    """Inspect a Windows PID without invoking ``os.kill``/``TerminateProcess``."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return False
    if result.returncode != 0:
        return False
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2:
            continue
        try:
            if int(row[1]) == int(pid):
                return True
        except ValueError:
            continue
    return False


def _is_running(pid: int | None) -> bool:
    """Return True if the process exists (any state)."""
    if pid is None:
        return False
    try:
        pid_value = int(pid)
        if pid_value <= 0:
            return False
        if _is_windows():
            return _windows_process_is_running(pid_value)
        os.kill(pid_value, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def _get_pgid(pid: int) -> int | None:
    """Return process group ID of pid, or None if dead."""
    if _is_windows():
        return int(pid) if _is_running(pid) else None
    try:
        return os.getpgid(int(pid))
    except (ProcessLookupError, OSError):
        return None


def _read_cmdline(pid: int) -> str:
    """Return the process command line, or ``""`` when it cannot be read."""
    try:
        pid_value = int(pid)
        proc_path = (
            Path("/proc/self/cmdline")
            if pid_value == os.getpid()
            else Path(f"/proc/{pid_value}/cmdline")
        )
        data = proc_path.read_bytes()
        return " ".join(a for a in data.decode(errors="replace").split("\x00") if a)
    except Exception:
        pass

    # macOS and other POSIX systems do not expose Linux's /proc filesystem.
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(int(pid)), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _is_vt_safe_to_kill(cmdline: str) -> bool:
    """Return True if cmdline matches a known safe-to-kill Metriplane pattern."""
    cl = cmdline.lower()
    for pat in _METRIPLANE_SAFE_PATTERNS:
        if pat.lower() in cl:
            return True
    return False


# ---------------------------------------------------------------------------
# Port / network helpers
# ---------------------------------------------------------------------------


def _has_listener(port: int) -> bool:
    """Return True if ss -tlnp shows an active LISTEN socket on this port.

    This is the definitive "is a server currently listening here?" check.
    It is immune to TIME_WAIT false positives that confuse bind-based probes.
    """
    try:
        res = subprocess.run(
            ["ss", "-H", "-ltnp"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        pat = f":{port} "
        for line in res.stdout.splitlines():
            if pat in line:
                return True
    except Exception:
        pass
    return False


def _is_port_in_use(host: str, port: int) -> bool:
    """Return True if a new server with SO_REUSEADDR cannot bind to host:port.

    Uses SO_REUSEADDR to match real server behaviour — returns False even
    when there are TIME_WAIT connections (which do NOT block real servers).
    Prefer _has_listener() for deciding whether to block startup or cleanup.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, int(port)))
            return False
        except OSError:
            return True


def _probe_http(url: str, timeout: float = 2.0) -> bool:
    """Return True if the URL returns any HTTP response (even 4xx)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as _:
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _wait_for_port(host: str, port: int, timeout: float = 8.0, interval: float = 0.2) -> bool:
    """Wait up to timeout seconds for host:port to accept connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=0.5):
                return True
        except OSError:
            time.sleep(interval)
    return False


def _wait_for_port_free(port: int, timeout: float = 8.0, interval: float = 0.15) -> bool:
    """Wait up to timeout seconds for port to become unbound."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_port_in_use("127.0.0.1", port):
            return True
        time.sleep(interval)
    return False


def _find_port_owner(port: int) -> dict[str, Any] | None:
    """Return {pid, cmdline, safe_to_kill} for the process listening on port, or None.

    Uses `ss -tlnp` (Linux). Parses ``users:(("python",pid=1234,fd=3))``.
    """
    try:
        res = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in res.stdout.splitlines():
            # Match the port number in the local address column
            if f":{port} " not in line and not line.endswith(f":{port}"):
                # More robust: check if ":PORT" appears anywhere in the line
                addr_pat = f":{port}"
                if addr_pat not in line:
                    continue
            m = re.search(r"pid=(\d+)", line)
            if not m:
                continue
            pid = int(m.group(1))
            cmdline = _read_cmdline(pid)
            return {
                "pid": pid,
                "cmdline": cmdline,
                "safe_to_kill": _is_vt_safe_to_kill(cmdline),
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Process launch helpers
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from cwd looking for pyproject.toml."""
    p = Path.cwd()
    for _ in range(8):
        if (p / "pyproject.toml").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path.cwd()


def _log_dir_path(runs_dir: str, timestamp: str) -> Path:
    d = Path(runs_dir) / "_launcher" / timestamp
    d.mkdir(parents=True, exist_ok=True)
    return d


def _launch(
    cmd: list[str], log_file: Path, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Launch a subprocess in an isolated platform process group."""
    group_options: dict[str, Any] = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}
        if _is_windows()
        else {"start_new_session": True}
    )
    with open(log_file, "w") as fh:
        return subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=fh,
            cwd=str(cwd),
            env=env,
            **group_options,
        )


def _print_log_tail(log_file: Path, *, lines: int = 20) -> None:
    """Print a short child log tail after a readiness failure."""
    try:
        content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"     Could not read log: {exc}")
        return
    if not content:
        print("     Log is empty.")
        return
    print("     Last log lines:")
    for line in content[-max(1, int(lines)) :]:
        print(f"       {line}")


def _start_runner(
    *,
    host: str,
    port: int,
    dashboard_host: str,
    dashboard_port: int,
    log_file: Path,
    repo_root: Path,
    paths: PlatformPaths,
) -> subprocess.Popen[bytes]:
    cmd = [
        sys.executable,
        "-m",
        "metriplane.runner.service",
        "--host",
        host,
        "--port",
        str(port),
        "--trusted-origin",
        f"http://{dashboard_host}:{dashboard_port}",
        "--trusted-origin",
        f"http://localhost:{dashboard_port}",
        "--trusted-origin",
        f"http://127.0.0.1:{dashboard_port}",
        "--config-dir",
        str(paths.config_dir),
        "--data-dir",
        str(paths.data_dir),
        "--cache-dir",
        str(paths.cache_dir),
        "--state-dir",
        str(paths.state_dir),
        "--runs-dir",
        str(paths.runs_dir),
    ]
    return _launch(cmd, log_file, repo_root)


def _start_dashboard(
    *, host: str, port: int, log_file: Path, repo_root: Path
) -> subprocess.Popen[bytes]:
    cmd = [
        sys.executable,
        "-m",
        "metriplane._local_http",
        str(port),
        "--bind",
        host,
        "--directory",
        str(repo_root),
    ]
    return _launch(cmd, log_file, repo_root)


def _runtime_module_for_config(config: str, repo_root: Path) -> str:
    cfg_path = Path(config)
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path
    try:
        from metriplane.config import load_config

        cfg = load_config(cfg_path)
    except Exception:
        return "metriplane.run_fusion"

    mode = str(getattr(cfg, "source_mode", "camera") or "camera").strip().lower()
    if mode in ("replay", "dummy"):
        return "metriplane.run"
    return "metriplane.run_fusion"


def _start_fusion(
    *,
    config: str,
    run_id: str,
    runs_dir: str,
    duration_s: float,
    backend: str,
    log_file: Path,
    repo_root: Path,
) -> subprocess.Popen[bytes]:
    run_id = validate_portable_run_id(run_id)
    env = dict(os.environ)
    env["METRIPLANE_COMPUTE_BACKEND"] = "gpu" if backend == "gpu" else "cpu"
    module = _runtime_module_for_config(config, repo_root)
    cmd = [
        sys.executable,
        "-m",
        module,
        "--config",
        config,
        "--run-id",
        run_id,
        "--runs-dir",
        runs_dir,
    ]
    if module == "metriplane.run_fusion":
        cmd.extend(["--duration-s", str(duration_s)])
    return _launch(cmd, log_file, repo_root, env=env)


# ---------------------------------------------------------------------------
# Stop helpers — PGID-based
# ---------------------------------------------------------------------------


def _stop_pg(
    pgid: int | None, pid: int | None, *, use_sigint: bool = False, name: str = "process"
) -> None:
    """Stop a process group. Sends SIGINT/SIGTERM, waits 5s, then SIGKILL."""
    if _is_windows():
        if pid is None or not _is_running(pid):
            return
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _is_running(pid):
                return
            time.sleep(0.1)
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not _is_running(pid):
                break
            time.sleep(0.05)
        print(f"  [{name}] forced process-tree termination after 5s")
        return

    # Build a list of targets: try by pgid first, fall back to pid
    def _send(sig: signal.Signals) -> bool:
        if pgid is not None:
            try:
                os.killpg(int(pgid), sig)
                return True
            except (ProcessLookupError, OSError):
                pass
        if pid is not None:
            try:
                os.kill(int(pid), sig)
                return True
            except (ProcessLookupError, OSError):
                pass
        return False

    def _any_alive() -> bool:
        if pgid is not None and pgid == pid:
            return _is_running(pid)
        # Check both
        if pgid is not None:
            if _is_running(pgid):
                return True
        if pid is not None:
            if _is_running(pid):
                return True
        return False

    if not _any_alive():
        return

    sig1 = signal.SIGINT if use_sigint else signal.SIGTERM
    _send(sig1)

    # Wait up to 5s for clean exit
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _any_alive():
            return
        time.sleep(0.1)

    # Force kill
    _send(signal.SIGKILL)
    # Wait up to 2s for SIGKILL to take effect
    deadline2 = time.monotonic() + 2.0
    while time.monotonic() < deadline2:
        if not _any_alive():
            break
        time.sleep(0.05)
    print(f"  [{name}] SIGKILL sent (did not exit cleanly after 5s)")


def _make_proc_entry(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Build the state entry for a started process (with pgid)."""
    pgid = _get_pgid(proc.pid) or proc.pid
    return {"pid": proc.pid, "pgid": pgid}


# ---------------------------------------------------------------------------
# Public commands
# ---------------------------------------------------------------------------


def cmd_start(
    *,
    live: bool = False,
    backend: str = "cpu",
    config: str = _DEFAULT_FUSION_CONFIG,
    duration_s: float = _DEFAULT_DURATION_S,
    run_id: str | None = None,
    dashboard_host: str = _DEFAULT_DASHBOARD_HOST,
    dashboard_port: int = _DEFAULT_DASHBOARD_PORT,
    runner_host: str = _DEFAULT_RUNNER_HOST,
    runner_port: int = _DEFAULT_RUNNER_PORT,
    runs_dir: str | None = None,
    open_browser: bool = True,
    operator: bool = False,
    paths: PlatformPaths | None = None,
) -> int:
    """Start the local Metriplane stack. Returns exit code."""
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    effective_run_id = f"live_{timestamp}" if run_id is None else run_id
    if live:
        try:
            effective_run_id = validate_portable_run_id(effective_run_id)
        except ValueError as exc:
            print(exc)
            return 2

    try:
        resolved_paths = _effective_paths(paths)
        explicit_runs_dir = normalize_runs_dir(runs_dir)
        if explicit_runs_dir is not None:
            resolved_paths = resolved_paths.with_runs_dir(explicit_runs_dir)
        else:
            resolved_paths = resolved_paths.with_runs_dir(resolved_paths.runs_dir)
        effective_runs_dir = str(resolved_paths.runs_dir)
        with _state_write_lock(resolved_paths):
            return _cmd_start_locked(
                live=live,
                backend=backend,
                config=config,
                duration_s=duration_s,
                effective_run_id=effective_run_id,
                dashboard_host=dashboard_host,
                dashboard_port=dashboard_port,
                runner_host=runner_host,
                runner_port=runner_port,
                open_browser=open_browser,
                operator=operator,
                resolved_paths=resolved_paths,
                effective_runs_dir=effective_runs_dir,
                timestamp=timestamp,
            )
    except (OSError, PlatformPathError, _LauncherStateError) as exc:
        print(f"Cannot access Metriplane platform directories: {exc}")
        return 2


def _cmd_start_locked(
    *,
    live: bool,
    backend: str,
    config: str,
    duration_s: float,
    effective_run_id: str,
    dashboard_host: str,
    dashboard_port: int,
    runner_host: str,
    runner_port: int,
    open_browser: bool,
    operator: bool,
    resolved_paths: PlatformPaths,
    effective_runs_dir: str,
    timestamp: str,
) -> int:
    """Run one complete read/act/publish lifecycle under the state writer lock."""
    state = _load_state(resolved_paths)
    _state_dir(resolved_paths)

    # Check for stale state with live processes
    if state:
        runner_pid = state.get("runner", {}).get("pid")
        dash_pid = state.get("dashboard", {}).get("pid")
        if _is_running(runner_pid) or _is_running(dash_pid):
            print("⚠️  Metriplane launcher is already running.")
            print("   Use `metriplane stop` first, or `metriplane status` to inspect.")
            return 1
        try:
            _clear_state(resolved_paths)
        except (OSError, _LauncherStateError) as exc:
            print(f"Cannot clear stale Metriplane launcher state: {exc}")
            return 2

    repo_root = _find_repo_root()
    try:
        log_d = _log_dir_path(effective_runs_dir, timestamp)
    except (OSError, _LauncherStateError) as exc:
        print(f"Cannot create Metriplane run directory: {exc}")
        return 2

    print(f"🔍 Repo root : {repo_root}")
    print(f"📋 Log dir  : {log_d}")

    # Port checks — also check for orphaned VT processes
    for port, pname in [(runner_port, "runner"), (dashboard_port, "dashboard")]:
        if _is_port_in_use("127.0.0.1", port):
            owner = _find_port_owner(port)
            if owner and owner["safe_to_kill"]:
                print(
                    f"\n⚠️  Port {port} ({pname}) held by orphaned Metriplane process "
                    f"(pid={owner['pid']}). Run `metriplane cleanup` to remove it."
                )
            else:
                print(f"\n❌ Port {port} ({pname}) is in use by an unknown process.")
                if owner:
                    print(f"   Owner: pid={owner['pid']}  cmd={owner['cmdline'][:80]}")
                print(f"   Try: lsof -nP -iTCP:{port} -sTCP:LISTEN  or  metriplane status")
            return 1
    if live:
        for port, pname in [(8000, "health/metrics"), (8765, "websocket")]:
            if _is_port_in_use("127.0.0.1", port):
                owner = _find_port_owner(port)
                if owner and owner["safe_to_kill"]:
                    print(
                        f"\n⚠️  Port {port} ({pname}) held by orphaned Metriplane process "
                        f"(pid={owner['pid']}). Run `metriplane cleanup` to remove it."
                    )
                else:
                    print(f"\n❌ Port {port} ({pname}) is in use by an unknown process.")
                    if owner:
                        print(f"   Owner: pid={owner['pid']}  cmd={owner['cmdline'][:80]}")
                    print(f"   Try: lsof -nP -iTCP:{port} -sTCP:LISTEN  or  metriplane status")
                return 1

    # --- Start runner ---
    print(f"\n▶  Starting runner on http://{runner_host}:{runner_port}/")
    rp = _start_runner(
        host=runner_host,
        port=runner_port,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        log_file=log_d / "runner.log",
        repo_root=repo_root,
        paths=resolved_paths,
    )
    if not _wait_for_port(runner_host, runner_port, timeout=8.0):
        print(f"  ❌ Runner did not start within 8s (pid={rp.pid})")
        runner_log = log_d / "runner.log"
        print(f"     Log: {runner_log}")
        returncode = rp.poll()
        if returncode is not None:
            print(f"     Runner exited with status {returncode}")
        _print_log_tail(runner_log)
        _stop_pg(rp.pid, rp.pid, name="runner")
        return 1
    print(f"  ✅ Runner OK  (pid={rp.pid})")

    # --- Start dashboard ---
    print(f"▶  Starting dashboard on http://{dashboard_host}:{dashboard_port}/")
    dp = _start_dashboard(
        host=dashboard_host,
        port=dashboard_port,
        log_file=log_d / "dashboard.log",
        repo_root=repo_root,
    )
    if not _wait_for_port(dashboard_host, dashboard_port, timeout=8.0):
        print(f"  ❌ Dashboard server did not start within 8s (pid={dp.pid})")
        _stop_pg(dp.pid, dp.pid, name="dashboard")
        _stop_pg(rp.pid, rp.pid, name="runner")
        return 1
    print(f"  ✅ Dashboard OK  (pid={dp.pid})")

    # --- Start runtime stream ---
    fusion_entry: dict[str, Any] | None = None
    if live:
        print(f"▶  Starting runtime stream  (config={config}, run_id={effective_run_id})")
        fp = _start_fusion(
            config=config,
            run_id=effective_run_id,
            runs_dir=effective_runs_dir,
            duration_s=duration_s,
            backend=backend,
            log_file=log_d / "fusion.log",
            repo_root=repo_root,
        )
        fusion_entry = _make_proc_entry(fp)
        fusion_entry.update(
            {
                "run_id": effective_run_id,
                "config": config,
                "backend": backend,
                "duration_s": duration_s,
            }
        )
        metrics_ready = _wait_for_port("127.0.0.1", 8000, timeout=8.0)
        ws_ready = _wait_for_port("127.0.0.1", 8765, timeout=4.0)
        if metrics_ready and ws_ready:
            print(f"  ✅ Runtime OK  (pid={fp.pid})")
        else:
            print(f"  ❌ Runtime failed readiness checks (pid={fp.pid})")
            print(f"     Health/Metrics ready: {metrics_ready}")
            print(f"     WebSocket ready     : {ws_ready}")
            print(f"     Log: {log_d / 'fusion.log'}")
            _stop_pg(_get_pgid(fp.pid) or fp.pid, fp.pid, use_sigint=True, name="fusion")
            _stop_pg(_get_pgid(dp.pid) or dp.pid, dp.pid, name="dashboard")
            _stop_pg(_get_pgid(rp.pid) or rp.pid, rp.pid, name="runner")
            _wait_for_port_free(8000, timeout=3.0)
            _wait_for_port_free(8765, timeout=3.0)
            _wait_for_port_free(dashboard_port, timeout=3.0)
            _wait_for_port_free(runner_port, timeout=3.0)
            _clear_state(resolved_paths)
            print("  ❌ Stack start aborted; all launcher children were stopped")
            return 1

    # --- Save state ---
    new_state: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "repo_root": str(repo_root),
        "log_dir": str(log_d),
        "runs_dir": effective_runs_dir,
        "timestamp": timestamp,
        "runner": {**_make_proc_entry(rp), "host": runner_host, "port": runner_port},
        "dashboard": {**_make_proc_entry(dp), "host": dashboard_host, "port": dashboard_port},
    }
    if fusion_entry is not None:
        new_state["fusion"] = fusion_entry
    try:
        _save_state(new_state, resolved_paths)
    except (OSError, _LauncherStateError) as exc:
        if fusion_entry is not None:
            _stop_pg(
                fusion_entry.get("pgid"), fusion_entry.get("pid"), use_sigint=True, name="fusion"
            )
        _stop_pg(_get_pgid(dp.pid) or dp.pid, dp.pid, name="dashboard")
        _stop_pg(_get_pgid(rp.pid) or rp.pid, rp.pid, name="runner")
        try:
            _clear_state(resolved_paths)
        except (OSError, _LauncherStateError) as cleanup_exc:
            print(f"Cannot clear failed launcher state: {cleanup_exc}")
        print(f"Cannot save Metriplane launcher state: {exc}")
        return 2

    # --- Print URLs ---
    dash_url = f"http://{dashboard_host}:{dashboard_port}/web/dashboard/index.html"
    op_url = f"http://{dashboard_host}:{dashboard_port}/web/dashboard/operator.html"
    open_url = op_url if operator else dash_url

    print(f"\n{'=' * 60}")
    print("✅  Metriplane stack is running")
    print(f"{'=' * 60}")
    print(f"  Console      : {dash_url}")
    print(f"  Operator UI  : {op_url}")
    print(f"  Runner API   : http://{runner_host}:{runner_port}/status")
    if live and fusion_entry:
        print("  Health       : http://127.0.0.1:8000/health")
        print("  Metrics      : http://127.0.0.1:8000/metrics")
        print("  WebSocket    : ws://127.0.0.1:8765")
    elif not live:
        print("  Runtime      : idle until Setup or Run starts a session")
    print(f"\n  Logs         : {log_d}/")
    print(f"  State        : {resolved_paths.launcher_state_file}")
    print("\n  Stop with    : metriplane stop")
    print(f"{'=' * 60}")

    if open_browser:
        _open_browser(open_url)
        print(f"\n🌐 Opened {open_url}")

    return 0


def cmd_stop(force: bool = False, *, paths: PlatformPaths | None = None) -> int:
    """Stop launcher-started processes and wait for ports to be released."""
    try:
        resolved_paths = _effective_paths(paths)
        with _state_write_lock(resolved_paths):
            return _cmd_stop_locked(force=force, resolved_paths=resolved_paths)
    except (OSError, PlatformPathError, _LauncherStateError) as exc:
        print(f"Cannot access Metriplane launcher state: {exc}")
        return 2


def _cmd_stop_locked(*, force: bool, resolved_paths: PlatformPaths) -> int:
    """Stop and clear one retained launcher lifecycle while holding its writer lock."""
    state = _load_state(resolved_paths)
    if not state and not force:
        print("ℹ️   No launcher state found. Use `metriplane cleanup` if processes are orphaned.")
        return 0

    if not state:
        # force mode: fall through to cleanup behavior
        return cmd_cleanup(paths=resolved_paths)

    runner_info = state.get("runner") or {}
    dash_info = state.get("dashboard") or {}
    fusion_info = state.get("fusion") or {}

    runner_pid = runner_info.get("pid")
    runner_pgid = runner_info.get("pgid") or runner_pid
    runner_port = runner_info.get("port", _DEFAULT_RUNNER_PORT)

    dash_pid = dash_info.get("pid")
    dash_pgid = dash_info.get("pgid") or dash_pid
    dash_port = dash_info.get("port", _DEFAULT_DASHBOARD_PORT)

    fusion_pid = fusion_info.get("pid")
    fusion_pgid = fusion_info.get("pgid") or fusion_pid

    stopped_any = False

    # Fusion first (SIGINT for clean recording flush)
    if fusion_pid:
        if _is_running(fusion_pid):
            print(f"  Stopping fusion    (pid={fusion_pid} pgid={fusion_pgid}) …")
            _stop_pg(fusion_pgid, fusion_pid, use_sigint=True, name="fusion")
            print("  ✅ Fusion stopped")
            stopped_any = True
        else:
            print(f"  ℹ️   Fusion pid={fusion_pid} already gone")

    # Runner
    if runner_pid:
        if _is_running(runner_pid):
            print(f"  Stopping runner    (pid={runner_pid} pgid={runner_pgid}) …")
            _stop_pg(runner_pgid, runner_pid, name="runner")
            print("  ✅ Runner stopped")
            stopped_any = True
        else:
            print(f"  ℹ️   Runner pid={runner_pid} already gone")

    # Dashboard
    if dash_pid:
        if _is_running(dash_pid):
            print(f"  Stopping dashboard (pid={dash_pid} pgid={dash_pgid}) …")
            _stop_pg(dash_pgid, dash_pid, name="dashboard")
            print("  ✅ Dashboard stopped")
            stopped_any = True
        else:
            print(f"  ℹ️   Dashboard pid={dash_pid} already gone")

    # Wait for ports to be actually released before clearing state
    ports_to_check = []
    if runner_pid:
        ports_to_check.append((runner_port, "runner"))
    if dash_pid:
        ports_to_check.append((dash_port, "dashboard"))
    if fusion_pid:
        ports_to_check.extend([(8000, "metrics"), (8765, "websocket")])

    all_free = True
    for port, pname in ports_to_check:
        if _is_port_in_use("127.0.0.1", port):
            freed = _wait_for_port_free(port, timeout=6.0)
            if not freed:
                print(f"  ⚠️  Port {port} ({pname}) still in use after 6s")
                owner = _find_port_owner(port)
                if owner:
                    print(f"       Held by pid={owner['pid']}  {owner['cmdline'][:80]}")
                all_free = False

    try:
        _clear_state(resolved_paths)
    except (OSError, _LauncherStateError) as exc:
        print(f"Cannot clear Metriplane launcher state: {exc}")
        return 2

    if all_free:
        msg = (
            "✅ All launcher services stopped."
            if stopped_any
            else "ℹ️   No live processes found (state cleared)."
        )
        print(f"\n{msg}")
    else:
        print("\n⚠️  Some ports may still be in use. Run `metriplane cleanup` if needed.")
    return 0


def cmd_cleanup(*, paths: PlatformPaths | None = None) -> int:
    """Kill only known Metriplane orphans on known ports. Never kills unknown processes."""
    try:
        resolved_paths = _effective_paths(paths)
        with _state_write_lock(resolved_paths):
            return _cmd_cleanup_locked(resolved_paths=resolved_paths)
    except (OSError, PlatformPathError, _LauncherStateError) as exc:
        print(f"Cannot resolve Metriplane launcher state: {exc}")
        return 2


def _cmd_cleanup_locked(*, resolved_paths: PlatformPaths) -> int:
    """Recover state and remove known orphans while holding the lifecycle lock."""
    try:
        recovered_state = _recover_corrupt_state(resolved_paths)
    except (OSError, _LauncherStateError) as exc:
        print(f"Cannot recover Metriplane launcher state: {exc}")
        return 2
    if recovered_state is not None:
        print(f"Preserved corrupt launcher state: {recovered_state}")
    print("🧹 Checking for orphaned Metriplane processes …")

    killed_any = False
    for port in _METRIPLANE_KNOWN_PORTS:
        if not _is_port_in_use("127.0.0.1", port):
            continue
        owner = _find_port_owner(port)
        if owner is None:
            print(f"  Port {port}: in use but owner not found via ss")
            continue
        pid = owner["pid"]
        cmdline = owner["cmdline"]
        if not owner["safe_to_kill"]:
            print(f"  Port {port}: occupied by non-Metriplane process (pid={pid})")
            print(f"    cmd: {cmdline[:100]}")
            print("    → SKIPPED (not a known Metriplane pattern)")
            continue
        print(f"  Port {port}: Metriplane orphan detected")
        print(f"    pid={pid}  cmd={cmdline[:80]}")
        pgid = _get_pgid(pid) or pid
        _stop_pg(pgid, pid, name=f"port-{port}")
        freed = _wait_for_port_free(port, timeout=5.0)
        if freed:
            print(f"  ✅ Port {port} released")
            killed_any = True
        else:
            print(f"  ⚠️  Port {port} still in use after kill")

    try:
        _clear_state(resolved_paths)  # Remove any stale state
    except (OSError, _LauncherStateError) as exc:
        print(f"Cannot clear Metriplane launcher state: {exc}")
        return 2

    if killed_any:
        print("\n✅ Orphan cleanup complete.")
    else:
        print("\nℹ️   No Metriplane orphans found.")
    return 0


def cmd_restart(
    *,
    live: bool = False,
    backend: str = "cpu",
    config: str = _DEFAULT_FUSION_CONFIG,
    duration_s: float = _DEFAULT_DURATION_S,
    run_id: str | None = None,
    dashboard_host: str = _DEFAULT_DASHBOARD_HOST,
    dashboard_port: int = _DEFAULT_DASHBOARD_PORT,
    runner_host: str = _DEFAULT_RUNNER_HOST,
    runner_port: int = _DEFAULT_RUNNER_PORT,
    runs_dir: str | None = None,
    open_browser: bool = True,
    operator: bool = False,
    paths: PlatformPaths | None = None,
) -> int:
    """Stop all services (including orphans), then start fresh."""
    try:
        resolved_paths = _effective_paths(paths)
        with _state_write_lock(resolved_paths):
            return _cmd_restart_locked(
                live=live,
                backend=backend,
                config=config,
                duration_s=duration_s,
                run_id=run_id,
                dashboard_host=dashboard_host,
                dashboard_port=dashboard_port,
                runner_host=runner_host,
                runner_port=runner_port,
                runs_dir=runs_dir,
                open_browser=open_browser,
                operator=operator,
                resolved_paths=resolved_paths,
            )
    except (OSError, PlatformPathError, _LauncherStateError) as exc:
        print(f"Cannot access Metriplane launcher state: {exc}")
        return 2


def _cmd_restart_locked(
    *,
    live: bool,
    backend: str,
    config: str,
    duration_s: float,
    run_id: str | None,
    dashboard_host: str,
    dashboard_port: int,
    runner_host: str,
    runner_port: int,
    runs_dir: str | None,
    open_browser: bool,
    operator: bool,
    resolved_paths: PlatformPaths,
) -> int:
    """Run the complete stop/cleanup/start restart lifecycle under one lock."""
    state = _load_state(resolved_paths)
    print("⟳  Stopping existing stack …")
    if state:
        result = cmd_stop(paths=resolved_paths)
        if result:
            return result
    else:
        # Even without state, hunt for known orphaned VT processes
        cleanup_ports = [runner_port, dashboard_port]
        if live:
            cleanup_ports.extend([8000, 8765])
        needs_cleanup = any(_is_port_in_use("127.0.0.1", p) for p in cleanup_ports)
        if needs_cleanup:
            print("ℹ️   No launcher state but Metriplane ports are occupied — running cleanup …")
            result = cmd_cleanup(paths=resolved_paths)
            if result:
                return result

    # Final check: wait a bit for ports to stabilize
    time.sleep(0.3)
    for port, pname in [(runner_port, "runner"), (dashboard_port, "dashboard")]:
        if _is_port_in_use("127.0.0.1", port):
            _wait_for_port_free(port, timeout=4.0)

    print("\n⟳  Starting new stack …")
    return cmd_start(
        live=live,
        backend=backend,
        config=config,
        duration_s=duration_s,
        run_id=run_id,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        runner_host=runner_host,
        runner_port=runner_port,
        runs_dir=runs_dir,
        open_browser=open_browser,
        operator=operator,
        paths=resolved_paths,
    )


def cmd_status(*, paths: PlatformPaths | None = None) -> int:
    """Show status of launcher services and probe known ports — even without state."""
    try:
        resolved_paths = _effective_paths(paths)
        state = _load_state(resolved_paths)
    except (OSError, PlatformPathError, _LauncherStateError) as exc:
        print(f"Cannot access Metriplane launcher state: {exc}")
        return 2

    print("Metriplane Launcher Status")
    print("=" * 60)

    if state:
        started_at = state.get("started_at", "unknown")
        print(f"  State file  : {resolved_paths.launcher_state_file}")
        print(f"  Started at  : {started_at}")
        print(f"  Log dir     : {state.get('log_dir', 'unknown')}")
        print()

    runner_info = state.get("runner") or {}
    dash_info = state.get("dashboard") or {}
    fusion_info = state.get("fusion") or {}

    def _pid_badge(pid: int | None, pgid: int | None = None) -> str:
        if pid and _is_running(pid):
            g = f" pgid={pgid}" if pgid and pgid != pid else ""
            return f"✅ running (pid={pid}{g})"
        elif pid:
            return f"❌ dead    (pid={pid})"
        return "— not in state"

    def _http_badge(url: str) -> str:
        return "🟢 online" if _probe_http(url) else "🔴 offline"

    # --- Runner ---
    rpid = runner_info.get("pid")
    rpgid = runner_info.get("pgid")
    rport = runner_info.get("port", _DEFAULT_RUNNER_PORT)
    rhost = runner_info.get("host", _DEFAULT_RUNNER_HOST)
    print(f"  Runner       : {_pid_badge(rpid, rpgid)}")
    r_url = f"http://{rhost}:{rport}/status"
    print(f"    URL        : {r_url}  {_http_badge(r_url)}")
    if rpid is None:
        _show_port_owner(rport, "  ")

    # --- Dashboard ---
    dpid = dash_info.get("pid")
    dpgid = dash_info.get("pgid")
    dport = dash_info.get("port", _DEFAULT_DASHBOARD_PORT)
    dhost = dash_info.get("host", _DEFAULT_DASHBOARD_HOST)
    print(f"  Dashboard    : {_pid_badge(dpid, dpgid)}")
    dash_url = f"http://{dhost}:{dport}/web/dashboard/"
    print(f"    Dashboard  : {dash_url}  {_http_badge(dash_url)}")
    op_url = f"http://{dhost}:{dport}/web/dashboard/operator.html"
    print(f"    Operator   : {op_url}  {_http_badge(op_url)}")
    if dpid is None:
        _show_port_owner(dport, "  ")

    # --- Fusion ---
    if fusion_info:
        fpid = fusion_info.get("pid")
        fpgid = fusion_info.get("pgid")
        frun = fusion_info.get("run_id", "unknown")
        print(f"  Fusion       : {_pid_badge(fpid, fpgid)}  run_id={frun}")
    else:
        print("  Runtime      : — idle until Setup or Run starts a session")

    # Always show health/metrics/WS port status
    print(
        f"    Health     : http://127.0.0.1:8000/health  {_http_badge('http://127.0.0.1:8000/health')}"
    )
    print(
        f"    Metrics    : http://127.0.0.1:8000/metrics {_http_badge('http://127.0.0.1:8000/metrics')}"
    )
    print("    WebSocket  : ws://127.0.0.1:8765", end="")
    ws_owner = _find_port_owner(8765)
    if ws_owner:
        print(f"  (pid={ws_owner['pid']})")
    else:
        print()
    if not fusion_info:
        _show_port_owner(8000, "  ")

    print()
    if not state:
        print("  ℹ️   No launcher state. Showing live port scan only.")
        print("  Start with   : metriplane start")
    else:
        print("  Stop with    : metriplane stop")
    print("=" * 60)
    return 0


def _show_port_owner(port: int, indent: str = "") -> None:
    """Print port owner info if something is listening."""
    if not _is_port_in_use("127.0.0.1", port):
        return
    owner = _find_port_owner(port)
    if owner:
        safety = "⚠️ Metriplane orphan" if owner["safe_to_kill"] else "❌ unknown process"
        print(f"{indent}  Port {port} occupied: {safety} pid={owner['pid']}")
        print(f"{indent}    cmd: {owner['cmdline'][:100]}")
        if owner["safe_to_kill"]:
            print(f"{indent}    → Run `metriplane cleanup` to remove")
    else:
        print(f"{indent}  Port {port}: in use (owner unknown — check with lsof -nP -iTCP:{port})")


# ---------------------------------------------------------------------------
# Browser helper
# ---------------------------------------------------------------------------


def _open_browser(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:
        pass
