<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# GPU Scaling Benchmark

An honest CPU vs GPU scaling study for Metriplane's fusion compute block. It answers: for
which object count does the GPU break even, how much is host-device transfer overhead, and
does GPU output match CPU within tolerance.

## Run it

```bash
# CPU only (always works, no CUDA needed)
python benchmarks/gpu_fusion_scaling.py --backend cpu --out /tmp/cpu.csv

# CPU + GPU if CuPy/CUDA is available
python benchmarks/gpu_fusion_scaling.py --backend both \
  --n-objects 1 10 100 1000 10000 100000 --obs-per-object 2 4 \
  --iters 30 --warmup 10 \
  --out evidence/experiments/gpu_fusion_scaling_001.csv \
  --report evidence/experiments/gpu_fusion_scaling_001.md
```

If no GPU is present, the benchmark prints the reason and runs CPU only (exit nonzero only
with `--require-gpu`).

## What it measures

Per (backend, n_objects, obs_per_object, method):

- p50 / p95 / p99 / mean / min / max latency per `fuse_xy` call
- throughput (observations per second)
- `output_rmse_vs_cpu` and `max_abs_diff` (GPU vs CPU equivalence)

GPU timing wraps `synchronize()` on both sides of the call, so **host-device transfer is
included** — this is intentional and honest.

## Batch replay

```bash
python benchmarks/gpu_batch_replay.py --session <session.jsonl> \
  --batch-sizes 1 8 32 --backend cpu --out /tmp/batch.csv
```

## Honesty note

For the current vectorized NumPy bincount aggregation, the CPU wins at small and medium
object counts because transfer overhead dominates the cheap math. On the reference host the
GPU only reaches break-even around **n_objects = 100,000**. Do not claim a GPU speedup for
small workloads — the benchmark reports the actual crossover from data, and equivalence
(RMSE vs CPU) is verified at every size.

## Limitations

- Synthetic observations; real workloads differ.
- Single-process, single-stream measurement.
- Break-even depends heavily on hardware (CPU model, GPU model, PCIe bandwidth).
