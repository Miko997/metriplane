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

| Property | Declared boundary |
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

Even after the schema, conversion, portability, and evidence gates pass, the SDK
assessment must report that this record is not permitted as external-source
evidence. Determinism cannot change its evidence class.

## Pending immutable identities

The final adapter implementation commit, source byte identity, dependency-lock
hash, capability fingerprint, normalized session hash, fixture fingerprints, and
workflow identities are recorded only after the adapter subtree is frozen and
the generated outputs are final. [READINESS.md](READINESS.md) tracks those
pending values.

