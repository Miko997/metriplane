from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
    id: str
    type: RuleType
    severity: SeverityLevel = "warning"
    object_filter: ObjectFilter | None = None
    object_filter_a: ObjectFilter | None = None
    object_filter_b: ObjectFilter | None = None
    zone: str | None = None
    max_duration_s: float | None = None
    min_distance_m: float | None = None
    max_speed_mps: float | None = None
    from_zone: str | None = None
    to_zone: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


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
