# Metriplane Prerequisites

**Target Audience**: Developers, researchers, and operators setting up Metriplane for the first time  
**Last Updated**: 2026-04-26  
**Supported Platform**: Ubuntu 24.04 LTS (native or Docker)

---

## Core Requirements

### Operating System

**Supported**:
- Ubuntu 24.04 LTS (recommended, tested)
- Ubuntu 22.04 LTS (should work, untested)
- Linux with v4l2 support (for USB camera access)

**Assumptions**:
- `bash` shell available
- Standard GNU utilities (`grep`, `sed`, `awk`, `find`)
- `git` installed for version control
- User in `video` group for camera access

**Not Supported**:
- Windows (Docker may work with WSL2, untested)
- macOS (Docker may work, camera pass-through untested)

---

## Python 3.12 Setup

### Install Python 3.12

Ubuntu 24.04 ships with Python 3.12 by default:

```bash
# Verify Python version
python3 --version
# Expected: Python 3.12.3 (or higher)

# Install venv module if missing
sudo apt install python3-venv python3-pip
```

### Create Local Virtual Environment

Metriplane uses a **local `.venv`** directory (not `~/metriplane-venv`):

```bash
# Navigate to Metriplane root
cd /path/to/metriplane

# Create .venv in project directory
python3 -m venv .venv

# Activate
source .venv/bin/activate

# Verify activation (should show .venv path)
which python
# Expected: /path/to/metriplane/.venv/bin/python
```

**Why local .venv?**
- Self-contained per-project isolation
- Easier for Docker bind mounts
- No risk of mixing dependencies across projects

---

## Install Metriplane Package

### Basic Installation

```bash
# Ensure .venv is activated
source .venv/bin/activate

# Install Metriplane in editable mode
python -m pip install -e .
```

This installs the core runtime dependencies declared in `pyproject.toml`, including NumPy, OpenCV headless, Pydantic, PyYAML, and websockets.

If development tools are not already installed, install them separately as needed:

```bash
python -m pip install pytest ruff mypy pre-commit
```

### Verify Installation

```bash
# Test import
python -c "from metriplane.config import Config; print('✅ Metriplane installed')"

# Check installed version
python -m pip show metriplane
```

---

## Run Tests

### Basic Test Command

```bash
# Activate venv
source .venv/bin/activate

# Run pytest with ROS 2 plugin disabled
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

**Why disable plugin autoload?**
- ROS 2 Jazzy installs `launch_testing` pytest plugin globally
- Plugin tries to interpret all tests as ROS launch tests
- Causes import errors for non-ROS tests

### Alternative: Configure pytest.ini

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-p no:launch_testing"
```

Then run normally:
```bash
python -m pytest -q
```

---

## Camera Setup

### Check Available Cameras

```bash
# List video devices
ls -l /dev/video*
# Expected: /dev/video0, /dev/video1, etc.

# List by stable ID (recommended)
ls -l /dev/v4l/by-id/
# Expected: usb-<vendor>_<model>-video-index0

# Check camera properties
v4l2-ctl --list-devices

# Test camera capture (requires OpenCV with GUI support)
python -c "
import cv2
cap = cv2.VideoCapture(0)
ret, frame = cap.read()
cap.release()
print('✅ Camera accessible' if ret else '❌ Camera failed')
"
```

### User Permissions

Ensure user is in `video` group:

```bash
# Check current groups
groups

# Add user to video group (if missing)
sudo usermod -aG video $USER

# Log out and log back in for group change to take effect
```

### Camera Index vs Device Path

Metriplane supports both:
- **Index**: `camera_index: 0` in config (uses `/dev/video0`)
- **Device path**: `device: /dev/v4l/by-id/usb-...` (stable across reboots)

**Recommendation**: Use `/dev/v4l/by-id/` paths for production to avoid device enumeration issues.

---

## ArUco Marker Requirements

Metriplane uses **OpenCV ArUco markers** for object detection.

### Marker Dictionary

Default: **4x4_50** (50 unique IDs, 4x4 bit pattern)

### Generate Markers

```bash
# Download marker generator
# https://chev.me/arucogen/

# Or use OpenCV directly
python -c "
import cv2
import numpy as np
aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
for i in range(10):
    marker = cv2.aruco.generateImageMarker(aruco_dict, i, 200)
    cv2.imwrite(f'marker_{i}.png', marker)
print('✅ Generated markers 0-9')
"
```

### Print Guidelines

- **Size**: At least 50mm x 50mm per marker (larger recommended)
- **Material**: Matte paper or foam board (avoid glossy/reflective surfaces)
- **Border**: White border around black marker (ArUco standard)
- **Mounting**: Flat surface, perpendicular to camera view for best detection

### Marker IDs

- Metriplane tracks objects by marker ID
- IDs must be unique within camera view
- Configure marker-to-object mapping in `calib/anchors.yaml` (optional)

