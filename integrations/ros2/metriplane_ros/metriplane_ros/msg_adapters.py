"""Pure, ROS-free adapters that turn Metriplane WebSocket/JSONL frames into the JSON
payloads published on ROS 2 topics. Kept free of rclpy so they are unit-testable in CI
without a ROS 2 installation.
"""
from __future__ import annotations

import json
from typing import Any


def extract_frame_json(frame: dict[str, Any]) -> str:
    """Canonical JSON for the /metriplane/frame_state topic."""
    return json.dumps(frame, sort_keys=True, separators=(",", ":"))


def extract_alert_json_strings(frame: dict[str, Any]) -> list[str]:
    """One JSON string per alert in the frame (topic /metriplane/alerts).

    Accepts alerts under either `alerts` or, for Sentinel frames, inside
    `metrics.sentinel.alerts`. Returns [] when there are none.
    """
    alerts = frame.get("alerts")
    if not alerts:
        metrics = frame.get("metrics") or {}
        sentinel = metrics.get("sentinel") or {}
        alerts = sentinel.get("alerts")
    if not isinstance(alerts, list):
        return []
    return [json.dumps(a, sort_keys=True, separators=(",", ":")) for a in alerts]


def extract_incident_json_strings(frame: dict[str, Any]) -> list[str]:
    """One JSON string per incident in the frame (topic /metriplane/incidents)."""
    incidents = frame.get("incidents")
    if not isinstance(incidents, list):
        return []
    return [json.dumps(i, sort_keys=True, separators=(",", ":")) for i in incidents]


def extract_object_summary(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact per-object summary (id + world XY + zone) for downstream consumers."""
    objs = frame.get("fused") or frame.get("objects") or []
    out: list[dict[str, Any]] = []
    for o in objs:
        if not isinstance(o, dict):
            continue
        pos = o.get("pos_world")
        out.append({
            "id": str(o.get("id")),
            "x": pos[0] if isinstance(pos, (list, tuple)) and len(pos) >= 2 else None,
            "y": pos[1] if isinstance(pos, (list, tuple)) and len(pos) >= 2 else None,
            "zone": o.get("zone"),
        })
    return out
