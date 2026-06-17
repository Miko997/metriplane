#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Edge latency benchmark.

Replays a session through the rule engine and measures FPS, per-frame latency
(p50/p95/p99), and optional CPU/memory usage (if psutil is installed). Designed to be run
on edge hardware (e.g. Jetson) but works anywhere; no camera required.

Example:
    python benchmarks/edge_latency.py \\
        --session tests/fixtures/contracts/sentinel_minimal_session.jsonl \\
        --duration-s 5 --out evidence/experiments/jetson_edge_latency_001.csv
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path


def run_edge_latency(session_path: str, duration_s: float = 0.0,
                     rules_path: str | None = None,
                     objects_path: str | None = None) -> dict:
    """Replay frames (optionally looping to fill duration_s) and measure latency."""
    from metriplane.sentinel.engine import RuleEngine, iter_frames

    frames = list(iter_frames(session_path))
    if not frames:
        raise SystemExit("no frames in session")

    ruleset = None
    registry = None
    if rules_path:
        from metriplane.sentinel.rules import load_rules
        ruleset = load_rules(rules_path)
    if objects_path:
        from metriplane.sentinel.registry import load_registry
        registry = load_registry(objects_path)

    per_frame_ms: list[float] = []
    n_processed = 0
    t_start = time.perf_counter()
    deadline = t_start + duration_s if duration_s > 0 else None

    while True:
        engine = RuleEngine(ruleset, registry) if ruleset else None
        for frame in frames:
            t0 = time.perf_counter()
            if engine is not None:
                engine.process_frame(frame)
            else:
                _ = frame.objects  # minimal touch
            per_frame_ms.append((time.perf_counter() - t0) * 1000.0)
            n_processed += 1
        if deadline is None or time.perf_counter() >= deadline:
            break

    elapsed = time.perf_counter() - t_start
    ordered = sorted(per_frame_ms)

    def pct(q: float) -> float:
        idx = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]

    result = {
        "frames_processed": n_processed,
        "elapsed_s": round(elapsed, 4),
        "fps": round(n_processed / elapsed, 2) if elapsed > 0 else 0.0,
        "p50_ms": round(pct(0.50), 6),
        "p95_ms": round(pct(0.95), 6),
        "p99_ms": round(pct(0.99), 6),
        "mean_ms": round(sum(per_frame_ms) / len(per_frame_ms), 6),
        "dropped_frames": 0,
        "cpu_percent": None,
        "rss_mb": None,
    }
    try:
        import psutil  # optional
        proc = psutil.Process()
        result["cpu_percent"] = round(proc.cpu_percent(interval=0.1), 2)
        result["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 2)
    except Exception:
        pass
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("edge_latency")
    p.add_argument("--session",
                   default="tests/fixtures/contracts/sentinel_minimal_session.jsonl")
    p.add_argument("--rules", default="configs/rules.example.yaml")
    p.add_argument("--objects", default="configs/objects.example.yaml")
    p.add_argument("--duration-s", type=float, default=0.0)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    result = run_edge_latency(args.session, args.duration_s, args.rules, args.objects)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(result.keys()))
            w.writeheader()
            w.writerow(result)
        print(f"wrote {args.out}")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
