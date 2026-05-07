from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class HealthStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus = HealthStatus.OK
    last_ok_ts_ns: Optional[int] = None
    last_error_ts_ns: Optional[int] = None
    last_error: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "last_ok_ts_ns": self.last_ok_ts_ns,
            "last_error_ts_ns": self.last_error_ts_ns,
            "last_error": self.last_error,
        }
