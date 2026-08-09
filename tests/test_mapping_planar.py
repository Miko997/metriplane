# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from metriplane.mapping.planar import HomographyMapping, load_homography, save_homography
from metriplane.mapping.planar_multi import load_multi_planar_mapper


def test_homography_identity_pixel_to_world() -> None:
    m = HomographyMapping(
        H=((1.0, 0.0, 0.0),
           (0.0, 1.0, 0.0),
           (0.0, 0.0, 1.0)),
        units="meters",
    )
    assert m.pixel_to_world_xy(10.0, 20.0) == (10.0, 20.0)


def test_save_load_roundtrip(tmp_path) -> None:
    p = tmp_path / "mapping.yaml"
    save_homography(
        p,
        H=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        units="meters",
        extra={"type": "homography_v1"},
    )
    m = load_homography(p)
    assert m.units == "meters"
    assert m.pixel_to_world_xy(3.0, 4.0) == (3.0, 4.0)


def test_multicamera_mapping_rejects_mixed_units(tmp_path) -> None:
    meters = tmp_path / "meters.yaml"
    millimeters = tmp_path / "millimeters.yaml"
    for path, units in ((meters, "meters"), (millimeters, "millimeters")):
        save_homography(
            path,
            H=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            units=units,
            extra={"type": "homography_v1"},
        )

    with pytest.raises(ValueError, match="units must match"):
        load_multi_planar_mapper(
            mapping_by_camera={"cam0": meters, "cam1": millimeters},
            intrinsics_by_camera={"cam0": None, "cam1": None},
        )
