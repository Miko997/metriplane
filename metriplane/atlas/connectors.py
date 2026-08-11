# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
from pathlib import Path

from metriplane.atlas.models import ATLAS_LIMITATION_STATEMENTS


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_connectors(run_dir: str | Path, out_dir: str | Path | None = None) -> dict:
    run = Path(run_dir)
    out = Path(out_dir) if out_dir else run / "connectors"
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((run / "atlas_manifest.json").read_text(encoding="utf-8"))
    events = _jsonl(run / "physical_event_log.jsonl")
    incidents = _jsonl(run / "incidents.jsonl")
    actions = json.loads((run / "improvement_actions.json").read_text(encoding="utf-8")) if (run / "improvement_actions.json").exists() else []
    _write_csv(
        out / "events.csv",
        events,
        ["run_id", "event_id", "ts", "event_type", "severity", "asset_id", "zone_id", "station_id", "process_step_id", "message"],
    )
    _write_csv(
        out / "incidents.csv",
        incidents,
        ["incident_id", "incident_type", "severity", "title", "summary", "work_order_id"],
    )
    rest_snapshot = {
        "schema_version": "metriplane.atlas.read_only_rest_snapshot.v1",
        "endpoints": {
            "/manifest": manifest,
            "/events": events,
            "/incidents": incidents,
            "/improvement-actions": actions,
        },
        "limitations": [
            "Static snapshot for read-only integrations.",
            "Does not write to MES, ERP, PLC, or robot controllers.",
            *ATLAS_LIMITATION_STATEMENTS,
        ],
    }
    webhook_payload = {
        "schema_version": "metriplane.atlas.webhook_payload.v1",
        "event": "atlas.run.completed",
        "run_id": manifest.get("run_id"),
        "cell_id": manifest.get("cell_id"),
        "event_count": manifest.get("event_count", 0),
        "incident_count": manifest.get("incident_count", 0),
        "report": manifest.get("artifacts", {}).get("cell_truth_report_html"),
    }
    mqtt_topics = {
        "schema_version": "metriplane.atlas.mqtt_topic_plan.v1",
        "topics": [
            f"metriplane/atlas/{manifest.get('cell_id')}/{manifest.get('run_id')}/events",
            f"metriplane/atlas/{manifest.get('cell_id')}/{manifest.get('run_id')}/incidents",
        ],
        "status": "topic_plan_only",
    }
    (out / "rest_snapshot.json").write_text(json.dumps(rest_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "webhook_payload.json").write_text(json.dumps(webhook_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "mqtt_topics.json").write_text(json.dumps(mqtt_topics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "metriplane.atlas.connector_export.v1",
        "out_dir": str(out),
        "events_csv": str(out / "events.csv"),
        "incidents_csv": str(out / "incidents.csv"),
        "rest_snapshot": str(out / "rest_snapshot.json"),
        "webhook_payload": str(out / "webhook_payload.json"),
        "mqtt_topics": str(out / "mqtt_topics.json"),
    }
