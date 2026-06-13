from __future__ import annotations

from metriplane.counterfactuals.transforms import (
    apply_rule_threshold,
    remove_object,
    scale_object_speed,
)
from metriplane.schema import FrameStateModel, ObjectStateModel
from metriplane.sentinel.rules import RuleDefinition, RuleSet


def frame(ts, fid, objs):
    return FrameStateModel(
        source_backend="dummy", ts=ts, frame_id=fid,
        objects=[ObjectStateModel(id=i, pos_world=(x, y, 0.0)) for i, x, y in objs])


def test_object_removal():
    frames = [frame(0.0, 0, [("7", 0.0, 0.0), ("3", 1.0, 0.0)])]
    out = remove_object(frames, "3")
    assert [str(o.id) for o in out[0].objects] == ["7"]


def test_object_removal_does_not_mutate_original():
    frames = [frame(0.0, 0, [("7", 0.0, 0.0), ("3", 1.0, 0.0)])]
    remove_object(frames, "3")
    assert len(frames[0].objects) == 2  # original untouched


def test_speed_scaling_changes_positions():
    frames = [
        frame(0.0, 0, [("3", 1.0, 0.0)]),
        frame(1.0, 1, [("3", 0.0, 0.0)]),
    ]
    out = scale_object_speed(frames, "3", 0.5)
    # first frame unchanged, second frame halfway: 1.0 + (0.0-1.0)*0.5 = 0.5
    assert out[0].objects[0].pos_world[0] == 1.0
    assert abs(out[1].objects[0].pos_world[0] - 0.5) < 1e-9


def test_speed_scaling_does_not_mutate_original():
    frames = [frame(0.0, 0, [("3", 1.0, 0.0)]), frame(1.0, 1, [("3", 0.0, 0.0)])]
    scale_object_speed(frames, "3", 0.5)
    assert frames[1].objects[0].pos_world[0] == 0.0


def test_speed_scaling_ignores_other_objects():
    frames = [frame(0.0, 0, [("7", 5.0, 0.0)]), frame(1.0, 1, [("7", 9.0, 0.0)])]
    out = scale_object_speed(frames, "3", 0.5)  # target absent
    assert out[1].objects[0].pos_world[0] == 9.0


def test_apply_rule_threshold():
    rs = RuleSet(rules=[RuleDefinition(id="r", type="min_distance",
                                       min_distance_m=0.6)])
    new = apply_rule_threshold(rs, "r", "min_distance_m", 0.2)
    assert new.rules[0].min_distance_m == 0.2
    assert rs.rules[0].min_distance_m == 0.6  # original unchanged


def test_apply_rule_threshold_unknown_rule():
    rs = RuleSet(rules=[RuleDefinition(id="r", type="min_distance",
                                       min_distance_m=0.6)])
    try:
        apply_rule_threshold(rs, "ghost", "min_distance_m", 0.2)
        assert False, "expected ValueError"
    except ValueError:
        pass
