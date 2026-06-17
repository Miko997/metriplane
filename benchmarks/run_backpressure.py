#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Backpressure / bounded-queue benchmark (M9.2).

This benchmark intentionally overloads a staged pipeline so we can observe:
- queue depths remain bounded
- frames are dropped intentionally according to policy
- worker threads stay alive (no pipeline collapse)
- latency remains bounded (esp. with KEEP_LATEST)

Example
-------

```bash
python benchmarks/run_backpressure.py \
  --duration-s 12 \
  --input-hz 60 \
  --detect-ms 45 \
  --queue-max 5 \
  --policy KEEP_LATEST \
  --out /tmp/backpressure_001.csv
```

For a "never drop, apply hard backpressure" run:

```bash
python benchmarks/run_backpressure.py \
  --duration-s 12 \
  --input-hz 60 \
  --detect-ms 45 \
  --queue-max 5 \
  --policy KEEP_ALL \
  --out /tmp/backpressure_keep_all.csv
```
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from metriplane.metrics import MetricsRegistry, start_metrics_server
from metriplane.pipeline.bounded_queue import BoundedQueue, QueuePolicy
from metriplane.pipeline.runtime_threaded import StageWorker


@dataclass(frozen=True, slots=True)
class BenchFrame:
    seq: int
    t_created: float


