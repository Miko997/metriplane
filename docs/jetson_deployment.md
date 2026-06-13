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

### Mode A — Replay only (no camera)

```bash
docker compose -f docker/compose.jetson.yaml up
```

Verifies install, replay pipeline, metrics/health, and the WebSocket port. Works on any
arch because the default base image is `python:3.12-slim`.

### Mode B — Live USB camera

```bash
tools/jetson_preflight.sh
docker compose -f docker/compose.jetson.yaml --profile live up
```

Passes `/dev/video0` into the container. Adjust the device index in
`docker/compose.jetson.yaml` for your hardware.

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

The Docker base image and CUDA path are documented but **hardware-validated proof on a
physical Jetson is pending** — the replay container path and the latency benchmark are
verified on x86. Run the benchmark on-device to capture Jetson numbers.
