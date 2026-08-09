# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field

from metriplane.atlas.models import (
    AssetModel,
    AtlasDeviation,
    AtlasEvent,
    AtlasIncident,
    ProcessModel,
    ProcessStepModel,
)


@dataclass
class AssetObservation:
    asset: AssetModel
    ts: float
    frame_id: int
    zone_id: str | None
    station_id: str | None


@dataclass
class ProcessEvaluator:
    run_id: str
    process: ProcessModel
    work_order_id: str
    _event_counter: int = 0
    _deviation_counter: int = 0
    _incident_counter: int = 0
    completed_steps: list[str] = field(default_factory=list)
    active_missing: dict[str, tuple[float, list[str]]] = field(default_factory=dict)
    active_missing_asset: dict[str, str] = field(default_factory=dict)
    emitted_delay_for_step: set[str] = field(default_factory=set)
    deviations: list[AtlasDeviation] = field(default_factory=list)
    incidents: list[AtlasIncident] = field(default_factory=list)

    def _next_event_id(self) -> str:
        self._event_counter += 1
        return f"evt_{self._event_counter:04d}"

    def _next_deviation_id(self) -> str:
        self._deviation_counter += 1
        return f"dev_{self._deviation_counter:04d}"

    def _next_incident_id(self) -> str:
        self._incident_counter += 1
        return f"INC-{self._incident_counter:04d}"

    def update(self, observations: list[AssetObservation], ts: float, frame_id: int) -> list[AtlasEvent]:
        events: list[AtlasEvent] = []
        by_type: dict[str, list[AssetObservation]] = {}
        by_asset: dict[str, AssetObservation] = {}
        for obs in observations:
            by_type.setdefault(obs.asset.asset_type, []).append(obs)
            by_asset[obs.asset.asset_id] = obs

        for step in self.process.steps:
            if step.step_id in self.completed_steps:
                continue
            step_events = self._evaluate_step(step, by_type, by_asset, ts, frame_id)
            events.extend(step_events)
            break
        return events

    def _evaluate_step(
        self,
        step: ProcessStepModel,
        by_type: dict[str, list[AssetObservation]],
        by_asset: dict[str, AssetObservation],
        ts: float,
        frame_id: int,
    ) -> list[AtlasEvent]:
        events: list[AtlasEvent] = []
        candidate = self._find_step_asset(step, by_type)
        required_present = self._required_assets_present(step, by_asset)

        if candidate and not step.required_assets:
            events.append(self._event(
                ts, frame_id, "step_completed", "info",
                f"{step.label} completed.",
                candidate.asset,
                step,
                candidate.zone_id,
                candidate.station_id,
            ))
            self.completed_steps.append(step.step_id)
            return events

        if not candidate and step.expected_asset_types:
            return events

        if step.required_assets and required_present:
            obs = by_asset.get(step.required_assets[0])
            if obs is not None:
                events.append(self._event(
                    ts, frame_id, "required_asset_present", "info",
                    f"{obs.asset.label} was present for {step.label}.",
                    obs.asset, step, obs.zone_id, obs.station_id,
                ))
            self.active_missing.pop(step.step_id, None)
            self.active_missing_asset.pop(step.step_id, None)
            self.completed_steps.append(step.step_id)
            events.append(self._event(
                ts, frame_id, "step_completed", "info",
                f"{step.label} completed.",
                obs.asset if obs else None,
                step,
                obs.zone_id if obs else None,
                obs.station_id if obs else None,
            ))
            return events

        if step.required_assets:
            missing_asset_id = self._first_missing_required_asset(step, by_asset)
            if missing_asset_id is None:
                missing_asset_id = step.required_assets[0]
            active_asset_id = self.active_missing_asset.get(step.step_id)
            if active_asset_id is not None and active_asset_id != missing_asset_id:
                self.active_missing.pop(step.step_id, None)
                self.active_missing_asset.pop(step.step_id, None)
                self.emitted_delay_for_step.discard(step.step_id)
            start_ts, event_ids = self.active_missing.get(step.step_id, (ts, []))
            if step.step_id not in self.active_missing:
                asset = self._placeholder_asset(missing_asset_id)
                missing = self._event(
                    ts, frame_id, "required_asset_missing", "warning",
                    f"{missing_asset_id} was not present for {step.label}.",
                    asset, step, step.required_zone, step.required_station,
                )
                events.append(missing)
                event_ids = [missing.event_id]
                self.active_missing[step.step_id] = (start_ts, event_ids)
                self.active_missing_asset[step.step_id] = missing_asset_id
            threshold = step.max_wait_s or 0.0
            duration = ts - start_ts
            if duration >= threshold and step.step_id not in self.emitted_delay_for_step:
                asset = self._placeholder_asset(missing_asset_id)
                delayed = self._event(
                    ts, frame_id, "step_delayed", "warning",
                    f"{step.label} waited {round(duration, 3)} s for {missing_asset_id}.",
                    asset, step, step.required_zone, step.required_station,
                    value=round(duration, 3), threshold=threshold,
                )
                events.append(delayed)
                event_ids.append(delayed.event_id)
                self.emitted_delay_for_step.add(step.step_id)
                deviation = AtlasDeviation(
                    deviation_id=self._next_deviation_id(),
                    type="missing_required_asset",
                    severity="warning",
                    work_order_id=self.work_order_id,
                    process_step_id=step.step_id,
                    asset_id=missing_asset_id,
                    duration_s=round(duration, 3),
                    event_ids=list(event_ids),
                )
                self.deviations.append(deviation)
                self.incidents.append(AtlasIncident(
                    incident_id=self._next_incident_id(),
                    incident_type="missing_tool_caused_delay",
                    severity="warning",
                    title=f"{missing_asset_id} missing during {step.label}",
                    start_ts=start_ts,
                    end_ts=ts,
                    asset_ids=[missing_asset_id],
                    work_order_id=self.work_order_id,
                    event_ids=list(event_ids),
                    summary=f"{step.label} waited because {missing_asset_id} was absent.",
                ))
            self.active_missing[step.step_id] = (start_ts, event_ids)
        return events

    def _find_step_asset(
        self,
        step: ProcessStepModel,
        by_type: dict[str, list[AssetObservation]],
    ) -> AssetObservation | None:
        for asset_type in step.expected_asset_types:
            for obs in by_type.get(asset_type, []):
                if step.required_zone and obs.zone_id != step.required_zone:
                    continue
                if step.required_station and obs.station_id != step.required_station:
                    continue
                return obs
        return None

    def _required_assets_present(
        self,
        step: ProcessStepModel,
        by_asset: dict[str, AssetObservation],
    ) -> bool:
        return self._first_missing_required_asset(step, by_asset) is None

    def _first_missing_required_asset(
        self,
        step: ProcessStepModel,
        by_asset: dict[str, AssetObservation],
    ) -> str | None:
        for asset_id in step.required_assets:
            obs = by_asset.get(asset_id)
            if obs is None:
                return asset_id
            if step.required_zone and obs.zone_id != step.required_zone:
                return asset_id
            if step.required_station and obs.station_id != step.required_station:
                return asset_id
        return None

    def _event(
        self,
        ts: float,
        frame_id: int,
        event_type: str,
        severity: str,
        message: str,
        asset: AssetModel | None,
        step: ProcessStepModel,
        zone_id: str | None,
        station_id: str | None,
        value: float | str | None = None,
        threshold: float | str | None = None,
    ) -> AtlasEvent:
        return AtlasEvent(
            event_id=self._next_event_id(),
            run_id=self.run_id,
            ts=ts,
            frame_id=frame_id,
            event_type=event_type,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            asset_id=asset.asset_id if asset else None,
            asset_type=asset.asset_type if asset else None,
            work_order_id=self.work_order_id,
            process_step_id=step.step_id,
            zone_id=zone_id,
            station_id=station_id,
            value=value,
            threshold=threshold,
            evidence=[f"frame:{frame_id}", f"step:{step.step_id}"],
        )

    @staticmethod
    def _placeholder_asset(asset_id: str) -> AssetModel:
        return AssetModel(
            object_id=asset_id,
            asset_id=asset_id,
            asset_type="unknown_required_asset",
            label=asset_id,
        )
