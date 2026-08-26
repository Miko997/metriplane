# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metriplane.sentinel.engine import RuleEngine, iter_frames
from metriplane.sentinel.events import IncidentRecord, RuleAlert
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
    incidents: list[IncidentRecord]
    p95_ms: float | None
    fingerprint: str
    rule_types: dict[str, str]


def _result(
    bundle_path: str,
    passed: bool,
    *,
    checks: list[dict[str, Any]] | None = None,
    observed: dict[str, Any] | None = None,
    output_hash: str | None = None,
) -> PhysicalRegressionResult:
    return PhysicalRegressionResult.model_validate(
        {
            "bundle_path": bundle_path,
            "pass": passed,
            "checks": checks or [],
            "observed": observed or {},
            "output_hash": output_hash,
        }
    )


def _evaluate(bundle: Path) -> _Evaluation:
    session = bundle / "session_excerpt.jsonl"
    rules = load_rules(bundle / "rules.yaml")
    objects_path = bundle / "objects.yaml"
    registry = load_registry(objects_path) if objects_path.exists() else None

    engine = RuleEngine(rules, registry)
    alerts: list[RuleAlert] = []
    per_frame_ms: list[float] = []
    frame_count = 0
    for frame in iter_frames(session):
        frame_count += 1
        t0 = time.perf_counter()
        alerts.extend(engine.process_frame(frame))
        per_frame_ms.append((time.perf_counter() - t0) * 1000.0)

    if frame_count == 0:
        raise ValueError("session_excerpt.jsonl contains no valid frames")

    incidents = build_incidents(alerts)
    p95 = None
    if per_frame_ms:
        ordered = sorted(per_frame_ms)
        idx = max(0, int(round(0.95 * (len(ordered) - 1))))
        p95 = ordered[idx]
    rule_types = {rule.id: str(rule.type) for rule in rules.rules}
    return _Evaluation(
        alerts,
        incidents,
        p95,
        incidents_fingerprint(incidents),
        rule_types,
    )


class PhysicalRegressionRunner:
    def __init__(
        self,
        verify_checksums: bool = True,
        strict_extra_incidents: bool = False,
        strict_extra_events: bool = False,
    ):
        self.verify_checksums = verify_checksums
        self.strict_extra_incidents = strict_extra_incidents
        self.strict_extra_events = strict_extra_events

    def run_bundle(self, bundle_path: str | Path) -> PhysicalRegressionResult:
        bundle = Path(bundle_path)
        try:
            return self._run_bundle(bundle)
        except Exception as exc:
            return _result(
                str(bundle),
                False,
                checks=[
                    {
                        "check": "bundle.input",
                        "pass": False,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                ],
            )

    def _run_bundle(self, bundle: Path) -> PhysicalRegressionResult:
        from metriplane.sentinel.bundles import (
            UNSIGNED_DERIVED_SIDECARS,
            validate_bundle_evidence,
            verify_checksums,
        )
        from metriplane.sentinel.events import read_incidents_json

        checks: list[dict[str, Any]] = []

        if bundle.is_symlink() or not bundle.is_dir():
            raise ValueError(f"bundle directory does not exist: {bundle}")

        expected_file = bundle / "expected.yaml"
        if expected_file.is_symlink() or not expected_file.is_file():
            return _result(
                str(bundle),
                False,
                checks=[
                    {
                        "check": "expected.yaml",
                        "pass": False,
                        "detail": "expected.yaml not found in bundle",
                    }
                ],
            )
        expected = load_expected(expected_file)
        if not expected.incidents and not expected.events:
            return _result(
                str(bundle),
                False,
                checks=[
                    {
                        "check": "expected.semantic_oracle",
                        "pass": False,
                        "detail": ("expected.yaml must require at least one incident or event"),
                    }
                ],
            )

        evidence_errors = validate_bundle_evidence(bundle)
        checks.append(
            {
                "check": "bundle.input",
                "pass": not evidence_errors,
                "detail": "ok" if not evidence_errors else f"{evidence_errors}",
            }
        )
        if evidence_errors:
            return _result(str(bundle), False, checks=checks)

        if self.verify_checksums:
            errors = verify_checksums(bundle, exclude=set(UNSIGNED_DERIVED_SIDECARS))
            checks.append(
                {
                    "check": "checksums",
                    "pass": not errors,
                    "detail": "ok" if not errors else f"{errors}",
                }
            )
            if errors:
                return _result(str(bundle), False, checks=checks)

        first = _evaluate(bundle)

        stored_incident = read_incidents_json(bundle / "incident.json")[0]
        reference_match = any(
            incident.rule_id == stored_incident.rule_id
            and incident.run_id == stored_incident.run_id
            and list(incident.alert_ids) == list(stored_incident.alert_ids)
            for incident in first.incidents
        )
        checks.append(
            {
                "check": "bundle.replayed_references",
                "pass": reference_match,
                "detail": (
                    "run_id and alert IDs reproduced"
                    if reference_match
                    else "stored run_id or alert IDs did not reproduce"
                ),
            }
        )

        if expected.replay.deterministic_hash_match:
            second = _evaluate(bundle)
            match = first.fingerprint == second.fingerprint
            checks.append(
                {
                    "check": "replay.deterministic_hash_match",
                    "pass": match,
                    "detail": first.fingerprint[:16]
                    if match
                    else "fingerprint changed across runs",
                }
            )

        checks.extend(
            compare_incidents(
                first.incidents,
                expected.incidents,
                self.strict_extra_incidents,
                first.rule_types,
            )
        )
        checks.extend(compare_events(first.alerts, expected.events, self.strict_extra_events))
        checks.extend(compare_latency(first.p95_ms, expected))

        passed = all(c["pass"] for c in checks)
        return _result(
            str(bundle),
            passed,
            checks=checks,
            observed={
                "incidents": len(first.incidents),
                "alerts": len(first.alerts),
                "p95_update_ms": first.p95_ms,
                "rule_ids": sorted({i.rule_id for i in first.incidents}),
            },
            output_hash=first.fingerprint,
        )
