<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Run the Generated Regression Check

The repository and CLI retain the immutable `test` command name:

```bash
metriplane atlas test \
  /tmp/metriplane-softwarex-atlas/regression_tests/INC-0001.yaml \
  --json
```

Expected result:

```json
{
  "errors": [],
  "pass": true,
  "schema_version": "metriplane.atlas.regression_result.v1",
  "test_id": "missing_tool_caused_delay_INC-0001"
}
```

A pass confirms that the preserved replay condition still produces the selected
expected event and incident fields. It does not establish remediation or general
robot correctness.
