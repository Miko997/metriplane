# Sentinel Runtime & Shadow Auditor — Phase 17 Evidence

- phase: 17
- feature: sentinel_runtime
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package additions: metriplane/sentinel/{config,status,runtime,export,cli_runtime}.py
- config_path: configs/sentinel_demo.yaml
- source_mode: replay
- run_id: sentinel_demo_001
- contract_path: configs/contracts/sentinel_demo.yaml
- objects_file: configs/objects.example.yaml

## Commands run

```bash
metriplane sentinel run \
  --config configs/sentinel_demo.yaml \
  --run-id sentinel_demo_001 \
  --runs-dir <runs-dir>

metriplane sentinel status <runs-dir>/sentinel_demo_001
```

## Result

```text
mode=shadow_auditor control_enabled=False run_id=sentinel_demo_001
objects_tracked=3 active_alerts=2 open_incidents=2 health=OK
```

- frames_processed: 9
- alerts_total: 2
- incidents_total: 2
- open_incidents_at_shutdown: 2
- summary_path: <runs-dir>/sentinel_demo_001/sentinel_summary.json
- control_enabled: false (observe-only; cannot be set true in v1)
- pass: true

## Tests

- tests/test_sentinel_config.py (6)
- tests/test_sentinel_status.py (5)
- tests/test_sentinel_export.py (6)

## Design note

`metriplane sentinel run` operates over a replay session JSONL (the backward-compatible
path the phase doc recommends), so the existing camera/detect/map/run_loop pipeline is
untouched. Sentinel orchestrates the Phase 16 contract engine + Phase 05 incident engine
and writes a run summary at shutdown.

## Limitations

- Replay/observer mode; live-runtime integration into run.py is deferred (no risk to the
  existing perception path).
- Shadow auditor only: no robot/machine control. control_enabled is always false.
- Incident counts recomputed from the full accumulated alert stream (O(n²) at demo scale).
