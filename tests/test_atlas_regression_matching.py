# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from metriplane.atlas.regression import (
    _event_matches,
    _maximum_one_to_one_matching,
    run_regression,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_SPEC = ROOT / "evidence" / "paper_v2_0" / "atlas_run" / "regression_tests" / "INC-0001.yaml"
FROZEN_BUNDLE = ROOT / "evidence" / "paper_v2_0" / "atlas_run" / "evidence_bundles" / "INC-0001.zip"


def _write_spec(tmp_path: Path, *, duplicate_key: str | None = None) -> Path:
    data = yaml.safe_load(FROZEN_SPEC.read_text(encoding="utf-8"))
    data["source_bundle"] = str(FROZEN_BUNDLE)
    if duplicate_key is not None:
        data[duplicate_key].append(dict(data[duplicate_key][0]))
    spec_path = tmp_path / "regression.yaml"
    spec_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    return spec_path


@pytest.mark.parametrize(
    ("duplicate_key", "error_text"),
    [
        ("expected_events", "missing expected event"),
        ("expected_incidents", "missing distinct expected incident"),
    ],
)
def test_regression_does_not_reuse_one_actual_output(
    tmp_path: Path,
    duplicate_key: str,
    error_text: str,
) -> None:
    result = run_regression(_write_spec(tmp_path, duplicate_key=duplicate_key))

    assert result["pass"] is False
    assert any(error_text in error for error in result["errors"])


def test_frozen_generated_regression_remains_compatible(tmp_path: Path) -> None:
    assert run_regression(_write_spec(tmp_path))["pass"] is True


def test_regression_still_allows_selected_expected_outputs(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    data["expected_events"] = data["expected_events"][:1]
    data["expected_incidents"] = []
    spec_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    assert run_regression(spec_path)["pass"] is True


def test_regression_expected_event_order_remains_irrelevant(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    data["expected_events"].reverse()
    spec_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    assert run_regression(spec_path)["pass"] is True


def test_regression_preserves_incident_severity_diagnostic(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path)
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    data["expected_incidents"][0]["severity"] = "critical"
    spec_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    result = run_regression(spec_path)

    assert result["pass"] is False
    assert any("incident severity mismatch" in error for error in result["errors"])


def test_matching_reassigns_a_broad_match_to_satisfy_a_specific_one() -> None:
    expected = [
        {"event_type": "step_completed"},
        {"event_type": "step_completed", "asset_id": "kit_bin_1"},
    ]
    actual = [
        {"event_type": "step_completed", "asset_id": "kit_bin_1"},
        {"event_type": "step_completed", "asset_id": "fixture_1"},
    ]

    matches = _maximum_one_to_one_matching(expected, actual, _event_matches)

    assert matches == {0: 1, 1: 0}


def test_matching_preserves_duplicate_multiplicity() -> None:
    expected = [{"event_type": "step_completed"}, {"event_type": "step_completed"}]
    actual = [{"event_type": "step_completed"}, {"event_type": "step_completed"}]

    matches = _maximum_one_to_one_matching(expected, actual, _event_matches)

    assert set(matches) == {0, 1}
    assert _maximum_one_to_one_matching([], actual, _event_matches) == {}
