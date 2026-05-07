from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class XYObs:
    camera_id: str
    x: float
    y: float
    confidence: float | None = None
    rmse: float | None = None


def fuse_average(observations: Iterable[XYObs]) -> tuple[float, float] | None:
    obs = list(observations)
    if not obs:
        return None
    sx = sum(o.x for o in obs)
    sy = sum(o.y for o in obs)
    n = float(len(obs))
    return (sx / n, sy / n)


def _weight(o: XYObs, eps: float = 1e-9) -> float:
    w = float(o.confidence) if o.confidence is not None else 1.0
    if o.rmse is not None and o.rmse > 0:
        # smaller rmse => larger weight
        w *= 1.0 / ((float(o.rmse) ** 2) + eps)
    return float(w)


def fuse_weighted(observations: Iterable[XYObs]) -> tuple[float, float] | None:
    obs = list(observations)
    if not obs:
        return None

    ws = [_weight(o) for o in obs]
    wsum = sum(ws)
    if wsum <= 0:
        return fuse_average(obs)

    x = sum(w * o.x for w, o in zip(ws, obs)) / wsum
    y = sum(w * o.y for w, o in zip(ws, obs)) / wsum
    return (float(x), float(y))
