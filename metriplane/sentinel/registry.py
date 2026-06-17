# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ObjectEntry(BaseModel):
    object_id: str
    marker_id: int
    type: str
    display_name: str
    dimensions_m: list[float] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ObjectRegistryConfig(BaseModel):
    objects: list[ObjectEntry]

    def by_marker_id(self, marker_id: int) -> ObjectEntry | None:
        for obj in self.objects:
            if obj.marker_id == marker_id:
                return obj
        return None

    def by_object_id(self, object_id: str) -> ObjectEntry | None:
        for obj in self.objects:
            if obj.object_id == object_id:
                return obj
        return None

    def resolve_id(self, raw_marker_id: str) -> str:
        try:
            mid = int(raw_marker_id)
        except (ValueError, TypeError):
            return f"marker_{raw_marker_id}"
        entry = self.by_marker_id(mid)
        return entry.object_id if entry else f"marker_{raw_marker_id}"


def load_registry(path: str | Path) -> ObjectRegistryConfig:
    data = yaml.safe_load(Path(path).read_text())
    return ObjectRegistryConfig.model_validate(data)


def validate_registry(path: str | Path) -> list[str]:
    errors: list[str] = []
    try:
        cfg = load_registry(path)
    except Exception as e:
        return [str(e)]
    marker_ids: list[int] = []
    object_ids: list[str] = []
    for entry in cfg.objects:
        if entry.marker_id in marker_ids:
            errors.append(f"duplicate marker_id: {entry.marker_id}")
        marker_ids.append(entry.marker_id)
        if entry.object_id in object_ids:
            errors.append(f"duplicate object_id: {entry.object_id}")
        object_ids.append(entry.object_id)
    return errors
