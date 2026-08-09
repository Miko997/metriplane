# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.run_fusion import (
    HealthRegistry,
    HealthStatus,
    _update_camera_capture_health,
)


def _update(status):
    health = HealthRegistry()
    result = _update_camera_capture_health(
        capture_status=status,
        expected_camera_ids=["cam0", "cam1"],
        health=health,
        fail_after_s=2.0,
        target_fps=30.0,
    )
    return result, health.snapshot()


def test_one_stalled_camera_fails_without_failing_fresh_camera() -> None:
    result, snapshot = _update(
        {
            "cam0": {"has_frame": True, "capture_age_s": 0.02},
            "cam1": {"has_frame": True, "capture_age_s": 2.5},
        }
    )

    assert result == {"cam0": HealthStatus.OK, "cam1": HealthStatus.FAILED}
    assert snapshot["components"]["camera.cam0"]["status"] == "OK"
    assert snapshot["components"]["camera.cam1"]["status"] == "FAILED"


def test_all_stalled_cameras_are_failed() -> None:
    result, snapshot = _update(
        {
            "cam0": {"has_frame": True, "capture_age_s": 2.1},
            "cam1": {"has_frame": False, "capture_age_s": 3.0},
        }
    )

    assert set(result.values()) == {HealthStatus.FAILED}
    assert snapshot["overall"] == "FAILED"


def test_fast_poll_without_new_capture_does_not_mark_camera_stalled() -> None:
    result, _ = _update(
        {
            "cam0": {"has_frame": True, "capture_age_s": 0.04},
            "cam1": {"has_frame": True, "capture_age_s": 0.05},
        }
    )

    assert set(result.values()) == {HealthStatus.OK}
