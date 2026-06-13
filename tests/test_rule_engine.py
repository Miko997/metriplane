from __future__ import annotations

import json

import pytest

from metriplane.sentinel.engine import RuleEngine, evaluate_session
from metriplane.sentinel.registry import ObjectRegistryConfig, load_registry
from metriplane.sentinel.rules import (
    ObjectFilter,
    RuleDefinition,
    RuleSet,
    load_rules,
)

CONFIG_OBJECTS = "configs/objects.example.yaml"
CONFIG_RULES = "configs/rules.example.yaml"


def make_frame(ts, frame_id, objects, run_id="rule_test"):
    objs = [
        {
            "id": str(o["id"]),
            "pos_world": o.get("pos"),
            "vel_world": o.get("vel"),
            "zone": o.get("zone"),
        }
        for o in objects
    ]
    return json.dumps({
        "schema_version": "1.0", "source_backend": "dummy", "run_id": run_id,
        "ts": ts, "frame_id": frame_id, "objects": objs, "events": [],
    })


def write_session(tmp_path, lines, name="session.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture
def registry():
    return load_registry(CONFIG_OBJECTS)


# --- forbidden_zone -------------------------------------------------------

def test_forbidden_zone_triggers(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="no_cart_in_exit", type="forbidden_zone",
        object_filter=ObjectFilter(type="cart"), zone="exit_lane",
        severity="warning",
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(2.0, 2, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) == 2
    assert all(a.rule_id == "no_cart_in_exit" for a in alerts)
    assert alerts[0].object_ids == ["cart_01"]


def test_forbidden_zone_no_match_other_type(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="no_cart_in_exit", type="forbidden_zone",
        object_filter=ObjectFilter(type="cart"), zone="exit_lane",
    )])
    # pallet (marker 12), not a cart, in exit_lane → no alert
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 12, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert alerts == []


# --- max_dwell ------------------------------------------------------------

def test_max_dwell_triggers_after_threshold(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="pallet_dwell", type="max_dwell",
        object_filter=ObjectFilter(type="pallet"), zone="exit_lane",
        max_duration_s=5.0, severity="critical",
    )])
    lines = [
        make_frame(float(t), t, [{"id": 12, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}])
        for t in range(0, 8)
    ]
    session = write_session(tmp_path, lines)
    alerts, _ = evaluate_session(session, rules, registry)
    # dwell hits 5.0 at ts=5, then 6, 7 → 3 alerts
    assert len(alerts) == 3
    assert all(a.severity == "critical" for a in alerts)
    assert alerts[0].ts == 5.0


def test_max_dwell_resets_on_exit(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="pallet_dwell", type="max_dwell",
        object_filter=ObjectFilter(type="pallet"), zone="exit_lane",
        max_duration_s=3.0,
    )])
    lines = [
        make_frame(0.0, 0, [{"id": 12, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(1.0, 1, [{"id": 12, "pos": [1.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(2.0, 2, [{"id": 12, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ]
    session = write_session(tmp_path, lines)
    alerts, _ = evaluate_session(session, rules, registry)
    # never dwells 3.0s continuously → no alert
    assert alerts == []


# --- min_distance ---------------------------------------------------------

def test_min_distance_triggers(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="cart_person", type="min_distance",
        object_filter_a=ObjectFilter(type="cart"),
        object_filter_b=ObjectFilter(type="human_proxy"),
        min_distance_m=0.6, severity="critical",
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [
            {"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"},
            {"id": 3, "pos": [0.3, 0.0, 0.0], "zone": "main"},
        ]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) == 1
    assert set(alerts[0].object_ids) == {"cart_01", "human_proxy_01"}
    assert alerts[0].detail["distance_m"] == 0.3


def test_min_distance_far_apart_no_alert(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="cart_person", type="min_distance",
        object_filter_a=ObjectFilter(type="cart"),
        object_filter_b=ObjectFilter(type="human_proxy"),
        min_distance_m=0.6,
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [
            {"id": 7, "pos": [0.0, 0.0, 0.0]},
            {"id": 3, "pos": [5.0, 0.0, 0.0]},
        ]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert alerts == []


# --- speed_limit ----------------------------------------------------------

def test_speed_limit_from_velocity(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="cart_speed", type="speed_limit",
        object_filter=ObjectFilter(type="cart"), max_speed_mps=1.5,
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "vel": [2.0, 0.0, 0.0]}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [2.0, 0.0, 0.0], "vel": [1.0, 0.0, 0.0]}]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) == 1
    assert alerts[0].detail["speed_mps"] == 2.0


def test_speed_limit_from_position_diff(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="cart_speed", type="speed_limit",
        object_filter=ObjectFilter(type="cart"), max_speed_mps=1.5,
    )])
    # moves 3m in 1s → 3 m/s (no vel_world provided)
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0]}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [3.0, 0.0, 0.0]}]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) == 1
    assert alerts[0].detail["speed_mps"] == 3.0


# --- missing_object -------------------------------------------------------

def test_missing_object_triggers(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="cart_missing", type="missing_object",
        object_filter=ObjectFilter(type="cart"), max_duration_s=2.0,
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0]}]),
        make_frame(1.0, 1, [{"id": 12, "pos": [0.0, 0.0, 0.0]}]),  # cart gone
        make_frame(5.0, 2, [{"id": 12, "pos": [0.0, 0.0, 0.0]}]),  # 5s since cart seen
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) >= 1
    assert alerts[-1].object_ids == ["cart_01"]


# --- restricted_transition -----------------------------------------------

def test_restricted_transition_triggers(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="no_main_to_exit", type="restricted_transition",
        object_filter=ObjectFilter(type="cart"),
        from_zone="main", to_zone="exit_lane",
    )])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ])
    alerts, _ = evaluate_session(session, rules, registry)
    assert len(alerts) == 1
    assert alerts[0].detail["from_zone"] == "main"
    assert alerts[0].detail["to_zone"] == "exit_lane"


# --- determinism & ids ----------------------------------------------------

def test_alert_ids_sequential_and_deterministic(tmp_path, registry):
    ruleset = load_rules(CONFIG_RULES)
    lines = [
        make_frame(float(t), t, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "exit_lane"}])
        for t in range(3)
    ]
    session = write_session(tmp_path, lines)
    a1, _ = evaluate_session(session, ruleset, registry)
    a2, _ = evaluate_session(session, ruleset, registry)
    assert [a.alert_id for a in a1] == [a.alert_id for a in a2]
    assert a1[0].alert_id == "alert_000001"


def test_run_id_captured(tmp_path, registry):
    rules = RuleSet(rules=[RuleDefinition(
        id="r", type="forbidden_zone",
        object_filter=ObjectFilter(type="cart"), zone="exit_lane")])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "exit_lane"}],
                   run_id="my_run"),
    ])
    alerts, run_id = evaluate_session(session, rules, registry)
    assert run_id == "my_run"
    assert alerts[0].run_id == "my_run"


def test_fallback_object_id_without_registry(tmp_path):
    rules = RuleSet(rules=[RuleDefinition(
        id="r", type="forbidden_zone", zone="exit_lane")])
    session = write_session(tmp_path, [
        make_frame(0.0, 0, [{"id": 99, "pos": [0.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ])
    alerts, _ = evaluate_session(session, rules, None)
    assert alerts[0].object_ids == ["marker_99"]
