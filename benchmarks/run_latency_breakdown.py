#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from metriplane.provenance.run_provenance import generate_run_id


def _best_run_dir(runs_dir: Path, run_id: str) -> Path | None:
    # Prefer exact match
    direct = runs_dir / run_id
    if direct.is_dir():
        return direct

    # Otherwise look for suffixed dirs (run_id-1, run_id-2, ...)
    cands = sorted(
        runs_dir.glob(f"{run_id}*"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for p in cands:
        if p.is_dir():
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="M9.5 latency breakdown runner")
    ap.add_argument(
        "--duration-s", type=float, default=15.0, help="How long to run before SIGINT (default: 15)"
    )
    ap.add_argument(
        "--out", type=str, required=True, help="Output CSV path (copied from run_dir/latency.csv)"
    )
    ap.add_argument(
        "--runs-dir", type=str, default=str(Path.home() / "metriplane-runs"), help="Runs base dir"
    )
    ap.add_argument(
        "--config", "-c", type=str, default="configs/fusion_health.yaml", help="Config YAML path"
    )
    ap.add_argument(
        "--runner",
        choices=["run", "fusion"],
        default="run",
        help="Which runner to benchmark: 'run' (metriplane.run) or 'fusion' (metriplane.run_fusion)",
    )
    ap.add_argument(
        "--run-id", type=str, default=None, help="Optional run id override (otherwise auto)"
    )
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir).expanduser().resolve()
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or generate_run_id("m95_latency")
    out_path = Path(args.out).expanduser().resolve()

    if args.runner == "fusion":
        cmd = [
            sys.executable,
            "-m",
            "metriplane.run_fusion",
            "--config",
            args.config,
            "--runs-dir",
            str(runs_dir),
            "--run-id",
            run_id,
        ]
    else:
        cmd = [
            sys.executable,
            "-m",
            "metriplane.run",
            "--config",
            args.config,
            "--runs-dir",
            str(runs_dir),
            "--run-id",
            run_id,
        ]

    print("=== M9.5 latency breakdown ===")
    print("runner    :", args.runner)
    print("config    :", args.config)
    print("runs_dir  :", runs_dir)
    print("run_id    :", run_id)
    print("duration  :", args.duration_s, "seconds")
    print("cmd       :", " ".join(cmd))
    print()

    proc = subprocess.Popen(cmd)
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

    rd = _best_run_dir(runs_dir, run_id)
    if rd is None:
        print(
            f"ERROR: could not find run dir for run_id={run_id} under {runs_dir}", file=sys.stderr
        )
        return 2

    src = rd / "latency.csv"
    if not src.is_file():
        print(
            f"ERROR: {src} not found. Did you patch run.py/run_fusion.py to write latency.csv?",
            file=sys.stderr,
        )
        return 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out_path)

    print("Run dir     :", rd)
    print("Copied from :", src)
    print("Wrote       :", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
