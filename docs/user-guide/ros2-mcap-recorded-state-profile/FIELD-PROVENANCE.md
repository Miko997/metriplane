<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Field provenance

## Trust layers

| Layer | Synthetic profile content | Boundary |
| --- | --- | --- |
| A. Source facts | Exact MCAP bytes; embedded schema bytes; channel metadata; pose messages; header stamps and frame IDs; static transforms; MCAP publish/log times; optional outcome messages | Authored source facts for format engineering only, not external evidence |
| B. Adapter-derived | CDR decoding; clock normalization; static transform composition; stable normalized IDs; complete-snapshot join; planar projection; polygon zone assignment | Every operation is explicit, configured, and reproducible |
| C. Metriplane/operator configured | Entity roles; polygon; station; process step; required tool; incident/control waits | Never presented as source truth |
| D. Metriplane derived | Events, deviations, incidents, report, evidence bundle, and regression | Produced only by unchanged Atlas after fixture validation |

Layer D cannot determine Layer B or C. The optional source outcome stream cannot
enter Layer C or D.

## Normalized field map

| Normalized field | Provenance class | Exact basis and derivation |
| --- | --- | --- |
| `schema_version` | Adapter constant | FrameStateModel `1.0` |
| `source_backend` | Adapter constant | Bounded synthetic profile identifier, not a claim about a general backend |
| `frame_id` | Adapter-derived | Contiguous output index after all required exact-time checks pass |
| `ts_sim_ns` | Adapter-derived from source fact | Required `PoseStamped.header.stamp` minus first authoritative header stamp |
| `ts` | Adapter-derived from source fact | Exact `ts_sim_ns / 1_000_000_000` seconds |
| `objects[*].id` | Adapter-derived | Explicit configured source identity to normalized identity mapping |
| `objects[*].pos_world[0:2]` | Adapter-derived from source fact | Decode `pose.position`, compose `sensor_frame -> cell_frame -> world`, retain X/Y |
| `objects[*].pos_world[2]` | Adapter-derived | Explicit planar projection sets normalized Z to `0.0`; source world Z is discarded |
| `objects[*].zone` | Adapter-derived from operator configuration | Inclusive membership in the frozen target polygon, otherwise `outside_workspace` |
| `events` | Contract guard | Always empty in normalized input; source annotations never become events |

## Container provenance

MCAP schema IDs, channel IDs, topic identities, encodings, schema hashes,
`log_time`, and `publish_time` remain conversion provenance. Schema and channel
IDs do not become stable physical entity identities. Log and publish time do not
become evaluation time.

## Excluded outcome inventory

| Source field | Treatment |
| --- | --- |
| `/metriplane/source_outcome.success` | Excluded |
| `/metriplane/source_outcome.result` | Excluded |
| `/metriplane/source_outcome.alarm` | Excluded |
| `/metriplane/source_outcome.action` | Excluded |
| `/metriplane/source_outcome.annotation` | Excluded |

The excluded fields do not affect source selection, identity, time, position,
zone, rules, Atlas events, or incidents.

