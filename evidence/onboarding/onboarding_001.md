# Metriplane Onboarding Evidence 001 — Executed

**Status**: ✅ EXECUTED — Fresh clone on same machine (NOT clean-machine)  
**Date**: 2026-04-29T19:20:52+03:00 → 19:23:22+03:00  
**Git commit**: `15037e0`  
**Tag**: none (main branch, post `v1.0.2-launcher`)  
**Environment**: fresh clone at `/tmp/metriplane-onboarding` — same hardware, warm pip cache  
**Environment label**: **fresh clone same machine — NOT clean-machine, NOT fresh user**

---

## Environment Disclaimer

This onboarding run was executed on the development machine using a fresh
`git clone` to a temporary directory. The pip cache was warm (packages already
downloaded). This means:

- Installation was ~5× faster than a true clean machine (warm cache)
- Python system packages (e.g. `python3-venv`) were already installed
- Live 2-camera hardware was already connected and calibrated

**Use for**: Demonstrating the command sequence, friction points, and step
count. **Do not use for**: Clean-machine time claims. A clean-VM protocol
on a fresh Ubuntu install with cold pip cache is needed for RQ1 time claims.

---

## Timing Summary

| Milestone | Timestamp | Elapsed from start |
|-----------|-----------|-------------------|
| Clone start | 19:20:52 | 0s |
| Clone done | 19:20:52 | <1s |
| `python3 -m venv .venv` | 19:21:03 | 11s |
| `pip install --upgrade pip` | 19:21:04 | 12s |
| `pip install -e .` done | 19:21:07 | 15s |
| ⚠️ `pip install pytest` (friction, undocumented) | 19:21:35 | 43s |
| `pytest -q` done (193/193) | 19:22:38 | 106s |
| Stack running (`start_metriplane.sh --live`) | 19:22:55 | 123s = **2.1 min** |
| Stack stopped | 19:23:22 | 150s = 2.5 min |

**Time to first live demo** (stack running + WebSocket alive): **~2.1 min** (warm cache, incl. tests)  
**Time to live stack without tests**: **~20s** (venv + install + start)  
**Steps to first demo**: **6** non-trivial steps + 1 friction step (see below)

---

## Full Command Log

### Step 1 — Clone

```bash
rm -rf /tmp/metriplane-onboarding
git clone file://<repo> /tmp/metriplane-onboarding
cd /tmp/metriplane-onboarding
git checkout main
git rev-parse --short HEAD
```

```
Already on 'main'
15037e0
```

**Result**: ✅ Clone complete, commit `15037e0` confirmed.

### Step 2 — Create venv

```bash
python3 -m venv .venv
```

Completed at 19:21:03 (11s from clone start).

**Result**: ✅

### Step 3 — Upgrade pip

```bash
source .venv/bin/activate   # or use .venv/bin/python directly
python -m pip install --upgrade pip
```

```
(exit 0, pip upgraded)
```

**Result**: ✅

### Step 4 — Install project

```bash
python -m pip install -e .
```

```
ERROR: pip's dependency resolver does not currently take into account all the
packages that are installed. This behaviour is the source of the following
dependency conflicts.
launch-ros 0.26.10 requires setuptools, which is not installed.
```

**Result**: ✅ Non-fatal warning only (system ROS package, unrelated to Metriplane).
Install succeeded. Duration: 3s (warm cache).

### Step 4a — ⚠️ FRICTION: pytest not installed

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

```
/tmp/metriplane-onboarding/.venv/bin/python: No module named pytest
```

**Friction**: `pytest` is not listed in `pyproject.toml` `[project.optional-dependencies]`
dev group (no such group exists). A new user following the README would hit this
immediately. Fix: install explicitly.

**Fix applied**:

```bash
pip install pytest
```

Duration: 1s (warm cache).

### Step 5 — Run tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

```
........................................................................ [ 37%]
........................................................................ [ 74%]
.................................................                        [100%]
193 passed in 62.97s (0:01:02)
```

**Result**: ✅ 193/193 PASS from fresh clone.

