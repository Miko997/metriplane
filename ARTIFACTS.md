<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane Software Artifact and Benchmark Evidence Supplement

## Artifact identity

MetriPlane v0.2.0 is the current software release candidate. It adds Sentinel,
Command Center, physical regression, and operational evidence layers on top of
the historical camera-to-coordinate benchmark baseline.

- Software release: `v0.2.0`
- Latest archived DOI release: `v0.1.4` at `10.5281/zenodo.20631037`
- Repository: `https://github.com/Miko997/metriplane`
- License: MIT
- Benchmark evidence baseline: preserved from `v0.1.3`
- Benchmark evidence status: supplemental release evidence, not peer-reviewed publication
- Paper status: no peer-reviewed publication is claimed in this artifact file

Historical note: earlier internal planning referred to this evidence as "Paper B". The public artifact should be cited as the MetriPlane software release and benchmark evidence supplement unless a separate peer-reviewed paper is accepted.

The benchmark evidence table is maintained in [`docs/eval/CANONICAL_EVIDENCE.md`](docs/eval/CANONICAL_EVIDENCE.md). The v0.2.0 release preserves the v0.1.3 benchmark evidence values and adds operational evidence for Sentinel, Command Center, evidence bundles, regression tests, camera trust, local operator answers, and the MetriPlane Evidence Review workflow: domain packs, a deterministic assembly-cell replay, physical event ledger, Cell Truth Report, evidence bundle v3, generated regression tests, training cases, improvement actions, and Atlas-Bench core.

## Scope

- Planar XY tracking only; world Z is fixed at `Z=0`.
- ArUco/fiducial IDs are the tracked object identity source.
- Evidence covers one-camera and two-camera evaluation runs.
- The primary integration surface is the WebSocket/JSONL `FrameStateModel` state stream.
- Sentinel is observe-only and does not control robots or machines.
- No marker-free recognition claim is made.
- No full 3D scene reconstruction claim is made.
- No safety-certified industrial control claim is made.
- Atlas is observe-only and asset/process focused. It does not control machines, certify safety, approve quality release, recognize people, or claim marker-free tracking.

## Artifact summary

