<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Information-loss statement

## Retained information

The synthetic profile retains only:

- exact relative integer-nanosecond evaluation time derived from declared
  message-header time;
- explicit material and tool identity;
- transformed world-frame X/Y position in metres;
- adapter-derived zone under one frozen operator polygon;
- provenance needed to reproduce the transform and materialization.

## Discarded or excluded information

| Source information | Treatment | Consequence |
| --- | --- | --- |
| Transformed world Z | Discarded; normalized Z set to `0.0` | No height or 3D placement claim |
| Pose orientation | Validated, then discarded | No orientation claim |
| Static transform quaternions and translations | Used for transform, retained in provenance, absent from normalized frames | Portable state cannot reconstruct the complete source message stream |
| MCAP channel and schema IDs | Provenance only | No claim that container IDs are physical identities |
| MCAP `log_time` | Provenance only | No physical-time claim from bag logging |
| MCAP `publish_time` | Provenance only | No transport-time claim from evaluation |
| Source message sequence | Structural validation only | No elapsed-time or entity-identity inference from order |
| Outcome fields | Excluded | No source success, result, alarm, action, or annotation semantics |
| ROS type support outside three exact embedded schemas | Unsupported | No arbitrary ROS message claim |
| Dynamic TF, interpolation, carry-forward, synchronization tolerance | Unsupported | No general TF2 or asynchronous-stream claim |
| Original MCAP and schema bytes | Excluded from portable fixture | Portable evaluation cannot replay the source container |

The output is a position-only planar evaluation input. It is not a lossless ROS
recording conversion and cannot establish physical accuracy, calibration
validity, dynamics, simulator realism, or robot-control correctness.
