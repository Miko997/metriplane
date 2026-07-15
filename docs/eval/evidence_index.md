<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane Evidence Index

Summary of public evidence artifacts, supported Paper B claims, and known limitations.

**Current software release**: [`v0.2.0`](https://github.com/Miko997/metriplane/releases/tag/v0.2.0)
**Paper B canonical release tag**: [`v0.1.3`](https://github.com/Miko997/metriplane/releases/tag/v0.1.3)
**Release name**: MetriPlane v0.1.3 — Paper B Provenance-Synchronized Evidence Release
**Prior canonical evidence release**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)
**Manifest**: `evidence/manifest.csv`
**Checksums**: `evidence/CHECKSUMS.sha256`

Paper title: **Benchmarking Camera-First Planar Digital Twins: A Reproducible Protocol and MetriPlane Evaluation**.

For Paper B, the authoritative metric table is docs/eval/CANONICAL_EVIDENCE.md in release v0.1.3. Other summaries are non-authoritative convenience summaries.

No benchmark numbers changed from v0.1.2 to v0.1.3. No archival DOI is claimed yet.

## Benchmark Artifacts

| ID | Feature | Artifact | Status | Key result |
|---|---|---|---|---:|
| `replay_determinism` | Deterministic replay | `evidence/experiments/replay_determinism.csv` | PASS | 302 frames; 906 object pairs; max_pos_diff=0.0 cm; 0 mismatches |
| `backpressure_summary` | Backpressure | `evidence/experiments/backpressure_summary.csv` | PASS | 120 Hz; queue_max=5; 995 published; 2,605 dropped; pass=true |
| `latency_summary` | Latency profiling | `evidence/experiments/latency_summary.csv` | PASS | 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms |
| `mapping_error_001` | Mapping accuracy | `evidence/experiments/mapping_error_001.csv` | PASS | 0.63 cm mean; 1.07 cm max; N=9 |
| `id_stability_001` | Static fiducial continuity | `evidence/experiments/id_stability_001.csv` | PASS | IDs 4, 7, and 12: 100.0% coverage over 4,387 frames |
| `id_stability_movement_001` | Motion fiducial continuity | `evidence/experiments/id_stability_movement_001.csv` | PASS | 98.39-99.25% coverage over 88,475 frames |
| `fusion_jitter_001` | Fusion jitter | `evidence/experiments/fusion_jitter_001.csv` | PASS | 0.067-0.080 mm jitter std; absolute fused accuracy not measured |
| `compute_equivalence_001` | CPU/GPU output equality | `evidence/experiments/compute_equivalence_001.csv` | PASS | 13,161 samples; rmse_diff=0.0 cm; max_diff=0.0 cm |
| `gpu_benchmark_001` | Fusion compute performance | `evidence/experiments/gpu_benchmark_001.csv` | PASS | Real `gpu_cupy` rows; GPU slower than CPU for tested N=1-1000 fusion-compute workloads |
| `case_study_1_movement_zone_*` | Zone analytics | `evidence/experiments/case_study_1_movement_zone_*.csv` | PASS | Four zones; 877.85 object-seconds dwell; 112 transitions |
| `docker_demo_proof_001` | Docker proof | `evidence/experiments/docker_demo_proof_001.md` | PASS | Dummy-mode startup, health, and WebSocket message flow |
| `operator_ui_final_smoke_001` | Operator UI smoke | `evidence/experiments/operator_ui_final_smoke_001.md` | PASS | 10-step workflow passed; smoke evidence only |

## Metriplane 0.2.0 Operational Evidence

| ID | Feature | Artifact | Status | Key result |
|---|---|---|---|---|
| `object_registry_001` | Object registry | `evidence/experiments/object_registry_001.md` | PASS | Marker IDs resolve to named physical assets, types, labels, and tags |
| `trace_store_001` | Trace summaries | `evidence/experiments/trace_store_001.md` | PASS | Session observations produce object duration, distance, speed, zone, and gap summaries |
| `event_schema_001` | Operational events | `evidence/experiments/event_schema_001.md` | PASS | Runtime alerts are additive and backward-compatible |
| `spatial_contract_language_001` | Spatial contracts | `evidence/experiments/spatial_contract_language_001.md` | PASS | Contract validation and replay testing cover forbidden zones and proximity rules |
| `sentinel_runtime_001` | Sentinel runtime | `evidence/experiments/sentinel_runtime_001.md` | PASS | Observe-only replay auditor writes run summary and keeps `control_enabled=false` |
| `risk_forecasting_001` | Short-horizon forecasting | `evidence/experiments/risk_forecasting_001.md` | PASS | Future proximity/zone violations are projected without mutating source state |
| `physical_regression_tests_001` | Physical regression | `evidence/experiments/physical_regression_tests_001.md` | PASS | Evidence bundle can be replayed as a regression test |
| `counterfactual_reports_001` | Counterfactuals | `evidence/experiments/counterfactual_reports_001.md` | PASS | Threshold, speed, and object-removal transforms are reported without mutating originals |
| `camera_trust_001` | Camera trust | `evidence/experiments/camera_trust_001.md` | PASS | Dropout/disagreement metrics and recommendations are exported |
| `operator_assistant_001` | Local assistant | `evidence/experiments/operator_assistant_001.md` | PASS | Grounded answers cite local incidents, traces, and trust artifacts |
| `command_center_ui_001` | Command Center | `evidence/experiments/command_center_ui_001.md` | PASS | Read-only API/UI exposes objects, incidents, traces, trust, and local answers |

## Current Acceptable Claims

1. Deterministic replay produced identical compared outputs for 302 frames and 906 object pairs.
2. Backpressure stayed bounded under 120 Hz synthetic overload with `KEEP_LATEST`, queue_max=5, 995 published frames, and 2,605 dropped frames.
3. Planar homography mapping error is 0.63 cm mean and 1.07 cm max over 9 grid points.
4. Static fiducial continuity is 100.0% for IDs 4, 7, and 12 over 4,387 frames.
5. Motion fiducial continuity is 98.39-99.25% for IDs 4, 7, and 12 over 88,475 frames.
6. Latency stage timing shows detect.cam0 p95 1.242 ms, detect.cam1 p95 1.684 ms, and fuse p95 0.184 ms.
7. Fusion jitter is 0.067-0.080 mm std with 100.0% coverage; absolute fused accuracy is not measured by that artifact.
8. CPU/GPU equivalence is exact for the Paper B artifact: 13,161 samples, 0.0 cm RMSE and max difference.
9. GPU fusion compute is correct but slower than CPU for tested N=1-1000 workloads; this does not claim full-pipeline GPU acceleration.
10. Zone analytics report four zones, 877.85 object-seconds dwell, and 112 transitions as applied analytics.
11. Sentinel evaluates spatial contracts in observe-only mode and does not actuate robots or machines.
12. 0.2.0 operational evidence supports replayable incidents, physical regression, camera trust, counterfactual reports, local operator answers, and Command Center review.

## Known Limitations

| Limitation | Impact | Evidence |
|---|---|---|
| Planar XY only | World Z is fixed at `Z=0`; no full 3D scene reconstruction claim | Scope docs and mapping artifacts |
| Fiducial markers required | Continuity is marker-ID continuity, not marker-free recognition | `id_stability_*.csv` |
| Fusion jitter artifact has `max_error_m=NaN` | Jitter/stability only; no absolute fused accuracy claim from this file | `fusion_jitter_001.csv` |
| GPU benchmark is fusion compute only | No GPU claim for camera capture, ArUco detection, mapping, streaming, or full pipeline | `gpu_benchmark_001.csv` |
| Zone analytics are applied analytics | Not a full manually annotated ground-truth zone-detection benchmark | `case_study_1_movement_zone_*.csv` |
| Docker proof uses dummy mode | Replay-mode behavior is not used as a benchmark claim | `docker_demo_proof_001.md` |
| Large JSONL sessions may be outside Git | Verify archived copies with manifest/checksum records | `evidence/manifest.csv` |
| Sentinel is observe-only | It is not a certified safety controller and does not control robots or machines | `docs/sentinel.md`, `evidence/experiments/sentinel_runtime_001.md` |

## Regeneration Commands

| Artifact | Command |
|---|---|
| Deterministic replay | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh deterministic-replay` |
| Backpressure | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh backpressure` |
| Latency breakdown | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh timing-breakdown` |
| Mapping error | `python benchmarks/run_mapping_error.py --help` |
| ID stability | `python tools/analyze_id_stability_jsonl.py <session.jsonl> --out <csv>` |
| Fusion jitter | `python benchmarks/run_fusion_jitter.py <session.jsonl> --out evidence/experiments/fusion_jitter_001.csv` |
| GPU benchmark | `./tools/mp.sh gpu-benchmark` |
| CPU/GPU equivalence | `python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu` |
| Zone analytics | `python tools/zones_report_jsonl.py <session.jsonl> --out evidence/experiments --prefix case_study_1_movement` |

See [`evidence_matrix.md`](evidence_matrix.md) for a per-claim evidence matrix.
