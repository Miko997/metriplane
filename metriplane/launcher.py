# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Metriplane Local Stack Launcher — v2

Manages the three local processes:
  - dashboard runner service  (127.0.0.1:9000)
  - static dashboard web server (127.0.0.1:8088, serves from repo root)
  - optional runtime stream (127.0.0.1:8000 metrics/health, ws://127.0.0.1:8765)

State: ~/.cache/metriplane/launcher-state.json
Logs:  ~/metriplane-runs/_launcher/<timestamp>/{runner,dashboard,fusion}.log

Key design decisions (v2):
- each child is its own process group leader (PGID = PID)
  (process_group=0 on macOS; start_new_session=True elsewhere)
- os.killpg(pgid, sig)    → kills the entire process group, not just the wrapper
- state stores both pid and pgid
- stop: SIGTERM → wait 5s → SIGKILL → poll port-free before clearing state
- status: shows port owners via ss -tlnp even when state file is absent
- cleanup: kills only identifiable Metriplane orphans on known ports
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATE_FILE = Path.home() / ".cache" / "metriplane" / "launcher-state.json"

_DEFAULT_RUNNER_HOST = "127.0.0.1"
_DEFAULT_RUNNER_PORT = 9000
_DEFAULT_DASHBOARD_PORT = 8088
_DEFAULT_DASHBOARD_HOST = "127.0.0.1"
_DEFAULT_FUSION_CONFIG = "configs/local_demo_replay.yaml"
_DEFAULT_DURATION_S = 7200
_DEFAULT_RUNS_DIR = str(Path.home() / "metriplane-runs")

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
    "http.server",           # dashboard static server (scoped to known port 8088)
]


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _state_dir() -> Path:
    d = _STATE_FILE.parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_state() -> dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    _state_dir()
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _clear_state() -> None:
    if _STATE_FILE.exists():
        _STATE_FILE.unlink()


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _is_running(pid: int | None) -> bool:
    """Return True if the process exists (any state)."""
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


def _get_pgid(pid: int) -> int | None:
    """Return process group ID of pid, or None if dead."""
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


def _launch(cmd: list[str], log_file: Path, cwd: Path, env: dict | None = None) -> subprocess.Popen:
    """Launch a subprocess in its own process group. Returns Popen."""
    # GitHub-hosted macOS runners have stalled children created with setsid().
    # A new process group preserves PGID-based cleanup without a detached session.
    group_options: dict[str, Any]
    if sys.platform == "darwin":
        group_options = {"process_group": 0}
    else:
        group_options = {"start_new_session": True}
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
    for line in content[-max(1, int(lines)):]:
        print(f"       {line}")


def _start_runner(
    *,
    host: str,
    port: int,
    dashboard_host: str,
    dashboard_port: int,
    log_file: Path,
    repo_root: Path,
) -> subprocess.Popen:
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
    ]
    return _launch(cmd, log_file, repo_root)


def _start_dashboard(*, host: str, port: int, log_file: Path, repo_root: Path) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "http.server", str(port), "--bind", host, "--directory", str(repo_root)]
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


