<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane Local Console

`web/dashboard/` is the localhost console for MetriPlane.

It links the major workflows into one UI:

- `index.html` - Start, workflow map, runner health, integrations, and browser-run actions.
- `run.html` - demo replay, live setup handoff, replay checks, and latest run state.
- `operator.html` - camera/profile/calibration/zones/run/evidence setup.
- `runtime.html` - live metric state, telemetry, health, and evidence streams.
- `command_center_live.html` - incidents, replay map, camera trust, forecasts, and assistant.
- `report.html` - plain-language run summary and proof actions.
- `atlas.html` - evidence review, incident archives, regressions, protocol exports, USD replay, and field review artifacts.
- `integrations.html` - ROS 2 checks, USD export, Docker, GPU, and data export controls.

## Quick Start

From the repository root:

```bash
metriplane start
```

Then open:

```text
http://localhost:8088/web/dashboard/index.html
```

The old helper script now delegates to the same launcher:

```bash
./tools/command_center_up.sh
```

Then open:

```text
http://localhost:8088/web/dashboard/index.html
```

## UI Actions

The browser does not execute arbitrary shell commands. Buttons call the local runner on `http://localhost:9000`, which only accepts allowlisted command IDs.

Current UI-runnable actions include:

- Doctor and preflight checks.
- Camera-free latency check, replay determinism, backpressure, and GPU diagnostics.
- Runner-safe stale-process check that keeps the active localhost UI online.
- Demo replay generation for Command Center, Cell Report, Evidence, and simulation export.
- Evidence sample generation under `web/dashboard/atlas_run/`.
- Incident archive verification, regression replay, event query, evidence index build, protocol export, edge readiness, field review kit, audit snapshot, USD replay export, and ROS 2 adapter checks.

Generated evidence artifacts are local and gitignored.
