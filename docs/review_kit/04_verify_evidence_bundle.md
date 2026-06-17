<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Verify Evidence Bundle

```bash
.venv/bin/metriplane atlas bundle verify evidence/paper_v2_0/atlas_run/evidence_bundles/INC-0001.zip
```

Captured output:

- `evidence/paper_v2_0/logs/bundle_verify.txt`
- `evidence/paper_v2_0/artifacts/INC-0001_zip_listing.txt`
- `evidence/paper_v2_0/artifacts/INC-0001_zip.sha256`

Expected result:

```json
{
  "errors": [],
  "pass": true,
  "schema_version": "metriplane.atlas.bundle_verifier.v1"
}
```

Bundle verification checks required contents and checksums. It is not a general
malware scan.
