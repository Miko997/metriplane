# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from metriplane.system.health import ComponentHealth, HealthStatus


_STATUS_RANK: dict[HealthStatus, int] = {
    HealthStatus.OK: 2,
    HealthStatus.DEGRADED: 1,
    HealthStatus.FAILED: 0,
}


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    enabled: bool
    overall: HealthStatus
    ts_ns: int
    uptime_s: float
    components: dict[str, ComponentHealth]

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "overall": self.overall.value,
            "ts_ns": int(self.ts_ns),
            "uptime_s": float(self.uptime_s),
            "components": {k: v.to_json() for k, v in self.components.items()},
        }


class HealthRegistry:
    """Thread-safe registry of component health.

    Tests expect:
      - set_ok / set_degraded / set_failed
      - snapshot().overall returning HealthStatus
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        now_ns: Callable[[], int] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self._now_ns: Callable[[], int] = now_ns or time.monotonic_ns
        self._lock = threading.Lock()
        self._started_ns = int(self._now_ns())
        self._components: dict[str, ComponentHealth] = {}

    def ensure(self, name: str) -> None:
        n = str(name)
        now = int(self._now_ns())
        with self._lock:
            if n not in self._components:
                ch = ComponentHealth(name=n)
                # Prime timestamps so /health doesn't show null forever.
                ch.status = HealthStatus.OK
                ch.last_ok_ts_ns = now
                self._components[n] = ch

    def _upsert(self, name: str, *, status: HealthStatus, err: str | None = None) -> None:
        n = str(name)
        now = int(self._now_ns())
        with self._lock:
            ch = self._components.get(n) or ComponentHealth(name=n)
            ch.status = status
            if status == HealthStatus.OK:
                ch.last_ok_ts_ns = now
            else:
                ch.last_error_ts_ns = now
                if err is not None:
                    ch.last_error = str(err)
            self._components[n] = ch

    # API expected by tests
    def set_ok(self, name: str) -> None:
        self._upsert(name, status=HealthStatus.OK)

    def set_degraded(self, name: str, err: str) -> None:
        self._upsert(name, status=HealthStatus.DEGRADED, err=str(err))

    def set_failed(self, name: str, err: str) -> None:
        self._upsert(name, status=HealthStatus.FAILED, err=str(err))

    # Backward-compatible aliases
    def mark_ok(self, name: str) -> None:
        self.set_ok(name)

    def mark_degraded(self, name: str, err: str) -> None:
        self.set_degraded(name, err)

    def mark_failed(self, name: str, err: str) -> None:
        self.set_failed(name, err)

    def overall(self) -> HealthStatus:
        with self._lock:
            comps = list(self._components.values())

        if not comps:
            return HealthStatus.OK

        worst_rank = min(_STATUS_RANK.get(c.status, 0) for c in comps)
        return {2: HealthStatus.OK, 1: HealthStatus.DEGRADED, 0: HealthStatus.FAILED}[worst_rank]

    def snapshot(self) -> HealthSnapshot:
        now = int(self._now_ns())
        with self._lock:
            comps = dict(self._components)

        return HealthSnapshot(
            enabled=self.enabled,
            overall=self.overall(),
            ts_ns=now,
            uptime_s=float(max(0, now - self._started_ns)) / 1e9,
            components=comps,
        )

    def snapshot_json(self) -> dict[str, Any]:
        return self.snapshot().to_json()


__all__ = ["HealthSnapshot", "HealthRegistry"]
