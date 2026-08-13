<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ROS 2/MCAP recorded-state profile v1

## Identity and scope

Profile identifier: `metriplane.ros2_mcap_recorded_state.v1`

This profile is implemented only against one Metriplane-authored synthetic
recording. It describes a narrow accepted structure. It is not a declaration of
general ROS 2, rosbag2, MCAP, or TF2 support.

## Required input declaration

A mapping must bind every consumed value through this complete chain:

```text
source artifact
  -> MCAP channel
  -> exact ROS message schema and schema hash
  -> topic
  -> exact field path
  -> stable source entity identity
  -> normalized entity ID
  -> source frame
  -> target frame
  -> authoritative unit
  -> authoritative clock field and domain
  -> transform and materialization policy
  -> field-provenance classification
```

No topic, schema, frame, entity, or field is discovered semantically. Unknown,
renamed, duplicated, retyped, or unexpectedly encoded input fails closed.

## Supported synthetic input

| Role | Exact value |
| --- | --- |
| MCAP profile | `ros2` |
| Message encoding | `cdr` |
| Schema encoding | `ros2msg` |
| Dynamic state type | `geometry_msgs/msg/PoseStamped` |
| Transform type | `tf2_msgs/msg/TFMessage` |
| Transform topic | `/tf_static` |
| Material state | `/metriplane/material_pose` |
| Tool state | `/metriplane/tool_pose` |
| Excluded annotations | Exact frozen `/metriplane/source_outcome` stream; complete absence is internal anti-taint-test input only |
| Required dynamic frames | 60 |
| First source timestamp | 1,000,000,000 ns |
| Period | 100,000,000 ns |
| Evaluation duration | 5.9 s from normalized 0.0 s through 5.9 s |

The decoder verifies MCAP magic, structure, checksums, profile, writer identity,
schemas, schema bytes, channels, channel metadata, encodings, topics, message
counts, sequences, CDR payloads, finite values, quaternions, clocks, frames,
and the exact complete-snapshot join.

## Message schema identities

The recording embeds the exact flattened ROS 2 message definitions used for
decoding:

| Schema | SHA-256 |
| --- | --- |
| `geometry_msgs/msg/PoseStamped` | `a80b6e20113061c6a8cbd4a5e623d7e1aa54d68deebbc3e69738ff1e502daae8` |
| `tf2_msgs/msg/TFMessage` | `e9121b91448577bf5075f9b1a00b8afcaeeab85422497da524a0cbef10896502` |
| `metriplane_msgs/msg/SourceOutcome` | `954f2e44e4c2e2e2654f9de20dc68de75f5a219d2d591c2fde40ac93d5366a80` |

These identities are frozen by adapter commit
`686c38c2f8ca34439f851b5d62c8f7cd1cfddac8`. A mutable local ROS
installation never defines their semantics.

No arbitrary Python object deserialization, runtime ROS graph, rosbag2 process,
or source launch file is used.

## Clock

`PoseStamped.header.stamp` is the sole evaluation clock. Its declared domain is
synthetic `ROS_TIME`, represented as integer nanoseconds. It is strictly
monotonic and exactly periodic for this recording.

MCAP `publish_time` equals header time plus 1,000,000 ns. MCAP `log_time` equals
header time plus 2,000,000 ns. These values are transport and container
provenance only. Neither becomes evaluation time.

## Frames and transforms

Both poses declare `sensor_frame`. One `/tf_static` message supplies exactly:

```text
world -> cell_frame -> sensor_frame
```

Both transforms are finite, unit-quaternion, nonconflicting, acyclic, and
declared timeless by the synthetic profile's zero-stamp convention. Positions
are transformed from `sensor_frame` to `world` by applying the stored edges in
reverse path order.

Dynamic TF, latest-at lookup, interpolation, and extrapolation are unsupported.

## Units and projection

Channel metadata and the frozen mapping declare positions in metres. The
adapter applies the static transform chain, copies world X/Y into normalized
state, sets normalized Z to `0.0`, and omits orientation. This is a declared
position-only planar projection.

## Identity

Exactly two configured source identities map one-to-one to normalized IDs and
Atlas assets:

- `synthetic_material_1` to `material_1`;
- `synthetic_tool_1` to `tool_1`.

Topic names alone are not treated as identities. The binding also includes the
channel metadata, message type, field path, source frame, unit, and mapping
record. Unknown or duplicate mappings fail closed.

## Complete snapshots

`/metriplane/material_pose` is the sampling trigger. Both required pose streams
must have exactly one valid message at the same authoritative header timestamp.
Synchronization tolerance is zero. There is no carry-forward, nearest-neighbor
selection, interpolation, resampling, extrapolation, or inferred absence.

A missing, duplicated, stale, partial, or invalid required observation rejects
the recording. It never emits physical absence.

## Annotation boundary

The frozen outcome stream contains fields named `success`, `result`, `alarm`,
`action`, and `annotation`. It is excluded from normalized state, operator
rules, Atlas events, and incidents. Public inspection and conversion accept
only the exact complete frozen stream. An internal anti-taint harness constructs
value mutations and a complete-absence variant solely to prove semantic
invariance; those variants still fail public source identity. Partial, renamed,
retyped, reordered, deleted, or malformed public input fails closed.

Outcome-only mutation and deletion tests demonstrate that normalized state and
Atlas semantics do not depend on the excluded values.

## Publication safety

On the frozen Linux x86_64 conversion platform, source, config, lock, candidate,
parent, and published-output identities are descriptor-bound and rechecked.
Publication uses atomic no-clobber rename to a fresh absent destination; links,
candidate replacement, late destination creation, existing output replacement,
or a post-transition input change fails closed and rolls back. This is a
point-in-time guarantee. Long-term custody against a same-privilege writer
requires external access separation or immutability.

## Portable output

Conversion produces an External Source Contract v1 fixture. Portable evaluation
uses only the ordinary Metriplane wheel and its normal runtime dependencies. The
fixture excludes MCAP bytes, ROS runtime, rosbag2, MCAP libraries, source schemas,
and adapter dependencies.

## Prohibited input paths

The profile rejects automatic topic discovery, arbitrary topics, arbitrary
schemas, unknown encodings, dynamic TF, multiple transform paths, interpolation,
extrapolation, carry-forward, tolerance-based synchronization, nominal-rate-only
timing, MCAP-time substitution, raw sensor interpretation, source outcome truth,
and any source requiring a core or Atlas change.
