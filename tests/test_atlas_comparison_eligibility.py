# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from metriplane.atlas.improvement import compare_runs
from metriplane.atlas.run_assessment import read_run_assessment
from metriplane.atlas.runtime import run_atlas


def _run(
    root: Path,
    name: str,
    *,
    arrival: int | None = 3,
    threshold: float = 2.0,
    final_frame: int = 4,
    trigger: bool = True,
    missing_observation: bool = False,
    context_change: str | None = None,
    start_ts: float = 0.0,
    time_points: list[float] | None = None,
    trigger_frame: int = 0,
    interval_s: float = 1.0,
) -> Path:
    pack = root / f"{name}-pack"
    pack.mkdir()
    assets: dict[str, Any] = {
        "schema_version": "metriplane.atlas.asset_registry.v1",
        "assets": [
            {
                "object_id": "material",
                "asset_id": "workpiece",
                "asset_type": "material",
                "label": "Workpiece",
            },
            {"object_id": "tool", "asset_id": "tool", "asset_type": "tool", "label": "Tool"},
        ],
    }
    workspace = {
        "schema_version": "metriplane.atlas.workspace.v1",
        "cell_id": "test-cell",
        "units": "meters",
        "zones": [
            {"zone_id": "target", "zone_type": "work", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}
        ],
        "stations": [],
    }
    process = {
        "schema_version": "metriplane.atlas.process_model.v1",
        "process_id": "handoff",
        "steps": [
            {
                "step_id": "handoff",
                "label": "Handoff",
                "expected_asset_types": ["material"],
                "required_assets": ["tool"],
                "required_zone": "target",
                "max_wait_s": threshold,
            }
        ],
    }
    if context_change == "assets":
        assets["assets"][1]["label"] = "Another retained tool mapping label"
    if context_change == "workspace":
        workspace["units"] = "centimeters"
    for filename, data in (
        ("assets.yaml", assets),
        ("workspace.yaml", workspace),
        ("process.yaml", process),
    ):
        (pack / filename).write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    frames = []
    for index in range(len(time_points) if time_points is not None else final_frame + 1):
        tool_present = arrival is not None and index >= arrival
        trigger_present = trigger and index >= trigger_frame
        objects = [
            {
                "id": "material",
                "pos_world": [0.5, 0.5, 0.0] if trigger_present else [2.0, 2.0, 0.0],
                "zone": "target" if trigger_present else "outside_workspace",
            },
            {
                "id": "tool",
                "pos_world": [0.5, 0.5, 0.0] if tool_present else [2.0, 2.0, 0.0],
                "zone": "target" if tool_present else "outside_workspace",
            },
        ]
        if missing_observation and index == 1:
            objects.pop()
        interval = 0.5 if context_change == "clock" else interval_s
        timestamp = start_ts + (time_points[index] if time_points is not None else index * interval)
        frames.append(
            {
                "schema_version": "1.0",
                "source_backend": "another_source"
                if context_change == "source"
                else "synthetic_comparison",
                "ts": timestamp,
                "ts_sim_ns": int(timestamp * 1_000_000_000),
                "frame_id": index,
                "objects": objects,
            }
        )
    session = root / f"{name}.jsonl"
    session.write_text("".join(json.dumps(frame) + "\n" for frame in frames), encoding="utf-8")
    run = root / name
    run_atlas(session, pack, run, run_id=name)
    return run


def _compare(root: Path, before: Path, after: Path) -> dict[str, Any]:
    result = compare_runs(before, after, root / "comparison.json")
    assert json.loads((root / "comparison.json").read_text(encoding="utf-8")) == result
    return result


