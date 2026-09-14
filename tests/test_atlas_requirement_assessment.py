# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Requirement conclusions are additive to the frozen sampled-event policy."""

from __future__ import annotations

import pytest

from metriplane.atlas.assessment import RequirementAssessment
from metriplane.atlas.models import AssetModel, ProcessModel, ProcessStepModel
from metriplane.atlas.process_model import AssetObservation, ProcessEvaluator


def _evaluator(threshold: float = 1.0, *, tools: int = 1) -> ProcessEvaluator:
    return ProcessEvaluator(
        run_id="assessment-test",
        work_order_id="work-order",
        process=ProcessModel(
            process_id="handoff",
            steps=[
                ProcessStepModel(
                    step_id="handoff-step",
                    label="Handoff",
                    expected_asset_types=["material"],
                    required_assets=[f"tool-{index}" for index in range(tools)],
                    required_zone="handoff-zone",
                    max_wait_s=threshold,
                )
            ],
        ),
    )


def _sample(
    evaluator: ProcessEvaluator,
    ts: float,
    *,
    inside: tuple[str, ...] = ("material",),
    omitted: tuple[str, ...] = (),
) -> list[str]:
    frame_id = evaluator.assessment().coverage.sample_count
    observations = [
        AssetObservation(
            asset=AssetModel(
                object_id=asset_id,
                asset_id=asset_id,
                asset_type="material" if asset_id == "material" else "tool",
                label=asset_id,
            ),
            ts=ts,
            frame_id=frame_id,
            zone_id="handoff-zone" if asset_id in inside else None,
            station_id=None,
        )
        for asset_id in ("material", *evaluator.process.steps[0].required_assets)
        if asset_id not in omitted
    ]
    return [event.event_type for event in evaluator.update(observations, ts, frame_id)]


def test_no_trigger_is_not_exercised_even_after_a_long_recording() -> None:
    evaluator = _evaluator()
    assert _sample(evaluator, 0, inside=()) == []
    assert _sample(evaluator, 10, inside=()) == []
    assessment = evaluator.assessment()
    assert assessment.outcome == "not_exercised"
    assert assessment.steps[0].trigger_ts is None
    assert assessment.steps[0].observed_wait_s is None
    assert assessment.steps[0].observed_wait_lower_bound_s is None
    assert evaluator.incidents == []


def test_pending_eof_exposes_a_lower_bound_and_never_satisfaction() -> None:
    evaluator = _evaluator()
    assert _sample(evaluator, 0) == ["required_asset_missing"]
    assert _sample(evaluator, 0.5) == []
    assessment = evaluator.assessment()
    step = assessment.steps[0]
    assert assessment.outcome == step.outcome == "unresolved"
    assert step.observed_wait_s is None
    assert step.observed_wait_lower_bound_s == 0.5
    assert step.completion_ts is None
    assert step.coverage_gaps is False
    assert assessment.coverage.continuous_state_established is False
    assert evaluator.incidents == []


def test_eof_after_proven_violation_remains_incomplete_and_violated() -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    assert _sample(evaluator, 1) == ["step_delayed"]
    step = evaluator.assessment().steps[0]
    assert step.outcome == "violated"
    assert step.completion_ts is None
    assert step.observed_wait_s is None
    assert step.observed_wait_lower_bound_s == 1
    assert step.detection_ts == step.missing_episodes[0].detection_ts == 1
    assert len(evaluator.incidents) == 1
    assert evaluator.incidents[0].end_ts == 1


def test_completion_retains_violation_and_distinguishes_detection_from_wait() -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    _sample(evaluator, 1)
    assert _sample(evaluator, 2, inside=("material", "tool-0")) == [
        "required_asset_present",
        "step_completed",
    ]
    step = evaluator.assessment().steps[0]
    assert step.outcome == "violated"
    assert step.observed_wait_s == 2
    assert step.observed_wait_lower_bound_s is None
    assert step.detection_ts == 1
    assert step.completion_ts == 2
    assert step.missing_episodes[0].last_missing_ts == 1
    assert step.missing_episodes[0].end_ts == 2
    assert evaluator.deviations[0].duration_s == 1
    assert evaluator.incidents[0].end_ts == 1


@pytest.mark.parametrize("arrival", [0.75, 1.0, 1.25])
def test_arrival_before_at_and_after_threshold_keeps_presence_precedence(arrival: float) -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    _sample(evaluator, 0.5)
    assert _sample(evaluator, arrival, inside=("material", "tool-0")) == [
        "required_asset_present",
        "step_completed",
    ]
    assessment = evaluator.assessment()
    step = assessment.steps[0]
    assert assessment.policy == "legacy_sampled_missing_v1"
    assert step.outcome == "satisfied"
    assert step.observed_wait_s == arrival
    assert step.missing_episodes[0].last_missing_ts == 0.5
    assert step.missing_episodes[0].deadline_ts == 1
    assert step.missing_episodes[0].end_ts == arrival
    assert (
        "arrival_observed_after_threshold_without_sampled_violation" in step.coverage_notes
    ) is (arrival > 1)
    assert evaluator.incidents == []


