<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane Multi-Camera Calibration Runbook

**Purpose**: Re-calibrate planar mapping for multi-camera fusion after cameras have been physically moved

**Last Updated**: 2026-04-27

---

## Problem Symptoms

- ✗ World map is unstable/flashing
- ✗ Object positions are incorrect
- ✗ Camera alignment is poor
- ✗ Multi-camera fusion showing large discrepancies

**Root Cause**: Cameras have moved → homography matrices are stale → pixel-to-world mapping is incorrect

---

## Prerequisites

### Required Hardware
- **Physical ArUco board**: 55cm × 40cm with corner markers
  - Marker ID 0: at (0.0, 0.0) m
  - Marker ID 1: at (0.0, 0.4) m  
  - Marker ID 2: at (0.55, 0.0) m
  - Marker ID 3: at (0.55, 0.4) m
- **Board positioning**: Must be flat, rigid, fully visible to both cameras
- **Lighting**: Good, even lighting; avoid glare/shadows
- **Camera stability**: Cameras must be physically stable during calibration

### Required Software
```bash
cd <repo>
source ~/metriplane-venv/bin/activate

# Verify dependencies
python -c "import cv2, numpy, yaml; print('✓ Dependencies OK')"
```

### Calibration Profile
This runbook uses: **`board_55x40_warehouse_story_v1_fusion`**

**Location**: `calib/profiles/board_55x40_warehouse_story_v1_fusion/`
```
├── anchors.yaml          # Corner marker world coordinates
├── cam0/
│   ├── mapping_raw.yaml  # Will be regenerated
│   └── camera.yaml       # Intrinsics (optional, if exists)
└── cam1/
    ├── mapping_raw.yaml  # Will be regenerated
    └── camera.yaml       # Intrinsics (optional)
```

---

## Step 1: Identify Camera Device Paths

Find which `/dev/video<N>` devices are capture-capable:

```bash
# List all video devices
ls -la /dev/video*

# Test OpenCV capture on each device
python -c "import cv2; cap = cv2.VideoCapture(0); print('video0:', cap.isOpened()); cap.release()"
python -c "import cv2; cap = cv2.VideoCapture(1); print('video1:', cap.isOpened()); cap.release()"
python -c "import cv2; cap = cv2.VideoCapture(2); print('video2:', cap.isOpened()); cap.release()"

# Stable by-id paths (recommended)
ls -la /dev/v4l/by-id/
```

**Expected Result**:
- **cam0**: `/dev/video0` → OpenCV index = 0
- **cam1**: `/dev/video2` or `/dev/video4` → OpenCV index = 2 or 4

**Note**: `/dev/video1` is often a companion node (metadata/audio) and cannot be opened for capture.

---

## Step 2: Position Calibration Board

**Setup**:
1. Place ArUco board flat on table/floor
2. Ensure all 4 corner markers (IDs 0,1,2,3) are visible
3. Position cameras so both can see all 4 corners simultaneously
4. Check lighting - markers should be clearly visible (no glare, good contrast)

**Quick Visual Check**:
```bash
# Preview cam0 (raw feed, no mapping)
python -c "import cv2; cap = cv2.VideoCapture(0); ret, frame = cap.read(); cv2.imwrite('/tmp/cam0_preview.jpg', frame); cap.release(); print('Saved /tmp/cam0_preview.jpg')"

# Preview cam1 (adjust index as needed)
python -c "import cv2; cap = cv2.VideoCapture(2); ret, frame = cap.read(); cv2.imwrite('/tmp/cam1_preview.jpg', frame); cap.release(); print('Saved /tmp/cam1_preview.jpg')"

# View saved images
eog /tmp/cam0_preview.jpg &
eog /tmp/cam1_preview.jpg &
```

**Verify**: All 4 corner markers visible in both images.

---

## IMPORTANT: OpenCV GUI Issue (Headless Environments)

**Problem**: If you get this error:
```
cv2.error: The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support.
```

Your OpenCV installation lacks GUI support. **Use `--no-preview` flag** for headless calibration:

```bash
# Headless calibration for cam0 (with timeout and max-frames protection)
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM0_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --no-preview \
  --no-intrinsics \
  --timeout-s 30 \
  --max-frames 600
```

