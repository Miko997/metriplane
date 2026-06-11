# Reviewer Quickstart

This guide provides a camera-free path for inspecting MetriPlane v0.1.4.

## Artifact

- Release: v0.1.4
- DOI: https://doi.org/10.5281/zenodo.20631037
- License: MIT

## Scope

MetriPlane is scoped to planar XY tracking with fiducial marker IDs. It does not claim marker-free tracking, full 3D reconstruction, safety-certified industrial control, or measured end-to-end ROS 2 / Omniverse latency.

## Linux/macOS Quickstart

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

## Windows Git Bash Quickstart

Use Git Bash or WSL on Windows, not plain Command Prompt, because `tools/mp.sh` is a Bash script.

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python -m venv .venv
source .venv/Scripts/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

Expected camera-free result:

- doctor: 0 failures
- deterministic replay: `pass=true`
- `mean_pos_diff_cm=0.0`
- `max_pos_diff_cm=0.0`
- `event_mismatch_count=0`
- `No /dev/video* devices found` is acceptable as a warning for camera-free replay.

## Docker smoke path

```bash
./tools/docker_demo_up.sh
curl http://localhost:8000/health
./tools/docker_clean.sh
```

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

The v0.1.4 release reports 193/193 tests passing in a clean environment.
