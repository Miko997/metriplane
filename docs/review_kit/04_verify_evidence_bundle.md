<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Verify Evidence Bundle

```bash
metriplane atlas bundle verify \
  /tmp/metriplane-softwarex-atlas/evidence_bundles/INC-0001.zip
```

Expected result:

```json
{
  "errors": [],
  "pass": true,
  "schema_version": "metriplane.atlas.bundle_verifier.v1"
}
```

Bundle verification checks required contents, schema, checksums, and incident
event references. It establishes local archive structure and integrity; it is
not physical validation, certification, or a general malware scan.
