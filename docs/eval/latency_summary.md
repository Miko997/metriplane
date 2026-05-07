# Metriplane Latency Summary (RQ3)

**Purpose**: Technical sufficiency evaluation  
**Last Updated**: 2026-04-27  
**Evidence Source**: `evidence/experiments/latency_summary.csv` (M9.5, re-run 2026-04-27)  
**Git Commit**: bfce3d905395aa3c95035faee7fca60cb21f58fb (v1.0.0-dirty)

---

## Environment

| Property | Value |
|----------|-------|
| OS | Linux 6.17.0-22-generic (Ubuntu 24.04) |
| Python | 3.12.3 |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| CUDA | 13.1.1 |
| CuPy | 13.6.0 |
| Cameras | /dev/video0 (cam0) + /dev/video2 (cam1) |
| Config | `configs/fusion_health_300fps.yaml` |
| Profile | board_55x40_warehouse_story_v1_fusion |
| Compute Backend | cpu_numpy (default) |

---

## Two-Camera Latency Breakdown (Primary — 2026-04-27 re-run)

**Configuration**: Multi-camera fusion (cam0 + cam1), ArUco detection, Kalman fusion  
**Frames Processed**: 4384  
**Session Duration**: 15.1 seconds  
**Tracked Objects**: 3 ArUco markers (IDs 4, 7, 12)

| Stage | Mean (ms) | p50 (ms) | p95 (ms) | Max (ms) | Count |
|-------|-----------|----------|----------|----------|-------|
| **detect.cam1** | 1.410 | — | **1.722** | 2.059 | 4384 |
| **detect.cam0** | 1.183 | — | **1.498** | 3.203 | 4384 |
| fuse | 0.159 | — | **0.190** | 0.280 | 4384 |
| build.msg | 0.165 | — | **0.180** | 0.842 | 4384 |
| record.jsonl | 0.138 | — | **0.151** | 0.660 | 4384 |
| map.cam0 | 0.026 | — | **0.029** | 0.156 | 4384 |
| map.cam1 | 0.024 | — | **0.027** | 0.114 | 4384 |
| zones | 0.022 | — | **0.025** | 0.115 | 4384 |
| ws.send | 0.011 | — | **0.013** | 0.180 | 4384 |
| tracking | 0.003 | — | **0.003** | 0.082 | 4384 |
| camera.read | 0.001 | — | **0.002** | 0.012 | 4384 |

**Total non-pacing latency (sum of p95)**: ~4.0ms (dominated by detection)  
**Detection as fraction of total**: ~80% (cam0+cam1 detect combined)

---

## Single-Camera Latency (Historical Reference — M9.5, April 26)

**Config**: `configs/fusion_health_cam0_local.yaml` (single camera)  
**Frames**: 449, **Duration**: 15.5s, **Commit**: dcfae1e

| Stage | p50 (ms) | p95 (ms) | Max (ms) |
|-------|----------|----------|----------|
| detect.cam0 | 0.952 | **1.251** | 2.056 |
| build.msg | 0.126 | 0.174 | 0.269 |
| record.jsonl | 0.082 | 0.117 | 0.178 |
| ws.send | 0.023 | 0.035 | 0.122 |
| fuse | 0.005 | **0.006** | 0.019 |
| zones | 0.003 | 0.004 | 0.012 |
| camera.read | 0.002 | 0.004 | 0.187 |
| tracking | 0.002 | 0.003 | 0.015 |
| map.cam0 | 0.000 | 0.001 | 0.005 |

---

## Key Findings

✅ **Detection dominates**: ArUco detection per camera: p95 = 1.5–1.7ms  
✅ **Fusion lightweight**: Kalman fusion p95 = 0.190ms even with 2 cameras  
✅ **Mapping negligible**: Homography p95 = 0.027–0.029ms per camera  
✅ **Streaming overhead low**: WebSocket send p95 = 0.013ms  
✅ **Total pipeline < 4ms p95** (excluding frame pacing sleep)

**Scaling observation**: With 2 cameras, detection doubles (1.25ms × 2 = ~2.5ms total detect), but fusion only increases to 0.190ms (Kalman efficient at merge)

---

## Sufficiency Assessment (RQ3)

| Criterion | Target | Achieved | Result |
|-----------|--------|----------|--------|
| Total pipeline latency p95 | < 10ms | ~4.0ms | ✅ PASS |
| Real-time at 30 FPS (33ms budget) | > 30 FPS | ✅ well within | ✅ PASS |
| Detection predictability | p95/mean < 2x | 1.72/1.41 = 1.22x | ✅ PASS |
| Fusion overhead | < 1ms | 0.190ms p95 | ✅ PASS |

---

## Missing Evidence

- [ ] **End-to-end client latency** (`ts_omniverse_apply - ts_cam_read`): FUTURE OPTIONAL — external Omniverse adapter instrumentation; not a v1.0.3 evaluation requirement. Measured v1.0.3 latency is camera-to-WebSocket-send only.  
- FPS/update-rate evidence is available in `docs/eval/fps_summary.md` (291 FPS mean, 282–304 per second at 300 FPS target config).

**Command to get FPS**: Extract from `metrics` field in JSONL:  
```bash
python -c "import json; lines = open('~/metriplane-runs/timing_breakdown_001-11/session.jsonl').readlines(); data = [json.loads(l) for l in lines if not json.loads(l).get('type')]; fps_vals = [d['metrics']['fps'] for d in data if d.get('metrics') and 'fps' in d['metrics']]; import statistics; print(f'FPS mean={statistics.mean(fps_vals):.1f}, max={max(fps_vals):.1f}')"
```

---

## Evidence Files

| File | Path | SHA256 |
|------|------|--------|
| latency_summary.csv (re-run) | `evidence/experiments/latency_summary.csv` | 0dffce9880303e3cedae81ffa202243d7b68a336c4bdb8bfe6b6110396e7da8c |
| latency_summary.csv (M9.5 reference) | `evidence/experiments/m9_5_latency_summary.csv` | — |
| Session JSONL | `~/metriplane-runs/timing_breakdown_001-11/session.jsonl` | — |

---

## Regeneration Command

```bash
cd <repo> && source .venv/bin/activate && ./tools/mp.sh timing-breakdown
```
