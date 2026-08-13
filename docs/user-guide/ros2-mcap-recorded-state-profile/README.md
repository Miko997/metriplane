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

## Frozen identities

| Item | Identity |
| --- | --- |
| Starting public main | `f8a3a48752101d74f658124e23354f0816e20a21` |
| Candidate audit commit | `782712f8b87c5daf237b55101594dcf91abed103` |
| Source Adapter SDK commit | `975fda022962b9f1f6a1b986693557600a320916` |
| ROS 2/MCAP adapter freeze | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |
| Capability schema SHA-256 | `30f42190171f9adcc51387909b738378143821c624187604a6d8d89256f103da` |
| Synthetic source | 28,735 bytes; `c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99` |
| Frozen mapping | `a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962` |
| Adapter lock | `864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6` |
| Shared normalized session | `4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8` |

Three clean conversions were byte-equivalent. Their canonical conversion-tree
digest is
`56a70b440f3105ae01a2913940db664008a829dae05d4442dc610aaa99b80505`.
The incident fixture records `60/4/1/1` for frames, events, deviations, and
incidents. Its evidence bundle verifies and its generated regression passes.
The control records `60/3/0/0`; evidence and regression are not applicable
because it contains no incident.

## Frozen boundaries

This work does not modify External Source Contract v1, FrameStateModel 1.0,
Atlas, the existing ManiSkill proof, the robomimic proof, the CALVIN rejection,
or the source-family matrix package. Metriplane remains version `0.3.0`.
