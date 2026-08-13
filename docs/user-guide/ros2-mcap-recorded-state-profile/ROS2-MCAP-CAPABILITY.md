<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Synthetic ROS 2/MCAP capability classification

## Classification

This is a **native synthetic-format-engineering classification** of the bounded
adapter candidate. It is not external-source evidence.

The record must use:

- `evidence_classification: synthetic_format_engineering`;
- `subject: candidate_adapter`;
- source classification
  `FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE`.

| Property | Frozen boundary |
| --- | --- |
| Profile | `metriplane.ros2_mcap_recorded_state.v1` |
| Contract fit | External Source Contract v1 complete-snapshot profile |
| Source | One exact Metriplane-authored synthetic MCAP recording |
| Clock | `PoseStamped.header.stamp`, declared synthetic `ROS_TIME`, integer nanoseconds |
| Container times | MCAP publish and log time retained as provenance only |
| Frames | Explicit static `world -> cell_frame -> sensor_frame` chain |
| Entities | Exactly configured material and tool pose streams |
| Completeness | Co-timestamped required state, zero tolerance, no carry-forward |
| Information loss | Source Z and orientation discarded after transform; normalized Z is 0.0 |
| Anti-taint | Exact frozen outcome stream excluded from normalized state and Atlas rules; complete absence exists only in the internal mutation harness |
| Dependencies | MCAP conversion dependencies isolated from the ordinary wheel |
| Original adapter freeze | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |
| Effective hardened adapter freeze | `686c38c2f8ca34439f851b5d62c8f7cd1cfddac8` |
| Source | 28,735 bytes; SHA-256 `c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99` |
| Frozen config | SHA-256 `a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962` |
| Adapter lock | SHA-256 `864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6` |
| Capability record file | SHA-256 `563fca13873a90d79644c9b5f552c3377e6f0143ead46403beb13fa5aa037295` |
| Canonical capability fingerprint | `ef9341324267b53ce94fa17b6eb313c1d839b2062ed26b9c0ee93a046bfe307f` |
| Shared normalized session | SHA-256 `4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8` |

Even after the schema, conversion, portability, and evidence gates pass, the SDK
assessment must report that this record is not permitted as external-source
evidence. Determinism cannot change its evidence class.

## Result

The isolated adapter suite passes 115 tests. A single raw conversion correctly
records determinism as `not_demonstrated`; the finalizer alone promotes the
capability after independently reconstructing and comparing three clean
conversions. Those conversions from the
exact frozen inputs are byte-equivalent. The finalized incident fixture
fingerprint is
`b88fe8731b3d9ed63414b6bd3d4af8be0d68e8259ed6c467fbf9df63e2bece66`.
The control fingerprint is
`2d7b98ffba20bd91b13c8ee311bacf9365b64d8dd5b56b8eaa1898226c3c9062`.

The record remains synthetic-format-engineering evidence and is never permitted
as external-source evidence. The reviewed exact head completed the required
public workflow gates, including all four portable rows; the live pull request
is authoritative for later additive heads.
