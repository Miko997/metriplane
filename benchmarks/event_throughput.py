#!/usr/bin/env python3
"""Event export throughput benchmark.

Generates synthetic events and measures events/sec to JSONL and to an in-memory mock
exporter (and Parquet if an engine is installed).

Example:
    python benchmarks/event_throughput.py --n-events 100000 \\
        --out evidence/experiments/scalable_event_pipeline_001.csv
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path


def _gen_events(n: int):
    for i in range(n):
        yield {
            "event_type": "alert",
            "ts": float(i) * 0.033,
            "rule_id": "no_cart_in_exit_lane" if i % 2 else "cart_person_distance",
            "object_ids": [f"obj_{i % 7}"],
            "severity": "warning" if i % 3 else "critical",
        }


def _bench_backend(name: str, exporter, events: list[dict]) -> dict:
    samples = []
    t0 = time.perf_counter()
    for e in events:
        s = time.perf_counter()
        exporter.publish_event(e)
        samples.append((time.perf_counter() - s) * 1000.0)
    dur = time.perf_counter() - t0
    exporter.close()
    samples.sort()

    def pct(q):
        idx = max(0, min(len(samples) - 1, int(round(q * (len(samples) - 1)))))
        return samples[idx]

    return {
        "backend": name,
        "n_events": len(events),
        "duration_s": round(dur, 4),
        "events_per_s": round(len(events) / dur, 1) if dur > 0 else 0.0,
        "p50_publish_ms": round(pct(0.50), 6),
        "p95_publish_ms": round(pct(0.95), 6),
    }


def run(n_events: int, tmp_dir: Path) -> list[dict]:
    from metriplane.exporters.base import JsonlExporter, MockExporter

    events = list(_gen_events(n_events))
    rows = [
        _bench_backend("mock", MockExporter(), events),
        _bench_backend("jsonl", JsonlExporter(tmp_dir / "jsonl"), events),
    ]
    try:
        from metriplane.exporters.parquet import parquet_available
        ok, engine = parquet_available()
        if ok:
            rows.append({"backend": f"parquet({engine})", "n_events": n_events,
                         "duration_s": None, "events_per_s": None,
                         "p50_publish_ms": None, "p95_publish_ms": None,
                         "note": "batch export; see metriplane.exporters.parquet"})
    except Exception:
        pass
    return rows


def main(argv: list[str] | None = None) -> int:
    import tempfile
    p = argparse.ArgumentParser("event_throughput")
    p.add_argument("--n-events", type=int, default=100000)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    with tempfile.TemporaryDirectory() as td:
        rows = run(args.n_events, Path(td))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["backend", "n_events", "duration_s", "events_per_s",
                  "p50_publish_ms", "p95_publish_ms"]
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {args.out}")
    for r in rows:
        print(f"{r['backend']}: {r.get('events_per_s')} events/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
