<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane Paper B Canonical Evidence

This file is the single source of truth for the Paper B benchmark manuscript evidence campaign.

Paper title: **Benchmarking Camera-First Planar Digital Twins: A Reproducible Protocol and MetriPlane Evaluation**.

Release name: **MetriPlane v0.1.3 — Paper B Provenance-Synchronized Evidence Release**.

No benchmark numbers changed from v0.1.2 to v0.1.3. No archival DOI is claimed yet.

## Release

| Field | Value |
|---|---|
| Display name | MetriPlane |
| Package/repo name | `metriplane` |
| Paper B canonical release tag | [`v0.1.3`](https://github.com/Miko997/metriplane/releases/tag/v0.1.3) |
| Release URL | <https://github.com/Miko997/metriplane/releases/tag/v0.1.3> |
| Prior canonical evidence release | [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2) |
| Initial public release | [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0) |
| Repository | <https://github.com/Miko997/metriplane> |
| Archival DOI | Not claimed; pending |

## Canonical Results

| Result | Canonical value | Artifact |
|---|---:|---|
| Latency / timing count | 4,387 timing samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms; non-pacing pipeline p95 approx. 3.55 ms | [`../../evidence/experiments/latency_summary.csv`](../../evidence/experiments/latency_summary.csv) |
| Mapping error | 0.63 cm mean; 1.07 cm max; N=9 grid points | [`../../evidence/experiments/mapping_error_001.csv`](../../evidence/experiments/mapping_error_001.csv) |
| Static fiducial continuity | IDs 4, 7, and 12: 100.0% coverage over 4,387 frames; 0 missing gaps | [`../../evidence/experiments/id_stability_001.csv`](../../evidence/experiments/id_stability_001.csv) |
| Motion fiducial continuity | 88,475 frames; primary-marker coverage 98.39-99.25%; max gap 533 frames | [`../../evidence/experiments/id_stability_movement_001.csv`](../../evidence/experiments/id_stability_movement_001.csv) |
| Replay determinism | 302 frames; 906 object pairs; 0.0 cm mean/max positional difference; 0 event mismatches; pass=true | [`../../evidence/experiments/replay_determinism.csv`](../../evidence/experiments/replay_determinism.csv) |
| Backpressure / overload | 30.0 s at 120 Hz synthetic input; queue_max=5; KEEP_LATEST; 3,600 generated; 995 published; 2,605 dropped; p95 latency 69.830 ms; pass=true | [`../../evidence/experiments/backpressure_summary.csv`](../../evidence/experiments/backpressure_summary.csv) |
| Fusion jitter | 0.067-0.080 mm jitter std; 100.0% coverage; `max_error_m=NaN`, so absolute fused accuracy is not measured here | [`../../evidence/experiments/fusion_jitter_001.csv`](../../evidence/experiments/fusion_jitter_001.csv) |
| CPU/GPU equivalence | 13,161 samples; 0.0 cm RMSE diff; 0.0 cm max diff; `cpu_numpy` vs `gpu_cupy` | [`../../evidence/experiments/compute_equivalence_001.csv`](../../evidence/experiments/compute_equivalence_001.csv) |
| CPU/GPU fusion performance | GPU backend is numerically valid but slower than CPU for tested N=1-1000 fusion-compute workloads | [`../../evidence/experiments/gpu_benchmark_001.csv`](../../evidence/experiments/gpu_benchmark_001.csv) |
| Zone analytics | Four zones (`bl`, `br`, `tl`, `tr`); 877.85 object-seconds dwell; 112 transitions | [`../../evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv`](../../evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv), [`../../evidence/experiments/case_study_1_movement_zone_transitions.csv`](../../evidence/experiments/case_study_1_movement_zone_transitions.csv) |
| Docker proof | Dummy-mode startup, health, and WebSocket message flow validated; replay-mode behavior is not used as a benchmark claim | [`../../evidence/experiments/docker_demo_proof_001.md`](../../evidence/experiments/docker_demo_proof_001.md) |
| Operator UI smoke | 10-step workflow passed; workflow smoke evidence, not a tracking-accuracy benchmark | [`../../evidence/experiments/operator_ui_final_smoke_001.md`](../../evidence/experiments/operator_ui_final_smoke_001.md) |

## GPU Performance Table

| N objects | CPU p50 ms | CPU p95 ms | GPU p50 ms | GPU p95 ms | Relation |
|---:|---:|---:|---:|---:|---|
| 1 | 0.005631 | 0.006708 | 0.322591 | 0.478844 | GPU slower |
| 10 | 0.024406 | 0.026089 | 0.343555 | 0.491760 | GPU slower |
| 50 | 0.109910 | 0.120303 | 0.432770 | 0.564343 | GPU slower |
| 200 | 0.437469 | 0.447466 | 0.773220 | 1.148387 | GPU slower |
| 1000 | 2.225280 | 2.270170 | 2.574817 | 2.728293 | GPU slower |

The GPU benchmark covers fusion compute only. It does not measure or imply GPU acceleration for camera capture, ArUco detection, planar mapping, WebSocket streaming, JSONL recording, or the full pipeline.

## Scope And Limitations

- Planar XY tracking only; world Z is fixed at `Z=0`.
- ArUco/fiducial markers are required.
- Marker continuity is not general marker-free recognition or person/object re-identification.
- Live evaluation uses a small workspace and a primary marker set of IDs 4, 7, and 12.
- The fusion jitter artifact measures stability only; absolute fused accuracy is not measured in that file.
- The GPU benchmark covers fusion compute only. CPU remains the default backend for current workloads; GPU remains optional for larger future batched workloads.
- Omniverse and ROS 2 demos are external/experimental integration demonstrations unless separately measured.
- Zone dwell/transitions are applied analytics, not a full manually annotated ground-truth zone-detection benchmark.
- Large JSONL sessions may be archived outside Git. When a session is absent from the source checkout, use [`../../evidence/manifest.csv`](../../evidence/manifest.csv) and checksums to verify the archived copy.

## Provenance Notes

Some evidence files preserve pre-public internal git descriptions such as `v1.0.0-dirty` or historical VisionTwin-era metadata. The Paper B canonical source release is `v0.1.3`; `v0.1.2` was the prior canonical evidence release; `v0.1.0` was the initial public release. Historical metadata is preserved to avoid breaking provenance and checksums.
