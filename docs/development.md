<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Development Guide

**Purpose**: Local developer workflow and environment setup for Metriplane

**Last Updated**: 2026-04-27

---

## Quick Start

```bash
# Clone and setup
cd <repo>
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Validate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m metriplane.cli doctor
```

---

## One-command Local Stack

After installation, bring up the full local stack with a single command:

```bash
# Full local stack: runner and dashboard. Runtime sessions are started
# intentionally from Setup, Run, or with --live.
metriplane start --open

# Start an immediate camera-free runtime stream, if you explicitly want one
metriplane start --live --open

# Camera-backed runtime, after setup has valid cameras/profile
metriplane start --live --config configs/fusion_health_300fps.yaml --open

# Open directly to the setup wizard
metriplane start --operator

# Status
metriplane status

# Stop everything
metriplane stop
```

### What it starts

| Process | Port | Description |
|---------|------|-------------|
| Dashboard runner | 9000 | REST API for operator commands |
| Static dashboard server | 8088 | Serves `web/dashboard/` and `evidence/` from repo root |
| Runtime stream | 8000/8765 | Metrics, health, WebSocket stream; starts from Setup, Run, or `--live` |

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--live` | off | Start runtime stream immediately |
| `--no-live` | on | Start only dashboard and runner |
| `--backend cpu\|gpu` | cpu | Fusion compute backend |
| `--config PATH` | `configs/local_demo_replay.yaml` | Runtime config |
| `--duration-s N` | 7200 | Stop camera-fusion runtime after N seconds |
| `--run-id TEXT` | auto | Override run ID |
| `--dashboard-port N` | 8088 | Web server port |
| `--runner-port N` | 9000 | Runner API port |
| `--runs-dir PATH` | `~/metriplane-runs` | Runs base directory |
| `--open/--no-open` | open | Open browser automatically |
| `--operator` | off | Open operator.html |

Launcher state lives in `~/.cache/metriplane/launcher-state.json`.  
Logs live in `~/metriplane-runs/_launcher/<timestamp>/`.

---

## Python Environment Setup

### 1. Create Virtual Environment

**Both patterns are supported**:

**In-project environment**: `.venv` in project root (gitignored):
```bash
cd <repo>
python3 -m venv .venv
```

**External environment**: Named venv outside project (known-good workflow):
```bash
python3 -m venv ~/metriplane-venv
```

**Note**: Current known-good workflow uses `~/metriplane-venv`. Either pattern works.

### 2. Activate Environment

```bash
# In-project venv
source .venv/bin/activate

# External venv (known-good)
source ~/metriplane-venv/bin/activate
```

Your prompt should show `(.venv)` or `(metriplane-venv)`.

### 3. Install Metriplane in Editable Mode

```bash
pip install -e .
```

**Benefits of `-e` (editable install)**:
- Code changes immediately available (no reinstall needed)
- Preserves git working directory structure
- Development-friendly workflow

**Verification**:
```bash
python -c "import metriplane; print(metriplane.__file__)"
# Should point to your project directory, not site-packages
```

### 4. Install Development Dependencies (Optional)

```bash
pip install pytest black mypy
```

---

## Testing

### pytest Command (with ROS 2 Workaround)

**Issue**: ROS 2 `launch_testing` pytest plugin conflicts with Metriplane's test suite.

**Workaround**: Disable plugin autoload:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

**What this does**:
- Disables `ros2.launch_testing.pytest.hooks` plugin
- Allows Metriplane tests to run cleanly
- Prevents `AttributeError: 'module' object has no attribute 'path'` errors

**Run specific test file**:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_zone_analytics.py -v
```

