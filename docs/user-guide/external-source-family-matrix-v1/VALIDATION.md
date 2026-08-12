<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Validation record

This living candidate record is completed against the exact PR head. Frozen
source proofs remain authoritative for their own technical identities.

## Required commands

```bash
python docs/user-guide/external-source-family-matrix-v1/validate.py \
  --require-jsonschema --validate-only
python tools/build_external_source_family_matrix.py \
  --require-jsonschema --validate-only
python tools/build_external_source_family_matrix.py \
  --require-jsonschema --out /tmp/matrix-a.zip
python tools/build_external_source_family_matrix.py \
  --require-jsonschema --out /tmp/matrix-b.zip
cmp /tmp/matrix-a.zip /tmp/matrix-b.zip
python -m pytest -q tests/external_sources/test_external_source_family_matrix.py
mkdocs build --strict
```

The official schema check uses `jsonschema==4.25.1`; citation validation uses
`cffconvert==2.0.0`; scoped license checks use `reuse==5.0.2`.

## Candidate results

| Gate | Local result | Exact-head CI result |
| --- | --- | --- |
| JSON syntax and Draft 2020-12 schema | Pass with `jsonschema==4.25.1` | Pending |
| Evidence references and frozen hashes | Pass; 16 unique repository paths verified | Pending |
| Complete SHA-256 inventory | Pass; 17 package entries, excluding the inventory itself | Pending |
| Two byte-identical builds | Pass | Pending |
| Machine-local path and unsupported-claim scan | Pass; 18 package files scanned including the inventory | Pending |
| Frozen fixture inventories | Pass; 52 files across four inventories | Pending |
| Focused publication tests | 8 passed | Pending |
| Full repository tests | 1,096 passed, 2 skipped | Pending |
| Strict documentation | Pass | Pending |
| Citation and scoped REUSE validation | Pass with `cffconvert==2.0.0` and `reuse==5.0.2` | Pending |
| Fresh-wheel Ubuntu/Python 3.12 fixture evaluation | Pass: `75/4/1/1`, `75/3/0/0`, `118/4/1/1`, `118/3/0/0`; incident evidence and regressions reverified | Pending |
| Portable Ubuntu/macOS × Python 3.12/3.13 | Not a local four-platform claim | Pending |
| Normal repository workflows | Not applicable locally | Pending |

The local test environment was Ubuntu with CPython 3.12.13. A local pass is
first-party development evidence; a GitHub-hosted pass is first-party CI
evidence. Neither is an independent rerun. Exact PR-head workflow identities
are recorded in the PR and Linear rather than embedded into their own hashed
input tree.
