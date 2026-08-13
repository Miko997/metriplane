<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Frame and TF decision

## Declared transform path

```text
world
  -> cell_frame
    -> sensor_frame
      -> configured PoseStamped.position
```

Both dynamic pose streams are expressed in `sensor_frame`. The normalized target
is `world`. One exact `/tf_static` message declares two edges:

| Parent | Child | Translation in metres | Rotation |
| --- | --- | --- | --- |
| `world` | `cell_frame` | `[0.4, -0.2, 0.1]` | yaw +90 degrees as a unit quaternion |
| `cell_frame` | `sensor_frame` | `[0.1, 0.05, -0.1]` | yaw -90 degrees as a unit quaternion |

The converter validates parent and child IDs, order, uniqueness, finiteness,
unit quaternion norms, absence of cycles, and the exact configured path. It
applies child coordinates to parent coordinates in reverse stored-path order.

## Temporal policy

Only static transforms are supported. Zero source timestamp means timeless
static state only because the synthetic profile says so. There is no dynamic TF,
latest-at lookup, interpolation, or extrapolation.

## Transform provenance

Every normalized position is traceable to the source topic, exact
`pose.position` field, `sensor_frame`, both static edges, composition order,
metre unit, `world` target, planar projection, and discarded dimensions.

## Fail-closed behavior

Missing frames, unknown frames, an extra edge, a cycle, an ambiguous path,
conflicting parentage, conflicting static transforms, invalid quaternions,
nonfinite values, reordered edges, dynamic transforms, or a source/target mismatch
rejects conversion.

This bounded implementation is not a general TF2 compatibility claim.
