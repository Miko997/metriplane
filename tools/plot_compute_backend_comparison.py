#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import matplotlib

matplotlib.use("Agg")  # headless-safe
import matplotlib.pyplot as plt


def _require_cols(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"missing required columns: {missing}\ncolumns={list(df.columns)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot CPU vs GPU compute backend comparison CSV.")
    ap.add_argument(
        "--in-csv",
        type=Path,
        default=Path("compute_backend_comparison.csv"),
        help="Path to compute_backend_comparison.csv (default: ./compute_backend_comparison.csv)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Output directory for figures (default: .)",
    )
    ap.add_argument(
        "--prefix",
        type=str,
        default="compute_backend_comparison",
        help="Output filename prefix",
    )
    args = ap.parse_args()

    if not args.in_csv.exists():
        raise SystemExit(
            f"CSV not found: {args.in_csv}\n\n"
            "Tip: pass the full path, e.g.\n"
            '  python tools/plot_compute_backend_comparison.py --in-csv "$RUN_DIR/compute_backend_comparison.csv" --out-dir "$RUN_DIR"\n'
            "or:\n"
            '  cd "$RUN_DIR" && python /path/to/tools/plot_compute_backend_comparison.py\n'
        )

    df = pd.read_csv(args.in_csv)
    _require_cols(df, ["backend", "n_objects", "p50_ms", "p95_ms", "throughput_hz"])

    # Normalize backend labels if you have backend_name too; prefer backend_name when present.
    if "backend_name" in df.columns:
        label_col = "backend_name"
    else:
        label_col = "backend"

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --- Latency plot (p50/p95) ---
    fig1 = plt.figure()
    for label, g in df.sort_values("n_objects").groupby(label_col):
        g2 = g.sort_values("n_objects")
        plt.plot(g2["n_objects"], g2["p50_ms"], marker="o", label=f"{label} p50")
        plt.plot(g2["n_objects"], g2["p95_ms"], marker="x", linestyle="--", label=f"{label} p95")

    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("n_objects")
    plt.ylabel("latency (ms)")
    plt.title("Fusion compute latency (p50/p95)")
    plt.grid(True, which="both", linestyle=":", linewidth=0.5)
    plt.legend()
    out1 = args.out_dir / f"{args.prefix}_latency.png"
    fig1.savefig(out1, dpi=160, bbox_inches="tight")
    plt.close(fig1)

    # --- Throughput plot ---
    fig2 = plt.figure()
    for label, g in df.sort_values("n_objects").groupby(label_col):
        g2 = g.sort_values("n_objects")
        plt.plot(g2["n_objects"], g2["throughput_hz"], marker="o", label=str(label))

    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("n_objects")
    plt.ylabel("throughput (Hz)")
    plt.title("Fusion compute throughput")
    plt.grid(True, which="both", linestyle=":", linewidth=0.5)
    plt.legend()
    out2 = args.out_dir / f"{args.prefix}_throughput.png"
    fig2.savefig(out2, dpi=160, bbox_inches="tight")
    plt.close(fig2)

    # Print a quick numeric summary too (useful for logs / evidence docs)
    pivot = df.pivot_table(index="n_objects", columns=label_col, values="p50_ms", aggfunc="first")
    print("Wrote:")
    print(" ", out1)
    print(" ", out2)
    print("\nP50 table (ms):")
    print(pivot.to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
