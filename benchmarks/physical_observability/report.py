# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
from pathlib import Path

from benchmarks.physical_observability.scenarios import BenchRow


def write_csv(rows: list[BenchRow], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "task", "metric", "value", "pass", "notes"])
        for r in rows:
            w.writerow(
                [r.scenario, r.task, r.metric, r.value, "PASS" if r.passed else "FAIL", r.notes]
            )


def write_report(rows: list[BenchRow], path: str) -> None:
    scenarios = sorted({r.scenario for r in rows})
    n_pass = sum(1 for r in rows if r.passed)
    lines = [
        "# Metriplane-Bench — Physical Observability",
        "",
        f"Scenarios: {len(scenarios)} | Checks: {len(rows)} | Passed: {n_pass}",
        "",
        "| scenario | task | metric | value | result | notes |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.scenario} | {r.task} | {r.metric} | {r.value} | "
            f"{'PASS' if r.passed else 'FAIL'} | {r.notes} |"
        )
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "python benchmarks/physical_observability/run_bench.py --scenario all \\",
        "  --out evidence/experiments/physical_observability_bench_001.csv \\",
        "  --report evidence/experiments/physical_observability_bench_001.md",
        "```",
        "",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines))


def print_summary(rows: list[BenchRow]) -> None:
    for r in rows:
        print(f"  {'PASS' if r.passed else 'FAIL'} {r.scenario}/{r.task}/{r.metric} = {r.value}")
    n_pass = sum(1 for r in rows if r.passed)
    print(f"Metriplane-Bench: {n_pass}/{len(rows)} checks passed")
