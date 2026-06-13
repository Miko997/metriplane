# Physical Observability

Metriplane 0.2.0 turns calibrated camera state into a measured operating layer
for planar physical spaces. The system remains marker-based and planar, but the
runtime output now carries enough structure to answer operational questions:
what object moved, where it moved, what rule it violated, what evidence was
captured, and how the result can be replayed.

## Layer model

| Layer | Primary files | Purpose |
|---|---|---|
| Metric state | `metriplane/schema.py`, `metriplane/pipeline/`, `metriplane/recording/` | Camera observations mapped into world XY coordinates and recorded as frame state. |
| Object registry | `metriplane/sentinel/registry.py`, `configs/objects.example.yaml` | Converts marker IDs into named assets with types, labels, and tags. |
| Trace store | `metriplane/trace/store.py` | Computes last seen, distance, speed, dwell, and idle summaries from object state. |
| Events and rules | `metriplane/sentinel/events.py`, `metriplane/sentinel/rules.py`, `metriplane/contracts/` | Emits typed operational events and spatial-contract violations. |
| Incidents | `metriplane/sentinel/incidents.py` | Groups related events into operator-reviewable incidents. |
| Evidence | `metriplane/sentinel/bundles.py`, `metriplane/testing/` | Packages incidents into replayable bundles and regression tests. |
| Operator review | `metriplane/runner/command_center_api.py`, `web/dashboard/command_center_live.html` | Presents map state, incidents, traces, trust, and local answers in a read-only UI. |

## Claims

Metriplane can claim measured planar object state, replayable evidence,
contract evaluation, trace summaries, and read-only operational review when the
corresponding tests and evidence artifacts are present in the release tree.

Metriplane does not claim certified safety control, marker-free recognition,
full 3D reconstruction, robot actuation, or cloud dependency in 0.2.0.

## Reproduction path

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
metriplane sentinel run --config configs/sentinel_demo.yaml --run-id sentinel_demo
metriplane command-center export evidence/incidents/INC-DIST-001 --out /tmp/command_center_data.json
metriplane test evidence/incidents/INC-0001
python scripts/audit_evidence.py
```

The release manifest and checksum file provide the provenance boundary for
public claims.
