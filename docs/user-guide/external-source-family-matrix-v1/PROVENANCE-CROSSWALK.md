<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Raw, prepared, derived, and normalized provenance crosswalk

This document keeps source facts, conversion products, normalized facts, and
operator-authored semantics separate. A blank implementation stage is not
filled by analogy to another source family.

| Source family | Decision | Raw or referenced source | Prepared boundary | Adapter-derived boundary | Normalized and evaluation boundary |
| --- | --- | --- | --- | --- | --- |
| ManiSkill | **GO** | External PickCube-v1 ZIP containing the pinned HDF5 trajectory and JSON metadata at dataset revision `d674485bbffdd533914e52d272fdda34c0515608`; source bytes are not redistributed | No separately published prepared dataset is claimed. The pinned ManiSkill 3.0.1 conversion environment restores each of 75 stored `traj_0` states independently | Restored `cube.pose` and Panda `agent.tcp_pose`; declared stable IDs; index-derived 50,000,000 ns clock; identity X/Y projection into a position-only record; no action stepping | Complete two-entity JSONL snapshots, then separately authored polygon/rules and Atlas evaluation. Session `7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`; incident fingerprint `954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2`; control `8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e` |
| CALVIN | **NO-GO** | Separately hosted debug ZIP with direct timestep NPZ state plus media/action fields. Only byte ranges and boundary members were inspected | No authoritative preparation record was established | A direct red-block/TCP mapping was technically plausible, but no adapter or derived values were published because rights and clock gates failed | No fixture, conversion, Atlas run, evidence bundle, or compatibility proof. The documentation-only rejection is the result |
| robomimic | **GO** | External raw HDF5 with flattened MuJoCo state, action, model, and metadata at revision `74fa018461f479cd9fd15b924a16103012096203` | External prepared HDF5 with simulator-derived `obs`/`next_obs` and copied fields. `Can` translation and TCP position were independently witnessed against raw state/model across 200 demos and 23,207 rows | For `demo_0`, consume prepared `obs/object[:,7:10]` and `obs/robot0_eef_pos`; map named entities to stable IDs; map raw simulator time to 50,000,000 ns steps; project X/Y; never consume `next_obs` or replay actions | 118 complete two-entity JSONL snapshots, then separate polygon/rules and Atlas evaluation. Shared session `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246`; incident fingerprint `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6`; control `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf` |
| MimicGen | **PARTIALLY SUPPORTED** | Candidate hosted `source/square.hdf5` identity was recorded, but the body was not inspected | Documentation describes a historical robosuite v1.2-to-v1.4 move; no immutable original-raw identity or exact command, environment, and lock were established | None | None: no fixture, conversion, Atlas run, evidence bundle, or compatibility proof |
| RoboCasa / RoboCasa365 | **NOT TESTED** | Not inspected | Not inspected | None | None |
| ROS 2 / MCAP + TF2 | **NOT TESTED** | Planned only: an immutable recording plus message definitions and TF/calibration sidecars would be required | No topic synchronization, TF materialization, calibration, or snapshot policy exists | None | None; no ROS 2 or MCAP compatibility claim exists. MET-46 is not started by this publication |

## Boundary rules carried into the publication

- Source artifacts remain external and are identified by immutable revisions and
  hashes when those identities were actually verified.
- A prepared field stays classified as prepared even when it is independently
  witnessed against raw state.
- Frame, time, entity identity, projection, and zone assignment are declared
  transformations; they are not silently treated as source facts.
- Operator polygons, Metriplane rules, incidents, controls, and Atlas outcomes
  are downstream evaluation layers, not labels supplied by a source project.
- A **NO-GO** records gate enforcement, not compatibility. **PARTIALLY
  SUPPORTED** records only the completed audit boundary and is not an
  implementation claim.

Detailed per-cell evidence is recorded in [`matrix.json`](matrix.json).
