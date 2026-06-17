<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run Regression Test

```bash
.venv/bin/metriplane atlas test evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml --json
```

Captured output:

- `evidence/paper_v2_0/logs/regression_test.json`
- `evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml`

Expected result:

```json
{
  "errors": [],
  "pass": true,
  "schema_version": "metriplane.atlas.regression_result.v1",
  "test_id": "missing_tool_caused_delay_INC-0001"
}
```
