# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.fusion.kalman_cv import MultiObjectKalman


def test_kalman_predicts_after_timestamp_zero() -> None:
    kalman = MultiObjectKalman(process_sigma=0.1, base_meas_sigma=0.01)
    kalman.update(ts=0.0, measurements={"1": [(0.0, 0.0, 0.01)]})
    first = kalman._filters["1"]
    first.x[2] = 1.0

    state = kalman.update(ts=1.0, measurements={"1": [(1.0, 0.0, 10.0)]})["1"]

    assert state[0] > 0.5
