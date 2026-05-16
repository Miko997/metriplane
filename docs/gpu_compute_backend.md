# GPU Compute Backend

**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)

MetriPlane includes an optional CuPy backend for fusion compute. CPU remains the default backend for current workloads.

## What Is Accelerated

The GPU backend covers the XY fusion reduction used by `avg` and `weighted` fusion methods. It does not accelerate camera capture, ArUco detection, planar mapping, WebSocket streaming, JSONL recording, or the full pipeline.

Implemented backends:

- `metriplane/compute/cpu_numpy.py` - CPU NumPy backend
- `metriplane/compute/gpu_cupy.py` - GPU CuPy backend
- `metriplane/compute/select.py` - backend selection and fallback

## Configuration

```yaml
compute:
  backend: gpu
  allow_fallback_to_cpu: true
  gpu:
    provider: cupy
    device: 0
    warmup_iters: 20
```

Environment overrides:

- `METRIPLANE_COMPUTE_BACKEND`: `cpu` or `gpu`
- `METRIPLANE_GPU_DEVICE`: integer device index

## Paper B Evidence

| Result | Artifact | Value |
|---|---|---:|
| CPU/GPU equivalence | `evidence/experiments/compute_equivalence_001.csv` | 13,161 samples; 0.0 cm RMSE diff; 0.0 cm max diff |
| CPU/GPU fusion performance | `evidence/experiments/gpu_benchmark_001.csv` | GPU backend slower than CPU for tested N=1-1000 fusion-compute workloads |

## CPU/GPU Performance Table

| N objects | CPU p50 ms | CPU p95 ms | GPU p50 ms | GPU p95 ms | Relation |
|---:|---:|---:|---:|---:|---|
| 1 | 0.005631 | 0.006708 | 0.322591 | 0.478844 | GPU slower |
| 10 | 0.024406 | 0.026089 | 0.343555 | 0.491760 | GPU slower |
| 50 | 0.109910 | 0.120303 | 0.432770 | 0.564343 | GPU slower |
| 200 | 0.437469 | 0.447466 | 0.773220 | 1.148387 | GPU slower |
| 1000 | 2.225280 | 2.270170 | 2.574817 | 2.728293 | GPU slower |

## Reproduction Commands

```bash
./tools/mp.sh gpu-smoke
./tools/mp.sh gpu-benchmark
python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu
```

See [`eval/gpu_summary.md`](eval/gpu_summary.md) and [`eval/CANONICAL_EVIDENCE.md`](eval/CANONICAL_EVIDENCE.md) for the Paper B evaluation framing.
