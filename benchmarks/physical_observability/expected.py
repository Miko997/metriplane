from __future__ import annotations

import json
from pathlib import Path

import yaml


def load_scenario_meta(scenario_dir: Path) -> dict:
    meta_file = scenario_dir / "scenario.yaml"
    if meta_file.exists():
        return yaml.safe_load(meta_file.read_text()) or {}
    return {}


def load_expected_alerts(scenario_dir: Path) -> list[str]:
    f = scenario_dir / "expected_alerts.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    return [d["rule_id"] if isinstance(d, dict) else str(d) for d in data]


def load_expected_incidents(scenario_dir: Path) -> list[dict]:
    f = scenario_dir / "expected_incidents.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text())
    return [d if isinstance(d, dict) else {"rule_id": str(d)} for d in data]
