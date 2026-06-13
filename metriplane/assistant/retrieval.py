from __future__ import annotations

import json
from pathlib import Path

from metriplane.assistant.citations import make_citation
from metriplane.assistant.models import CitationModel


def _find(run_dir: Path, names: list[str]) -> Path | None:
    for n in names:
        p = run_dir / n
        if p.exists():
            return p
    return None


def retrieve_incidents(run_dir: str | Path) -> tuple[list[dict], list[CitationModel], list[str]]:
    run = Path(run_dir)
    p = _find(run, ["incident.json", "incidents/incidents.json", "incidents.json"])
    if p is None:
        return [], [], ["no incident artifact found in run dir"]
    try:
        data = json.loads(p.read_text())
        incidents = data if isinstance(data, list) else [data]
    except Exception:
        return [], [], [f"could not parse {p.name}"]
    cites = [make_citation(p, run, "incidents", record_id=i.get("incident_id"))
             for i in incidents]
    return incidents, cites, []


def retrieve_rule(run_dir: str | Path, rule_id: str | None
                  ) -> tuple[dict | None, list[CitationModel], list[str]]:
    run = Path(run_dir)
    p = _find(run, ["rules.yaml", "contract.yaml", "contracts.yaml"])
    if p is None:
        return None, [], ["no rules/contract artifact found in run dir"]
    try:
        import yaml
        data = yaml.safe_load(p.read_text()) or {}
        rules = data.get("rules", [])
    except Exception:
        return None, [], [f"could not parse {p.name}"]
    if rule_id is None:
        return ({"rules": [r.get("id") for r in rules]},
                [make_citation(p, run, "rules")], [])
    for r in rules:
        if r.get("id") == rule_id:
            return r, [make_citation(p, run, "rules", record_id=rule_id)], []
    return None, [make_citation(p, run, "rules")], [f"rule '{rule_id}' not found"]


def retrieve_camera_trust(run_dir: str | Path
                          ) -> tuple[dict | None, list[CitationModel], list[str]]:
    run = Path(run_dir)
    p = _find(run, ["camera_trust.json"])
    if p is not None:
        try:
            return json.loads(p.read_text()), [make_citation(p, run, "camera_trust")], []
        except Exception:
            return None, [], ["could not parse camera_trust.json"]
    # fall back to analyzing the session if present
    session = _find(run, ["session_excerpt.jsonl", "session.jsonl"])
    if session is None:
        return None, [], ["no camera_trust.json or session found"]
    try:
        from metriplane.camera_trust.analyzer import analyze_session
        report = analyze_session(session).model_dump()
        return report, [make_citation(session, run, "session")], []
    except Exception:
        return None, [], ["camera trust analysis failed"]


def retrieve_traces(run_dir: str | Path, object_id: str | None = None
                    ) -> tuple[list[dict], list[CitationModel], list[str]]:
    run = Path(run_dir)
    session = _find(run, ["session_excerpt.jsonl", "session.jsonl"])
    if session is None:
        return [], [], ["no session found for traces"]
    objects_path = _find(run, ["objects.yaml", "object_registry.yaml"])
    try:
        from metriplane.trace.store import TraceStore
        store = TraceStore(registry_path=objects_path)
        store.load_session(session)
        summaries = store.summarize()
    except Exception:
        return [], [], ["trace analysis failed"]
    rows = []
    for s in summaries:
        if object_id is not None and s.object_id != object_id:
            continue
        rows.append({
            "object_id": s.object_id, "duration_s": s.duration_s,
            "total_distance_m": s.total_distance_m, "zones_visited": s.zones_visited,
            "dwell_by_zone": s.dwell_by_zone, "gap_count": s.gap_count,
        })
    cite = [make_citation(session, run, "session")]
    return rows, cite, []


def known_object_ids(run_dir: str | Path) -> list[str]:
    rows, _, _ = retrieve_traces(run_dir)
    return [r["object_id"] for r in rows]
