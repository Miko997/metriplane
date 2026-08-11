# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest
from maniskill_pickcube.constants import DEFAULT_CONFIG
from maniskill_pickcube.core import RestoredFrame, load_config


@pytest.fixture
def frozen_config() -> dict[str, object]:
    return load_config(DEFAULT_CONFIG)


@pytest.fixture
def restored_frames(frozen_config: dict[str, object]) -> list[RestoredFrame]:
    polygon = frozen_config["target_polygon"]
    assert isinstance(polygon, dict)
    center = polygon["center"]
    assert isinstance(center, list)
    inside = (float(center[0]), float(center[1]), 0.04, 1.0, 0.0, 0.0, 0.0)
    outside = (0.25, 0.25, 0.04, 1.0, 0.0, 0.0, 0.0)
    goal = (
        float(center[0]),
        float(center[1]),
        0.2889334559440613,
        1.0,
        0.0,
        0.0,
        0.0,
    )
    return [
        RestoredFrame(
            cube_pose=inside if index >= 66 else outside,
            tcp_pose=inside if index >= 71 else outside,
            goal_pose=goal,
        )
        for index in range(75)
    ]


@pytest.fixture
def config_path() -> Path:
    return DEFAULT_CONFIG
