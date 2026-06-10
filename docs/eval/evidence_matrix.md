# MetriPlane Evidence Matrix

**Paper B canonical release tag**: [`v0.1.3`](https://github.com/Miko997/metriplane/releases/tag/v0.1.3)
**Release name**: MetriPlane v0.1.3 — Paper B Provenance-Synchronized Evidence Release
**Prior canonical evidence release**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)
**Tests**: 193/193 passing as of initial public release evidence.

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
| Docker quickstart proof | Executed proof with health and WebSocket message flow | YES | `evidence/experiments/docker_demo_proof_001.md` | Dummy-mode startup, health, and WebSocket message flow validated. Replay-mode behavior is not used as a benchmark claim. |
| Operator UI proof | Step-by-step validated run | YES | `evidence/experiments/operator_ui_final_smoke_001.md` | 10-step workflow passed; smoke evidence, not tracking-accuracy benchmark evidence. |
| Manifest and checksums | Manifest rows and aggregate checksum file | YES | `evidence/manifest.csv`, `evidence/CHECKSUMS.sha256` | Checksum verification is expected to pass with `sha256sum -c evidence/CHECKSUMS.sha256`. |
| Large session provenance | Session hash in manifest when JSONL is outside Git | PARTIAL | `evidence/manifest.csv` | Large JSONL sessions may be archived outside Git; verify archived copies against manifest checksums. |
| Paper B canonical release tag | Paper B source/evidence release URL | YES | `https://github.com/Miko997/metriplane/releases/tag/v0.1.3` | Canonical source/evidence release for Paper B; `v0.1.2` was the prior canonical evidence release; `v0.1.0` was the initial public release. |

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
| Display name | Use MetriPlane. |
| Package/repo/CLI references | Use `metriplane` where referring to package, repo, or commands. |
| Paper B canonical release | Use `v0.1.3` and <https://github.com/Miko997/metriplane/releases/tag/v0.1.3>; mention `v0.1.2` as the prior canonical evidence release and `v0.1.0` as the initial public release. |
| GPU claim | CPU faster than GPU for current N=1-1000 fusion-compute benchmark; no full-pipeline GPU acceleration claim. |
| Zone claim | Four zones and 112 transitions from current CSVs. |
| Mapping claim | 0.63 cm mean and 1.07 cm max from `mapping_error_001.csv`. |