**Run with coverage**:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --cov=metriplane --cov-report=term-missing
```

### System Health Check

```bash
python -m metriplane.cli doctor
```

**Checks**:
- Python version
- metriplane import successful
- Git commit hash
- tools/mp.sh exists
- Config files exist
- Ports available (8000, 8001, 8765)
- Camera devices detected
- GPU availability (if CUDA installed)

**Expected Output**:
```
Metriplane Doctor - Environment Check
==================================================
✅ PASS: Python 3.12.3
✅ PASS: metriplane import successful
✅ PASS: Git commit 2240729
✅ PASS: tools/mp.sh exists
✅ PASS: configs/fusion_health_300fps.yaml exists
✅ PASS: Ports 8000, 8001, 8765 available
✅ PASS: Camera devices found: /dev/video0, /dev/video2
✅ PASS: GPU available: NVIDIA GeForce RTX 5070 Ti
==================================================
Summary: 8 passed, 0 warnings, 0 failed
```

---

## Dashboard Development

### Start Dashboard Runner Service

```bash
./tools/dashboard_runner.sh
```

**What it does**:
- Starts runner service on port 9000
- Enables "Run" buttons in dashboard
- Allows command execution from web UI

**Check status**:
```bash
curl http://localhost:9000/status
# {"status": "idle", "running_jobs": 0}
```

### Serve Dashboard Web App

**Important**: Serve from repo root to allow evidence/manifest.csv loading:

```bash
cd <repo>
python -m http.server 8088
```

**Access**: http://localhost:8088/web/dashboard/

**Why serve from root**:
- Dashboard tries to load: `../../evidence/manifest.csv` and `evidence/manifest.csv`
- Serving from root makes both paths accessible
- Evidence manifest will display properly

**Alternative ports**:
- 8088 (recommended, avoids common conflicts)
- 8080 (common alternative)
- 3000 (dev server convention)

### Dashboard Features

**V1 Features**:
- Real-time WebSocket telemetry (port 8765)
- Health endpoint polling (port 8000)
- Metrics endpoint polling (port 8000)
- World state visualization with trails
- Evidence manifest display
- Copy-paste commands

**V2 Features** (with runner service):
- One-click command execution
- Real-time job output streaming
- Job cancellation
- Command history

---

## Camera Development

### List Camera Devices

**By-ID paths** (stable across reboots):
```bash
ls -lah /dev/v4l/by-id/
```

**Output example**:
```
usb-046d_HD_Pro_Webcam_C920_12345678-video-index0 -> ../../video0
usb-046d_HD_Pro_Webcam_C920_87654321-video-index0 -> ../../video2
```

**Direct device nodes**:
```bash
ls -lah /dev/video*
```

**Note**: `/dev/video1`, `/dev/video3` are often metadata nodes (not capture-capable).

### OpenCV Capture Test

```bash
python -c "
import cv2
cap = cv2.VideoCapture(0)
opened = cap.isOpened()
ret, frame = cap.read() if opened else (False, None)
shape = frame.shape if ret else None
cap.release()
print(f'index 0: opened={opened} read={ret} shape={shape}')
"
```

**Test all indices**:
```bash
for i in 0 2 4; do
  python -c "import cv2; cap = cv2.VideoCapture($i); print(f'video{$i}: opened={cap.isOpened()}'); cap.release()"
done
```

### Camera Resolution Check

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

**Common resolutions**:
- 640×480 (VGA) - most compatible
- 1280×720 (HD) - good balance
- 1920×1080 (Full HD) - high detail

---

## Configuration Management

### Local Config Pattern

**Gitignored**: All `*_local.yaml` configs are ignored by git.

```bash
# Create local config
cp configs/examples/config.m8_fusion.yaml configs/examples/config.m8_fusion_local.yaml

# Edit for your hardware
vim configs/examples/config.m8_fusion_local.yaml
# Change camera devices: /dev/video0, /dev/video2
# Adjust calibration profile paths
# Set logging levels

