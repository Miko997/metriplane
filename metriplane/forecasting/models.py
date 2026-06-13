from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ForecastType = Literal[
    "future_forbidden_zone",
    "future_minimum_distance",
    "future_zone_capacity",
    "future_speed_limit",
    "future_blocked_zone",
]


class ProjectedPointModel(BaseModel):
    dt_s: float
    pos_world: tuple[float, float, float]


class RiskForecastModel(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_type: Literal["risk_forecast"] = "risk_forecast"
    forecast_type: ForecastType
    severity: Literal["info", "warning", "high", "critical"] = "warning"
    ts: float
    horizon_s: float
    time_to_violation_s: float | None = None
    confidence: float = 0.5

    object_ids: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    contract_id: str | None = None
    rule_id: str | None = None
    explanation: str
    projected_path: list[ProjectedPointModel] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
