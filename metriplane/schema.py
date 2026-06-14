# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ObjectStateModel(BaseModel):
    id: str
    pos_world: tuple[float, float, float] | None = None
    vel_world: tuple[float, float, float] | None = None  # NEW (Kalman optional)
    zone: str | None = None
    confidence: float | None = None
    extra: dict[str, Any] | None = None


class ZoneEventModel(BaseModel):
    type: Literal["zone_enter", "zone_exit"]
    object_id: str
    zone: str
    ts: float


class CameraFrameModel(BaseModel):
    camera_id: str
    ts_cam_read: float
    objects: list[ObjectStateModel]
    metrics: dict[str, Any] | None = None


class FrameStateModel(BaseModel):
    schema_version: Literal["1.0"] = Field(default="1.0")

    # M9.4 provenance (optional, but filled for runs)
    run_id: str | None = None
    config_hash: str | None = None
    git_commit: str | None = None

    ts_sim_ns: int | None = None

    source_backend: str
    ts: float
    frame_id: int

    # Backward compatible: Omniverse + ROS2 already consume this
    objects: list[ObjectStateModel]

    # NEW
    fused: list[ObjectStateModel] | None = None
    raw_per_camera: list[CameraFrameModel] | None = None

    events: list[ZoneEventModel] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