def _rebind_assessment(run: Path) -> None:
    path = run / "atlas_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["requirement_assessment_sha256"] = hashlib.sha256(
        (run / "requirement_assessment.json").read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_changed_deadline_on_identical_recording_is_not_improvement(tmp_path: Path) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", threshold=4.0)
    assert (before / "state_segment.jsonl").read_bytes() == (
        after / "state_segment.jsonl"
    ).read_bytes()
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "incompatible"
    assert result["comparison_status"] == "not_comparable"
    assert any(
        reason["code"] == "requirement_changed" for reason in result["eligibility"]["reasons"]
    )
    assert (
        result["observed_wait"]["before_total_s"] == result["observed_wait"]["after_total_s"] == 3.0
    )
    assert result["observed_wait"]["delta_s"] is None
    # Historical metric keys still describe their original sampled deviations.
    assert result["wait_time_delta_s"] == -2.0
    assert result["legacy_wait_metric"]["used_for_improvement_conclusion"] is False


def test_same_rule_different_recording_can_show_improvement(tmp_path: Path) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", arrival=1)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["eligible"] is True
    assert result["comparison_status"] == "improved"
    assert result["observed_wait"] == {
        "schema_version": "metriplane.atlas.observed_wait_comparison.v1",
        "before_total_s": 3.0,
        "after_total_s": 1.0,
        "delta_s": -2.0,
        "used_for_improvement_conclusion": True,
    }


def test_translating_clock_cannot_turn_float_boundary_into_improvement(tmp_path: Path) -> None:
    before = _run(tmp_path, "before", arrival=2, threshold=0.2, time_points=[3.3, 3.5, 3.55])
    after = _run(
        tmp_path,
        "after",
        arrival=2,
        threshold=0.2,
        time_points=[3.3, 3.5, 3.55],
        start_ts=4.7,
    )
    result = _compare(tmp_path, before, after)
    assert result["before_incidents"] == 1
    assert result["after_incidents"] == 0
    assert (
        result["observed_wait"]["before_total_s"]
        == result["observed_wait"]["after_total_s"]
        == 0.25
    )
    assert result["eligibility"]["status"] == "incompatible"
    assert result["comparison_status"] == "not_comparable"
    assert any(reason.get("field") == "time_policy" for reason in result["eligibility"]["reasons"])


@pytest.mark.parametrize("pad", [False, True], ids=["cropped-window", "padded-crop"])
def test_cropped_maniskill_recording_does_not_demonstrate_improvement(
    tmp_path: Path, pad: bool
) -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "examples/external_sources/maniskill_pickcube/incident"
    )
    session = fixture / "session.jsonl"
    before = tmp_path / "before"
    run_atlas(session, fixture / "domain-pack", before, run_id="before")
    frames = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    cropped = frames[71:]
    if pad:
        cropped += [cropped[-1]] * (len(frames) - len(cropped))
    after_session = tmp_path / "cropped.jsonl"
    rows = []
    for index, frame in enumerate(cropped):
        row = dict(frame)
        row.update(frame_id=index, ts=index * 0.05, ts_sim_ns=index * 50_000_000)
        rows.append(row)
    after_session.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    after = tmp_path / "after"
    run_atlas(after_session, fixture / "domain-pack", after, run_id="after")
    result = _compare(tmp_path, before, after)
    assert result["before_incidents"] == 1
    assert result["after_incidents"] == 0
    assert result["eligibility"]["eligible"] is False
    assert result["comparison_status"] == "not_comparable"
    assert any(
        reason.get("field") == "initial_relevant_zones"
        for reason in result["eligibility"]["reasons"]
    )


def test_first_sample_completion_has_insufficient_pretrigger_coverage(tmp_path: Path) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", arrival=0)
    assessment = read_run_assessment(after)
    assert assessment["process_assessment"]["outcome"] == "satisfied"
    assert "first_sample_completion_without_prior_observation" in assessment["coverage"]["gaps"]
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "insufficient_evidence"


