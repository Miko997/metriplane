<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 44: Multi-Cell Rollout

Value: compare independent local Cell Black Box runs by `cell_id`.

Run:

```bash
metriplane atlas multicell compare --root runs/atlas --out-json runs/atlas/multicell.json --out-md runs/atlas/multicell.md
```

Primary outputs:

- Multi-cell JSON summary
- Multi-cell Markdown summary

What it does not prove:

- It does not implement production cell-level permissions or cross-site authorization.