---

## OpenCV Headless Note

Metriplane's default dependency is `opencv-python-headless`, which is suitable for server/headless operation and automated tests.

Some debugging tools that use `cv2.imshow()` require a GUI-capable OpenCV build. Do not install multiple conflicting OpenCV packages at the same time. If GUI tools are needed, remove the headless package first and install an appropriate GUI/contrib build:

```bash
# Remove headless version first
pip uninstall opencv-python-headless

# Install GUI version
pip install opencv-contrib-python
```

**Note**: GUI builds have additional dependencies (Qt, GTK) that may not be available in Docker or headless servers.

---

## Docker Requirements

### Install Docker Engine

```bash
# Ubuntu 24.04
sudo apt update
sudo apt install docker.io docker-compose

# Add user to docker group (no sudo needed for docker commands)
sudo usermod -aG docker $USER
# Log out and back in

# Verify
docker --version
docker compose version
```

### Camera Device Pass-Through

For live camera mode in Docker:

```bash
# Pass device to container
docker run --device /dev/video0 ...

# Or in compose.yaml:
devices:
  - /dev/video0:/dev/video0
```

### Docker QuickStart

```bash
# Demo mode (replay dataset, no camera)
./tools/docker_demo_up.sh

# Check logs
docker compose logs -f

# Clean up
./tools/docker_clean.sh
```

See `docker/docker_quickstart.md` for full workflows.

---

## Optional: NVIDIA GPU / CUDA / CuPy

Metriplane optionally uses **CuPy** for GPU-accelerated fusion operations.

### Check GPU Availability

```bash
# Check NVIDIA driver
nvidia-smi

# Expected output:
# +-----------------------------------------------------------------------------+
# | NVIDIA-SMI 550.xx.xx    Driver Version: 550.xx.xx    CUDA Version: 12.4  |
# +-----------------------------------------------------------------------------+
```

### Install CUDA Toolkit

**Option 1: System package (Ubuntu 24.04)**

```bash
# CUDA 12.x (system repo)
sudo apt install nvidia-cuda-toolkit

# Verify
nvcc --version
```

**Option 2: NVIDIA installer (latest CUDA 13.x)**

Follow: https://developer.nvidia.com/cuda-downloads

### Install CuPy

```bash
# Activate venv
source .venv/bin/activate

# For CUDA 12.x
pip install -e .[gpu-cuda12x]

# For CUDA 13.x
pip install -e .[gpu-cuda13x]
```

### Environment Setup

Metriplane looks for `tools/env/vt_cuda13_env.sh`:

```bash
# Example vt_cuda13_env.sh
export CUDA_HOME=/usr/local/cuda-13.1
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
export PATH=$CUDA_HOME/bin:$PATH
```

Edit path to match your CUDA installation.

### Verify GPU Backend

```bash
# Run GPU smoke test
./tools/mp.sh gpu-smoke

# Check CuPy import
python -c "import cupy; print('✅ CuPy available')"
```

### GPU in Docker

Requires **nvidia-docker2**:

```bash
# Install nvidia-docker2
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt update
sudo apt install nvidia-docker2
sudo systemctl restart docker

# Test
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

**Note**: GPU acceleration is **optional**. Metriplane automatically falls back to CPU if CuPy is unavailable.

---

## Optional: ROS 2 Setup

Metriplane can bridge to **ROS 2** topics via WebSocket.

### Install ROS 2 Jazzy

```bash
# Ubuntu 24.04 (Jazzy Jalisco is the official ROS 2 release)
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository universe
sudo apt update && sudo apt install curl
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | \
  sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
  http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | \
  sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt install ros-jazzy-desktop

# Source ROS 2 environment
source /opt/ros/jazzy/setup.bash
```

### ROS 2 Pytest Plugin Conflict

ROS 2 installs **launch_testing** pytest plugin globally, which interferes with Metriplane tests.

**Solution**: Disable plugin (see [Run Tests](#run tests) section above).

### ROS 2 Bridge Example

```python
# Example: Subscribe to Metriplane WebSocket, publish to ROS 2 topic
import asyncio
import websockets
import rclpy
from std_msgs.msg import String

async def bridge():
    async with websockets.connect('ws://localhost:8765') as ws:
        while True:
            frame_json = await ws.recv()
            # Publish to ROS 2 topic
            # (implement using rclpy.Node)
```

**Full integration guide**: See planned `docs/INTEGRATION.md`.

---

## Optional: NVIDIA Omniverse Setup

Metriplane can stream to **Omniverse** via WebSocket for 3D visualization.

### Install Omniverse

1. Download **NVIDIA Omniverse Launcher**: https://www.nvidia.com/en-us/omniverse/download/
2. Install Omniverse Kit or Create
3. Enable Developer Mode (for custom extensions)

### Install Metriplane Omniverse Extension

```bash
# Clone extension repo (separate from main Metriplane)
git clone <metriplane-omniverse-ext-url>

