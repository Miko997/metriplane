<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Clock decision

## Evaluation clock

| Property | Value |
| --- | --- |
| Authority | `geometry_msgs/msg/PoseStamped.header.stamp` |
| Domain | Declared synthetic `ROS_TIME` |
| Representation | Integer nanoseconds |
| Epoch | Synthetic declared source domain |
| First source time | 1,000,000,000 ns |
| Period | 100,000,000 ns |
| Frame count | 60 |
| Normalized mapping | Subtract the first source timestamp; write `ts_sim_ns` and exact seconds in `ts` |
| Monotonicity | Strictly increasing |

The domain declaration is valid only because Metriplane authors the synthetic
recording and its clock. It does not transfer to an external ROS recording.

## Container times

For each dynamic message:

- MCAP `publish_time = header.stamp + 1,000,000 ns`;
- MCAP `log_time = header.stamp + 2,000,000 ns`.

These relationships are verified. Publish time remains transport provenance.
Log time remains container provenance. Neither substitutes for message time.

The static TF message precedes dynamic state and uses separately frozen MCAP
times. Its zero message stamp means timeless only under the explicit synthetic
static-transform convention.

## Rejection policy

Conversion rejects missing, default, reordered, duplicated, nonmonotonic, mixed,
or unexpected timestamps. It rejects any disagreement between required dynamic
streams, any publish/header/log relationship drift, nominal-rate-only timing,
file-order timing, or substitution of MCAP time for the declared evaluation
clock.

No order-only support exists. No cadence is synthesized from topic frequency.
