<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Atlas Domain Pack: Assembly Cell

This is the flagship MetriPlane Cell Black Box demo pack. It models a bounded
single workcell where a kit arrives, a workpiece reaches station A, and a
required torque driver is missing long enough to create a replayable process
deviation.

Run it from a clean checkout:

```bash
metriplane atlas validate-pack configs/domain_packs/assembly_cell
metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out runs/atlas/assembly_cell_missing_tool
```

The output directory contains a physical event ledger, reality graph, process
trace, Cell Truth Report, evidence bundle, generated regression test, training
case, and improvement action.

Scope limits: this pack uses tagged planar object state. It is not a safety
controller, quality authority, marker-free tracker, or worker surveillance
system.
