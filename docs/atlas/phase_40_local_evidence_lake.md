<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 40: Local Evidence Lake

Value: search and summarize multiple local Atlas runs without cloud or enterprise infrastructure.

Run:

```bash
metriplane atlas lake build --root runs/atlas --db runs/atlas/evidence_lake.sqlite
metriplane atlas lake query --db runs/atlas/evidence_lake.sqlite --table events --type step_delayed
metriplane atlas lake trends --db runs/atlas/evidence_lake.sqlite --out runs/atlas/trends.json
```

Primary outputs:

- SQLite database of runs, events, and incidents.
- Trend summary JSON by cell, event type, and incident type.

What it does not prove:

- It is not an enterprise evidence warehouse or permission system.
