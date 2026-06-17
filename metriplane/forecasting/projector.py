# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations


def project_path(
    pos: tuple[float, float],
    vel: tuple[float, float],
    horizon_s: float,
    step_s: float,
    max_points: int = 12,
) -> list[tuple[float, float, float]]:
    """
    Constant-velocity projection.

    Returns a list of (dt_s, x, y) from step_s up to horizon_s (inclusive),
    capped at max_points. A stationary object yields points at the same
    position.
    """
    if step_s <= 0 or horizon_s <= 0:
        return []
    points: list[tuple[float, float, float]] = []
    dt = step_s
    while dt <= horizon_s + 1e-9 and len(points) < max_points:
        x = pos[0] + vel[0] * dt
        y = pos[1] + vel[1] * dt
        points.append((round(dt, 6), x, y))
        dt += step_s
    return points