| Result group | Primary files | Notes |
|---|---|---|
| Latency/update rate | [`latency_summary.csv`](evidence/experiments/latency_summary.csv), [`latency_summary.md`](docs/eval/latency_summary.md) | Current canonical timing rows: 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms; non-pacing pipeline p95 approx. 3.55 ms. |
| Mapping error | [`mapping_error_001.csv`](evidence/experiments/mapping_error_001.csv) | 9-point planar grid; mean 0.63 cm, max 1.07 cm. |
| Static/motion continuity | [`id_stability_001.csv`](evidence/experiments/id_stability_001.csv), [`id_stability_movement_001.csv`](evidence/experiments/id_stability_movement_001.csv), [`stability_summary.md`](docs/eval/stability_summary.md) | Static: 100.0% coverage over 4,387 frames. Motion: 98.39-99.25% coverage over 88,475 frames. Marker continuity, not general re-identification. |
| Replay determinism | [`replay_determinism.csv`](evidence/experiments/replay_determinism.csv), [`manifest.csv`](evidence/manifest.csv) | 302 frames; 906 object pairs; 0.0 cm mean/max positional difference; 0 event mismatches. |
| Backpressure | [`backpressure_summary.csv`](evidence/experiments/backpressure_summary.csv), [`backpressure_001.csv`](evidence/experiments/backpressure_001.csv) | 30.0 s at 120 Hz synthetic input; KEEP_LATEST; 3,600 generated; 995 published; 2,605 dropped; p95 latency 69.830 ms. |
| Fusion jitter | [`fusion_jitter_001.csv`](evidence/experiments/fusion_jitter_001.csv), [`benchmark_summary.md`](docs/eval/benchmark_summary.md) | 0.067-0.080 mm jitter std; 100.0% coverage. Absolute fused accuracy was not measured in this artifact. |
| CPU/GPU equivalence | [`compute_equivalence_001.csv`](evidence/experiments/compute_equivalence_001.csv) | 13,161 samples; CPU/GPU outputs match at 0.0 cm RMSE and max difference. |
| CPU/GPU benchmark | [`gpu_benchmark_001.csv`](evidence/experiments/gpu_benchmark_001.csv), [`gpu_summary.md`](docs/eval/gpu_summary.md) | GPU backend is numerically valid but slower than CPU for tested N=1-1000 fusion-compute workloads. Scope is fusion compute only. |
| Zone analytics | [`case_study_1_movement_zone_dwell.csv`](evidence/experiments/case_study_1_movement_zone_dwell.csv), [`case_study_1_movement_zone_dwell_by_zone.csv`](evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv), [`case_study_1_movement_zone_transitions.csv`](evidence/experiments/case_study_1_movement_zone_transitions.csv), [`case_study_1_movement_zone_events.csv`](evidence/experiments/case_study_1_movement_zone_events.csv) | Four zones (`bl`, `br`, `tl`, `tr`); 877.85 object-seconds dwell; 112 transitions. Applied analytics, not a manually annotated ground-truth zone benchmark. |
| Docker proof | [`docker_demo_proof_001.md`](evidence/experiments/docker_demo_proof_001.md) | Docker dummy-mode proof; replay-mode behavior is not expanded into a benchmark claim. |
| Operator UI smoke | [`operator_ui_final_smoke_001.md`](evidence/experiments/operator_ui_final_smoke_001.md), [`operator_ui_final_smoke_001_zone_events.csv`](evidence/experiments/operator_ui_final_smoke_001_zone_events.csv), [`operator_ui_final_smoke_001_zone_dwell.csv`](evidence/experiments/operator_ui_final_smoke_001_zone_dwell.csv), [`operator_ui_final_smoke_001_zone_transitions.csv`](evidence/experiments/operator_ui_final_smoke_001_zone_transitions.csv) | Workflow smoke evidence, not a tracking-accuracy benchmark. |
| Release fixtures | [`test_release_fixture_integrity.py`](tests/test_release_fixture_integrity.py), [`tests/fixtures`](tests/fixtures/), [`evidence/incidents/INC-0001`](evidence/incidents/INC-0001/), [`evidence/incidents/INC-DIST-001`](evidence/incidents/INC-DIST-001/) | Small deterministic fixtures required by CI and release tests. Raw local runs and large media remain ignored. |
| Object registry / traces / events | [`object_registry_001.md`](evidence/experiments/object_registry_001.md), [`trace_store_001.md`](evidence/experiments/trace_store_001.md), [`event_schema_001.md`](evidence/experiments/event_schema_001.md) | Named objects, trace summaries, and typed operational events. |
| Rules / incidents / evidence bundles | [`rule_engine_001.md`](evidence/experiments/rule_engine_001.md), [`incident_engine_001.md`](evidence/experiments/incident_engine_001.md), [`evidence_bundles_001.md`](evidence/experiments/evidence_bundles_001.md), [`INC-0001`](evidence/incidents/INC-0001/) | Spatial rules, grouped incidents, replay bundle reports, and checksums. |
| Sentinel contracts/runtime/forecasting | [`spatial_contract_language_001.md`](evidence/experiments/spatial_contract_language_001.md), [`sentinel_runtime_001.md`](evidence/experiments/sentinel_runtime_001.md), [`risk_forecasting_001.md`](evidence/experiments/risk_forecasting_001.md) | Observe-only Sentinel run path and short-horizon forecast evidence. |
| Regression/counterfactual/trust/assistant | [`physical_regression_tests_001.md`](evidence/experiments/physical_regression_tests_001.md), [`counterfactual_reports_001.md`](evidence/experiments/counterfactual_reports_001.md), [`camera_trust_001.md`](evidence/experiments/camera_trust_001.md), [`operator_assistant_001.md`](evidence/experiments/operator_assistant_001.md) | Replay regression, threshold/speed/object-removal counterfactuals, camera trust, and local grounded answers. |
| Command Center | [`command_center_ui_001.md`](evidence/experiments/command_center_ui_001.md), [`command_center_data.json`](evidence/experiments/command_center/command_center_data.json) | Read-only operator map, incidents, traces, trust, and assistant endpoints. |
| Evidence Review | [`atlas_phase_24_001.md`](evidence/experiments/atlas_phase_24_001.md) through [`atlas_phase_50_001.md`](evidence/experiments/atlas_phase_50_001.md), [`docs/atlas/README.md`](docs/atlas/README.md), [`assembly_cell_missing_tool.jsonl`](datasets/demo/atlas/assembly_cell_missing_tool.jsonl) | Local evidence workflow: domain packs, physical event ledger, Cell Truth Report, dashboard, USDA replay export, evidence bundle v3, regression, training, query/saved queries, SQLite evidence lake, connectors, edge helpers, multi-cell compare, privacy report, protocol export, pilot kit, freeze audit, and Atlas-Bench core. |
| Integrations and deployment | [`ros2_bridge_001.md`](evidence/experiments/ros2_bridge_001.md), [`isaac_omniverse_replay_001.md`](evidence/experiments/isaac_omniverse_replay_001.md), [`jetson_edge_deployment_001.md`](evidence/experiments/jetson_edge_deployment_001.md), [`fleet_agent_001.md`](evidence/experiments/fleet_agent_001.md), [`scalable_event_pipeline_001.md`](evidence/experiments/scalable_event_pipeline_001.md) | Adapter and deployment evidence with hardware/tooling limitations documented per artifact. |
| Manual integration runtime smoke | [`ros2_runtime_manual_2026-06-14.md`](evidence/experiments/ros2_runtime_manual_2026-06-14.md), [`omniverse_runtime_manual_2026-06-14.md`](evidence/experiments/omniverse_runtime_manual_2026-06-14.md) | ROS 2 one-environment smoke passed for bridge build, `ros2 run`, launch, topic echo, and bag capture. Omniverse generated USDA evidence is partial because no raw open log or screenshot was captured. Isaac Sim and Docker runtime were not run in this pass. |
| Manifest/checksums | [`manifest.csv`](evidence/manifest.csv), [`CHECKSUMS.sha256`](evidence/CHECKSUMS.sha256) | Manifest records claim IDs, artifact paths, metrics, current hashes, release tag, and provenance notes; aggregate checksums cover regular files in the release tree. |

