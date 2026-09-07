# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Additive, recorded-sample assessments of the existing process evaluator.

This observer does not decide when the process evaluator emits events. In
particular, its ``satisfied`` outcome is scoped to the declared legacy sampled
policy, not to an unobserved physical arrival or a new arrival-deadline policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from metriplane.atlas.models import AtlasEvent, ProcessModel, ProcessStepModel


Outcome = Literal["satisfied", "violated", "unresolved", "not_exercised"]
POLICY = "legacy_sampled_missing_v1"


class AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SampleCoverage(AssessmentModel):
    scope: Literal["recorded_samples_only"] = "recorded_samples_only"
    sample_count: int = Field(ge=0)
    first_ts: float | None = None
    last_ts: float | None = None
    min_sample_interval_s: float | None = None
    max_sample_interval_s: float | None = None
    continuous_state_established: Literal[False] = False


class MissingEpisode(AssessmentModel):
    asset_id: str
    start_ts: float
    start_frame_id: int
    last_missing_ts: float
    deadline_ts: float
    max_wait_s: float
    detection_ts: float | None = None
    end_ts: float | None = None
    end_reason: Literal["required_assets_present", "first_missing_asset_changed"] | None = None
    event_ids: list[str] = Field(default_factory=list)


class StepAssessment(AssessmentModel):
    step_id: str
    label: str
    outcome: Outcome
    trigger_ts: float | None = None
    trigger_frame_id: int | None = None
    completion_ts: float | None = None
    completion_frame_id: int | None = None
    last_evaluated_ts: float | None = None
    observed_wait_s: float | None = None
    observed_wait_lower_bound_s: float | None = None
    detection_ts: float | None = None
    coverage_gaps: bool = False
    coverage_notes: list[str] = Field(default_factory=list)
    missing_episodes: list[MissingEpisode] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class RequirementAssessment(AssessmentModel):
    schema_version: Literal["metriplane.atlas.requirement_assessment.v1"] = (
        "metriplane.atlas.requirement_assessment.v1"
    )
    run_id: str
    work_order_id: str
    process_id: str
    policy: Literal["legacy_sampled_missing_v1"] = POLICY
    policy_details: dict[str, str] = Field(default_factory=lambda: {
        "threshold": "binary-float elapsed >= max_wait_s while a required asset is missing",
        "completion": "required-asset presence is evaluated before the missing-state threshold",
        "absence_timer": "resets when the first missing required asset changes",
        "trigger_gap": "legacy timer is retained while the trigger is ineligible",
        "scope": "outcomes describe the recorded samples under this policy only",
        "display_arithmetic": "durations use decimal differences of serialized timestamps",
    })
    outcome: Outcome
    counts: dict[str, int]
    coverage: SampleCoverage
    steps: list[StepAssessment]


def _elapsed(end: float, start: float) -> float:
    """Readable sample-time differences; never used to generate legacy events."""
    return float(Decimal(str(end)) - Decimal(str(start)))


@dataclass
class _StepRecord:
    trigger_ts: float | None = None
    trigger_frame_id: int | None = None
    completion_ts: float | None = None
    completion_frame_id: int | None = None
    last_evaluated_ts: float | None = None
    detection_ts: float | None = None
    coverage_gaps: bool = False
    notes: set[str] = field(default_factory=set)
    episodes: list[MissingEpisode] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)


