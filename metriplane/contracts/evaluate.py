# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.contracts.engine import ContractEvent, SpatialContractEngine
from metriplane.contracts.models import SpatialContractPackage
from metriplane.sentinel.engine import iter_frames
from metriplane.sentinel.registry import ObjectRegistryConfig


def evaluate_contract_session(
    session_path: str | Path,
    package: SpatialContractPackage,
    registry: ObjectRegistryConfig | None = None,
) -> tuple[list[ContractEvent], str | None]:
    """Run a contract package over a session JSONL. Returns (events, run_id)."""
    engine = SpatialContractEngine(package, registry)
    events: list[ContractEvent] = []
    for frame in iter_frames(session_path):
        if frame.run_id and not engine.run_id:
            engine.run_id = frame.run_id
        observed = frame.fused if frame.fused else frame.objects
        events.extend(engine.update(frame.ts, observed))
    return events, engine.run_id
