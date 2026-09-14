# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SeverityAtLeast = Literal["info", "warning", "high", "critical"]

_SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 3}


def severity_rank(sev: str) -> int:
    return _SEVERITY_RANK.get(sev, 0)


class _ExpectedCountSpec(BaseModel):
    min_count: int = Field(default=1, ge=0)
    max_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _valid_count_range(self) -> Self:
        if self.max_count is not None and self.max_count < self.min_count:
            raise ValueError("max_count must be greater than or equal to min_count")
        return self


class ExpectedIncidentSpec(_ExpectedCountSpec):
    type: str
    rule_id: str | None = None
    object_ids_any_order: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    severity_at_least: SeverityAtLeast | None = None


class ExpectedEventSpec(_ExpectedCountSpec):
    event_type: str | None = None
    rule_id: str | None = None


class ExpectedReplaySpec(BaseModel):
    deterministic_hash_match: bool = True


class ExpectedLatencySpec(BaseModel):
    p95_update_ms_max: float | None = Field(
        default=None,
        ge=0.0,
        allow_inf_nan=False,
    )


class PhysicalRegressionExpected(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    incidents: list[ExpectedIncidentSpec] = Field(default_factory=list)
    events: list[ExpectedEventSpec] = Field(default_factory=list)
    replay: ExpectedReplaySpec = Field(default_factory=ExpectedReplaySpec)
    latency: ExpectedLatencySpec = Field(default_factory=ExpectedLatencySpec)


class PhysicalRegressionResult(BaseModel):
    bundle_path: str
    pass_: bool = Field(alias="pass")
    checks: list[dict[str, Any]] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    output_hash: str | None = None

    model_config = ConfigDict(populate_by_name=True)
