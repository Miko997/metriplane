# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from metriplane.schema import ObjectStateModel
from metriplane.zone_analytics import ZoneAnalytics
from metriplane.zones import Zone, ZoneMap


def test_zone_enter_exit_and_direct_transition() -> None:
    left = Zone(name="left", polygon=((0, 0), (0.5, 0), (0.5, 1.0), (0, 1.0)))
    right = Zone(name="right", polygon=((0.5, 0), (1.0, 0), (1.0, 1.0), (0.5, 1.0)))
    zm = ZoneMap(units="meters", zones=(left, right))
    a = ZoneAnalytics(zm)

    # t=1: object appears in left
    objs = [ObjectStateModel(id="7", pos_world=(0.25, 0.5, 0.0))]
    _, ev = a.update(1.0, objs)
    assert any(e.type == "zone_enter" and e.zone == "left" for e in ev)

    # t=2: moves to right directly -> transition left->right
    objs = [ObjectStateModel(id="7", pos_world=(0.75, 0.5, 0.0))]
    _, ev = a.update(2.0, objs)
    assert any(e.type == "zone_exit" and e.zone == "left" for e in ev)
    assert any(e.type == "zone_enter" and e.zone == "right" for e in ev)
    assert a._transitions.get(("left", "right")) == 1

    # t=3: disappears -> exit right
    objs = []
    _, ev = a.update(3.0, objs)
    assert any(e.type == "zone_exit" and e.zone == "right" for e in ev)


def test_transition_across_outside_gap() -> None:
    # This matches your real logs: zone_exit then later zone_enter in another zone,
    # with a brief period where zone=None.
    left = Zone(name="left", polygon=((0, 0), (0.5, 0), (0.5, 1.0), (0, 1.0)))
    right = Zone(name="right", polygon=((0.5, 0), (1.0, 0), (1.0, 1.0), (0.5, 1.0)))
    zm = ZoneMap(units="meters", zones=(left, right))
    a = ZoneAnalytics(zm, transition_window_s=10.0)

    # t=1: in right
    objs = [ObjectStateModel(id="0", pos_world=(0.75, 0.5, 0.0))]
    _, ev = a.update(1.0, objs)
    assert any(e.type == "zone_enter" and e.zone == "right" for e in ev)

    # t=2: outside all zones -> exit right (zone becomes None)
    objs = [ObjectStateModel(id="0", pos_world=(2.0, 0.5, 0.0))]
    _, ev = a.update(2.0, objs)
    assert any(e.type == "zone_exit" and e.zone == "right" for e in ev)

    # t=3: enters left -> should count right->left transition
    objs = [ObjectStateModel(id="0", pos_world=(0.25, 0.5, 0.0))]
    _, ev = a.update(3.0, objs)
    assert any(e.type == "zone_enter" and e.zone == "left" for e in ev)
    assert a._transitions.get(("right", "left")) == 1
