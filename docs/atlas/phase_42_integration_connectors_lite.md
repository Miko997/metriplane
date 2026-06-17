<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 42: Integration Connectors Lite

Value: export run artifacts into basic CSV and read-only payloads for downstream systems.

Run:

```bash
metriplane atlas connectors export --run-dir runs/atlas/assembly_cell_missing_tool
```

Primary outputs:

- `connectors/events.csv`
- `connectors/incidents.csv`
- `connectors/rest_snapshot.json`
- `connectors/webhook_payload.json`
- `connectors/mqtt_topics.json`

What it does not prove:

- It does not write to MES, ERP, PLC, robot, MQTT, or webhook endpoints by default.
