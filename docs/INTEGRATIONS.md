<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Integrations

**Last Updated**: 2026-04-26  
**Status**: Integration interfaces stable, external clients are separate components  
**Purpose**: Guide for integrating Metriplane with Omniverse, ROS 2, and custom clients

---

## Overview

Metriplane core provides **standard data interfaces** that external systems can consume:

1. **WebSocket Stream** (port 8765): Real-time `FrameStateModel` JSON frames
2. **HTTP Metrics** (port 8000): Prometheus-format metrics endpoint
3. **HTTP Health** (port 8000): Component health status JSON
4. **JSONL Recording**: Offline session replay files

**Integration Architecture**: Metriplane is **headless** by design. Visualization, robot control, and analytics are **separate components** that consume Metriplane outputs via standard protocols.

---

## Core Metriplane Outputs

### 1. WebSocket Stream (Port 8765)

**Endpoint**: `ws://<host>:8765`  
**Protocol**: WebSocket (RFC 6455)  
**Data Format**: JSON (Pydantic `FrameStateModel` serialization)  
**Frame Rate**: Configurable (default ~30 FPS, health configs up to 300 FPS target)

**Example Frame Structure** (illustrative - see `metriplane/schema.py` and `docs/schema.md` for exact specification):
```json
{
  "ts_sim_ns": <int>,
  "run_id": "<string>",
  "config_hash": "<string>",
  "git_commit": "<string>",
  "schema_version": "1.0",
  "objects": [
    {"id": <int>, "x_m": <float>, "y_m": <float>, "confidence": <float>, ...}
  ],
  "events": [
    {"event_type": "<string>", "zone_id": "<string>", "object_id": <int>, ...}
  ],
  "metrics": {...},
  "raw_per_camera": [...]
}
```

**Note**: This is an illustrative structure. For the exact `FrameStateModel` schema, see:
- Authoritative source: `metriplane/schema.py` (Pydantic model)
- Documentation: `docs/schema.md`

### 2. HTTP Metrics (Port 8000)

**Endpoint**: `http://<host>:8000/metrics`  
**Format**: Prometheus text format  
**Use Case**: Monitoring, alerting, Grafana dashboards

**Example**:
```bash
curl http://localhost:8000/metrics

# Sample output:
# metriplane_fps_actual 29.8
# metriplane_latency_total_ms 12.3
# metriplane_objects_tracked 5
# metriplane_queue_depth_frames 2
```

### 3. HTTP Health (Port 8000)

**Endpoint**: `http://<host>:8000/health`  
**Format**: JSON  
**Use Case**: Readiness probes, health checks, orchestration (K8s, Docker)

**Example**:
```bash
curl http://localhost:8000/health | jq

# Sample output:
{
  "overall": "healthy",
  "components": {
    "camera.cam0": {"status": "healthy"},
    "camera.cam1": {"status": "healthy"},
    "ws.send": {"status": "healthy", "client_count": 2}
  }
}
```

### 4. JSONL Recording

**Location**: `<runs-dir>/<run_id>/session.jsonl`

Platform-aware commands default `<runs-dir>` to the platform data directory's `metriplane/runs`
child (for example, `$XDG_DATA_HOME/metriplane/runs` on Linux). The legacy `metriplane-run` console
script, `python -m metriplane.run`, and `python -m metriplane.run_fusion` retain `/data/runs` in
Docker and `./runs` on a host. An explicit `--runs-dir` or config `runs_dir` overrides either
default.
**Format**: Newline-delimited JSON (one `FrameStateModel` per line)  
**Use Case**: Deterministic replay, offline analysis, dataset creation

---

## WebSocket Client Smoke Test

Verify Metriplane WebSocket stream is functional:

```bash
# Start Metriplane backend (Docker demo)
./tools/docker_demo_up.sh

# Python WebSocket client (requires websockets package)
python3 - <<'PY'
import asyncio
import websockets
import json

async def smoke_test():
    try:
        async with websockets.connect("ws://localhost:8765") as ws:
            print("✅ WebSocket connected")
            
            # Receive one frame
            frame_json = await ws.recv()
            frame = json.loads(frame_json)
            
            print(f"✅ Received frame: schema_version={frame.get('schema_version')}")
            print(f"   Objects: {len(frame.get('objects', []))}")
            print(f"   Events: {len(frame.get('events', []))}")
            print(f"   Run ID: {frame.get('run_id')}")
            
    except Exception as e:
        print(f"❌ Smoke test failed: {e}")

asyncio.run(smoke_test())
PY

# Clean up
./tools/docker_clean.sh
```

**Expected Output**:
```
✅ WebSocket connected
✅ Received frame: schema_version=1.0
   Objects: 3
   Events: 1
   Run ID: run_20260426_195432_a1b2c3
```

