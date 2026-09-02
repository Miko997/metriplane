<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Evidence Matrix

**Reduced Truth Recovery core software release**: `v0.4.0` (no DOI; not a new measurement boundary)
**Prior usability and adoption software release**: `v0.3.0` (no DOI; not a new measurement boundary)
**Published packaging predecessor**: `v0.2.1`
**Frozen DOI research artifact**: [`10.5281/zenodo.20736619`](https://doi.org/10.5281/zenodo.20736619)
**Archived release name**: MetriPlane v0.2.0 — Physical Observability, Evidence Bundles, and Command Center
**Main SoftwareX paper artifact**: `v0.2.0`
**Historical benchmark evidence release**: [`v0.1.3`](https://github.com/Miko997/metriplane/releases/tag/v0.1.3)
**Historical DOI-archived baseline**: [`v0.1.4`](https://doi.org/10.5281/zenodo.20631037)
**Prior canonical evidence release**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)
**Tests**: 580/580 passing in the captured v0.2.0 release-gate run (`evidence/paper_v2_0/test_output.txt`).

Key: YES = primary artifact supports the claim; PARTIAL = implementation/evidence exists but should not be promoted into a primary Paper B quantitative claim.

## Technical Benchmark Evidence

| Claim | Required evidence | Found? | Actual artifact path(s) | Quality assessment | Regenerate command |
|---|---|---|---|---|---|
| Deterministic replay | CSV with zero positional diff and zero event mismatches | YES | `evidence/experiments/replay_determinism.csv` | 302 frames; 906 object pairs; 0.0 cm mean/max diff; 0 mismatches; pass=true | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh deterministic-replay` |
| Backpressure | CSV with drop counts, queue depth, and latency | YES | `evidence/experiments/backpressure_summary.csv`, `evidence/experiments/backpressure_001.csv` | 30.0 s at 120 Hz; queue_max=5; 995 published; 2,605 dropped; p95 latency 69.830 ms; pass=true | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh backpressure` |
| Timing breakdown | Per-stage latency CSV | YES | `evidence/experiments/latency_summary.csv` | 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh timing-breakdown` |
| Mapping error | Marker position error vs ground truth grid | YES | `evidence/experiments/mapping_error_001.csv` | Mean 0.63 cm; max 1.07 cm; N=9 points | `python benchmarks/run_mapping_error.py --help` |
| Static fiducial continuity | Per-object coverage and gap CSV | YES | `evidence/experiments/id_stability_001.csv` | IDs 4, 7, and 12 each have 100.0% coverage over 4,387 frames with 0 gaps | `python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_001.csv` |
| Motion fiducial continuity | Per-object coverage and gap CSV under movement | YES | `evidence/experiments/id_stability_movement_001.csv` | IDs 4, 7, and 12 have 98.39-99.25% coverage over 88,475 frames; max gap 533 frames | `python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_movement_001.csv` |
| Fusion jitter | Per-object jitter std and coverage CSV | YES | `evidence/experiments/fusion_jitter_001.csv` | 0.067-0.080 mm jitter std; 100.0% coverage; `max_error_m=NaN`, so no absolute fused accuracy claim | `python benchmarks/run_fusion_jitter.py <session.jsonl> --out evidence/experiments/fusion_jitter_001.csv` |
| CPU/GPU equivalence | CPU/GPU comparison CSV with samples and zero diff | YES | `evidence/experiments/compute_equivalence_001.csv` | 13,161 samples; 0.0 cm RMSE diff; 0.0 cm max diff; `cpu_numpy` vs `gpu_cupy` | `python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu` |
| CPU/GPU fusion performance | Benchmark CSV with CPU and GPU timing rows | YES | `evidence/experiments/gpu_benchmark_001.csv` | Real `gpu_cupy` timing rows exist; GPU is slower than CPU for tested N=1-1000 fusion-compute workloads | `./tools/mp.sh gpu-benchmark` |
| Health degradation | Numeric degradation scenario artifact | PARTIAL | `evidence/experiments/health_degrade_cam1_meta.json` | Meta evidence only; not a primary Paper B quantitative claim | `METRIPLANE_EVIDENCE_OUT=1 ./tools/mp.sh health-degrade-cam1` |

## Product And Reproducibility Evidence

| Claim | Required evidence | Found? | Actual artifact path(s) | Quality assessment |
|---|---|---|---|---|
| Docker quickstart proof | Executed proof with health and WebSocket message flow | YES | `evidence/experiments/docker_demo_proof_001.md`, `evidence/paper_v2_0/logs/17_docker_health.json` | Historical local demo startup, health, and WebSocket message flow validated. The v0.2.0 paper package also captures Docker local replay/demo smoke: build/start, health endpoint JSON, and cleanup. Smoke evidence only; not benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence. |
| Operator UI proof | Step-by-step validated run | YES | `evidence/experiments/operator_ui_final_smoke_001.md` | 10-step workflow passed; smoke evidence, not tracking-accuracy benchmark evidence. |
| Manifest and checksums | Manifest rows and aggregate checksum file | YES | `evidence/manifest.csv`, `evidence/CHECKSUMS.sha256` | Checksum verification is expected to pass with `sha256sum -c evidence/CHECKSUMS.sha256`. |
| Large session provenance | Session hash in manifest when JSONL is outside Git | PARTIAL | `evidence/manifest.csv` | Large JSONL sessions may be archived outside Git; verify archived copies against manifest checksums. |
| Historical benchmark evidence release | Benchmark source/evidence release URL | YES | `https://github.com/Miko997/metriplane/releases/tag/v0.1.3` | v0.1.3 remains the historical benchmark evidence release; v0.2.0 is the frozen DOI-archived SoftwareX paper artifact. Benchmark evidence is supplemental release evidence, not a peer-reviewed publication claim. |

## MetriPlane 0.2.0 Operational Evidence

| Claim | Required evidence | Found? | Actual artifact path(s) | Quality assessment |
|---|---|---|---|---|
| Named physical objects | Object registry config, tests, and proof | YES | `configs/objects.example.yaml`, `tests/test_object_registry.py`, `evidence/experiments/object_registry_001.md` | Marker IDs can resolve to object IDs, types, labels, and tags while preserving unknown-ID fallback. |
| Trace summaries | Trace store tests and proof | YES | `tests/test_trace_store.py`, `evidence/experiments/trace_store_001.md` | Distance, speed, zones, point count, and gaps are derived from replay state. |
| Spatial contracts | Contract model/engine/CLI tests and proof | YES | `tests/test_contract_*.py`, `evidence/experiments/spatial_contract_language_001.md` | Contract validation and replay testing cover core rule types. |
| Sentinel observe-only runtime | Runtime tests and summary evidence | YES | `tests/test_sentinel_*.py`, `evidence/experiments/sentinel_runtime_001.md` | `control_enabled=false`; replay-only auditor path writes status and summary artifacts. |
| Incidents and bundles | Incident/evidence tests and checked-in bundle | YES | `tests/test_incident_engine.py`, `tests/test_evidence_bundles.py`, `evidence/incidents/INC-0001/` | Incidents are grouped and packaged with checksums/reports for replay review. |
| Physical regression | Regression runner tests and proof | YES | `tests/test_physical_regression_runner.py`, `evidence/experiments/physical_regression_tests_001.md` | Bundle expectations can be replayed with pass/fail reports. |
| Forecasting | Forecast tests and proof | YES | `tests/test_forecasting_*.py`, `evidence/experiments/risk_forecasting_001.md` | Short-horizon risk projections are downstream and non-mutating. |
| Counterfactuals | Counterfactual tests and proof | YES | `tests/test_counterfactual_*.py`, `evidence/experiments/counterfactual_reports_001.md` | Threshold, speed, and object-removal variants are reported separately from originals. |
| Camera trust | Analyzer/model/recommendation tests and proof | YES | `tests/test_camera_trust_*.py`, `evidence/experiments/camera_trust_001.md` | Dropout and disagreement metrics are summarized with placement recommendations. |
| Local operator assistant | Retrieval/intent/citation tests and proof | YES | `tests/test_assistant_*.py`, `evidence/experiments/operator_assistant_001.md` | Answers are local and cite checked-in incident/trace/trust artifacts. |
| Command Center | API/endpoint tests and UI proof | YES | `tests/test_operator_command_center_*.py`, `evidence/experiments/command_center_ui_001.md` | Read-only browser/API path exposes state, incidents, traces, trust, and assistant answers. |

## Case Study Evidence

| Claim | Required evidence | Found? | Actual artifact path(s) | Quality assessment |
|---|---|---|---|---|
| Zone dwell by zone | Aggregated zone dwell CSV | YES | `evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv` | Four zones: `bl`, `br`, `tl`, `tr`; total dwell 877.85 object-seconds. |
| Zone transitions | Transition count CSV | YES | `evidence/experiments/case_study_1_movement_zone_transitions.csv` | Sum of transition counts is 112. |
| Zone events | Enter/exit event CSV | YES | `evidence/experiments/case_study_1_movement_zone_events.csv` | Applied analytics event stream. |
| Session recording | Large JSONL or archived checksum | PARTIAL | `evidence/manifest.csv` | Raw session is large and may be outside Git; checksum records anchor provenance. |

## Integration Boundaries

| Integration claim | Evidence position |
|---|---|
| WebSocket/JSONL stream | Primary measured output boundary. |
| Omniverse | External/experimental demonstration unless separately measured. |
| ROS 2 | External/user-implemented adapter unless separately measured. |
| Full 3D reconstruction | Out of scope. |
| Marker-free recognition | Out of scope. |
| Safety-certified industrial control | Out of scope. |

## Documentation Consistency Checks

| Check | Expected |
|---|---|
| Display name | Use Metriplane in active copy; retain MetriPlane inside frozen historical names where changing it would alter provenance. |
| Package/repo/CLI references | Use `metriplane` where referring to package, repo, or commands. |
| Frozen research release and DOI | Use `v0.2.0` and DOI `10.5281/zenodo.20736619` only for the frozen SoftwareX research artifact; v0.4.0 and v0.3.0 have no DOI and did not produce these results. |
| Historical benchmark and DOI lineage | Use `v0.1.3` as the historical benchmark evidence release, `v0.1.4` / `10.5281/zenodo.20631037` as the historical DOI-archived baseline, `v0.1.2` as the prior canonical evidence release, and `v0.1.0` as the initial public release. |
| GPU claim | CPU faster than GPU for current N=1-1000 fusion-compute benchmark; no full-pipeline GPU acceleration claim. |
| Zone claim | Four zones and 112 transitions from current CSVs. |
| Mapping claim | 0.63 cm mean and 1.07 cm max from `mapping_error_001.csv`. |
