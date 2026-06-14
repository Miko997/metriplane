<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Dashboard Multi-Camera Fusion Runbook

**Purpose**: Run live 2-camera fusion and view it in the dashboard

**Last Updated**: 2026-04-29

---

## ⚡ One-command Start

```bash
cd <repo>
source .venv/bin/activate

# Start runner + dashboard, open browser
metriplane start --open

# Start runner + dashboard + camera-free demo runtime, open browser
metriplane start --live --open

# Start runner + dashboard + camera-backed fusion, open browser
metriplane start --live --config configs/fusion_health_300fps.yaml --open

# Check all endpoints (works even without state file)
metriplane status

# Stop cleanly (waits for ports to be released)
metriplane stop

# If ports remain occupied after stop:
metriplane cleanup          # removes Metriplane orphans only

# Restart in one command (cleans orphans automatically):
metriplane restart --config configs/fusion_health_300fps.yaml --open

# Without venv activation:
./tools/start_metriplane.sh --open
./tools/start_metriplane.sh stop
./tools/start_metriplane.sh cleanup
```

The launcher starts the runner (port 9000) and static dashboard server (port 8088), then opens `http://127.0.0.1:8088/web/dashboard/` automatically. Runtime streams on ports 8000/8765 start only when you click the Setup/Run workflow or pass `--live`, so demo pages and Command Center are not overwritten by an automatic startup run.

**Stop guarantees port release:** uses `os.killpg()` (process group kill) and polls until all owned ports are unbound. `restart` automatically runs cleanup if ports are still occupied after stop.

For manual multi-step startup, see the sections below.

---

## Prerequisites

### Required Hardware
- 2 USB cameras (capture-capable, not companion nodes)
- Physical ArUco markers (ID 0-3 for corners, ID 7 for robot)
- Board with calibrated homography profiles

### Check Camera Availability
```bash
# List all video devices
ls -la /dev/video*

# Check by-id paths (stable device names)
ls -la /dev/v4l/by-id/

# Test if OpenCV can open device
python -c "import cv2; cap = cv2.VideoCapture(0); print('video0:', cap.isOpened()); cap.release()"
python -c "import cv2; cap = cv2.VideoCapture(1); print('video1:', cap.isOpened()); cap.release()"
```

**Known Issue**: `/dev/video1` may exist but be a non-capture companion node (audio/metadata). OpenCV cannot open it. A second capture device typically appears as `/dev/video2` or `/dev/video4`.

---

## Configuration Files

### 1. Two-Camera Live Fusion: `configs/fusion_health.yaml`
- **cam0**: `/dev/v4l/by-id/usb-XIFT_Streaming_Webcams_2025072203-video-index0`
- **cam1**: `/dev/v4l/by-id/usb-SunplusIT_Inc_HP_320_FHD_Webcam_YJGD325HP20211201V0-video-index0`
- **Fusion method**: Kalman
- **Target FPS**: 60
- **Ports**: WS 8765, Metrics 8000

### 2. Alternative: `configs/fusion_health_300fps.yaml`
- Same cameras, target_fps: 300

### 3. Single-Camera Fallback: `configs/fusion_health_cam0.yaml`
- Only cam0 (for testing when second camera unavailable)

---

## Step-by-Step Execution

### Terminal 1: Dashboard Runner (Optional)
```bash
cd <repo>
source ~/metriplane-venv/bin/activate
./tools/dashboard_runner.sh

# Or with custom port:
python -m metriplane.runner.service --port 9000
```
**Port**: 9000  
**API**: http://localhost:9000/status

---

### Terminal 2: Dashboard HTTP Server
```bash
cd <repo>
python -m http.server 8088

# Open browser:
# http://localhost:8088/web/dashboard/
```
**Port**: 8088  
**URL**: http://localhost:8088/web/dashboard/

---

### Terminal 3: Run 2-Camera Fusion
```bash
cd <repo>
source ~/metriplane-venv/bin/activate

# Default config (fusion_health_300fps.yaml)
./tools/mp.sh run-fusion cpu 60 test_run

# Or specify config explicitly:
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 test_run

# With GPU backend:
./tools/mp.sh run-fusion gpu 60 test_gpu

# Single camera (if /dev/video1 unavailable):
CONFIG=configs/fusion_health_cam0.yaml ./tools/mp.sh run-fusion cpu 60 cam0_only
```

