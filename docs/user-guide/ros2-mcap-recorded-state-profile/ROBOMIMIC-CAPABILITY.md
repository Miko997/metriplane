<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic capability classification

## Classification

This is a **post-hoc external-source classification** of the already-public
frozen robomimic low-dimensional adapter. It does not claim that the historical
adapter emitted a capability record.

Record path:
`adapters/source_adapter_sdk/src/metriplane_source_adapter_sdk/records/robomimic-lowdim.json`

| Property | Classified value |
| --- | --- |
| Frozen adapter | `cfc285a3e757fdf742858b1c4cf685c384d01e8b` |
| Adapter environment | CPython 3.12, Linux x86_64, pinned lock |
| Contract fit | External Source Contract v1 complete-snapshot profile, verified |
| Source identity | Pinned Can Proficient Human `demo_0`, raw and prepared artifacts separately identified |
| Clock | Raw MuJoCo simulation time at 50,000,000 ns source steps; not order-only |
| Coordinates | `robosuite_world`, metres, identity transform, planar XY projection |
| Stable entities | `can_1`, `robot_tcp_1` |
| Completeness | Two known entities per frame; omissions and unknown state rejected; no carry-forward |
| Determinism | Three clean conversions, byte-identity comparison |
| Portability | Source dependencies absent from fixture evaluation; Ubuntu/macOS and Python 3.12/3.13 evidence |
| Semantics | One bounded operator-authored planar arrival and required-presence timing path |

The record preserves the raw/prepared distinction. Prepared observations remain
prepared fields even though the position fields were independently witnessed
against raw state and model evidence.

## Limits

The classification covers one 118-frame trajectory, one operator, and one
position-only rule. It does not establish general robomimic or HDF5 support,
grasp or controller correctness, physical accuracy, simulator realism,
source-project endorsement, or an independent outside rerun.

The post-hoc record file SHA-256 is
`806624b6b9b8efb37b3e1aa7be08082c43efa864a4a2ff159cbb363866fa35a3`.
Its validated canonical capability fingerprint is
`053b7994edd1f1043ee1b3423ee7de45e83c111c2dcf921482bce8ffb4afa610`.
The classification is frozen in SDK commit
`975fda022962b9f1f6a1b986693557600a320916`.
