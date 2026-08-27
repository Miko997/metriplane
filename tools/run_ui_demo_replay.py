#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build the camera-free MetriPlane demo path used by the localhost UI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from metriplane.paths import (
    PlatformPathError,
    normalize_runs_dir,
    resolve_platform_paths,
    resolve_runs_dir,
)
from metriplane.provenance.run_provenance import generate_run_id
from metriplane.run_ids import validate_portable_run_id

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RUN = ROOT / "web/dashboard/atlas_run"
INCIDENT_DIR = EVIDENCE_RUN / "evidence_bundles/INC-0001"


def run_step(label: str, command: list[str]) -> None:
    print(f"\n== {label} ==")
    print(" ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="Run-recording base directory (default: platform runs directory)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Portable run identifier (default: generate a unique identifier)",
    )
    args = parser.parse_args(argv)

    py = sys.executable
    try:
        requested_run_id = (
            generate_run_id("metriplane_demo") if args.run_id is None else args.run_id
        )
        run_id = validate_portable_run_id(requested_run_id)
    except ValueError as exc:
        print(exc, file=sys.stderr)
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
    run_step(
        "Build incident replay for Command Center",
        [
            py,
            "-m",
            "metriplane.cli",
            "sentinel",
            "run",
            "--config",
            "configs/sentinel_operator_demo.yaml",
            "--run-id",
            run_id,
            "--runs-dir",
            str(runs_dir),
        ],
    )
    run_step(
        "Build evidence workspace",
        [
            py,
            "-m",
            "metriplane.cli",
            "atlas",
            "run",
            "--session-jsonl",
            "datasets/demo/atlas/assembly_cell_missing_tool.jsonl",
            "--pack",
            "configs/domain_packs/assembly_cell",
            "--out",
            str(EVIDENCE_RUN.relative_to(ROOT)),
            "--run-id",
            run_id,
        ],
    )
    run_step(
        "Export simulation replay",
        [
            py,
            "-m",
            "integrations.omniverse.metriplane_usd_replay",
            "--run-dir",
            str(INCIDENT_DIR.relative_to(ROOT)),
            "--out",
            "web/dashboard/atlas_run/omniverse/metriplane_replay.usda",
        ],
    )

    print("\nDemo replay ready.")
    print("Open Live View: web/dashboard/runtime.html")
    print("Open Cell Report: web/dashboard/report.html")
    print("Open Evidence: web/dashboard/atlas.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
