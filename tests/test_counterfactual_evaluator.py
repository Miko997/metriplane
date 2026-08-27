# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from metriplane.counterfactuals.cli import main_counterfactual
from metriplane.counterfactuals.evaluator import (
    CounterfactualError,
    CounterfactualEvaluator,
)
from metriplane.counterfactuals.models import CounterfactualTransform
from metriplane.counterfactuals.rule_sweep import sweep_transforms

BUNDLE = "evidence/incidents/INC-DIST-001"


@pytest.fixture
def bundle_copy(tmp_path):
    dst = tmp_path / "INC-DIST-001"
    shutil.copytree(BUNDLE, dst)
    return dst


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_threshold_sweep_changes_detection(bundle_copy):
    transforms = sweep_transforms("cart_person_distance.min_distance_m=0.1:0.6:0.1")
    report = CounterfactualEvaluator().evaluate(bundle_copy, transforms)
    presence = [c.original_incident_present for c in report.cases]
    # low thresholds prevent, high thresholds keep the incident
    assert presence[0] is False  # 0.1
    assert presence[-1] is True  # 0.6


def test_speed_scale_prevents_incident(bundle_copy):
    t = [
        CounterfactualTransform(
            type="object_speed_scale", target="human_proxy_01", params={"factor": 0.5}
        )
    ]
    report = CounterfactualEvaluator().evaluate(bundle_copy, t)
    assert report.cases[0].original_incident_present is False


def test_object_remove_prevents_incident(bundle_copy):
    t = [CounterfactualTransform(type="object_remove", target="human_proxy_01")]
    report = CounterfactualEvaluator().evaluate(bundle_copy, t)
    assert report.cases[0].original_incident_present is False


def test_report_contains_original_summary(bundle_copy):
    t = [CounterfactualTransform(type="object_remove", target="human_proxy_01")]
    report = CounterfactualEvaluator().evaluate(bundle_copy, t)
    assert report.original_summary["rule_id"] == "cart_person_distance"
    assert report.limitations


def test_max_cases_enforced(bundle_copy):
    transforms = sweep_transforms("cart_person_distance.min_distance_m=0.1:1.0:0.1")
    report = CounterfactualEvaluator(max_cases=3).evaluate(bundle_copy, transforms)
    assert len(report.cases) == 3


def test_original_bundle_not_mutated(bundle_copy):
    session = bundle_copy / "session_excerpt.jsonl"
    before = _digest(session)
    t = [
        CounterfactualTransform(type="object_remove", target="human_proxy_01"),
        CounterfactualTransform(
            type="object_speed_scale", target="human_proxy_01", params={"factor": 0.5}
        ),
    ]
    CounterfactualEvaluator().evaluate(bundle_copy, t)
    assert _digest(session) == before


def test_baseline_must_reproduce(tmp_path, bundle_copy):
    # corrupt the incident.json so baseline no longer matches
    inc = json.loads((bundle_copy / "incident.json").read_text())
    inc[0]["rule_id"] = "nonexistent_rule"
    (bundle_copy / "incident.json").write_text(json.dumps(inc))
    with pytest.raises(CounterfactualError):
        CounterfactualEvaluator().evaluate(
            bundle_copy, [CounterfactualTransform(type="object_remove", target="human_proxy_01")]
        )


def test_cli_end_to_end(bundle_copy, capsys):
    rc = main_counterfactual(
        [
            str(bundle_copy),
            "--sweep-rule",
            "cart_person_distance.min_distance_m=0.2:0.6:0.2",
            "--remove-object",
            "human_proxy_01",
            "--no-write-reports",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "PREVENTED" in out
    assert "cart_person_distance" in out


def test_cli_writes_report(bundle_copy):
    rc = main_counterfactual(
        [
            str(bundle_copy),
            "--remove-object",
            "human_proxy_01",
        ]
    )
    assert rc == 0
    data = json.loads((bundle_copy / "counterfactual_report.json").read_text())
    assert data["incident_id"]
    assert (bundle_copy / "counterfactual_report.md").exists()


def test_cli_no_transforms_errors(bundle_copy):
    rc = main_counterfactual([str(bundle_copy)])
    assert rc == 2
