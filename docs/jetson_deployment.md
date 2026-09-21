<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Jetson / Edge Deployment

Metriplane runs on NVIDIA Jetson-class edge hardware. The replay-only path needs no camera
and no CUDA; live camera and GPU paths are documented and used where the hardware supports
them.

## Preflight

```bash
tools/jetson_preflight.sh          # human-readable
tools/jetson_preflight.sh --json   # machine-readable
```

Checks OS/arch, Python, `/dev/video*` devices, `nvidia-smi`/`tegrastats`, CuPy/CUDA
visibility, port 8000, and `import metriplane`.

## Deployment modes

The Jetson profiles don't publish control endpoints. Replay starts no Metrics or WebSocket
listener; the example live configuration keeps both listeners on loopback inside the
container. The services run as UID/GID `10001:10001`, with a read-only root filesystem,
all capabilities dropped, and `no-new-privileges`. For camera mode, set
`METRIPLANE_VIDEO_GID` when the host video group differs from `44`. Use a separate,
reviewed configuration and bearer-token secret injection before deliberately exposing
either listener on a non-loopback interface.

### Mode A — Replay only (no camera)

```bash
docker compose -f docker/compose.jetson.yaml up
```

Verifies install and the camera-free replay pipeline. It doesn't start or publish Metrics
or WebSocket listeners. It works on any architecture because the default base image is
`python:3.12-slim`.

### Mode B — Live USB camera

```bash
tools/jetson_preflight.sh
docker compose -f docker/compose.jetson.yaml --profile live up
```

Passes `/dev/video0` into the container. Adjust the device index in
`docker/compose.jetson.yaml` for your hardware. The bundled configuration keeps Metrics
and WebSocket listeners container-local; the profile doesn't publish their ports.

### Mode C — GPU / CUDA

On Jetson, build against an L4T base that provides CUDA:

```bash
docker build --build-arg BASE_IMAGE=nvcr.io/nvidia/l4t-base:r36.2.0 \
  -f docker/jetson.Dockerfile -t metriplane-jetson .
```

Set `METRIPLANE_COMPUTE_BACKEND=gpu`. If CuPy/CUDA is unavailable, Metriplane falls back to
the CPU backend automatically (see `metriplane/compute/select.py`).

## Edge latency benchmark

```bash
python benchmarks/edge_latency.py --duration-s 60 \
  --out evidence/experiments/jetson_edge_latency_001.csv
```

Reports FPS, p50/p95/p99 per-frame latency, dropped frames, and (if `psutil` is installed)
CPU and RSS memory.

## Honesty

The Docker base image, confined camera mapping, and CUDA path are documented but
**hardware-validated proof on a physical Jetson is pending** — the replay container path
and the latency benchmark are verified on x86. Run the benchmark on-device to capture
Jetson numbers.