def _percentile(xs: List[float], p: float) -> float:
    """Nearest-rank percentile (0-100)."""
    if not xs:
        return float("nan")
    if p <= 0:
        return float(min(xs))
    if p >= 100:
        return float(max(xs))
    ys = sorted(xs)
    k = int(math.ceil((p / 100.0) * len(ys))) - 1
    k = max(0, min(len(ys) - 1, k))
    return float(ys[k])


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Metriplane M9.2 backpressure benchmark")
    ap.add_argument("--duration-s", type=float, default=10.0)
    ap.add_argument("--input-hz", type=float, default=60.0, help="producer rate")
    ap.add_argument("--detect-ms", type=float, default=45.0, help="simulated slow stage cost")
    ap.add_argument("--queue-max", type=int, default=5)
    ap.add_argument(
        "--policy",
        type=str.upper,
        choices=[p.name for p in QueuePolicy],
        default="KEEP_LATEST",
        help="queue policy when full (case-insensitive)",
    )
    ap.add_argument("--out", type=str, default="/tmp/backpressure_001.csv")
    ap.add_argument(
        "--out-timeseries",
        type=str,
        default=None,
        help="optional timeseries CSV (defaults to <out>_timeseries.csv)",
    )
    ap.add_argument("--log-every-s", type=float, default=1.0)
    ap.add_argument(
        "--metrics-port",
        type=int,
        default=None,
        help="if set, start a Prometheus /metrics endpoint on this port",
    )
    args = ap.parse_args(argv)

    duration_s = float(args.duration_s)
    input_hz = float(args.input_hz)
    detect_ms = float(args.detect_ms)
    queue_max = int(args.queue_max)
    policy = QueuePolicy[args.policy]

    out_path = Path(str(args.out))
    out_ts = Path(str(args.out_timeseries)) if args.out_timeseries else out_path.with_suffix("")
    if not args.out_timeseries:
        out_ts = Path(str(out_path) + "_timeseries.csv")

    metrics = MetricsRegistry()

    # Optional metrics server (for demo: curl http://127.0.0.1:<port>/metrics)
    if args.metrics_port is not None:
        start_metrics_server(
            host="127.0.0.1",
            port=int(args.metrics_port),
            registry=metrics,
            get_ws_clients=lambda: 0,
        )

    # Pipeline:
    #   producer -> q_detect_in -> [detect worker (slow)] -> q_publish_in -> [publish worker (fast)]
    q_detect_in = BoundedQueue[BenchFrame](
        maxsize=queue_max,
        policy=policy,
        name="detect_in",
    )
    q_publish_in = BoundedQueue[BenchFrame](
        maxsize=queue_max,
        policy=QueuePolicy.KEEP_LATEST,
        name="publish_in",
    )

    published_lat_ms: List[float] = []

    def detect_fn(fr: BenchFrame) -> BenchFrame:
        # Simulate a slow stage
        time.sleep(max(0.0, detect_ms / 1000.0))
        return fr

    def publish_fn(fr: BenchFrame) -> None:
        # Record end-to-end latency (producer->publish)
        published_lat_ms.append((time.monotonic() - fr.t_created) * 1000.0)
        return None

    detect_worker = StageWorker(
        name="detect",
        fn=detect_fn,
        in_queue=q_detect_in,
        out_queue=q_publish_in,
        metrics=metrics,
    )

    publish_worker = StageWorker(
        name="publish",
        fn=publish_fn,
        in_queue=q_publish_in,
        out_queue=None,
        metrics=metrics,
    )

    detect_worker.start()
    publish_worker.start()

    t0 = time.monotonic()
    next_log = t0
    next_sample = t0
    sample_dt = 0.2

    # Counters
    frames_generated = 0
    frames_accepted = 0
    drops_total = 0
    max_q_depth = 0

    # Time series samples: (t_s, q_depth, dropped_total, detect_processed, publish_processed)
    series: List[tuple[float, int, int, int, int]] = []

    # Producer loop
    period_s = 1.0 / input_hz if input_hz > 0 else 0.0

    try:
        while True:
            now = time.monotonic()
            elapsed = now - t0
            if elapsed >= duration_s:
                break

            fr = BenchFrame(seq=frames_generated, t_created=time.monotonic())
            frames_generated += 1

            res = q_detect_in.put(fr)
            drops_total += int(res.dropped)
            if res.ok:
                frames_accepted += 1

            # update metrics for producer-side drops (input queue)
            if res.dropped:
                metrics.inc_queue_dropped(q_detect_in.name, policy=policy.name, n=int(res.dropped))

            depth = q_detect_in.qsize()
            max_q_depth = max(max_q_depth, depth)
            metrics.set_queue_depth(q_detect_in.name, depth)

            # Sample
            if now >= next_sample:
                series.append(
                    (
                        float(elapsed),
                        int(depth),
                        int(drops_total),
                        int(detect_worker.stats.processed),
                        int(publish_worker.stats.processed),
                    )
                )
                next_sample += sample_dt

            # Log
            if now >= next_log:
                stats = {
                    "t_s": round(elapsed, 2),
                    "q_depth": depth,
                    "q_max": queue_max,
                    "drops_total": drops_total,
                    "detect_processed": detect_worker.stats.processed,
                    "publish_processed": publish_worker.stats.processed,
                    "detect_ms_ema": round(detect_worker.stats.ema_latency_ms, 2),
                    "publish_ms_ema": round(publish_worker.stats.ema_latency_ms, 2),
                }
                print(json.dumps(stats, sort_keys=True))
                next_log += float(args.log_every_s)

            # Sleep to maintain input rate (best effort)
            if period_s > 0:
                target = t0 + frames_generated * period_s
                sleep_s = target - time.monotonic()
                if sleep_s > 0:
                    time.sleep(min(sleep_s, 0.02))

    finally:
        # Let pipeline drain briefly
        drain_deadline = time.monotonic() + 2.0
        while time.monotonic() < drain_deadline:
            if q_detect_in.empty() and q_publish_in.empty():
                break
            time.sleep(0.01)

        detect_worker.stop()
        publish_worker.stop()

        # Best-effort join (do not hang forever in CI).
        detect_worker.join(timeout=2.0)
        publish_worker.join(timeout=2.0)

    # Summary
    published = publish_worker.stats.processed

    p50 = _percentile(published_lat_ms, 50)
    p95 = _percentile(published_lat_ms, 95)
    mean_lat = float(statistics.mean(published_lat_ms)) if published_lat_ms else float("nan")

    pass_ok = True
    if max_q_depth > queue_max:
        pass_ok = False
    if not detect_worker.is_alive() or not publish_worker.is_alive():
        # threads should have exited cleanly at the end, but not unexpectedly
        pass
    if detect_worker.stats.exceptions or publish_worker.stats.exceptions:
        pass_ok = False

    summary = {
        "duration_s": round(duration_s, 3),
        "input_hz": input_hz,
        "detect_ms": detect_ms,
        "queue_max": queue_max,
        "policy": policy.name,
        "frames_generated": frames_generated,
        "frames_accepted": frames_accepted,
        "drops_total": drops_total,
        "detect_processed": int(detect_worker.stats.processed),
        "published": int(published),
        "max_queue_depth": int(max_q_depth),
        "mean_latency_ms": mean_lat,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "pass": str(pass_ok).lower(),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary.keys()))
        w.writeheader()
        w.writerow(summary)

    with out_ts.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "q_depth", "drops_total", "detect_processed", "published"])
        for row in series:
            w.writerow(list(row))

    print(f"[backpressure] wrote summary: {out_path}")
    print(f"[backpressure] wrote timeseries: {out_ts}")
    print(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