def _start_fusion(*, config: str, run_id: str, runs_dir: str, duration_s: float,
                   backend: str, log_file: Path, repo_root: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["METRIPLANE_COMPUTE_BACKEND"] = "gpu" if backend == "gpu" else "cpu"
    module = _runtime_module_for_config(config, repo_root)
    cmd = [
        sys.executable, "-m", module,
        "--config", config,
        "--run-id", run_id,
        "--runs-dir", runs_dir,
    ]
    if module == "metriplane.run_fusion":
        cmd.extend(["--duration-s", str(duration_s)])
    return _launch(cmd, log_file, repo_root, env=env)


# ---------------------------------------------------------------------------
# Stop helpers — PGID-based
# ---------------------------------------------------------------------------

def _stop_pg(pgid: int | None, pid: int | None, *,
              use_sigint: bool = False, name: str = "process") -> None:
    """Stop a process group. Sends SIGINT/SIGTERM, waits 5s, then SIGKILL."""
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


def _make_proc_entry(proc: subprocess.Popen) -> dict[str, Any]:
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
    runs_dir: str = _DEFAULT_RUNS_DIR,
    open_browser: bool = True,
    operator: bool = False,
) -> int:
    """Start the local Metriplane stack. Returns exit code."""
    # Check for stale state with live processes
    state = _load_state()
    if state:
        runner_pid = state.get("runner", {}).get("pid")
        dash_pid = state.get("dashboard", {}).get("pid")
        if _is_running(runner_pid) or _is_running(dash_pid):
            print("⚠️  Metriplane launcher is already running.")
            print("   Use `metriplane stop` first, or `metriplane status` to inspect.")
            return 1
        _clear_state()

    repo_root = _find_repo_root()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_d = _log_dir_path(runs_dir, timestamp)

    print(f"🔍 Repo root : {repo_root}")
    print(f"📋 Log dir  : {log_d}")

    # Port checks — also check for orphaned VT processes
    for port, pname in [(runner_port, "runner"), (dashboard_port, "dashboard")]:
        if _is_port_in_use("127.0.0.1", port):
            owner = _find_port_owner(port)
            if owner and owner["safe_to_kill"]:
                print(f"\n⚠️  Port {port} ({pname}) held by orphaned Metriplane process "
                      f"(pid={owner['pid']}). Run `metriplane cleanup` to remove it.")
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
                    print(f"\n⚠️  Port {port} ({pname}) held by orphaned Metriplane process "
                          f"(pid={owner['pid']}). Run `metriplane cleanup` to remove it.")
                else:
                    print(f"\n❌ Port {port} ({pname}) is in use by an unknown process.")
                    if owner:
                        print(f"   Owner: pid={owner['pid']}  cmd={owner['cmdline'][:80]}")
                    print(f"   Try: lsof -nP -iTCP:{port} -sTCP:LISTEN  or  metriplane status")
                return 1

    # --- Start runner ---
    print(f"\n▶  Starting runner on http://{runner_host}:{runner_port}/")
    rp = _start_runner(host=runner_host, port=runner_port,
                       dashboard_host=dashboard_host, dashboard_port=dashboard_port,
                       log_file=log_d / "runner.log", repo_root=repo_root)
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
    dp = _start_dashboard(host=dashboard_host, port=dashboard_port,
                          log_file=log_d / "dashboard.log", repo_root=repo_root)
    if not _wait_for_port(dashboard_host, dashboard_port, timeout=8.0):
        print(f"  ❌ Dashboard server did not start within 8s (pid={dp.pid})")
        _stop_pg(dp.pid, dp.pid, name="dashboard")
        _stop_pg(rp.pid, rp.pid, name="runner")
        return 1
    print(f"  ✅ Dashboard OK  (pid={dp.pid})")

    # --- Start runtime stream ---
    fusion_entry: dict[str, Any] | None = None
    effective_run_id = run_id or f"live_{timestamp}"
    if live:
        print(f"▶  Starting runtime stream  (config={config}, run_id={effective_run_id})")
        fp = _start_fusion(config=config, run_id=effective_run_id,
                           runs_dir=runs_dir, duration_s=duration_s,
                           backend=backend, log_file=log_d / "fusion.log",
                           repo_root=repo_root)
        fusion_entry = _make_proc_entry(fp)
        fusion_entry.update({"run_id": effective_run_id, "config": config,
                              "backend": backend, "duration_s": duration_s})
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
            _clear_state()
            print("  ❌ Stack start aborted; all launcher children were stopped")
            return 1

    # --- Save state ---
    new_state: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "repo_root": str(repo_root),
        "log_dir": str(log_d),
        "timestamp": timestamp,
        "runner": {**_make_proc_entry(rp), "host": runner_host, "port": runner_port},
        "dashboard": {**_make_proc_entry(dp), "host": dashboard_host, "port": dashboard_port},
    }
    if fusion_entry is not None:
        new_state["fusion"] = fusion_entry
    _save_state(new_state)

    # --- Print URLs ---
    dash_url = f"http://{dashboard_host}:{dashboard_port}/web/dashboard/index.html"
    op_url = f"http://{dashboard_host}:{dashboard_port}/web/dashboard/operator.html"
    open_url = op_url if operator else dash_url

    print(f"\n{'='*60}")
    print("✅  Metriplane stack is running")
    print(f"{'='*60}")
    print(f"  Console      : {dash_url}")
    print(f"  Operator UI  : {op_url}")
    print(f"  Runner API   : http://{runner_host}:{runner_port}/status")
    if live and fusion_entry:
        print(f"  Health       : http://127.0.0.1:8000/health")
        print(f"  Metrics      : http://127.0.0.1:8000/metrics")
        print(f"  WebSocket    : ws://127.0.0.1:8765")
    elif not live:
        print("  Runtime      : idle until Setup or Run starts a session")
    print(f"\n  Logs         : {log_d}/")
    print(f"  State        : {_STATE_FILE}")
    print(f"\n  Stop with    : metriplane stop")
    print(f"{'='*60}")

    if open_browser:
        _open_browser(open_url)
        print(f"\n🌐 Opened {open_url}")

    return 0


