#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from metriplane.paths import (
    PlatformPathError,
    normalize_runs_dir,
    resolve_platform_paths,
    resolve_runs_dir,
)
from metriplane.provenance.run_provenance import (
    generate_run_id,
    reserve_run_directory,
)
from metriplane.run_ids import validate_portable_run_id


def _resolve_output_path(value: str) -> Path:
    unresolved = Path(value)
    try:
        expanded = unresolved.expanduser()
        try:
            return expanded.resolve(strict=True)
        except FileNotFoundError:
            return expanded.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PlatformPathError(
            f"cannot resolve latency output path {unresolved}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M9.5 latency breakdown runner")
    ap.add_argument("--duration-s", type=float, default=15.0, help="How long to run before SIGINT (default: 15)")
    ap.add_argument("--out", type=str, required=True, help="Output CSV path (copied from run_dir/latency.csv)")
    ap.add_argument(
        "--runs-dir",
        type=str,
        default=None,
        help="Runs base dir (default: platform runs directory)",
    )
    ap.add_argument("--config", "-c", type=str, default="configs/fusion_health.yaml", help="Config YAML path")
    ap.add_argument(
        "--runner",
        choices=["run", "fusion"],
        default="run",
        help="Which runner to benchmark: 'run' (metriplane.run) or 'fusion' (metriplane.run_fusion)",
    )
    ap.add_argument("--run-id", type=str, default=None, help="Optional run id override (otherwise auto)")
    args = ap.parse_args(argv)

    try:
        requested_run_id = (
            generate_run_id("m95_latency") if args.run_id is None else args.run_id
        )
        run_id = validate_portable_run_id(requested_run_id)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        out_path = _resolve_output_path(args.out)
    except PlatformPathError as exc:
        print(f"output path error: {exc}", file=sys.stderr)
        return 2

    try:
        explicit_runs_dir = normalize_runs_dir(args.runs_dir)
        unresolved_runs_dir = (
            Path(explicit_runs_dir)
            if explicit_runs_dir is not None
            else resolve_platform_paths().runs_dir
        )
        runs_dir = resolve_runs_dir(unresolved_runs_dir)
        if runs_dir is None:
            raise AssertionError("run-recording root unexpectedly resolved as absent")
        runs_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PlatformPathError) as exc:
        print(f"platform path error: {exc}", file=sys.stderr)
        return 2

    try:
        reservation = reserve_run_directory(runs_dir, run_id)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"run reservation error: {exc}", file=sys.stderr)
        return 2
    run_id = reservation.run_id

    if args.runner == "fusion":
        cmd = [sys.executable, "-m", "metriplane.run_fusion", "--config", args.config, "--runs-dir", str(runs_dir), "--run-id", run_id]
    else:
        cmd = [sys.executable, "-m", "metriplane.run", "--config", args.config, "--runs-dir", str(runs_dir), "--run-id", run_id]

    print("=== M9.5 latency breakdown ===")
    print("runner    :", args.runner)
    print("config    :", args.config)
    print("runs_dir  :", runs_dir)
    print("run_id    :", run_id)
    print("duration  :", args.duration_s, "seconds")
    print("cmd       :", " ".join(cmd))
    print()

    try:
        proc = subprocess.Popen(
            cmd,
            env=reservation.child_environment(os.environ),
        )
    except OSError as exc:
        reservation.cancel_if_pending()
        print(f"ERROR: could not start benchmark runtime: {exc}", file=sys.stderr)
        return 2
    try:
        time.sleep(float(max(0.1, args.duration_s)))
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    try:
        rd = reservation.claimed_run_dir()
    except PlatformPathError as exc:
        reservation.cancel_if_pending()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    src = rd / "latency.csv"
    if not src.is_file():
        print(f"ERROR: {src} not found. Did you patch run.py/run_fusion.py to write latency.csv?", file=sys.stderr)
        return 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out_path)

    print("Run dir     :", rd)
    print("Copied from :", src)
    print("Wrote       :", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
