<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Expected Outputs

## Core artifact path

| Check | Expected |
|---|---|
| Doctor | Passes with at most non-blocking warnings |
| Deterministic replay | `pass=true`; 24 frames; 72 object pairs; zero mean/max position difference; zero event mismatches |
| Domain pack validation | `PASS configs/domain_packs/assembly_cell` |
| Atlas run | 6 physical events, 1 process deviation, 1 incident |
| Evidence bundle | `INC-0001.zip` with 16 files |
| Bundle verification | JSON result with `"pass": true` |
| Generated regression check | JSON result with `"pass": true` |

## Included author-run maintainer evidence

The checked-in paper evidence package records `580 passed` in the captured
Ubuntu 24.04 / Python 3.12.3 author environment. Reproducing that full gate is
separate from the camera-free core path; see
`docs/review_kit/09_full_maintainer_gate.md`.

The demonstrated results are limited to the checked-in replay inputs. Live
camera, Docker production runtime, and Isaac Sim runtime behavior are outside
this review path unless separate evidence is generated.
