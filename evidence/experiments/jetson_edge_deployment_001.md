# Jetson / Edge Deployment — Phase 13 Evidence

- phase: 13
- feature: jetson_edge_deployment
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- artifacts: docker/jetson.Dockerfile, docker/compose.jetson.yaml,
  tools/jetson_preflight.sh, benchmarks/edge_latency.py

## Preflight (this host)

```bash
tools/jetson_preflight.sh --json
```

```json
{"os_arch":"Linux/x86_64","python":"3.12.3","cameras":"/dev/video0 /dev/video1",
 "nvidia":"nvidia-smi","cuda":"cupy","port_8000":"free","metriplane_import":"ok"}
```

## Edge latency benchmark (replay, x86 reference host)

```bash
python benchmarks/edge_latency.py --duration-s 2 \
  --out evidence/experiments/jetson_edge_latency_001.csv
```

- frames_processed: ~250k in 2s
- fps: ~126,000 (rule-engine evaluation of a 9-frame fixture, looped)
- p50_ms: ~0.008, p95_ms: ~0.009, p99_ms: ~0.011
- dropped_frames: 0

## Tests

- tests/test_edge_latency.py (3): single-pass metrics, duration looping, no-rules path.

## Deployment modes

- Mode A (replay, no camera): `docker compose -f docker/compose.jetson.yaml up`
- Mode B (live camera): `--profile live`, passes `/dev/video0`
- Mode C (GPU/CUDA): build against an L4T base; CPU fallback if CuPy unavailable

## Limitations

- **Hardware proof on a physical Jetson is pending.** The Dockerfile/compose and CUDA path
  are documented; the replay container and latency benchmark are verified on x86.
- FPS numbers here reflect rule-engine throughput on a tiny fixture, not full
  camera→detect→map runtime. Run on-device for representative Jetson numbers.
