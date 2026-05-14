# Launcher Smoke Evidence — launcher_smoke_001

**Status**: ✅ PASS  
**Date**: 2026-04-29T18:46:26+03:00  
**Git commit**: `57823ba` (fix: make launcher restart ports reusable)  
**Tag**: `v1.0.2-launcher`  
**Config**: `configs/fusion_health_300fps.yaml`

---

## 1. Test Suite

```
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

```
........................................................................ [ 37%]
........................................................................ [ 74%]
.................................................                        [100%]
193 passed in 62.87s (0:01:02)
```

---

## 2. Cleanup + Pre-start Port Check

```
metriplane cleanup
```

```
🧹 Checking for orphaned Metriplane processes …

ℹ️   No Metriplane orphans found.
```

```
for p in 9000 8088 8000 8765; do ss -H -ltnp | grep ":$p " && echo "OCCUPIED $p" || echo "FREE $p"; done
```

```
FREE 9000
FREE 8088
FREE 8000
FREE 8765
```

---

## 3. Start

```
metriplane start --live
```

```
🔍 Repo root : <repo>
📋 Log dir  : ~/metriplane-runs/_launcher/20260429_184626

▶  Starting runner on http://127.0.0.1:9000/
  ✅ Runner OK  (pid=65827)
▶  Starting dashboard on http://127.0.0.1:8088/
  ✅ Dashboard OK  (pid=65829)
▶  Starting fusion  (config=configs/fusion_health_300fps.yaml, run_id=live_20260429_184626)
  ✅ Fusion OK  (pid=65842)

============================================================
✅  Metriplane stack is running
============================================================
  Dashboard    : http://127.0.0.1:8088/web/dashboard/
  Operator UI  : http://127.0.0.1:8088/web/dashboard/operator.html
  Runner API   : http://127.0.0.1:9000/status
  Health       : http://127.0.0.1:8000/health
  Metrics      : http://127.0.0.1:8000/metrics
  WebSocket    : ws://127.0.0.1:8765

  Logs         : ~/metriplane-runs/_launcher/20260429_184626/
  State        : .cache/metriplane/launcher-state.json

  Stop with    : metriplane stop
============================================================
```

---

## 4. Endpoint Checks

### Runner

```
curl -fsS http://127.0.0.1:9000/status
```

```json
{"service": "metriplane-runner", "version": "2.0.0", "status": "idle", "current_job": null,
 "last_completed_job": null, "job_history_size": 0, "uptime_s": 2.85,
 "repo_root": "<repo>"}
```

### Health (all 14 components OK)

```
curl -fsS http://127.0.0.1:8000/health
```

```json
{"components": {
  "camera.cam0": {"status": "OK"},
  "camera.cam1": {"status": "OK"},
  "camera.open": {"status": "OK"},
  "camera.read": {"status": "OK"},
  "compute.backend": {"status": "OK"},
  "fusion": {"status": "OK"},
  "http.metrics": {"status": "OK"},
  "mapping.cam0": {"status": "OK"},
  "mapping.cam1": {"status": "OK"},
  "process": {"status": "OK"},
  "recorder.jsonl": {"status": "OK"},
  "ws": {"status": "OK"},
  "ws.send": {"status": "OK"},
  "zones": {"status": "OK"}
 },
 "overall": "OK",
 "uptime_s": 2.202324787}
```

### Metrics

```
curl -fsS http://127.0.0.1:8000/metrics | head -6
```

```
# HELP metriplane_fps Current FPS (smoothed).
# TYPE metriplane_fps gauge
metriplane_fps 289.903

# HELP metriplane_objects_tracked Number of objects currently tracked.
# TYPE metriplane_objects_tracked gauge
metriplane_objects_tracked 2
```

### WebSocket — schema_version and raw_per_camera=2

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        frame = json.loads(await ws.recv())
        print("schema_version:", frame.get("schema_version"))
        print("frame_id:", frame.get("frame_id"))
        rpc = frame.get("raw_per_camera", [])
        print("raw_per_camera count:", len(rpc))
        for c in rpc:
            print(" cam:", c.get("camera_id"), "objs:", len(c.get("objects", [])),
                  "stale:", c.get("metrics", {}).get("stale_for_fusion"))

asyncio.run(main())
```