def cmd_stop(force: bool = False) -> int:
    """Stop launcher-started processes and wait for ports to be released."""
    state = _load_state()
    if not state and not force:
        print("ℹ️   No launcher state found. Use `metriplane cleanup` if processes are orphaned.")
        return 0

    if not state:
        # force mode: fall through to cleanup behavior
        return cmd_cleanup()

    runner_info = state.get("runner") or {}
    dash_info = state.get("dashboard") or {}
    fusion_info = state.get("fusion") or {}

    runner_pid  = runner_info.get("pid")
    runner_pgid = runner_info.get("pgid") or runner_pid
    runner_port = runner_info.get("port", _DEFAULT_RUNNER_PORT)

    dash_pid  = dash_info.get("pid")
    dash_pgid = dash_info.get("pgid") or dash_pid
    dash_port = dash_info.get("port", _DEFAULT_DASHBOARD_PORT)

    fusion_pid  = fusion_info.get("pid")
    fusion_pgid = fusion_info.get("pgid") or fusion_pid

    stopped_any = False

    # Fusion first (SIGINT for clean recording flush)
    if fusion_pid:
        if _is_running(fusion_pid):
            print(f"  Stopping fusion    (pid={fusion_pid} pgid={fusion_pgid}) …")
            _stop_pg(fusion_pgid, fusion_pid, use_sigint=True, name="fusion")
            print(f"  ✅ Fusion stopped")
            stopped_any = True
        else:
            print(f"  ℹ️   Fusion pid={fusion_pid} already gone")

    # Runner
    if runner_pid:
        if _is_running(runner_pid):
            print(f"  Stopping runner    (pid={runner_pid} pgid={runner_pgid}) …")
            _stop_pg(runner_pgid, runner_pid, name="runner")
            print(f"  ✅ Runner stopped")
            stopped_any = True
        else:
            print(f"  ℹ️   Runner pid={runner_pid} already gone")

    # Dashboard
    if dash_pid:
        if _is_running(dash_pid):
            print(f"  Stopping dashboard (pid={dash_pid} pgid={dash_pgid}) …")
            _stop_pg(dash_pgid, dash_pid, name="dashboard")
            print(f"  ✅ Dashboard stopped")
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

    _clear_state()

    if all_free:
        msg = "✅ All launcher services stopped." if stopped_any else "ℹ️   No live processes found (state cleared)."
        print(f"\n{msg}")
    else:
        print("\n⚠️  Some ports may still be in use. Run `metriplane cleanup` if needed.")
    return 0


