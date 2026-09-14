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


@dataclass(slots=True)
class CpuNumpyBackend(FusionComputeBackend):
    """CPU compute backend implemented with NumPy.

    Uses a vectorized 'bincount' aggregation so the compute cost scales well when
    the number of observations grows.
    """

    name: str = "cpu_numpy"

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

        # stable ordering for determinism
        oids = sorted(str(k) for k in observations.keys())
        if not oids:
            return {}

        obj_idx: list[int] = []
        xs: list[float] = []
        ys: list[float] = []
        ws: list[float] = []

        for i, oid in enumerate(oids):
            for ob in observations.get(oid, ()):
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

        idx = np.asarray(obj_idx, dtype=np.int64)
        x = np.asarray(xs, dtype=np.float64)
        y = np.asarray(ys, dtype=np.float64)
        weights = np.asarray(ws, dtype=np.float64)

        n = int(len(oids))
        sum_w = np.bincount(idx, weights=weights, minlength=n).astype(np.float64)
        sum_wx = np.bincount(idx, weights=(weights * x), minlength=n).astype(np.float64)
        sum_wy = np.bincount(idx, weights=(weights * y), minlength=n).astype(np.float64)

        out: dict[str, Tuple[float, float]] = {}
        for i, oid in enumerate(oids):
            sw = float(sum_w[i])
            if sw <= 0:
                continue
            out[str(oid)] = (float(sum_wx[i] / sw), float(sum_wy[i] / sw))

        return out

    def synchronize(self) -> None:
        # CPU is synchronous
        return
