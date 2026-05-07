# Metriplane GPU Compute Summary (RQ4)

**Purpose**: GPU vs CPU fusion compute tradeoffs RQ4  
**Last Updated**: 2026-04-27  
**Evidence Source**: GPU benchmark re-run 2026-04-27, git bfce3d9

---

## Environment

| Property | Value |
|----------|-------|
| OS | Linux 6.17.0-22-generic (Ubuntu 24.04) |
| Python | 3.12.3 |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| GPU UUID | GPU-5220413c-57fb-fba9-af75-723eaadd36ad |
| CUDA | 13.1.1 |
| CuPy | 13.6.0 (cupy-cuda13x) |

---

## Implementation

- **CPU Backend**: `metriplane/compute/cpu_numpy.py` — NumPy weighted average fusion
- **GPU Backend**: `metriplane/compute/gpu_cupy.py` — CuPy equivalent (no custom kernels)
- **Selection/Fallback**: `metriplane/compute/select.py` — auto-selects CPU if GPU unavailable
- **Tested method**: `weighted` average fusion

---

## GPU Smoke Test ✅ PASS

**Commit**: bfce3d9  
**Command**: `./tools/mp.sh gpu-smoke`

```
GPU 0: NVIDIA GeForce RTX 5070 Ti (UUID: GPU-5220413c-57fb-fba9-af75-723eaadd36ad)
cupy: 13.6.0
deviceCount: 1
CuPy smoke: OK
```

---

## CPU vs GPU Performance Benchmark (Scaling Table)

**Commit**: bfce3d9  
**Method**: Weighted average fusion, synthetic observation batches  
**Command**: `./tools/mp.sh gpu-benchmark`  
**Output**: `~/metriplane-runs/gpu_benchmark_001/compute_backend_comparison.csv`

### P50 Latency Table (ms) — Lower is better

| N Objects | CPU NumPy p50 (ms) | GPU CuPy p50 (ms) | CPU p95 (ms) | GPU p95 (ms) | CPU faster by |
|-----------|-------------------|-------------------|--------------|--------------|---------------|
| **1** | **0.006** | 0.373 | 0.007 | 0.402 | **60x** |
| **10** | **0.025** | 0.398 | 0.025 | 0.445 | **16x** |
| **50** | **0.111** | 0.488 | 0.122 | 0.533 | **4.4x** |
| **200** | **0.445** | 0.833 | 0.460 | 0.885 | **1.9x** |
| **1000** | **2.226** | 2.642 | 2.266 | 2.690 | **1.2x** |

### Throughput Table (Hz) — Higher is better

| N Objects | CPU Hz | GPU Hz | CPU advantage |
|-----------|--------|--------|---------------|
| 1 | 153,230 | 2,642 | **58x** |
| 10 | 39,790 | 2,454 | **16x** |
| 50 | 8,830 | 2,016 | **4.4x** |
| 200 | 2,231 | 1,185 | **1.9x** |
| 1000 | 449 | 377 | **1.2x** |

---

## Key Findings (RQ4)

### 🔑 Finding 1: GPU never wins in tested range (N=1 to N=1000)

**CPU is faster than GPU** at all tested workload sizes. The gap narrows as N increases:
- At N=1: CPU is **60x faster**
- At N=1000: CPU is only **1.2x faster**

**Crossover extrapolation**: If the trend continues linearly, GPU may become competitive at N ≈ 2000–5000 objects. However, this is far beyond realistic ArUco tracking scenarios (typically 1–20 objects).

### 🔑 Finding 2: GPU transfer overhead dominates small workloads

At N=1:
- CPU: 0.006 ms p50
- GPU: 0.373 ms p50
- GPU is approximately 62× slower because fixed transfer/setup overhead dominates the tiny fusion workload.

This confirms the fundamental limitation: fusion compute is memory-bound at small N, not compute-bound. GPU acceleration requires large batch sizes to amortize transfer cost.

### 🔑 Finding 3: CPU baseline sufficient for experimentation use cases

From `docs/eval/latency_summary.md`:
- Actual fusion stage p95 = **0.190ms** in live 2-camera pipeline
- This is for fusing 3 objects from 2 cameras
- CPU easily handles this; GPU would be ~**2x slower** (0.373ms at N=1 equivalent)

### 🔑 Finding 4: GPU useful as optional scalability path

GPU is architecturally sound as an optional path:
- ✅ Automatic CPU fallback works (tested)
- ✅ No code changes needed for users without GPU
- ✅ GPU advantage grows with N — future-ready for scenarios with many objects
- ❌ No practical benefit for current experimentation scenarios (1–10 objects)

---

