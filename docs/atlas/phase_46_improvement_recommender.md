<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 46: Improvement Recommender

Value: turn repeated evidence into bounded process-improvement suggestions, then compare before/after replay runs.

Run:

```bash
metriplane atlas improvement compare --before-run runs/atlas/before --after-run runs/atlas/after --out runs/atlas/before_after.json
```

Primary outputs:

- `improvement_actions.json`
- before/after comparison JSON

What it does not prove:

- It suggests hypotheses. It does not prove guaranteed causality without real before/after validation.