**How it works** (headless mode):
- No GUI window opens
- Tool captures frames continuously
- **Progress printed every 30 frames** showing detected marker IDs
- **Automatically writes calibration** when all 4+ anchors detected
- **Timeout protection**: Exits after 30s (configurable with --timeout-s)
- **Frame limit**: Stops after 600 frames (configurable with --max-frames)
- **Diagnostic output**: Shows detailed error info if calibration fails

**New Flags**:
- `--timeout-s N`: Maximum time to wait (default: 30 seconds)
- `--max-frames N`: Maximum frames to capture (default: 600)
- `--no-intrinsics`: Disable intrinsics (recommended for headless)

---

## Step 3: Calibrate cam0

**Run Interactive Calibration Tool**:
```bash
cd <repo>
source ~/metriplane-venv/bin/activate

python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera 0 \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
```

**What You'll See**:
- OpenCV window showing live camera feed
- Green dots on detected ArUco markers
- Text: `anchors_seen=4/4 (press 'w' to write when >=4 seen, 'q' to quit)`

**Actions**:
1. **Wait** until text shows `anchors_seen=4/4`
2. **Press 'w'** to write calibration
3. **Check output**: `anchor_rmse=<value>` should be very small (ideally < 1e-6)

**Expected Output**:
```
[calib_plane] wrote calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml  rmse=0.000000 meters
```

**If RMSE > 0.01**:
- Board is not flat
- Markers are occluded/damaged
- Lighting is poor

---

## Step 4: Calibrate cam1

**Important**: Determine correct camera index first!

```bash
# If your second camera is /dev/video2:
CAMERA_INDEX=2

# If your second camera is /dev/video4:
CAMERA_INDEX=4

# Run calibration
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAMERA_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml
```

**Actions**: Same as cam0 - press 'w' when 4/4 anchors seen.

**Expected Output**:
```
[calib_plane] wrote calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml  rmse=0.000000 meters
```

---

## Step 5: Verify Cross-Camera Alignment

Run the alignment diagnostic tool to check if both cameras agree on world coordinates:

```bash
python tools/debug_alignment.py \
  --cam0 0 \
  --cam1 $CAMERA_INDEX \
  --mapping-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --mapping-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --intrinsics-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --intrinsics-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/camera.yaml \
  --anchors calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml
```

**Replace** `$CAMERA_INDEX` with 2 or 4 based on your hardware.

**Note**: If camera.yaml doesn't exist for a camera, you can omit that intrinsics argument or specify a dummy path.

**What It Does**:
- Captures frames from both cameras simultaneously
- Applies calibrated mappings
- Compares world coordinates for same marker IDs
- Reports cross-camera distance errors

**Expected Output**:
```
=== CROSS-CAMERA CONSISTENCY (using best per-cam pipeline) ===
overlap ids=[0, 1, 2, 3, 7]
mean_dist=0.0015m  max_dist=0.0032m

=== PER-MARKER CROSS-CAMERA COMPARISON ===
ID     Cam0_X   Cam0_Y   Cam1_X   Cam1_Y   Dist_m Type      
--------------------------------------------------------------------
0      0.0000   0.0000   0.0001   0.0001   0.0001 ANCHOR    
1      0.0000   0.4000   0.0001   0.4001   0.0001 ANCHOR    
2      0.5500   0.0000   0.5501   0.0001   0.0001 ANCHOR    
3      0.5500   0.4000   0.5501   0.4001   0.0001 ANCHOR    
7      1.5234   2.3456   1.5239   2.3461   0.0007 NON-ANCHOR

non-anchor summary: mean_dist=0.0007m  max_dist=0.0007m

=== VERDICT (heuristics) ===
(no warnings)
Done.
```

**New Feature - Per-Marker Table**:
- Shows world coordinates from both cameras for each overlapping marker
- **ANCHOR** markers (IDs 0,1,2,3) listed first
- **NON-ANCHOR** markers (e.g. ID 7 for robot) listed separately
- **Distance** column shows cross-camera disagreement
- **⚠ Warning** if any non-anchor marker distance > 0.02m

**Good Alignment**:
- ✅ `mean_dist < 0.005 m` (< 5mm)
- ✅ `max_dist < 0.010 m` (< 10mm)
- ✅ No warnings about size mismatch or double-undistort

**Poor Alignment**:
- ✗ `mean_dist > 0.020 m` → re-calibrate
- ✗ Warnings about intrinsics size mismatch → verify camera resolution
- ✗ "DOUBLE-UNDISTORT" warning → check if intrinsics are being applied twice

