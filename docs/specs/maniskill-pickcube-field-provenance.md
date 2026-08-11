<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube field provenance and normalization loss

This record defines the complete source-to-normalized field map for the frozen
episode-0 fixture. It is intentionally narrower than the ManiSkill task: Atlas
receives two object identities, planar positions, zone assignments, and fixed
state-index time. It does not receive source outcomes, actions, grasp state,
orientation, or a task-success definition.

## Trust layers

| Layer | Meaning in this fixture |
| --- | --- |
| A — source fact | Bytes and metadata in the pinned demonstration artifacts, plus named state restored through the pinned ManiSkill runtime. |
| B — adapter-derived fact | Deterministic mapping, forward kinematics exposed as `agent.tcp_pose`, XY projection, integer-index time, and zone assignment against separately hashed rules. |
| C — operator rule | The whole target polygon, station association, inclusive boundary, overlap/outside policy, and relative process wait. |
| D — Metriplane result | Atlas events, deviations, incidents, reports, bundles, and regressions. |

## Complete normalized field map

Every field present in `session.jsonl` is listed exactly once. No normalized
field is attributed directly to a Layer-C or Layer-D value.

| Normalized field | Source identity | Deterministic operation | Layer |
| --- | --- | --- | --- |
| `schema_version` | Frozen External Source Contract profile | Emit FrameStateModel `1.0`; no source outcome is consulted. | B |
| `source_backend` | Frozen adapter identity | Emit the stable namespaced external backend identifier. | B |
| `frame_id` | Ordered stored-state index `i`, `0..74` | Copy the index as an integer. | B |
| `ts_sim_ns` | Ordered stored-state index `i` | Compute `i * 50_000_000`; this is the authoritative evaluation clock. | B |
| `ts` | The same ordered stored-state index | Compute `ts_sim_ns / 1_000_000_000`; this is descriptive seconds, not a separately sampled clock. | B |
| `objects[*].id` | Named restored source entity and the hashed one-to-one entity map | Map `cube.pose` to `cube_1`; map the Panda articulation-derived `agent.tcp_pose` to `robot_tcp_1`. | B |
| `objects[*].pos_world` | `traj_0/env_states/actors/cube` restored as `cube.pose`; `traj_0/env_states/articulations/panda` restored and evaluated through `agent.tcp_pose` | Use the pinned ManiSkill/SAPIEN state restoration and Panda forward kinematics, copy world X/Y, and set normalized Z to `0.0`. No action is stepped or integrated. | B |
| `objects[*].zone` | Normalized XY position plus the hashed `domain-pack/workspace.yaml` polygon | Inclusive point-in-polygon assignment; emit `target_xy_region` inside and explicit `outside_workspace` outside; reject overlaps. | B assignment using C definitions |

The TCP forward-kinematics implementation identity is fixed by the adapter
commit, the adapter dependency lock, ManiSkill `3.0.1`, conversion commit
`a4a4f9272ad64b1564035874b605ceb687b63ed8`, and the pinned conversion wheel
SHA-256
`685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a`.

## Layer-C rule map

| Rule | Frozen value | Runtime authority |
| --- | --- | --- |
| Polygon center | `(0.026815734803676605, -0.0019813179969787598)` m | Domain pack only |
| Square half-extent | `0.010000000` m | Domain pack only |
| Boundary / overlap / outside | Inclusive / reject / `outside_workspace` | Domain pack and contract declaration |
| Station | `target_station` associated with `target_xy_region` | Domain pack only |
| Incident wait | `0.20` s from cube presence while TCP is missing | Incident domain pack only |
| Control wait | `0.30` s from cube presence while TCP is missing | Control domain pack only |

The frozen adapter configuration is a deterministic fixture-authoring input.
It does not become Atlas runtime input. The hashed domain pack is the sole
Layer-C runtime authority. Conversion may verify that the polygon center equals
the audited projected goal XY, but it must not derive or alter the polygon from
the goal pose.

## Source annotations and action exclusion

The source contains `reward`, `success`, `terminated`, and `truncated` arrays;
episode metadata also contains elapsed steps, environment/task labels, control
mode, source descriptors, and the registered 50-step RL horizon. A standalone
`failure` array is absent. These facts are inventoried for provenance only and
do not feed any normalized field, rule, event, deviation, incident, or expected
outcome. Actions are also excluded: each stored state is restored independently
and the simulator is never stepped.

Episode selection was outcome-blind within an official corpus that had already
been filtered upstream. The selected episode is therefore not an unbiased
sample of PickCube behavior.

## Information loss

The source cube pose, Panda-derived TCP pose, and goal-site pose are 3D poses.
The normalized fixture deliberately discards:

- source Z for the cube and TCP;
- each complete source quaternion;
- yaw, roll, and pitch, including the numerically well-defined audit yaw;
- angular and linear velocity not represented by the two named pose reads;
- joint/articulation state other than what is used by pinned forward kinematics
  to obtain the named TCP position;
- the goal-site Z and orientation;
- grasp/contact state, reward, success/failure, termination, truncation, and
  other source task annotations;
- the full robot articulation and all source render/camera material.

No discarded orientation is hidden in `ObjectStateModel.extra`, another object,
or an auxiliary stream. The goal pose and projected goal XY are retained only
as inert provenance and rationale.

Consequently this fixture evaluates bounded XY occupancy and timing only. It
does not evaluate 3D placement, orientation, grasp state, source success, or the
official PickCube success condition.
