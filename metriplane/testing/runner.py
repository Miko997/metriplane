# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from metriplane.sentinel.engine import RuleEngine, iter_frames
from metriplane.sentinel.events import RuleAlert
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import load_rules
from metriplane.testing.compare import (
    compare_events,
    compare_incidents,
    compare_latency,
)
from metriplane.testing.hash import incidents_fingerprint
from metriplane.testing.load_expected import load_expected
from metriplane.testing.models import PhysicalRegressionResult


@dataclass
class _Evaluation:
    alerts: list[RuleAlert]
    incidents: list
    p95_ms: float | None
    fingerprint: str


def _evaluate(bundle: Path) -> _Evaluation:
    session = bundle / "session_excerpt.jsonl"
    rules = load_rules(bundle / "rules.yaml")
    objects_path = bundle / "objects.yaml"
    registry = load_registry(objects_path) if objects_path.exists() else None

    engine = RuleEngine(rules, registry)
    alerts: list[RuleAlert] = []
    per_frame_ms: list[float] = []
    for frame in iter_frames(session):
        observed = frame.fused if frame.fused else frame.objects
        t0 = time.perf_counter()
        alerts.extend(engine.process_frame(frame))
        per_frame_ms.append((time.perf_counter() - t0) * 1000.0)

    incidents = build_incidents(alerts)
    p95 = None
    if per_frame_ms:
        ordered = sorted(per_frame_ms)
        idx = max(0, int(round(0.95 * (len(ordered) - 1))))
        p95 = ordered[idx]
    return _Evaluation(alerts, incidents, p95, incidents_fingerprint(incidents))


class PhysicalRegressionRunner:
    def __init__(self, verify_checksums: bool = True,
                 strict_extra_incidents: bool = False,
                 strict_extra_events: bool = False):
        self.verify_checksums = verify_checksums
        self.strict_extra_incidents = strict_extra_incidents
        self.strict_extra_events = strict_extra_events

    def run_bundle(self, bundle_path: str | Path) -> PhysicalRegressionResult:
        from metriplane.sentinel.bundles import verify_checksums as verify_chk

        bundle = Path(bundle_path)
        checks: list[dict] = []

        expected_file = bundle / "expected.yaml"
        if not expected_file.exists():
            return PhysicalRegressionResult(
                bundle_path=str(bundle), **{"pass": False},
                checks=[{"check": "expected.yaml", "pass": False,
                         "detail": "expected.yaml not found in bundle"}],
            )
        expected = load_expected(expected_file)

        if self.verify_checksums:
            errors = verify_chk(bundle)
            checks.append({"check": "checksums", "pass": not errors,
                           "detail": "ok" if not errors else f"{errors}"})
            if errors:
                return PhysicalRegressionResult(
                    bundle_path=str(bundle), **{"pass": False}, checks=checks)

        first = _evaluate(bundle)

        if expected.replay.deterministic_hash_match:
            second = _evaluate(bundle)
            match = first.fingerprint == second.fingerprint
            checks.append({"check": "replay.deterministic_hash_match", "pass": match,
                           "detail": first.fingerprint[:16] if match
                           else "fingerprint changed across runs"})

        checks.extend(compare_incidents(first.incidents, expected.incidents,
                                        self.strict_extra_incidents))
        checks.extend(compare_events(first.alerts, expected.events,
                                     self.strict_extra_events))
        checks.extend(compare_latency(first.p95_ms, expected))

        passed = all(c["pass"] for c in checks)
        return PhysicalRegressionResult(
            bundle_path=str(bundle),
            **{"pass": passed},
            checks=checks,
            observed={
                "incidents": len(first.incidents),
                "alerts": len(first.alerts),
                "p95_update_ms": first.p95_ms,
                "rule_ids": sorted({i.rule_id for i in first.incidents}),
            },
            output_hash=first.fingerprint,
        )
