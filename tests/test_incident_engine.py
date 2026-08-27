# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.sentinel.events import RuleAlert
from metriplane.sentinel.incidents import (
    IncidentEngineConfig,
    build_incidents,
)


def alert(ts, rule_id="r1", severity="warning", objects=("cart_01",), zone="exit_lane", aid=None):
    return RuleAlert(
        alert_id=aid or f"a{int(ts * 1000):07d}",
        rule_id=rule_id,
        severity=severity,
        ts=ts,
        object_ids=list(objects),
        zone=zone,
        run_id="test",
    )


def test_single_incident_from_contiguous_alerts():
    alerts = [alert(0.0), alert(1.0), alert(2.0)]
    incidents = build_incidents(alerts)
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.opened_ts == 0.0
    assert inc.closed_ts == 2.0
    assert inc.duration_s == 2.0
    assert len(inc.alert_ids) == 3
    assert inc.status == "closed"


def test_gap_splits_into_two_incidents():
    # gap_close_s default 1.0; a 5s gap between bursts → two incidents
    alerts = [alert(0.0), alert(1.0), alert(10.0), alert(11.0)]
    incidents = build_incidents(alerts)
    assert len(incidents) == 2
    assert incidents[0].closed_ts == 1.0
    assert incidents[1].opened_ts == 10.0


def test_different_rules_are_separate_incidents():
    alerts = [
        alert(0.0, rule_id="rule_a"),
        alert(0.0, rule_id="rule_b"),
        alert(1.0, rule_id="rule_a"),
        alert(1.0, rule_id="rule_b"),
    ]
    incidents = build_incidents(alerts)
    assert len(incidents) == 2
    rule_ids = {inc.rule_id for inc in incidents}
    assert rule_ids == {"rule_a", "rule_b"}


def test_different_objects_are_separate_incidents():
    alerts = [
        alert(0.0, objects=("cart_01",)),
        alert(0.0, objects=("cart_02",)),
        alert(1.0, objects=("cart_01",)),
    ]
    incidents = build_incidents(alerts)
    assert len(incidents) == 2


def test_severity_escalation():
    alerts = [
        alert(0.0, severity="warning"),
        alert(1.0, severity="critical"),
        alert(2.0, severity="warning"),
    ]
    incidents = build_incidents(alerts)
    assert len(incidents) == 1
    assert incidents[0].severity == "critical"


def test_incident_ids_sequential_and_deterministic():
    alerts = [alert(0.0), alert(10.0), alert(20.0)]
    inc1 = build_incidents(alerts)
    inc2 = build_incidents(alerts)
    assert [i.incident_id for i in inc1] == [i.incident_id for i in inc2]
    assert inc1[0].incident_id == "inc_0001"
    assert inc1[1].incident_id == "inc_0002"


def test_summary_text_generated():
    incidents = build_incidents([alert(0.0), alert(1.0)])
    assert "cart_01" in incidents[0].summary
    assert "r1" in incidents[0].summary
    assert "exit_lane" in incidents[0].summary


def test_empty_alerts_no_incidents():
    assert build_incidents([]) == []


def test_custom_gap_close():
    # with a larger gap_close_s, the 3s gap stays a single incident
    alerts = [alert(0.0), alert(3.0)]
    incidents = build_incidents(alerts, IncidentEngineConfig(gap_close_s=5.0))
    assert len(incidents) == 1


def test_incidents_ordered_by_open_time():
    alerts = [
        alert(20.0, rule_id="rule_b"),
        alert(0.0, rule_id="rule_a"),
    ]
    incidents = build_incidents(alerts)
    assert incidents[0].opened_ts <= incidents[1].opened_ts
