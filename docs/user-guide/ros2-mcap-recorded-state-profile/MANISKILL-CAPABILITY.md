<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill capability classification

## Classification

This is a **post-hoc external-source classification** of the already-public
frozen ManiSkill PickCube adapter. It does not claim that the historical adapter
emitted a capability record.

Record path:
`adapters/source_adapter_sdk/src/metriplane_source_adapter_sdk/records/maniskill-pickcube.json`

| Property | Classified value |
| --- | --- |
| Frozen adapter | `95d1134d9fb9273318c552c507952f1c5c26877e` |
| Adapter environment | CPython 3.12, Linux x86_64, pinned lock |
| Contract fit | External Source Contract v1 complete-snapshot profile, verified |
| Source identity | Pinned ManiSkill PickCube episode and separately identified source artifacts |
| Clock | Stored environment-state index with declared 50,000,000 ns simulation step; not order-only |
| Coordinates | `maniskill_world`, metres, identity transform, planar XY projection |
| Stable entities | `cube_1`, `robot_tcp_1` |
| Completeness | Two known entities per frame; omissions and unknown state rejected; no carry-forward |
| Determinism | Three clean conversions, byte-identity comparison |
| Portability | Source dependencies absent from fixture evaluation; Ubuntu/macOS and Python 3.12/3.13 evidence |
| Semantics | One bounded operator-authored planar arrival and required-presence timing path |

The record points to the frozen manifests, proof record, rights record, field
provenance, red-team record, adapter commit, and workflow evidence. It does not
modify or regenerate the frozen proof.

## Limits

The classification covers one official episode from an upstream
success-filtered corpus. It does not establish general ManiSkill support,
conversion portability across platforms, physical accuracy, simulator realism,
source-project endorsement, or an independent outside rerun.

The exact capability-record fingerprint is recorded only after the SDK schema
and classification files reach their public freeze point.

