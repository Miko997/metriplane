# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import math
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
    metrics = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict) or not isinstance(metrics.get("wait_time_s"), dict):
        raise ValueError(f"invalid legacy wait metrics in {run_dir}")
    values = metrics["wait_time_s"].values()
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value < 0 for value in values):
        raise ValueError(f"invalid legacy wait metric value in {run_dir}")
    count = metrics.get("incident_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"invalid incident count in {run_dir}")
    return metrics


def _eligibility(before: Path, after: Path) -> tuple[dict, dict | None, dict | None]:
    from metriplane.atlas.run_assessment import read_run_assessment

    reasons = []
    assessments = []
    for side, run in (("before", before), ("after", after)):
        try:
            assessment = read_run_assessment(run)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            reasons.append({"code": "assessment_evidence_unavailable", "side": side, "detail": str(exc)})
            assessment = None
        assessments.append(assessment)
        if assessment is not None and not assessment["coverage"]["complete"]:
            reasons.append({"code": "incomplete_requirement_coverage", "side": side,
                            "detail": "Every matched step must complete with complete retained observations."})
        if assessment is not None and not assessment["observed_wait"]["complete"]:
            reasons.append({"code": "incomplete_observed_wait", "side": side,
                            "detail": "An unresolved or unexercised interval cannot be counted as zero wait."})
    before_assessment, after_assessment = assessments
    status = "insufficient_evidence" if reasons else "eligible"
    compared_keys: list[str] = []
    if before_assessment is not None and after_assessment is not None:
        before_context = before_assessment["comparison_context"]
        after_context = after_assessment["comparison_context"]
        for key in before_context:
            if key == "schema_version":
                continue
            compared_keys.append(key)
            if before_context[key] != after_context[key]:
                reasons.append({
                    "code": "requirement_changed" if key == "process_rules_sha256" else "comparison_context_changed",
                    "field": key,
                    "detail": "The retained evaluation conditions differ; no performance improvement is inferred.",
                })
                if status == "eligible":
                    status = "incompatible"
    return ({
        "schema_version": "metriplane.atlas.comparison_eligibility.v1",
        "status": status,
        "eligible": status == "eligible",
        "reasons": reasons,
        "compared_context_keys": compared_keys,
        "integrity_scope": "Retained-file integrity, not source authenticity or physical accuracy.",
    }, before_assessment, after_assessment)


def compare_runs(before_run: str | Path, after_run: str | Path, out_path: str | Path) -> dict:
    before = Path(before_run)
    after = Path(after_run)
    before_metrics = _metrics(before)
    after_metrics = _metrics(after)
    before_wait = sum(float(value) for value in before_metrics["wait_time_s"].values())
    after_wait = sum(float(value) for value in after_metrics["wait_time_s"].values())
    before_incidents = before_metrics["incident_count"]
    after_incidents = after_metrics["incident_count"]
    eligibility, before_assessment, after_assessment = _eligibility(before, after)
    before_observed = before_assessment["observed_wait"]["total_s"] if before_assessment else None
    after_observed = after_assessment["observed_wait"]["total_s"] if after_assessment else None
    direction = "not_comparable"
    conclusion = "No improvement conclusion: comparison evidence is insufficient or evaluation conditions differ."
    if eligibility["eligible"]:
        wait_delta = after_observed - before_observed
        incident_delta = after_incidents - before_incidents
        if wait_delta < 0 and incident_delta <= 0:
            direction = "improved"
            conclusion = "After run reduced observed wait/incident burden under the same retained evaluation conditions."
        elif wait_delta == 0 and incident_delta != 0:
            direction = "incident_count_reduced" if incident_delta < 0 else "incident_count_increased"
            conclusion = (
                "The sampled incident count changed while observed wait was unchanged. "
                "No overall improvement or regression is inferred: legacy threshold detection "
                "is sensitive to the absolute floating-point phase of a trigger."
            )
        elif wait_delta == 0 and incident_delta == 0:
            direction = "unchanged"
            conclusion = "No observed wait or incident-count change under the same retained evaluation conditions."
        elif wait_delta >= 0 and incident_delta >= 0:
            direction = "regressed"
            conclusion = "After run increased observed wait/incident burden under the same retained evaluation conditions."
        else:
            direction = "tradeoff"
            conclusion = "Observed wait and incident count changed in opposing directions; no overall improvement is inferred."
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
        "legacy_wait_metric": {
            "schema_version": "metriplane.atlas.legacy_deviation_wait_metric.v1",
            "meaning": "Legacy wait_time_s values are sampled deviation durations, not completed observed waits.",
            "used_for_improvement_conclusion": False,
        },
        "eligibility": eligibility,
        "comparison_status": direction,
        "observed_wait": {
            "schema_version": "metriplane.atlas.observed_wait_comparison.v1",
            "before_total_s": before_observed,
            "after_total_s": after_observed,
            "delta_s": round(after_observed - before_observed, 12) if eligibility["eligible"] else None,
            "used_for_improvement_conclusion": eligibility["eligible"],
        },
        "conclusion": conclusion,
        "caveat": "Before/after comparison is replay evidence, not proof of a guaranteed causal fix.",
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
