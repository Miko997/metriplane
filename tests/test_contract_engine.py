# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.contracts.engine import SpatialContractEngine
from metriplane.contracts.models import (
    ContractRuleSpec,
    SpatialContractPackage,
    SubjectSpec,
)
from metriplane.schema import ObjectStateModel
from metriplane.sentinel.registry import load_registry

REGISTRY = load_registry("configs/objects.example.yaml")

# marker 7 = cart_01 (cart), 12 = pallet_01 (pallet), 3 = human_proxy_01 (human_proxy)
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


def engine(rule):
    pkg = SpatialContractPackage(contract_id="t", subjects=SUBJECTS, rules=[rule])
    return SpatialContractEngine(pkg, REGISTRY)


def test_forbidden_zone_emits():
    e = engine(
        ContractRuleSpec(id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"])
    )
    events = e.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    assert len(events) == 1
    ev = events[0]
    assert ev.rule_id == "fz"
    assert ev.contract_id == "t"
    assert ev.object_ids == ["cart_01"]
    assert ev.explanation


def test_forbidden_zone_cooldown_suppresses():
    e = engine(
        ContractRuleSpec(
            id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"], cooldown_s=5.0
        )
    )
    e.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    e2 = e.update(1.0, [obj(7, 1.0, 1.0, zone="exit_lane")])  # within cooldown
    assert e2 == []
    e3 = e.update(6.0, [obj(7, 1.0, 1.0, zone="exit_lane")])  # cooldown expired
    assert len(e3) == 1


def test_minimum_distance_emits_after_min_duration():
    e = engine(
        ContractRuleSpec(
            id="md",
            type="minimum_distance",
            subject_a="people",
            subject_b="movable",
            distance_m=0.6,
            min_duration_s=0.3,
        )
    )
    # close at t=0 but min_duration not yet met
    ev0 = e.update(0.0, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    assert ev0 == []
    # 0.5s later → duration satisfied
    ev1 = e.update(0.5, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    assert len(ev1) == 1
    assert set(ev1[0].object_ids) == {"human_proxy_01", "cart_01"}


def test_minimum_distance_resets_when_apart():
    e = engine(
        ContractRuleSpec(
            id="md",
            type="minimum_distance",
            subject_a="people",
            subject_b="movable",
            distance_m=0.6,
            min_duration_s=0.3,
        )
    )
    e.update(0.0, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    # move apart → resets continuous-violation timer
    e.update(0.5, [obj(3, 0.0, 0.0), obj(7, 5.0, 0.0)])
    # come back close: timer restarts, so immediate frame should not emit
    ev = e.update(0.6, [obj(3, 0.0, 0.0), obj(7, 0.3, 0.0)])
    assert ev == []


def test_zone_occupancy_duration_emits():
    e = engine(
        ContractRuleSpec(
            id="zo",
            type="zone_occupancy_duration",
            subject="movable",
            zones=["exit_lane"],
            max_duration_s=5.0,
        )
    )
    for t in range(0, 5):
        ev = e.update(float(t), [obj(12, 1.0, 1.0, zone="exit_lane")])
        assert ev == []  # dwell < 5.0
    ev = e.update(5.0, [obj(12, 1.0, 1.0, zone="exit_lane")])
    assert len(ev) == 1
    assert ev[0].object_ids == ["pallet_01"]


def test_forbidden_direction_emits_wrong_way():
    e = engine(
        ContractRuleSpec(
            id="dir",
            type="forbidden_direction",
            subject="movable",
            zones=["packing_lane"],
            allowed_direction="left_to_right",
            min_speed_mps=0.05,
        )
    )
    # moving right_to_left (vx negative) in packing_lane → wrong way
    ev = e.update(0.0, [obj(7, 1.0, 1.0, zone="packing_lane", vel=(-0.5, 0.0))])
    assert len(ev) == 1
    assert ev[0].rule_id == "dir"


def test_forbidden_direction_allows_correct_way():
    e = engine(
        ContractRuleSpec(
            id="dir",
            type="forbidden_direction",
            subject="movable",
            zones=["packing_lane"],
            allowed_direction="left_to_right",
            min_speed_mps=0.05,
        )
    )
    ev = e.update(0.0, [obj(7, 1.0, 1.0, zone="packing_lane", vel=(0.5, 0.0))])
    assert ev == []


def test_speed_limit_emits():
    e = engine(ContractRuleSpec(id="sp", type="speed_limit", subject="movable", max_speed_mps=1.5))
    ev = e.update(0.0, [obj(7, 0.0, 0.0, vel=(2.0, 0.0))])
    assert len(ev) == 1
    assert ev[0].observed_value == 2.0


def test_zone_capacity_emits():
    e = engine(
        ContractRuleSpec(
            id="cap", type="zone_capacity", subject="movable", zones=["dock"], max_count=1
        )
    )
    ev = e.update(0.0, [obj(7, 0.0, 0.0, zone="dock"), obj(12, 1.0, 0.0, zone="dock")])
    assert len(ev) == 1
    assert ev[0].observed_value == 2
    assert set(ev[0].object_ids) == {"cart_01", "pallet_01"}


def test_disabled_rule_does_not_emit():
    e = engine(
        ContractRuleSpec(
            id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"], enabled=False
        )
    )
    ev = e.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    assert ev == []


def test_event_has_full_provenance():
    e = engine(
        ContractRuleSpec(id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"])
    )
    ev = e.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])[0]
    assert ev.contract_id == "t"
    assert ev.rule_id == "fz"
    assert ev.rule_type == "forbidden_zone"
    assert ev.observed_value is not None
    assert ev.threshold_value is not None
    assert ev.explanation


def test_event_ids_deterministic_and_sequential():
    e1 = engine(
        ContractRuleSpec(id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"])
    )
    e2 = engine(
        ContractRuleSpec(id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"])
    )
    ev1 = e1.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    ev2 = e2.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    assert ev1[0].event_id == ev2[0].event_id == "cevt_000001"


def test_to_rule_alert_maps_high_to_critical():
    e = engine(
        ContractRuleSpec(
            id="fz", type="forbidden_zone", subject="movable", zones=["exit_lane"], severity="high"
        )
    )
    ev = e.update(0.0, [obj(7, 1.0, 1.0, zone="exit_lane")])[0]
    alert = ev.to_rule_alert()
    assert alert.severity == "critical"
    assert alert.detail["contract_severity"] == "high"
