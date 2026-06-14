# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SentinelModeStatus(BaseModel):
    mode: Literal["disabled", "shadow_auditor"] = "disabled"
    control_enabled: bool = False
    run_id: str | None = None
    contract_id: str | None = None
    objects_tracked: int = 0
    active_alerts: int = 0
    open_incidents: int = 0
    closed_incidents: int = 0
    risk_forecasts_enabled: bool = False
    last_event_ts: float | None = None
    health: str = "OK"
    details: dict[str, Any] = Field(default_factory=dict)
