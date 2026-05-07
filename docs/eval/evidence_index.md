# Metriplane — Evidence Index

_Summary of test coverage, benchmark artifacts, known claims, and known limitations._

---

## Test Suite

| Suite | Count | Command |
|-------|-------|---------|
| Unit + integration tests | 193 | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` |
| CI (automated on push) | ✅ | `.github/workflows/ci.yml` → ubuntu-latest |

---

## Benchmark Artifacts

| ID | Feature | Artifact | Status | Key Result |
|----|---------|----------|--------|------------|
| `m9_1_deterministic_replay` | Deterministic replay | `evidence/experiments/replay_determinism.csv` | ✅ | 301 frames, max_pos_diff=0.0 cm, 0 mismatches |
| `m9_2_backpressure` | Backpressure | `evidence/experiments/backpressure_summary.csv` | ✅ | 120 Hz, queue_max=5, pass=true |
| `mapping_error_001` | Mapping accuracy | `evidence/experiments/mapping_error_001.csv` | ✅ | mean 0.63 cm, max 1.07 cm, N=9 points |
| `id_continuity_001` | ID stability (static) | `evidence/experiments/id_stability_001.csv` | ✅ | 100% coverage, 0 gaps, 4384 frames |
| `id_stability_movement_001` | ID stability (motion) | `evidence/experiments/id_stability_movement_001.csv` | ✅ | ≥97.4% all 3 objects, 87608 frames |
| `m9_5_timing_breakdown` | Latency profiling | `evidence/experiments/latency_summary.csv` | ✅ | detect p95: cam0=1.50 ms, cam1=1.72 ms; fuse p95=0.19 ms |
| `fps_update_rate` | Frame rate | `docs/eval/fps_summary.md` | ✅ | mean 291 fps, 4384 frames, 15s session |
| `fusion_jitter_001` | Fusion jitter | `evidence/experiments/fusion_jitter_001.csv` | ⚠️ | jitter_std 0.07–0.23 mm; max_error_m=NaN (no ground-truth ref) |
| `gpu_benchmark_001` | CPU vs GPU performance | `evidence/experiments/gpu_benchmark_001.csv` | ✅ | CPU faster at N=1–1000; CPU p50(N=1000)=2.23ms, GPU=2.64ms |
| `compute_equivalence_001` | CPU/GPU output equality | `evidence/experiments/compute_equivalence_001.csv` | ✅ | 4387 frames, rmse_diff=0.0, max_diff=0.0 |
| `m9_4_provenance` | Config provenance | `evidence/experiments/run_meta.json` | ✅ | config_hash, run_id, git_commit all present |
| `health_degrade_cam1` | Health degradation | `evidence/experiments/health_degrade_cam1_meta.json` | ⚠️ | Meta JSON only; no scenario CSV |
| `onboarding_001` | Onboarding | `evidence/onboarding/onboarding_001.md` | ⚠️ | Same-machine warm-cache (see limitations) |
| `operator_ui_smoke_001` | Operator UI | `evidence/experiments/operator_ui_smoke_001.md` | ✅ | 13 steps validated, 1797 frames |
| `case_study_1_movement` | Case study | `docs/case-studies/case-study-1.md` | ✅ | 120 zone events, 880 obj-sec dwell, 77 transitions |

All artifacts listed in `evidence/manifest.csv` with SHA256 checksums.

---

## Current Acceptable Claims

1. **Deterministic replay**: Bit-exact frame-by-frame reproducibility. Fixed-step clock, single authoritative `Clock` instance. Verified by hash comparison across two independent replay runs on 301 frames.

2. **Backpressure**: Bounded queues prevent unbounded memory growth under overload. Drop policy `KEEP_LATEST` measured at 120 Hz synthetic input with 30ms detection latency.

3. **Mapping accuracy**: Planar homography maps markers to world coordinates with mean error 0.63 cm and max 1.07 cm across 9 ground-truth reference points.

4. **ID stability**: Object IDs are stable across sessions. 100% coverage on static scene (4384 frames), ≥97.4% under active motion (87608 frames, 3 tracked objects).

5. **Latency**: Camera detect p95 < 2 ms, fusion p95 < 0.20 ms at tested throughput. Full per-stage breakdown available.

6. **Provenance**: Every run is stamped with git commit hash, config SHA256, run ID, and schema version. Verified in `run_meta.json`.

7. **WebSocket integration**: Frames stream in real-time at `ws://host:8765` with `FrameStateModel` v1.0 schema. Verified in CI and operator UI smoke test.

8. **Operator UI**: 10-step setup wizard (environment → cameras → profile → anchors → calibrate → validate → zones → config → run → export) validated end-to-end.

---

## Known Limitations

| Limitation | Impact | Evidence |
|-----------|--------|----------|
| Onboarding was same-machine, warm pip cache | Installation time on a cold machine will be longer; no clean-machine timing claim | `evidence/onboarding/onboarding_001.md` |
| `fusion_jitter_001.csv`: `max_error_m` is NaN | Absolute fused position accuracy vs ground truth not measured. Only relative jitter (std) is available. | `evidence/experiments/fusion_jitter_001.csv` |
| CPU backend faster than GPU at N=1–1000 | No GPU speedup claimed for typical workloads. GPU available for larger-N or future use. | `evidence/experiments/gpu_benchmark_001.csv` |
| Omniverse/ROS 2 integrations not measured | No live latency claim for external integrations. WebSocket is the measured boundary. | `docs/INTEGRATIONS.md` |
| Large session JSONL files not in git | Sessions > ~50 MB archived externally. SHA256 checksums retained in manifest. | `evidence/manifest.csv` col `artifact_sha256` |
| Health degradation (M9.3) | Meta JSON only; no numeric scenario CSV for cam1 disconnect event. | `evidence/experiments/health_degrade_cam1_meta.json` |
| Docker replay-mode exited immediately | Docker proof uses dummy-mode (camera=dummy); replay-mode exits without session. | `evidence/experiments/docker_demo_proof_001.md` |

---

## Regeneration Commands

| Artifact | Command |
|----------|---------|
| Deterministic replay | `./tools/mp.sh deterministic-replay` |
| Backpressure | `./tools/mp.sh backpressure` |
| Mapping error | `python benchmarks/run_mapping_error.py --help` |
| ID stability | `python tools/analyze_id_stability_jsonl.py <session.jsonl>` |
| Latency breakdown | `./tools/mp.sh timing-breakdown` |
| Fusion jitter | `python benchmarks/run_fusion_jitter.py` |
| GPU benchmark | `./tools/mp.sh gpu-benchmark` |
| CPU/GPU equivalence | `python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu` |
| Provenance run | `./tools/mp.sh provenance` |

---

_See [`docs/eval/evidence_matrix.md`](evidence_matrix.md) for full per-claim evidence table._