**Arguments**:
- `cpu|gpu`: Compute backend
- `60`: Duration in seconds
- `test_run`: Run ID (for evidence)

**Ports Used**:
- **8765**: WebSocket stream
- **8000**: Health endpoint
- **8001**: Metrics endpoint

---

## Dashboard Ports Summary

| Service | Port | Description |
|---------|------|-------------|
| WebSocket | 8765 | Live frame stream |
| Health | 8000 | `/health` endpoint |
| Metrics | 8001 | Prometheus metrics (Note: dashboard polls 8000, may need update) |
| Dashboard Static | 8088 | HTTP server for dashboard files |
| Runner API | 9000 | Command execution service (optional) |

---

## Expected WebSocket Frame Structure

### Full 2-Camera Fusion Frame
```json
{
  "schema_version": "1.0",
  "run_id": "test_run",
  "frame_id": 42,
  "ts": 1714224000.123,
  
  "fused": [
    {"id": "7", "pos_world": [1.5, 2.3, 0.0], "confidence": 0.95, "vel_world": [0.1, 0.0, 0.0]}
  ],
  
  "objects": [
    {"id": "7", "pos_world": [1.5, 2.3, 0.0], "confidence": 0.95}
  ],
  
  "raw_per_camera": [
    {
      "camera_id": "cam0",
      "ts_cam_read": 1714224000.120,
      "objects": [
        {"id": "7", "pos_world": [1.48, 2.28, 0.0], "confidence": 0.92}
      ],
      "metrics": {"detections": 1, "mapped_count": 1, "kept_count": 1, "stale_for_fusion": false}
    },
    {
      "camera_id": "cam1",
      "ts_cam_read": 1714224000.121,
      "objects": [
        {"id": "7", "pos_world": [1.52, 2.32, 0.0], "confidence": 0.98}
      ],
      "metrics": {"detections": 1, "mapped_count": 1, "kept_count": 1, "stale_for_fusion": false}
    }
  ],
  
  "metrics": {
    "cams": {"cam0": {"detections": 1}, "cam1": {"detections": 1}}
  }
}
```

### Key Fields
- **`fused`**: Kalman-filtered fused objects (world coordinates)
- **`objects`**: Same as fused (backward compatibility)
- **`raw_per_camera`**: Raw observations from each camera (before fusion)
  - Each camera has its own `objects` array (post-mapping, world coords)
  - `metrics.stale_for_fusion`: true if camera data too old
- **`metrics.cams`**: Per-camera detection counts

---

## Dashboard Visualization

### Current Rendering (Post-Patch)
The world map canvas now renders 3 layers:

1. **Cam0 raw detections**: 🟦 Blue squares
2. **Cam1 raw detections**: 🟪 Purple squares
3. **Fused objects**: 🟢 Green/🔵 Cyan/🟠 Orange dots (color by confidence)

### Camera Telemetry Panel
Shows per-camera stats:
- **Detections**: Raw detection count
- **Mapped**: Objects successfully mapped to world coords
- **Kept**: Objects kept after filtering
- **Fusion Status**: OK / STALE

---

## Creating a Local 2-Camera Config

If your second camera appears as `/dev/video2` or `/dev/video4`, create:

**`configs/fusion_health_local_2cam.yaml`**:
```yaml
profile: board_55x40_warehouse_story_v1_fusion

target_fps: 60
object_timeout_s: 1.0

ws_host: 127.0.0.1
ws_port: 8765
metrics_host: 127.0.0.1
metrics_port: 8000

cameras:
  - name: cam0
    device: /dev/video0  # First capture device
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml

  - name: cam1
    device: /dev/video2  # Second capture device (adjust as needed)
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml

exclude_marker_ids: [0, 1, 2, 3]

fusion:
  method: kalman
  meas_sigma: 0.03
  process_sigma: 0.8

record_jsonl: /tmp/fusion_health_local_2cam.jsonl

health:
  enabled: true
```

**Usage**:
```bash
CONFIG=configs/fusion_health_local_2cam.yaml ./tools/mp.sh run-fusion cpu 60 local_2cam
```