## CPU/GPU performance

| N objects | CPU p50 ms | CPU p95 ms | GPU p50 ms | GPU p95 ms | Relation |
|---:|---:|---:|---:|---:|---|
| 1 | 0.005631 | 0.006708 | 0.322591 | 0.478844 | GPU slower |
| 10 | 0.024406 | 0.026089 | 0.343555 | 0.491760 | GPU slower |
| 50 | 0.109910 | 0.120303 | 0.432770 | 0.564343 | GPU slower |
| 200 | 0.437469 | 0.447466 | 0.773220 | 1.148387 | GPU slower |
| 1000 | 2.225280 | 2.270170 | 2.574817 | 2.728293 | GPU slower |

This benchmark covers fusion compute only. It does not measure camera capture, ArUco detection, mapping, WebSocket streaming, JSONL recording, or full-pipeline acceleration.

## Reproduction commands

| Result | Command |
| ------ | ------- |
| Latency/update rate | `./tools/mp.sh timing-breakdown` |
| Static continuity | `python tools/analyze_id_stability_jsonl.py SESSION_JSONL --out evidence/experiments/id_stability_001.csv` |
| Motion continuity | `python tools/analyze_id_stability_jsonl.py SESSION_JSONL --out evidence/experiments/id_stability_movement_001.csv` |
| Mapping error | `python benchmarks/run_mapping_error.py --help` |
| Replay determinism | `./tools/mp.sh deterministic-replay` |
| Backpressure | `./tools/mp.sh backpressure` |
| Fusion jitter | `python benchmarks/run_fusion_jitter.py SESSION_JSONL --out evidence/experiments/fusion_jitter_001.csv` |
| CPU/GPU equivalence | `python benchmarks/run_compute_equivalence.py --session-jsonl SESSION_JSONL --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu` |
| CPU/GPU benchmark | `./tools/mp.sh gpu-benchmark` |
| Zone analytics | `python tools/zones_report_jsonl.py SESSION_JSONL --out evidence/experiments --prefix case_study_1_movement` |
| Docker proof | `./tools/docker_demo_up.sh` |
| Operator UI smoke | See [`docs/operator_ui_runbook.md`](docs/operator_ui_runbook.md) |
| Sentinel demo | `metriplane sentinel run --config configs/sentinel_demo.yaml --run-id sentinel_demo` |
| Command Center export | `metriplane command-center export evidence/incidents/INC-DIST-001 --out web/dashboard/command_center_data.json` |
| Physical regression | `metriplane test evidence/incidents/INC-0001` |
| Evidence Review | `metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out runs/atlas/assembly_cell_missing_tool` |
| Atlas bundle/regression | `metriplane atlas bundle verify runs/atlas/assembly_cell_missing_tool/evidence_bundles/INC-0001.zip && metriplane atlas test runs/atlas/assembly_cell_missing_tool/regression_tests/INC-0001.yaml` |
| Evidence Review late-phase tools | `metriplane atlas dashboard build --run-dir runs/atlas/assembly_cell_missing_tool && metriplane atlas lake build --root runs/atlas --db runs/atlas/evidence_lake.sqlite && metriplane atlas freeze build --root . --out runs/atlas/assembly_cell_missing_tool/evidence_freeze` |
| Evidence audit | `python scripts/audit_evidence.py` |