def test_trigger_phase_change_without_wait_change_is_not_overall_improvement(
    tmp_path: Path,
) -> None:
    before = _run(
        tmp_path,
        "before",
        arrival=71,
        trigger_frame=66,
        threshold=0.2,
        final_frame=200,
        interval_s=0.05,
    )
    after = _run(
        tmp_path,
        "after",
        arrival=165,
        trigger_frame=160,
        threshold=0.2,
        final_frame=200,
        interval_s=0.05,
    )
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["eligible"] is True
    assert result["before_incidents"] == 1
    assert result["after_incidents"] == 0
    assert (
        result["observed_wait"]["before_total_s"]
        == result["observed_wait"]["after_total_s"]
        == 0.25
    )
    assert result["comparison_status"] == "incident_count_reduced"
    assert "No overall improvement or regression" in result["conclusion"]


@pytest.mark.parametrize(("arrival", "expected"), [(3, "unchanged"), (4, "regressed")])
def test_eligible_comparison_direction(tmp_path: Path, arrival: int, expected: str) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", arrival=arrival)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["eligible"] is True
    assert result["comparison_status"] == expected


@pytest.mark.parametrize("change", ["assets", "workspace", "source", "clock"])
def test_changed_evaluation_context_is_incompatible(tmp_path: Path, change: str) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", context_change=change)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "incompatible"
    assert result["comparison_status"] == "not_comparable"


@pytest.mark.parametrize(
    "options",
    [
        {"arrival": None, "final_frame": 1},
        {"arrival": None},
        {"trigger": False},
        {"missing_observation": True},
    ],
    ids=[
        "pending-before-deadline",
        "violated-but-unfinished",
        "not-exercised",
        "omitted-observation",
    ],
)
def test_incomplete_coverage_cannot_reduce_wait_to_zero(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", **options)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "insufficient_evidence"
    assert result["comparison_status"] == "not_comparable"
    assert result["observed_wait"]["after_total_s"] is None


def test_legacy_run_remains_readable_but_has_insufficient_comparison_evidence(
    tmp_path: Path,
) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", arrival=1)
    (before / "requirement_assessment.json").unlink()
    result = _compare(tmp_path, before, after)
    assert result["schema_version"] == "metriplane.atlas.before_after_improvement.v1"
    assert result["before_incidents"] == 1
    assert result["eligibility"]["status"] == "insufficient_evidence"
    assert result["comparison_status"] == "not_comparable"


@pytest.mark.parametrize(
    "filename", ["metrics.json", "requirement_assessment.json", "configs/process.yaml"]
)
def test_changed_bound_artifact_blocks_comparison(tmp_path: Path, filename: str) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", arrival=1)
    path = after / filename
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "insufficient_evidence"
    assert result["comparison_status"] == "not_comparable"


def test_rebound_forged_context_is_checked_against_retained_inputs(tmp_path: Path) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after")
    path = after / "requirement_assessment.json"
    assessment = json.loads(path.read_text(encoding="utf-8"))
    assessment["comparison_context"]["process_rules_sha256"] = "0" * 64
    path.write_text(json.dumps(assessment), encoding="utf-8")
    _rebind_assessment(after)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "insufficient_evidence"


def test_changed_producer_identity_is_incompatible(tmp_path: Path) -> None:
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after")
    path = after / "requirement_assessment.json"
    assessment = json.loads(path.read_text(encoding="utf-8"))
    assessment["comparison_context"]["evaluator_identity"]["implementation_sha256"][
        "assessment.py"
    ] = "0" * 64
    path.write_text(json.dumps(assessment), encoding="utf-8")
    _rebind_assessment(after)
    result = _compare(tmp_path, before, after)
    assert result["eligibility"]["status"] == "incompatible"
    assert any(
        reason.get("field") == "evaluator_identity" for reason in result["eligibility"]["reasons"]
    )


def test_assessment_reader_rejects_symlinked_input(tmp_path: Path) -> None:
    run = _run(tmp_path, "run")
    original = run / "configs/process.yaml"
    elsewhere = tmp_path / "elsewhere.yaml"
    original.rename(elsewhere)
    original.symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        read_run_assessment(run)
