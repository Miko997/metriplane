# Operator UI Smoke Test 001

Date: 2026-04-28
Run ID: operator_run_20260428_094902
Runner: ./tools/dashboard_runner.sh
Dashboard: http://localhost:8088/web/dashboard/operator.html

## Result

PASS: Operator UI completed the end-to-end low-code workflow.

## Steps validated

- Doctor
- Preflight
- Camera scan
- Profile creation
- cam0 homography calibration
- cam1 homography calibration
- Planar alignment validation
- Zone writing
- Runtime config generation
- 60-second fusion run
- Zone report export
- ID stability export
- Session checksum

## Run artifact

Session:
- ~/metriplane-runs/operator_run_20260428_094902/session.jsonl
- Size: 14 MB
- SHA256: de6d0fa9e817476342a60fdb56c1ee096c03a2b2f3c7039c8a70acc219972c40

## Exported evidence

- evidence/experiments/operator_zone_events.csv
- evidence/experiments/operator_zone_dwell.csv
- evidence/experiments/operator_zone_dwell_by_zone.csv
- evidence/experiments/operator_zone_transitions.csv
- evidence/experiments/operator_id_stability.csv

## Notes

This validates the low-code UI path for running Metriplane without manual terminal commands after launching the runner/dashboard. The session JSONL is not tracked in git; the path, size, and SHA256 are recorded for reproducibility.