```
schema_version: 1.0
frame_id: 337
raw_per_camera count: 2
 cam: cam0 objs: 2 stale: False
 cam: cam1 objs: 2 stale: False
```

---

## 5. Stop + Port-free Verification

```
metriplane stop
```

```
  Stopping fusion    (pid=65842 pgid=65842) …
  ✅ Fusion stopped
  Stopping runner    (pid=65827 pgid=65827) …
  ✅ Runner stopped
  Stopping dashboard (pid=65829 pgid=65829) …
  ✅ Dashboard stopped

✅ All launcher services stopped.
```

Port check immediately after stop:

| Port | Service       | Status |
|------|---------------|--------|
| 9000 | Runner        | FREE   |
| 8088 | Dashboard     | FREE   |
| 8000 | Health/Metrics| FREE   |
| 8765 | WebSocket     | FREE   |

---

## 6. Restart Cycles (×3)

Each cycle: `metriplane restart --live` → endpoint checks → `metriplane stop` → port check

### Cycle 1

```
⟳  Starting new stack …
  ✅ Runner OK  (pid=66283)
  ✅ Dashboard OK  (pid=66285)
  ✅ Fusion OK  (pid=66287)
✅  Metriplane stack is running

runner status: idle
health: OK
metriplane_fps 289.903 (gauge)

  ✅ Fusion stopped / ✅ Runner stopped / ✅ Dashboard stopped
✅ All launcher services stopped.
FREE 9000 / FREE 8088 / FREE 8000 / FREE 8765
```

### Cycle 2

```
  ✅ Runner OK  (pid=66446)
  ✅ Dashboard OK  (pid=66448)
  ✅ Fusion OK  (pid=66450)
runner status: idle  |  health: OK
✅ All launcher services stopped.
FREE 9000 / FREE 8088 / FREE 8000 / FREE 8765
```

### Cycle 3

```
  ✅ Runner OK  (pid=66611)
  ✅ Dashboard OK  (pid=66613)
  ✅ Fusion OK  (pid=66615)
runner status: idle  |  health: OK
✅ All launcher services stopped.
FREE 9000 / FREE 8088 / FREE 8000 / FREE 8765
```

---

## 7. tools/start_metriplane.sh (no venv activation)

```
./tools/start_metriplane.sh --live
```

```
🔍 Repo root : <repo>
  ✅ Runner OK  (pid=66937)
  ✅ Dashboard OK  (pid=66939)
  ✅ Fusion OK  (pid=66942)
✅  Metriplane stack is running
```

```
./tools/start_metriplane.sh status
```

```
  Runner       : ✅ running (pid=66937)
    URL        : http://127.0.0.1:9000/status  🟢 online
  Dashboard    : ✅ running (pid=66939)
    Dashboard  : http://127.0.0.1:8088/web/dashboard/  🟢 online
  Fusion       : ✅ running (pid=66942)  run_id=live_20260429_184710
    Health     : http://127.0.0.1:8000/health  🟢 online
    Metrics    : http://127.0.0.1:8000/metrics 🟢 online
```

Endpoint verification (no venv):

```
curl -fsS http://127.0.0.1:9000/status → runner: idle
curl -fsS http://127.0.0.1:8000/health → health: OK
```

```
./tools/start_metriplane.sh stop
```

```
  ✅ Fusion stopped
  ✅ Runner stopped
  ✅ Dashboard stopped
✅ All launcher services stopped.
FREE 9000 / FREE 8088 / FREE 8000 / FREE 8765
```

---

## Summary

| Check | Result |
|-------|--------|
| Unit tests | 193/193 PASS |
| Pre-start all ports free | ✅ |
| start --live | ✅ runner + dashboard + fusion |
| runner /status | ✅ `{"status": "idle"}` |
| health /health all 14 components | ✅ `overall: OK` |
| /metrics metriplane_fps | ✅ 289.903 |
| WebSocket schema_version | ✅ `1.0` |
| WebSocket raw_per_camera | ✅ count=2 (cam0 + cam1, both stale=False) |
| stop — all 4 ports free | ✅ immediate |
| restart ×3 — each cycle clean | ✅ |
| start_metriplane.sh (no venv) | ✅ start/status/stop all work |
