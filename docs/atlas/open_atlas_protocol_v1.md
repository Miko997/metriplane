<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Open Atlas Protocol v1

Open Atlas Protocol v1 is the JSON/YAML artifact contract used by the local
Cell Black Box implementation.

Schema version strings:

| Artifact | Schema version |
|---|---|
| Asset registry | `metriplane.atlas.asset_registry.v1` |
| Workspace | `metriplane.atlas.workspace.v1` |
| Process model | `metriplane.atlas.process_model.v1` |
| Work order | `metriplane.atlas.work_order.v1` |
| Event | `metriplane.atlas.event.v1` |
| Deviation | `metriplane.atlas.deviation.v1` |
| Incident | `metriplane.atlas.incident.v1` |
| Reality graph | `metriplane.atlas.reality_graph.v1` |
| Evidence bundle | `metriplane.atlas.evidence_bundle.v1` |
| Regression test | `metriplane.atlas.regression_test.v1` |
| Training case | `metriplane.atlas.training_case.v1` |
| Improvement action | `metriplane.atlas.improvement_action.v1` |
| Run manifest | `metriplane.atlas.run_manifest.v1` |

Required evidence bundle files:

```text
manifest.json
incident.json
event_timeline.jsonl
state_segment.jsonl
reality_graph_excerpt.json
process_trace_excerpt.json
configs/assets.yaml
configs/workspace.yaml
configs/process.yaml
reports/cell_truth_report.md
checksums.sha256
replay_command.sh
limitations.md
```

Protocol boundaries:

- Events are derived from replayed planar state streams.
- Asset identity comes from tracked/tagged objects.
- Bundles must verify checksums before use as regression or training evidence.
- Reports and recommendations must carry limitations and avoid causal overclaim.