@pytest.mark.parametrize("start,missing,violated", [(1.0, 1.2, False), (3.3, 3.5, True)])
def test_legacy_binary_float_threshold_is_not_silently_redefined(
    start: float, missing: float, violated: bool
) -> None:
    evaluator = _evaluator(0.2)
    _sample(evaluator, start)
    emitted = _sample(evaluator, missing)
    assert ("step_delayed" in emitted) is violated
    step = evaluator.assessment().steps[0]
    assert step.outcome == ("violated" if violated else "unresolved")
    # Display arithmetic is intentionally independent of binary-float detection.
    assert step.observed_wait_lower_bound_s == 0.2
    assert step.missing_episodes[0].deadline_ts == missing


def test_zero_wait_missing_detects_immediately_but_immediate_presence_completes() -> None:
    missing = _evaluator(0)
    present = _evaluator(0)
    assert _sample(missing, 0) == ["required_asset_missing", "step_delayed"]
    assert _sample(present, 0, inside=("material", "tool-0")) == [
        "required_asset_present",
        "step_completed",
    ]
    assert missing.assessment().outcome == "violated"
    assert present.assessment().outcome == "satisfied"
    assert present.assessment().steps[0].observed_wait_s == 0


def test_first_missing_asset_reset_keeps_total_wait_and_prior_violation() -> None:
    evaluator = _evaluator(tools=2)
    _sample(evaluator, 0, inside=("material", "tool-1"))
    assert _sample(evaluator, 1, inside=("material", "tool-1")) == ["step_delayed"]
    assert _sample(evaluator, 1.5, inside=("material", "tool-0")) == ["required_asset_missing"]
    _sample(evaluator, 2, inside=("material", "tool-0", "tool-1"))
    step = evaluator.assessment().steps[0]
    assert step.outcome == "violated"
    assert step.observed_wait_s == 2
    first, second = step.missing_episodes
    assert first.asset_id == "tool-0"
    assert first.detection_ts == 1
    assert first.end_ts == 1.5
    assert first.end_reason == "first_missing_asset_changed"
    assert second.asset_id == "tool-1"
    assert second.start_ts == 1.5
    assert second.deadline_ts == 2.5
    assert second.detection_ts is None
    assert second.end_ts == 2
    assert len(evaluator.incidents) == 1
    assert evaluator.emitted_delay_for_step == set()


@pytest.mark.parametrize("omitted", [(), ("material",)])
def test_trigger_gap_is_explicit_and_does_not_reset_legacy_timer(omitted: tuple[str, ...]) -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    assert _sample(evaluator, 0.5, inside=(), omitted=omitted) == []
    assert _sample(evaluator, 2) == ["step_delayed"]
    step = evaluator.assessment().steps[0]
    assert step.coverage_gaps is True
    expected = (
        "trigger_not_observed_while_pending" if omitted else "trigger_ineligible_while_pending"
    )
    assert expected in step.coverage_notes
    assert step.trigger_ts == 0
    assert step.missing_episodes[0].start_ts == 0
    assert evaluator.incidents[0].start_ts == 0


def test_trigger_gap_at_eof_does_not_invent_an_observed_wait() -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    _sample(evaluator, 0.5)
    _sample(evaluator, 100, inside=())
    step = evaluator.assessment().steps[0]
    assert step.outcome == "unresolved"
    assert step.observed_wait_s is None
    assert step.observed_wait_lower_bound_s == 0.5
    assert step.last_evaluated_ts == 0.5
    assert evaluator.assessment().coverage.last_ts == 100
    assert evaluator.incidents == []


def test_missing_required_observation_is_distinct_from_observed_outside_zone() -> None:
    outside = _evaluator()
    unobserved = _evaluator()
    assert _sample(outside, 0) == _sample(unobserved, 0, omitted=("tool-0",))
    assert outside.assessment().steps[0].coverage_gaps is False
    assert unobserved.assessment().steps[0].coverage_gaps is True
    assert unobserved.assessment().steps[0].coverage_notes == ["required_asset_not_observed"]


def test_later_sequential_step_is_not_exercised_in_same_completion_frame() -> None:
    evaluator = _evaluator()
    first = evaluator.process.steps[0]
    evaluator.process.steps.append(first.model_copy(update={"step_id": "next-step"}))
    _sample(evaluator, 0, inside=("material", "tool-0"))
    assessment = evaluator.assessment()
    assert [step.outcome for step in assessment.steps] == ["satisfied", "not_exercised"]
    assert assessment.outcome == "not_exercised"
    assert assessment.counts == {
        "satisfied": 1,
        "violated": 0,
        "unresolved": 0,
        "not_exercised": 1,
    }
    assert evaluator.completed_steps == ["handoff-step"]


def test_requirement_free_step_completes_with_zero_observed_wait() -> None:
    evaluator = _evaluator(tools=0)
    assert _sample(evaluator, 0) == ["step_completed"]
    step = evaluator.assessment().steps[0]
    assert step.outcome == "satisfied"
    assert step.observed_wait_s == 0
    assert step.missing_episodes == []


def test_assessment_is_a_detached_snapshot_and_round_trips_without_state_changes() -> None:
    evaluator = _evaluator()
    _sample(evaluator, 0)
    earlier = evaluator.assessment()
    earlier.steps[0].missing_episodes[0].event_ids.append("not-an-event")
    _sample(evaluator, 0.5)
    current = evaluator.assessment()
    assert earlier.steps[0].observed_wait_lower_bound_s == 0
    assert current.steps[0].observed_wait_lower_bound_s == 0.5
    assert current.steps[0].missing_episodes[0].event_ids == ["evt_0001"]
    encoded = current.model_dump_json()
    assert RequirementAssessment.model_validate_json(encoded) == current
    assert evaluator.assessment().model_dump_json() == encoded
