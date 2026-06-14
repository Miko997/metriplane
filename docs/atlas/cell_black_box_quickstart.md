<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Cell Black Box Quickstart

The checked-in flagship demo is an assembly cell where a required torque driver
is absent long enough to delay a process step.

```bash
metriplane atlas validate-pack configs/domain_packs/assembly_cell
metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out runs/atlas/assembly_cell_missing_tool
```

Expected local output:

- `physical_event_log.jsonl`: append-only Atlas event ledger.
- `reality_graph.json`: asset, zone, station, process, event, and incident graph.
- `process_trace.json`: completed steps and active process state.
- `cell_truth_report.md` and `.html`: nontechnical report.
- `evidence_bundles/INC-0001.zip`: portable incident evidence bundle.
- `regression_tests/INC-0001.yaml`: generated physical regression test.
- `training_cases/INC-0001.md`: training case generated from the incident.
- `improvement_actions.json`: process-improvement suggestion with caveats.
- `atlas_dashboard.html`: nontechnical dashboard with timeline, incidents, evidence links, and actions.
- `twinverify_replay.usda`: simple USDA export with zones, asset motion samples, and incident annotations.
- `privacy_report.json`: video-free and identity-field scan report.
- `connectors/`: CSV exports plus read-only REST/webhook/MQTT payload artifacts.

Useful reviewer commands:

```bash
metriplane atlas bundle verify runs/atlas/assembly_cell_missing_tool/evidence_bundles/INC-0001.zip
metriplane atlas test runs/atlas/assembly_cell_missing_tool/regression_tests/INC-0001.yaml
metriplane atlas query events --run-dir runs/atlas/assembly_cell_missing_tool --asset torque_driver_1
metriplane atlas bench core --out runs/bench/atlas_core_001
metriplane atlas lake build --root runs/atlas --db runs/atlas/evidence_lake.sqlite
metriplane atlas protocol export --out runs/atlas/open_atlas_protocol
```

The demo is intentionally small and deterministic. It is meant to make the
evidence loop inspectable in seconds, not to claim factory-wide autonomy.
