# Counterfactual Incident Reports — Phase 21 Evidence

- phase: 21
- feature: counterfactual_reports
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/counterfactuals/
- bundle_path: evidence/incidents/INC-DIST-001
- incident_id: inc_0001 (rule cart_person_distance, objects cart_01 + human_proxy_01)

## Commands run

```bash
python -m pytest tests/test_counterfactual_models.py \
  tests/test_counterfactual_transforms.py tests/test_counterfactual_rule_sweep.py \
  tests/test_counterfactual_evaluator.py -q

metriplane counterfactual evidence/incidents/INC-DIST-001 \
  --sweep-rule cart_person_distance.min_distance_m=0.1:0.6:0.1 \
  --slow-object human_proxy_01=0.5 \
  --remove-object human_proxy_01 \
  --output evidence/experiments/counterfactual_reports_001.json
```

## Result

```text
Original: cart_person_distance (critical) objects=cart_01,human_proxy_01
  [PREVENTED] min_distance_m=0.1: original incident not detected
  [PREVENTED] min_distance_m=0.2: original incident not detected
  [PREVENTED] min_distance_m=0.3: original incident not detected
  [kept]      min_distance_m=0.4: original incident still detected
  [kept]      min_distance_m=0.5: original incident still detected
  [kept]      min_distance_m=0.6: original incident still detected
  [PREVENTED] human_proxy_01 speed x0.5: original incident not detected
  [PREVENTED] remove human_proxy_01: original incident not detected
```

- cases_total: 8
- transforms_used: rule_threshold_sweep, object_speed_scale, object_remove
- cases_preventing_original_incident: 5
- cases_preserving_original_incident: 3

## Transforms implemented

- rule_threshold_sweep (modifies a copied ruleset only)
- object_speed_scale (scales displacement from first frame)
- object_remove (drops object from frames)

The original bundle is never mutated; baseline reproduction is verified before any
transform runs.

## Tests

- tests/test_counterfactual_models.py (4)
- tests/test_counterfactual_rule_sweep.py (7)
- tests/test_counterfactual_transforms.py (7)
- tests/test_counterfactual_evaluator.py (10)

## Limitations

- Geometric replay transform only; not a physics simulation.
- Speed scaling assumes constant scaling of displacement from the first frame.
- Results show detection under the transform, not causal proof.
- Position-based transforms (speed/remove) affect distance/speed rules; zone-label rules
  respond to object_remove but not to repositioning, since zone membership comes from the
  recorded frame label.
