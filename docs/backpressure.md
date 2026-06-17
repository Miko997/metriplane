<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# M9.2 — Bounded queues + backpressure (Systems Demo 2)

## What this adds

This milestone introduces **explicitly bounded stage queues** and a **threaded pipeline runtime** that can
survive overload without memory growth or runaway latency.

Core components:

- `metriplane/pipeline/bounded_queue.py`
  - A small bounded queue with explicit policy:
    - `KEEP_ALL`: bounded buffering + **producer blocks** when full (pure backpressure, no drops).
    - `DROP_OLDEST`: bounded buffering + drop the oldest buffered item when full.
    - `KEEP_LATEST`: bounded buffering + **drain** the buffer and keep only the newest item.
- `metriplane/pipeline/runtime_threaded.py`
  - A simple stage worker model:
    - each stage runs in its own thread
    - consumes from a bounded input queue
    - emits to the next bounded queue
    - instruments per-stage processing time
    - updates Prometheus-style metrics via `MetricsRegistry`

## Why this prevents pipeline collapse

When a downstream stage slows down (e.g., expensive detection), an unbounded queue causes:

- memory growth
- increasing end-to-end latency (older frames stuck behind backlog)
- eventual crash / OS OOM / watchdog kill

A bounded queue prevents collapse by making overload behavior **explicit and bounded**:

- **`KEEP_ALL`**: memory is bounded, and backpressure propagates upstream by blocking producers.
- **`DROP_OLDEST`**: memory is bounded, and the system keeps up with the newest work by discarding stale items.
- **`KEEP_LATEST`**: memory + latency are bounded; the pipeline always works on the newest sample.

## Metrics

`metriplane/metrics.py` now exports additional Prometheus metrics:

- `metriplane_queue_depth{queue="..."}` (gauge)
- `metriplane_queue_dropped_total{queue="...",policy="..."}` (counter)
- `metriplane_stage_latency_ms_last{stage="..."}` (gauge)
- `metriplane_stage_latency_ms_ema{stage="..."}` (gauge)

## Backpressure benchmark

The benchmark intentionally overloads the pipeline:

- **input** produces frames at a fixed rate (`--input-hz`)
- a simulated **detect** stage sleeps (`--detect-ms`) to emulate expensive processing
- the pipeline uses a bounded input queue (`--queue-max` + `--policy`)

Run:

```bash
python benchmarks/run_backpressure.py \
  --duration-s 10 \
  --input-hz 60 \
  --detect-ms 60 \
  --queue-max 8 \
  --policy keep_latest \
  --out evidence/experiments/backpressure_001.csv
```

Outputs:

- `evidence/experiments/backpressure_001.csv` (summary)
- `evidence/experiments/backpressure_001_timeseries.csv` (time series)

Expected results under overload:

- `max_queue_depth <= queue_max`
- `drops_total` increases (for `keep_latest` / `drop_oldest`)
- threads remain alive and benchmark completes

## Systems Demo 2 — suggested shot list

See `evidence/demos/metriplane_systems_demo_2.md`.
