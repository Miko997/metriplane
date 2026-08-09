# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RuleType = Literal[
    "forbidden_zone",
    "max_dwell",
    "min_distance",
    "speed_limit",
    "missing_object",
    "restricted_transition",
]

SeverityLevel = Literal["info", "warning", "critical"]


class ObjectFilter(BaseModel):
    type: str | None = None
    object_id: str | None = None
    tags: list[str] = Field(default_factory=list)

    def matches(
        self,
        obj_type: str | None = None,
        obj_id: str | None = None,
        obj_tags: list[str] | None = None,
    ) -> bool:
        if self.type is not None and obj_type != self.type:
            return False
        if self.object_id is not None and obj_id != self.object_id:
            return False
        if self.tags and obj_tags is not None:
            if not all(t in obj_tags for t in self.tags):
                return False
        return True


class RuleDefinition(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    id: str
    type: RuleType
    severity: SeverityLevel = "warning"
    object_filter: ObjectFilter | None = None
    object_filter_a: ObjectFilter | None = None
    object_filter_b: ObjectFilter | None = None
    zone: str | None = None
    max_duration_s: float | None = Field(default=None, ge=0.0)
    min_distance_m: float | None = Field(default=None, ge=0.0)
    max_speed_mps: float | None = Field(default=None, ge=0.0)
    from_zone: str | None = None
    to_zone: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _required_condition_fields(self):
        if not self.id.strip():
            raise ValueError("rule id must not be empty")
        required: dict[RuleType, tuple[str, ...]] = {
            "forbidden_zone": ("zone",),
            "max_dwell": ("zone", "max_duration_s"),
            "min_distance": ("min_distance_m",),
            "speed_limit": ("max_speed_mps",),
            "missing_object": ("max_duration_s",),
            "restricted_transition": ("from_zone", "to_zone"),
        }
        missing = [name for name in required[self.type] if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"{self.type} rule requires: {', '.join(missing)}"
            )
        return self


class RuleSet(BaseModel):
    rules: list[RuleDefinition]


def load_rules(path: Any) -> RuleSet:
    import yaml
    from pathlib import Path
    data = yaml.safe_load(Path(path).read_text())
    return RuleSet.model_validate(data)


def validate_rules(path: Any) -> list[str]:
    errors: list[str] = []
    try:
        rs = load_rules(path)
    except Exception as e:
        return [str(e)]
    seen: set[str] = set()
    for r in rs.rules:
        if r.id in seen:
            errors.append(f"duplicate rule id: {r.id}")
        seen.add(r.id)
    return errors
