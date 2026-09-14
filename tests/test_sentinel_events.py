# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from metriplane.sentinel.events import (
    IncidentRecord,
    OperationalEvent,
    RuleAlert,
    read_alerts_jsonl,
    read_incidents_json,
    write_alerts_jsonl,
    write_incidents_json,
)
from metriplane.sentinel.rules import (
    ObjectFilter,
    load_rules,
    validate_rules,
)


# ---------------------------------------------------------------------------
# RuleAlert
# ---------------------------------------------------------------------------


def test_rule_alert_fields():
    a = RuleAlert(rule_id="r1", severity="warning", ts=100.0, object_ids=["cart_01"])
    assert a.rule_id == "r1"
    assert a.severity == "warning"
    assert a.ts == 100.0
    assert a.object_ids == ["cart_01"]


def test_alert_id_auto_generated():
    a1 = RuleAlert(rule_id="r1", severity="info", ts=0.0, object_ids=[])
    a2 = RuleAlert(rule_id="r1", severity="info", ts=0.0, object_ids=[])
    assert a1.alert_id != a2.alert_id


def test_alerts_jsonl_roundtrip(tmp_path):
    alerts = [
        RuleAlert(rule_id="r1", severity="warning", ts=1.0, object_ids=["cart_01"]),
        RuleAlert(rule_id="r2", severity="critical", ts=2.0, object_ids=["pallet_01"]),
        RuleAlert(rule_id="r3", severity="info", ts=3.0, object_ids=[]),
    ]
    p = tmp_path / "alerts.jsonl"
    write_alerts_jsonl(alerts, p)
    loaded = read_alerts_jsonl(p)
    assert len(loaded) == 3
    assert loaded[0].rule_id == "r1"


# ---------------------------------------------------------------------------
# IncidentRecord
# ---------------------------------------------------------------------------


def test_incident_open():
    inc = IncidentRecord(
        rule_id="pallet_blocks_exit",
        severity="critical",
        opened_ts=100.0,
        object_ids=["pallet_01"],
        zones=["exit_lane"],
        summary="pallet_01 blocked exit_lane",
    )
    assert inc.status == "open"
    assert inc.closed_ts is None


def test_incident_close():
    inc = IncidentRecord(
        rule_id="pallet_blocks_exit",
        severity="critical",
        opened_ts=100.0,
        object_ids=["pallet_01"],
        zones=["exit_lane"],
        summary="pallet_01 blocked exit_lane",
    )
    inc.close(130.0)
    assert inc.status == "closed"
    assert inc.closed_ts == 130.0
    assert inc.duration_s == 30.0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: RuleAlert(rule_id="r", severity="warning", ts=float("nan"), object_ids=[]),
        lambda: IncidentRecord(
            rule_id="r",
            severity="warning",
            opened_ts=2.0,
            closed_ts=1.0,
            duration_s=-1.0,
            object_ids=[],
            zones=[],
            summary="invalid",
        ),
    ],
)
def test_event_models_reject_invalid_timing(factory):
    with pytest.raises(ValueError):
        factory()


def test_incidents_json_roundtrip(tmp_path):
    inc1 = IncidentRecord(
        rule_id="r1",
        severity="warning",
        opened_ts=10.0,
        object_ids=["cart_01"],
        zones=["zone_a"],
        summary="test1",
    )
    inc2 = IncidentRecord(
        rule_id="r2",
        severity="critical",
        opened_ts=20.0,
        object_ids=["pallet_01"],
        zones=["zone_b"],
        summary="test2",
    )
    inc2.close(30.0)
    p = tmp_path / "incidents.json"
    write_incidents_json([inc1, inc2], p)
    loaded = read_incidents_json(p)
    assert len(loaded) == 2
    assert loaded[1].status == "closed"
    assert loaded[1].duration_s == 10.0


# ---------------------------------------------------------------------------
# OperationalEvent
# ---------------------------------------------------------------------------


def test_event_from_alert():
    a = RuleAlert(rule_id="r1", severity="info", ts=5.0, object_ids=["cart_01"])
    ev = OperationalEvent.from_alert(a)
    assert ev.event_type == "alert"
    assert ev.payload["rule_id"] == "r1"


def test_event_from_incident_open():
    inc = IncidentRecord(
        rule_id="r1",
        severity="warning",
        opened_ts=10.0,
        object_ids=[],
        zones=[],
        summary="x",
    )
    ev = OperationalEvent.from_incident_open(inc)
    assert ev.event_type == "incident_open"
    assert ev.ts == 10.0


def test_event_from_incident_close():
    inc = IncidentRecord(
        rule_id="r1",
        severity="warning",
        opened_ts=10.0,
        object_ids=[],
        zones=[],
        summary="x",
    )
    inc.close(20.0)
    ev = OperationalEvent.from_incident_close(inc)
    assert ev.event_type == "incident_close"
    assert ev.ts == 20.0


# ---------------------------------------------------------------------------
# ObjectFilter
# ---------------------------------------------------------------------------


def test_filter_type_match():
    assert ObjectFilter(type="cart").matches(obj_type="cart") is True


def test_filter_type_no_match():
    assert ObjectFilter(type="cart").matches(obj_type="pallet") is False


def test_filter_none_matches_all():
    assert ObjectFilter().matches(obj_type="anything") is True


# ---------------------------------------------------------------------------
# RuleSet
# ---------------------------------------------------------------------------


def test_load_rules_inline(tmp_path):
    yaml_text = """\
rules:
  - id: rule_a
    type: forbidden_zone
    zone: main
    severity: warning
  - id: rule_b
    type: max_dwell
    zone: main
    max_duration_s: 5.0
    severity: critical
"""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml_text)
    rs = load_rules(p)
    assert len(rs.rules) == 2
    assert rs.rules[0].id == "rule_a"


def test_validate_rules_ok(tmp_path):
    yaml_text = """\
rules:
  - id: unique_a
    type: forbidden_zone
    zone: main
  - id: unique_b
    type: speed_limit
    max_speed_mps: 1.0
"""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml_text)
    assert validate_rules(p) == []


def test_validate_rules_duplicate_id(tmp_path):
    yaml_text = """\
rules:
  - id: same_id
    type: forbidden_zone
    zone: main
  - id: same_id
    type: max_dwell
    zone: main
    max_duration_s: 3.0
"""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml_text)
    errors = validate_rules(p)
    assert any("duplicate rule id" in e for e in errors)


def test_unknown_rule_type(tmp_path):
    yaml_text = """\
rules:
  - id: bad_rule
    type: banana
"""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml_text)
    with pytest.raises(Exception):
        load_rules(p)
