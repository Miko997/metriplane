# Reviewer Quickstart

This guide provides a camera-free path for inspecting MetriPlane v0.1.4.

## Artifact

- Release: v0.1.4
- DOI: https://doi.org/10.5281/zenodo.20631037
- License: MIT

## Scope

MetriPlane is scoped to planar XY tracking with fiducial marker IDs. It does not claim marker-free tracking, full 3D reconstruction, safety-certified industrial control, or measured end-to-end ROS 2 / Omniverse latency.

## Quickstart

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

Expected replay result: pass=true, zero positional difference, zero event mismatches.

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
