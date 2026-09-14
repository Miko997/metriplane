# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "tests/fixtures/camera_trust/multicam_session.jsonl",
    "tests/fixtures/contracts/sentinel_minimal_session.jsonl",
    "tests/fixtures/contracts/forecast_session.jsonl",
    "tests/fixtures/contracts/operator_demo_session.jsonl",
    "tests/fixtures/contracts/sentinel_expected.yaml",
    "benchmarks/physical_observability/scenarios/blocked_path_001/input_session.jsonl",
    "benchmarks/physical_observability/scenarios/blocked_path_001/object_registry.yaml",
    "benchmarks/physical_observability/scenarios/blocked_path_001/rules.yaml",
    "benchmarks/physical_observability/scenarios/blocked_path_001/scenario.yaml",
    "benchmarks/physical_observability/scenarios/blocked_path_001/expected_alerts.json",
    "benchmarks/physical_observability/scenarios/blocked_path_001/expected_incidents.json",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/input_session.jsonl",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/object_registry.yaml",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/rules.yaml",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/scenario.yaml",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/expected_alerts.json",
    "benchmarks/physical_observability/scenarios/restricted_zone_001/expected_incidents.json",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/input_session.jsonl",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/object_registry.yaml",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/rules.yaml",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/scenario.yaml",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/expected_alerts.json",
    "benchmarks/physical_observability/scenarios/unsafe_proximity_001/expected_incidents.json",
    "datasets/demo/atlas/assembly_cell_missing_tool.jsonl",
    "evidence/incidents/INC-0001/session_excerpt.jsonl",
    "evidence/incidents/INC-0001/alerts.jsonl",
    "evidence/incidents/INC-0001/trace.csv",
    "evidence/incidents/INC-0001/incident.json",
    "evidence/incidents/INC-0001/objects.yaml",
    "evidence/incidents/INC-0001/rules.yaml",
    "evidence/incidents/INC-0001/expected.yaml",
    "evidence/incidents/INC-0001/CHECKSUMS.sha256",
    "evidence/incidents/INC-DIST-001/session_excerpt.jsonl",
    "evidence/incidents/INC-DIST-001/alerts.jsonl",
    "evidence/incidents/INC-DIST-001/trace.csv",
    "evidence/incidents/INC-DIST-001/incident.json",
    "evidence/incidents/INC-DIST-001/objects.yaml",
    "evidence/incidents/INC-DIST-001/rules.yaml",
    "evidence/incidents/INC-DIST-001/CHECKSUMS.sha256",
    "evidence/experiments/assistant_demo/camera_trust.json",
]


def test_required_release_fixtures_exist_and_are_non_empty():
    for rel in REQUIRED_FILES:
        path = REPO / rel
        assert path.exists(), f"Required release fixture is missing from checkout: {rel}"
        assert path.is_file(), f"Required release fixture is not a file: {rel}"
        assert path.stat().st_size > 0, f"Required release fixture is empty: {rel}"

    current_version_workflows = (
        ".github/workflows/ros2-mcap-recorded-state.yml",
        ".github/workflows/massrobotics-amr-offline-replay.yml",
        ".github/workflows/robomimic-lowdim.yml",
        ".github/workflows/external-source-family-matrix.yml",
    )
    for rel in current_version_workflows:
        workflow = (REPO / rel).read_text(encoding="utf-8")
        assert "materialize_current_version_fixture" in workflow

    for rel in (
        ".github/workflows/ros2-mcap-recorded-state.yml",
        ".github/workflows/massrobotics-amr-offline-replay.yml",
    ):
        workflow = (REPO / rel).read_text(encoding="utf-8")
        assert 'git worktree add --detach "$freeze" "$ADAPTER_COMMIT"' in workflow
        assert 'uv pip install --system "$freeze"' in workflow

    gate = (REPO / "tools/cross_adapter_gate.py").read_text(encoding="utf-8")
    assert "installed_version = version_output.strip()" in gate
    assert "installed_version=installed_version" in gate