# Use local config
CONFIG=configs/examples/config.m8_fusion_local.yaml ./tools/mp.sh run-fusion cpu 60 dev_test
```

**Benefits**:
- Experiment without affecting committed configs
- Machine-specific settings (camera indices, paths)
- Safe for sensitive data (API keys, credentials)

### Config Hierarchy

1. **Committed configs**: `configs/*.yaml` (shared defaults)
2. **Local overrides**: `configs/*_local.yaml` (gitignored)
3. **Environment variables**: `CONFIG=path/to/config.yaml`
4. **CLI arguments**: `--config path/to/config.yaml`

---

## Calibration Development

### Headless Calibration

**Problem**: SSH sessions without X11 forwarding can't use OpenCV GUI.

**Solution**: Use `--no-preview` mode with auto-write:

```bash
# Calibrate cam0 (headless)
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera 0 \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --no-preview \
  --no-intrinsics \
  --timeout-s 30 \
  --max-frames 600
```

**Flags**:
- `--no-preview`: Disable OpenCV window (headless mode)
- `--no-intrinsics`: Skip intrinsics correction (raw pixels)
- `--timeout-s 30`: Exit after 30 seconds if unsuccessful
- `--max-frames 600`: Limit frame capture

**Progress Output**:
```
[calib_plane] Headless mode: max_frames=600, timeout=30s
[calib_plane] Waiting for anchors [0, 1, 2, 3]...
[calib_plane] frame=30 elapsed=1.2s detected_ids=[0, 1, 2, 3] anchors_seen=4/4
[calib_plane] All 4 anchors detected! Auto-writing calibration...
[calib_plane] wrote calib/.../cam0/mapping_raw.yaml  rmse=0.000001 meters
```

### Verify Cross-Camera Alignment

```bash
python tools/debug_alignment.py \
  --cam0 0 \
  --cam1 2 \
  --mapping-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --mapping-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --intrinsics-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --intrinsics-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/camera.yaml \
  --anchors calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml
```

**What it checks**:
- Per-camera anchor RMSE
- Cross-camera world coordinate agreement
- Per-marker disagreement table (anchors + non-anchors)
- Intrinsics size mismatches
- Double-undistort detection
- Swapped intrinsics detection

**Good Calibration**:
```
=== PER-MARKER CROSS-CAMERA COMPARISON ===
ID     Cam0_X   Cam0_Y   Cam1_X   Cam1_Y   Dist_m Type      
--------------------------------------------------------------------
0      0.0000   0.0000   0.0001   0.0001   0.0001 ANCHOR    
7      1.5234   2.3456   1.5236   2.3458   0.0003 NON-ANCHOR

non-anchor summary: mean_dist=0.0003m  max_dist=0.0003m
```

**Poor Calibration**:
```
7      1.5234   2.3456   1.5459   2.3681   0.0289 NON-ANCHOR ⚠

⚠ WARNING: Large disagreement on non-anchor markers:
  Marker ID 7: 0.0289m (>0.02m threshold)
```

---

## Validation Checklist

### Before Committing Code

Run all validation steps:

```bash
# 1. Python tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q

# 2. System health
python -m metriplane.cli doctor

# 3. Shell syntax checks
bash -n tools/mp.sh
bash -n tools/dashboard_runner.sh

# 4. Optional: Type checking
mypy metriplane --ignore-missing-imports

# 5. Optional: Code formatting
black metriplane tests --check
```

**All must pass** before pushing to main branch.

### CI/CD Integration

**.github/workflows/ci.yml** runs automatically on push:
- pytest with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
- metriplane import check
- doctor check
- bash syntax validation

**.github/workflows/docker-smoke.yml** is manual-only (workflow_dispatch).

**Local pre-push check**:
```bash
# Mimics CI pipeline
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q && \
python -m metriplane.cli doctor && \
bash -n tools/mp.sh && \
bash -n tools/dashboard_runner.sh && \
echo "✅ Ready to push"
```

---

## Common Workflows

### 1. Add New Feature

```bash
# Create feature branch
git checkout -b feature/new-detector

# Make changes
vim metriplane/backends/new_detector.py

# Add tests
vim tests/test_new_detector.py

# Run tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_new_detector.py -v

# Validate
python -m metriplane.cli doctor
bash -n tools/mp.sh

# Commit
git add metriplane/backends/new_detector.py tests/test_new_detector.py
git commit -m "feat: add new detector backend"
```

### 2. Debug Live Pipeline

```bash
# Terminal 1: Run fusion with logging
CONFIG=configs/fusion_health_local.yaml ./tools/mp.sh run-fusion cpu 60 debug_session

# Terminal 2: Monitor WebSocket
websocat ws://localhost:8765

# Terminal 3: Check health
curl http://localhost:8000/health | jq

# Terminal 4: Dashboard
python -m http.server 8088
# Open browser: http://localhost:8088/web/dashboard/
```

### 3. Profile Performance

```bash
# Run with profiling
python -m cProfile -o output.prof metriplane/run_fusion.py

# Analyze results
python -m pstats output.prof
> sort cumtime
> stats 20
```

### 4. Re-Calibrate After Camera Move

```bash
# Set environment
export CAM0_INDEX=0
export CAM1_INDEX=2

# Calibrate both cameras (headless)
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM0_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --no-preview --no-intrinsics --timeout-s 30

python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera $CAM1_INDEX \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --no-preview --no-intrinsics --timeout-s 30

# Verify alignment
python tools/debug_alignment.py \
  --cam0 $CAM0_INDEX \
  --cam1 $CAM1_INDEX \
  --mapping-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml \
  --mapping-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/mapping_raw.yaml \
  --intrinsics-cam0 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/camera.yaml \
  --intrinsics-cam1 calib/profiles/board_55x40_warehouse_story_v1_fusion/cam1/camera.yaml \
  --anchors calib/profiles/board_55x40_warehouse_story_v1_fusion/anchors.yaml

# Test with fusion
CONFIG=configs/fusion_health_local.yaml ./tools/mp.sh run-fusion cpu 60 test_calibration
```

---

## Troubleshooting

### Issue: pytest AttributeError with ROS 2

**Error**:
```
AttributeError: 'module' object has no attribute 'path'
```

**Solution**: Use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`

**Why**: ROS 2 `launch_testing` pytest plugin conflicts with Metriplane tests.

### Issue: Camera Not Opening

**Check device availability**:
```bash
ls -lah /dev/video*
v4l2-ctl --list-devices
```

**Test with OpenCV**:
```bash
python -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened()); cap.release()"
```

**Common fixes**:
1. Wrong index (try 0, 2, 4 instead of 1, 3, 5)
2. Device in use by another process
3. Permissions issue: `sudo usermod -a -G video $USER` (then re-login)

### Issue: Dashboard Not Loading

**Check ports**:
```bash
# Dashboard server
lsof -i :8088

# WebSocket server
lsof -i :8765

# Health/Metrics API
lsof -i :8000
```

**Restart services**:
```bash
# Kill old processes
pkill -f "http.server 8088"
pkill -f "metriplane"

# Restart
CONFIG=configs/fusion_health.yaml ./tools/mp.sh run-fusion cpu 60 test &
python -m http.server 8088 &
```

### Issue: Import Error for metriplane

**Verify editable install**:
```bash
pip show metriplane
# Location should point to your project directory
```

**Reinstall if needed**:
```bash
pip uninstall metriplane
pip install -e .
```

### Issue: CalibrationProfile Not Found

**Check active profile**:
```bash
cat calib/active_profile.yaml
# profile: board_55x40_warehouse_story_v1_fusion
```

**Verify profile directory exists**:
```bash
ls -lah calib/profiles/board_55x40_warehouse_story_v1_fusion/
```

**Use explicit profile**:
```bash
python tools/calibrate_planar_homography.py \
  --profile board_55x40_warehouse_story_v1_fusion \
  --camera 0 \
  --out calib/profiles/board_55x40_warehouse_story_v1_fusion/cam0/mapping_raw.yaml
```

---

## Git Workflow

### Branches

- **main**: Production-ready code
- **develop**: Integration branch (if used)
- **feature/\***: New features
- **fix/\***: Bug fixes
- **docs/\***: Documentation updates

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add GPU backend support
fix: resolve camera index issue in multi-cam fusion
docs: update calibration runbook
test: add tests for zone analytics
refactor: simplify mapping pipeline
```

### Pre-Commit Hook (Optional)

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
set -e

echo "Running pre-commit checks..."

# Run tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q || exit 1

# Run doctor
python -m metriplane.cli doctor || exit 1

# Check shell scripts
bash -n tools/mp.sh || exit 1
bash -n tools/dashboard_runner.sh || exit 1

echo "✅ Pre-commit checks passed"
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

---

## Environment Variables

### Commonly Used

```bash
# Config file override
export CONFIG=configs/fusion_health_local.yaml

# Camera indices
export CAM0_INDEX=0
export CAM1_INDEX=2

# Logging level
export LOG_LEVEL=DEBUG

# CUDA device selection
export CUDA_VISIBLE_DEVICES=0

# Python path (if needed)
export PYTHONPATH=<repo>:$PYTHONPATH
```

### Load from File

Create `.env` (gitignored):
```bash
CONFIG=configs/fusion_health_local.yaml
CAM0_INDEX=0
CAM1_INDEX=2
LOG_LEVEL=INFO
```

Load:
```bash
set -a
source .env
set +a
```

---

## IDE Setup

### VS Code

**Recommended Extensions**:
- Python (Microsoft)
- Pylance
- Black Formatter
- Even Better TOML

**settings.json**:
```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": [
    "tests",
    "-v"
  ],
  "python.envFile": "${workspaceFolder}/.env",
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "ms-python.black-formatter"
  }
}
```

**launch.json** (debugging):
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Run Fusion",
      "type": "python",
      "request": "launch",
      "module": "metriplane.run_fusion",
      "args": [],
      "env": {
        "CONFIG": "configs/fusion_health_local.yaml"
      },
      "console": "integratedTerminal"
    }
  ]
}
```

### PyCharm

1. **Open project**: `<repo>`
2. **Configure interpreter**: File → Settings → Project → Python Interpreter → Add → Existing → `.venv/bin/python`
3. **Mark sources root**: Right-click project root → Mark Directory as → Sources Root
4. **Run configurations**: Run → Edit Configurations → Add → Python → Module: `metriplane.run_fusion`

---

## Performance Tips

### 1. Use GPU Backend

```bash
# Check GPU availability
python -c "import cupy; print(cupy.cuda.runtime.getDeviceCount())"

# Run with GPU
CONFIG=configs/fusion_health_local.yaml ./tools/mp.sh run-fusion gpu 60 gpu_test
```

### 2. Adjust Queue Depths

Edit config YAML:
```yaml
pipeline:
  queue_depth: 2  # Lower = less memory, more backpressure
  # queue_depth: 10  # Higher = more buffering, less jitter
```

### 3. Profile with Timing Breakdown

```bash
CONFIG=configs/fusion_health_local.yaml ./tools/mp.sh timing-breakdown
```

**Output**: Per-stage latencies (capture, detect, map, fuse, publish)

---

## Additional Resources

**Documentation**:
- [docs/calibration_runbook.md](calibration_runbook.md) - Multi-camera calibration
- [docs/dashboard_multicam_runbook.md](dashboard_multicam_runbook.md) - Dashboard usage
- [docs/schema.md](schema.md) - Frame schema specification
- [docs/gpu_compute_backend.md](gpu_compute_backend.md) - GPU acceleration

**Tools**:
- [tools/mp.sh](../tools/mp.sh) - Main CLI wrapper
- [tools/dashboard_runner.sh](../tools/dashboard_runner.sh) - Runner service
- [tools/debug_alignment.py](../tools/debug_alignment.py) - Calibration diagnostics

**Web UI**:
- [web/dashboard/](../web/dashboard/) - Dashboard source code
- [web/dashboard/README.md](../web/dashboard/README.md) - Dashboard documentation

---

**Generated**: 2026-04-27  
**See also**: README.md, docs/PREREQUISITES.md, docs/INTEGRATIONS.md
