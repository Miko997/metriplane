<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Shared adapter evidence

The capability schema was derived from the two existing successful adapters,
not from the synthetic ROS profile. This table records the repeated
responsibilities that justified the common layer.

| Responsibility | ManiSkill PickCube | robomimic low-dimensional | Shared class |
| --- | --- | --- | --- |
| Adapter identity and version | `org.metriplane.maniskill_pickcube`, `1.0.0` | `org.metriplane.robomimic_lowdim`, `1.0.0` | C |
| Implementation commit | `95d1134d9fb9273318c552c507952f1c5c26877e` | `cfc285a3e757fdf742858b1c4cf685c384d01e8b` | C |
| Isolated environment | CPython 3.12, Linux x86_64, pinned lock | CPython 3.12, Linux x86_64, pinned lock | C |
| Exact source identity | Pinned PickCube HDF5 and metadata, exact episode | Pinned raw and prepared Can HDF5, exact `demo_0` | A |
| Source hashes | Artifact identities recorded in frozen manifests | Raw and prepared SHA-256 values recorded separately | A |
| Source family | ManiSkill trajectory and restored environment state | robomimic low-dimensional HDF5 with raw-witnessed prepared observations | A |
| Rights | Source, derived fixture, adapter, assets, and rules separated | Code, dataset, prepared/normalized derivative, assets, and rules separated | A |
| Clock authority | Stored-state index with declared 50,000,000 ns source step | Raw MuJoCo simulation time at 50,000,000 ns steps | B |
| Clock mapping | Fixed step to integer `ts_sim_ns` | Raw seconds to integer `ts_sim_ns` | B |
| Coordinate frame and unit | `maniskill_world`, metres | `robosuite_world`, metres | B |
| Transform and projection | Identity world transform, planar XY | Identity world transform, planar XY | B |
| Stable source identity | Named cube and Panda TCP restoration | Named Can and robot TCP prepared fields witnessed against raw state | B |
| Normalized identity | `cube_1`, `robot_tcp_1` | `can_1`, `robot_tcp_1` | B |
| Raw/prepared/derived boundary | Referenced source, restored pose, projected state | Raw state/model, prepared observation, projected state | A/B |
| Field provenance | Complete source or restored-field map | Complete prepared-field and raw-witness map | B |
| Complete snapshots | Two known entities per evaluated frame | Two known entities per evaluated frame | B |
| Missing-state policy | Reject omission or unknown state | Reject omission or unknown state | B |
| Information loss | Z, orientation, velocity, articulation, actions, contacts, outcomes, rendering | Z, orientation, velocity, articulation, actions, contacts, outcomes, images, `next_obs`, model detail | B |
| Anti-taint | Rewards, success, termination, truncation, and actions excluded | Actions, rewards, dones, `next_obs`, controller/user/intervention and mask fields excluded | B |
| Deterministic conversion | Three clean conversions, byte identity | Three clean conversions, byte identity | C |
| Portable evaluation | Source dependencies absent; four OS/Python rows | Source dependencies absent; four OS/Python rows | C |
| Supported semantics | One bounded operator-authored planar arrival and required-presence timing path | One bounded operator-authored planar arrival and required-presence timing path | C |
| Prohibited semantics | Source task success, grasp/controller correctness, 3D/physical/safety/general-family claims | Source outcome, grasp/controller correctness, 3D/physical/safety/general-family claims | C |

Class A is an existing Contract v1 requirement. Class B is an existing contract
field with reusable validation semantics. Class C is a repeated adapter
responsibility consolidated as a capability gate. ROS topics, MCAP channels,
message schemas, and TF paths are Class D and remain outside the common schema.

