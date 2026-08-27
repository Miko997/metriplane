# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.forecasting.projector import project_path


def test_constant_velocity_projection():
    path = project_path((0.0, 0.0), (1.0, 0.0), horizon_s=1.0, step_s=0.5)
    assert len(path) == 2
    assert path[0] == (0.5, 0.5, 0.0)
    assert path[1] == (1.0, 1.0, 0.0)


def test_respects_horizon_and_step():
    path = project_path((0.0, 0.0), (1.0, 1.0), horizon_s=2.0, step_s=0.5)
    assert len(path) == 4
    assert path[-1][0] == 2.0


def test_caps_projected_points():
    path = project_path((0.0, 0.0), (1.0, 0.0), horizon_s=100.0, step_s=0.1, max_points=5)
    assert len(path) == 5


def test_stationary_object_stays_put():
    path = project_path((3.0, 4.0), (0.0, 0.0), horizon_s=1.0, step_s=0.5)
    assert all(abs(x - 3.0) < 1e-9 and abs(y - 4.0) < 1e-9 for _, x, y in path)


def test_zero_step_returns_empty():
    assert project_path((0.0, 0.0), (1.0, 0.0), horizon_s=1.0, step_s=0.0) == []


def test_zero_horizon_returns_empty():
    assert project_path((0.0, 0.0), (1.0, 0.0), horizon_s=0.0, step_s=0.1) == []
