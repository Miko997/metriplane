<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 39: TwinVerify USD / Isaac Replay

Value: export zones, asset motion samples, and incident annotations into a simple USDA scene for downstream visual replay.

Run:

```bash
metriplane atlas twinverify export-usd --run-dir runs/atlas/assembly_cell_missing_tool
```

Primary output:

- `twinverify_replay.usda`

What it proves:

- Atlas can write a deterministic USDA artifact from replayed planar state.

What it does not prove:

- It does not claim Isaac/Omniverse latency, physics fidelity, or certified safety behavior.
