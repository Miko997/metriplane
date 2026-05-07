# Changelog

All notable changes to Metriplane are documented here.

---

## [0.1.0] — 2026-05-06 — Initial public release

### Summary

First public release of Metriplane. The system was developed privately through milestones M1–M9 and is now released as an open-source project under the MIT license.

### Features included

**Core pipeline**
- USB and RTSP camera ingest via v4l2 / OpenCV
- ArUco marker detection with stable object IDs
- Planar homography mapping: pixel coordinates → world meters
- Multi-camera sensor fusion (nearest-neighbor, weighted average, Kalman filter)
- Object tracking registry with configurable timeout and zone enter/exit/dwell events
- JSONL session recording for deterministic replay

**Systems reliability**
- Deterministic replay: fixed-step clock, bit-exact frame reproducibility
- Backpressure handling: bounded queues with configurable drop policies
- Health monitoring: component-level registry for cameras, compute, WebSocket
- Config provenance: automatic stamping with git commit hash, config SHA256, run ID
- Per-stage observability: latency breakdown (detect, map, fuse, stream)

**Compute backends**
- CPU backend: NumPy-based (default)
- GPU backend: CuPy-based (optional, requires CUDA 12.x or 13.x)
- Note: CPU backend is faster than GPU in tested workloads (N=1–1000 objects)

**Operator dashboard**
- Browser-based 10-step setup wizard (environment → cameras → profile → anchors → calibrate → validate → zones → config → run → export)
- Runner service REST API on `:9000`
- Live state dashboard with WebSocket stream visualization

**Docker**
- `compose.yaml` for single-command deployment
- Replay demo mode (no camera required)
- Live camera pass-through mode

**Testing**
- 193 automated tests (unit + integration)
- 7 benchmark scripts covering determinism, backpressure, latency, GPU equivalence, and fusion jitter
- CI via GitHub Actions on ubuntu-latest

### Known limitations (initial release)

- Onboarding evidence was collected on the development machine with a warm pip cache; clean-machine installation time is not measured.
- `fusion_jitter_001.csv`: absolute fused position accuracy (`max_error_m`) was not compared against ground truth; relative jitter stability is measured.
- CPU backend is faster than GPU at small vector sizes (N ≤ 1000). GPU backend exists for larger workloads and future use.
- NVIDIA Omniverse and ROS 2 integrations are external/experimental community examples. No live latency measurements are claimed for these.
- Large session JSONL files are not included in git (size). SHA256 checksums are retained in `evidence/manifest.csv`.

### Removed from private history

This public release was prepared from the private development history with the following categories removed:
- School/research writing planning documents
- Private internal audit documents
- Personal machine-specific paths and usernames
- Unexecuted template evidence files

---

_For detailed evidence and benchmarks, see [`docs/eval/evidence_index.md`](docs/eval/evidence_index.md)._
