# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any

from metriplane.sentinel.events import IncidentRecord, RuleAlert
from metriplane.testing.models import (
    ExpectedEventSpec,
    ExpectedIncidentSpec,
    PhysicalRegressionExpected,
    severity_rank,
)


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "pass": passed, "detail": detail}


_INCIDENT_TYPE_BY_RULE_TYPE = {
    "forbidden_zone": "forbidden_zone_entry",
    "max_dwell": "max_dwell",
    "min_distance": "min_distance",
    "speed_limit": "speed_limit",
    "missing_object": "missing_object",
    "restricted_transition": "restricted_transition",
}


def _incident_matches(
    inc: IncidentRecord,
    spec: ExpectedIncidentSpec,
    rule_types: dict[str, str],
) -> bool:
    rule_type = rule_types.get(inc.rule_id)
    actual_type = _INCIDENT_TYPE_BY_RULE_TYPE.get(rule_type or "", rule_type)
    if actual_type != spec.type:
        return False
    if spec.rule_id is not None and inc.rule_id != spec.rule_id:
        return False
    if spec.severity_at_least is not None:
        if severity_rank(inc.severity) < severity_rank(spec.severity_at_least):
            return False
    if spec.object_ids_any_order:
        if not set(spec.object_ids_any_order).issubset(set(inc.object_ids)):
            return False
    if spec.zones:
        if not set(spec.zones).issubset(set(inc.zones)):
            return False
    return True


def compare_incidents(observed: list[IncidentRecord],
                      specs: list[ExpectedIncidentSpec],
                      strict_extra: bool = False,
                      rule_types: dict[str, str] | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    matched_idx: set[int] = set()
    known_rule_types = rule_types or {}
    for spec in specs:
        hits = [
            i for i, inc in enumerate(observed)
            if _incident_matches(inc, spec, known_rule_types)
        ]
        matched_idx.update(hits)
        n = len(hits)
        ok = n >= spec.min_count and (spec.max_count is None or n <= spec.max_count)
        rng = f">={spec.min_count}" + (f",<={spec.max_count}" if spec.max_count else "")
        checks.append(_check(
            f"incident[{spec.type}/{spec.rule_id or '*'}]", ok,
            f"matched {n} (expected {rng})"))
    if strict_extra:
        extra = [observed[i].rule_id for i in range(len(observed)) if i not in matched_idx]
        checks.append(_check("incidents.no_extra", len(extra) == 0,
                             f"unexpected incidents: {extra}" if extra else "none"))
    return checks


def compare_events(observed: list[RuleAlert], specs: list[ExpectedEventSpec],
                   strict_extra: bool = False) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    matched_idx: set[int] = set()
    for spec in specs:
        hits = [
            (index, alert)
            for index, alert in enumerate(observed)
            if (spec.rule_id is None or alert.rule_id == spec.rule_id)
            and (spec.event_type is None or spec.event_type == "alert")
        ]
        matched_idx.update(index for index, _ in hits)
        n = len(hits)
        ok = n >= spec.min_count and (spec.max_count is None or n <= spec.max_count)
        rng = f">={spec.min_count}" + (f",<={spec.max_count}" if spec.max_count else "")
        checks.append(_check(
            f"event[{spec.rule_id or spec.event_type or '*'}]", ok,
            f"matched {n} (expected {rng})"))
    if strict_extra:
        extra = sorted(
            observed[index].rule_id
            for index in range(len(observed))
            if index not in matched_idx
        )
        checks.append(_check("events.no_extra", len(extra) == 0,
                             f"unexpected events: {extra}" if extra else "none"))
    return checks


def compare_latency(p95_ms: float | None,
                    expected: PhysicalRegressionExpected) -> list[dict[str, Any]]:
    limit = expected.latency.p95_update_ms_max
    if limit is None or p95_ms is None:
        return []
    ok = p95_ms <= limit
    return [_check("latency.p95_update_ms", ok,
                   f"{round(p95_ms, 3)}ms (max {limit}ms)")]
