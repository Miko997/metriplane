# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, cast

from pydantic import BaseModel

from metriplane.contracts.models import (
    ContractRuleSpec,
    Severity,
    SpatialContractPackage,
    SubjectSpec,
)
from metriplane.schema import ObjectStateModel
from metriplane.sentinel.events import RuleAlert, SeverityLevel
from metriplane.sentinel.registry import ObjectRegistryConfig

_SEVERITY_TO_ALERT: dict[Severity, SeverityLevel] = {
    "info": "info",
    "warning": "warning",
    "high": "critical",
    "critical": "critical",
}


class ContractEvent(BaseModel):
    """A spatial-contract violation, carrying full provenance for audit."""

    event_id: str
    contract_id: str
    rule_id: str
    rule_type: str
    severity: Severity
    ts: float
    object_ids: list[str]
    zone: str | None = None
    observed_value: float | str | None = None
    threshold_value: float | str | None = None
    explanation: str = ""
    run_id: str | None = None

    def to_rule_alert(self) -> RuleAlert:
        return RuleAlert(
            alert_id=self.event_id,
            rule_id=self.rule_id,
            severity=_SEVERITY_TO_ALERT[self.severity],
            ts=self.ts,
            object_ids=list(self.object_ids),
            zone=self.zone,
            detail={
                "contract_id": self.contract_id,
                "rule_type": self.rule_type,
                "contract_severity": self.severity,
                "observed_value": self.observed_value,
                "threshold_value": self.threshold_value,
                "explanation": self.explanation,
            },
            run_id=self.run_id,
        )


@dataclass
class _CState:
    object_id: str
    marker_id: str
    type: str | None
    tags: list[str] = field(default_factory=list)
    zone: str | None = None
    zone_since: float | None = None
    last_seen: float | None = None
    pos: tuple[float, float] | None = None
    speed: float | None = None
    vel: tuple[float, float] | None = None
    present: bool = False


