# Metriplane — Product Scope

This document defines what is in scope, what is explicitly out of scope, and what claims are supported by evidence for Metriplane v1.0.

---

## 1. In Scope (Core Product)

### 1.1 Camera Pipeline
- USB camera ingest via v4l2
- RTSP camera ingest via OpenCV
- Multi-camera support (up to 2 cameras, fusion mode)
- Frame-level ArUco marker detection
- Planar homography mapping: pixel → world coordinates (meters)

### 1.2 Fusion and Tracking
- Three fusion strategies: nearest-neighbor, weighted average, Kalman filter
- Per-camera confidence weighting
- Object tracking registry with configurable timeout
- Zone analytics: polygon zones with enter/exit/dwell/transition events

### 1.3 Output Streams
- WebSocket stream (`ws://host:8765`) with `FrameStateModel` v1.0 JSON
- HTTP health endpoint (`/health`)
- HTTP Prometheus metrics (`/metrics`)
- JSONL session recording for deterministic replay

### 1.4 Systems Reliability
- Deterministic replay with fixed-step clock
- Backpressure handling with bounded queues and drop policies
- Component-level health registry
- Config provenance: git commit hash + config SHA256 + run ID on every run
- Per-stage latency observability

### 1.5 Operator Tools
- Browser-based 10-step setup wizard
- Runner service REST API (`:9000`)
- Calibration runbook and tooling

### 1.6 Deployment
- Docker single-container deployment
- Replay demo mode (no camera required)
- CI via GitHub Actions

---

## 2. Integration Boundary

**Measured integration surface**: WebSocket stream at `ws://host:8765`

Any external system (Omniverse, ROS 2, custom application) that reads from this stream is an external integration. Metriplane guarantees the stream format (`FrameStateModel` schema v1.0) and that it is emitted in real time during a live session.

---

## 3. External / Experimental Integrations

The following integrations exist as **community examples** and are **not core deliverables**:

| Integration | Location | Status | Claimed? |
|-------------|----------|--------|----------|
| NVIDIA Omniverse | `metriplane-omniverse-ext/`, `tools/omniverse/` | External/experimental | No live latency claimed |
| ROS 2 | User-implemented via WebSocket | External/experimental | No ROS 2 latency claimed |

These adapters demonstrate that the WebSocket stream can be consumed by external systems. No live integration latency measurements are available or claimed for these.

---

## 4. GPU Compute Backend

Metriplane includes an optional CuPy GPU backend for fusion matrix operations.

**What is claimed:**
- CPU and GPU backends produce bit-identical results (verified: rmse_diff=0.0, max_diff=0.0 across 4384 frames)
- GPU backend is optional and falls back to CPU automatically if CuPy/CUDA is unavailable

**What is NOT claimed:**
- GPU speedup in typical workloads. In measured benchmarks (N=1–1000 objects), **CPU is faster than GPU** due to per-frame transfer overhead. See `evidence/experiments/gpu_benchmark_001.csv`.

---

## 5. Out of Scope

- Cloud or multi-site deployments
- Non-ArUco marker types (AprilTag, QR codes, etc.)
- DeepStream, TensorRT, or any deep learning inference pipeline
- ROS 2 integration (bridge is user-implemented)
- Live Omniverse/USD scene synchronization
- Clean-machine onboarding benchmarks (current evidence is same-machine warm-cache only)

---

## 6. Evidence Boundaries

All product claims must be backed by an artifact in `evidence/` or a `docs/eval/` summary.

| Area | Evidence | Notes |
|------|----------|-------|
| Deterministic replay | `evidence/experiments/replay_determinism.csv` | ✅ |
| Backpressure | `evidence/experiments/backpressure_summary.csv` | ✅ |
| Mapping accuracy | `evidence/experiments/mapping_error_001.csv` | ✅ mean 0.40 cm |
| ID stability | `evidence/experiments/id_stability_001.csv` | ✅ 100% coverage |
| Latency | `evidence/experiments/latency_summary.csv` | ✅ |
| GPU equivalence | `evidence/experiments/compute_equivalence_001.csv` | ✅ |
| GPU benchmark | `evidence/experiments/gpu_benchmark_001.csv` | ✅ CPU faster |
| Provenance | `evidence/experiments/run_meta.json` | ✅ |
| Onboarding | `evidence/onboarding/onboarding_001.md` | ⚠️ same-machine warm cache |
| Operator UI | `evidence/experiments/operator_ui_smoke_001.md` | ✅ |
| Omniverse latency | — | ❌ not measured |
| ROS 2 latency | — | ❌ not measured |
| Clean-machine install time | — | ❌ not measured |

---

_See [`docs/eval/evidence_index.md`](eval/evidence_index.md) for the full evidence summary._
