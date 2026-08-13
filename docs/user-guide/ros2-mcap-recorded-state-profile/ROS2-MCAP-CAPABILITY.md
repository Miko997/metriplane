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
| Anti-taint | Optional outcome stream excluded from normalized state and Atlas rules |
| Dependencies | MCAP conversion dependencies isolated from the ordinary wheel |
| Adapter freeze | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |
| Source | 28,735 bytes; SHA-256 `c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99` |
| Frozen config | SHA-256 `a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962` |
| Adapter lock | SHA-256 `864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6` |
| Capability record file | SHA-256 `18b2ceb08568aaf3975d3bdf87354d182d93551625f5e8b59a25cd4aa36ba27d` |
| Canonical capability fingerprint | `3bb37c0457a945fbea166e339d57c373e8251620f3a90ec3a02992fec7b01db7` |
| Shared normalized session | SHA-256 `4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8` |

Even after the schema, conversion, portability, and evidence gates pass, the SDK
assessment must report that this record is not permitted as external-source
evidence. Determinism cannot change its evidence class.

## Result

The isolated adapter suite passes 101 tests. Three clean conversions from the
exact frozen inputs are byte-equivalent. The finalized incident fixture
fingerprint is
`79d1061df5e4f8880f29ead31de3dfac8adae5cf52fbe269513cb6beeb67ae31`.
The control fingerprint is
`559f9c803da6514c82c4ee83c2b925d505be88db2a57582daf7e1d82ec68db42`.

The record remains synthetic-format-engineering evidence and is never permitted
as external-source evidence. Exact-head public workflow results remain a
separate readiness gate.
