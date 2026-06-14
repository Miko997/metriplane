#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Metriplane-Bench runner.

Evaluates physical-observability scenarios (replay determinism, rule-alert and incident
precision/recall, latency) and emits a CSV + Markdown report.

Example:
    python benchmarks/physical_observability/run_bench.py --scenario all \\
      --out evidence/experiments/physical_observability_bench_001.csv \\
      --report evidence/experiments/physical_observability_bench_001.md
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("metriplane-bench")
    p.add_argument("--scenario", default="all",
                   help="'all' or a specific scenario id")
    p.add_argument("--out", default=None, help="CSV output path")
    p.add_argument("--report", default=None, help="Markdown report path")
    args = p.parse_args(argv)

    from benchmarks.physical_observability.report import (
        print_summary,
        write_csv,
        write_report,
    )
    from benchmarks.physical_observability.scenarios import (
        discover_scenarios,
        run_all,
    )

    if args.scenario == "all":
        names = discover_scenarios()
    else:
        names = [args.scenario]
    if not names:
        print("no scenarios found", file=sys.stderr)
        return 2

    rows = run_all(names)
    print_summary(rows)

    if args.out:
        write_csv(rows, args.out)
        print(f"wrote CSV to {args.out}")
    if args.report:
        write_report(rows, args.report)
        print(f"wrote report to {args.report}")

    failed = [r for r in rows if not r.passed]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
