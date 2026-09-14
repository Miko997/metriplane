#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Camera-free timing check used by the localhost Benchmarks page."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.edge_latency import run_edge_latency  # noqa: E402

OUT_DIR = ROOT / "runs/demo-evidence"
OUT_CSV = OUT_DIR / "ui_latency_check.csv"
SESSION = ROOT / "tests/fixtures/contracts/sentinel_minimal_session.jsonl"
RULES = ROOT / "configs/rules.example.yaml"
OBJECTS = ROOT / "configs/objects.example.yaml"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Camera-free MetriPlane latency check ===")
    print("No camera is opened. This measures replay/rule-engine processing timing.")
    print("Live camera pipeline timing requires a valid camera profile in Setup.")
    print(f"session={SESSION.relative_to(ROOT)}")

    result = run_edge_latency(
        str(SESSION),
        duration_s=1.0,
        rules_path=str(RULES),
        objects_path=str(OBJECTS),
    )

    with OUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(result.keys()))
        writer.writeheader()
        writer.writerow(result)

    print("\nTiming summary:")
    for key in ("frames_processed", "elapsed_s", "fps", "p50_ms", "p95_ms", "p99_ms", "mean_ms"):
        print(f"{key}: {result.get(key)}")
    print(f"\nWrote {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
