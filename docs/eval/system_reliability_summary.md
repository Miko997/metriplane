# Metriplane System Reliability Summary

**Purpose**: Systems hardening evidence RQ2 (architecture) and RQ3 (robustness)  
**Last Updated**: 2026-04-27  
**Git Commit**: bfce3d905395aa3c95035faee7fca60cb21f58fb (v1.0.0-dirty)

---

## Overview

M9 milestone: systems hardening — determinism, backpressure, health monitoring, provenance.  
These demonstrate production-grade reliability patterns in a research artifact.

---

## M9.1: Deterministic Replay ✅ PASS

**Command**: `./tools/mp.sh deterministic-replay`  
**Date**: 2026-04-27  
**Evidence**: `evidence/experiments/replay_determinism.csv`  
**SHA256**: `901e317c0b8c258aa584724131ce91c27851e8a2c784b39c5484400d523e71cc`

### Results

| Metric | Value |
|--------|-------|
| Frames compared | **1201** |
| Object pairs compared | **8405** |
| Mean position difference | **0.0 cm** |
| Max position difference | **0.0 cm** |
| Event mismatches | **0** |
| Pass | **TRUE** |

> Note: 2026-04-26 run had 301 frames with 0 object pairs (no live markers at that time).  
> 2026-04-27 re-run used a session with real ArUco markers — 8405 object pair comparisons, still 0.0 cm.

### What This Proves
✅ Bit-exact reproducibility: replay produces identical outputs to live run  
✅ Fixed-step simulation: `ts_sim_ns` clock eliminates nondeterminism  
✅ Object state determinism confirmed across 8405 comparisons  
✅ Zone event determinism: 0 mismatches  

### Mechanism
- Single authoritative clock (`time/clock.py`) produces `ts_sim_ns`
- Stable sorted iteration (cameras, objects, detections)  
- `metriplane/replay/engine.py` re-runs pipeline with same inputs

---

## M9.2: Backpressure Handling ✅ PASS

**Command**: `./tools/mp.sh backpressure`  
**Date**: 2026-04-27  
**Evidence**: `evidence/experiments/backpressure_summary.csv`  
**SHA256**: `cb0b3ae28c46184d7221ddf0e9b41d9d1ae4ab8dc333558f7f303fbb50bc9cdc`

### Configuration

| Parameter | Value |
|-----------|-------|
| Duration | 30.0 s |
| Input rate | 120 FPS (synthetic — 4× target rate) |
| Simulated detect time | 30 ms/frame |
| Queue max | 5 frames |
| Policy | KEEP_LATEST (drop oldest on overflow) |

### Results

| Metric | Value |
|--------|-------|
| Frames generated | 3600 |
| Frames accepted | 3600 |
| **Frames dropped** | **2600** (72.2%) |
| Detect processed | 1000 |
| Published | 1000 |
| Max queue depth | **5** (saturated as expected) |
| Mean latency | 51.06 ms |
| p50 latency | 51.15 ms |
| p95 latency | 69.80 ms |
| Pass | **TRUE** |

### What This Proves
✅ Graceful degradation: system stable under 4× overload for 30s  
✅ Bounded queues: memory does not grow unbounded  
✅ KEEP_LATEST policy: recent frames preserved, stale dropped  
✅ No crashes, no blocked threads, no OOM  

### Mechanism
- `metriplane/pipeline/bounded_queue.py`: `BoundedQueue` with configurable max depth
- KEEP_LATEST: on overflow, oldest item discarded, newest accepted
- Metrics exported via Prometheus endpoint during run

---

## M9.3: Health Monitoring ⚠️ PARTIAL

**Status**: Code complete, full multi-camera scenario **BLOCKED** by hardware

### What Exists (Code Complete)

| Component | Path | Status |
|-----------|------|--------|
| Health registry | `metriplane/system/health_registry.py` | ✅ Complete |
| Health probes | `metriplane/system/health.py` | ✅ Complete |
| Fault injection | `metriplane/system/fault_injection.py` | ✅ Complete |
| Health unit tests | `tests/test_health_registry.py`, `tests/test_fault_injection.py` | ✅ Pass |
| Single-cam health validated | doctor: 8/8 PASS | ✅ Pass |

### Blocked Evidence

**Reason**: Hardware limitation — `/dev/video1` exists but cannot be opened by OpenCV (companion node, not capture-capable). Testing cam1 failure requires a second real capture camera.

**Available evidence**:
- `evidence/experiments/health_degrade_cam1_meta.json` (January 2026 attempt)
- `evidence/experiments/m9_3_health_001.jsonl` (40 KB of health log frames)

### Evaluation Position
The health monitoring system is implemented and tested at the unit level (2 test files pass). Full degradation scenario not hardware-validated on this machine. Mark as "implemented, hardware-constrained validation" in the evaluation.

To fully test: add second capture-capable USB camera to `/dev/video2` while running 2-camera config.

---

## M9.4: Config Provenance ✅ PASS

**Command**: `./tools/mp.sh provenance`  
**Date**: 2026-04-27  
**Evidence**: `evidence/experiments/run_meta.json`  
**SHA256**: `d4b97c55f67b11a742ba8a98168ec7b9d939c653e415bc3f0275f96ccc886247`

### Provenance Fields (Verified in Live Run)

```json
{
  "run_id": "provenance_run_001-18",
  "config_hash": "374489919f82bd800d922f4492405680bff9812c085916e854034047c284d481",
  "git": {
    "commit": "bfce3d905395aa3c95035faee7fca60cb21f58fb",
    "describe": "v1.0.0-dirty",
    "dirty": true
  },
  "schema_version": "1.0",
  "created_utc": "2026-04-27T17:28:25Z",
  "hostname": "miko-21796-2252-20700",
  "resolvedprofile": "board_55x40_warehouse_story_v1_fusion"
}
```

**Additionally, each JSONL frame carries**:
- `config_hash`
- `git_commit`
- `run_id`
- `schema_version`
- `ts_sim_ns` (authoritative simulation time)

### What This Proves
✅ Every run traceable to exact git commit  
✅ Config immutable (canonical JSON hash)  
✅ Environment captured (env.txt with pip freeze)  
✅ Schema version stamped on every output frame  
✅ Results reproducible: given session JSONL + meta.json → full audit trail  

---

## Summary Table

| Capability | Status | Evidence | Evaluation Value |
|------------|--------|----------|--------------|
| **Deterministic Replay** | ✅ COMPLETE | 1201 frames, 8405 pairs, 0.0 cm | RQ2, RQ3 |
| **Backpressure** | ✅ COMPLETE | 2600 drops, 30s stable, PASS | RQ2, RQ3 |
| **Health Monitoring** | ⚠️ PARTIAL | Unit tests pass; degradation hardware-blocked | RQ2 |
| **Config Provenance** | ✅ COMPLETE | git_commit + config_hash + schema_version | RQ2 |

---

## CI Validation

**Tests**: 193/193 passed (initial-public-release, 2026-04-29)
**Command**: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`  
**Coverage**: Unit tests for health registry, fault injection, provenance, schema, zones, mapping

---

## Regeneration Commands

```bash
cd <repo> && source .venv/bin/activate

./tools/mp.sh deterministic-replay   # M9.1
./tools/mp.sh backpressure            # M9.2 (30s runtime)
./tools/mp.sh provenance              # M9.4
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q  # Unit tests
python -m metriplane.cli doctor       # System check
```
