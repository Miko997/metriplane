# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ObjectState:
    id: str
    pos_world: tuple[float, float, float] | None = None
    zone: str | None = None
    confidence: float | None = None
    extra: dict[str, Any] | None = None


@dataclass(frozen=True)
class ZoneEvent:
    type: Literal["zone_enter", "zone_exit"]
    object_id: str
    zone: str
    ts: float


@dataclass(frozen=True)
class FrameState:
    schema_version: str
    source_backend: str
    ts: float
    frame_id: int
    objects: list[ObjectState]
    events: list[ZoneEvent]
    metrics: dict[str, Any] | None = None
