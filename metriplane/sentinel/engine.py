# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from metriplane.schema import FrameStateModel, frame_time_s
from metriplane.sentinel.events import RuleAlert
from metriplane.sentinel.registry import ObjectRegistryConfig
from metriplane.sentinel.rules import ObjectFilter, RuleDefinition, RuleSet


def iter_frames(session_path: str | Path) -> Iterator[FrameStateModel]:
    """Yield validated frames, rejecting malformed non-header records."""
    for line_number, line in enumerate(
        Path(session_path).read_text().splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if isinstance(record, dict) and record.get("type") == "run_header":
                continue
            yield FrameStateModel.model_validate(record)
        except Exception as exc:
            raise ValueError(
                f"invalid frame record at {session_path}:{line_number}: {exc}"
            ) from exc
            continue


@dataclass
class _TrackedObject:
    object_id: str
    marker_id: str
    type: str | None
    tags: list[str] = field(default_factory=list)
    zone: str | None = None
    prev_zone: str | None = None
    zone_since: float | None = None
    last_seen: float | None = None
    pos: tuple[float, float] | None = None
    speed: float | None = None
    present: bool = False


class RuleEngine:
    """
    Evaluates a RuleSet against a stream of FrameStateModel frames.

    Emits one RuleAlert per frame while a rule condition holds; the incident
    engine groups consecutive alerts into incidents. Alert IDs are sequential
    (alert_000001, ...) so output is deterministic across replays.
    """

    def __init__(self, ruleset: RuleSet, registry: ObjectRegistryConfig | None = None):
        self.ruleset = ruleset
        self.registry = registry
        self.run_id: str | None = None
        self._objects: dict[str, _TrackedObject] = {}
        self._alert_seq = 0

    def _next_alert_id(self) -> str:
        self._alert_seq += 1
        return f"alert_{self._alert_seq:06d}"

    def _resolve(self, raw_id: str) -> tuple[str, str | None, list[str]]:
        if self.registry is not None:
            try:
                entry = self.registry.by_marker_id(int(raw_id))
            except (TypeError, ValueError):
                entry = None
            if entry is not None:
                return entry.object_id, entry.type, list(entry.tags)
        return f"marker_{raw_id}", None, []

    @staticmethod
    def _matches(f: ObjectFilter | None, st: _TrackedObject) -> bool:
        if f is None:
            return True
        return f.matches(obj_type=st.type, obj_id=st.object_id, obj_tags=st.tags)

    def _present_matching(self, f: ObjectFilter | None) -> list[_TrackedObject]:
        return [st for st in sorted(self._objects.values(), key=lambda s: s.object_id)
                if st.present and self._matches(f, st)]

    def _mk_alert(self, rule: RuleDefinition, ts: float, object_ids: list[str],
                  zone: str | None, detail: dict) -> RuleAlert:
        return RuleAlert(
            alert_id=self._next_alert_id(),
            rule_id=rule.id,
            severity=rule.severity,
            ts=ts,
            object_ids=object_ids,
            zone=zone,
            detail=detail,
            run_id=self.run_id,
        )

    def process_frame(self, frame: FrameStateModel) -> list[RuleAlert]:
        if frame.run_id and not self.run_id:
            self.run_id = frame.run_id
        ts = frame_time_s(frame)
        observed = frame.fused if frame.fused is not None else frame.objects

        for st in self._objects.values():
            st.present = False

        transitions: list[tuple[_TrackedObject, str | None, str | None]] = []
        for obj in sorted(observed, key=lambda o: str(o.id)):
            object_id, otype, tags = self._resolve(str(obj.id))
            st = self._objects.get(object_id)
            if st is None:
                st = _TrackedObject(object_id=object_id, marker_id=str(obj.id),
                                    type=otype, tags=tags)
                self._objects[object_id] = st
            st.present = True

            x = obj.pos_world[0] if obj.pos_world else None
            y = obj.pos_world[1] if obj.pos_world else None
            new_pos = (x, y) if x is not None and y is not None else None

            speed: float | None = None
            if obj.vel_world:
                speed = math.hypot(obj.vel_world[0], obj.vel_world[1])
            elif new_pos is not None and st.pos is not None and st.last_seen is not None:
                dt = ts - st.last_seen
                if dt > 0:
                    speed = math.hypot(new_pos[0] - st.pos[0], new_pos[1] - st.pos[1]) / dt
            st.speed = speed

            if new_pos is not None:
                st.pos = new_pos

            if obj.zone != st.zone:
                transitions.append((st, st.zone, obj.zone))
                st.prev_zone = st.zone
                st.zone = obj.zone
                st.zone_since = ts

            st.last_seen = ts

        alerts: list[RuleAlert] = []
        for rule in self.ruleset.rules:
            alerts.extend(self._eval_rule(rule, ts, transitions))
        return alerts

    def _eval_rule(self, rule: RuleDefinition, ts: float,
                   transitions: list[tuple[_TrackedObject, str | None, str | None]],
                   ) -> list[RuleAlert]:
        out: list[RuleAlert] = []

        if rule.type == "forbidden_zone":
            if rule.zone is None:
                return out
            for st in self._present_matching(rule.object_filter):
                if st.zone == rule.zone:
                    out.append(self._mk_alert(rule, ts, [st.object_id], st.zone, {}))

        elif rule.type == "max_dwell":
            if rule.zone is None or rule.max_duration_s is None:
                return out
            for st in self._present_matching(rule.object_filter):
                if st.zone == rule.zone and st.zone_since is not None:
                    dwell = ts - st.zone_since
                    if dwell >= rule.max_duration_s:
                        out.append(self._mk_alert(rule, ts, [st.object_id], st.zone,
                                                  {"dwell_s": round(dwell, 3)}))

        elif rule.type == "min_distance":
            if rule.min_distance_m is None:
                return out
            a_list = self._present_matching(rule.object_filter_a)
            b_list = self._present_matching(rule.object_filter_b)
            seen_pairs: set[tuple[str, str]] = set()
            for a in a_list:
                for b in b_list:
                    if a.object_id == b.object_id:
                        continue
                    key = tuple(sorted((a.object_id, b.object_id)))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    if a.pos is None or b.pos is None:
                        continue
                    d = math.hypot(a.pos[0] - b.pos[0], a.pos[1] - b.pos[1])
                    if d < rule.min_distance_m:
                        out.append(self._mk_alert(rule, ts, list(key),
                                                  a.zone or b.zone,
                                                  {"distance_m": round(d, 3)}))

        elif rule.type == "speed_limit":
            if rule.max_speed_mps is None:
                return out
            for st in self._present_matching(rule.object_filter):
                if st.speed is not None and st.speed > rule.max_speed_mps:
                    out.append(self._mk_alert(rule, ts, [st.object_id], st.zone,
                                              {"speed_mps": round(st.speed, 3)}))

        elif rule.type == "missing_object":
            if rule.max_duration_s is None:
                return out
            for st in sorted(self._objects.values(), key=lambda s: s.object_id):
                if st.present or st.last_seen is None:
                    continue
                if not self._matches(rule.object_filter, st):
                    continue
                missing_for = ts - st.last_seen
                if missing_for > rule.max_duration_s:
                    out.append(self._mk_alert(rule, ts, [st.object_id], None,
                                              {"missing_for_s": round(missing_for, 3)}))

        elif rule.type == "restricted_transition":
            for st, old, new in transitions:
                if not self._matches(rule.object_filter, st):
                    continue
                if old == rule.from_zone and new == rule.to_zone:
                    out.append(self._mk_alert(rule, ts, [st.object_id], new,
                                              {"from_zone": old, "to_zone": new}))

        return out


def evaluate_session(
    session_path: str | Path,
    ruleset: RuleSet,
    registry: ObjectRegistryConfig | None = None,
) -> tuple[list[RuleAlert], str | None]:
    """Run the rule engine over a full session JSONL. Returns (alerts, run_id)."""
    engine = RuleEngine(ruleset, registry)
    alerts: list[RuleAlert] = []
    for frame in iter_frames(session_path):
        alerts.extend(engine.process_frame(frame))
    return alerts, engine.run_id
