# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Bind an additive requirement assessment to the inputs retained in an Atlas run.

Hashes detect changed retained files; they do not authenticate their author or
establish the accuracy of upstream physical observations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from metriplane import __version__
from metriplane.atlas.domain_packs import load_domain_pack
from metriplane.schema import FrameStateModel

ASSESSMENT_PATH = "requirement_assessment.json"
RUN_ASSESSMENT_SCHEMA = "metriplane.atlas.run_assessment.v1"
_REQUIRED_FILES = (
    "configs/assets.yaml", "configs/workspace.yaml", "configs/process.yaml",
    "state_segment.jsonl", "metrics.json", "physical_event_log.jsonl",
    "process_trace.json", "incidents.jsonl", "deviations.jsonl",
)
_OPTIONAL_FILES = (
    "configs/contracts.yaml", "configs/work_orders.csv", "external_source_provenance.json",
)


def _file(root: Path, name: str) -> Path:
    path = root / name
    if root.is_symlink() or any(part.is_symlink() for part in (path, *path.parents)
                                if part == root or root in part.parents):
        raise ValueError(f"assessment input must not use symlinks: {name}")
    if not path.is_file():
        raise ValueError(f"missing assessment input: {name}")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path.name}")
    # Reject nonstandard NaN/Infinity accepted by Python's JSON decoder.
    json.dumps(data, allow_nan=False)
    return data


