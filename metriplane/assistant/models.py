# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

IntentType = Literal[
    "incident_search",
    "object_history",
    "zone_occupancy",
    "rule_explanation",
    "camera_health",
    "run_comparison",
    "unknown",
]


class AssistantQuery(BaseModel):
    question: str
    run_dir: str | None = None
    bundle_path: str | None = None
    intent: IntentType = "unknown"
    filters: dict[str, Any] = Field(default_factory=dict)


class CitationModel(BaseModel):
    source_path: str
    source_type: str
    record_id: str | None = None
    line_number: int | None = None
    field: str | None = None


class AssistantAnswer(BaseModel):
    question: str
    intent: IntentType
    answer: str
    citations: list[CitationModel] = Field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = Field(default_factory=list)


class SummaryProvider(Protocol):
    def summarize(self, *, question: str, facts: list[dict[str, Any]]) -> str: ...
