<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run Assembly-Cell Case

Validate the domain pack:

```bash
.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell
```

Run the replay:

```bash
.venv/bin/metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out evidence/paper_v2_0/atlas_run \
  --overwrite
```

Captured output:

- `evidence/paper_v2_0/logs/atlas_validate_pack.txt`
- `evidence/paper_v2_0/logs/atlas_assembly_cell_run.txt`
- `evidence/paper_v2_0/atlas_run/cell_truth_report.md`
- `evidence/paper_v2_0/atlas_run/cell_truth_report.html`
- `evidence/paper_v2_0/atlas_run/atlas_dashboard.html`
- `evidence/paper_v2_0/atlas_run/physical_event_log.jsonl`
- `evidence/paper_v2_0/atlas_run/reality_graph.json`
- `evidence/paper_v2_0/atlas_run/process_trace.json`

Expected result: 6 physical events and 1 incident for missing
`torque_driver_1` during the required process step.
