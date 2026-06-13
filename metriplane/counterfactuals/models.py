from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TransformType = Literal[
    "rule_threshold_sweep",
    "object_speed_scale",
    "object_remove",
    "zone_translate",
    "camera_drop",
]


class CounterfactualTransform(BaseModel):
    type: TransformType
    target: str
    params: dict[str, Any] = Field(default_factory=dict)


class CounterfactualCaseResult(BaseModel):
    case_id: str
    transform: CounterfactualTransform
    pass_: bool = Field(alias="pass")
    original_incident_present: bool
    observed_incidents: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class CounterfactualReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    bundle_path: str
    incident_id: str
    original_summary: dict[str, Any]
    cases: list[CounterfactualCaseResult]
    limitations: list[str] = Field(default_factory=list)