---

## Verification Steps

### 1. Check Runner
```bash
# Check if runner is up
curl http://localhost:9000/status | jq .

# Expected: {"service": "metriplane-runner", "status": "idle", ...}
```

### 2. Check Metriplane Stream
```bash
# Check if WebSocket is streaming
wscat -c ws://localhost:8765 | head -n 5

# Or with Python:
python tools/ws_smoke_client.py
```

### 3. Check Health
```bash
curl http://localhost:8000/health | jq .

# Expected: {"overall": "healthy", "components": {"cam0": ..., "cam1": ...}}
```

### 4. Verify Dashboard
Open: http://localhost:8088/web/dashboard/

**Expected Display**:
- ✅ WebSocket: Connected (green)
- ✅ Health: Online (green)
- ✅ Metrics: Online (green)
- ✅ World State canvas showing objects with 3 layers
- ✅ Camera Telemetry showing cam0 and cam1 cards
- ✅ Objects table populated with fused coordinates

---

## Troubleshooting

### WebSocket Not Connected
```bash
# Check if fusion is running
ps aux | grep run_fusion

# Check port
netstat -tln | grep 8765
```

### No Objects Rendered
- Ensure ArUco markers are visible to cameras
- Check camera telemetry shows detections > 0
- Verify markers are NOT in exclude_marker_ids
- Check calibration profiles exist for both cameras

### Camera Shows STALE
- Camera detection rate too low
- Camera timestamps falling behind
- Check camera FPS and system load

### Second Camera Not Working
```bash
# List capture capabilities
v4l2-ctl --list-devices

# Test capture on each device
ffplay /dev/video0  # Should show video
ffplay /dev/video2  # Should show video
ffplay /dev/video1  # May fail if companion node
```

---

## Example Session

```bash
# Terminal 1: Runner
./tools/dashboard_runner.sh

# Terminal 2: Dashboard
python -m http.server 8088

# Terminal 3: Fusion (60s)
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 multicam_test

# Browser: http://localhost:8088/web/dashboard/
# Watch world map populate with:
#   - Blue squares (cam0 raw)
#   - Purple diamonds (cam1 raw)
#   - Green/cyan circles (fused)
```

---

## Dashboard World Map Legend

| Symbol | Layer | Color | Meaning |
|--------|-------|-------|---------|
| ◻ | Cam0 Raw | Blue | Pre-fusion detection from cam0 (hollow square) |
| ◇ | Cam1 Raw | Purple | Pre-fusion detection from cam1 (hollow diamond) |
| △ | Other Raw | Amber | Pre-fusion detection from cam2+ (hollow triangle) |
| ● | Fused | Green | High confidence (>0.8, solid circle) |
| ● | Fused | Cyan | Medium confidence (solid circle) |
| ● | Fused | Orange | Low confidence (<0.5, solid circle) |
| ● | Fused | Red | Stale object (solid circle) |

---

## How to Verify Two-Camera Fusion

When you open the dashboard at http://localhost:8088/web/dashboard/, you should see clear visual indicators that multi-camera fusion is working:

### ✅ Fusion Status Badge (Top of World State)
**Location**: Above the world map canvas

**What to check**:
- **MULTI-CAMERA** (green) = True 2-camera fusion active
  - Indicates: `fused` objects have `sensors >= 2` OR `raw_per_camera` has 2+ active cameras
- **SINGLE-CAMERA** (orange) = Only one camera contributing
  - Indicates: All fused objects have `sensors = 1` or only one active camera in `raw_per_camera`
- **UNKNOWN** (gray) = No data yet

### ✅ World Map Visual Layers
**Location**: Canvas in World State section

**What you should see for true 2-camera fusion**:
1. **Blue hollow squares** = cam0 raw detections (before fusion)
2. **Purple hollow diamonds** = cam1 raw detections (before fusion)
3. **Green/cyan solid circles** = fused objects (after fusion)

**If you only see one shape type**, you have single-camera mode.

**Layer Toggles**: Use checkboxes above canvas to show/hide layers:
- ☑ cam0 raw
- ☑ cam1 raw  
- ☑ fused

### ✅ Fused Object Labels
**Location**: Above each fused object circle on canvas

