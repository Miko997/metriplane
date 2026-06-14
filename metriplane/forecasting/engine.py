# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import math
from dataclasses import dataclass, field

from metriplane.contracts.models import SpatialContractPackage, SubjectSpec
from metriplane.forecasting.models import ProjectedPointModel, RiskForecastModel
from metriplane.forecasting.projector import project_path
from metriplane.forecasting.velocity import VelocityEstimator
from metriplane.schema import ObjectStateModel
from metriplane.sentinel.registry import ObjectRegistryConfig
from metriplane.zones import ZoneMap


@dataclass
class _Obj:
    object_id: str
    type: str | None
    tags: list[str]
    zone: str | None
    pos: tuple[float, float] | None
    vx: float
    vy: float
    confidence: float


def _match(spec: SubjectSpec, o: _Obj) -> bool:
    matched = False
    if spec.object_ids:
        if o.object_id not in spec.object_ids:
            return False
        matched = True
    if spec.object_types:
        if o.type not in spec.object_types:
            return False
        matched = True
    if spec.tags:
        if not all(t in o.tags for t in spec.tags):
            return False
        matched = True
    if spec.zones:
        if o.zone not in spec.zones:
            return False
        matched = True
    return matched


@dataclass
class ForecastEngine:
    horizon_s: float = 2.0
    step_s: float = 0.2
    min_confidence: float = 0.5
    max_projected_points: int = 12
    include_projected_path: bool = True
    cooldown_s: float = 0.0
    contract_package: SpatialContractPackage | None = None
    registry: ObjectRegistryConfig | None = None
    zone_map: ZoneMap | None = None

    _vel: VelocityEstimator = field(default_factory=VelocityEstimator)
    _seq: int = 0
    _cooldown: dict[tuple[str, str], float] = field(default_factory=dict)
    run_id: str | None = None

    def _resolve(self, raw_id: str) -> tuple[str, str | None, list[str]]:
        if self.registry is not None:
            try:
                entry = self.registry.by_marker_id(int(raw_id))
            except (TypeError, ValueError):
                entry = None
            if entry is not None:
                return entry.object_id, entry.type, list(entry.tags)
        return f"marker_{raw_id}", None, []

    def _subject(self, name: str | None) -> SubjectSpec | None:
        if name is None or self.contract_package is None:
            return None
        return self.contract_package.subjects.get(name)

    def _cooldown_ok(self, rule_id: str, key: str, ts: float) -> bool:
        if self.cooldown_s <= 0:
            return True
        last = self._cooldown.get((rule_id, key))
        return last is None or (ts - last) >= self.cooldown_s

    def _mark(self, rule_id: str, key: str, ts: float) -> None:
        self._cooldown[(rule_id, key)] = ts

    def update(self, ts: float, objects: list[ObjectStateModel]) -> list[RiskForecastModel]:
        resolved: list[_Obj] = []
        for obj in sorted(objects, key=lambda o: str(o.id)):
            object_id, otype, tags = self._resolve(str(obj.id))
            pos = ((obj.pos_world[0], obj.pos_world[1])
                   if obj.pos_world else None)
            self._vel.observe(object_id, ts, pos)
            vel_world = ((obj.vel_world[0], obj.vel_world[1])
                         if obj.vel_world else None)
            est = self._vel.estimate(object_id, vel_world)
            resolved.append(_Obj(object_id, otype, tags, obj.zone, pos,
                                 est.vx, est.vy, est.confidence))

        if self.contract_package is None:
            return []

        out: list[RiskForecastModel] = []
        for rule in self.contract_package.rules:
            if not rule.enabled:
                continue
            if rule.type == "forbidden_zone":
                out.extend(self._forecast_zone(rule, ts, resolved))
            elif rule.type == "minimum_distance":
                out.extend(self._forecast_distance(rule, ts, resolved))
        return out

    def _forecast_zone(self, rule, ts, resolved):
        out = []
        if self.zone_map is None:
            return out
        spec = self._subject(rule.subject)
        if spec is None:
            return out
        for o in resolved:
            if o.pos is None or o.confidence < self.min_confidence:
                continue
            if not _match(spec, o):
                continue
            if o.zone in rule.zones:
                continue  # already inside; that's an incident, not a forecast
            path = project_path((o.pos[0], o.pos[1]), (o.vx, o.vy),
                                self.horizon_s, self.step_s, self.max_projected_points)
            hit_dt = None
            hit_zone = None
            for dt, x, y in path:
                z = self.zone_map.zone_for_xy(x, y)
                if z in rule.zones:
                    hit_dt, hit_zone = dt, z
                    break
            if hit_dt is not None:
                if not self._cooldown_ok(rule.id, o.object_id, ts):
                    continue
                self._mark(rule.id, o.object_id, ts)
                out.append(self._mk(
                    "future_forbidden_zone", rule, ts, [o.object_id],
                    [hit_zone], hit_dt, o.confidence, path,
                    f"{o.object_id} projected to enter {hit_zone} in {hit_dt}s"))
        return out

    def _forecast_distance(self, rule, ts, resolved):
        out = []
        spec_a = self._subject(rule.subject_a)
        spec_b = self._subject(rule.subject_b)
        if spec_a is None or spec_b is None:
            return out
        a_list = [o for o in resolved if o.pos is not None and _match(spec_a, o)]
        b_list = [o for o in resolved if o.pos is not None and _match(spec_b, o)]
        seen: set[tuple[str, str]] = set()
        for a in a_list:
            for b in b_list:
                if a.object_id == b.object_id:
                    continue
                key = tuple(sorted((a.object_id, b.object_id)))
                if key in seen:
                    continue
                seen.add(key)
                cur = math.hypot(a.pos[0] - b.pos[0], a.pos[1] - b.pos[1])
                if cur < rule.distance_m:
                    continue  # already violating; that's current, not forecast
                conf = min(a.confidence, b.confidence)
                if conf < self.min_confidence:
                    continue
                pa = project_path(a.pos, (a.vx, a.vy), self.horizon_s,
                                  self.step_s, self.max_projected_points)
                pb = project_path(b.pos, (b.vx, b.vy), self.horizon_s,
                                  self.step_s, self.max_projected_points)
                hit_dt = None
                for (dt, ax, ay), (_, bx, by) in zip(pa, pb):
                    if math.hypot(ax - bx, ay - by) < rule.distance_m:
                        hit_dt = dt
                        break
                if hit_dt is not None:
                    if not self._cooldown_ok(rule.id, "|".join(key), ts):
                        continue
                    self._mark(rule.id, "|".join(key), ts)
                    out.append(self._mk(
                        "future_minimum_distance", rule, ts, list(key), [],
                        hit_dt, conf, pa,
                        f"{key[0]} and {key[1]} projected within "
                        f"{rule.distance_m}m in {hit_dt}s"))
        return out

    def _mk(self, ftype, rule, ts, object_ids, zones, ttv, conf, path, explanation):
        self._seq += 1
        projected = []
        if self.include_projected_path:
            projected = [ProjectedPointModel(dt_s=dt, pos_world=(x, y, 0.0))
                         for dt, x, y in path]
        return RiskForecastModel(
            forecast_type=ftype,
            severity=rule.severity,
            ts=ts,
            horizon_s=self.horizon_s,
            time_to_violation_s=ttv,
            confidence=round(conf, 3),
            object_ids=object_ids,
            zones=zones,
            contract_id=self.contract_package.contract_id,
            rule_id=rule.id,
            explanation=explanation,
            projected_path=projected,
            metadata={"forecast_seq": self._seq},
        )
