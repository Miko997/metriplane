# Metriplane Benchmark Summary

**Purpose**: Consolidated evaluation evidence for RQ3 and RQ4  
**Last Updated**: 2026-04-27  
**Git Commit**: bfce3d905395aa3c95035faee7fca60cb21f58fb (v1.0.0-dirty)

---

## Environment (All Benchmarks)

| Property | Value |
|----------|-------|
| OS | Linux 6.17.0-22-generic (Ubuntu 24.04) |
| Python | 3.12.3 |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| CUDA | cuda-toolkit 13.1.1 |
| CuPy | 13.6.0 (cupy-cuda13x) |
| Cameras | /dev/video0 + /dev/video2 (USB) |
| Calibration Profile | board_55x40_warehouse_story_v1_fusion |

---

## All Executed Benchmarks

| Benchmark | Status | Date | Commit | Key Result | Evidence Path |
|-----------|--------|------|--------|------------|---------------|
| **CI Tests (pytest)** | ✅ PASS | 2026-04-29 | 4a899bb | 193/193 passed (initial-public-release) | — |
| **Doctor / Preflight** | ✅ PASS | 2026-04-27 | bfce3d9 | 8/8 checks passed | — |
| **M9.1 Deterministic Replay** | ✅ PASS | 2026-04-27 | bfce3d9 | 1201 frames, 8405 pairs, 0.0 cm | `evidence/experiments/replay_determinism.csv` |
| **M9.2 Backpressure** | ✅ PASS | 2026-04-27 | bfce3d9 | 2600 drops, stable, PASS | `evidence/experiments/backpressure_summary.csv` |
| **M9.3 Health Monitoring** | ⚠️ PARTIAL | 2026-01-22 | — | Code exists, multi-cam blocked | `evidence/experiments/health_degrade_cam1_meta.json` |
| **M9.4 Provenance** | ✅ PASS | 2026-04-27 | bfce3d9 | config_hash + git_commit stamped | `evidence/experiments/run_meta.json` |
| **M9.5 Latency Breakdown** | ✅ PASS | 2026-04-27 | bfce3d9 | detect p95=1.72ms, fuse=0.19ms | `evidence/experiments/latency_summary.csv` |
| **M9.6 GPU Smoke** | ✅ PASS | 2026-04-27 | bfce3d9 | RTX 5070 Ti, CuPy 13.6.0 | `evidence/manifest.csv` row 6 |
| **M9.6 GPU Benchmark** | ✅ PASS | 2026-04-29 | 4a899bb | CPU faster (all N tested) | `evidence/experiments/gpu_benchmark_001.csv` |
| **M9.6 GPU Equivalence** | ✅ PASS | 2026-04-27 | bfce3d9 | 13152 samples, RMSE=0.000000 | `evidence/experiments/compute_equivalence_001.csv` |
| **Multi-Camera Alignment** | ✅ PASS | 2026-04-27 | 3dfeee5 | mean_dist=0.9mm, max=1.2mm | `evidence/manifest.csv` row 8 |
| **Mapping Error (9-point)** | ✅ PASS | 2026-04-29 | — | mean=0.40cm, max=1.09cm | `evidence/experiments/mapping_error_001.csv` |
| **Fusion Jitter** | ✅ PASS | 2026-04-27 | bfce3d9 | 100% coverage, jitter<0.23mm | `evidence/experiments/fusion_jitter_001.csv` |
| **FPS / Update Rate** | ✅ PASS | 2026-04-27 | bfce3d9 | 291 FPS mean, 282–304 sustained | `docs/eval/fps_summary.md` |
| **ID Continuity (static)** | ✅ PASS | 2026-04-27 | bfce3d9 | 100% coverage, 0 gaps | `evidence/experiments/id_stability_001.csv` |
| **Case Study 1 — Movement** | ✅ PASS | 2026-04-27 | 9ac3366 | 87608 frames, 77 zone transitions | `docs/case-studies/case-study-1.md` |
| **Zone Analytics (movement)** | ✅ PASS | 2026-04-27 | 9ac3366 | dwell~880 obj-s, 77 transitions | `evidence/experiments/case_study_1_movement_zone_*.csv` |
| **ID Continuity (motion)** | ✅ PASS | 2026-04-27 | 9ac3366 | 97.4–99.1% coverage (3 objects) | `evidence/experiments/id_stability_movement_001.csv` |
| **Operator UI End-to-End Smoke Test** | ✅ PASS | 2026-04-28 | ac186ef | 60 s, 1797 frames, 5 CSVs exported | `docs/eval/operator_ui_summary.md` |
| **Operator UI Final Smoke Test** | ✅ PASS | 2026-04-28 | 469d51c | 60 s, 1797 frames, calibration/alignment/config/run/export completed | `docs/eval/operator_ui_final_smoke_summary.md` |

