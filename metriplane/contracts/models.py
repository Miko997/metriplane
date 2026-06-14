# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Severity = Literal["info", "warning", "high", "critical"]

RuleType = Literal[
    "forbidden_zone",
    "minimum_distance",
    "zone_occupancy_duration",
    "missing_object",
    "speed_limit",
    "forbidden_direction",
    "zone_capacity",
]

Direction = Literal["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"]


class SubjectSpec(BaseModel):
    """A named group of objects, matched by id, type, tags, or current zone."""
    object_ids: list[str] = Field(default_factory=list)
    object_types: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)


class ContractRuleSpec(BaseModel):
    id: str
    type: RuleType
    enabled: bool = True
    severity: Severity = "warning"
    cooldown_s: float = 0.0

    subject: str | None = None
    subject_a: str | None = None
    subject_b: str | None = None

    zones: list[str] = Field(default_factory=list)
    distance_m: float | None = None
    min_duration_s: float | None = None
    max_duration_s: float | None = None
    max_count: int | None = None
    max_speed_mps: float | None = None
    min_speed_mps: float | None = None
    missing_after_s: float | None = None
    allowed_direction: Direction | None = None

    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_required_fields(self) -> "ContractRuleSpec":
        if self.cooldown_s < 0:
            raise ValueError(f"rule {self.id}: cooldown_s must be >= 0")
        if self.type == "forbidden_zone":
            if not self.subject or not self.zones:
                raise ValueError(f"rule {self.id}: forbidden_zone requires subject and zones")
        elif self.type == "minimum_distance":
            if not self.subject_a or not self.subject_b:
                raise ValueError(f"rule {self.id}: minimum_distance requires subject_a and subject_b")
            if self.distance_m is None or self.distance_m < 0:
                raise ValueError(f"rule {self.id}: minimum_distance requires non-negative distance_m")
        elif self.type == "zone_occupancy_duration":
            if not self.subject or not self.zones:
                raise ValueError(f"rule {self.id}: zone_occupancy_duration requires subject and zones")
            if self.max_duration_s is None or self.max_duration_s < 0:
                raise ValueError(f"rule {self.id}: zone_occupancy_duration requires non-negative max_duration_s")
        elif self.type == "speed_limit":
            if not self.subject or self.max_speed_mps is None:
                raise ValueError(f"rule {self.id}: speed_limit requires subject and max_speed_mps")
        elif self.type == "missing_object":
            if not self.subject or self.missing_after_s is None:
                raise ValueError(f"rule {self.id}: missing_object requires subject and missing_after_s")
        elif self.type == "forbidden_direction":
            if not self.subject or not self.zones or self.allowed_direction is None:
                raise ValueError(f"rule {self.id}: forbidden_direction requires subject, zones, allowed_direction")
        elif self.type == "zone_capacity":
            if not self.subject or not self.zones or self.max_count is None:
                raise ValueError(f"rule {self.id}: zone_capacity requires subject, zones, max_count")
        return self


class SpatialContractPackage(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    name: str | None = None
    units: str = "meters"
    subjects: dict[str, SubjectSpec] = Field(default_factory=dict)
    rules: list[ContractRuleSpec]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_unique_rule_ids(self) -> "SpatialContractPackage":
        seen: set[str] = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id}")
            seen.add(r.id)
        # subject references must resolve
        for r in self.rules:
            for ref in (r.subject, r.subject_a, r.subject_b):
                if ref is not None and ref not in self.subjects:
                    raise ValueError(f"rule {r.id}: unknown subject '{ref}'")
        return self
