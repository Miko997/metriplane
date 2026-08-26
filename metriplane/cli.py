# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import glob
import importlib
import logging
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from metriplane.paths import (
    PlatformPathError,
    PlatformPaths,
    normalize_runs_dir,
    resolve_platform_paths,
)

log = logging.getLogger("metriplane.cli")


def _main_help() -> int:
    """Show the small, stable set of commands most users need first."""
    print(
        """Metriplane helps explain what went wrong in a recorded robot or assembly workcell run.

It creates a report of what happened, preserves the supporting evidence, and
builds a repeatable check that can catch the same problem after a change.

Usage:
  metriplane <command> [options]

Start here:
  demo       Run a complete recorded-incident example
  doctor     Check whether this installation is ready

More commands:
  atlas      Create, verify, and rerun incident evidence
  external   Validate and run a portable external fixture bundle
  replay     Replay a recorded JSONL timeline the same way every time
  test       Rerun a bundle and compare its incidents and events with expectations
  incidents  Find, inspect, and package incidents from a recording
  run        Process a live camera or a recorded session

Run `metriplane <command> --help` for command-specific options.
Run `metriplane --version` to show the installed package version.
Existing `metriplane --config ...` invocations remain supported as runtime shorthand.
"""
    )
    return 0


def _main_run(argv: list[str], *, paths: PlatformPaths | None = None) -> int:
    # Lazy imports to allow doctor command to run without dependencies
    from metriplane.config import load_config
    from metriplane.run import run_loop
    
    p = argparse.ArgumentParser("metriplane")
    p.add_argument("--config", default="config.example.yaml", help="Path to YAML config")
    p.add_argument(
        "--profile",
        default=None,
        help=(
            "Calibration profile name (defaults to calib/active_profile.yaml). "
            "Profile maps to calib/profiles/<profile>/..."
        ),
    )

    # M9.4: provenance controls
    p.add_argument("--run-id", default=None, help="Optional run id override (otherwise auto).")
    p.add_argument(
        "--runs-dir",
        default=None,
        help=(
            "Override runs base dir (default: platform runs directory). "
            "Example: --runs-dir /path/to/runs"
        ),
    )

    # M9.3: reproducible fault injection (passthrough to run_loop)
    p.add_argument(
        "--fault",
        action="append",
        default=[],
        help="Fault injection (repeatable). Example: --fault ws_send_fail_after_s=12",
    )

    args = p.parse_args(argv)

    cfg = load_config(Path(args.config))

    if (
        paths is None
        and normalize_runs_dir(args.runs_dir) is None
        and normalize_runs_dir(cfg.runs_dir) is None
    ):
        try:
            paths = resolve_platform_paths()
        except PlatformPathError as exc:
            print(f"platform path error: {exc}", file=sys.stderr)
            return 2

    # Allow CLI to override profile without requiring config edits.
    if args.profile:
        cfg = replace(cfg, profile=str(args.profile))

    log.info(
        "loaded config: path=%s profile=%s source_mode=%s camera_backend=%s "
        "vision_backend=%s",
        args.config,
        cfg.profile or "(none)",
        cfg.source_mode,
        cfg.camera_backend,
        cfg.vision_backend,
    )

    return run_loop(
        cfg,
        cli_faults=list(args.fault or []),
        config_path=Path(args.config),
        argv=["metriplane", *argv],
        run_id=str(args.run_id) if args.run_id else None,
        runs_dir=str(args.runs_dir) if args.runs_dir else None,
        paths=paths,
    )


