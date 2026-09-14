# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FleetHeartbeat:
    node_id: str
    ts: float
    run_id: str | None
    git_commit: str | None
    config_hash: str | None
    health_overall: str
    fps: float | None
    objects_tracked: int | None
    active_incidents: int | None
    frames_total: int | None
    frames_dropped_total: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))
