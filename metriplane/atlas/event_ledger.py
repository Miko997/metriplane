# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.atlas.models import AtlasEvent


def write_events(path: str | Path, events: list[AtlasEvent]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as handle:
        for event in sorted(events, key=lambda item: (item.ts, item.event_id)):
            handle.write(json.dumps(event.model_dump(), sort_keys=True) + "\n")


def read_events(path: str | Path) -> list[AtlasEvent]:
    events: list[AtlasEvent] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(AtlasEvent.model_validate(json.loads(line)))
    return events


def query_events(
    events: list[AtlasEvent],
    asset_id: str | None = None,
    zone_id: str | None = None,
    station_id: str | None = None,
    process_step_id: str | None = None,
    event_type: str | None = None,
) -> list[AtlasEvent]:
    result = events
    if asset_id:
        result = [event for event in result if event.asset_id == asset_id]
    if zone_id:
        result = [event for event in result if event.zone_id == zone_id]
    if station_id:
        result = [event for event in result if event.station_id == station_id]
    if process_step_id:
        result = [event for event in result if event.process_step_id == process_step_id]
    if event_type:
        result = [event for event in result if event.event_type == event_type]
    return sorted(result, key=lambda item: (item.ts, item.event_id))
