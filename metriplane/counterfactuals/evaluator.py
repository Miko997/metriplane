from __future__ import annotations

from pathlib import Path

from metriplane.counterfactuals.models import (
    CounterfactualCaseResult,
    CounterfactualReport,
    CounterfactualTransform,
)
from metriplane.counterfactuals.transforms import (
    apply_rule_threshold,
    remove_object,
    scale_object_speed,
)
from metriplane.sentinel.engine import RuleEngine, iter_frames
from metriplane.sentinel.events import read_incidents_json
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import RuleSet, load_rules

MAX_CASES_DEFAULT = 50


class CounterfactualError(RuntimeError):
    pass


def _eval(frames, ruleset: RuleSet, registry) -> list:
    engine = RuleEngine(ruleset, registry)
    alerts = []
    for f in frames:
        alerts.extend(engine.process_frame(f))
    return build_incidents(alerts)


def _present(incidents, rule_id: str, objects: set[str]) -> bool:
    for inc in incidents:
        if inc.rule_id == rule_id and (not objects or objects.issubset(set(inc.object_ids))):
            return True
    return False


class CounterfactualEvaluator:
    def __init__(self, max_cases: int = MAX_CASES_DEFAULT):
        self.max_cases = max_cases

    def evaluate(self, bundle_path: str | Path,
                 transforms: list[CounterfactualTransform]) -> CounterfactualReport:
        bundle = Path(bundle_path)
        incidents_meta = read_incidents_json(bundle / "incident.json")
        if not incidents_meta:
            raise CounterfactualError("bundle has no incident.json record")
        original = incidents_meta[0]
        target_rule = original.rule_id
        target_objs = set(original.object_ids)

        frames = list(iter_frames(bundle / "session_excerpt.jsonl"))
        ruleset = load_rules(bundle / "rules.yaml")
        objects_path = bundle / "objects.yaml"
        registry = load_registry(objects_path) if objects_path.exists() else None

        # Baseline must reproduce the original incident before any transform.
        baseline = _eval(frames, ruleset, registry)
        if not _present(baseline, target_rule, target_objs):
            raise CounterfactualError(
                "baseline does not reproduce the original incident; refusing to run")

        def _marker(obj_or_marker: str) -> str:
            if registry is not None:
                entry = registry.by_object_id(obj_or_marker)
                if entry is not None:
                    return str(entry.marker_id)
            return obj_or_marker

        cases: list[CounterfactualCaseResult] = []
        for i, tr in enumerate(transforms[: self.max_cases]):
            case_id = f"cf_{i + 1:03d}"
            try:
                incidents = self._apply(tr, frames, ruleset, registry, _marker)
            except Exception as e:
                cases.append(CounterfactualCaseResult(
                    case_id=case_id, transform=tr, **{"pass": False},
                    original_incident_present=False,
                    summary=f"error: {e}"))
                continue
            present = _present(incidents, target_rule, target_objs)
            cases.append(CounterfactualCaseResult(
                case_id=case_id, transform=tr, **{"pass": True},
                original_incident_present=present,
                observed_incidents=[
                    {"rule_id": inc.rule_id, "severity": inc.severity,
                     "objects": inc.object_ids} for inc in incidents],
                summary=self._summary(tr, present),
                metrics={"incident_count": len(incidents)}))

        return CounterfactualReport(
            bundle_path=str(bundle),
            incident_id=original.incident_id,
            original_summary={
                "rule_id": target_rule,
                "severity": original.severity,
                "objects": sorted(target_objs),
            },
            cases=cases,
            limitations=[
                "Geometric replay transform only; not a physics simulation.",
                "Speed scaling assumes constant scaling of displacement from first frame.",
                "Results show detection under the transform, not causal proof.",
            ],
        )

    def _apply(self, tr, frames, ruleset, registry, marker_fn):
        if tr.type == "rule_threshold_sweep":
            rs = apply_rule_threshold(ruleset, tr.target,
                                      tr.params["field"], tr.params["value"])
            return _eval(frames, rs, registry)
        if tr.type == "object_speed_scale":
            nf = scale_object_speed(frames, marker_fn(tr.target),
                                    float(tr.params["factor"]))
            return _eval(nf, ruleset, registry)
        if tr.type == "object_remove":
            nf = remove_object(frames, marker_fn(tr.target))
            return _eval(nf, ruleset, registry)
        raise CounterfactualError(f"unsupported transform: {tr.type}")

    @staticmethod
    def _summary(tr, present) -> str:
        verb = "still detected" if present else "not detected"
        if tr.type == "rule_threshold_sweep":
            return (f"{tr.target}.{tr.params['field']}={tr.params['value']}: "
                    f"original incident {verb}")
        if tr.type == "object_speed_scale":
            return f"{tr.target} speed x{tr.params['factor']}: original incident {verb}"
        if tr.type == "object_remove":
            return f"remove {tr.target}: original incident {verb}"
        return verb
