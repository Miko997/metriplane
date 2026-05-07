from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np  # type: ignore


@dataclass
class KalmanCV2D:
    """
    State: [x, y, vx, vy]
    Measurement: [x, y]
    """
    x: np.ndarray  # (4,)
    P: np.ndarray  # (4,4)

    def predict(self, dt: float, process_sigma: float) -> None:
        dt = float(max(dt, 0.0))

        F = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

        # Discrete white noise acceleration model
        # process_sigma ~ accel noise (m/s^2)
        q = float(process_sigma) ** 2
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2

        Q = q * np.array(
            [
                [dt4 / 4.0, 0.0, dt3 / 2.0, 0.0],
                [0.0, dt4 / 4.0, 0.0, dt3 / 2.0],
                [dt3 / 2.0, 0.0, dt2, 0.0],
                [0.0, dt3 / 2.0, 0.0, dt2],
            ],
            dtype=np.float64,
        )

        self.x = (F @ self.x).astype(np.float64)
        self.P = (F @ self.P @ F.T + Q).astype(np.float64)

    def update_xy(self, z: Tuple[float, float], meas_sigma: float) -> None:
        zx, zy = float(z[0]), float(z[1])

        H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)

        r = float(max(meas_sigma, 1e-6)) ** 2
        R = np.array([[r, 0.0], [0.0, r]], dtype=np.float64)

        y = np.array([zx, zy], dtype=np.float64) - (H @ self.x)
        S = H @ self.P @ H.T + R

        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = (self.x + (K @ y)).astype(np.float64)
        I = np.eye(4, dtype=np.float64)
        self.P = ((I - (K @ H)) @ self.P).astype(np.float64)


@dataclass
class MultiObjectKalman:
    process_sigma: float = 0.8
    base_meas_sigma: float = 0.03
    timeout_s: float = 2.0

    _filters: Dict[str, KalmanCV2D] = field(default_factory=dict)
    _last_ts: Dict[str, float] = field(default_factory=dict)

    def prune(self, ts: float) -> None:
        cutoff = float(ts) - float(self.timeout_s)
        for oid, last in list(self._last_ts.items()):
            if float(last) < cutoff:
                self._last_ts.pop(oid, None)
                self._filters.pop(oid, None)

    def update(
        self,
        *,
        ts: float,
        measurements: Dict[str, List[Tuple[float, float, float]]],
    ) -> Dict[str, Tuple[float, float, float, float]]:
        """
        measurements[object_id] = [(x, y, meas_sigma), ...] from multiple cameras
        Returns fused states: {oid: (x, y, vx, vy)}
        """
        ts_f = float(ts)
        self.prune(ts_f)

        out: Dict[str, Tuple[float, float, float, float]] = {}

        for oid, meas_list in measurements.items():
            if not meas_list:
                continue

            oid_s = str(oid)
            last = self._last_ts.get(oid_s)
            if oid_s not in self._filters:
                # init at mean measurement
                mx = sum(m[0] for m in meas_list) / float(len(meas_list))
                my = sum(m[1] for m in meas_list) / float(len(meas_list))
                x0 = np.array([mx, my, 0.0, 0.0], dtype=np.float64)
                P0 = np.diag([0.25, 0.25, 1.0, 1.0]).astype(np.float64)  # loose
                self._filters[oid_s] = KalmanCV2D(x=x0, P=P0)
                self._last_ts[oid_s] = ts_f
                last = ts_f

            kf = self._filters[oid_s]
            dt = float(ts_f - float(last or ts_f))
            if dt > 0:
                kf.predict(dt, process_sigma=float(self.process_sigma))

            # Multi-sensor updates
            for (x, y, sigma) in meas_list:
                sig = float(sigma) if sigma > 0 else float(self.base_meas_sigma)
                kf.update_xy((float(x), float(y)), meas_sigma=sig)

            self._last_ts[oid_s] = ts_f

            out[oid_s] = (float(kf.x[0]), float(kf.x[1]), float(kf.x[2]), float(kf.x[3]))

        return out
