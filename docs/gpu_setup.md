<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# GPU Setup (M9.6)

This project’s M9.6 GPU compute backend uses **CuPy** to run the fusion compute block on an NVIDIA GPU.

## Host prerequisites

- NVIDIA GPU + recent NVIDIA driver
- CUDA-capable runtime (driver only is enough for CuPy wheels; you generally do **not** need the full CUDA Toolkit)
- Python 3.12

Verify your driver/GPU:

```bash
nvidia-smi
```

## Python install

### Option A: install a CuPy wheel that matches your CUDA driver

CuPy wheels are distributed per CUDA major version (examples):

- `cupy-cuda11x`
- `cupy-cuda12x`

Install the right one for your machine:

```bash
pip install -U cupy-cuda12x
# or
pip install -U cupy-cuda11x
```

Then install Metriplane:

```bash
pip install -e .
```

### Option B: use the project extra (adjust if needed)

If your `pyproject.toml` defines an extra `gpu`, you can do:

```bash
pip install -e ".[gpu]"
```

**Note:** If your environment needs `cupy-cuda11x` instead of `cupy-cuda12x`, update the extra accordingly.

## Smoke test (CuPy + GPU)

```bash
python - <<'PY'
import cupy as cp
print('cupy:', cp.__version__)
print('device count:', cp.cuda.runtime.getDeviceCount())
with cp.cuda.Device(0):
    a = cp.ones((1024, 1024), dtype=cp.float32)
    b = a @ a
    cp.cuda.Stream.null.synchronize()
print('ok')
PY
```

## Docker (optional)

If you run in Docker, ensure the NVIDIA Container Toolkit is installed and your Docker supports GPUs.

Typical run patterns:

```bash
docker run --gpus all --rm nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Or via docker compose (if your compose file defines a `gpu` profile/service):

```bash
docker compose --profile gpu up --build
```