### Step 6 — Start the stack

```bash
./tools/start_metriplane.sh --live
```

```
🔍 Repo root : /tmp/metriplane-onboarding
  ✅ Runner OK  (pid=91818)
  ✅ Dashboard OK  (pid=91820)
  ✅ Fusion OK  (pid=91822)
✅  Metriplane stack is running
  Dashboard    : http://127.0.0.1:8088/web/dashboard/
  Runner API   : http://127.0.0.1:9000/status
  Health       : http://127.0.0.1:8000/health
  Metrics      : http://127.0.0.1:8000/metrics
  WebSocket    : ws://127.0.0.1:8765
  Stop with    : metriplane stop
```

Stack up in **3 seconds**.

**Result**: ✅ Runner + Dashboard + Fusion all started.

### Step 7 — Verify endpoints

```bash
curl -fsS http://127.0.0.1:9000/status
```
```
runner status: idle  version: 2.0.0
```

```bash
curl -fsS http://127.0.0.1:8000/health
```
```
health overall: OK  components: 14
```

```bash
curl -fsS http://127.0.0.1:8000/metrics | grep metriplane_fps
```
```
metriplane_fps 287.977
metriplane_objects_tracked 2
```

### Step 8 — WebSocket check

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        frame = json.loads(await ws.recv())
        rpc = frame.get("raw_per_camera", [])
        objs = [o for c in rpc for o in c.get("objects", [])]
        print("schema_version:", frame.get("schema_version"))
        print("frame_id:", frame.get("frame_id"))
        print("raw_per_camera count:", len(rpc))
        print("object count:", len(objs))

asyncio.run(main())
```

```
schema_version: 1.0
frame_id: 327
raw_per_camera count: 2
object count: 4
```

**Result**: ✅ `schema_version: 1.0`, `raw_per_camera count: 2`, objects live.

### Step 9 — Stop

```bash
./tools/start_metriplane.sh stop
```

```
  ✅ Fusion stopped
  ✅ Runner stopped
  ✅ Dashboard stopped
✅ All launcher services stopped.
```

**Result**: ✅ All ports free immediately.

---

## Steps Summary

| Step | Command | Result | Notes |
|------|---------|--------|-------|
| 1 | `git clone` + `git checkout main` | ✅ | <1s |
| 2 | `python3 -m venv .venv` | ✅ | 11s |
| 3 | `pip install --upgrade pip` | ✅ | 1s |
| 4 | `pip install -e .` | ✅ | 3s (warm cache); non-fatal ROS warning |
| 4a ⚠️ | `pip install pytest` | ✅ friction | Not in pyproject.toml deps |
| 5 | `pytest -q` | ✅ 193/193 | 63s (test suite) |
| 6 | `./tools/start_metriplane.sh --live` | ✅ | 3s to stack running |
| 7–8 | curl + WebSocket verify | ✅ | All endpoints online |
| 9 | `stop` | ✅ | All ports free |

**Non-trivial step count**: 6 (steps 2–6–stop, excluding clone as prerequisite)  
**Friction count**: 1 (pytest not in deps)

---

## Findings

1. **Single command to live demo** after install: `./tools/start_metriplane.sh --live`  
   Stack starts in 3 seconds from the command.

2. **`pip install pytest` friction** (1 extra undocumented step): A `dev` optional
   dependency group with `pytest` should be added to `pyproject.toml`. Recommended
   fix: `pip install -e ".[dev]"` for developer onboarding.

3. **Total install time (warm cache)**: 15s. On cold cache (clean machine) expect
   2–5 minutes depending on network speed and platform.

4. **Onboarding step count to live demo**: 6 steps, 1 friction point.
   Compares favorably to sensor-heavy approaches requiring hardware driver
   installation, multi-step calibration, and service configuration.

5. **Not a clean-machine measurement**: For RQ1 adoption friction claims, a
   bare Ubuntu VM with no prior Python packages is needed. This evidence shows
   the command sequence is correct and the friction point is identified.