---

## Step 6: Preview Live Mapping (Optional)

**Single Camera Preview**:
```bash
# Preview cam0 with world overlay
python tools/preview_world_overlay.py \
  --camera 0 \
  --profile board_55x40_warehouse_story_v1_fusion

# Preview cam1 with world overlay
python tools/preview_world_overlay.py \
  --camera $CAMERA_INDEX \
  --profile board_55x40_warehouse_story_v1_fusion
```

**What You'll See**:
- Live camera feed
- Detected markers with world coordinates overlaid
- Positions should be stable and accurate

**Press 'q' to quit preview.**

---

## Step 7: Run Multi-Camera Fusion

Test the updated calibration with live fusion:

```bash
# Update active profile (if needed)
echo "profile: board_55x40_warehouse_story_v1_fusion" > calib/active_profile.yaml

# Run 2-camera fusion for 60 seconds
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 test_recalibrated
```

**Adjust Camera Devices in Config (if needed)**:
If your cam1 is on /dev/video2, temporarily edit `configs/fusion_health.yaml`:
```yaml
cameras:
  - name: cam0
    device: /dev/video0
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
  - name: cam1
    device: /dev/video2  # or /dev/video4
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml
```

---

## Step 8: Verify in Dashboard

**Start Dashboard**:
```bash
# Terminal 1: Dashboard server
python -m http.server 8088

# Terminal 2: Fusion (if not already running)
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 verify_calib

# Browser: http://localhost:8088/web/dashboard/
```

**What to Check**:

### ✅ Fusion Status Badge
- Should show **MULTI-CAMERA** (green)
- If SINGLE-CAMERA (orange), only one camera is contributing

### ✅ World Map Canvas
- **Blue squares** (cam0 raw) and **purple diamonds** (cam1 raw) should be **co-located**
- **Solid circles** (fused) should be stable, not jumping
- Objects should have `s=2` (sensor count = 2)

### ✅ Camera Telemetry
- Both cam0 and cam1 cards visible
- Both show Fusion: **OK** (green)
- Detections > 0 for both cameras

### ✅ Stability Test
- Move ArUco marker ID 7 slowly across board
- World position should update smoothly
- No sudden jumps or flickering
- Both blue square and purple diamond should track together

**Good Calibration Indicators**:
- Raw camera detections (squares/diamonds) overlap within ~5mm
- Fused position (circle) is stable and smooth
- Objects don't "jump" between frames
- Cross-camera distance is minimal

**Bad Calibration Indicators**:
- ✗ Raw detections from cam0 and cam1 are offset by >2cm
- ✗ Objects flicker/jump between frames
- ✗ Fused objects show `s=1` (only one camera seeing them)
- ✗ Camera telemetry shows STALE fusion status

---

## Troubleshooting

### Issue: "anchors_seen=0/4" - No markers detected

**Solutions**:
```bash
# Check if camera is opening
python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened()); cap.release()"

# Check ArUco detection manually
python -c "
import cv2
from metriplane.backends.aruco_backend import ArUcoBackend
cap = cv2.VideoCapture(0)
backend = ArUcoBackend()
ret, frame = cap.read()
dets = backend.detect(type('F', (), {'ts_cam_read': 0, 'image': frame})())
print(f'Detected: {len(dets)} markers')
print(f'IDs: {[int(d[0]) for d in dets]}')
cap.release()
"
```

**Checklist**:
- ☐ Board is in camera view
- ☐ Markers are printed clearly (not blurry/damaged)
- ☐ Lighting is adequate (not under/overexposed)
- ☐ Correct ArUco dictionary (default: 6x6_250)

### Issue: "anchors_seen=3/4" - One marker missing

**Solutions**:
- Reposition camera or board to include all 4 corners
- Check if marker is occluded/damaged
- Improve lighting on missing corner

### Issue: High RMSE (> 0.001 m)

**Causes**:
- Board is not flat (warped/bent)
- Markers are not precisely positioned
- Camera lens distortion (consider using intrinsics)

**Solutions**:
```bash
# Try with intrinsics (if camera.yaml exists)
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera 0 \
  --intrinsics calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
```

### Issue: Cross-camera distance > 0.02m

**From debug_alignment.py output**:
```
mean_dist=0.0450m  max_dist=0.0840m  # BAD!
```

