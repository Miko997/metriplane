# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from metriplane.zones import Zone, ZoneMap, point_in_polygon


def test_point_in_polygon_basic_square() -> None:
    poly = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert point_in_polygon(0.5, 0.5, poly) is True
    assert point_in_polygon(-0.1, 0.5, poly) is False
    assert point_in_polygon(1.0, 0.5, poly) is True  # edge treated as inside


def test_zone_map_lookup_first_match() -> None:
    z1 = Zone(name="A", polygon=((0, 0), (1, 0), (1, 1), (0, 1)))
    z2 = Zone(name="B", polygon=((2, 2), (3, 2), (3, 3), (2, 3)))
    zm = ZoneMap(units="meters", zones=(z1, z2))
    assert zm.zone_for_xy(0.2, 0.2) == "A"
    assert zm.zone_for_xy(2.2, 2.2) == "B"
    assert zm.zone_for_xy(9.0, 9.0) is None