## Checksums

The aggregate checksum file is [`evidence/CHECKSUMS.sha256`](evidence/CHECKSUMS.sha256). It was generated from regular files in the current public proof surface in this checkout, excluding the aggregate file itself to avoid self-referential hashing.

To verify files that are present locally:

```bash
sha256sum -c evidence/CHECKSUMS.sha256
```

Large JSONL sessions may be archived outside Git. When a session is absent from the source checkout, use the SHA256 recorded in [`evidence/manifest.csv`](evidence/manifest.csv) to verify the archived copy.

## Known limitations

- Planar XY only; `Z=0`.
- Fiducial markers are required.
- Marker continuity is not general re-identification.
- Live evaluation uses a small workspace and primary marker set.
- The GPU benchmark covers only fusion compute, not camera capture or marker detection.
- ROS 2 manual runtime smoke is one maintainer environment only; it does not establish latency, reliability, safety, robot-control, or production-runtime claims.
- Omniverse USDA generation is evidenced, but no raw Omniverse open log or screenshot is captured in this pass.
- Atlas USD/Isaac, external pilots, hardware appliance packaging, Docker runtime, and network connectors remain future work unless separately evidenced.
- Zone dwell/transitions are applied analytics, not a full manually annotated ground-truth zone-detection benchmark.
- Large JSONL sessions may be archived outside Git if applicable.
- The latest DOI-archived software release is v0.1.4 at [`10.5281/zenodo.20631037`](https://doi.org/10.5281/zenodo.20631037). v0.2.0 release archival should be performed after tagging.

## Versioning and provenance

Some evidence files preserve pre-public internal git descriptions such as `v1.0.0-dirty` or historical VisionTwin-era metadata. The v0.2.0 software release preserves the v0.1.3 benchmark evidence baseline; [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2) was the prior canonical evidence release, and [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0) was the initial public release. Historical metadata is preserved to avoid breaking provenance and checksums.

## Historical provenance

MetriPlane was previously developed under the internal name VisionTwin. Historical evidence artifacts may preserve the old name where editing would break checksums or provenance.
