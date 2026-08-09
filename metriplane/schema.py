# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_json_extension(value: Any, *, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, (list, tuple)):
        return [
            _validate_json_extension(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        validated: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            validated[key] = _validate_json_extension(item, path=f"{path}.{key}")
        return validated
    raise ValueError(f"{path} contains a non-JSON value: {type(value).__name__}")


class ObjectStateModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    id: str
    pos_world: tuple[float, float, float] | None = None
    vel_world: tuple[float, float, float] | None = None  # NEW (Kalman optional)
    zone: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extra: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _nonempty_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("object id must not be empty")
        return value

    @field_validator("extra", mode="before")
    @classmethod
    def _valid_extra(cls, value: Any) -> Any:
        return _validate_json_extension(value, path="extra")


class ZoneEventModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    type: Literal["zone_enter", "zone_exit"]
    object_id: str
    zone: str
    ts: float


class CameraFrameModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    camera_id: str
    ts_cam_read: float
    objects: list[ObjectStateModel]
    metrics: dict[str, Any] | None = None

    @field_validator("metrics", mode="before")
    @classmethod
    def _valid_metrics(cls, value: Any) -> Any:
        return _validate_json_extension(value, path="metrics")

    @model_validator(mode="after")
    def _unique_object_ids(self):
        ids = [obj.id for obj in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError(f"camera {self.camera_id!r} contains duplicate object ids")
        if not self.camera_id.strip():
            raise ValueError("camera id must not be empty")
        return self


class FrameStateModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    schema_version: Literal["1.0"] = Field(default="1.0")

    # M9.4 provenance (optional, but filled for runs)
    run_id: str | None = None
    config_hash: str | None = None
    git_commit: str | None = None

    ts_sim_ns: int | None = Field(default=None, strict=True, ge=0)

    source_backend: str
    ts: float
    frame_id: int = Field(strict=True, ge=0)

    # Backward compatible: Omniverse + ROS2 already consume this
    objects: list[ObjectStateModel]

    # NEW
    fused: list[ObjectStateModel] | None = None
    raw_per_camera: list[CameraFrameModel] | None = None

    events: list[ZoneEventModel] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None

    @field_validator("metrics", mode="before")
    @classmethod
    def _valid_metrics(cls, value: Any) -> Any:
        return _validate_json_extension(value, path="metrics")

    @model_validator(mode="after")
    def _unique_frame_identities(self):
        for name, objects in (("objects", self.objects), ("fused", self.fused)):
            if objects is None:
                continue
            ids = [obj.id for obj in objects]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} contains duplicate object ids")
        if self.raw_per_camera is not None:
            camera_ids = [camera.camera_id for camera in self.raw_per_camera]
            if len(camera_ids) != len(set(camera_ids)):
                raise ValueError("raw_per_camera contains duplicate camera ids")
        return self


def frame_time_s(frame: FrameStateModel) -> float:
    """Return the authoritative frame time in seconds.

    Fixed-clock replays set ``ts_sim_ns``; source-clock records use ``ts``.
    Frame validation guarantees both representations are finite and
    non-negative where present.
    """
    if frame.ts_sim_ns is not None:
        return frame.ts_sim_ns / 1_000_000_000.0
    return frame.ts
