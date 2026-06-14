# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.mapping.planar import HomographyMapping, load_homography, save_homography


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
