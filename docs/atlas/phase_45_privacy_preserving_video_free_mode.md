<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 45: Privacy-Aware Video-Free Mode

Value: keep the default evidence path based on derived state and reports, without raw video.

Run:

```bash
metriplane atlas privacy report --run-dir runs/atlas/assembly_cell_missing_tool --out runs/atlas/assembly_cell_missing_tool/privacy_report.json
metriplane atlas privacy pseudonymize --run-dir runs/atlas/assembly_cell_missing_tool --out runs/atlas/assembly_cell_missing_tool_proxy
```

Primary outputs:

- `privacy_report.json`
- pseudonymized proxy run directory and `privacy_metadata.json`

What it does not prove:

- It is a technical guard and report, not legal compliance advice.
- Deterministic pseudonyms are correlatable and may be guessable. They are not
  anonymous data. Review exported fields before sharing them.
