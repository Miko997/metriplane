<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 41: Atlas Query Language v1

Value: answer common operational questions with repeatable filters and saved queries.

Run:

```bash
metriplane atlas query events --run-dir runs/atlas/assembly_cell_missing_tool --asset torque_driver_1
metriplane atlas query saved --run-dir runs/atlas/assembly_cell_missing_tool --query-id delayed_steps --json
metriplane atlas query list-saved
```

Primary input:

- `configs/atlas/saved_queries.yaml`

What it does not prove:

- It is not a general graph query language or natural-language query engine.
