# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


def _coerce_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


@dataclass(slots=True)
class FaultInjector:
    """Deterministic, test-friendly fault injection.

    Faults are provided as a mapping (often strings from config/CLI/env).

    Example:
        fi = FaultInjector(now_ns=time.time_ns, faults={"cam1_disconnect_after_s": "8"})
        if fi.should_fire_after_s("cam1_disconnect_after_s"):
            ... apply the fault exactly once ...
    """

    now_ns: Callable[[], int]
    faults: Mapping[str, Any] = field(default_factory=dict)

    # Slots-safe internal state
    _t0_ns: int = field(init=False, repr=False)
    _fired: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self._t0_ns = int(self.now_ns())

    def elapsed_ns(self) -> int:
        return max(0, int(self.now_ns()) - int(self._t0_ns))

    def elapsed_s(self) -> float:
        return float(self.elapsed_ns()) / 1e9

    def get(self, key: str, default: Any = None) -> Any:
        return self.faults.get(str(key), default)

    def seconds(self, key: str, default: float | None = None) -> float | None:
        return _coerce_float(self.get(key), default)

    def fire_once_after_s(self, key: str) -> bool:
        """Return True exactly once after elapsed_s() >= configured seconds."""
        k = str(key)
        if k in self._fired:
            return False

        after_s = self.seconds(k)
        if after_s is None:
            return False

        if self.elapsed_s() >= float(after_s):
            self._fired.add(k)
            return True

        return False

    # --- Aliases expected by tests / older call sites ---
    should_fire_after_s = fire_once_after_s
    fire_once = fire_once_after_s
    should_fire_once = fire_once_after_s
    check = fire_once_after_s
