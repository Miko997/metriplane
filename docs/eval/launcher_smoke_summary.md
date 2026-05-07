# Launcher Smoke Summary

**Evidence ID**: `launcher_smoke_001`  
**Commit**: `57823ba` | **Tag**: `v1.0.2-launcher`  
**Status**: ✅ PASS — 2026-04-29  
**Artifact**: `evidence/experiments/launcher_smoke_001.md`

---

## What Was Validated

The Metriplane one-command launcher (`metriplane start/stop/restart/cleanup` and
`tools/start_metriplane.sh`) was validated end-to-end on the development machine
with live 2-camera fusion:

| Step | Result |
|------|--------|
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` | 193/193 PASS |
| `metriplane cleanup` — no orphans | ✅ |
| `metriplane start --live` — runner + dashboard + fusion | ✅ all 3 services start |
| `curl /status` runner | ✅ `{"status": "idle"}` |
| `curl /health` — 14 components | ✅ `overall: OK` |
| `curl /metrics` — FPS gauge | ✅ `metriplane_fps 289.903` |
| WebSocket `schema_version` | ✅ `"1.0"` |
| WebSocket `raw_per_camera` count | ✅ `2` (cam0 + cam1, both `stale: False`) |
| `metriplane stop` — ports free immediately | ✅ 9000/8088/8000/8765 all FREE |
| `metriplane restart --live` × 3 cycles | ✅ each cycle clean |
| `tools/start_metriplane.sh --live` (no venv activation) | ✅ start/status/stop work |

---

## RQ Alignment

### RQ1 — Product value vs. sensor-heavy approaches

The one-command launcher contributes to the RQ1 productization value argument:
- Operator friction is eliminated: `metriplane start --live --open` starts the full
  pipeline (fusion + runner + dashboard) and opens the browser in a single command.
- No manual process management needed. Stop/cleanup/restart are atomic operations.
- `tools/start_metriplane.sh` works without `source .venv/bin/activate`, removing
  a friction point for non-developer operators.

This directly compares favorably against sensor-heavy approaches where operator
setup requires hardware configuration, driver installation, and multi-step service
startup. Metriplane reduces setup to one command from a terminal.

### RQ2 — Architectural choices for extensibility, integration, and adoption

The launcher architecture demonstrates productization design:
- **Process group management (`os.killpg`)**: Every service is a separate process
  group (PGID = PID via `start_new_session=True`), enabling atomic shutdown without
  port residue (TIME_WAIT false positives fixed via `SO_REUSEADDR` bind probe).
- **State JSON with PGID**: `~/.cache/metriplane/launcher-state.json` stores both
  `pid` and `pgid` for reliable kill, with `cmd_cleanup()` as a safe fallback.
- **Port-free polling**: `stop` verifies all ports are released before returning,
  making immediate `restart` safe without explicit sleep.
- **Layered recovery**: `cleanup` → `stop --force` → `restart` covers all orphan
  scenarios without killing non-Metriplane processes.

These are reusable platform design patterns applicable to any multi-service
Python deployment, not specific to vision systems.

### RQ3 — Performance/robustness for practical experimentation

The smoke test confirms the platform meets practical operational requirements:
- **FPS at start**: 289.9 Hz pipeline FPS confirmed within 3 seconds of startup
  (2-camera live fusion on `configs/fusion_health_300fps.yaml`)
- **Health registry**: 14 components reported OK simultaneously at start
  (camera.cam0, camera.cam1, compute.backend, fusion, mapping.cam0, mapping.cam1,
  recorder.jsonl, ws, ws.send, zones, process, http.metrics, camera.open, camera.read)
- **Zero port residue**: All 4 ports free immediately after stop, enabling 3
  consecutive restart cycles with no state accumulation

---

## Notes

- Onboarding timing (time-to-first-demo, steps-to-first-demo) is **not measured here**.
  A clean-machine onboarding log would be required to measure those. This smoke
  measures operational restart reliability only.
- Omniverse and ROS 2 integration are external surfaces not tested in this smoke.
  The WebSocket stream (`ws://127.0.0.1:8765`) is the validated integration surface.
- The `metriplane_fps 289.903` is a smoothed gauge, not a benchmark measurement.
  Dedicated latency/FPS benchmarks are in `evidence/experiments/m9_5_latency_summary.csv`
  and `evidence/experiments/latency_summary.csv`.
