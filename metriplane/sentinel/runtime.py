# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metriplane.schema import ObjectStateModel
from metriplane.sentinel.config import SentinelConfig
from metriplane.sentinel.events import RuleAlert
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.status import SentinelModeStatus


@dataclass
class SentinelUpdate:
    ts: float
    frame_id: int
    alerts: list[RuleAlert]
    open_incident_count: int


class SentinelError(RuntimeError):
    pass


class SentinelRuntime:
    """
    Non-invasive shadow-auditor runtime.

    Consumes object states frame by frame, applies a spatial contract package,
    accumulates alerts, groups them into incidents, and writes a run summary at
    shutdown. It never controls anything: control_enabled is always False.
    """

    def __init__(self, config: SentinelConfig, run_dir: str | Path | None = None,
                 run_id: str | None = None):
        self.config = config
        self.run_dir = Path(run_dir) if run_dir else None
        self.run_id = run_id
        self.health = "OK"
        self._engine = None
        self._registry = None
        self._contract_id: str | None = None
        self._package = None
        self._forecast_engine = None
        self._forecasts_total = 0
        self._camera_trust = None
        self._alerts: list[RuleAlert] = []
        self._objects_seen: set[str] = set()
        self._frames = 0
        self._last_event_ts: float | None = None

        if config.enabled and config.contracts_file:
            self._load_contract()
            self._load_forecasting()

    def _load_contract(self) -> None:
        from metriplane.contracts.engine import SpatialContractEngine
        from metriplane.contracts.load import ContractLoadError, load_spatial_contract
        from metriplane.sentinel.registry import load_registry

        try:
            package = load_spatial_contract(self.config.contracts_file)
        except ContractLoadError as e:
            if self.config.fail_fast_on_contract_error:
                raise SentinelError(str(e)) from e
            self.health = "DEGRADED"
            return
        if self.config.objects_file:
            try:
                self._registry = load_registry(self.config.objects_file)
            except Exception:
                self.health = "DEGRADED"
        self._engine = SpatialContractEngine(package, self._registry)
        self._engine.run_id = self.run_id
        self._contract_id = package.contract_id
        self._package = package

    def _load_forecasting(self) -> None:
        fc = self.config.forecasting
        if not fc or not fc.get("enabled") or self._package is None:
            return
        from metriplane.forecasting.engine import ForecastEngine

        zone_map = None
        if self.config.zones_file:
            try:
                from metriplane.zones import load_zones
                zone_map = load_zones(Path(self.config.zones_file))
            except Exception:
                self.health = "DEGRADED"
        self._forecast_engine = ForecastEngine(
            horizon_s=float(fc.get("horizon_s", 2.0)),
            step_s=float(fc.get("step_s", 0.2)),
            min_confidence=float(fc.get("min_confidence", 0.5)),
            max_projected_points=int(fc.get("max_projected_points", 12)),
            include_projected_path=bool(fc.get("include_projected_path", True)),
            cooldown_s=float(fc.get("cooldown_s", 0.0)),
            contract_package=self._package,
            registry=self._registry,
            zone_map=zone_map,
        )

    @classmethod
    def from_config(cls, sentinel_dict: dict[str, Any] | None,
                    run_dir: str | Path | None = None,
                    run_id: str | None = None) -> "SentinelRuntime":
        return cls(SentinelConfig.from_dict(sentinel_dict), run_dir, run_id)

    def update(self, ts: float, frame_id: int,
               objects: list[ObjectStateModel], frame: Any = None) -> SentinelUpdate:
        self._frames += 1
        # Camera trust: analyze the full frame when it carries per-camera observations.
        if frame is not None and getattr(frame, "raw_per_camera", None):
            try:
                if self._camera_trust is None:
                    from metriplane.camera_trust.analyzer import CameraTrustAnalyzer
                    self._camera_trust = CameraTrustAnalyzer()
                self._camera_trust.update(frame)
            except Exception:
                self.health = "DEGRADED"
        frame_alerts: list[RuleAlert] = []
        if self._engine is not None:
            try:
                events = self._engine.update(ts, objects)
            except Exception:
                self.health = "DEGRADED"
                events = []
            for ev in events:
                alert = ev.to_rule_alert()
                self._alerts.append(alert)
                frame_alerts.append(alert)
                self._last_event_ts = ts
        if self._forecast_engine is not None:
            try:
                forecasts = self._forecast_engine.update(ts, objects)
                self._forecasts_total += len(forecasts)
            except Exception:
                self.health = "DEGRADED"
        for obj in objects:
            self._objects_seen.add(str(obj.id))
        incidents = build_incidents(self._alerts)
        return SentinelUpdate(
            ts=ts, frame_id=frame_id, alerts=frame_alerts,
            open_incident_count=len(incidents),
        )

    def incidents(self):
        return build_incidents(self._alerts)

    def status(self) -> SentinelModeStatus:
        incidents = build_incidents(self._alerts)
        return SentinelModeStatus(
            mode="shadow_auditor" if self.config.enabled else "disabled",
            control_enabled=False,
            run_id=self.run_id,
            contract_id=self._contract_id,
            objects_tracked=len(self._objects_seen),
            active_alerts=len(self._alerts),
            open_incidents=len(incidents),
            closed_incidents=len(incidents),
            risk_forecasts_enabled=self._forecast_engine is not None,
            last_event_ts=self._last_event_ts,
            health=self.health,
            details={"frames_processed": self._frames,
                     "forecasts_total": self._forecasts_total},
        )

    def summary(self) -> dict[str, Any]:
        incidents = build_incidents(self._alerts)
        return {
            "phase": 17,
            "mode": "shadow_auditor" if self.config.enabled else "disabled",
            "control_enabled": False,
            "run_id": self.run_id,
            "contract_id": self._contract_id,
            "frames_processed": self._frames,
            "objects_tracked": len(self._objects_seen),
            "alerts_total": len(self._alerts),
            "incidents_total": len(incidents),
            "forecasts_total": self._forecasts_total,
            "risk_forecasts_enabled": self._forecast_engine is not None,
            "health": self.health,
            "pass": True,
        }

    def _emit_fleet_heartbeat(self) -> None:
        if not (self.config.fleet and self.config.fleet.get("enabled") and self.run_dir):
            return
        try:
            from metriplane.fleet.agent import FleetAgent
            status = self.status()
            agent = FleetAgent.from_config_dict(
                self.config.fleet,
                metrics_provider=lambda: {
                    "health_overall": status.health,
                    "objects_tracked": status.objects_tracked,
                    "active_incidents": status.open_incidents,
                },
                run_dir=self.run_dir,
                run_id=self.run_id,
            )
            if agent is not None:
                agent.emit_once()
        except Exception:
            self.health = "DEGRADED"

    def _persist_artifacts(self) -> None:
        """Write incidents.json + alerts.jsonl so a run dir is self-describing for the
        dashboard / assistant (in addition to sentinel_summary.json)."""
        if self.run_dir is None:
            return
        try:
            from metriplane.sentinel.events import (
                write_alerts_jsonl,
                write_incidents_json,
            )
            self.run_dir.mkdir(parents=True, exist_ok=True)
            write_incidents_json(self.incidents(), self.run_dir / "incident.json")
            write_alerts_jsonl(self._alerts, self.run_dir / "alerts.jsonl")
        except Exception:
            self.health = "DEGRADED"

    def _persist_camera_trust(self) -> None:
        if self._camera_trust is None or self.run_dir is None:
            return
        try:
            report = self._camera_trust.report()
            if not report.camera_scores:
                return
            from metriplane.camera_trust.export import export_camera_trust_report
            self.run_dir.mkdir(parents=True, exist_ok=True)
            export_camera_trust_report(self.run_dir / "camera_trust.json", report)
        except Exception:
            self.health = "DEGRADED"

    def close(self) -> Path | None:
        self._emit_fleet_heartbeat()
        self._persist_artifacts()
        self._persist_camera_trust()
        if not (self.config.export_summary and self.run_dir):
            return None
        import json
        self.run_dir.mkdir(parents=True, exist_ok=True)
        out = self.run_dir / "sentinel_summary.json"
        out.write_text(json.dumps(self.summary(), indent=2))
        return out
