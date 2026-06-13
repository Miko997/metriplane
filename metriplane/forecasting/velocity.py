from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

# Clamp velocity to a sane physical bound to suppress marker-jitter / ID-swap
# teleports producing absurd forecasts.
MAX_SPEED_MPS = 10.0


@dataclass
class VelocityEstimate:
    vx: float
    vy: float
    speed: float
    n_points: int          # number of valid trace points available
    source: str            # "vel_world" | "trace" | "none"

    @property
    def confidence(self) -> float:
        """Deterministic MVP confidence tiers (see docs/forecasting.md)."""
        if self.source == "trace" and self.n_points >= 3:
            return 0.8
        if self.source == "trace" and self.n_points == 2:
            return 0.6
        if self.source == "vel_world":
            return 0.4
        return 0.0


@dataclass
class VelocityEstimator:
    """Tracks recent world positions per object to estimate velocity."""
    history_len: int = 5
    _hist: dict[str, deque] = field(default_factory=dict)

    def observe(self, object_id: str, ts: float,
                pos: tuple[float, float] | None) -> None:
        if pos is None:
            return
        dq = self._hist.get(object_id)
        if dq is None:
            dq = deque(maxlen=self.history_len)
            self._hist[object_id] = dq
        dq.append((ts, pos[0], pos[1]))

    def n_points(self, object_id: str) -> int:
        dq = self._hist.get(object_id)
        return len(dq) if dq else 0

    def estimate(self, object_id: str,
                 vel_world: tuple[float, float] | None) -> VelocityEstimate:
        dq = self._hist.get(object_id)
        # Prefer trace-derived velocity when we have at least two points.
        if dq is not None and len(dq) >= 2:
            t0, x0, y0 = dq[-2]
            t1, x1, y1 = dq[-1]
            dt = t1 - t0
            if dt > 0:
                vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
                vx, vy, speed = _clamp(vx, vy)
                return VelocityEstimate(vx, vy, speed, len(dq), "trace")
        if vel_world is not None:
            vx, vy, speed = _clamp(vel_world[0], vel_world[1])
            return VelocityEstimate(vx, vy, speed, self.n_points(object_id), "vel_world")
        return VelocityEstimate(0.0, 0.0, 0.0, self.n_points(object_id), "none")


def _clamp(vx: float, vy: float) -> tuple[float, float, float]:
    speed = (vx * vx + vy * vy) ** 0.5
    if speed > MAX_SPEED_MPS and speed > 0:
        scale = MAX_SPEED_MPS / speed
        vx, vy = vx * scale, vy * scale
        speed = MAX_SPEED_MPS
    return vx, vy, speed