# Link extension to Omniverse
# (Follow extension README for installation)
```

### Connect to Metriplane WebSocket

The Omniverse extension connects to `ws://localhost:8765` and:
- Parses `FrameStateModel` JSON
- Creates USD prims for each tracked object
- Updates transforms in real-time

**Integration guide**: See planned `docs/INTEGRATION.md`.

---

## Troubleshooting

| Issue | Symptom | Solution |
|-------|---------|----------|
| **ImportError: No module named 'metriplane'** | `from metriplane.config import Config` fails | Activate `.venv`: `source .venv/bin/activate`<br>Install package: `pip install -e .` |
| **Pytest import errors (launch_testing)** | `ERROR collecting test session` | Run with: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` |
| **Camera not accessible** | `/dev/video0: Permission denied` | Add user to video group: `sudo usermod -aG video $USER`<br>Log out and back in |
| **Camera not found** | `cv2.VideoCapture(0)` returns no frames | Check devices: `ls /dev/video*`<br>Try different index: `VideoCapture(1)` |
| **ArUco markers not detected** | No detections in logs | Check marker size (too small?)<br>Check lighting (too dark/bright?)<br>Check marker flat on surface<br>Use `tools/preview_zones_overlay.py` to debug |
| **CuPy not found** | `ModuleNotFoundError: No module named 'cupy'` | Install GPU extras: `pip install -e .[gpu-cuda13x]`<br>Or run CPU-only (automatic fallback) |
| **CUDA version mismatch** | `cupy.cuda.compiler.CompileException` | Check CUDA version: `nvcc --version`<br>Install matching CuPy: `pip install cupy-cuda12x` or `cupy-cuda13x` |
| **Docker permission denied** | `docker: Got permission denied` | Add user to docker group: `sudo usermod -aG docker $USER`<br>Log out and back in |
| **Docker camera pass-through fails** | Camera not visible in container | Check device exists: `ls /dev/video0`<br>Add `--device /dev/video0` to docker run<br>Ensure user  in video group on host |
| **ROS 2 environment pollution** | Tests fail with ROS 2 sourced | Deactivate ROS: start new shell without `source /opt/ros/jazzy/setup.bash`<br>Or disable pytest plugin (see above) |
| **Omniverse extension not loading** | Extension not visible in Omniverse | Check extension path in Omniverse settings<br>Check extension manifest (`extension.toml`) |
| **WebSocket connection refused** | `ConnectionRefusedError [Errno 111]` | Check Metriplane backend running: `curl http://localhost:8000/health`<br>Check port 8765 not blocked by firewall |
| **High CPU usage, slow FPS** | Pipeline runs at <10 FPS | Check target FPS in config (default 300 may be too high)<br>Reduce resolution or detection frequency<br>Enable GPU backend if available |
| **Memory leak, OOM crashes** | Process killed by OOM | Check queue sizes in config (bounded queues prevent unbounded growth)<br>Reduce image resolution<br>Check for circular references in tracking |

---

## Verification Checklist

Before running Metriplane, verify:

- [ ] **Python 3.12** installed: `python3 --version`
- [ ] **Virtual environment** created: `.venv/` directory exists
- [ ] **Metriplane package** installed: `python -c "import metriplane"`
- [ ] **Tests pass**: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
- [ ] **Camera accessible**: `ls /dev/video*` or `ls /dev/v4l/by-id/`
- [ ] **User in video group**: `groups | grep video`
- [ ] **ArUco markers** printed and mounted
- [ ] **Git available**: `git --version`
- [ ] **Docker** (optional): `docker --version`
- [ ] **GPU/CUDA** (optional): `nvidia-smi`
- [ ] **CuPy** (optional): `python -c "import cupy"`
- [ ] **ROS 2** (optional): `source /opt/ros/jazzy/setup.bash && ros2 --version`

---

## Next Steps

After completing prerequisites:

1. **Run preflight check**: `./tools/mp.sh preflight`
2. **Try Docker demo**: `./tools/docker_demo_up.sh` (no camera required)
3. **Try quickstart commands**: See [README.md](../README.md#-quickstart-3-commands)
4. **Configure cameras**: Edit `calib/profiles/<profile>/cam*/mapping.yaml`
5. **Run live demo**: `./tools/mp.sh run-fusion cpu 10 my_first_run`

---

## Support

- **Documentation**: [docs/development.md)
- **Health check**: [docs/PREREQUISITES.md)
- **Release audit**: [docs/scope_rules.md)
- **GitHub Issues**: Report bugs or ask questions

---

**Last Updated**: 2026-04-26  
**Verified on**: Ubuntu 24.04 LTS, Python 3.12.3, ROS 2 Jazzy