**Solutions**:
1. **Re-calibrate both cameras** - one may have failed
2. **Check marker ID overlap** - both cameras must see same markers
3. **Verify camera indices** - ensure --camera values are correct
4. **Check intrinsics** - may be swapped between cam0/cam1

### Issue: Intrinsics Size Mismatch Warning

```
cam0: INTRINSICS SIZE MISMATCH -> calibrate intrinsics at the exact runtime resolution
```

**Solution**: Either:
1. **Ignore intrinsics** (use raw pixel mapping):
   ```bash
   python tools/calibrate_planar_homography.py \
     --profile board_55x40_warehouse_story_v1_fusion \
     --camera 0 \
     --no-undistort \
     --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
   ```

2. **Re-calibrate intrinsics** at correct resolution:
   ```bash
   python tools/calibrate_intrinsics_chessboard.py \
     --camera 0 \
     --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml
   ```

### Issue: Wrong Camera Index

**Symptom**: Camera preview is black or shows wrong camera

**Solution**:
```bash
# List v4l devices with capabilities
v4l2-ctl --list-devices

# Test each index
for i in 0 1 2 3 4; do
  python -c "import cv2; cap = cv2.VideoCapture($i); ok = cap.isOpened(); cap.release(); print(f'video{$i}: {ok}')"
done
```

---

## Complete Re-Calibration Procedure

### STEP 1: Setup Environment
```bash
cd <repo>
source ~/metriplane-venv/bin/activate

# Set camera indices (adjust based on your hardware)
export CAM0_INDEX=0
export CAM1_INDEX=2  # or 4, depending on your system
```

### STEP 2: Backup Old Calibration (Optional but Recommended)
```bash
cp calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
   calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml.backup

cp calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
   calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml.backup
```

### STEP 3: Calibrate cam0

**For headless (no GUI) environments - RECOMMENDED:**
```bash
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM0_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --no-preview \
  --no-intrinsics \
  --timeout-s 30 \
  --max-frames 600
```

**What You'll See** (headless mode):
```
[calib_plane] Headless mode: max_frames=600, timeout=30s
[calib_plane] Waiting for anchors [0, 1, 2, 3]...
[calib_plane] frame=30 elapsed=1.2s detected_ids=[0, 1, 2, 3] anchors_seen=4/4
[calib_plane] All 4 anchors detected! Auto-writing calibration...
[calib_plane] wrote calib/profiles/.../cam0/mapping_raw.yaml  rmse=0.000001 meters
```

**Key Behavior**:
- **No keypress required** - automatically writes when all anchors detected
- Progress printed every 30 frames
- Exits after 30s timeout or 600 frames if unsuccessful

**For GUI environments** (if you have X11/display):
```bash
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM0_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
```

**Interactive Steps** (GUI mode):
1. OpenCV window opens showing camera feed
2. Move board/camera until `anchors_seen=4/4`
3. **Press 'w'** to write calibration
4. Check `anchor_rmse` is very small (< 0.001)
5. Window closes automatically

### STEP 4: Calibrate cam1

**For headless (no GUI) environments - RECOMMENDED:**
```bash
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM1_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --no-preview \
  --no-intrinsics \
  --timeout-s 30 \
  --max-frames 600
```

**Expected Output**: Same as cam0 - auto-writes when all anchors detected, no keypress needed

### STEP 5: Verify Cross-Camera Alignment
```bash
python tools/debug_alignment.py \
  --cam0 $CAM0_INDEX \
  --cam1 $CAM1_INDEX \
  --mapping-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --mapping-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --intrinsics-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --intrinsics-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/camera.yaml \
  --anchors calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml
```

**Expected Output**:
```
=== CROSS-CAMERA CONSISTENCY ===
overlap ids=[0, 1, 2, 3, ...]
mean_dist=0.0012m  max_dist=0.0028m
```

**Quality Thresholds**:
- ✅ **Excellent**: mean_dist < 0.003m (3mm)
- ✅ **Good**: mean_dist < 0.010m (10mm)
- ⚠️ **Acceptable**: mean_dist < 0.020m (20mm)
- ✗ **Poor**: mean_dist > 0.020m → **re-calibrate**

