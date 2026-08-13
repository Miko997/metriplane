<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Bounded ROS 2 and MCAP recorded-state profile

## Result

**PARTIAL: synthetic format engineering only.**

Three credible public ROS 2 recordings stored as MCAP were audited against the
same fail-closed source gates used by the existing external-source process. None
passed every gate. No external recording was selected, converted, or used as
compatibility evidence.

The repository instead contains a Metriplane-authored deterministic recording
that exercises a narrow profile:

`metriplane.ros2_mcap_recorded_state.v1`

It uses explicitly configured `PoseStamped` channels, one `/tf_static` chain,
message-header time in a declared synthetic `ROS_TIME` domain, exact-time
complete snapshots, and no carry-forward or interpolation. The synthetic source
is labeled everywhere:

`FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE`

This result does not change the source-family matrix decision for ROS 2 / MCAP +
TF2 from `NOT TESTED`. It does not establish support for ROS 2, rosbag2, MCAP,
TF2, arbitrary topics, automatic discovery, or any external recording.

## Architecture

```text
identified source bytes
  -> explicit source-family decoder
  -> source-adapter capability record
  -> configured field, clock, frame, and identity mapping
  -> deterministic complete-snapshot materialization
  -> External Source Contract v1 bundle
  -> metriplane external validate
  -> metriplane external run
  -> unchanged Atlas
```

The capability record is adapter metadata, not a state model. FrameStateModel
1.0 remains the normalized state format. External Source Contract v1 remains the
fixture protocol. Atlas remains source-neutral.

## Package guide

- [Candidate comparison](SOURCE-CANDIDATES.md)
- [Source audit conclusion](SOURCE-AUDIT.md)
- [Rights matrix](RIGHTS-MATRIX.md)
- [Shared ManiSkill and robomimic adapter evidence](SHARED-ADAPTER-EVIDENCE.md)
- [Source Adapter capability specification](SOURCE-ADAPTER-CAPABILITY.md)
- [ManiSkill post-hoc classification](MANISKILL-CAPABILITY.md)
- [robomimic post-hoc classification](ROBOMIMIC-CAPABILITY.md)
- [Synthetic ROS 2/MCAP classification](ROS2-MCAP-CAPABILITY.md)
- [Recorded-state profile](PROFILE.md)
- [Topic, message, field, and entity mapping](TOPIC-MAPPING.md)
- [Clock decision](CLOCK-DECISION.md)
- [Frame and TF decision](TF-DECISION.md)
- [Completeness and materialization decision](MATERIALIZATION.md)
- [Field provenance](FIELD-PROVENANCE.md)
- [Information loss](INFORMATION-LOSS.md)
- [Negative-test record](NEGATIVE-TESTS.md)
- [Red-team record](RED-TEAM.md)
- [Reproduction guide](REPRODUCE.md)
- [Claims register](CLAIMS.md)
- [Readiness record](READINESS.md)

The exact capability JSON Schema and records live in the isolated
`adapters/source_adapter_sdk/` package. The format adapter and synthetic-source
generator live in `adapters/ros2_mcap/`. Neither package enters the ordinary
Metriplane wheel.

## Frozen boundaries

This work does not modify External Source Contract v1, FrameStateModel 1.0,
Atlas, the existing ManiSkill proof, the robomimic proof, the CALVIN rejection,
or the source-family matrix package. Metriplane remains version `0.3.0`.
