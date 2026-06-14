<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 38: Nontechnical Dashboard

Value: give a nontechnical reviewer one page for the Cell Black Box report, timeline, incidents, evidence links, training links, and next actions.

Run:

```bash
metriplane atlas dashboard build --run-dir runs/atlas/assembly_cell_missing_tool
```

Primary output:

- `atlas_dashboard.html`

What it proves:

- A replay run can produce a local, static dashboard from the same artifacts used by the evidence bundle and regression test.

What it does not prove:

- It is not a production multi-user web app or raw-video review system.
