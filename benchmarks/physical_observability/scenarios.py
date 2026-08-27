# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from benchmarks.physical_observability.expected import (
    load_expected_alerts,
    load_expected_incidents,
)
from benchmarks.physical_observability.metrics import (
    compare_incidents,
    latency_summary,
    precision_recall_f1,
)
from metriplane.sentinel.engine import RuleEngine, iter_frames
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import load_rules
from metriplane.testing.hash import incidents_fingerprint

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


@dataclass
class BenchRow:
    scenario: str
    task: str
    metric: str
    value: object
    passed: bool
    notes: str = ""


def discover_scenarios() -> list[str]:
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SCENARIOS_DIR.iterdir()
        if p.is_dir() and (p / "input_session.jsonl").exists()
    )


def _evaluate(scenario_dir: Path):
    session = scenario_dir / "input_session.jsonl"
    rules = load_rules(scenario_dir / "rules.yaml")
    reg_path = scenario_dir / "object_registry.yaml"
    registry = load_registry(reg_path) if reg_path.exists() else None

    engine = RuleEngine(rules, registry)
    alerts = []
    per_frame_ms = []
    for frame in iter_frames(session):
        t0 = time.perf_counter()
        alerts.extend(engine.process_frame(frame))
        per_frame_ms.append((time.perf_counter() - t0) * 1000.0)
    incidents = build_incidents(alerts)
    return alerts, incidents, per_frame_ms


def run_scenario(name: str) -> list[BenchRow]:
    sd = SCENARIOS_DIR / name
    rows: list[BenchRow] = []

    alerts, incidents, per_frame_ms = _evaluate(sd)
    fp1 = incidents_fingerprint(incidents)

    # replay determinism
    _, incidents2, _ = _evaluate(sd)
    fp2 = incidents_fingerprint(incidents2)
    rows.append(
        BenchRow(name, "replay_determinism", "hash_match", fp1 == fp2, fp1 == fp2, fp1[:16])
    )

    # rule alerts P/R/F1
    expected_alerts = load_expected_alerts(sd)
    observed_alert_rules = sorted({a.rule_id for a in alerts})
    pr = precision_recall_f1(expected_alerts, observed_alert_rules)
    rows.append(
        BenchRow(
            name,
            "rule_alerts",
            "precision",
            pr["precision"],
            pr["precision"] >= 1.0,
            f"fp={pr['fp']}",
        )
    )
    rows.append(
        BenchRow(name, "rule_alerts", "recall", pr["recall"], pr["recall"] >= 1.0, f"fn={pr['fn']}")
    )
    rows.append(
        BenchRow(
            name, "rule_alerts", "f1", pr["f1"], pr["f1"] >= 1.0, f"observed={observed_alert_rules}"
        )
    )

    # incidents P/R/F1
    expected_incidents = load_expected_incidents(sd)
    observed_incidents = [{"rule_id": i.rule_id} for i in incidents]
    ip = compare_incidents(expected_incidents, observed_incidents)
    rows.append(
        BenchRow(
            name,
            "incidents",
            "precision",
            ip["precision"],
            ip["precision"] >= 1.0,
            f"fp={ip['fp']}",
        )
    )
    rows.append(
        BenchRow(name, "incidents", "recall", ip["recall"], ip["recall"] >= 1.0, f"fn={ip['fn']}")
    )
    rows.append(
        BenchRow(name, "incidents", "f1", ip["f1"], ip["f1"] >= 1.0, f"count={len(incidents)}")
    )

    # latency
    lat = latency_summary(per_frame_ms)
    rows.append(
        BenchRow(
            name,
            "latency",
            "p50_ms",
            lat["p50_ms"],
            True,
            f"p95={lat['p95_ms']} p99={lat['p99_ms']}",
        )
    )

    return rows


def run_all(scenarios: list[str] | None = None) -> list[BenchRow]:
    names = scenarios or discover_scenarios()
    rows: list[BenchRow] = []
    for name in names:
        rows.extend(run_scenario(name))
    return rows
