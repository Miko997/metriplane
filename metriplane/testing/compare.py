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


def _incident_matches(inc: IncidentRecord, spec: ExpectedIncidentSpec) -> bool:
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
                      strict_extra: bool = False) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    matched_idx: set[int] = set()
    for spec in specs:
        hits = [i for i, inc in enumerate(observed) if _incident_matches(inc, spec)]
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
    matched_rules: set[str] = set()
    for spec in specs:
        hits = [a for a in observed
                if (spec.rule_id is None or a.rule_id == spec.rule_id)]
        if spec.rule_id:
            matched_rules.add(spec.rule_id)
        n = len(hits)
        ok = n >= spec.min_count and (spec.max_count is None or n <= spec.max_count)
        rng = f">={spec.min_count}" + (f",<={spec.max_count}" if spec.max_count else "")
        checks.append(_check(
            f"event[{spec.rule_id or spec.event_type or '*'}]", ok,
            f"matched {n} (expected {rng})"))
    if strict_extra:
        extra = sorted({a.rule_id for a in observed} - matched_rules)
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
