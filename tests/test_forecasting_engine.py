# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.contracts.models import (
    ContractRuleSpec,
    SpatialContractPackage,
    SubjectSpec,
)
from metriplane.forecasting.engine import ForecastEngine
from metriplane.schema import ObjectStateModel
from metriplane.sentinel.registry import load_registry
from metriplane.zones import Zone, ZoneMap

REGISTRY = load_registry("configs/objects.example.yaml")

# exit_lane spans x in [2,4], y in [-1,1]
ZONE_MAP = ZoneMap(
    units="meters",
    zones=(Zone(name="exit_lane", polygon=((2.0, -1.0), (4.0, -1.0), (4.0, 1.0), (2.0, 1.0))),),
)

SUBJECTS = {
    "movable": SubjectSpec(object_types=["cart", "pallet"]),
    "people": SubjectSpec(object_types=["human_proxy"]),
}


def obj(marker, x, y, zone=None, vel=None):
    return ObjectStateModel(
        id=str(marker),
        pos_world=(x, y, 0.0),
        vel_world=(vel[0], vel[1], 0.0) if vel else None,
        zone=zone,
    )


def zone_engine():
    pkg = SpatialContractPackage(
        contract_id="t",
        subjects=SUBJECTS,
        rules=[
            ContractRuleSpec(
                id="no_asset_in_exit_lane",
                type="forbidden_zone",
                subject="movable",
                zones=["exit_lane"],
            )
        ],
    )
    return ForecastEngine(
        horizon_s=2.0, step_s=0.2, contract_package=pkg, registry=REGISTRY, zone_map=ZONE_MAP
    )


def dist_engine():
    pkg = SpatialContractPackage(
        contract_id="t",
        subjects=SUBJECTS,
        rules=[
            ContractRuleSpec(
                id="human_proxy_distance",
                type="minimum_distance",
                subject_a="people",
                subject_b="movable",
                distance_m=0.6,
            )
        ],
    )
    return ForecastEngine(
        horizon_s=2.0, step_s=0.2, contract_package=pkg, registry=REGISTRY, zone_map=ZONE_MAP
    )


def test_future_forbidden_zone_emitted():
    e = zone_engine()
    e.update(0.0, [obj(7, 0.0, 0.0)])  # 1 trace point
    fc = e.update(0.5, [obj(7, 1.0, 0.0)])  # vx=2.0, heading into exit_lane
    assert len(fc) == 1
    f = fc[0]
    assert f.forecast_type == "future_forbidden_zone"
    assert f.object_ids == ["cart_01"]
    assert "exit_lane" in f.zones
    assert f.rule_id == "no_asset_in_exit_lane"
    assert f.time_to_violation_s is not None
    assert f.explanation


def test_future_minimum_distance_emitted():
    e = dist_engine()
    e.update(0.0, [obj(3, 0.0, 0.0), obj(7, 3.0, 0.0)])
    fc = e.update(0.5, [obj(3, 0.0, 0.0), obj(7, 2.0, 0.0)])  # cart approaching
    assert len(fc) == 1
    f = fc[0]
    assert f.forecast_type == "future_minimum_distance"
    assert set(f.object_ids) == {"human_proxy_01", "cart_01"}
    assert f.rule_id == "human_proxy_distance"


def test_low_confidence_suppressed():
    # only vel_world (no trace) → confidence 0.4 < min_confidence 0.5
    e = zone_engine()
    fc = e.update(0.0, [obj(7, 1.0, 0.0, vel=(2.0, 0.0))])
    assert fc == []


def test_no_forecast_without_position():
    e = zone_engine()
    e.update(0.0, [ObjectStateModel(id="7", pos_world=None)])
    fc = e.update(0.5, [ObjectStateModel(id="7", pos_world=None)])
    assert fc == []


def test_zone_forecast_skipped_without_zone_map():
    pkg = SpatialContractPackage(
        contract_id="t",
        subjects=SUBJECTS,
        rules=[
            ContractRuleSpec(id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"])
        ],
    )
    e = ForecastEngine(
        horizon_s=2.0, step_s=0.2, contract_package=pkg, registry=REGISTRY, zone_map=None
    )
    e.update(0.0, [obj(7, 0.0, 0.0)])
    fc = e.update(0.5, [obj(7, 1.0, 0.0)])
    assert fc == []  # no zone geometry → no zone forecast, no crash


def test_already_inside_zone_not_forecast():
    e = zone_engine()
    e.update(0.0, [obj(7, 3.0, 0.0, zone="exit_lane")])
    fc = e.update(0.5, [obj(7, 3.0, 0.0, zone="exit_lane")])
    assert fc == []  # already inside is an incident, not a forecast


def test_already_close_not_forecast():
    e = dist_engine()
    e.update(0.0, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    fc = e.update(0.5, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    assert fc == []  # already within distance is current, not forecast


def test_cooldown_suppresses_repeat():
    pkg = SpatialContractPackage(
        contract_id="t",
        subjects=SUBJECTS,
        rules=[
            ContractRuleSpec(
                id="fz",
                type="forbidden_zone",
                subject="movable",
                zones=["exit_lane"],
                cooldown_s=5.0,
            )
        ],
    )
    e = ForecastEngine(
        horizon_s=2.0,
        step_s=0.2,
        contract_package=pkg,
        registry=REGISTRY,
        zone_map=ZONE_MAP,
        cooldown_s=5.0,
    )
    e.update(0.0, [obj(7, 0.0, 0.0)])
    fc1 = e.update(0.5, [obj(7, 1.0, 0.0)])
    fc2 = e.update(1.0, [obj(7, 1.2, 0.0)])  # within cooldown
    assert len(fc1) == 1
    assert fc2 == []


def test_forecast_deterministic():
    e1 = zone_engine()
    e2 = zone_engine()
    e1.update(0.0, [obj(7, 0.0, 0.0)])
    e2.update(0.0, [obj(7, 0.0, 0.0)])
    f1 = e1.update(0.5, [obj(7, 1.0, 0.0)])
    f2 = e2.update(0.5, [obj(7, 1.0, 0.0)])
    assert f1[0].time_to_violation_s == f2[0].time_to_violation_s
    assert f1[0].confidence == f2[0].confidence
