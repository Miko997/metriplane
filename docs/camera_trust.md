<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Camera Trust & Placement Advisor

Metriplane scores camera reliability and zone coverage from structured observations, and
emits qualitative operator recommendations. It is non-invasive and needs no raw video — it
works from `raw_per_camera` + `fused` records in a session.

## Run it

```bash
metriplane camera-trust analyze \
  --input tests/fixtures/camera_trust/multicam_session.jsonl \
  --out camera_trust.json
```

## Report

```json
{
  "camera_scores": {
    "cam0": {"status": "OK", "score": 1.0, "dropout_rate": 0.0, "mean_disagreement_m": 0.0},
    "cam1": {"status": "FAILED", "score": 0.1, "dropout_rate": 0.6, "mean_disagreement_m": 0.083}
  },
  "recommendations": [
    "cam1 has high dropout (60%); check cable, focus, occlusion, or device index.",
    "cam1 disagrees with the fused estimate by 8.3 cm; re-run calibration / alignment validation."
  ]
}
```

## Metrics

- **dropout_rate** — fraction of frames where the camera produced no detection.
- **mean / p95 disagreement (m)** — distance between a camera's world-XY for an object and
  the fused estimate of the same object.
- **mean_confidence** — average detection confidence.
- **zone coverage** — how many cameras observe objects in each zone (single-camera zones
  are flagged as low redundancy).

## Trust score (transparent heuristic)

```
score = 1.0 − dropout_penalty − disagreement_penalty − low_confidence_penalty
OK: score ≥ 0.80   DEGRADED: 0.50–0.80   FAILED: < 0.50
```

Thresholds are configurable (`disagreement_warn_m`, `dropout_fail_rate`, …).

## Limitations

- MVP provides **qualitative guidance**, not optimal camera-placement coordinates.
- Single-camera runs report scores but disagreement is null (no redundancy to compare).
- Reports contain camera ids, zone names, and layout quality — treat as operationally
  sensitive. No raw images/video are included.
