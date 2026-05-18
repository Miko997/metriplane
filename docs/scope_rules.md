# MetriPlane Product Scope

This document defines the supported public-release scope for MetriPlane and the evidence boundaries for Paper B.

**Paper B canonical release tag**: [`v0.1.3`](https://github.com/Miko997/metriplane/releases/tag/v0.1.3)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Repository**: <https://github.com/Miko997/metriplane>
**Canonical Paper B evidence**: [`eval/CANONICAL_EVIDENCE.md`](eval/CANONICAL_EVIDENCE.md)

## In Scope

- USB and RTSP camera ingest through the `metriplane` camera pipeline.
- ArUco/fiducial marker detection with printed marker IDs.
- Planar homography mapping from image coordinates to world XY coordinates.
- World coordinates are planar; `Z=0`.
- One-camera and two-camera evaluation runs.
- Fusion strategies for observed fiducial positions.
- Polygon zone analytics with dwell, enter/exit, and transition events.
- WebSocket/JSONL `FrameStateModel` state stream.
- Deterministic replay, bounded backpressure, provenance records, and per-stage timing evidence.
- Browser-based operator workflow smoke evidence.
- Docker dummy-mode startup, health, and WebSocket message-flow proof.

## Explicitly Out Of Scope

- Marker-free object recognition.
- General re-identification without fiducials.
- Full 3D scene reconstruction.
- Safety-certified industrial control.
- DeepStream, TensorRT, or deep-learning inference pipeline claims.
- Cloud or multi-site deployment claims.
- Live Omniverse or ROS 2 latency claims unless separately measured.

## Evidence Boundaries

| Area | Evidence | Supported claim |
|---|---|---|
| Deterministic replay | `evidence/experiments/replay_determinism.csv` | 302 frames; 906 object pairs; 0.0 cm max positional difference; 0 event mismatches |
| Backpressure | `evidence/experiments/backpressure_summary.csv` | 120 Hz synthetic input; queue_max=5; 995 published; 2,605 dropped; pass=true |
| Mapping accuracy | `evidence/experiments/mapping_error_001.csv` | 0.63 cm mean; 1.07 cm max; N=9 grid points |
| Static fiducial continuity | `evidence/experiments/id_stability_001.csv` | IDs 4, 7, and 12: 100.0% coverage over 4,387 frames |
| Motion fiducial continuity | `evidence/experiments/id_stability_movement_001.csv` | 98.39-99.25% coverage over 88,475 frames |
| Latency | `evidence/experiments/latency_summary.csv` | 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms |
| Fusion jitter | `evidence/experiments/fusion_jitter_001.csv` | 0.067-0.080 mm jitter std; absolute fused accuracy not measured |
| CPU/GPU equivalence | `evidence/experiments/compute_equivalence_001.csv` | 13,161 samples; 0.0 cm RMSE and max difference |
| GPU fusion benchmark | `evidence/experiments/gpu_benchmark_001.csv` | CPU faster than GPU for tested N=1-1000 fusion-compute workloads |
| Zone analytics | `evidence/experiments/case_study_1_movement_zone_*.csv` | Four zones; 877.85 object-seconds dwell; 112 transitions |
| Docker proof | `evidence/experiments/docker_demo_proof_001.md` | Dummy-mode startup, health, and WebSocket message flow |
| Operator UI | `evidence/experiments/operator_ui_final_smoke_001.md` | 10-step workflow smoke proof |

## GPU Compute Backend

MetriPlane includes an optional CuPy GPU backend for fusion compute.

Supported claims:

- `cpu_numpy` and `gpu_cupy` produce identical Paper B fusion outputs in `compute_equivalence_001.csv`.
- The GPU backend is correct but slower than CPU for tested N=1-1000 fusion-compute workloads in `gpu_benchmark_001.csv`.
- CPU remains the default backend for current workloads.
- GPU remains optional for larger future batched workloads.

Not claimed:

- GPU acceleration of camera capture.
- GPU acceleration of ArUco detection.
- GPU acceleration of planar mapping.
- GPU acceleration of WebSocket streaming, JSONL recording, or the full pipeline.

## Integration Boundary

The measured integration surface is the WebSocket/JSONL state stream. Omniverse and ROS 2 demos are external/experimental integration demonstrations unless separately measured.

## Provenance Note

Some evidence files preserve pre-public internal git descriptions such as `v1.0.0-dirty` or historical VisionTwin-era metadata. The Paper B canonical source release is `v0.1.3`; `v0.1.2` was the prior canonical evidence release; `v0.1.0` was the initial public release. Historical metadata is preserved to avoid breaking provenance and checksums.