Alternative smoke test script: `tools/ws_smoke_client.py`

---

## Omniverse Integration

### Status: Experimental USD export

The repository contains checked-in, read-only USD replay exporters:

- `integrations/isaac/metriplane_to_usd.py`
- `integrations/isaac/metriplane_isaac_replay.py`
- `integrations/omniverse/metriplane_usd_replay.py`
- `tools/omniverse/m6_warehouse_story_v1.py`

These tools generate USD from recorded Metriplane output. They are not an
Omniverse extension and do not require the retired Omniverse Launcher. Open the
generated USD with a currently supported NVIDIA application such as Isaac Sim
or a Kit-based application installed through NVIDIA's current distribution
channels.

The core CI checks exporter syntax and deterministic output. End-to-end Isaac
Sim rendering remains a manual external validation step.

---

## ROS 2 Integration

### Status: Official source-distributed bridge

The official ROS 2 Jazzy bridge lives at
`integrations/ros2/metriplane_ros/`. It includes `package.xml`, a Python node,
message adapters, a launch file, and ROS-free adapter tests. It republishes the
Metriplane WebSocket stream on:

- `/metriplane/frame_state`
- `/metriplane/alerts`
- `/metriplane/incidents`

The bridge is deliberately packaged separately from the core PyPI wheel so a
normal `pip install metriplane` does not require ROS. Copy it into a ROS 2
workspace and build it with `colcon`; see [ros2_bridge.md](ros2_bridge.md) for
the exact commands and limitations. TF, custom message types, and RViz plugins
are not currently provided.

---

## Custom Client Integration

### WebSocket Client Template

```python
import asyncio
import websockets
import json

async def metriplane_client():
    uri = "ws://localhost:8765"
    
    async with websockets.connect(uri) as websocket:
        print(f"Connected to {uri}")
        
        while True:
            # Receive frame
            frame_json = await websocket.recv()
            frame = json.loads(frame_json)
            
            # Process frame
            for obj in frame.get("objects", []):
                print(f"Object {obj['id']}: ({obj['x_m']:.2f}, {obj['y_m']:.2f})")
            
            for event in frame.get("events", []):
                print(f"Event: {event['event_type']} - {event['zone_id']}")

# Run
asyncio.run(metriplane_client())
```

### Client Requirements

**Minimum**:
- WebSocket client library (Python: `websockets`, JS: native WebSocket API)
- JSON parser

**Recommended**:
- Schema validation against `FrameStateModel` (use Pydantic if Python)
- Connection retry logic (Metriplane may restart)
- Graceful handling of schema version changes

---

## Fallback Behavior

### When Integrations Are Absent

Metriplane operates **standalone** by default. Integrations are purely optional.

**If no WebSocket clients connected**:
- ✅ Metriplane continues running
- ✅ Metrics still exported on `:8000/metrics`
- ✅ JSONL recording still works
- ✅ Health endpoint still responds
- ⚠️ Frame broadcast happens to zero clients (minimal overhead)

**If Omniverse not installed**:
- ✅ Metriplane runs normally
- ❌ No 3D visualization
- ℹ️ Use `tools/preview_world_overlay.py` for 2D preview instead