### STEP 6: Test with Live Preview
```bash
# Preview cam0 with calibrated mapping
python tools/preview_world_overlay.py \
  --camera $CAM0_INDEX \
  --profile board_55x40_warehouse_story_v1_fusion

# Press 'q' to quit, then preview cam1
python tools/preview_world_overlay.py \
  --camera $CAM1_INDEX \
  --profile board_55x40_warehouse_story_v1_fusion
```

**Verify**:
- World coordinates are displayed on markers
- Positions are stable (not flickering)
- Coordinates match expected values (within a few mm)

### STEP 7: Update Fusion Config (if needed)
If your cam1 device changed, update the config:

**Edit `configs/fusion_health.yaml`**:
```yaml
cameras:
  - name: cam0
    device: /dev/video0  # or stable by-id path
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml

  - name: cam1
    device: /dev/video2  # adjust to your actual device
    mapping_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml
```

### STEP 8: Run Multi-Camera Fusion
```bash
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 test_recalibrated
```

**Expected Behavior**:
- No errors about missing calibration files
- Both cameras streaming (check terminal output)
- WebSocket publishing on port 8765
- Health endpoint available on port 8000

### STEP 9: Verify in Dashboard
```bash
# Terminal 1: Dashboard (if not already running)
python -m http.server 8088

# Browser: http://localhost:8088/web/dashboard/
```

**Dashboard Verification Checklist**:
- ✅ Fusion Status: **MULTI-CAMERA** (green badge)
- ✅ Camera Telemetry: 2 cards (cam0, cam1), both show Fusion: **OK**
- ✅ World Map: Blue squares and purple diamonds co-located (< 5mm apart)
- ✅ Fused objects: Labeled with `s=2` (sensor count)
- ✅ Objects move smoothly, no flickering/jumping

---

## Reference: Output File Structure

### anchors.yaml (Profile-Level)
```yaml
anchors:
  - id: 0
    world_xy: [0.000, 0.000]
  - id: 1
    world_xy: [0.000, 0.400]
  - id: 2
    world_xy: [0.550, 0.000]
  - id: 3
    world_xy: [0.550, 0.400]
```

### mapping_raw.yaml (Per-Camera)
```yaml
units: meters
homography:  # 3x3 matrix for pixel→world transform
- [a, b, c]
- [d, e, f]
- [g, h, 1.0]
type: homography_v1
computed_at_unix: 1768582061.99
anchors_file: calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml
anchors_used: [0, 1, 2, 3]
anchors_seen: 4
anchor_rmse: 9.424e-09  # Should be very small!
intrinsics_file: null
undistort_points: false
profile: board_55x40_warehouse_story_v1_fusion
```

---

## Quick Command Reference

```bash
# Environment setup
cd <repo>
source ~/metriplane-venv/bin/activate
export CAM0_INDEX=0
export CAM1_INDEX=2

# Full re-calibration sequence (headless mode with auto-write)
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM0_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --no-preview --no-intrinsics --timeout-s 30 --max-frames 600

python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM1_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --no-preview --no-intrinsics --timeout-s 30 --max-frames 600

# Verify alignment
python tools/debug_alignment.py \
  --cam0 $CAM0_INDEX --cam1 $CAM1_INDEX \
  --mapping-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --mapping-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --intrinsics-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --intrinsics-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/camera.yaml \
  --anchors calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml

# Test with fusion
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 test_recalibrated

# View in dashboard
python -m http.server 8088
# Open: http://localhost:8088/web/dashboard/
```

---

## FAQ

**Q: Do I need to calibrate intrinsics first?**  
A: Not required. The `--no-undistort` flag disables intrinsics. Raw pixel mapping works for most setups if cameras have minimal distortion.

**Q: How often should I re-calibrate?**  
A: Whenever cameras are physically moved or alignment degrades.

**Q: Can I calibrate one camera at a time?**  
A: Yes! Calibrate cam0, test it, then calibrate cam1. Each camera has independent mapping file.

**Q: What if my markers are different IDs?**  
A: Edit `anchors.yaml` to match your physical board marker IDs and world positions.

**Q: Which mapping file does fusion use?**  
A: Check your config YAML under `cameras[].mapping_file` - should point to `mapping_raw.yaml` in each cam's profile directory.

**Q: Can I use a different profile?**  
A: Yes! Replace `board_55x40_warehouse_story_v1_fusion` with your profile name. Create profile directory structure if needed.

---

**Generated**: 2026-04-27  
**See also**: docs/dashboard_multicam_runbook.md for running multi-camera fusion