---

## Detailed Results by Category

### 1) Determinism (M9.1)

**Evidence**: `evidence/experiments/replay_determinism.csv`

| Metric | Value |
|--------|-------|
| Frames compared | 1201 (re-run) / 301 (M9.1) |
| Object pairs compared | 8405 (re-run with real markers) |
| Mean position difference | **0.0 cm** |
| Max position difference | **0.0 cm** |
| Event mismatches | **0** |
| Pass | **TRUE** |

**Significance**: Bit-exact replay proven with 8405 object pair comparisons at 0.0 cm.

---

### 2) Backpressure / Graceful Degradation (M9.2)

**Evidence**: `evidence/experiments/backpressure_summary.csv`

| Metric | Value |
|--------|-------|
| Duration | 30.0 s |
| Input rate | 120 FPS (synthetic overload, 4x target) |
| Simulated detection time | 30 ms/frame |
| Queue depth max | 5 |
| Policy | KEEP_LATEST |
| Frames generated | 3600 |
| Frames accepted | 3600 |
| **Frames dropped** | **2600** |
| Detect processed | 1000 |
| Published | 1000 |
| Max queue depth | **5** (saturated as expected) |
| Mean latency | 51.06 ms |
| p50 latency | 51.15 ms |
| p95 latency | 69.80 ms |
| Pass | **TRUE** |

**Significance**: System degrades gracefully under 4x overload. No crash, no memory blowup.

---

### 3) Latency Breakdown (M9.5)

**Evidence**: `evidence/experiments/latency_summary.csv` (re-run 2026-04-27)

| Stage | Mean (ms) | p95 (ms) | Max (ms) |
|-------|-----------|----------|----------|
| detect.cam1 | 1.410 | **1.722** | 2.059 |
| detect.cam0 | 1.183 | **1.498** | 3.203 |
| fuse (Kalman) | 0.159 | **0.190** | 0.280 |
| build.msg | 0.165 | 0.180 | 0.842 |
| record.jsonl | 0.138 | 0.151 | 0.660 |
| map.cam0 | 0.026 | 0.029 | 0.156 |
| map.cam1 | 0.024 | 0.027 | 0.114 |
| zones | 0.022 | 0.025 | 0.115 |
| ws.send | 0.011 | 0.013 | 0.180 |

**Total non-pacing pipeline p95 ≈ 4.0 ms** (4384 frames, 2 cameras, 3 markers)

---

### 4) Mapping Accuracy

**Evidence**: `evidence/experiments/mapping_error_001.csv`

| Metric | Value |
|--------|-------|
| Test points (N) | 9 |
| Mean error | **0.40 cm** |
| Median error | 0.27 cm |
| Max error | **1.09 cm** (point p21) |
| Min error | 0.13 cm |
| Std deviation | 0.30 cm |

**Workspace**: board_110x40 (1.1m × 0.4m), single camera  
**Significance**: Mean < 1 cm, max < 2 cm — suitable for experimentation use cases.

---