def cmd_cleanup() -> int:
    """Kill only known Metriplane orphans on known ports. Never kills unknown processes."""
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
            print(f"    → SKIPPED (not a known Metriplane pattern)")
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

    _clear_state()  # Remove any stale state

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
    runs_dir: str = _DEFAULT_RUNS_DIR,
    open_browser: bool = True,
    operator: bool = False,
) -> int:
    """Stop all services (including orphans), then start fresh."""
    print("⟳  Stopping existing stack …")
    state = _load_state()
    if state:
        cmd_stop()
    else:
        # Even without state, hunt for known orphaned VT processes
        cleanup_ports = [runner_port, dashboard_port]
        if live:
            cleanup_ports.extend([8000, 8765])
        needs_cleanup = any(_is_port_in_use("127.0.0.1", p) for p in cleanup_ports)
        if needs_cleanup:
            print("ℹ️   No launcher state but Metriplane ports are occupied — running cleanup …")
            cmd_cleanup()

    # Final check: wait a bit for ports to stabilize
    time.sleep(0.3)
    for port, pname in [(runner_port, "runner"), (dashboard_port, "dashboard")]:
        if _is_port_in_use("127.0.0.1", port):
            _wait_for_port_free(port, timeout=4.0)

    print("\n⟳  Starting new stack …")
    return cmd_start(
        live=live, backend=backend, config=config, duration_s=duration_s,
        run_id=run_id, dashboard_host=dashboard_host, dashboard_port=dashboard_port,
        runner_host=runner_host, runner_port=runner_port, runs_dir=runs_dir,
        open_browser=open_browser, operator=operator,
    )


def cmd_status() -> int:
    """Show status of launcher services and probe known ports — even without state."""
    state = _load_state()

    print("Metriplane Launcher Status")
    print("=" * 60)

    if state:
        started_at = state.get("started_at", "unknown")
        print(f"  State file  : {_STATE_FILE}")
        print(f"  Started at  : {started_at}")
        print(f"  Log dir     : {state.get('log_dir', 'unknown')}")
        print()

    runner_info = state.get("runner") or {}
    dash_info   = state.get("dashboard") or {}
    fusion_info = state.get("fusion") or {}

    def _pid_badge(pid, pgid=None):
        if pid and _is_running(pid):
            g = f" pgid={pgid}" if pgid and pgid != pid else ""
            return f"✅ running (pid={pid}{g})"
        elif pid:
            return f"❌ dead    (pid={pid})"
        return "— not in state"

    def _http_badge(url):
        return "🟢 online" if _probe_http(url) else "🔴 offline"

    # --- Runner ---
    rpid  = runner_info.get("pid")
    rpgid = runner_info.get("pgid")
    rport = runner_info.get("port", _DEFAULT_RUNNER_PORT)
    rhost = runner_info.get("host", _DEFAULT_RUNNER_HOST)
    print(f"  Runner       : {_pid_badge(rpid, rpgid)}")
    r_url = f"http://{rhost}:{rport}/status"
    print(f"    URL        : {r_url}  {_http_badge(r_url)}")
    if rpid is None:
        _show_port_owner(rport, "  ")

    # --- Dashboard ---
    dpid  = dash_info.get("pid")
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
        fpid  = fusion_info.get("pid")
        fpgid = fusion_info.get("pgid")
        frun  = fusion_info.get("run_id", "unknown")
        print(f"  Fusion       : {_pid_badge(fpid, fpgid)}  run_id={frun}")
    else:
        print("  Runtime      : — idle until Setup or Run starts a session")

    # Always show health/metrics/WS port status
    print(f"    Health     : http://127.0.0.1:8000/health  {_http_badge('http://127.0.0.1:8000/health')}")
    print(f"    Metrics    : http://127.0.0.1:8000/metrics {_http_badge('http://127.0.0.1:8000/metrics')}")
    print(f"    WebSocket  : ws://127.0.0.1:8765", end="")
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