@dataclass
class AssessmentObserver:
    """Track explanatory data without changing the process state machine."""

    records: dict[str, _StepRecord] = field(default_factory=dict)
    sample_count: int = 0
    first_ts: float | None = None
    last_ts: float | None = None
    min_interval: float | None = None
    max_interval: float | None = None

    def observe_sample(self, ts: float) -> None:
        if self.last_ts is not None:
            interval = _elapsed(ts, self.last_ts)
            self.min_interval = interval if self.min_interval is None else min(self.min_interval, interval)
            self.max_interval = interval if self.max_interval is None else max(self.max_interval, interval)
        if self.first_ts is None:
            self.first_ts = ts
        self.last_ts = ts
        self.sample_count += 1

    def observe_step(
        self,
        step: ProcessStepModel,
        events: list[AtlasEvent],
        ts: float,
        frame_id: int,
        *,
        eligible: bool,
        trigger_observed: bool,
        unobserved_required_assets: list[str],
    ) -> None:
        record = self.records.setdefault(step.step_id, _StepRecord())
        if not eligible:
            if record.trigger_ts is not None:
                record.coverage_gaps = True
                record.notes.add(
                    "trigger_ineligible_while_pending" if trigger_observed
                    else "trigger_not_observed_while_pending"
                )
            return

        if record.trigger_ts is None:
            record.trigger_ts = ts
            record.trigger_frame_id = frame_id
        record.last_evaluated_ts = ts
        if unobserved_required_assets:
            record.coverage_gaps = True
            record.notes.add("required_asset_not_observed")
        for event in events:
            record.event_ids.append(event.event_id)
            if event.event_type == "required_asset_missing":
                if record.episodes and record.episodes[-1].end_ts is None:
                    record.episodes[-1].end_ts = ts
                    record.episodes[-1].end_reason = "first_missing_asset_changed"
                    record.notes.add("first_missing_asset_changed_resets_absence_timer")
                threshold = step.max_wait_s or 0.0
                record.episodes.append(MissingEpisode(
                    asset_id=event.asset_id or step.required_assets[0],
                    start_ts=ts,
                    start_frame_id=frame_id,
                    last_missing_ts=ts,
                    deadline_ts=float(Decimal(str(ts)) + Decimal(str(threshold))),
                    max_wait_s=threshold,
                    event_ids=[event.event_id],
                ))
            elif event.event_type == "step_delayed":
                if record.detection_ts is None:
                    record.detection_ts = ts
                if record.episodes:
                    record.episodes[-1].detection_ts = ts
                    record.episodes[-1].event_ids.append(event.event_id)
            elif event.event_type == "step_completed":
                record.completion_ts = ts
                record.completion_frame_id = frame_id
                if record.episodes and record.episodes[-1].end_ts is None:
                    episode = record.episodes[-1]
                    episode.end_ts = ts
                    episode.end_reason = "required_assets_present"
                    if record.detection_ts is None and (
                        Decimal(str(ts)) - Decimal(str(episode.start_ts))
                        > Decimal(str(episode.max_wait_s))
                    ):
                        record.notes.add("arrival_observed_after_threshold_without_sampled_violation")
        if record.episodes and record.episodes[-1].end_ts is None:
            record.episodes[-1].last_missing_ts = ts

    def assessment(
        self, process: ProcessModel, run_id: str, work_order_id: str
    ) -> RequirementAssessment:
        steps: list[StepAssessment] = []
        for step in process.steps:
            record = self.records.get(step.step_id, _StepRecord())
            outcome: Outcome
            if record.detection_ts is not None:
                outcome = "violated"
            elif record.completion_ts is not None:
                outcome = "satisfied"
            elif record.trigger_ts is not None:
                outcome = "unresolved"
            else:
                outcome = "not_exercised"
            complete_wait = None
            wait_lower_bound = None
            if record.trigger_ts is not None:
                if record.completion_ts is not None:
                    complete_wait = _elapsed(record.completion_ts, record.trigger_ts)
                elif record.last_evaluated_ts is not None:
                    wait_lower_bound = _elapsed(record.last_evaluated_ts, record.trigger_ts)
            steps.append(StepAssessment(
                step_id=step.step_id,
                label=step.label,
                outcome=outcome,
                trigger_ts=record.trigger_ts,
                trigger_frame_id=record.trigger_frame_id,
                completion_ts=record.completion_ts,
                completion_frame_id=record.completion_frame_id,
                last_evaluated_ts=record.last_evaluated_ts,
                observed_wait_s=complete_wait,
                observed_wait_lower_bound_s=wait_lower_bound,
                detection_ts=record.detection_ts,
                coverage_gaps=record.coverage_gaps,
                coverage_notes=sorted(record.notes),
                missing_episodes=[episode.model_copy(deep=True) for episode in record.episodes],
                event_ids=list(record.event_ids),
            ))
        counts = {outcome: sum(step.outcome == outcome for step in steps) for outcome in (
            "satisfied", "violated", "unresolved", "not_exercised"
        )}
        aggregate: Outcome = "not_exercised"
        if counts["violated"]:
            aggregate = "violated"
        elif counts["unresolved"]:
            aggregate = "unresolved"
        elif steps and counts["satisfied"] == len(steps):
            aggregate = "satisfied"
        return RequirementAssessment(
            run_id=run_id,
            work_order_id=work_order_id,
            process_id=process.process_id,
            outcome=aggregate,
            counts=counts,
            coverage=SampleCoverage(
                sample_count=self.sample_count,
                first_ts=self.first_ts,
                last_ts=self.last_ts,
                min_sample_interval_s=self.min_interval,
                max_sample_interval_s=self.max_interval,
            ),
            steps=steps,
        )
