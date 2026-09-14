# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple

import numpy as np

from metriplane.compute.interface import (
    FusionComputeBackend,
    normalize_method,
    obs_to_lite,
    weight_for,
)


class GpuUnavailable(RuntimeError):
    pass


def _import_cupy() -> Any:
    try:
        import cupy as cp  # type: ignore[import-not-found]

        return cp
    except Exception as e:
        raise GpuUnavailable(str(e)) from e


@dataclass(slots=True)
class GpuCupyBackend(FusionComputeBackend):
    """GPU compute backend implemented with CuPy.

    Notes:
    - This backend is optional; it requires a CUDA-enabled GPU and an installed
      CuPy package matching your CUDA runtime (e.g. cupy-cuda12x).
    - For correct wall-clock timing, benchmarks MUST call .synchronize().
    """

    device: int = 0
    name: str = "gpu_cupy"

    def __post_init__(self) -> None:
        cp = _import_cupy()
        # Ensure the device exists and select it.
        try:
            n = int(cp.cuda.runtime.getDeviceCount())
        except Exception as e:
            raise GpuUnavailable(f"CUDA runtime not available: {e}") from e
        if n <= 0:
            raise GpuUnavailable("no CUDA devices found")
        if int(self.device) < 0 or int(self.device) >= n:
            raise GpuUnavailable(f"requested device={self.device} but device_count={n}")
        cp.cuda.Device(int(self.device)).use()

        # Lightweight warmup: allocate + simple op.
        try:
            a = cp.zeros((1024,), dtype=cp.float32)
            _ = a.sum()
            cp.cuda.Stream.null.synchronize()
        except Exception as e:
            raise GpuUnavailable(f"GPU warmup failed: {e}") from e

    def fuse_xy(
        self,
        observations: Mapping[str, Sequence[Any]],
        *,
        method: str,
        eps: float = 1e-9,
    ) -> dict[str, Tuple[float, float]]:
        m = normalize_method(method)
        if m not in ("avg", "weighted"):
            raise ValueError(f"unsupported fuse method '{method}' (expected avg|weighted)")

        cp = _import_cupy()

        # stable ordering for determinism
        oids = sorted(str(k) for k in observations.keys())
        if not oids:
            return {}

        obj_idx: list[int] = []
        xs: list[float] = []
        ys: list[float] = []
        ws: list[float] = []

        for i, oid in enumerate(oids):
            for ob in observations.get(oid, ()):  # ragged
                lite = obs_to_lite(ob)
                if lite is None:
                    continue
                w = weight_for(lite, method=m, eps=float(eps))
                obj_idx.append(i)
                xs.append(float(lite.x))
                ys.append(float(lite.y))
                ws.append(float(w))

        if not obj_idx:
            return {}

        # Host -> device
        idx = cp.asarray(np.asarray(obj_idx, dtype=np.int64))
        x = cp.asarray(np.asarray(xs, dtype=np.float64))
        y = cp.asarray(np.asarray(ys, dtype=np.float64))
        w = cp.asarray(np.asarray(ws, dtype=np.float64))

        n = int(len(oids))
        sum_w = cp.bincount(idx, weights=w, minlength=n).astype(cp.float64)
        sum_wx = cp.bincount(idx, weights=(w * x), minlength=n).astype(cp.float64)
        sum_wy = cp.bincount(idx, weights=(w * y), minlength=n).astype(cp.float64)

        # Device -> host
        sum_w_h = cp.asnumpy(sum_w)
        sum_wx_h = cp.asnumpy(sum_wx)
        sum_wy_h = cp.asnumpy(sum_wy)

        out: dict[str, Tuple[float, float]] = {}
        for i, oid in enumerate(oids):
            sw = float(sum_w_h[i])
            if sw <= 0:
                continue
            out[str(oid)] = (float(sum_wx_h[i] / sw), float(sum_wy_h[i] / sw))
        return out

    def synchronize(self) -> None:
        cp = _import_cupy()
        cp.cuda.Stream.null.synchronize()


def is_available(*, device: int = 0) -> bool:
    """Best-effort check: can we import CuPy and select device?"""
    try:
        _ = GpuCupyBackend(device=int(device))
        return True
    except Exception:
        return False
