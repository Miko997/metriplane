<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 43: Edge Appliance Mode

Value: provide local edge-machine checks, resource summaries, retention planning, and autostart documentation hooks.

Run:

```bash
metriplane atlas edge doctor --runs-root runs/atlas
metriplane atlas edge retention-plan --runs-root runs/atlas --keep-last 20
metriplane atlas edge bundle --runs-root runs/atlas --out runs/atlas/edge_bundle.json
```

Primary outputs:

- Edge doctor JSON
- Retention plan JSON
- Edge bundle JSON

What it does not prove:

- It is not a hardware certification, installed appliance image, or 30-minute soak result.