def _canonical_sha(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _evidence(root: Path) -> dict[str, str | None]:
    result: dict[str, str | None] = {name: _sha(_file(root, name)) for name in _REQUIRED_FILES}
    for name in _OPTIONAL_FILES:
        path = root / name
        result[name] = _sha(_file(root, name)) if path.exists() or path.is_symlink() else None
    return result


def _identity() -> dict[str, Any]:
    return {
        "metriplane_version": __version__,
        "implementation_sha256": {
            name: _sha(Path(__file__).with_name(name))
            for name in ("process_model.py", "assessment.py")
        },
    }


def _context_and_coverage(root: Path, assessment: dict[str, Any],
                          identity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pack = load_domain_pack(root / "configs")
    frames = [FrameStateModel.model_validate(json.loads(line))
              for line in _file(root, "state_segment.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    if not frames:
        raise ValueError("assessment state segment is empty")
    if (assessment["process_id"] != pack.process.process_id
            or assessment["work_order_id"] != pack.work_orders[0].work_order_id
            or [step["step_id"] for step in assessment["steps"]] !=
               [step.step_id for step in pack.process.steps]):
        raise ValueError("assessment requirement identities do not match retained process")
    expected_counts = {outcome: sum(step["outcome"] == outcome for step in assessment["steps"])
                       for outcome in ("satisfied", "violated", "unresolved", "not_exercised")}
    if assessment["counts"] != expected_counts:
        raise ValueError("assessment outcome counts are inconsistent")
    for step in assessment["steps"]:
        start, end = step["trigger_ts"], step["completion_ts"]
        expected_outcome = ("violated" if step["detection_ts"] is not None else
                            "satisfied" if end is not None else
                            "unresolved" if start is not None else "not_exercised")
        if step["outcome"] != expected_outcome:
            raise ValueError("assessment step outcome is inconsistent with its timing")
        if end is not None:
            if start is None or end < start or step["observed_wait_s"] != float(Decimal(str(end)) - Decimal(str(start))):
                raise ValueError("assessment completed wait is inconsistent with its observations")
        elif step["observed_wait_s"] is not None:
            raise ValueError("assessment unfinished step cannot have a completed observed wait")
    required_ids = {asset for step in pack.process.steps for asset in step.required_assets}
    expected_types = {kind for step in pack.process.steps for kind in step.expected_asset_types}
    object_ids = {asset.object_id for asset in pack.assets.assets
                  if asset.asset_id in required_ids or asset.asset_type in expected_types}
    gaps: set[str] = set()
    # Match the existing Atlas evaluator's float conversion exactly.
    times = [float(frame.ts_sim_ns) / 1_000_000_000.0
             if frame.ts_sim_ns is not None else float(frame.ts) for frame in frames]
    timed_steps = {step.step_id for step in pack.process.steps if step.required_assets}
    if any(step["step_id"] in timed_steps and
           step["trigger_ts"] == step["completion_ts"] == times[0]
           for step in assessment["steps"]):
        gaps.add("first_sample_completion_without_prior_observation")
    if any(not math.isfinite(ts) for ts in times):
        gaps.add("nonfinite_time")
    if any(after <= before for before, after in zip(times, times[1:])):
        gaps.add("nonincreasing_time")
    if any(after.frame_id != before.frame_id + 1 for before, after in zip(frames, frames[1:])):
        gaps.add("noncontiguous_frame_ids")
    time_fields = sorted({"ts_sim_ns" if frame.ts_sim_ns is not None else "ts" for frame in frames})
    if len(time_fields) != 1:
        gaps.add("mixed_authoritative_clocks")
    collections = sorted({"fused" if frame.fused is not None else "objects" for frame in frames})
    for frame in frames:
        objects = frame.fused if frame.fused is not None else frame.objects
        by_id = {obj.id: obj for obj in objects}
        if object_ids - by_id.keys():
            gaps.add("missing_relevant_observations")
        for object_id in object_ids & by_id.keys():
            obj = by_id[object_id]
            if obj.pos_world is None or not all(math.isfinite(value) for value in obj.pos_world):
                gaps.add("unknown_relevant_position")
            if not obj.zone:
                gaps.add("unknown_relevant_zone")
    if any(step.get("coverage_gaps") is not False for step in assessment["steps"]):
        gaps.add("requirement_observation_gaps")
    steps_complete = all(step.get("completion_ts") is not None and
                         step.get("outcome") in {"satisfied", "violated"}
                         for step in assessment["steps"])
    coverage = {
        "schema_version": "metriplane.atlas.comparison_coverage.v1",
        "complete": not gaps and steps_complete,
        "complete_recorded_snapshots": not gaps,
        "all_steps_completed": steps_complete,
        "gaps": sorted(gaps),
        "frame_count": len(frames),
        "relevant_object_ids": sorted(object_ids),
        "step_ids": [step.step_id for step in pack.process.steps],
        "first_observation_ts": times[0],
        "last_observation_ts": times[-1],
        "limitation": "Completeness concerns retained samples, not unobserved physical events.",
    }
    provenance_path = root / "external_source_provenance.json"
    if provenance_path.exists():
        provenance = _json(_file(root, "external_source_provenance.json"))
        normalization = provenance.get("normalization")
        if not isinstance(normalization, dict):
            normalization = {}
        normalization_keys = (
            "frame_state_model_version", "source_backend", "authoritative_object_collection",
            "clock", "coordinates", "zone_assignment", "completeness", "temporal_alignment",
            "confidence", "entity_mapping", "atlas_asset_mapping",
        )
        if any(normalization.get(key) is None for key in normalization_keys):
            gaps.add("missing_external_normalization_context")
        normalization_context = {
            "kind": "external_source_contract",
            "contract_schema_version": provenance.get("contract_schema_version"),
            "contract_profile": provenance.get("contract_profile"),
            "adapter": provenance.get("adapter"),
            "normalization": {key: normalization.get(key) for key in normalization_keys},
        }
    else:
        normalization_context = {
            "kind": "native_recorded_state",
            "frame_state_model_version": "1.0",
            "object_collection_policy": "fused_when_nonnull_otherwise_objects",
            "zone_assignment": "supplied_state_labels",
            "upstream_accuracy": "not_established",
        }
    coverage["gaps"] = sorted(gaps)
    coverage["complete_recorded_snapshots"] = not gaps
    coverage["complete"] = not gaps and steps_complete
    context = {
        "schema_version": "metriplane.atlas.comparison_context.v1",
        "evaluator_identity": identity,
        "deadline_policy": assessment["policy"],
        "process_rules_sha256": _canonical_sha(pack.process.model_dump(mode="json")),
        "asset_mapping_sha256": _canonical_sha(pack.assets.model_dump(mode="json")),
        "workspace_sha256": _canonical_sha(pack.workspace.model_dump(mode="json")),
        "work_orders_sha256": _canonical_sha([order.model_dump(mode="json") for order in pack.work_orders]),
        "contracts_sha256": _sha(pack.contracts_path) if pack.contracts_path else None,
        "normalization": normalization_context,
        "time_policy": {
            "authoritative_fields": time_fields,
            # Legacy threshold arithmetic uses absolute binary-float times;
            # translating the clock can therefore change boundary detection.
            "first_authoritative_timestamp_s": times[0],
            "frame_count": len(frames),
            "observed_duration_s": float(Decimal(str(times[-1])) - Decimal(str(times[0]))),
            "relative_sample_schedule_sha256": _canonical_sha([
                str(Decimal(str(timestamp)) - Decimal(str(times[0]))) for timestamp in times
            ]),
            "observed_sample_intervals_s": sorted({round(after - before, 12)
                                                    for before, after in zip(times, times[1:])}),
        },
        "source_backends": sorted({frame.source_backend for frame in frames}),
        "initial_relevant_zones": {
            obj.id: obj.zone
            for obj in (frames[0].fused if frames[0].fused is not None else frames[0].objects)
            if obj.id in object_ids
        },
        "observed_object_collections": collections,
        "step_ids": coverage["step_ids"],
    }
    return context, coverage


def _observed_wait(assessment: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    complete = coverage["complete"] and all(step.get("observed_wait_s") is not None
                                             for step in assessment["steps"])
    by_step = {step["step_id"]: step.get("observed_wait_s") for step in assessment["steps"]}
    return {
        "schema_version": "metriplane.atlas.observed_wait.v1",
        "complete": complete,
        "by_step_s": by_step,
        "total_s": round(sum(by_step.values()), 12) if complete else None,
        "meaning": "Observed trigger-to-completion wait across completed process steps; not detection latency.",
    }


def write_run_assessment(run_dir: Path, process_assessment: dict[str, Any]) -> str:
    from metriplane.atlas.assessment import RequirementAssessment

    assessment = RequirementAssessment.model_validate(process_assessment).model_dump(mode="json")
    evidence = _evidence(run_dir)
    context, coverage = _context_and_coverage(run_dir, assessment, _identity())
    result = {
        "schema_version": RUN_ASSESSMENT_SCHEMA,
        "process_assessment": assessment,
        "comparison_context": context,
        "coverage": coverage,
        "observed_wait": _observed_wait(assessment, coverage),
        "evidence_sha256": evidence,
    }
    path = run_dir / ASSESSMENT_PATH
    path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return _sha(path)


def read_run_assessment(run_dir: Path) -> dict[str, Any]:
    """Load a supported, hash-bound assessment or fail without inventing metadata."""
    from metriplane.atlas.assessment import RequirementAssessment

    manifest = _json(_file(run_dir, "atlas_manifest.json"))
    if manifest.get("artifacts", {}).get("requirement_assessment") != ASSESSMENT_PATH:
        raise ValueError("missing supported requirement assessment reference")
    digest = manifest.get("requirement_assessment_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("missing requirement assessment SHA-256")
    path = _file(run_dir, ASSESSMENT_PATH)
    if _sha(path) != digest:
        raise ValueError("requirement assessment SHA-256 mismatch")
    result = _json(path)
    if result.get("schema_version") != RUN_ASSESSMENT_SCHEMA:
        raise ValueError("unsupported run assessment schema")
    if result.get("evidence_sha256") != _evidence(run_dir):
        raise ValueError("retained assessment evidence SHA-256 mismatch")
    assessment = RequirementAssessment.model_validate(result["process_assessment"]).model_dump(mode="json")
    if assessment["run_id"] != manifest.get("run_id"):
        raise ValueError("assessment run identity does not match manifest")
    identity = result["comparison_context"]["evaluator_identity"]
    if (not isinstance(identity, dict) or not isinstance(identity.get("metriplane_version"), str)
            or not identity["metriplane_version"]
            or set(identity.get("implementation_sha256", {})) != {"process_model.py", "assessment.py"}
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in identity["implementation_sha256"].values())):
        raise ValueError("missing evaluator implementation identity")
    context, coverage = _context_and_coverage(run_dir, assessment, identity)
    if result["comparison_context"] != context:
        raise ValueError("comparison context does not match retained inputs")
    if result.get("coverage") != coverage or result.get("observed_wait") != _observed_wait(assessment, coverage):
        raise ValueError("assessment coverage or wait summary does not match retained inputs")
    return result
