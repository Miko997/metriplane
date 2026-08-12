# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest

from robomimic_lowdim.constants import DEFAULT_CONFIG
from robomimic_lowdim.fixture import load_config
from robomimic_lowdim.hdf5_audit import SourceFrame


@pytest.fixture
def frozen_config() -> dict[str, object]:
    return load_config(DEFAULT_CONFIG)


@pytest.fixture
def config_path() -> Path:
    return DEFAULT_CONFIG


@pytest.fixture
def source_frames(frozen_config: dict[str, object]) -> list[SourceFrame]:
    polygon = frozen_config["target_polygon"]
    assert isinstance(polygon, dict)
    center = polygon["center"]
    assert isinstance(center, list)
    can_inside = (float(center[0]), float(center[1]), 0.86)
    tcp_inside = (float(center[0]) + 0.005, float(center[1]) + 0.005, 0.95)
    outside = (0.35, 0.35, 1.0)
    return [
        SourceFrame(
            can_xyz=can_inside if index <= 63 else outside,
            tcp_xyz=tcp_inside if 42 <= index <= 64 else outside,
        )
        for index in range(118)
    ]
