from __future__ import annotations

import copy

from metriplane.schema import FrameStateModel, ObjectStateModel
from metriplane.sentinel.rules import RuleSet


def _first_pos(frames: list[FrameStateModel], marker_id: str):
    for f in frames:
        for o in f.objects:
            if str(o.id) == marker_id and o.pos_world is not None:
                return o.pos_world
    return None


def scale_object_speed(frames: list[FrameStateModel], marker_id: str,
                       factor: float) -> list[FrameStateModel]:
    """
    Scale a target object's displacement relative to its first observed position.

    new_pos = first_pos + (pos - first_pos) * factor

    Lower factors slow the object; the original bundle is never mutated.
    """
    first = _first_pos(frames, marker_id)
    out: list[FrameStateModel] = []
    for f in frames:
        nf = f.model_copy(deep=True)
        nf.objects = [_scale_obj(o, marker_id, first, factor) for o in nf.objects]
        if nf.fused:
            nf.fused = [_scale_obj(o, marker_id, first, factor) for o in nf.fused]
        out.append(nf)
    return out


def _scale_obj(o: ObjectStateModel, marker_id: str, first, factor: float):
    if str(o.id) != marker_id or o.pos_world is None or first is None:
        return o
    nx = first[0] + (o.pos_world[0] - first[0]) * factor
    ny = first[1] + (o.pos_world[1] - first[1]) * factor
    nz = first[2] + (o.pos_world[2] - first[2]) * factor
    return o.model_copy(update={"pos_world": (nx, ny, nz)})


def remove_object(frames: list[FrameStateModel], marker_id: str) -> list[FrameStateModel]:
    out: list[FrameStateModel] = []
    for f in frames:
        nf = f.model_copy(deep=True)
        nf.objects = [o for o in nf.objects if str(o.id) != marker_id]
        if nf.fused:
            nf.fused = [o for o in nf.fused if str(o.id) != marker_id]
        out.append(nf)
    return out


def apply_rule_threshold(ruleset: RuleSet, rule_id: str, field: str,
                         value: float) -> RuleSet:
    new = copy.deepcopy(ruleset)
    found = False
    for r in new.rules:
        if r.id == rule_id:
            if not hasattr(r, field):
                raise ValueError(f"rule {rule_id} has no field {field!r}")
            setattr(r, field, value)
            found = True
    if not found:
        raise ValueError(f"rule not found: {rule_id}")
    return new
