<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Atlas Domain Packs

Domain packs describe what Atlas should treat as meaningful inside one bounded
cell. A pack consists of:

- `assets.yaml`: tracked object IDs mapped to asset IDs, asset types, labels,
  expected zones/stations, and optional material/tool/work-order fields.
- `workspace.yaml`: cell ID, zones, and stations.
- `process.yaml`: ordered process expectations.
- `work_orders.csv`: optional work-order import.
- `contracts.yaml`: optional claim-boundary and process-contract notes.

Checked-in packs:

| Pack | Purpose |
|---|---|
| `assembly_cell` | Flagship runnable Cell Black Box missing-tool demo. |
| `robot_cell` | Observe-only robot-cell process evidence. |
| `warehouse_lane` | Material-flow evidence for carts, pallets, and totes. |
| `line_clearance` | Traceability evidence for line-clearance review. |
| `training_lab` | Replay-derived training cases without identity claims. |

Validate all packs through:

```bash
metriplane atlas validate-pack configs/domain_packs/assembly_cell
```

The validator checks schema load, duplicate object/asset IDs, station-zone
references, process references to known zones/stations, and required assets.
