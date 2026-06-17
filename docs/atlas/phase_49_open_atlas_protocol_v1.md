<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Phase 49: Open Atlas Protocol v1

Value: export schemas and compatibility checks for external reuse of Atlas artifacts.

Run:

```bash
metriplane atlas protocol export --out docs/atlas/protocol_export
metriplane atlas protocol compat --pack configs/domain_packs/assembly_cell --bundle runs/atlas/assembly_cell_missing_tool/evidence_bundles/INC-0001.zip
```

Primary outputs:

- JSON Schema files for Atlas Pydantic models
- protocol index JSON
- compatibility check JSON

What it does not prove:

- It is a local protocol export, not a standards-body specification.
