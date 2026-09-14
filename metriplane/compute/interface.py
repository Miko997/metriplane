# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, Tuple


# -----------------------------------------------------------------------------
# Interface
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XYObsLite:
    """A lightweight (x,y) observation.

    The compute backends accept observations in any of these shapes:
    - an object with attributes: .x, .y, .confidence, .rmse
    - a dict with keys: x, y, confidence, rmse

    This dataclass is primarily used internally by helper functions.
    """

    x: float
    y: float
    confidence: float
    rmse: float | None


class FusionComputeBackend(Protocol):
    """Compute backend for a fusion "compute block".

    M9.6 goal: allow swapping CPU vs GPU implementations of the same math.

    Backends MUST:
    - be deterministic for a given input
    - produce results equivalent within tolerance
    - expose a synchronize() for correct benchmarking on async GPUs
    """

    name: str

    def fuse_xy(
        self,
        observations: Mapping[str, Sequence[Any]],
        *,
        method: str,
        eps: float = 1e-9,
    ) -> dict[str, Tuple[float, float]]:
        """Fuse world-XY observations per object.

        Parameters
        ----------
        observations:
            {object_id: [obs1, obs2, ...]}
            Each obs must provide x,y and optionally confidence, rmse.

        method:
            "avg" or "weighted".

        eps:
            Small epsilon to avoid division by zero in weighting.

        Returns
        -------
        dict[str, (x, y)]
            Fused XY per object id. Objects with no usable observations are omitted.
        """

    def synchronize(self) -> None:
        """Block until all queued compute is complete.

        For CPU backends this is a no-op.
        For GPU backends this should synchronize the default stream.
        """


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def normalize_method(method: str) -> str:
    m = str(method or "").strip().lower()
    if m in ("mean", "average"):
        return "avg"
    if m in ("w", "wt", "weighted"):
        return "weighted"
    return m


def obs_to_lite(obs: Any) -> XYObsLite | None:
    """Best-effort extraction of (x,y,confidence,rmse) from an observation."""
    if obs is None:
        return None

    # dict-like
    if isinstance(obs, dict):
        try:
            x_raw = obs.get("x")
            y_raw = obs.get("y")
            if x_raw is None or y_raw is None:
                return None
            x = float(x_raw)
            y = float(y_raw)
        except Exception:
            return None
        conf_raw = obs.get("confidence")
        conf = float(conf_raw) if conf_raw is not None else 1.0
        rmse_raw = obs.get("rmse")
        rmse = float(rmse_raw) if rmse_raw is not None else None
        return XYObsLite(x=x, y=y, confidence=conf, rmse=rmse)

    # attribute-like
    try:
        x = float(getattr(obs, "x"))
        y = float(getattr(obs, "y"))
    except Exception:
        return None

    conf_raw = getattr(obs, "confidence", None)
    conf = float(conf_raw) if conf_raw is not None else 1.0

    rmse_raw = getattr(obs, "rmse", None)
    rmse = float(rmse_raw) if rmse_raw is not None else None

    return XYObsLite(x=x, y=y, confidence=conf, rmse=rmse)


def weight_for(obs: XYObsLite, *, method: str, eps: float) -> float:
    """Compute the weight used for fusion."""
    m = normalize_method(method)
    if m == "avg":
        return 1.0
    if m == "weighted":
        # confidence * inverse-variance weight based on rmse
        # (matches the scoring logic used elsewhere in the project)
        r = float(obs.rmse) if (obs.rmse is not None) else 0.0
        if r <= 0:
            return float(obs.confidence)
        return float(obs.confidence) / ((r * r) + float(eps))

    raise ValueError(f"unsupported fuse method '{method}' (expected avg|weighted)")
