# metriplane/time/clock.py
from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod
import time


def ms_to_ns(ms: int) -> int:
    if ms <= 0:
        raise ValueError(f"dt_ms must be > 0, got {ms}")
    return ms * 1_000_000


class Clock(ABC):
    """Authoritative time source for Metriplane.

    Requirement: core logic should not call time.time() directly; use Clock.now_ns()
    and propagate ts_sim_ns into outputs.  :contentReference[oaicite:2]{index=2}
    """

    @abstractmethod
    def now_ns(self) -> int:
        """Return the current simulation timestamp in ns."""

    def advance_to_ns(self, ts_ns: int) -> None:
        """Advance clock state to the given timestamp (used by replay clocks)."""
        raise NotImplementedError

    def tick(self) -> int:
        """Advance by one tick and return the new timestamp (used by fixed-step clocks)."""
        return self.now_ns()


@dataclass
class RealTimeClock(Clock):
    """Wall-clock-ish monotonic time (ns). Good for live runs."""
    def now_ns(self) -> int:
        return time.monotonic_ns()

    def advance_to_ns(self, ts_ns: int) -> None:
        # Real-time clock does not support explicit advance.
        return

    def tick(self) -> int:
        return self.now_ns()


@dataclass
class ReplayClock(Clock):
    """Replay clock: caller sets time to recorded timestamps."""
    current_ns: int = 0

    def now_ns(self) -> int:
        return int(self.current_ns)

    def advance_to_ns(self, ts_ns: int) -> None:
        self.current_ns = int(ts_ns)

    def tick(self) -> int:
        # ReplayClock doesn't increment on its own; it's externally driven.
        return self.now_ns()


@dataclass
class FixedStepClock(Clock):
    """Fixed-step simulation clock: deterministic ticks."""
    dt_ns: int
    current_ns: int = 0

    def now_ns(self) -> int:
        return int(self.current_ns)

    def advance_to_ns(self, ts_ns: int) -> None:
        self.current_ns = int(ts_ns)

    def tick(self) -> int:
        self.current_ns = int(self.current_ns) + int(self.dt_ns)
        return int(self.current_ns)
