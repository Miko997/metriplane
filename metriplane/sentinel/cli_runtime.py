# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main_sentinel(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane sentinel")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run Sentinel shadow auditor over a replay session")
    run.add_argument("--config", required=True, help="Sentinel YAML config")
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--runs-dir", default=None, help="Base directory for run artifacts (default: ./runs)"
    )

    status = sub.add_parser("status", help="Print a sentinel_summary.json")
    status.add_argument("run_dir")

    args = p.parse_args(argv)

    if args.cmd == "run":
        return _run(args)
    if args.cmd == "status":
        return _status(args)
    return 1


def _run(args: argparse.Namespace) -> int:
    import yaml

    from metriplane.sentinel.config import SentinelConfig
    from metriplane.sentinel.runtime import SentinelError, SentinelRuntime

    cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    sentinel_dict = cfg.get("sentinel") or {}
    sentinel_cfg = SentinelConfig.from_dict(sentinel_dict)

    if not sentinel_cfg.enabled:
        print("sentinel.enabled is false; nothing to run")
        return 1

    session_path = cfg.get("replay_input")
    if not session_path:
        print("config must set replay_input (path to a session JSONL)")
        return 1

    run_id = args.run_id or "sentinel_run"
    runs_dir = Path(args.runs_dir) if args.runs_dir else Path("runs")
    run_dir = runs_dir / run_id

    try:
        runtime = SentinelRuntime(sentinel_cfg, run_dir=run_dir, run_id=run_id)
    except SentinelError as e:
        print(f"sentinel failed to start: {e}")
        return 1

    from metriplane.sentinel.engine import iter_frames
    from metriplane.schema import frame_time_s

    for frame in iter_frames(session_path):
        observed = frame.fused if frame.fused is not None else frame.objects
        runtime.update(frame_time_s(frame), frame.frame_id, observed, frame=frame)

    summary_path = runtime.close()

    # Copy the session + object registry into the run dir so the operator dashboard and
    # assistant can read this run directly (objects, traces, names).
    try:
        import shutil

        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(session_path, run_dir / "session.jsonl")
        if sentinel_cfg.objects_file and Path(sentinel_cfg.objects_file).exists():
            shutil.copyfile(sentinel_cfg.objects_file, run_dir / "objects.yaml")
        if sentinel_cfg.zones_file and Path(sentinel_cfg.zones_file).exists():
            shutil.copyfile(sentinel_cfg.zones_file, run_dir / "zones.yaml")
        if sentinel_cfg.contracts_file and Path(sentinel_cfg.contracts_file).exists():
            shutil.copyfile(sentinel_cfg.contracts_file, run_dir / "contracts.yaml")
    except Exception:
        pass

    status = runtime.status()

    print(f"mode={status.mode} control_enabled={status.control_enabled} run_id={status.run_id}")
    print(
        f"objects_tracked={status.objects_tracked} "
        f"active_alerts={status.active_alerts} "
        f"open_incidents={status.open_incidents} health={status.health}"
    )
    if summary_path:
        print(f"summary: {summary_path}")
    return 0


def _status(args: argparse.Namespace) -> int:
    summary_file = Path(args.run_dir)
    if summary_file.is_dir():
        summary_file = summary_file / "sentinel_summary.json"
    if not summary_file.exists():
        print(f"no sentinel_summary.json at {summary_file}")
        return 1
    print(json.dumps(json.loads(summary_file.read_text()), indent=2))
    return 0
