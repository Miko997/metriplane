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
- Governed Linux/macOS children run in their own session and process group (PGID = PID)
- exact birth/executable/argv identity is retained before lifecycle state is accepted
- Windows helpers remain non-destructive, but start fails closed without an exact identity provider
- state stores pid, pgid, and the retained process identity
- stop: SIGTERM → wait 5s → SIGKILL → poll port-free before clearing state
- status: shows port owners via ss -tlnp even when state file is absent
- cleanup: kills only identifiable Metriplane orphans on known ports
"""

from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import json

from metriplane.strict_parsing import load_json as strict_json_loads
import os
import re
import secrets
import select
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
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

_METRIPLANE_SAFE_MODULES = {
    "metriplane.runner.service",
    "metriplane.run",
    "metriplane.run_fusion",
    "metriplane._local_http",
}
_POSIX_EXEC_GATE = """\
import os
import signal
import sys

gate_fd = int(sys.argv[1])
command = sys.argv[2:]
try:
    released = os.read(gate_fd, 2) == b"\\n"
finally:
    os.close(gate_fd)
if not released:
    raise SystemExit(125)
for signal_name in ("SIGPIPE", "SIGXFZ", "SIGXFSZ"):
    inherited_signal = getattr(signal, signal_name, None)
    if inherited_signal is not None:
        signal.signal(inherited_signal, signal.SIG_DFL)
try:
    os.execvp(command[0], command)
except (OSError, IndexError):
    raise SystemExit(126)
"""
_POSIX_LAUNCH_SUPERVISOR = """\
import os
import signal
import subprocess
import sys

gate_fd = int(sys.argv[1])
ready_fd = int(sys.argv[2])
exec_gate = sys.argv[3]
command = sys.argv[4:]
child = None
pending_signal = None

def retain_supervisor(signum, _frame):
    global pending_signal
    pending_signal = signum

signal.signal(signal.SIGINT, retain_supervisor)
signal.signal(signal.SIGTERM, retain_supervisor)

def close_fd(descriptor):
    if descriptor is not None:
        try:
            os.close(descriptor)
        except OSError:
            pass

def reap_child():
    if child is None:
        return
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)

if pending_signal is not None:
    raise SystemExit(128 + pending_signal)
child_gate_read, child_gate_write = os.pipe()
if pending_signal is not None:
    close_fd(child_gate_read)
    close_fd(child_gate_write)
    raise SystemExit(128 + pending_signal)
try:
    child = subprocess.Popen(
        [sys.executable, "-c", exec_gate, str(child_gate_read), *command],
        pass_fds=(child_gate_read,),
    )
except (OSError, ValueError):
    close_fd(child_gate_read)
    close_fd(child_gate_write)
    raise SystemExit(125)
close_fd(child_gate_read)
if pending_signal is not None:
    try:
        child.send_signal(pending_signal)
    except ProcessLookupError:
        pass
try:
    os.write(ready_fd, b"\\n")
except OSError:
    close_fd(child_gate_write)
    reap_child()
    raise SystemExit(125)
finally:
    os.close(ready_fd)
if os.read(gate_fd, 2) != b"\\n":
    close_fd(child_gate_write)
    reap_child()
    raise SystemExit(125)
os.close(gate_fd)
if pending_signal is not None:
    close_fd(child_gate_write)
    reap_child()
    raise SystemExit(128 + pending_signal)
try:
    os.write(child_gate_write, b"\\n")
except OSError:
    close_fd(child_gate_write)
    reap_child()
    raise SystemExit(125)
