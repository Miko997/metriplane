<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 45: Privacy-Preserving Video-Free Mode

Value: keep the default evidence path based on derived state and reports, without raw video.

Run:

```bash
metriplane atlas privacy report --run-dir runs/atlas/assembly_cell_missing_tool --out runs/atlas/assembly_cell_missing_tool/privacy_report.json
metriplane atlas privacy anonymize --run-dir runs/atlas/assembly_cell_missing_tool --out runs/atlas/assembly_cell_missing_tool_proxy
```

Primary outputs:

- `privacy_report.json`
- anonymized proxy run directory

What it does not prove:

- It is a technical guard and report, not legal compliance advice.
