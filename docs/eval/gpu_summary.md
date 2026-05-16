# MetriPlane GPU Compute Summary

**Purpose**: CPU/GPU fusion-compute evidence for Paper B
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Performance artifact**: `evidence/experiments/gpu_benchmark_001.csv` (2026-04-29, commit `4a899bb`)
**Equivalence artifact**: `evidence/experiments/compute_equivalence_001.csv` (2026-05-13, commit `382be2d`)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

## Scope

The GPU benchmark covers fusion compute only. It does not measure camera capture, ArUco detection, mapping, WebSocket streaming, JSONL recording, or full-pipeline acceleration.

CPU remains the default backend for current workloads. The GPU backend remains optional for larger future batched workloads.

## Environment

| Property | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti |
| CUDA | 13.1.1 |
| CuPy | 13.6.0 (`cupy-cuda13x`) |
| Tested method | `weighted` average fusion |
| CPU backend | `cpu_numpy` |
| GPU backend | `gpu_cupy` |

## GPU Performance Benchmark

| N objects | CPU p50 ms | CPU p95 ms | GPU p50 ms | GPU p95 ms | Relation |
|---:|---:|---:|---:|---:|---|
| 1 | 0.005631 | 0.006708 | 0.322591 | 0.478844 | GPU slower |
| 10 | 0.024406 | 0.026089 | 0.343555 | 0.491760 | GPU slower |
| 50 | 0.109910 | 0.120303 | 0.432770 | 0.564343 | GPU slower |
| 200 | 0.437469 | 0.447466 | 0.773220 | 1.148387 | GPU slower |
| 1000 | 2.225280 | 2.270170 | 2.574817 | 2.728293 | GPU slower |

**Interpretation**: The GPU backend is numerically valid but slower than CPU for the tested N=1-1000 fusion-compute workloads. The measured overhead is consistent with small-to-medium batch sizes where NumPy CPU execution is already sub-millisecond to low-millisecond.

## CPU/GPU Equivalence

| Metric | Value |
|---|---:|
| Frames used | 4,387 |
| Samples | 13,161 |
| RMSE diff | 0.0 cm |
| Max absolute diff | 0.0 cm |
| CPU backend | `cpu_numpy` |
| GPU backend | `gpu_cupy` |
| Pass | true |

The equivalence artifact confirms that `cpu_numpy` and `gpu_cupy` produce identical outputs for the Paper B weighted-fusion session. Do not replace this artifact with later demo-dataset `gpu-equivalence` outputs when citing Paper B.

## Key Findings

1. CPU fusion compute is the right default for current Paper B workloads.
2. GPU execution is correct, but slower than CPU for the tested N=1-1000 fusion-compute batches.
3. The GPU path remains useful as an optional backend for future larger batched workloads.
4. CPU/GPU equivalence is measured separately from performance and is anchored to `compute_equivalence_001.csv`.

## Evidence Files

| File | Path | Notes |
|---|---|---|
| Performance benchmark CSV | `evidence/experiments/gpu_benchmark_001.csv` | CPU and real `gpu_cupy` timing rows for N=1, 10, 50, 200, and 1000 |
| CPU/GPU equivalence CSV | `evidence/experiments/compute_equivalence_001.csv` | 13,161 samples; 0.0 cm RMSE and max difference |
| GPU smoke evidence | `evidence/manifest.csv` | GPU initialization and CuPy environment evidence |

## Regeneration Commands

```bash
./tools/mp.sh gpu-smoke
./tools/mp.sh gpu-benchmark
python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu
```
