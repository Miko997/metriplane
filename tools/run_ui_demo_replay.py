#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build the camera-free MetriPlane demo path used by the localhost UI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from metriplane.paths import resolve_platform_paths

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RUN = ROOT / "web/dashboard/atlas_run"
INCIDENT_DIR = EVIDENCE_RUN / "evidence_bundles/INC-0001"


def run_step(label: str, command: list[str]) -> None:
    print(f"\n== {label} ==")
    print(" ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    py = sys.executable
    runs_dir = resolve_platform_paths().runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)

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
            "metriplane_demo",
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
            "metriplane_demo_replay",
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
