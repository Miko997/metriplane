# Camera Trust — Phase 22 Evidence

- phase: 22
- feature: camera_trust
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/camera_trust/
- input_session: tests/fixtures/camera_trust/multicam_session.jsonl

## Command

```bash
metriplane camera-trust analyze \
  --input tests/fixtures/camera_trust/multicam_session.jsonl \
  --out evidence/experiments/camera_trust_001.json
```

## Result

- frames_analyzed: 5
- cameras_seen: cam0, cam1
- cam0: OK, score 1.0, dropout 0.0, disagreement 0.0 m
- cam1: FAILED, score 0.1, dropout 0.6, mean disagreement 0.083 m
- recommendations: 2 (dropout check + recalibration)

The fixture models a healthy cam0 (agrees with fused every frame) and a degraded cam1
(misses 3 of 5 frames and disagrees by ~8 cm when it does see the object).

## Tests

- tests/test_camera_trust_models.py (3)
- tests/test_camera_trust_analyzer.py (6): dropout, disagreement, status, frame count,
  no-raw-per-camera safety, stable ordering.
- tests/test_camera_trust_recommendations.py (5)

## Limitations

- Qualitative operator guidance, not optimal placement coordinates.
- Single-camera runs yield null disagreement (no redundancy).
- Reports are operationally sensitive (camera ids, layout quality); no raw video included.
