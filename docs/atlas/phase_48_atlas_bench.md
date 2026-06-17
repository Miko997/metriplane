<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 48: Atlas-Bench

Value: run a repeatable benchmark of the Cell Black Box artifact loop.

Run:

```bash
metriplane atlas bench core --out runs/bench/atlas_core_001
```

Primary output:

- `summary.json`

What it proves:

- The demo run, report generation, evidence bundle verification, and generated regression tests pass in one benchmark command.

What it does not prove:

- It is an artifact-integrity benchmark, not a production throughput or tracking-accuracy benchmark.