**What to check**:
- Label format: `id=7 s=2`
  - `id=7`: ArUco marker ID
  - `s=2`: **Sensor count** (number of cameras that detected this object)
  
**If sensor count = 2**, that object was detected by both cameras and fused.

**If sensor count = 1**, only one camera saw it (or other camera's observation was too stale).

### ✅ Camera Telemetry Cards
**Location**: Below world map

**What you should see**:
```
┌─ Camera cam0 ────┐  ┌─ Camera cam1 ────┐
│ Detections: 1    │  │ Detections: 1    │
│ Mapped: 1        │  │ Mapped: 1        │
│ Kept: 1          │  │ Kept: 1          │
│ Fusion: OK       │  │ Fusion: OK       │
└──────────────────┘  └──────────────────┘
```

**Fusion Status**:
- **OK** (green) = Camera data is fresh, contributing to fusion
- **STALE** (orange) = Camera data too old, NOT used for fusion

### ✅ Console Browser DevTools Check
**Location**: Browser Console (F12  → Console tab)

**What to check**:
```javascript
// Type in console:
JSON.parse(lastFrameData)

// Verify structure:
{
  fused: [
    {id: "7", pos_world: [1.5, 2.3, 0], extra: {fusion: {sensors: 2}}}
  ],
  raw_per_camera: [
    {camera_id: "cam0", objects: [...], metrics: {stale_for_fusion: false}},
    {camera_id: "cam1", objects: [...], metrics: {stale_for_fusion: false}}
  ]
}
```

**Key Indicators of Success**:
1. `raw_per_camera.length === 2` (both cameras active)
2. `raw_per_camera[0].metrics.stale_for_fusion === false` (cam0 fresh)
3. `raw_per_camera[1].metrics.stale_for_fusion === false` (cam1 fresh)
4. `fused[0].extra.fusion.sensors === 2` (object detected by both)

### ✅ WebSocket Frame Inspection
**Check raw WebSocket data**:
```bash
wscat -c ws://localhost:8765 | jq '.raw_per_camera | length'
# Expected: 2 (for two cameras)

wscat -c ws://localhost:8765 | jq '.fused[0].extra.fusion.sensors'
# Expected: 2 (if both cameras see the object)
```

### ❌ Common False Positives

**Scenario 1: Single camera, but UI looks fine**
- Dashboard shows cam0 detections
- Fusion Status = SINGLE-CAMERA (orange)
- Camera Telemetry shows only cam0
- **Not true 2-camera fusion**

**Scenario 2: Two cameras listed, but one is STALE**
- Camera Telemetry shows cam0: OK, cam1: STALE
- Fused objects show `s=1` (only cam0 contributing)
- Fusion Status may still be SINGLE-CAMERA
- **Degraded mode - only one camera usable**

**Scenario 3: Both cameras active, but seeing different markers**
- cam0 sees marker ID 7
- cam1 sees marker ID 8 (different object)
- Fused objects each show `s=1`
- **Cameras work, but no overlap → no multi-sensor fusion**

### ✅ Definitive Success Criteria

**YOU HAVE TRUE 2-CAMERA FUSION IF**:
1. ✅ Fusion Status badge shows **MULTI-CAMERA** (green)
2. ✅ Camera Telemetry shows 2 cards, both with Fusion: **OK**
3. ✅ At least one fused object label shows **s=2** or higher
4. ✅ World map shows blue squares (cam0) + purple diamonds (cam1) near same location
5. ✅ WebSocket frame `raw_per_camera.length === 2` with both non-stale

---

## Notes

- **Current Hardware Limitation**: Local /dev/video1 is likely a companion node, not capture-capable. True 2-camera fusion requires second capture device (typically /dev/video2 or /dev/video4).
- **Single Camera Works**: Use `configs/fusion_health_cam0.yaml` for single-camera testing.
- **Fusion Method**: Kalman filter provides velocity estimation and temporal smoothing.
- **Evidence Recording**: Sessions automatically recorded to `/tmp/*.jsonl` for replay.
- **Dashboard**: Works offline (graceful degradation) - copy-only mode if runner unavailable.

---

**Generated**: 2026-04-27  
**Contact**: See README.md for project details
