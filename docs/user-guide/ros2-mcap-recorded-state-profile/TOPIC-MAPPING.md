<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Topic, message, field, and entity mapping

## Consumed mapping

| MCAP topic | Message schema | Exact field | Source identity | Normalized ID | Source frame | Target frame | Unit | Clock role | Completeness role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/metriplane/material_pose` | `geometry_msgs/msg/PoseStamped` | `pose.position` | `synthetic_material_1` from channel metadata plus frozen mapping | `material_1` | `sensor_frame` | `world` | m | `header.stamp` is authoritative | Sampling trigger and required dynamic state |
| `/metriplane/tool_pose` | `geometry_msgs/msg/PoseStamped` | `pose.position` | `synthetic_tool_1` from channel metadata plus frozen mapping | `tool_1` | `sensor_frame` | `world` | m | Must exactly equal trigger `header.stamp` | Required dynamic state |
| `/tf_static` | `tf2_msgs/msg/TFMessage` | `transforms[*]` | Exact configured parent and child frame IDs | Not an entity | Per transform | `world` | m and unit quaternion | Zero stamp means timeless only under this synthetic declaration | Required static state |

## Excluded mapping

| MCAP topic | Message schema | Fields | Treatment |
| --- | --- | --- | --- |
| `/metriplane/source_outcome` | `metriplane_msgs/msg/SourceOutcome` | `success`, `result`, `alarm`, `action`, `annotation` | Explicitly excluded from normalized state, process rules, events, and incidents |

`header.stamp` and `header.frame_id` on the excluded stream are checked only to
authenticate the exact optional stream structure. They do not feed normalized
time or spatial state.

## Entity authority

Every process-relevant normalized object has one explicit source binding and one
Atlas asset binding. Array order is never entity identity. Topic naming is
insufficient on its own. Unknown entities, aliases, duplicated source
identities, and duplicated normalized IDs reject conversion.

## Operator layer

The polygon, station, roles, required-asset rule, and waits are separate
Metriplane-authored configuration. None is extracted from a source annotation,
topic name, frame ID, or outcome field.

