# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import fixture_root

from massrobotics_amr_adapter.constants import DEFAULT_CONFIG, DEFAULT_SOURCE_ROOT
from massrobotics_amr_adapter.core import convert

ADAPTER_COMMIT = "a" * 40
EXPECTED = {
    "incident": {
        "counts": [9, 4, 1, 1],
        "event_types": [
            "required_asset_missing",
            "step_delayed",
            "required_asset_present",
            "step_completed",
        ],
        "frames": [2, 5, 6, 6],
        "timestamps": [2.0, 5.0, 6.0, 6.0],
    },
    "control": {
        "counts": [9, 3, 0, 0],
        "event_types": [
            "required_asset_missing",
            "required_asset_present",
            "step_completed",
        ],
        "frames": [2, 4, 4],
        "timestamps": [2.0, 4.0, 4.0],
    },
}


def _converted(tmp_path: Path, variant: str) -> Path:
    output = tmp_path / f"{variant}-conversion"
    convert(
        DEFAULT_SOURCE_ROOT / variant,
        config_path=DEFAULT_CONFIG,
        output_root=output,
        adapter_commit=ADAPTER_COMMIT,
    )
    return fixture_root(output, variant)


def _run_atlas(fixture: Path, output: Path, *, run_id: str) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[3]
    program = r"""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.external_sources.execution import run_external_fixture

fixture = Path(sys.argv[1])
output = Path(sys.argv[2])
summary = run_external_fixture(fixture, output, run_id=sys.argv[3])
if not summary.passed:
    raise RuntimeError(summary.errors)
def rows(name):
    path = output / name
    return [json.loads(line) for line in path.read_text().splitlines() if line]
bundles = sorted((output / "evidence_bundles").glob("*.zip")) if (output / "evidence_bundles").is_dir() else []
regressions = sorted((output / "regression_tests").glob("*.yaml")) if (output / "regression_tests").is_dir() else []
def json_document(name):
    path = output / name
    return json.loads(path.read_text()) if path.is_file() else None
def regression_semantics(path):
    return "\n".join(
        line for line in path.read_text().splitlines()
        if not line.startswith("source_bundle:")
    )
def bundle_member_hashes(path):
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in sorted(archive.namelist())
        }
print(json.dumps({
    "counts": [summary.frame_count, summary.event_count, summary.deviation_count, summary.incident_count],
    "state": rows("state_segment.jsonl"),
    "events": rows("physical_event_log.jsonl"),
    "deviations": rows("deviations.jsonl"),
    "incidents": rows("incidents.jsonl"),
    "summary_bundle_verified": [item.verified for item in summary.evidence_bundles],
    "summary_regression_passed": [item.passed for item in summary.generated_regressions],
    "direct_bundle_verified": [verify_bundle(path)["pass"] for path in bundles],
    "direct_regression_passed": [run_regression(path)["pass"] for path in regressions],
    "bundle_member_hashes": [bundle_member_hashes(path) for path in bundles],
    "regression_semantics": [regression_semantics(path) for path in regressions],
    "process_trace": json_document("process_trace.json"),
    "reality_graph": json_document("reality_graph.json"),
}, allow_nan=False, sort_keys=True, separators=(",", ":")))
"""
    result = subprocess.run(
        [sys._base_executable, "-c", program, str(fixture), str(output), run_id],
        cwd=repository_root,
        env={
            **os.environ,
            "METRIPLANE_GIT_COMMIT": "b" * 40,
            "PYTHONPATH": str(repository_root),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_fixture_exact_event_sequence(tmp_path: Path, variant: str) -> None:
    fixture = _converted(tmp_path, variant)
    result = _run_atlas(fixture, tmp_path / f"{variant}-run", run_id=f"met55_{variant}")
    expected = EXPECTED[variant]
    assert result["counts"] == expected["counts"]
    assert [event["event_type"] for event in result["events"]] == expected["event_types"]
    assert [event["frame_id"] for event in result["events"]] == expected["frames"]
    assert [event["ts"] for event in result["events"]] == expected["timestamps"]


def test_incident_fixture_exact_event_sequence(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "incident")
    result = _run_atlas(fixture, tmp_path / "run", run_id="met55_incident_exact")
    assert [event["event_type"] for event in result["events"]] == EXPECTED["incident"][
        "event_types"
    ]
    assert [event["ts"] for event in result["events"]] == [2.0, 5.0, 6.0, 6.0]


def test_control_fixture_exact_event_sequence(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "control")
    result = _run_atlas(fixture, tmp_path / "run", run_id="met55_control_exact")
    assert [event["event_type"] for event in result["events"]] == EXPECTED["control"]["event_types"]
    assert [event["ts"] for event in result["events"]] == [2.0, 4.0, 4.0]


def test_incident_fixture_has_one_deviation_and_one_incident(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "incident")
    result = _run_atlas(fixture, tmp_path / "run", run_id="met55_incident_counts")
    assert result["counts"] == [9, 4, 1, 1]
    assert len(result["deviations"]) == 1
    assert len(result["incidents"]) == 1
    assert result["incidents"][0]["incident_type"] == "missing_tool_caused_delay"


def test_control_fixture_has_no_deviations_or_incidents(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "control")
    result = _run_atlas(fixture, tmp_path / "run", run_id="met55_control_counts")
    assert result["counts"] == [9, 3, 0, 0]
    assert result["deviations"] == []
    assert result["incidents"] == []


def test_incident_bundle_verifies(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "incident")
    output = tmp_path / "run"
    result = _run_atlas(fixture, output, run_id="met55_incident_bundle")
    assert result["summary_bundle_verified"] == [True]
    assert result["direct_bundle_verified"] == [True]
    assert (output / "evidence_bundles" / "INC-0001.zip").is_file()


def test_incident_generated_regression_passes(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "incident")
    output = tmp_path / "run"
    result = _run_atlas(fixture, output, run_id="met55_incident_regression")
    assert result["summary_regression_passed"] == [True]
    assert result["direct_regression_passed"] == [True]
    assert (output / "regression_tests" / "INC-0001.yaml").is_file()


def test_control_produces_no_incident_bundle(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "control")
    output = tmp_path / "run"
    result = _run_atlas(fixture, output, run_id="met55_control_bundle_absence")
    assert result["summary_bundle_verified"] == []
    assert result["direct_bundle_verified"] == []
    assert not (output / "evidence_bundles").exists()


def test_control_produces_no_generated_regression(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "control")
    output = tmp_path / "run"
    result = _run_atlas(fixture, output, run_id="met55_control_regression_absence")
    assert result["summary_regression_passed"] == []
    assert result["direct_regression_passed"] == []
    assert not (output / "regression_tests").exists()


@pytest.mark.parametrize("variant", ["incident", "control"])
def test_atlas_run_is_deterministic_three_times(tmp_path: Path, variant: str) -> None:
    fixture = _converted(tmp_path, variant)
    results = [
        _run_atlas(fixture, tmp_path / f"run-{index}", run_id=f"met55_{variant}_deterministic")
        for index in range(3)
    ]
    assert results[0] == results[1] == results[2]


def test_incident_atlas_run_is_deterministic_three_times(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "incident")
    results = [
        _run_atlas(fixture, tmp_path / f"run-{index}", run_id="met55_incident_repeat")
        for index in range(3)
    ]
    assert results[0] == results[1] == results[2]


def test_control_atlas_run_is_deterministic_three_times(tmp_path: Path) -> None:
    fixture = _converted(tmp_path, "control")
    results = [
        _run_atlas(fixture, tmp_path / f"run-{index}", run_id="met55_control_repeat")
        for index in range(3)
    ]
    assert results[0] == results[1] == results[2]