**If ROS 2 not installed**:
- ✅ Metriplane runs normally
- ✅ Tests run without ROS 2 (use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`)
- ❌ No ROS 2 topic bridge
- ℹ️ Use raw WebSocket or HTTP endpoints for custom integration

### Graceful Degradation

- **WebSocket client disconnect**: Metriplane logs disconnect, continues running
- **Client connection limit**: No hard limit, broadcasts to all connected clients
- **Slow client**: Metriplane does not block on slow receivers (async send)

---

## Known Limitations

### Current Integration Constraints

1. **Omniverse Extension**:
   - ℹ️ Metriplane provides USD exporters, not an Omniverse extension
   - ⚠️ Isaac Sim rendering is a manual external validation step
   - ℹ️ The deprecated Omniverse Launcher is not part of the setup path

2. **ROS 2 Bridge**:
   - ✅ Official source-distributed Jazzy bridge and launch file
   - ❌ **No custom ROS 2 message types** defined
   - ❌ **No TF broadcaster** for world→object transforms
   - ⚠️ End-to-end ROS runtime validation remains manual

3. **WebSocket Protocol**:
   - ⚠️ **No authentication/authorization** (assumes trusted network)
   - ⚠️ **No TLS/WSS support** (plain WebSocket only)
   - ℹ️ Single WebSocket server, multiple clients supported
   - ℹ️ No bidirectional control (Metriplane → clients only)

4. **Schema Evolution**:
   - ⚠️ **No schema migration strategy** documented for v2.0
   - ℹ️ Current: `schema_version: "1.0"` (clients should check this field)
   - ℹ️ Backward compatibility not guaranteed beyond v1.x

### Platform Limitations

- **Coordinate System**: Planar (XY only, Z=0 assumption)
- **Detection Backend**: ArUco markers only (no AprilTag, no feature tracking)
- **Camera Support**: USB (v4l2) and RTSP only (no GigE, no Basler SDK)
- **OS Support**: Linux only (Docker on Windows/macOS untested)

---

## Compatibility Matrix

### Tested Integrations

| Integration | Tested? | Status | Metriplane Version | Notes |
|-------------|---------|--------|-------------------|-------|
| Python WebSocket client | ⚠️ Available | **Needs v1.0 verification** | Unknown | `tools/ws_smoke_client.py` workflow available |
| Docker demo | ⚠️ Available | **Needs v1.0 verification** | Unknown | `./tools/docker_demo_up.sh` workflow available |
| HTTP metrics | ⚠️ Available | **Needs v1.0 verification** | Unknown | Prometheus endpoint exists |
| HTTP health | ⚠️ Available | **Needs v1.0 verification** | Unknown | Health endpoint exists |
| USD replay export | ✅ Static tested | **EXPERIMENTAL** | current source | Isaac/Omniverse exporters are checked in; rendering is manual |
| ROS 2 bridge | ✅ Static tested | **SOURCE DISTRIBUTED** | current source | Jazzy bridge; runtime smoke is manual |
| RViz visualization | ❌ No | **NOT PROVIDED** | N/A | No TF or marker publisher yet |

### Schema Compatibility

| Client Implementation | Schema Version | Compatible? | Notes |
|-----------------------|----------------|-------------|-------|
| Omniverse extension (current) | Unknown | ⚠️ **Unverified** | May predate schema v1.0 |
| Future v2.0 clients | 2.0 | ❌ **Incompatible** | Breaking changes expected |
| Custom clients (v1.0) | 1.0 | ✅ **Compatible** | Check `schema_version` field |

---

## Pre-Release Integration Checklist

### For a future stable integration release

**Must Complete Before Release**:

- [ ] **Run USD output in a supported Isaac Sim release**
- [ ] **Run the ROS 2 Jazzy bridge end to end**
- [ ] **Record the exact external-tool versions used**
- [ ] **Create fallback documentation** for users without Omniverse/ROS 2
- [ ] **Add schema version checking** recommendation to client integration guide
- [ ] **Document WebSocket security** limitations (no auth, no TLS)

### Recommended Integration Testing

Before v1.0 tag:

```bash
# Test 1: WebSocket smoke test
./tools/docker_demo_up.sh
python tools/ws_smoke_client.py
curl http://localhost:8000/health
./tools/docker_clean.sh

# Test 2: Omniverse extension smoke test (if available)
# 1. Start Metriplane: ./tools/mp.sh run-fusion cpu 60 omni_test
# 2. Open Omniverse
# 3. Load warehouse scene
# 4. Verify objects appear and move
# 5. Check console for errors

# Test 3: Custom client test
# Use template above to create minimal client
# Verify FrameStateModel fields parse correctly
```

---

## Integration Roadmap

### V1.0 (Current)
- ✅ WebSocket stream (`FrameStateModel` v1.0)
- ✅ HTTP metrics and health endpoints
- ⚠️ Omniverse extension exists but not pinned
- ❌ ROS 2 bridge not provided

### V1.1 (Proposed)
- Extract and version-pin Omniverse extension
- Provide official ROS 2 bridge package
- Add WebSocket authentication (optional)
- Schema migration guide for extension developers

### V2.0 (Future)
- Schema v2.0 with breaking changes (documented migrations)
- Bidirectional WebSocket control (client → Metriplane commands)
- TLS/WSS support for secure deployments
- Alternative streaming protocols (gRPC, MQTT)

---

## Support

**For Integration Issues**:
1. Check Metriplane backend is running: `curl http://localhost:8000/health`
2. Verify WebSocket connectivity: `python tools/ws_smoke_client.py`
3. Review logs for connection errors
4. Check firewall rules (ports 8000, 8765)

**For Omniverse Integration**:
- ⚠️ **Community support only** until official release
- Check `metriplane-omniverse-ext/` README (if available)
- Report issues to extension repository (separate from Metriplane core)

**For ROS 2 Integration**:
- ⚠️ **User-implemented** using example code
- See `docs/PREREQUISITES.md` for ROS 2 pytest plugin workaround
- Consider using `rosbridge_server` for WebSocket → ROS topic bridge

---

**Last Updated**: 2026-04-26  
**Review Required**: Before v1.0 public release  
**Owner**: Project lead + integration maintainers
