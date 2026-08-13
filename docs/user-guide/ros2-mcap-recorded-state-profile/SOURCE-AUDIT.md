<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Source audit conclusion

## Decision

**No external recording selected.**

The candidate audit is frozen in commit
`782712f8b87c5daf237b55101594dcf91abed103` on starting public main
`f8a3a48752101d74f658124e23354f0816e20a21`.

The strongest candidate, the Omega Prime ROS simulation example, contains
explicit object state and TF streams. It still fails closed because its official
artifacts do not declare the semantic domain of the message-header timestamps,
do not pin the simulator and input configuration that generated the recording,
and do not state a recording-specific normalized-derivative rights boundary.

The TUM recording has explicit vehicle state but no TF2 stream or bounded
multi-entity workcell snapshot. The AIT recording contains GNSS and IMU sensor
measurements rather than explicit process-relevant object state. Neither can be
made compliant by guessing frames, deriving pose from raw sensors, treating bag
time as physical time, or inventing an entity model.

## Preserved negative result

The audit therefore establishes:

- three immutable candidate identities;
- three evidence-backed rejection records;
- no external-source adapter input;
- no external-source fixture;
- no external-source Atlas run;
- no ROS 2 or MCAP compatibility claim.

This is the required fail-closed outcome. Parsable storage is not semantic
interoperability.

## Synthetic continuation

Engineering continued with a Metriplane-authored recording so the decoder,
schema checks, CDR parsing, exact header clock, static TF composition,
materialization policy, anti-taint boundary, capability record, and portable
fixture path could be tested without mislabeling an external source.

The synthetic source is not a replacement for an accepted candidate. It cannot
change an external-source decision to `GO`. Reopening requires one external
recording to satisfy every criterion in [READINESS.md](READINESS.md).