### 5) Fusion Jitter & Coverage

**Evidence**: `evidence/experiments/fusion_jitter_001.csv`

| Object ID | Frames Seen | Total Frames | Coverage | Jitter Std (m) |
|-----------|-------------|--------------|----------|----------------|
| 12 | 4384 | 4384 | **100.0%** | 0.000229 m (0.23 mm) |
| 4 | 4384 | 4384 | **100.0%** | 0.000068 m (0.07 mm) |
| 7 | 4384 | 4384 | **100.0%** | 0.000178 m (0.18 mm) |

**Session**: `~/metriplane-runs/timing_breakdown_001-11/session.jsonl` (15.1s, 2-camera)  
**Significance**: 100% tracking coverage with sub-mm jitter for all 3 markers.

---

### 6) Multi-Camera Alignment

**Evidence**: `evidence/manifest.csv` row 8 (2026-04-27)

| Metric | Value |
|--------|-------|
| Marker tested | ArUco ID 7 |
| Raw delta cam0 vs cam1 | **0.0021 m** (2.1 mm) |
| Mean cross-camera distance | **0.0009 m** (0.9 mm) |
| Max cross-camera distance | **0.0012 m** (1.2 mm) |
| Fused sensors | **2** |

---

### 7) GPU Compute Scaling

**Evidence**: `evidence/experiments/gpu_benchmark_001.csv`

| N Objects | CPU p50 (ms) | GPU p50 (ms) | CPU faster by |
|-----------|-------------|-------------|---------------|
| 1 | **0.006** | 0.373 | 60x |
| 10 | **0.025** | 0.398 | 16x |
| 50 | **0.111** | 0.488 | 4.4x |
| 200 | **0.445** | 0.833 | 1.9x |
| 1000 | **2.226** | 2.642 | 1.2x |

**Key finding**: CPU faster than GPU at all tested N. Crossover estimated beyond N=1000.

---

## Missing Evidence

| Benchmark | Reason | Priority | Command |
|-----------|--------|----------|---------|
| M9.3 Health degradation (multi-cam) | `/dev/video1` not capture-capable | LOW | Add 2nd USB camera |
| Case Study 1 screenshot/video | Dashboard not run during movement session | MEDIUM | `./tools/dashboard_runner.sh` during live run |
| Onboarding clean-machine time | Same-machine warm-cache run done (2.1 min, 6 steps); clean-VM pending | MEDIUM | Repeat on fresh Ubuntu VM |
| End-to-end client latency | Omniverse integration external/experimental | LOW | Requires Omniverse extension |

---

## Sufficiency Assessment (RQ3)

| Requirement | Target | Result | Pass? |
|-------------|--------|--------|-------|
| Determinism | 0 diff on replay | 0.0 cm, 0 mismatches | ✅ |
| Backpressure | No crash under overload | Stable 30s, 2600 drops | ✅ |
| Latency p95 | < 10ms total | ~4.0ms (2-cam) | ✅ |
| Mapping error mean | < 1 cm | 0.40 cm | ✅ |
| Mapping error max | < 2 cm | 1.09 cm | ✅ |
| Tracking coverage | > 95% | 100% (3 markers) | ✅ |
| Fusion jitter | < 5 mm std | < 0.23 mm | ✅ |

---

## Regeneration Commands

```bash
cd <repo> && source .venv/bin/activate

# Tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q

# Doctor
python -m metriplane.cli doctor

# All system benchmarks
./tools/mp.sh deterministic-replay
./tools/mp.sh backpressure
./tools/mp.sh provenance
./tools/mp.sh timing-breakdown
./tools/mp.sh gpu-smoke
./tools/mp.sh gpu-benchmark

# Fusion jitter (needs session JSONL)
python benchmarks/run_fusion_jitter.py ~/metriplane-runs/timing_breakdown_001-11/session.jsonl --out evidence/experiments/fusion_jitter_001.csv
```
