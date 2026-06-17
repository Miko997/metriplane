<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Expected Outputs

| Check | Expected |
|---|---|
| Test gate | `580 passed` |
| Deterministic replay | `pass=true`, zero mean/max position diff, zero event mismatches |
| Domain pack validation | `PASS configs/domain_packs/assembly_cell` |
| Atlas run | `events=6 incidents=1` |
| Physical event log | 6 JSONL rows |
| Incident log | 1 JSONL row |
| Evidence bundle | `INC-0001.zip` with 16 files |
| Bundle verification | JSON result with `"pass": true` |
| Regression test | JSON result with `"pass": true` |
| Package build | Wheel and sdist under `dist/` |
| Twine check | Passed with long-description warnings |

The package is deterministic for the checked-in replay inputs. Live-camera,
Docker runtime, and Isaac Sim runtime behavior are outside this review path
unless separate evidence is generated.
