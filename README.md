<p align="center">
  <img src="docs/assets/metriplane.png" alt="Metriplane" width="760">
</p>

<h1 align="center">Metriplane</h1>

<p align="center">
  <strong>Turn ordinary cameras into metric object-state streams — ArUco + planar homography → real-time world-coordinate tracking and zone analytics.</strong>
</p>

<p align="center">
  <a href="https://github.com/Miko997/metriplane/actions/workflows/ci.yml">
    <img src="https://github.com/Miko997/metriplane/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT">
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.12%2B-blue" alt="Python 3.12+">
  </a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#operator-dashboard">Operator Dashboard</a> ·
  <a href="#evidence--benchmarks">Evidence</a> ·
  <a href="#installation">Setup</a> ·
  <a href="#documentation">Docs</a>
</p>

---

## Why Metriplane?

| Feature | What it means |
|---|---|
| 📷 **Any USB or RTSP camera** | No LiDAR, no depth sensor — a printed ArUco board and a USB camera are enough |
| 📐 **Metric world coordinates** | Pixel positions mapped to real-world cm/m via planar homography |
| 🔀 **Multi-camera fusion** | Kalman-filtered sensor fusion across multiple views |
| 🗺️ **Zone analytics** | Polygon zones with enter / exit / dwell event streams |
| 📡 **WebSocket streaming** | Real-time `FrameStateModel` JSON on `ws://host:8765` |
| 🎞️ **Deterministic replay** | Bit-exact JSONL replay for regression testing and demos |
| 🖥️ **Operator dashboard** | Browser-based wizard: scan cameras → calibrate → run → export |
| 🐳 **Docker ready** | One-command `docker-compose up` demo — no camera needed |
| 🔬 **Evidence-backed** | All benchmark claims backed by CSV artifacts in `evidence/` |
| ⚡ **GPU-optional** | CuPy backend for large workloads; CPU is default for small N (see [GPU Statement](#gpu-statement)) |

---

## Operator Dashboard

The browser-based Operator Dashboard guides you through every step — environment check, camera scan, calibration, zone drawing, live fusion, and session export — with no command-line required after initial setup.

<p align="center">
  <img src="docs/assets/Operator.png" alt="Metriplane Operator Dashboard" width="900">
</p>

**Start the dashboard:**

```bash
python -m metriplane.runner.service --host 127.0.0.1 --port 9000 &
python -m http.server 8088 --directory web/dashboard
# → open http://localhost:8088/operator.html
```

Full runbook: [`docs/operator_ui_runbook.md`](docs/operator_ui_runbook.md) · Multi-camera setup: [`docs/dashboard_multicam_runbook.md`](docs/dashboard_multicam_runbook.md)

---

## Demo Gallery

<table>
<tr>
<td width="50%" valign="top">
<a href="https://www.youtube.com/watch?v=X4nyYcNFQhM">
  <img src="docs/assets/demo1.jpg" alt="Metriplane Demo 1" width="100%">
</a>
<br><b>Demo 1</b>
</td>
<td width="50%" valign="top">
<a href="https://www.youtube.com/watch?v=q20j5-Owd4w">
  <img src="docs/assets/demo2.jpg" alt="Metriplane Demo 2" width="100%">
</a>
<br><b>Demo 2</b>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="https://www.youtube.com/watch?v=xfuW-MVuphE">
  <img src="docs/assets/demo3.jpg" alt="Metriplane Demo 3" width="100%">
</a>
<br><b>Demo 3</b>
</td>
<td width="50%" valign="top">
<a href="https://www.youtube.com/watch?v=tQvOO5kANqw">
  <img src="docs/assets/demo4.jpg" alt="Metriplane Demo 4" width="100%">
</a>
<br><b>Demo 4</b>
</td>
</tr>
</table>

## Quickstart

### Option A: Demo replay (no camera needed)

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
./tools/mp.sh deterministic-replay   # replay included demo dataset
```

### Option B: Docker (fastest start)

```bash
./tools/docker_demo_up.sh            # start backend (replays pre-recorded session)
curl http://localhost:8000/health | jq
./tools/docker_clean.sh              # clean up
```

See [`docker/docker_quickstart.md`](docker/docker_quickstart.md) for live-camera mode and GPU pass-through.

### Option C: Live camera

```bash
source .venv/bin/activate
./tools/mp.sh preflight              # verify system
./tools/mp.sh run-fusion cpu 30 my_run_001  # 30 second live session
```

Then open the Operator Dashboard (see above) to calibrate and monitor.

---

## Architecture

```
USB/RTSP Camera → ArUco Detection → Planar Mapping → Fusion → Tracking/Zones → WebSocket/JSONL
```

| Component | Module | Description |
|---|---|---|
| Camera ingest | `metriplane/camera/` | USB (v4l2), RTSP, multi-camera |
| ArUco detection | `metriplane/backends/` | Marker detection with stable IDs |
| Planar mapping | `metriplane/mapping/` | Homography: pixel → world meters |
| Fusion | `metriplane/pipeline/` | Nearest / weighted / Kalman strategies |
| Zone analytics | `metriplane/zones.py` | Polygon zones, enter/exit/dwell events |
| Streaming | `metriplane/streaming/` | WebSocket `ws://host:8765` |
| Recording | `metriplane/recording/` | JSONL for deterministic replay |
| Health | `metriplane/system/` | Component-level health registry |
| Compute backend | `metriplane/compute/` | CPU (NumPy) or GPU (CuPy) |

**Output endpoints:**

| Endpoint | Format | Description |
|---|---|---|
| `ws://host:8765` | JSON | Real-time `FrameStateModel` per frame |
| `http://host:8000/metrics` | Prometheus | Frame rate, object count, health scores |
| `http://host:8000/health` | JSON | Per-component health status |
| `<runs_dir>/<run_id>/session.jsonl` | JSONL | Full session recording for replay |

---

## Evidence & Benchmarks

All benchmark results are in `evidence/` with SHA256 checksums. See [`evidence/manifest.csv`](evidence/manifest.csv).

| Feature | Artifact | Key result |
|---|---|---|
| Deterministic replay | `evidence/experiments/replay_determinism.csv` | 301 frames, 0.0 cm max diff, 0 mismatches |
| Backpressure | `evidence/experiments/backpressure_summary.csv` | 120 Hz load, queue_max=5, pass=true |
| Mapping accuracy | `evidence/experiments/mapping_error_001.csv` | mean 0.63 cm, max 1.07 cm (N=9 points) |
| ID stability (static) | `evidence/experiments/id_stability_001.csv` | 100% coverage, 0 gaps, 4384 frames |
| ID stability (motion) | `evidence/experiments/id_stability_movement_001.csv` | ≥97.4% coverage, 87608 frames |
| Latency (detect, p95) | `evidence/experiments/latency_summary.csv` | cam0: 1.50 ms, cam1: 1.72 ms |
| Fusion jitter | `evidence/experiments/fusion_jitter_001.csv` | jitter_std 0.07–0.23 mm |
| GPU vs CPU | `evidence/experiments/gpu_benchmark_001.csv` | CPU faster at all tested N (1–1000 objects) |
| CPU/GPU equivalence | `evidence/experiments/compute_equivalence_001.csv` | 4387 frames, rmse_diff=0.0, max_diff=0.0 |

Full evidence docs: [`docs/eval/evidence_matrix.md`](docs/eval/evidence_matrix.md) · [`docs/eval/evidence_index.md`](docs/eval/evidence_index.md)

---

## Integration

### WebSocket — primary integration surface

Connect any WebSocket client to `ws://host:8765`:

```python
import asyncio, websockets, json

async def main():
    async with websockets.connect("ws://localhost:8765") as ws:
        frame = json.loads(await ws.recv())
        print(frame["run_id"], len(frame["objects"]))

asyncio.run(main())
```

Schema documented in [`docs/schema.md`](docs/schema.md).

### NVIDIA Omniverse *(external / experimental)*

Scripts in `tools/omniverse/` demonstrate consuming the WebSocket stream in an Omniverse USD scene. **No live integration latency is measured or claimed.** See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

### ROS 2 *(external / experimental)*

WebSocket frames can be bridged to ROS 2 topics via `rosbridge_server` or a custom subscriber node. Zone events map naturally to ROS 2 lifecycle events. Implementation is user-provided. See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -e .                      # core package
pip install -e .[gpu-cuda13x]         # optional: GPU backend (requires CUDA 12.x / 13.x + CuPy)
pip install -e .[plots]               # optional: benchmark plotting

python -m metriplane.cli doctor       # verify install
```

**Prerequisites**: Ubuntu 24.04 (tested), Python 3.12+, OpenCV, v4l2 (USB cameras).
Full details: [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md)

---

## Running Tests

```bash
source .venv/bin/activate
pip install pytest pytest-asyncio pydantic websockets   # if not already installed
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q   # 193 tests
```

> **Note**: The `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` flag prevents conflicts with ROS 2 pytest plugins if installed system-wide.

---

## Running the Demo

```bash
./tools/mp.sh demo-all 5                  # full feature showcase, ~5 s per scenario

# Individual scenarios:
./tools/mp.sh deterministic-replay        # bit-exact replay
./tools/mp.sh backpressure               # bounded queue under overload
./tools/mp.sh provenance                 # config hash + git commit stamping
./tools/mp.sh timing-breakdown           # per-stage latency profile
./tools/mp.sh gpu-smoke                  # GPU availability check
./tools/mp.sh gpu-benchmark              # CPU vs GPU comparison
```

---

## Running Live Camera Mode

```bash
./tools/mp.sh preflight                  # 1. verify system

# 2. open Operator Dashboard for guided calibration
python -m metriplane.runner.service --host 127.0.0.1 --port 9000 &
python -m http.server 8088 --directory web/dashboard &
# → http://localhost:8088/operator.html → Step 5: Calibrate

./tools/mp.sh run-fusion cpu 60 session_001   # 3. run fusion (60 s)
```

See [`docs/calibration_runbook.md`](docs/calibration_runbook.md) and [`docs/operator_ui_runbook.md`](docs/operator_ui_runbook.md).

---

## Key Commands Reference

```bash
# System checks
./tools/mp.sh preflight                        # environment health check
python -m metriplane.cli doctor                # import + dependency check

# Run fusion
./tools/mp.sh run-fusion cpu 30 run_001        # 30 s CPU session
./tools/mp.sh run-fusion gpu 30 run_002        # 30 s GPU session (requires CuPy)

# Validation scenarios
./tools/mp.sh deterministic-replay             # bit-exact replay test
./tools/mp.sh backpressure                     # bounded-queue load test
./tools/mp.sh health-degrade-cam1              # graceful degradation test
./tools/mp.sh provenance                       # provenance stamping test
./tools/mp.sh timing-breakdown                 # per-stage latency profile
./tools/mp.sh gpu-smoke                        # GPU smoke test
./tools/mp.sh gpu-equivalence                  # CPU vs GPU output equality
./tools/mp.sh gpu-benchmark                    # CPU vs GPU performance

# Docker
./tools/docker_demo_up.sh                      # start replay demo
./tools/docker_live_up.sh                      # start live camera mode
./tools/docker_stop.sh                         # stop containers
```

**Environment overrides:**

```bash
METRIPLANE_VENV=~/my-venv              # venv path (default: <repo>/.venv)
RUNS=~/metriplane-runs                 # output directory
CONFIG=configs/my.yaml                 # config file
METRIPLANE_COMPUTE_BACKEND=gpu         # force GPU backend
METRIPLANE_TIMING=1                    # enable per-stage timing
```

---

## Documentation

| Document | Purpose |
|---|---|
| [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md) | System requirements, dependency install |
| [`docs/development.md`](docs/development.md) | Dev setup, code quality, contribution guide |
| [`docs/calibration_runbook.md`](docs/calibration_runbook.md) | Camera calibration step-by-step |
| [`docs/operator_ui_runbook.md`](docs/operator_ui_runbook.md) | Web dashboard operator guide |
| [`docs/dashboard_multicam_runbook.md`](docs/dashboard_multicam_runbook.md) | Multi-camera dashboard setup |
| [`docs/schema.md`](docs/schema.md) | `FrameStateModel` v1.0 field reference |
| [`docs/frames.md`](docs/frames.md) | Coordinate systems: pixel, camera, world |
| [`docs/backpressure.md`](docs/backpressure.md) | Bounded queue design |
| [`docs/gpu_setup.md`](docs/gpu_setup.md) | CUDA / CuPy setup |
| [`docs/gpu_compute_backend.md`](docs/gpu_compute_backend.md) | GPU backend architecture |
| [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) | WebSocket, Omniverse, ROS 2 integration |
| [`docs/eval/evidence_matrix.md`](docs/eval/evidence_matrix.md) | Full evidence matrix with artifacts |
| [`docs/eval/evidence_index.md`](docs/eval/evidence_index.md) | Evidence summary and known limitations |

---

## Scope, Limitations & Disclaimers

### What's in scope

| | |
|---|---|
| ✅ In scope | Camera ingest, ArUco detection, planar homography mapping, multi-camera fusion, zone analytics, WebSocket streaming, JSONL recording, Docker deployment |
| ✅ Verified integration surface | WebSocket stream (`ws://host:8765`) — measured and claimed |
| ⚡ External / experimental | NVIDIA Omniverse extension and ROS 2 bridge are community integration examples — **no live latency measurements claimed** |
| ❌ Not in scope | Cloud infrastructure, multi-site federation, non-ArUco markers, tracking without a calibrated board |

### GPU Statement

Metriplane includes an optional CuPy GPU backend for fusion matrix operations. **In tested workloads (N=1–1000 objects), the CPU backend is faster than GPU** due to per-frame transfer overhead at small vector sizes. The GPU backend is available for larger workloads and future use.

Measured results: [`docs/gpu_compute_backend.md`](docs/gpu_compute_backend.md) · [`evidence/experiments/gpu_benchmark_001.csv`](evidence/experiments/gpu_benchmark_001.csv)

### Known Limitations

- **Onboarding evidence** (`evidence/onboarding/onboarding_001.md`) was performed on the development machine with a warm pip cache — install time on a cold cache will be slower.
- **Fusion jitter** (`fusion_jitter_001.csv`): `max_error_m` is NaN — ground-truth absolute position comparison was not run. Jitter stability (std) is measured and reported.
- **Large session files** (JSONL) are not included in git due to size; SHA256 checksums are in `evidence/manifest.csv`.
- **Omniverse and ROS 2** integrations are external/experimental — no live latency measurements are claimed.

---

## Development

```bash
ruff check .                                      # linting
mypy metriplane/                                  # type checking
pre-commit install && pre-commit run --all-files  # pre-commit hooks
python benchmarks/run_replay_determinism.py --help
```

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Miko997/metriplane/issues) for bugs and feature requests
- **Questions**: [GitHub Discussions](https://github.com/Miko997/metriplane/discussions)
- **Docs**: start with [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md) for setup, [`docs/operator_ui_runbook.md`](docs/operator_ui_runbook.md) for the dashboard

---

*Metriplane — initial public release*