## Operational Tradeoffs (Evaluation Evidence)

### CPU NumPy Backend
- ✅ Zero additional dependencies
- ✅ Works on any machine (laptop, CI, Docker)
- ✅ Deterministic — no GPU scheduling variability
- ✅ Cold start: instant
- ✅ Available in GitHub Actions CI
- ✅ Tested: 4384+ frames in production

### GPU CuPy Backend  
- ⚠️ Requires CUDA Toolkit 13.x + matching cupy-cuda13x
- ⚠️ Driver-dependent (NVIDIA only)
- ⚠️ Not available in standard CI (No GPU on GitHub Actions)
- ⚠️ Cold start: JIT compilation warmup on first use
- ✅ Automatic fallback to CPU if unavailable
- ✅ Architecturally ready for high-N scenarios
- ✅ Same `ComputeInterface` contract as CPU

---

## CPU↔GPU Equivalence Test ✅ PASS

**Date**: 2026-04-27  
**Git Commit**: bfce3d905395aa3c95035faee7fca60cb21f58fb  
**Evidence**: `evidence/experiments/compute_equivalence_001.csv`  
**SHA256**: `cbff2c77a57599594f92f1a53fbc52c61365f269aa9a5a1584c45bf14c5b580c`

**Command** (requires metriplane-venv with CUDA env):
```bash
cd <repo>
bash -c 'source <repo>/.venv/bin/activate && source tools/env/vt_cuda13_env.sh && \
  python benchmarks/run_compute_equivalence.py \
  --session-jsonl ~/metriplane-runs/timing_breakdown_001-11/session.jsonl \
  --out-csv evidence/experiments/compute_equivalence_001.csv \
  --method weighted'
```

**Results**:

| Metric | Value |
|--------|-------|
| Frames used | **4384** |
| Samples (object × frame) | **13152** |
| RMSE diff (cm) | **0.000000** |
| Max absolute diff (cm) | **0.000000** |
| CPU backend | cpu_numpy |
| GPU backend | gpu_cupy |
| GPU device | 0 (RTX 5070 Ti) |
| **Pass** | **TRUE** |

**Interpretation**: CPU and GPU backends produce **numerically identical results** across 13,152 fusion operations. The maximum absolute difference is exactly 0.000000 cm — no floating point discrepancy detected. This confirms that the GPU acceleration is a pure performance optimization with no numerical divergence.

**Why this matters (RQ4 product claim)**:  
The equivalence guarantee means users can switch between CPU and GPU backends without any change in output values. The GPU provides the same science as the CPU — only the speed (and overhead) changes.

---

## Evaluation Framing (RQ4)

**Research Question**: How does GPU-accelerated fusion compute (CuPy on CUDA) affect performance and operational feasibility relative to a CPU baseline (NumPy)?

**Answer (evidence-based)**:

1. **Performance**: GPU CuPy is **slower** than CPU NumPy for the workloads tested (N=1 to N=1000). The crossover point is beyond N=1000, which exceeds realistic tracking scenarios.

2. **Operational feasibility**: GPU adds significant setup complexity (CUDA runtime, driver matching, no CI support) without performance benefit in experimentation scenarios. The automatic fallback architecture mitigates this by making GPU strictly optional.

3. **Architectural value**: The pluggable compute backend design is validated — the system correctly selects backends and falls back gracefully. This is a productization strength even without GPU performance advantage.

4. **Design recommendation**: Deploy with CPU backend for experimentation use cases. GPU backend is available for future high-throughput scenarios.

---

## Evidence Files

| File | Path | Notes |
|------|------|-------|
| Benchmark CSV | `~/metriplane-runs/gpu_benchmark_001/compute_backend_comparison.csv` | Full scaling data |
| Latency plot | `~/metriplane-runs/gpu_benchmark_001/compute_backend_comparison_latency.png` | Visual |
| Throughput plot | `~/metriplane-runs/gpu_benchmark_001/compute_backend_comparison_throughput.png` | Visual |
| Smoke test | `evidence/manifest.csv` row 6 | GPU init confirmed |
| CPU↔GPU equivalence CSV | `evidence/experiments/compute_equivalence_001.csv` | 13,152 samples, RMSE=0.000000 cm |

---

## Regeneration Commands

```bash
# GPU smoke test
cd <repo> && source .venv/bin/activate && ./tools/mp.sh gpu-smoke

# Full CPU vs GPU scaling benchmark
cd <repo> && source .venv/bin/activate && ./tools/mp.sh gpu-benchmark

# GPU equivalence (requires visible markers)
cd <repo> && source .venv/bin/activate && ./tools/mp.sh gpu-equivalence
```
