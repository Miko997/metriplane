# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Read-only Command Center data readers.

Pure functions that read a run directory or incident bundle and return JSON-serializable
dicts for the command center dashboard. Missing artifacts degrade to empty lists/objects
rather than raising, so the dashboard never 500s.

A "run dir" may be:
  - an incident evidence bundle (session_excerpt.jsonl, incident.json, objects.yaml, ...)
  - any run dir containing session.jsonl (+ optional incident/alerts artifacts)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from metriplane.runner.safe_reads import (
    PinnedDirectory,
    PinnedFile,
    UnsafeReadPathError,
    pin_file,
)

RunSource = str | Path | PinnedDirectory
RunArtifact = PinnedFile


def _run_source(run_dir: RunSource) -> Path | PinnedDirectory:
    return run_dir if isinstance(run_dir, PinnedDirectory) else Path(run_dir)


def find_run_artifact(
    run_dir: Path | PinnedDirectory,
    names: list[str] | tuple[str, ...],
) -> RunArtifact | None:
    """Return a pinned regular artifact from a selected run.

    Results acquired from a path own their directory authority and must be closed.
    Results acquired from a ``PinnedDirectory`` remain owned by that directory.
    """
    if isinstance(run_dir, PinnedDirectory):
        return run_dir.find_file(names)
    root = Path(run_dir)
    for name in names:
        try:
            return pin_file([root], root / name)
        except (OSError, UnsafeReadPathError):
            continue
    return None


def _release_artifact(artifact: RunArtifact | None) -> None:
    if artifact is not None and artifact.owns_authority:
        artifact.close()


def _session(run_dir: Path | PinnedDirectory) -> RunArtifact | None:
    return find_run_artifact(run_dir, ["session_excerpt.jsonl", "session.jsonl",
                                       "traces/object_traces.jsonl"])


def _objects_yaml(run_dir: Path | PinnedDirectory) -> RunArtifact | None:
    return find_run_artifact(run_dir, ["objects.yaml", "object_registry.yaml"])


def _workspace_yaml(run_dir: Path | PinnedDirectory) -> RunArtifact | None:
    return find_run_artifact(
        run_dir,
        ["workspace.yaml", "zones.yaml", "configs/workspace.yaml", "configs/zones.yaml"],
    )


def _registry(run_dir: Path | PinnedDirectory) -> Any:
    p = _objects_yaml(run_dir)
    if p is None:
        return None
    try:
        from metriplane.sentinel.registry import ObjectRegistryConfig

        return ObjectRegistryConfig.model_validate(yaml.safe_load(p.read_text()))
    except Exception:
        return None
    finally:
        _release_artifact(p)


def get_workspace(run_dir: RunSource) -> dict[str, Any]:
    run = _run_source(run_dir)
    path = _workspace_yaml(run)
    if path is None:
        return {"zones": [], "stations": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {"zones": [], "stations": []}
    finally:
        _release_artifact(path)

    zones = []
    for item in data.get("zones", []) or []:
        zone_id = item.get("zone_id") or item.get("name") or item.get("id")
        polygon = item.get("polygon") or []
        if not zone_id or not polygon:
            continue
        zones.append({
            "zone_id": zone_id,
            "label": item.get("label") or zone_id,
            "zone_type": item.get("zone_type") or item.get("type") or "zone",
            "polygon": polygon,
        })

    stations = []
    for item in data.get("stations", []) or []:
        station_id = item.get("station_id") or item.get("id")
        if not station_id:
            continue
        stations.append({
            "station_id": station_id,
            "zone_id": item.get("zone_id"),
            "label": item.get("label") or station_id,
        })

    return {
        "zones": zones,
        "stations": stations,
        "source": str(path),
        "cell_id": data.get("cell_id"),
        "units": data.get("units", "meters"),
    }


def get_objects(run_dir: RunSource) -> list[dict[str, Any]]:
    """Latest object states from the last frame of the session."""
    run = _run_source(run_dir)
    session = _session(run)
    if session is None:
        return []
    try:
        from metriplane.sentinel.engine import iter_frames_text

        frames = list(iter_frames_text(session.read_text(), source=str(session)))
    except Exception:
        return []
    finally:
        _release_artifact(session)
    if not frames:
        return []
    registry = _registry(run)
    last = frames[-1]
    observed = last.fused if last.fused is not None else last.objects
    out = []
    for o in observed:
        oid, otype = f"marker_{o.id}", "unknown"
        if registry is not None:
            try:
                entry = registry.by_marker_id(int(o.id))
                if entry is not None:
                    oid, otype = entry.object_id, entry.type
            except (TypeError, ValueError):
                pass
        speed = None
        if o.vel_world:
            speed = round((o.vel_world[0] ** 2 + o.vel_world[1] ** 2) ** 0.5, 3)
        out.append({
            "object_id": oid,
            "marker_id": str(o.id),
            "type": otype,
            "zone": o.zone,
            "x_m": o.pos_world[0] if o.pos_world else None,
            "y_m": o.pos_world[1] if o.pos_world else None,
            "speed_mps": speed,
            "last_ts": last.ts,
        })
    return out


def get_incidents(run_dir: RunSource) -> list[dict[str, Any]]:
    run = _run_source(run_dir)
    p = find_run_artifact(run, ["incident.json", "incidents/incidents.json", "incidents.json"])
    if p is None:
        return []
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, list) else [data]
    except Exception:
        return []
    finally:
        _release_artifact(p)


