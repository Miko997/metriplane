# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.system.fault_injection import FaultInjector


class FakeClock:
    def __init__(self) -> None:
        self.t = 0

    def now_ns(self) -> int:
        return self.t

    def advance_s(self, s: float) -> None:
        self.t += int(s * 1e9)


def test_fault_fires_once() -> None:
    clk = FakeClock()
    fi = FaultInjector(now_ns=clk.now_ns, faults={"cam1_disconnect_after_s": "1.0"})

    assert fi.should_fire_after_s("cam1_disconnect_after_s") is False
    clk.advance_s(1.1)
    assert fi.should_fire_after_s("cam1_disconnect_after_s") is True
    assert fi.should_fire_after_s("cam1_disconnect_after_s") is False
