# GPU Compute Backend (M9.6)

M9.6 introduces an **optional GPU compute backend** for the fusion compute block.

## What is accelerated

The first GPU-accelerated compute block is the **XY fusion reduction** used by the fusion runner when `fusion.method` is:

- `avg` (simple mean)
- `weighted` (RMSE-weighted mean)

This block is implemented in:

- `metriplane/compute/cpu_numpy.py` (CPU, NumPy)
- `metriplane/compute/gpu_cupy.py` (GPU, CuPy)

Both backends implement the same interface from `metriplane/compute/interface.py`.

## Config

Add a `compute` section to your YAML config (requires `Config.compute` to exist in the Config dataclass):

```yaml
compute:
  backend: gpu           # cpu|gpu
  allow_fallback_to_cpu: true
  gpu:
    provider: cupy       # currently only cupy
    device: 0
    warmup_iters: 20
```

Environment overrides supported by `metriplane.compute.select`:

- `METRIPLANE_COMPUTE_BACKEND` (or `METRIPLANE_COMPUTE_BACKEND`): `cpu` or `gpu`
- `METRIPLANE_GPU_DEVICE` (or `METRIPLANE_GPU_DEVICE`): integer device index

## How it is selected

`metriplane.compute.select.select_fusion_backend(...)` chooses:

- GPU backend if requested and CuPy+GPU are available
- otherwise (if `allow_fallback_to_cpu=true`) falls back to NumPy

## Benchmarks

### 1) Equivalence (CPU ↔ GPU)

Compares CPU vs GPU fused XY outputs frame-by-frame from a recorded `session.jsonl`.

```bash
python benchmarks/run_compute_equivalence.py \
  --session-jsonl runs/<run_id>/session.jsonl \
  --method weighted \
  --out-csv runs/<run_id>/compute_equivalence.csv
```

Default tolerances (override via CLI):

- `rmse_diff_cm <= 0.05`
- `max_abs_diff_cm <= 0.20`

### 2) Performance comparison (CPU vs GPU)

Synthetic benchmark that scales number of objects and measures latency p50/p95 + throughput.

```bash
python benchmarks/run_compute_backend_comparison.py \
  --backends cpu,gpu \
  --objects 10,50,200,1000 \
  --cameras 2 \
  --iters 1000 \
  --warmup 100 \
  --out-csv runs/compute_backend_comparison.csv
```

## GPU proof (demo)

During the performance benchmark, keep `nvidia-smi` running in another terminal:

```bash
watch -n 0.5 nvidia-smi
```

This is the required “GPU utilization proof” shot in **GPU Demo 7**.