def _main_replay(argv: list[str]) -> int:
    # Lazy imports to allow doctor command to run without dependencies
    from metriplane.replay.engine import EngineConfig, iter_replay_outputs, write_outputs_jsonl
    
    p = argparse.ArgumentParser("metriplane replay")
    p.add_argument("--input", required=True, help="Input JSONL session file")
    p.add_argument("--clock", choices=["replay", "fixed"], default="replay")
    p.add_argument("--dt-ms", type=int, default=None, help="Required when --clock fixed")
    p.add_argument("--run-id", default=None)
    p.add_argument(
        "--speed",
        type=float,
        default=None,
        help="Deprecated compatibility option; deterministic file output is unpaced",
    )
    p.add_argument(
        "--output-file",
        default=None,
        help="If set: write JSONL outputs and exit (NO WS server).",
    )
    args = p.parse_args(argv)

    if args.clock == "fixed" and args.dt_ms is None:
        p.error("--dt-ms is required when --clock fixed")

    if not args.output_file:
        # Spec rule you gave: output-file mode is the non-interactive path.
        # Keep it strict for now (we can add WS streaming later).
        p.error("--output-file is required for replay CLI in M9.1 (non-interactive determinism mode)")

    if args.speed is not None:
        print(
            "WARNING: --speed is retained for compatibility but deterministic "
            "file output is not wall-clock paced.",
            file=sys.stderr,
        )

    cfg = EngineConfig(
        input_path=Path(args.input),
        clock=str(args.clock),
        dt_ms=int(args.dt_ms) if args.dt_ms is not None else None,
        run_id=str(args.run_id or "replay"),
        speed=float(args.speed) if args.speed is not None else None,
    )

    outputs = iter_replay_outputs(cfg)
    out_path = Path(args.output_file)
    write_outputs_jsonl(out_path, outputs)
    print(f"[metriplane replay] wrote {out_path}")
    return 0


def _check_python_version() -> tuple[str, str]:
    """Check the declared Python 3.12/3.13 compatibility boundary."""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    if version.major == 3 and version.minor in {12, 13}:
        return ("PASS", f"Python {version_str}")
    return ("FAIL", f"Python {version_str} (requires Python 3.12 or 3.13)")


def _check_import_metriplane() -> tuple[str, str]:
    """Check metriplane import works."""
    try:
        import metriplane  # noqa: F401

        return ("PASS", "metriplane import successful")
    except Exception as exc:
        return ("FAIL", f"metriplane import failed: {exc}")


def _check_required_dependencies() -> tuple[str, str]:
    """Check every declared runtime dependency can be imported."""
    modules = ("numpy", "cv2", "yaml", "websockets", "pydantic")
    failures: list[str] = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:
            failures.append(f"{module} ({type(exc).__name__})")
    if failures:
        return ("FAIL", f"Required dependencies unavailable: {', '.join(failures)}")
    return ("PASS", f"Required dependencies available ({len(modules)} modules)")


def _package_source_root() -> Path:
    """Return the possible checkout root for the imported package code."""
    return Path(__file__).resolve().parents[1]


