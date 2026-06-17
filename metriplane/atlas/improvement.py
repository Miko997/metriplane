# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.atlas.models import AtlasIncident, ImprovementAction


def recommend_actions(incidents: list[AtlasIncident]) -> list[ImprovementAction]:
    actions: list[ImprovementAction] = []
    for idx, incident in enumerate(incidents, start=1):
        if incident.incident_type == "missing_tool_caused_delay":
            actions.append(ImprovementAction(
                action_id=f"act_{idx:04d}",
                action_type="add_required_tool_check",
                title="Add a required-tool staging check",
                rationale=(
                    f"{incident.incident_id} shows a required asset was absent while a "
                    "process step waited. Add a visible pre-step tool/material check."
                ),
                cited_event_ids=list(incident.event_ids),
                cited_incident_ids=[incident.incident_id],
            ))
    return actions


def _metrics(run_dir: Path) -> dict:
    path = run_dir / "metrics.json"
    if not path.exists():
        raise ValueError(f"missing metrics.json in {run_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_runs(before_run: str | Path, after_run: str | Path, out_path: str | Path) -> dict:
    before = Path(before_run)
    after = Path(after_run)
    before_metrics = _metrics(before)
    after_metrics = _metrics(after)
    before_wait = sum(float(value) for value in before_metrics.get("wait_time_s", {}).values())
    after_wait = sum(float(value) for value in after_metrics.get("wait_time_s", {}).values())
    before_incidents = int(before_metrics.get("incident_count", 0))
    after_incidents = int(after_metrics.get("incident_count", 0))
    result = {
        "schema_version": "metriplane.atlas.before_after_improvement.v1",
        "before_run": str(before),
        "after_run": str(after),
        "before_wait_time_s": round(before_wait, 3),
        "after_wait_time_s": round(after_wait, 3),
        "wait_time_delta_s": round(after_wait - before_wait, 3),
        "before_incidents": before_incidents,
        "after_incidents": after_incidents,
        "incident_delta": after_incidents - before_incidents,
        "conclusion": (
            "After run reduced observed wait/incident burden in this replay."
            if after_wait < before_wait or after_incidents < before_incidents
            else "No replay improvement detected."
        ),
        "caveat": "Before/after comparison is replay evidence, not proof of a guaranteed causal fix.",
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
