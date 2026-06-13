# Sentinel Mode

Metriplane Sentinel is a **non-invasive physical-space auditor**. It watches object
traces, applies [spatial contracts](contracts.md), emits incidents, and creates evidence
**without modifying robot or machine controller code**.

## What it is

- An external observer / shadow auditor over camera-derived object states.
- A runtime preset that loads object metadata, contracts, and the incident engine.
- A producer of run summaries and evidence artifacts.

## What it is not

- Not a robot controller. `control_enabled` is always `false` and cannot be set true in v1.
- Not a certified safety system.
- Not dependent on robot integration or machine-controller access.

## Run a replay demo (no cameras)

```bash
metriplane sentinel run \
  --config configs/sentinel_demo.yaml \
  --run-id sentinel_demo_001 \
  --runs-dir ~/metriplane-runs
```

Output:

```text
mode=shadow_auditor control_enabled=False run_id=sentinel_demo_001
objects_tracked=3 active_alerts=2 open_incidents=2 health=OK
summary: ~/metriplane-runs/sentinel_demo_001/sentinel_summary.json
```

Inspect the summary:

```bash
metriplane sentinel status ~/metriplane-runs/sentinel_demo_001
```

```json
{
  "phase": 17,
  "mode": "shadow_auditor",
  "control_enabled": false,
  "run_id": "sentinel_demo_001",
  "contract_id": "sentinel_demo_warehouse",
  "frames_processed": 9,
  "objects_tracked": 3,
  "alerts_total": 2,
  "incidents_total": 2,
  "health": "OK",
  "pass": true
}
```

## Config

```yaml
replay_input: tests/fixtures/contracts/sentinel_minimal_session.jsonl

sentinel:
  enabled: true
  mode: shadow_auditor
  contracts_file: configs/contracts/sentinel_demo.yaml
  objects_file: configs/objects.example.yaml
  export_summary: true
  api_enabled: true
  fail_fast_on_contract_error: true
```

If the contract file is missing: with `fail_fast_on_contract_error: true` the runtime
refuses to start; with `false` it marks health `DEGRADED` and continues without contracts.

## Evidence layout

```text
<runs-dir>/<run-id>/sentinel_summary.json
evidence/experiments/sentinel_runtime_001.md
evidence/experiments/sentinel_runtime_001.json
```

## Limitations

- This release runs Sentinel over replay sessions. Live in-runtime integration into the
  camera pipeline is deferred so the existing perception path stays untouched.
- Incident counts are recomputed from the full alert stream (fine at demo scale).
