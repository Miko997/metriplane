<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# M9.2 — Bounded queues + backpressure (Systems Demo 2)

This document explains **what M9.2 does**, **what the benchmark result proves**, and **how to view backpressure metrics live**.

---

## Goal

Prevent pipeline collapse under load by:

- **Bounding queue depths** (memory stays bounded)
- **Dropping frames intentionally** under overload (instead of unbounded backlog)
- **Exporting metrics** so the behavior is visible and testable

---

## What the benchmark proves (with your run)

You ran:

- `--duration-s 30`
- `--input-hz 120` (generator pushes 120 frames/sec)
- `--detect-ms 30` (detection stage sleeps 30ms ⇒ ~33 frames/sec capacity)
- `--queue-max 5`
- `--policy KEEP_LATEST`

Your summary was:

```json
{
  "duration_s": 30.0,
  "input_hz": 120.0,
  "detect_ms": 30.0,
  "queue_max": 5,
  "policy": "KEEP_LATEST",
  "frames_generated": 3600,
  "frames_accepted": 3600,
  "drops_total": 2605,
  "detect_processed": 995,
  "published": 995,
  "max_queue_depth": 5,
  "mean_latency_ms": 50.891,
  "p50_latency_ms": 50.873,
  "p95_latency_ms": 69.830,
  "pass": "true"
}
```

Interpretation:

- The system is intentionally overloaded: **120 Hz in** vs **~33 Hz detect throughput**.
- Because queues are bounded to **5**, the backlog cannot grow without bound.
- Because the policy is **KEEP_LATEST**, the queue preferentially keeps fresh frames and **drops older frames** when saturated.
- The benchmark reports **`max_queue_depth == 5`**, confirming the bound is respected.
- **`drops_total == 2605`** confirms drop behavior activated under overload.
- The pipeline continues to run for the full duration and exits cleanly with **`pass=true`**.

This directly satisfies the DoD:

- ✅ System remains running under overload
- ✅ Drops are visible and bounded
- ✅ Metrics exist (queue depth + dropped totals + stage latency)

---

## How it works

### 1) BoundedQueue

A `BoundedQueue[T]` wraps a `collections.deque` with a max length and a policy:

- **KEEP_ALL**
  - Blocks the producer when full (classic backpressure).
  - Use when you must not drop frames.

- **DROP_OLDEST**
  - When full, evicts the oldest item and enqueues the new one.
  - Keeps the queue always “recent-ish”, but still allows small buffering.

- **KEEP_LATEST**
  - When full, clears queued items and keeps only the most recent frame.
  - Best when freshness matters more than processing every frame.

The queue updates metrics:

- `metriplane_queue_depth{queue="..."}` gauge
- `metriplane_queue_dropped_total{queue="...",policy="..."}` counter

### 2) Threaded runtime

`metriplane/pipeline/runtime_threaded.py` runs each pipeline stage in its own thread:

- each stage has an **input queue** (bounded)
- each stage records:
  - **processed frames**
  - **per-item latency** (time spent inside the stage function)

Stage latency metrics are exported as:

- `metriplane_stage_latency_ms_last{stage="..."}`
- `metriplane_stage_latency_ms_ema{stage="..."}`

### 3) Benchmark structure

`benchmarks/run_backpressure.py` creates a two-stage pipeline:

- **detect stage:** sleeps `--detect-ms` per frame (simulates slow inference)
- **publish stage:** fast sink

A generator produces frames at `--input-hz` for `--duration-s`.

Because detect is slower than input, **the queue saturates**, and the configured policy determines whether frames block, drop oldest, or keep latest.

---

## Viewing metrics (why your `curl` printed nothing)

You ran `curl` **after** the benchmark finished.

`run_backpressure.py` starts the `/metrics` HTTP server **inside the benchmark process**. When the benchmark exits, that process ends → the metrics server stops → `curl -s` returns nothing (because `-s` hides connection errors).

### Correct way to view metrics

Run the benchmark in **Terminal A**, and curl metrics in **Terminal B while it is still running**.

**Terminal A**

```bash
cd ~/src/metriplane/metriplane-core
source .venv/bin/activate

python benchmarks/run_backpressure.py \
  --duration-s 120 \
  --input-hz 120 \
  --detect-ms 30 \
  --queue-max 5 \
  --policy KEEP_LATEST \
  --out /tmp/backpressure_001.csv \
  --out-timeseries /tmp/backpressure_timeseries_001.csv \
  --metrics-port 8001
```

**Terminal B**

```bash
curl -fsS http://127.0.0.1:8001/metrics | egrep "metriplane_queue_depth|metriplane_queue_dropped_total|metriplane_stage_latency_ms" | head -n 50
```

You should see lines like:

```text
metriplane_queue_depth{queue="detect_in"} 5
metriplane_queue_dropped_total{queue="detect_in",policy="KEEP_LATEST"} 1234
metriplane_stage_latency_ms_ema{stage="detect"} 30.1
```

### One-terminal option (background)

```bash
python benchmarks/run_backpressure.py ... --metrics-port 8001 --duration-s 120 &
PID=$!

# now curl while it runs
curl -fsS http://127.0.0.1:8001/metrics | egrep "metriplane_queue_depth|metriplane_queue_dropped_total|metriplane_stage_latency_ms" | head

wait $PID
```

---

## Evidence artifacts to save

After a “PASS” run:

```bash
mkdir -p evidence/experiments
cp /tmp/backpressure_001.csv evidence/experiments/backpressure_001.csv
cp /tmp/backpressure_timeseries_001.csv evidence/experiments/backpressure_timeseries_001.csv
sha256sum evidence/experiments/backpressure_001.csv \
         evidence/experiments/backpressure_timeseries_001.csv
```

---

## Demo video shot list (Systems Demo 2)

1) Show the benchmark command + parameters
2) Show live `/metrics` output updating while benchmark runs (queue depth + drops)
3) Show final summary JSON with `pass=true`
4) Open the CSV and point out:
   - `max_queue_depth == queue_max`
   - `drops_total > 0`
   - `system stayed alive` (completed full duration)
