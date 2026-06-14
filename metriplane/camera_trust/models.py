# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CameraTrustScoreModel(BaseModel):
    camera_id: str
    score: float
    status: Literal["OK", "DEGRADED", "FAILED"]
    frames_seen: int = 0
    detections_total: int = 0
    dropout_rate: float | None = None
    mean_disagreement_m: float | None = None
    p95_disagreement_m: float | None = None
    mean_confidence: float | None = None
    notes: list[str] = Field(default_factory=list)


class ZoneCoverageScoreModel(BaseModel):
    zone: str
    score: float
    frames_with_objects: int = 0
    camera_observation_counts: dict[str, int] = Field(default_factory=dict)
    weak_cameras: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CameraTrustReportModel(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str | None = None
    frames_analyzed: int = 0
    camera_scores: dict[str, CameraTrustScoreModel] = Field(default_factory=dict)
    zone_scores: dict[str, ZoneCoverageScoreModel] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