class SpatialContractEngine:
    """
    Evaluates a SpatialContractPackage against a stream of object states.

    Stateful across frames: tracks zone dwell, cooldowns, and continuous
    distance-violation durations so events do not spam and duration thresholds
    are honored. Event IDs are sequential for deterministic replay.
    """

    def __init__(
        self, package: SpatialContractPackage, registry: ObjectRegistryConfig | None = None
    ):
        self.package = package
        self.registry = registry
        self.run_id: str | None = None
        self._objects: dict[str, _CState] = {}
        self._seq = 0
        # cooldown: (rule_id, entity_key) -> last emit ts
        self._cooldown: dict[tuple[str, str], float] = {}
        # continuous distance-violation start: (rule_id, pair_key) -> ts
        self._dist_since: dict[tuple[str, str], float] = {}

    # -- helpers -----------------------------------------------------------

    def _next_id(self) -> str:
        self._seq += 1
        return f"cevt_{self._seq:06d}"

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
    def _subject_matches(spec: SubjectSpec, st: _CState) -> bool:
        matched = False
        if spec.object_ids:
            if st.object_id not in spec.object_ids:
                return False
            matched = True
        if spec.object_types:
            if st.type not in spec.object_types:
                return False
            matched = True
        if spec.tags:
            if not all(t in st.tags for t in spec.tags):
                return False
            matched = True
        if spec.zones:
            if st.zone not in spec.zones:
                return False
            matched = True
        return matched

    def _subjects_present(self, subject_name: str | None) -> list[_CState]:
        if subject_name is None:
            return []
        spec = self.package.subjects.get(subject_name)
        if spec is None:
            return []
        return [
            st
            for st in sorted(self._objects.values(), key=lambda s: s.object_id)
            if st.present and self._subject_matches(spec, st)
        ]

    def _cooldown_ok(self, rule: ContractRuleSpec, key: str, ts: float) -> bool:
        if rule.cooldown_s <= 0:
            return True
        last = self._cooldown.get((rule.id, key))
        if last is None or (ts - last) >= rule.cooldown_s:
            return True
        return False

    def _mark(self, rule: ContractRuleSpec, key: str, ts: float) -> None:
        self._cooldown[(rule.id, key)] = ts

    def _event(
        self,
        rule: ContractRuleSpec,
        ts: float,
        object_ids: list[str],
        zone: str | None,
        observed: Any,
        threshold: Any,
        explanation: str,
    ) -> ContractEvent:
        return ContractEvent(
            event_id=self._next_id(),
            contract_id=self.package.contract_id,
            rule_id=rule.id,
            rule_type=rule.type,
            severity=rule.severity,
            ts=ts,
            object_ids=object_ids,
            zone=zone,
            observed_value=observed,
            threshold_value=threshold,
            explanation=explanation,
            run_id=self.run_id,
        )

    # -- per-frame update --------------------------------------------------

    def update(self, ts: float, objects: list[ObjectStateModel]) -> list[ContractEvent]:
        for st in self._objects.values():
            st.present = False

        for obj in sorted(objects, key=lambda o: str(o.id)):
            object_id, otype, tags = self._resolve(str(obj.id))
            state = self._objects.get(object_id)
            if state is None:
                state = _CState(object_id=object_id, marker_id=str(obj.id), type=otype, tags=tags)
                self._objects[object_id] = state
            state.present = True

            x = obj.pos_world[0] if obj.pos_world else None
            y = obj.pos_world[1] if obj.pos_world else None
            new_pos = (x, y) if x is not None and y is not None else None

            vel: tuple[float, float] | None = None
            speed: float | None = None
            if obj.vel_world:
                vel = (obj.vel_world[0], obj.vel_world[1])
                speed = math.hypot(vel[0], vel[1])
            elif new_pos is not None and state.pos is not None and state.last_seen is not None:
                dt = ts - state.last_seen
                if dt > 0:
                    vx = (new_pos[0] - state.pos[0]) / dt
                    vy = (new_pos[1] - state.pos[1]) / dt
                    vel = (vx, vy)
                    speed = math.hypot(vx, vy)
            state.vel = vel
            state.speed = speed
            if new_pos is not None:
                state.pos = new_pos

            if obj.zone != state.zone:
                state.zone = obj.zone
                state.zone_since = ts
            state.last_seen = ts

        events: list[ContractEvent] = []
        for rule in self.package.rules:
            if not rule.enabled:
                continue
            events.extend(self._eval(rule, ts))
        return events

    # -- rule evaluation ---------------------------------------------------

    def _eval(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        fn = cast(
            Callable[[ContractRuleSpec, float], list[ContractEvent]] | None,
            getattr(self, f"_eval_{rule.type}", None),
        )
        if fn is None:
            return []
        return fn(rule, ts)

    def _eval_forbidden_zone(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        for st in self._subjects_present(rule.subject):
            if st.zone in rule.zones and self._cooldown_ok(rule, st.object_id, ts):
                self._mark(rule, st.object_id, ts)
                out.append(
                    self._event(
                        rule,
                        ts,
                        [st.object_id],
                        st.zone,
                        st.zone,
                        ",".join(rule.zones),
                        f"{st.object_id} entered forbidden zone {st.zone}",
                    )
                )
        return out

    def _eval_zone_occupancy_duration(
        self, rule: ContractRuleSpec, ts: float
    ) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        max_duration_s = rule.max_duration_s
        if max_duration_s is None:
            return out
        for st in self._subjects_present(rule.subject):
            if st.zone in rule.zones and st.zone_since is not None:
                dwell = ts - st.zone_since
                if dwell >= max_duration_s and self._cooldown_ok(rule, st.object_id, ts):
                    self._mark(rule, st.object_id, ts)
                    out.append(
                        self._event(
                            rule,
                            ts,
                            [st.object_id],
                            st.zone,
                            round(dwell, 3),
                            max_duration_s,
                            f"{st.object_id} occupied {st.zone} for {round(dwell, 1)}s",
                        )
                    )
        return out

    def _eval_minimum_distance(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        distance_m = rule.distance_m
        if distance_m is None:
            return out
        a_list = self._subjects_present(rule.subject_a)
        b_list = self._subjects_present(rule.subject_b)
        min_dur = rule.min_duration_s or 0.0
        seen: set[tuple[str, str]] = set()
        active_now: set[tuple[str, str]] = set()
        for a in a_list:
            for b in b_list:
                if a.object_id == b.object_id:
                    continue
                key = (min(a.object_id, b.object_id), max(a.object_id, b.object_id))
                if key in seen:
                    continue
                seen.add(key)
                if a.pos is None or b.pos is None:
                    continue
                d = math.hypot(a.pos[0] - b.pos[0], a.pos[1] - b.pos[1])
                if d < distance_m:
                    active_now.add(key)
                    start = self._dist_since.get((rule.id, "|".join(key)))
                    if start is None:
                        start = ts
                        self._dist_since[(rule.id, "|".join(key))] = ts
                    if (ts - start) >= min_dur and self._cooldown_ok(rule, "|".join(key), ts):
                        self._mark(rule, "|".join(key), ts)
                        out.append(
                            self._event(
                                rule,
                                ts,
                                list(key),
                                a.zone or b.zone,
                                round(d, 3),
                                distance_m,
                                f"{key[0]} and {key[1]} within {round(d, 3)}m (< {distance_m}m)",
                            )
                        )
        # clear duration state for pairs no longer in violation
        for dkey in list(self._dist_since.keys()):
            if dkey[0] == rule.id:
                pair = cast(tuple[str, str], tuple(dkey[1].split("|")))
                if pair not in active_now:
                    del self._dist_since[dkey]
        return out

    def _eval_speed_limit(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        max_speed_mps = rule.max_speed_mps
        if max_speed_mps is None:
            return out
        for st in self._subjects_present(rule.subject):
            if st.speed is not None and st.speed > max_speed_mps:
                if self._cooldown_ok(rule, st.object_id, ts):
                    self._mark(rule, st.object_id, ts)
                    out.append(
                        self._event(
                            rule,
                            ts,
                            [st.object_id],
                            st.zone,
                            round(st.speed, 3),
                            max_speed_mps,
                            f"{st.object_id} moving at {round(st.speed, 2)} m/s "
                            f"(> {max_speed_mps})",
                        )
                    )
        return out

    def _eval_missing_object(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        missing_after_s = rule.missing_after_s
        if rule.subject is None or missing_after_s is None:
            return out
        spec = self.package.subjects.get(rule.subject)
        if spec is None:
            return out
        for st in sorted(self._objects.values(), key=lambda s: s.object_id):
            if st.present or st.last_seen is None:
                continue
            if not self._subject_matches(spec, st):
                continue
            missing_for = ts - st.last_seen
            if missing_for > missing_after_s and self._cooldown_ok(rule, st.object_id, ts):
                self._mark(rule, st.object_id, ts)
                out.append(
                    self._event(
                        rule,
                        ts,
                        [st.object_id],
                        None,
                        round(missing_for, 3),
                        missing_after_s,
                        f"{st.object_id} missing for {round(missing_for, 1)}s",
                    )
                )
        return out

    def _eval_forbidden_direction(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        min_speed = rule.min_speed_mps or 0.0
        for st in self._subjects_present(rule.subject):
            if st.zone not in rule.zones or st.vel is None:
                continue
            vx, vy = st.vel
            wrong, axis_speed = _wrong_direction(rule.allowed_direction, vx, vy)
            if wrong and axis_speed >= min_speed and self._cooldown_ok(rule, st.object_id, ts):
                self._mark(rule, st.object_id, ts)
                out.append(
                    self._event(
                        rule,
                        ts,
                        [st.object_id],
                        st.zone,
                        f"({round(vx, 2)},{round(vy, 2)})",
                        rule.allowed_direction,
                        f"{st.object_id} moving against allowed direction "
                        f"{rule.allowed_direction} in {st.zone}",
                    )
                )
        return out

    def _eval_zone_capacity(self, rule: ContractRuleSpec, ts: float) -> list[ContractEvent]:
        out: list[ContractEvent] = []
        max_count = rule.max_count
        if max_count is None:
            return out
        present = self._subjects_present(rule.subject)
        for zone in rule.zones:
            in_zone = [st for st in present if st.zone == zone]
            if len(in_zone) > max_count and self._cooldown_ok(rule, zone, ts):
                self._mark(rule, zone, ts)
                out.append(
                    self._event(
                        rule,
                        ts,
                        [st.object_id for st in in_zone],
                        zone,
                        len(in_zone),
                        max_count,
                        f"{len(in_zone)} objects in {zone} (> {max_count})",
                    )
                )
        return out


def _wrong_direction(allowed: str | None, vx: float, vy: float) -> tuple[bool, float]:
    """Return (is_wrong_way, speed_along_relevant_axis)."""
    if allowed == "left_to_right":
        return (vx < 0, abs(vx))
    if allowed == "right_to_left":
        return (vx > 0, abs(vx))
    if allowed == "bottom_to_top":
        return (vy < 0, abs(vy))
    if allowed == "top_to_bottom":
        return (vy > 0, abs(vy))
    return (False, 0.0)