def _check_git_commit() -> tuple[str, str]:
    """Check the imported package checkout's Git commit availability."""
    try:
        result = subprocess.run(
            ["git", "-C", str(_package_source_root()), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        commit = result.stdout.strip()
        return ("PASS", f"Git commit {commit}")
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ("WARN", "Git commit not available for the source checkout")


def _check_demo_resources() -> tuple[str, str]:
    """Check the installed wheel contains every bundled-demo input."""
    try:
        from importlib import resources

        from metriplane.demo import BUNDLED_DEMO_RESOURCES

        package = resources.files("metriplane.demo")
        missing = [
            path
            for path in BUNDLED_DEMO_RESOURCES
            if not package.joinpath(path).is_file()
        ]
    except Exception as exc:
        return ("FAIL", f"Bundled demo resources could not be inspected: {exc}")
    if missing:
        return ("FAIL", f"Bundled demo resources missing: {', '.join(missing)}")
    return (
        "PASS",
        f"Bundled demo resources available ({len(BUNDLED_DEMO_RESOURCES)} files)",
    )


def _installation_context() -> str:
    """Describe whether doctor is running from an editable checkout or a package."""
    root = _package_source_root()
    pyproject = root / "pyproject.toml"
    try:
        import json
        import tomllib
        from importlib import metadata

        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        is_source_checkout = (
            project.get("project", {}).get("name") == "metriplane"
            and (root / "metriplane" / "cli.py").is_file()
        )
    except Exception:
        is_source_checkout = False
    if not is_source_checkout:
        return "installed distribution"

    try:
        distribution = metadata.distribution("metriplane")
        direct_url = distribution.read_text("direct_url.json")
        if direct_url:
            payload = json.loads(direct_url)
            if payload.get("dir_info", {}).get("editable") is True:
                return "editable source checkout"
    except Exception:
        pass
    return "source checkout"


def _check_vt_sh_exists() -> tuple[str, str]:
    """Check tools/mp.sh exists."""
    path = _package_source_root() / "tools/mp.sh"
    if path.exists():
        return ("PASS", "tools/mp.sh exists")
    return ("WARN", "tools/mp.sh not found (source-checkout helper, optional)")


def _check_config_exists() -> tuple[str, str]:
    """Check configs/fusion_health_300fps.yaml exists."""
    path = _package_source_root() / "configs/fusion_health_300fps.yaml"
    if path.exists():
        return ("PASS", "configs/fusion_health_300fps.yaml exists")
    return (
        "WARN",
        "configs/fusion_health_300fps.yaml not found "
        "(source-checkout live-camera example, optional)",
    )


def _check_ports_available() -> tuple[str, str]:
    """Check ports 8000, 8001, 8765 availability."""
    ports = [8000, 8001, 8765]
    unavailable = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            unavailable.append(port)
        finally:
            sock.close()

    if not unavailable:
        return ("PASS", f"Ports {', '.join(map(str, ports))} available")
    return (
        "WARN",
        f"Ports {', '.join(map(str, unavailable))} in use "
        "(may be Metriplane already running)",
    )


def _check_video_devices() -> tuple[str, str]:
    """Check /dev/video* availability."""
    devices = glob.glob("/dev/video*")
    if devices:
        device_list = ", ".join(sorted(devices))
        return ("PASS", f"Camera devices found: {device_list}")
    return (
        "WARN",
        "No /dev/video* devices found (not needed for the bundled camera-free demo)",
    )


def _check_nvidia_smi() -> tuple[str, str]:
    """Check nvidia-smi availability (GPU optional)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        gpu_name = result.stdout.strip().split("\n")[0] if result.stdout.strip() else "Unknown GPU"
        return ("PASS", f"GPU available: {gpu_name}")
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ("WARN", "nvidia-smi not available (GPU is optional for the bundled demo)")


def _main_doctor(argv: list[str]) -> int:
    """Run Metriplane environment checks."""
    p = argparse.ArgumentParser("metriplane doctor")
    p.parse_args(argv)  # No args yet, but keep for future expansion

    print("Metriplane Doctor - Installation Readiness")
    print("=" * 50)
    installation_context = _installation_context()
    print(f"Installation: {installation_context}")

    required_checks = [
        _check_python_version(),
        _check_import_metriplane(),
        _check_required_dependencies(),
        _check_demo_resources(),
    ]
    source_checks = (
        [_check_git_commit(), _check_vt_sh_exists(), _check_config_exists()]
        if installation_context in {"source checkout", "editable source checkout"}
        else [
            (
                "WARN",
                "Source-checkout development checks skipped for installed distribution",
            )
        ]
    )
    optional_checks = [
        *source_checks,
        _check_ports_available(),
        _check_video_devices(),
        _check_nvidia_smi(),
    ]

    status_icons = {
        "PASS": "✅",
        "WARN": "⚠️",
        "FAIL": "❌",
    }

    print("Required for the bundled camera-free demo:")
    for status, message in required_checks:
        icon = status_icons.get(status, "?")
        print(f"{icon} {status}: {message}")

    fail_count = sum(1 for status, _ in required_checks if status == "FAIL")
    warn_count = sum(1 for status, _ in required_checks if status == "WARN")
    pass_count = sum(1 for status, _ in required_checks if status == "PASS")
    print(f"Summary: {pass_count} passed, {warn_count} warnings, {fail_count} failed")

    print("\nOptional capabilities:")
    for status, message in optional_checks:
        if status == "PASS":
            print(f"✅ AVAILABLE: {message}")
        else:
            print(f"○ OPTIONAL: {message}")
    optional_available = sum(1 for status, _ in optional_checks if status == "PASS")
    optional_unavailable = len(optional_checks) - optional_available
    print(
        f"Optional: {optional_available} available, "
        f"{optional_unavailable} unavailable or not configured"
    )
    print("=" * 50)

    if fail_count > 0:
        print("\nNot ready for the bundled camera-free demo. See required FAIL items above.")
        return 1
    print("\nReady for the bundled camera-free demo.")
    return 0


# ---------------------------------------------------------------------------
# Launcher subcommands
# ---------------------------------------------------------------------------

_LAUNCHER_FLAGS_HELP = """\
Launcher flags (shared by start and restart):
  --live              Start runtime stream immediately
  --no-live           Dashboard/runner only, no runtime stream (default)
  --backend cpu|gpu   Compute backend for fusion (default: cpu)
  --config PATH       Runtime config YAML (default: configs/local_demo_replay.yaml)
  --duration-s INT    Stop fusion after N seconds (default: 7200)
  --run-id TEXT       Override run ID (default: live_YYYYMMDD_HHMMSS)
  --dashboard-port N  Dashboard web server port (default: 8088)
  --runner-port N     Dashboard runner API port (default: 9000)
  --runs-dir PATH     Runs base directory (default: platform runs directory)
  --open / --no-open  Open browser after start (default: --open)
  --operator          Open operator.html instead of runtime dashboard
"""


def _build_launcher_parser(name: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        f"metriplane {name}",
        description=f"Metriplane one-command local stack ({name}).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_LAUNCHER_FLAGS_HELP,
    )
    if name in ("start", "restart"):
        p.add_argument("--live", action="store_true", default=False,
                       help="Start runtime stream immediately (default: off)")
        p.add_argument("--no-live", dest="live", action="store_false",
                       help="Dashboard/runner only — no runtime stream (default)")
        p.add_argument("--backend", choices=["cpu", "gpu"], default="cpu",
                       help="Fusion compute backend (default: cpu)")
        p.add_argument("--config", default="configs/local_demo_replay.yaml",
                       help="Runtime config YAML")
        p.add_argument("--duration-s", type=float, default=7200,
                       dest="duration_s", help="Stop fusion after N seconds (default: 7200)")
        p.add_argument("--run-id", default=None, dest="run_id",
                       help="Override fusion run ID")
        p.add_argument("--dashboard-port", type=int, default=8088,
                       dest="dashboard_port", help="Dashboard server port (default: 8088)")
        p.add_argument("--runner-port", type=int, default=9000,
                       dest="runner_port", help="Runner API port (default: 9000)")
        p.add_argument("--runs-dir", default=None, dest="runs_dir",
                       help="Runs base directory (default: platform runs directory)")
        p.add_argument("--open", action="store_true", default=True, dest="open_browser",
                       help="Open browser after start (default: on)")
        p.add_argument("--no-open", action="store_false", dest="open_browser",
                       help="Do not open browser")
        p.add_argument("--operator", action="store_true", default=False,
                       help="Open operator.html instead of the Metriplane home console")
    return p


def _main_start(
    argv: list[str],
    *,
    paths: PlatformPaths | None = None,
) -> int:
    from metriplane.launcher import cmd_start
    p = _build_launcher_parser("start")
    args = p.parse_args(argv)
    return cmd_start(
        live=bool(args.live),
        backend=str(args.backend),
        config=str(args.config),
        duration_s=float(args.duration_s),
        run_id=str(args.run_id) if args.run_id else None,
        dashboard_port=int(args.dashboard_port),
        runner_port=int(args.runner_port),
        runs_dir=str(args.runs_dir) if args.runs_dir else None,
        open_browser=bool(args.open_browser),
        operator=bool(args.operator),
        paths=paths,
    )


def _main_stop(
    argv: list[str],
    *,
    paths: PlatformPaths | None = None,
) -> int:
    from metriplane.launcher import cmd_stop
    p = argparse.ArgumentParser("metriplane stop",
                                description="Stop all launcher-started Metriplane processes.")
    p.add_argument("--force", action="store_true", default=False,
                   help="Force-stop even without state file; runs cleanup for orphaned VT processes")
    args = p.parse_args(argv)
    return cmd_stop(force=bool(args.force), paths=paths)


def _main_cleanup(
    argv: list[str],
    *,
    paths: PlatformPaths | None = None,
) -> int:
    from metriplane.launcher import cmd_cleanup
    p = argparse.ArgumentParser("metriplane cleanup",
                                description="Remove orphaned Metriplane processes on known ports. "
                                            "Only kills processes matching known Metriplane patterns.")
    p.parse_args(argv)
    return cmd_cleanup(paths=paths)


def _main_restart(
    argv: list[str],
    *,
    paths: PlatformPaths | None = None,
) -> int:
    from metriplane.launcher import cmd_restart
    p = _build_launcher_parser("restart")
    args = p.parse_args(argv)
    return cmd_restart(
        live=bool(args.live),
        backend=str(args.backend),
        config=str(args.config),
        duration_s=float(args.duration_s),
        run_id=str(args.run_id) if args.run_id else None,
        dashboard_port=int(args.dashboard_port),
        runner_port=int(args.runner_port),
        runs_dir=str(args.runs_dir) if args.runs_dir else None,
        open_browser=bool(args.open_browser),
        operator=bool(args.operator),
        paths=paths,
    )


def _main_status(
    argv: list[str],
    *,
    paths: PlatformPaths | None = None,
) -> int:
    from metriplane.launcher import cmd_status
    p = argparse.ArgumentParser("metriplane status",
                                description="Show status of launcher-started Metriplane services.")
    p.parse_args(argv)
    return cmd_status(paths=paths)


def main(
    argv: list[str] | None = None,
    *,
    paths: PlatformPaths | None = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Fast-path commands that need no logging setup
    if argv in (["-h"], ["--help"]):
        return _main_help()
    if argv in (["-V"], ["--version"]):
        from metriplane import __version__

        print(f"metriplane {__version__}")
        return 0
    if argv and argv[0] == "demo":
        from metriplane.demo import main as demo_main
        return demo_main(argv[1:])
    if argv and argv[0] == "doctor":
        return _main_doctor(argv[1:])
    if argv and argv[0] == "objects":
        from metriplane.sentinel.cli_registry import main_objects
        return main_objects(argv[1:])
    if argv and argv[0] == "rules":
        from metriplane.sentinel.cli_rules import main_rules
        return main_rules(argv[1:])
    if argv and argv[0] == "incidents":
        from metriplane.sentinel.cli_incidents import main_incidents
        return main_incidents(argv[1:])
    if argv and argv[0] == "query":
        from metriplane.sentinel.cli_query import main_query
        return main_query(argv[1:])
    if argv and argv[0] == "contracts":
        from metriplane.contracts.cli import main as contracts_main
        return contracts_main(argv[1:])
    if argv and argv[0] == "sentinel":
        from metriplane.sentinel.cli_runtime import main_sentinel
        if paths is None:
            return main_sentinel(argv[1:])
        return main_sentinel(argv[1:], paths=paths)
    if argv and argv[0] == "test":
        from metriplane.testing.cli import main_test
        return main_test(argv[1:])
    if argv and argv[0] == "counterfactual":
        from metriplane.counterfactuals.cli import main_counterfactual
        return main_counterfactual(argv[1:])
    if argv and argv[0] == "command-center":
        from metriplane.runner.cli_command_center import main_command_center
        return main_command_center(argv[1:])
    if argv and argv[0] == "camera-trust":
        from metriplane.camera_trust.cli import main_camera_trust
        return main_camera_trust(argv[1:])
    if argv and argv[0] == "ask":
        from metriplane.assistant.cli import main_ask
        return main_ask(argv[1:])
    if argv and argv[0] == "traces":
        from metriplane.trace.cli_traces import main_traces
        return main_traces(argv[1:])
    if argv and argv[0] == "atlas":
        from metriplane.atlas.cli import main as atlas_main
        return atlas_main(argv[1:])
    if argv and argv[0] == "external":
        from metriplane.external_sources.cli import main as external_main
        return external_main(argv[1:])
    if argv and argv[0] == "start":
        return _main_start(argv[1:], paths=paths)
    if argv and argv[0] == "stop":
        return _main_stop(argv[1:], paths=paths)
    if argv and argv[0] == "restart":
        return _main_restart(argv[1:], paths=paths)
    if argv and argv[0] == "status":
        return _main_status(argv[1:], paths=paths)
    if argv and argv[0] == "cleanup":
        return _main_cleanup(argv[1:], paths=paths)
    # Setup logging for run and replay commands
    from metriplane.logging import setup_logging
    setup_logging()

    if argv and argv[0] == "run":
        if paths is None:
            return _main_run(argv[1:])
        return _main_run(argv[1:], paths=paths)
    if argv and argv[0] == "replay":
        return _main_replay(argv[1:])
    if paths is None:
        return _main_run(argv)
    return _main_run(argv, paths=paths)


if __name__ == "__main__":
    raise SystemExit(main())
