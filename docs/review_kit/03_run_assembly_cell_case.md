<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run Assembly-Cell Case

Validate the domain pack:

```bash
metriplane atlas validate-pack configs/domain_packs/assembly_cell
```

Run the replay into a temporary directory:

```bash
metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out /tmp/metriplane-softwarex-atlas \
  --overwrite
```

Expected result: 6 physical events, 1 process deviation, and 1 incident for
missing `torque_driver_1` during the configured process step. The rerun creates
the report, event ledger, incident record, evidence bundle, and generated
regression YAML under `/tmp/metriplane-softwarex-atlas`.

The immutable author-run artifacts included with the release remain under
`evidence/paper_v2_0/atlas_run/`.
