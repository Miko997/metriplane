# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

from metriplane.assistant.citations import make_citation
from metriplane.assistant.models import CitationModel
from metriplane.runner.safe_reads import PinnedDirectory, PinnedFile

RunSource = str | Path | PinnedDirectory
RunArtifact = Path | PinnedFile


def _run_source(run_dir: RunSource) -> Path | PinnedDirectory:
    return run_dir if isinstance(run_dir, PinnedDirectory) else Path(run_dir)


def _citation(
    path: RunArtifact,
    run: Path | PinnedDirectory,
    source_type: str,
    *,
    record_id: str | None = None,
) -> CitationModel:
    if isinstance(path, PinnedFile):
        return CitationModel(
            source_path=str(path.relative_path),
            source_type=source_type,
            record_id=record_id,
        )
    assert isinstance(run, Path)
    return make_citation(path, run, source_type, record_id=record_id)


def _find(
    run_dir: Path | PinnedDirectory,
    names: list[str],
) -> RunArtifact | None:
    if isinstance(run_dir, PinnedDirectory):
        return run_dir.find_file(names)
    try:
        root = run_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not root.is_dir():
        return None
    for name in names:
        candidate = run_dir / name
        try:
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        return resolved
    return None


def retrieve_incidents(
    run_dir: RunSource,
) -> tuple[list[dict[str, Any]], list[CitationModel], list[str]]:
    run = _run_source(run_dir)
    p = _find(run, ["incident.json", "incidents/incidents.json", "incidents.json"])
    if p is None:
        return [], [], ["no incident artifact found in run dir"]
    try:
        data = json.loads(p.read_text())
        incidents = data if isinstance(data, list) else [data]
    except Exception:
        return [], [], [f"could not parse {p.name}"]
    cites = [_citation(p, run, "incidents", record_id=i.get("incident_id")) for i in incidents]
    return incidents, cites, []


def retrieve_rule(
    run_dir: RunSource, rule_id: str | None
) -> tuple[dict[str, Any] | None, list[CitationModel], list[str]]:
    run = _run_source(run_dir)
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
        return ({"rules": [r.get("id") for r in rules]}, [_citation(p, run, "rules")], [])
    for r in rules:
        if r.get("id") == rule_id:
            return r, [_citation(p, run, "rules", record_id=rule_id)], []
    return None, [_citation(p, run, "rules")], [f"rule '{rule_id}' not found"]


def retrieve_camera_trust(
    run_dir: RunSource,
) -> tuple[dict[str, Any] | None, list[CitationModel], list[str]]:
    run = _run_source(run_dir)
    p = _find(run, ["camera_trust.json"])
    if p is not None:
        try:
            return json.loads(p.read_text()), [_citation(p, run, "camera_trust")], []
        except Exception:
            return None, [], ["could not parse camera_trust.json"]
    # fall back to analyzing the session if present
    session = _find(run, ["session_excerpt.jsonl", "session.jsonl"])
    if session is None:
        return None, [], ["no camera_trust.json or session found"]
    try:
        from metriplane.camera_trust.analyzer import CameraTrustAnalyzer
        from metriplane.sentinel.engine import iter_frames_text

        analyzer = CameraTrustAnalyzer()
        for frame in iter_frames_text(session.read_text(), source=str(session)):
            analyzer.update(frame)
        report = analyzer.report().model_dump()
        return report, [_citation(session, run, "session")], []
    except Exception:
        return None, [], ["camera trust analysis failed"]


def retrieve_traces(
    run_dir: RunSource, object_id: str | None = None
) -> tuple[list[dict[str, Any]], list[CitationModel], list[str]]:
    run = _run_source(run_dir)
    session = _find(run, ["session_excerpt.jsonl", "session.jsonl"])
    if session is None:
        return [], [], ["no session found for traces"]
    objects_path = _find(run, ["objects.yaml", "object_registry.yaml"])
    try:
        import yaml

        from metriplane.sentinel.registry import ObjectRegistryConfig
        from metriplane.trace.store import TraceStore

        registry = (
            ObjectRegistryConfig.model_validate(yaml.safe_load(objects_path.read_text()))
            if objects_path is not None
            else None
        )
        store = TraceStore(registry=registry)
        store.load_session_text(session.read_text())
        summaries = store.summarize()
    except Exception:
        return [], [], ["trace analysis failed"]
    rows = []
    for s in summaries:
        if object_id is not None and s.object_id != object_id:
            continue
        rows.append(
            {
                "object_id": s.object_id,
                "duration_s": s.duration_s,
                "total_distance_m": s.total_distance_m,
                "zones_visited": s.zones_visited,
                "dwell_by_zone": s.dwell_by_zone,
                "gap_count": s.gap_count,
            }
        )
    cite = [_citation(session, run, "session")]
    return rows, cite, []


def known_object_ids(run_dir: RunSource) -> list[str]:
    rows, _, _ = retrieve_traces(run_dir)
    return [r["object_id"] for r in rows]