close_fd(child_gate_write)
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
    if "identity" in value:
        identity = value["identity"]
        if not isinstance(identity, dict):
            raise _state_corruption(f"launcher state field {name}.identity is invalid")
        required = {"pid", "pgid", "birth", "executable", "argv"}
        if set(identity) != required:
            raise _state_corruption(f"launcher state field {name}.identity fields are invalid")
        if identity["pid"] != value.get("pid") or identity["pgid"] != value.get("pgid"):
            raise _state_corruption(f"launcher state field {name}.identity numeric binding differs")
        if not isinstance(identity["birth"], str) or not identity["birth"]:
            raise _state_corruption(f"launcher state field {name}.identity.birth is invalid")
        if not isinstance(identity["executable"], str) or not identity["executable"]:
            raise _state_corruption(f"launcher state field {name}.identity.executable is invalid")
        argv = identity["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) for item in argv)
        ):
            raise _state_corruption(f"launcher state field {name}.identity.argv is invalid")


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
        state = strict_json_loads(
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
    """Return True if the process is live rather than a retained zombie."""
    if pid is None:
        return False
    try:
        pid_value = int(pid)
        if pid_value <= 0:
            return False
        if _is_windows():
            return _windows_process_is_running(pid_value)
        if sys.platform == "darwin":
            darwin_status = _darwin_process_status(pid_value)
            if darwin_status == 5:  # SZOMB in Darwin's proc.h
                return False
            if darwin_status is not None:
                return True
        if Path("/proc").is_dir():
            try:
                parsed = _parse_linux_proc_stat(Path(f"/proc/{pid_value}/stat").read_text())
                if parsed is not None and parsed[0] == "Z":
                    return False
            except (FileNotFoundError, ProcessLookupError):
                return False
            except (PermissionError, OSError, ValueError):
                pass
        os.kill(pid_value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
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


def _read_argv(pid: int) -> list[str]:
    """Return the process argv without substring interpretation."""
    try:
        data = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        return [
            item.decode("utf-8", errors="surrogateescape") for item in data.split(b"\0") if item
        ]
    except Exception:
        return []


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
    # POSIX permits empty arguments after argv[0].  Preserve those exact
    # boundaries; only argv[0] must name an executable for this identity.
    return argv if argv and argv[0] else None


def _darwin_process_argv(pid: int) -> list[str] | None:
    """Read KERN_PROCARGS2 with the kernel's declared maximum argument size."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        libc.sysctlbyname.restype = ctypes.c_int
        maximum = ctypes.c_int()
        maximum_size = ctypes.c_size_t(ctypes.sizeof(maximum))
        if (
            libc.sysctlbyname(
                b"kern.argmax",
                ctypes.byref(maximum),
                ctypes.byref(maximum_size),
                None,
                0,
            )
            != 0
        ):
            return None
        if maximum_size.value != ctypes.sizeof(maximum):
            return None
        capacity = int(maximum.value)
        if capacity <= 4 or capacity > 16 * 1024 * 1024:
            return None

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
        args_size = ctypes.c_size_t(capacity)
        args_buffer = ctypes.create_string_buffer(capacity)
        if libc.sysctl(mib, 3, args_buffer, ctypes.byref(args_size), None, 0) != 0:
            return None
        if args_size.value <= 4 or args_size.value > capacity:
            return None
        return _parse_darwin_procargs(args_buffer.raw[: args_size.value])
    except (AttributeError, OSError, OverflowError, ValueError):
        return None


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
        if libproc.proc_pidpath(int(pid), path_buffer, len(path_buffer)) <= 0:
            return None
        argv = _darwin_process_argv(int(pid))
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


def _darwin_process_status(pid: int) -> int | None:
    """Read Darwin's native process status, including a positive zombie state."""
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
        info = _DarwinProcBsdInfo()
        size = ctypes.sizeof(info)
        if libproc.proc_pidinfo(int(pid), 3, 0, ctypes.byref(info), size) != size:
            return None
        if int(info.pbi_pid) != int(pid):
            return None
        return int(info.pbi_status)
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


def _capture_process_identity(pid: int) -> dict[str, Any] | None:
    """Capture birth, executable and argv before retaining a numeric process ID."""
    pid_value = int(pid)
    if sys.platform == "darwin":
        return _darwin_process_identity(pid_value)
    if _is_windows():
        return None
    argv = _read_argv(pid_value)
    if not argv or not Path("/proc").is_dir():
        return None
    try:
        parsed = _parse_linux_proc_stat(Path(f"/proc/{pid_value}/stat").read_text())
        executable = os.readlink(f"/proc/{pid_value}/exe")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError):
        return None
    if parsed is None:
        return None
    _, pgid, birth = parsed
    return {
        "pid": pid_value,
        "pgid": int(pgid),
        "birth": birth,
        "executable": executable,
        "argv": argv,
    }


def _process_identity_matches(expected: object) -> bool:
    if not isinstance(expected, dict):
        return False
    try:
        current = _capture_process_identity(int(expected["pid"]))
    except (KeyError, TypeError, ValueError):
        return False
    return current == expected


def _process_group_size(pgid: int | None) -> int | None:
    if pgid is None or _is_windows():
        return 0
    if sys.platform == "darwin":
        return _darwin_process_group_size(int(pgid))
    if Path("/proc").is_dir():
        members = 0
        try:
            entries = Path("/proc").iterdir()
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    parsed = _parse_linux_proc_stat((entry / "stat").read_text())
                    if parsed is not None and parsed[0] != "Z" and parsed[1] == int(pgid):
                        members += 1
                except (
                    FileNotFoundError,
                    ProcessLookupError,
                    PermissionError,
                    OSError,
                    ValueError,
                ):
                    continue
        except OSError:
            return None
        return members
    return None


def _process_group_alive(pgid: int | None) -> bool:
    size = _process_group_size(pgid)
    return size is None or size > 0


def _is_metriplane_argv(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name.lower()
    if re.fullmatch(r"(?:python|pypy)(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable) is None:
        return False
    return len(argv) >= 3 and argv[1] == "-m" and argv[2] in _METRIPLANE_SAFE_MODULES


def _is_metriplane_process_identity(identity: object) -> bool:
    """Authorize cleanup only when kernel executable and exact argv agree."""
    if not isinstance(identity, dict):
        return False
    executable = identity.get("executable")
    argv = identity.get("argv")
    if not isinstance(executable, str) or not isinstance(argv, list):
        return False
    if not argv or not all(isinstance(item, str) for item in argv):
        return False
    argv0 = Path(argv[0])
    if not argv0.is_absolute() or not _is_metriplane_argv(argv):
        return False
    try:
        return os.path.samefile(executable, argv0)
    except OSError:
        return False


def _is_vt_safe_to_kill(cmdline: str) -> bool:
    """Compatibility wrapper using exact argv structure, never substring matches."""
    try:
        return _is_metriplane_argv(shlex.split(cmdline))
    except ValueError:
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
            identity = _capture_process_identity(pid)
            argv = identity["argv"] if identity is not None else []
            cmdline = " ".join(shlex.quote(item) for item in argv)
            return {
                "pid": pid,
                "cmdline": cmdline,
                "identity": identity,
                "safe_to_kill": _is_metriplane_process_identity(identity),
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
    """Launch behind a gate so exact group identity exists before user code runs."""
    if _is_windows():
        raise _LauncherStateError(
            "launcher start requires an exact Windows process-identity provider"
        )
    gate_read, gate_write = os.pipe()
    try:
        ready_read, ready_write = os.pipe()
    except BaseException:
        os.close(gate_read)
        os.close(gate_write)
        raise
    try:
        with open(log_file, "w") as fh:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _POSIX_LAUNCH_SUPERVISOR,
                    str(gate_read),
                    str(ready_write),
                    _POSIX_EXEC_GATE,
                    *cmd,
                ],
                stdout=fh,
                stderr=fh,
                cwd=str(cwd),
                env=env,
                start_new_session=True,
                pass_fds=(gate_read, ready_write),
            )
    except BaseException:
        os.close(gate_write)
        os.close(ready_read)
        raise
    finally:
        os.close(gate_read)
        os.close(ready_write)
    process._metriplane_gate_fd = gate_write  # type: ignore[attr-defined]
    process._metriplane_ready_fd = ready_read  # type: ignore[attr-defined]
    return process


def _release_launch_gate(proc: subprocess.Popen[bytes]) -> None:
    """Release a launcher child only after its supervisor identity is retained."""
    gate_fd = getattr(proc, "_metriplane_gate_fd", None)
    if gate_fd is None:
        return
    proc._metriplane_gate_fd = None  # type: ignore[attr-defined]
    try:
        os.write(int(gate_fd), b"\n")
    except OSError as exc:
        raise _LauncherStateError("could not release retained launcher child") from exc
    finally:
        os.close(int(gate_fd))


def _discard_unreleased_process(proc: subprocess.Popen[bytes]) -> None:
    """Close a failed child's gate; no user command or unverified signal is needed."""
    gate_fd = getattr(proc, "_metriplane_gate_fd", None)
    if gate_fd is not None:
        proc._metriplane_gate_fd = None  # type: ignore[attr-defined]
        try:
            os.close(int(gate_fd))
        except OSError:
            pass
    ready_fd = getattr(proc, "_metriplane_ready_fd", None)
    if ready_fd is not None:
        proc._metriplane_ready_fd = None  # type: ignore[attr-defined]
        try:
            os.close(int(ready_fd))
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


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
    session_capability: str,
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
    env = dict(os.environ)
    env["METRIPLANE_RUNNER_SESSION_TOKEN"] = session_capability
    return _launch(cmd, log_file, repo_root, env=env)


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
        str(repo_root / "web" / "dashboard"),
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
    pgid: int | None,
    pid: int | None,
    *,
    expected_identity: dict[str, Any] | None = None,
    use_sigint: bool = False,
    name: str = "process",
) -> bool:
    """Stop a process group. Sends SIGINT/SIGTERM, waits 5s, then SIGKILL."""
    if pid is None:
        return True
    leader_running = _is_running(pid)
    group_running = _process_group_alive(pgid)
    if not leader_running and not group_running:
        return True
    identity = expected_identity or _capture_process_identity(pid)
    if _is_windows():
        if identity is None or not _process_identity_matches(identity):
            print(f"  [{name}] retained process identity unavailable or changed; refusing signal")
            return False
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
                return True
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
        return not _is_running(pid)

    current_identity = _capture_process_identity(pid)
    if (
        identity is None
        or (leader_running and current_identity != identity)
        or (not leader_running and current_identity not in (None, identity))
    ):
        print(f"  [{name}] retained process identity unavailable or changed; refusing signal")
        return False

    # Build a list of targets: try by pgid first, fall back to pid
    def _send(sig: signal.Signals) -> bool:
        current_identity = _capture_process_identity(pid)
        leader_is_running = _is_running(pid)
        if (leader_is_running and current_identity != identity) or (
            not leader_is_running and current_identity not in (None, identity)
        ):
            return False
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
        return _process_group_alive(pgid) or _is_running(pid)

    if not _any_alive():
        return True

    sig1 = signal.SIGINT if use_sigint else signal.SIGTERM
    if not _send(sig1):
        return not _any_alive()

    # Wait up to 5s for clean exit
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _any_alive():
            return True
        time.sleep(0.1)

    # Force kill
    if not _send(signal.SIGKILL):
        return not _any_alive()
    # Wait up to 2s for SIGKILL to take effect
    deadline2 = time.monotonic() + 2.0
    while time.monotonic() < deadline2:
        if not _any_alive():
            break
        time.sleep(0.05)
    print(f"  [{name}] SIGKILL sent (did not exit cleanly after 5s)")
    return not _any_alive()


def _make_proc_entry(proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Build state only after retaining a PID-reuse-resistant process identity."""
    ready_fd = getattr(proc, "_metriplane_ready_fd", None)
    if ready_fd is not None:
        proc._metriplane_ready_fd = None  # type: ignore[attr-defined]
        readiness_error: Exception | None = None
        acknowledged = False
        try:
            try:
                readable, _, _ = select.select([int(ready_fd)], [], [], 2.0)
                acknowledged = bool(readable) and os.read(int(ready_fd), 2) == b"\n"
            except (OSError, ValueError) as exc:
                readiness_error = exc
        finally:
            try:
                os.close(int(ready_fd))
            except OSError as exc:
                if readiness_error is None:
                    readiness_error = exc
        if readiness_error is not None:
            raise _LauncherStateError(
                "child supervisor identity gate I/O failed"
            ) from readiness_error
        if not acknowledged:
            raise _LauncherStateError("child supervisor did not reach its identity gate")
    identity = getattr(proc, "_metriplane_test_identity", None)
    deadline = time.monotonic() + 0.25
    while identity is None and proc.poll() is None and time.monotonic() < deadline:
        identity = _capture_process_identity(proc.pid)
        if identity is None:
            time.sleep(0.005)
    if identity is None:
        raise _LauncherStateError("could not retain child birth/executable/argv identity")
    entry = {"pid": proc.pid, "pgid": identity["pgid"], "identity": identity}
    _release_launch_gate(proc)
    return entry


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
        runner_info = state.get("runner", {})
        dash_info = state.get("dashboard", {})
        fusion_info = state.get("fusion", {})
        runner_pid = runner_info.get("pid")
        dash_pid = dash_info.get("pid")
        fusion_pid = fusion_info.get("pid")
        if (
            _is_running(runner_pid)
            or _process_group_alive(runner_info.get("pgid"))
            or _is_running(dash_pid)
            or _process_group_alive(dash_info.get("pgid"))
            or _is_running(fusion_pid)
            or _process_group_alive(fusion_info.get("pgid"))
        ):
            print("⚠️  Metriplane launcher is already running.")
            print("   Use `metriplane stop` first, or `metriplane status` to inspect.")
            return 1
        try:
            _clear_state(resolved_paths)
        except (OSError, _LauncherStateError) as exc:
            print(f"Cannot clear stale Metriplane launcher state: {exc}")
            return 2

    repo_root = _find_repo_root()
    session_capability = secrets.token_urlsafe(32)
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
        session_capability=session_capability,
    )
    try:
        runner_entry = _make_proc_entry(rp)
    except _LauncherStateError as exc:
        _discard_unreleased_process(rp)
        print(f"  ❌ Runner identity capture failed: {exc}")
        return 1
    if not _wait_for_port(runner_host, runner_port, timeout=8.0):
        print(f"  ❌ Runner did not start within 8s (pid={rp.pid})")
        runner_log = log_d / "runner.log"
        print(f"     Log: {runner_log}")
        returncode = rp.poll()
        if returncode is not None:
            print(f"     Runner exited with status {returncode}")
        _print_log_tail(runner_log)
        _stop_pg(
            runner_entry["pgid"],
            runner_entry["pid"],
            expected_identity=runner_entry["identity"],
            name="runner",
        )
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
    try:
        dashboard_entry = _make_proc_entry(dp)
    except _LauncherStateError as exc:
        _discard_unreleased_process(dp)
        _stop_pg(
            runner_entry["pgid"],
            runner_entry["pid"],
            expected_identity=runner_entry["identity"],
            name="runner",
        )
        print(f"  ❌ Dashboard identity capture failed: {exc}")
        return 1
    if not _wait_for_port(dashboard_host, dashboard_port, timeout=8.0):
        print(f"  ❌ Dashboard server did not start within 8s (pid={dp.pid})")
        _stop_pg(
            dashboard_entry["pgid"],
            dashboard_entry["pid"],
            expected_identity=dashboard_entry["identity"],
            name="dashboard",
        )
        _stop_pg(
            runner_entry["pgid"],
            runner_entry["pid"],
            expected_identity=runner_entry["identity"],
            name="runner",
        )
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
        try:
            fusion_entry = _make_proc_entry(fp)
        except _LauncherStateError as exc:
            _discard_unreleased_process(fp)
            _stop_pg(
                dashboard_entry["pgid"],
                dashboard_entry["pid"],
                expected_identity=dashboard_entry["identity"],
                name="dashboard",
            )
            _stop_pg(
                runner_entry["pgid"],
                runner_entry["pid"],
                expected_identity=runner_entry["identity"],
                name="runner",
            )
            print(f"  ❌ Runtime identity capture failed: {exc}")
            return 1
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
            _stop_pg(
                fusion_entry["pgid"],
                fusion_entry["pid"],
                expected_identity=fusion_entry["identity"],
                use_sigint=True,
                name="fusion",
            )
            _stop_pg(
                dashboard_entry["pgid"],
                dashboard_entry["pid"],
                expected_identity=dashboard_entry["identity"],
                name="dashboard",
            )
            _stop_pg(
                runner_entry["pgid"],
                runner_entry["pid"],
                expected_identity=runner_entry["identity"],
                name="runner",
            )
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
        "runner": {**runner_entry, "host": runner_host, "port": runner_port},
        "dashboard": {**dashboard_entry, "host": dashboard_host, "port": dashboard_port},
    }
    if fusion_entry is not None:
        new_state["fusion"] = fusion_entry
    try:
        _save_state(new_state, resolved_paths)
    except (OSError, _LauncherStateError) as exc:
        if fusion_entry is not None:
            _stop_pg(
                fusion_entry.get("pgid"),
                fusion_entry.get("pid"),
                expected_identity=fusion_entry.get("identity"),
                use_sigint=True,
                name="fusion",
            )
        _stop_pg(
            dashboard_entry["pgid"],
            dashboard_entry["pid"],
            expected_identity=dashboard_entry["identity"],
            name="dashboard",
        )
        _stop_pg(
            runner_entry["pgid"],
            runner_entry["pid"],
            expected_identity=runner_entry["identity"],
            name="runner",
        )
        try:
            _clear_state(resolved_paths)
        except (OSError, _LauncherStateError) as cleanup_exc:
            print(f"Cannot clear failed launcher state: {cleanup_exc}")
        print(f"Cannot save Metriplane launcher state: {exc}")
        return 2

    # --- Print URLs ---
    dash_url = f"http://{dashboard_host}:{dashboard_port}/index.html"
    op_url = f"http://{dashboard_host}:{dashboard_port}/operator.html"
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
        capability_fragment = urllib.parse.urlencode({"capability": session_capability})
        _open_browser(f"{open_url}#{capability_fragment}")
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
        if _is_running(fusion_pid) or _process_group_alive(fusion_pgid):
            if not isinstance(fusion_info.get("identity"), dict):
                print("  ❌ Fusion state has no retained process identity; refusing signal")
                return 2
            print(f"  Stopping fusion    (pid={fusion_pid} pgid={fusion_pgid}) …")
            if _stop_pg(
                fusion_pgid,
                fusion_pid,
                expected_identity=fusion_info.get("identity"),
                use_sigint=True,
                name="fusion",
            ):
                print("  ✅ Fusion stopped")
                stopped_any = True
            else:
                print("  ❌ Fusion identity changed; state retained and no signal was sent")
                return 2
        else:
            print(f"  ℹ️   Fusion pid={fusion_pid} already gone")

    # Runner
    if runner_pid:
        if _is_running(runner_pid) or _process_group_alive(runner_pgid):
            if not isinstance(runner_info.get("identity"), dict):
                print("  ❌ Runner state has no retained process identity; refusing signal")
                return 2
            print(f"  Stopping runner    (pid={runner_pid} pgid={runner_pgid}) …")
            if _stop_pg(
                runner_pgid,
                runner_pid,
                expected_identity=runner_info.get("identity"),
                name="runner",
            ):
                print("  ✅ Runner stopped")
                stopped_any = True
            else:
                print("  ❌ Runner identity changed; state retained and no signal was sent")
                return 2
        else:
            print(f"  ℹ️   Runner pid={runner_pid} already gone")

    # Dashboard
    if dash_pid:
        if _is_running(dash_pid) or _process_group_alive(dash_pgid):
            if not isinstance(dash_info.get("identity"), dict):
                print("  ❌ Dashboard state has no retained process identity; refusing signal")
                return 2
            print(f"  Stopping dashboard (pid={dash_pid} pgid={dash_pgid}) …")
            if _stop_pg(
                dash_pgid,
                dash_pid,
                expected_identity=dash_info.get("identity"),
                name="dashboard",
            ):
                print("  ✅ Dashboard stopped")
                stopped_any = True
            else:
                print("  ❌ Dashboard identity changed; state retained and no signal was sent")
                return 2
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
        if not _stop_pg(
            pgid,
            pid,
            expected_identity=owner.get("identity"),
            name=f"port-{port}",
        ):
            print(f"  ❌ Port {port}: process identity changed; signal refused")
            continue
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
    dash_url = f"http://{dhost}:{dport}/index.html"
    print(f"    Dashboard  : {dash_url}  {_http_badge(dash_url)}")
    op_url = f"http://{dhost}:{dport}/operator.html"
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
