# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import uuid
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SeverityLevel = Literal["info", "warning", "critical"]


class RuleAlert(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    rule_id: str
    severity: SeverityLevel
    ts: float
    object_ids: list[str]
    zone: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


class IncidentRecord(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    incident_id: str = Field(default_factory=lambda: f"inc_{str(uuid.uuid4())[:6]}")
    run_id: str | None = None
    rule_id: str
    severity: SeverityLevel
    status: Literal["open", "closed"] = "open"
    opened_ts: float
    closed_ts: float | None = None
    duration_s: float | None = None
    object_ids: list[str]
    zones: list[str]
    summary: str
    alert_ids: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_timing(self) -> Self:
        if self.closed_ts is not None and self.closed_ts < self.opened_ts:
            raise ValueError("closed_ts must be greater than or equal to opened_ts")
        if self.duration_s is not None and self.duration_s < 0:
            raise ValueError("duration_s must be non-negative")
        return self

    def close(self, closed_ts: float) -> None:
        if closed_ts < self.opened_ts:
            raise ValueError("closed_ts must be greater than or equal to opened_ts")
        self.status = "closed"
        self.closed_ts = closed_ts
        self.duration_s = round(closed_ts - self.opened_ts, 3)


class OperationalEvent(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    event_type: Literal["alert", "incident_open", "incident_close", "zone_enter", "zone_exit"]
    ts: float
    run_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_alert(cls, alert: RuleAlert) -> "OperationalEvent":
        return cls(event_type="alert", ts=alert.ts, run_id=alert.run_id, payload=alert.model_dump())

    @classmethod
    def from_incident_open(cls, inc: IncidentRecord) -> "OperationalEvent":
        return cls(
            event_type="incident_open",
            ts=inc.opened_ts,
            run_id=inc.run_id,
            payload=inc.model_dump(),
        )

    @classmethod
    def from_incident_close(cls, inc: IncidentRecord) -> "OperationalEvent":
        assert inc.closed_ts is not None
        return cls(
            event_type="incident_close",
            ts=inc.closed_ts,
            run_id=inc.run_id,
            payload=inc.model_dump(),
        )


def write_alerts_jsonl(alerts: list[RuleAlert], path: Any) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for a in alerts:
            f.write(a.model_dump_json() + "\n")


def read_alerts_jsonl(path: Any) -> list[RuleAlert]:
    from pathlib import Path

    result = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            result.append(RuleAlert.model_validate_json(line))
    return result


def write_incidents_json(incidents: list[IncidentRecord], path: Any) -> None:
    import json
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([inc.model_dump() for inc in incidents], indent=2))


def read_incidents_json(path: Any) -> list[IncidentRecord]:
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text())
    return [IncidentRecord.model_validate(d) for d in data]
