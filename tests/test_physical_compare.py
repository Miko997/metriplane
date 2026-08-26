# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.sentinel.events import IncidentRecord, RuleAlert
from metriplane.testing.compare import compare_events, compare_incidents
from metriplane.testing.models import ExpectedEventSpec, ExpectedIncidentSpec


def inc(
    rule_id="no_cart_in_exit_lane", severity="warning", objects=("cart_01",), zones=("exit_lane",)
):
    return IncidentRecord(
        incident_id="inc_0001",
        rule_id=rule_id,
        severity=severity,
        status="closed",
        opened_ts=1.0,
        closed_ts=2.0,
        duration_s=1.0,
        object_ids=list(objects),
        zones=list(zones),
        summary="x",
    )


def passed(checks):
    return all(c["pass"] for c in checks)


def compare_typed_incidents(observed, specs, strict_extra=False):
    rule_types = {incident.rule_id: "t" for incident in observed}
    return compare_incidents(observed, specs, strict_extra, rule_types)


def test_matching_incident_passes():
    checks = compare_typed_incidents(
        [inc()], [ExpectedIncidentSpec(type="t", rule_id="no_cart_in_exit_lane", min_count=1)]
    )
    assert passed(checks)


def test_missing_incident_fails():
    checks = compare_typed_incidents(
        [], [ExpectedIncidentSpec(type="t", rule_id="no_cart_in_exit_lane", min_count=1)]
    )
    assert not passed(checks)


def test_severity_too_low_fails():
    checks = compare_typed_incidents(
        [inc(severity="warning")],
        [
            ExpectedIncidentSpec(
                type="t", rule_id="no_cart_in_exit_lane", severity_at_least="critical"
            )
        ],
    )
    assert not passed(checks)


def test_object_ids_any_order_match():
    i = inc(objects=("cart_01", "human_proxy_01"))
    checks = compare_typed_incidents(
        [i], [ExpectedIncidentSpec(type="t", object_ids_any_order=["human_proxy_01", "cart_01"])]
    )
    assert passed(checks)


def test_extra_incident_tolerated_by_default():
    checks = compare_typed_incidents(
        [inc(), inc(rule_id="other")],
        [ExpectedIncidentSpec(type="t", rule_id="no_cart_in_exit_lane")],
    )
    assert passed(checks)


def test_extra_incident_fails_in_strict_mode():
    checks = compare_typed_incidents(
        [inc(), inc(rule_id="other")],
        [ExpectedIncidentSpec(type="t", rule_id="no_cart_in_exit_lane")],
        strict_extra=True,
    )
    assert not passed(checks)


def test_max_count_violation_fails():
    checks = compare_typed_incidents(
        [inc(), inc()],
        [ExpectedIncidentSpec(type="t", rule_id="no_cart_in_exit_lane", min_count=1, max_count=1)],
    )
    assert not passed(checks)


def test_zones_subset_required():
    checks = compare_typed_incidents(
        [inc(zones=("main",))], [ExpectedIncidentSpec(type="t", zones=["exit_lane"])]
    )
    assert not passed(checks)


def test_event_count_matching():
    alerts = [
        RuleAlert(
            alert_id=f"a{i}", rule_id="r", severity="warning", ts=float(i), object_ids=["cart_01"]
        )
        for i in range(3)
    ]
    checks = compare_events(alerts, [ExpectedEventSpec(rule_id="r", min_count=2)])
    assert passed(checks)


def test_event_count_too_few_fails():
    alerts = [RuleAlert(alert_id="a", rule_id="r", severity="warning", ts=0.0, object_ids=[])]
    checks = compare_events(alerts, [ExpectedEventSpec(rule_id="r", min_count=5)])
    assert not passed(checks)
