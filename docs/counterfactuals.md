<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Counterfactual Incident Reports

Sentinel can run **geometric counterfactuals** over an incident bundle to test whether
changed rules or object trajectories would still produce the same incident. It answers
"what if" questions like:

- What if the distance threshold were 0.5 m instead of 0.6 m?
- What if the object moved 50% slower?
- Would the incident still be detected if an object were absent?

This is **not a physics simulation and not causal proof**. It is a deterministic
replay-time transformation and re-evaluation tool. Wording is always "under this geometric
replay transform."

## Command

```bash
metriplane counterfactual evidence/incidents/INC-DIST-001 \
  --sweep-rule cart_person_distance.min_distance_m=0.1:0.6:0.1 \
  --slow-object human_proxy_01=0.5 \
  --remove-object human_proxy_01 \
  --output evidence/incidents/INC-DIST-001/counterfactual_report.json
```

## Output

```text
Original: cart_person_distance (critical) objects=cart_01,human_proxy_01
  [PREVENTED] min_distance_m=0.1: original incident not detected
  ...
  [kept]      min_distance_m=0.6: original incident still detected
  [PREVENTED] human_proxy_01 speed x0.5: original incident not detected
  [PREVENTED] remove human_proxy_01: original incident not detected
```

## Supported transforms

| Flag | Transform | Effect |
|---|---|---|
| `--sweep-rule rule.field=start:stop:step` | rule_threshold_sweep | re-evaluates across a threshold range (copied ruleset only) |
| `--slow-object id=factor` | object_speed_scale | scales an object's displacement from its first frame |
| `--remove-object id` | object_remove | drops an object from the replay frames |

## Safety

- The **original bundle is never mutated**; transforms run on in-memory copies.
- The baseline (no transform) must reproduce the original incident before any case runs.
- No code from a bundle or transform spec is executed; transforms are data operations.

## Limitations

- Geometric only — no acceleration, collision, or physical-plausibility modeling.
- Position transforms affect distance/speed rules. Zone-label rules respond to object
  removal but not to repositioning, because zone membership comes from the recorded frame
  label rather than recomputed geometry.
- A counterfactual shows detection under a transform; it is not a causal claim.
