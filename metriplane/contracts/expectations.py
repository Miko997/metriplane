from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from metriplane.contracts.engine import ContractEvent
from metriplane.sentinel.incidents import build_incidents


@dataclass
class ExpectationResult:
    expected_incidents: int
    observed_incidents: int
    false_positives: int
    missed: int
    rule_ids_expected: list[str] = field(default_factory=list)
    rule_ids_observed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.false_positives == 0 and self.missed == 0


def load_expectations(path: str | Path) -> dict:
    """Load an expected-events YAML file.

    Expected format:
        expected_incidents: 2
        rules:
          - exit_lane_blocked
          - human_proxy_distance
    """
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expectations must be a mapping")
    return data


def compare(events: list[ContractEvent], expected: dict) -> ExpectationResult:
    """Group events into incidents and compare against expected rule set."""
    alerts = [e.to_rule_alert() for e in events]
    incidents = build_incidents(alerts)

    observed_rules = sorted({inc.rule_id for inc in incidents})
    expected_rules = sorted(expected.get("rules", []))

    expected_count = expected.get("expected_incidents", len(expected_rules))

    exp_set = set(expected_rules)
    obs_set = set(observed_rules)
    false_positives = len(obs_set - exp_set) if expected_rules else 0
    missed = len(exp_set - obs_set)

    return ExpectationResult(
        expected_incidents=expected_count,
        observed_incidents=len(incidents),
        false_positives=false_positives,
        missed=missed,
        rule_ids_expected=expected_rules,
        rule_ids_observed=observed_rules,
    )
