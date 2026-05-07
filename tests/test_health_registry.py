from __future__ import annotations

from metriplane.system.health import HealthStatus
from metriplane.system.health_registry import HealthRegistry


class FakeClock:
    def __init__(self) -> None:
        self.t = 0

    def now_ns(self) -> int:
        self.t += 10
        return self.t


def test_overall_ok() -> None:
    clk = FakeClock()
    hr = HealthRegistry(now_ns=clk.now_ns)
    hr.set_ok("camera.cam0")
    hr.set_ok("ws")
    snap = hr.snapshot()
    assert snap.overall == HealthStatus.OK


def test_overall_degraded_and_failed() -> None:
    clk = FakeClock()
    hr = HealthRegistry(now_ns=clk.now_ns)
    hr.set_ok("camera.cam0")
    hr.set_degraded("fusion", "cam1 missing")
    assert hr.snapshot().overall == HealthStatus.DEGRADED
    hr.set_failed("camera.cam1", "disconnect")
    assert hr.snapshot().overall == HealthStatus.FAILED
