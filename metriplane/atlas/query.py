# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import yaml

from metriplane.atlas.event_ledger import query_events, read_events


def query_run_events(
    run_dir: str | Path,
    asset_id: str | None = None,
    zone_id: str | None = None,
    station_id: str | None = None,
    process_step_id: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    events = read_events(Path(run_dir) / "physical_event_log.jsonl")
    return [
        event.model_dump()
        for event in query_events(events, asset_id, zone_id, station_id, process_step_id, event_type)
    ]


def index_runs(root: str | Path) -> dict:
    root_path = Path(root)
    runs = []
    for manifest_path in sorted(root_path.rglob("atlas_manifest.json")):
        data = json.loads(manifest_path.read_text())
        runs.append({
            "run_id": data.get("run_id"),
            "cell_id": data.get("cell_id"),
            "run_dir": str(manifest_path.parent),
            "event_count": data.get("event_count", 0),
            "incident_count": data.get("incident_count", 0),
        })
    return {
        "schema_version": "metriplane.atlas.evidence_lake_index.v1",
        "root": str(root_path),
        "runs": runs,
    }


def run_saved_query(run_dir: str | Path, query_file: str | Path, query_id: str) -> list[dict]:
    data = yaml.safe_load(Path(query_file).read_text(encoding="utf-8")) or {}
    queries = data.get("queries", [])
    query = next((item for item in queries if item.get("query_id") == query_id), None)
    if query is None:
        raise ValueError(f"saved query not found: {query_id}")
    filters = query.get("filters") or {}
    return query_run_events(
        run_dir,
        asset_id=filters.get("asset_id"),
        zone_id=filters.get("zone_id"),
        station_id=filters.get("station_id"),
        process_step_id=filters.get("process_step_id"),
        event_type=filters.get("event_type"),
    )


def explain_query(query_file: str | Path) -> dict:
    data = yaml.safe_load(Path(query_file).read_text(encoding="utf-8")) or {}
    return {
        "schema_version": "metriplane.atlas.saved_queries.v1",
        "query_file": str(query_file),
        "queries": [
            {
                "query_id": item.get("query_id"),
                "label": item.get("label"),
                "filters": item.get("filters", {}),
            }
            for item in data.get("queries", [])
        ],
    }
