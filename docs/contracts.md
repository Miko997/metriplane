<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Spatial Contracts

Metriplane Sentinel can evaluate **spatial contracts** in observer mode. A contract is a
versioned, typed, testable description of physical-space rules. It does not require robot
integration or machine-controller access.

## Why

Physical spaces have informal rules ("do not block the exit lane", "keep carts 0.6 m from
people"). Without a contract language these live in operator memory or ad-hoc code, which
is impossible to test or audit. A contract makes them explicit, typed, versioned, and
replayable.

## Contract file

```yaml
schema_version: "1.0"
contract_id: sentinel_demo_warehouse
name: Sentinel demo warehouse rules
units: meters

subjects:
  human_proxy:
    object_types: [human_proxy]
  movable_assets:
    object_types: [cart, pallet]

rules:
  - id: no_asset_in_exit_lane
    type: forbidden_zone
    subject: movable_assets
    zones: [exit_lane]
    severity: critical
    cooldown_s: 5
```

### Subjects

A subject is a named group of objects. An object matches a subject when it satisfies every
*specified* criterion (an empty subject matches nothing):

| Criterion | Semantics |
|---|---|
| `object_ids` | object_id is in the list (OR) |
| `object_types` | resolved type is in the list (OR) |
| `tags` | object has **all** listed tags |
| `zones` | object's current zone is in the list (OR) |

Object types and tags come from the object registry (`configs/objects.example.yaml`).
Markers without a registry entry resolve to `marker_<id>` with no type.

### Supported rule types

| Type | Required fields | Fires when |
|---|---|---|
| `forbidden_zone` | subject, zones | subject object is in a listed zone |
| `minimum_distance` | subject_a, subject_b, distance_m | two objects closer than distance_m (held for `min_duration_s`) |
| `zone_occupancy_duration` | subject, zones, max_duration_s | object dwells in zone past max_duration_s |
| `speed_limit` | subject, max_speed_mps | object speed exceeds max_speed_mps |
| `missing_object` | subject, missing_after_s | a known object is unseen longer than missing_after_s |
| `forbidden_direction` | subject, zones, allowed_direction | object moves against allowed direction (≥ min_speed_mps) |
| `zone_capacity` | subject, zones, max_count | more than max_count subject objects in a zone |

`cooldown_s` suppresses repeat events for the same entity within the window.

Direction convention (world axes): `left_to_right`=+X, `right_to_left`=−X,
`bottom_to_top`=+Y, `top_to_bottom`=−Y.

## CLI

```bash
# validate a contract
metriplane contracts validate configs/contracts/sentinel_demo.yaml

# run a contract against a replay session and compare to expected events
metriplane contracts test \
  --contract configs/contracts/sentinel_demo.yaml \
  --input tests/fixtures/contracts/sentinel_minimal_session.jsonl \
  --expect tests/fixtures/contracts/sentinel_expected.yaml \
  --objects configs/objects.example.yaml \
  --output result.json
```

Expected output:

```text
contract_id=sentinel_demo_warehouse schema=1.0 rules=4 result=PASS
expected_incidents=2 observed_incidents=2 false_positives=0 missed=0
```

## How contracts differ from robot control

Contracts are **configuration, not executable code**. There is no `eval`, templating, or
shell execution. The engine observes object traces and emits violation events; it never
controls a robot or machine. See [Sentinel mode](sentinel.md).

## Limitations

- Pairwise `minimum_distance` is O(n²) within matched subjects.
- The contract engine is a downstream layer; it does not modify detection, mapping, or
  camera code.