def get_events(run_dir: RunSource) -> list[dict[str, Any]]:
    run = _run_source(run_dir)
    p = find_run_artifact(run, ["alerts.jsonl", "events.jsonl"])
    if p is None:
        return []
    out = []
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:
        return []
    finally:
        _release_artifact(p)
    return out


def get_traces(run_dir: RunSource, object_id: str | None = None) -> list[dict[str, Any]]:
    run = _run_source(run_dir)
    session = _session(run)
    if session is None:
        return []
    try:
        from metriplane.trace.store import TraceStore

        store = TraceStore(registry=_registry(run))
        store.load_session_text(session.read_text())
        summaries = store.summarize()
    except Exception:
        return []
    finally:
        _release_artifact(session)
    rows = []
    for s in summaries:
        if object_id is not None and s.object_id != object_id:
            continue
        rows.append({
            "object_id": s.object_id,
            "marker_id": s.marker_id,
            "duration_s": s.duration_s,
            "total_distance_m": s.total_distance_m,
            "max_speed_mps": s.max_speed_mps,
            "zones_visited": s.zones_visited,
            "dwell_by_zone": s.dwell_by_zone,
            "point_count": s.point_count,
            "gap_count": s.gap_count,
        })
    return rows


def get_frames(run_dir: RunSource, max_frames: int = 600) -> dict[str, Any]:
    """Per-frame object positions for map replay, plus incident windows.

    Returns {"frames": [{ts, frame_id, objects:[{object_id, type, x, y, zone}]}],
             "incidents": [{rule_id, object_ids, opened_ts, closed_ts, severity}]}.
    """
    run = _run_source(run_dir)
    session = _session(run)
    workspace = get_workspace(run)
    if session is None:
        return {"frames": [], "incidents": [], "workspace": workspace}
    try:
        from metriplane.sentinel.engine import iter_frames_text

        registry = _registry(run)
        frames_out: list[dict[str, Any]] = []
        for frame in iter_frames_text(session.read_text(), source=str(session)):
            observed = frame.fused if frame.fused is not None else frame.objects
            objs = []
            for o in observed:
                oid, otype = f"marker_{o.id}", "unknown"
                if registry is not None:
                    try:
                        entry = registry.by_marker_id(int(o.id))
                        if entry is not None:
                            oid, otype = entry.object_id, entry.type
                    except (TypeError, ValueError):
                        pass
                objs.append({
                    "object_id": oid, "type": otype, "zone": o.zone,
                    "x_m": o.pos_world[0] if o.pos_world else None,
                    "y_m": o.pos_world[1] if o.pos_world else None,
                })
            frames_out.append({"ts": frame.ts, "frame_id": frame.frame_id,
                               "objects": objs})
            if len(frames_out) >= max_frames:
                break
    except Exception:
        return {"frames": [], "incidents": [], "workspace": workspace}
    finally:
        _release_artifact(session)

    incidents = []
    for inc in get_incidents(run):
        incidents.append({
            "incident_id": inc.get("incident_id"),
            "rule_id": inc.get("rule_id"),
            "severity": inc.get("severity"),
            "object_ids": inc.get("object_ids", []),
            "opened_ts": inc.get("opened_ts"),
            "closed_ts": inc.get("closed_ts"),
        })
    return {"frames": frames_out, "incidents": incidents, "workspace": workspace}


def get_live_summary(run_dir: RunSource) -> dict[str, Any]:
    run = _run_source(run_dir)
    objects = get_objects(run)
    events = get_events(run)
    incidents = get_incidents(run)
    open_incidents = [i for i in incidents if i.get("status") != "closed"]
    run_id = None
    if incidents:
        run_id = incidents[0].get("run_id")
    return {
        "run_id": run_id,
        "objects_count": len(objects),
        "alerts_count": len(events),
        "open_incidents_count": len(open_incidents),
        "incidents_count": len(incidents),
        "latest_run_dir": str(run),
        "health": {"overall": "OK"},
    }


def export_command_center(run_dir: RunSource, out_path: str | Path) -> dict[str, Any]:
    """Bundle all command-center data into one JSON the static page can load."""
    run = _run_source(run_dir)
    payload = {
        "summary": get_live_summary(run),
        "objects": get_objects(run),
        "incidents": get_incidents(run),
        "events": get_events(run),
        "traces": get_traces(run),
        "workspace": get_workspace(run),
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))
    return payload
