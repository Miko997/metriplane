# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_VALID_MODES = {"shadow_auditor"}


@dataclass(frozen=True)
class SentinelConfig:
    enabled: bool = False
    mode: str = "shadow_auditor"
    contracts_file: str | None = None
    objects_file: str | None = None
    zones_file: str | None = None
    export_summary: bool = True
    api_enabled: bool = True
    include_alerts_in_frame_metrics: bool = True
    fail_fast_on_contract_error: bool = True
    forecasting: dict[str, Any] | None = None
    fleet: dict[str, Any] | None = None
    camera_trust: dict[str, Any] | None = None

    # Control is intentionally absent. Sentinel is observe-only in v1.
    @property
    def control_enabled(self) -> bool:
        return False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SentinelConfig":
        if not data:
            return cls(enabled=False)
        mode = str(data.get("mode", "shadow_auditor"))
        if mode not in _VALID_MODES:
            raise ValueError(f"invalid sentinel mode: {mode!r} (allowed: {_VALID_MODES})")
        if data.get("control_enabled", False):
            raise ValueError("sentinel control_enabled cannot be true in v1 (observe-only)")
        return cls(
            enabled=bool(data.get("enabled", False)),
            mode=mode,
            contracts_file=data.get("contracts_file"),
            objects_file=data.get("objects_file"),
            zones_file=data.get("zones_file"),
            export_summary=bool(data.get("export_summary", True)),
            api_enabled=bool(data.get("api_enabled", True)),
            include_alerts_in_frame_metrics=bool(data.get("include_alerts_in_frame_metrics", True)),
            fail_fast_on_contract_error=bool(data.get("fail_fast_on_contract_error", True)),
            forecasting=data.get("forecasting"),
            fleet=data.get("fleet"),
            camera_trust=data.get("camera_trust"),
        )
