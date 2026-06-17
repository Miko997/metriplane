# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _manifests(root: Path) -> list[Path]:
    return sorted(root.rglob("atlas_manifest.json"))


def build_lake(root: str | Path, db_path: str | Path) -> dict:
    root_path = Path(root)
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            drop table if exists runs;
            drop table if exists events;
            drop table if exists incidents;
            create table runs (
              run_key text primary key,
              run_id text,
              cell_id text,
              run_dir text,
              frame_count integer,
              event_count integer,
              incident_count integer
            );
            create table events (
              run_id text,
              event_id text,
              ts real,
              event_type text,
              severity text,
              asset_id text,
              zone_id text,
              station_id text,
              process_step_id text,
              message text
            );
            create table incidents (
              run_id text,
              incident_id text,
              incident_type text,
              severity text,
              title text,
              summary text
            );
            """
        )
        run_count = event_count = incident_count = 0
        for manifest_path in _manifests(root_path):
            run_dir = manifest_path.parent
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            conn.execute(
                "insert into runs values (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(run_dir),
                    manifest.get("run_id"),
                    manifest.get("cell_id"),
                    str(run_dir),
                    manifest.get("frame_count", 0),
                    manifest.get("event_count", 0),
                    manifest.get("incident_count", 0),
                ),
            )
            run_count += 1
            for event in _jsonl(run_dir / "physical_event_log.jsonl"):
                conn.execute(
                    "insert into events values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.get("run_id"),
                        event.get("event_id"),
                        event.get("ts"),
                        event.get("event_type"),
                        event.get("severity"),
                        event.get("asset_id"),
                        event.get("zone_id"),
                        event.get("station_id"),
                        event.get("process_step_id"),
                        event.get("message"),
                    ),
                )
                event_count += 1
            for incident in _jsonl(run_dir / "incidents.jsonl"):
                conn.execute(
                    "insert into incidents values (?, ?, ?, ?, ?, ?)",
                    (
                        manifest.get("run_id"),
                        incident.get("incident_id"),
                        incident.get("incident_type"),
                        incident.get("severity"),
                        incident.get("title"),
                        incident.get("summary"),
                    ),
                )
                incident_count += 1
    return {
        "schema_version": "metriplane.atlas.evidence_lake_build.v1",
        "root": str(root_path),
        "db_path": str(db),
        "run_count": run_count,
        "event_count": event_count,
        "incident_count": incident_count,
    }


def lake_query(db_path: str | Path, table: str = "events", asset_id: str | None = None, event_type: str | None = None, cell_id: str | None = None) -> list[dict]:
    if table not in {"runs", "events", "incidents"}:
        raise ValueError(f"unsupported table: {table}")
    clauses: list[str] = []
    values: list[str] = []
    if table == "events":
        if asset_id:
            clauses.append("asset_id = ?")
            values.append(asset_id)
        if event_type:
            clauses.append("event_type = ?")
            values.append(event_type)
        sql = "select * from events"
    elif table == "runs":
        if cell_id:
            clauses.append("cell_id = ?")
            values.append(cell_id)
        sql = "select * from runs"
    else:
        sql = "select * from incidents"
    if clauses:
        sql += " where " + " and ".join(clauses)
    sql += " order by 1, 2"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, values).fetchall()]


def trend_summary(db_path: str | Path, out_path: str | Path | None = None) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        by_cell = [dict(row) for row in conn.execute(
            "select cell_id, count(*) as runs, sum(event_count) as events, sum(incident_count) as incidents from runs group by cell_id order by cell_id"
        )]
        by_event_type = [dict(row) for row in conn.execute(
            "select event_type, count(*) as count from events group by event_type order by event_type"
        )]
        by_incident_type = [dict(row) for row in conn.execute(
            "select incident_type, count(*) as count from incidents group by incident_type order by incident_type"
        )]
    result = {
        "schema_version": "metriplane.atlas.trend_summary.v1",
        "db_path": str(db_path),
        "by_cell": by_cell,
        "by_event_type": by_event_type,
        "by_incident_type": by_incident_type,
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
