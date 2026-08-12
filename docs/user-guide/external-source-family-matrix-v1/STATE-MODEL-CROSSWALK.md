<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Clock, frame, unit, identity, and completeness crosswalk

The comparison below states only what the frozen evidence supports. “Not
tested” means no value or policy is inferred.

| Source family | Decision | Authoritative clock and domain | Frame and transform model | Units | Stable identity | Completeness and missing-state policy | Materialization or carry-forward |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ManiSkill | **GO** | Stored-state index `i` maps to `i * 50,000,000` ns from zero; 75 frames at 20 Hz, 0–3.70 s. The 50-step RL horizon is separate provenance and does not truncate the fixture | Independently restored named poses in `maniskill_world`; identity X/Y transform; normalized Z fixed to 0.0; polygon membership is a separate inclusive operator rule | Metres; authoritative integer nanoseconds | `cube_1/material` and `robot_tcp_1/tool`; mapping SHA-256 `9127535a2e8eb3091aeac82f335e001f81c3a9e5098272881f7969c6eeecbee7` | Every frame has known state for both entities; omission, unknown state, duplicate state, or invalid data rejects the fixture; event lists are empty | None. Each stored state is restored independently; no action stepping, interpolation, resampling, synchronization, or carry-forward |
| CALVIN | **NO-GO** | **Blocked.** Indices establish order only; NPZs have no timestamps. Nominal 30 Hz cannot replace wall-clock-gated recording behavior, and inventing a fixed step is prohibited | PyBullet-world and direct XY are technically plausible; exact handedness was not found in inspected sources; no transform or polygon was frozen | TCP XYZ is documented as world metres; block metres and Euler radians are supported inferences; no supported elapsed-time unit | Fixed red/blue/pink ordering could map the red block, but it was not verified across the complete sequence | Boundary NPZs are snapshots, but all 2,771 candidate samples were not inspected. A future path would reject gaps, shape changes, nonfinite values, and missing entities | Not applicable because no adapter exists. A proposed direct path would reject incomplete samples and use no interpolation, resampling, or carry-forward |
| robomimic | **GO** | Raw `states[:,0]` MuJoCo simulation time; every one of 23,007 within-demo adjacent differences is 0.05 s within floating representation; `demo_0` maps to 118 frames at 50,000,000 ns steps, 0–5.85 s | Can and TCP are in `robosuite_world` under pinned MuJoCo semantics; identity X/Y transform; normalized Z fixed to 0.0; polygon membership is a separate operator rule | Positions in metres; raw simulation seconds; normalized integer nanoseconds | `can_1/material` and `robot_tcp_1/tool`; mapping SHA-256 `51735e2c4e416c951d5d355dbb271a89f467354a9cab41fef386fa105c671a8c` | All 118 `obs` rows are complete two-entity snapshots. Omission, unknown, nonfinite, duplicate, or mismatched state rejects the fixture; no T+1 frame is fabricated | `partial_updates_materialized=false`; no carry-forward, interpolation, or resampling; same-row observations need no synchronization; `next_obs` is excluded |
| MimicGen | **PARTIALLY SUPPORTED** | Not tested for the selected artifact | No frame, transform, projection, or zone model verified | Not tested | Not tested | HDF5 body not inspected for snapshot completeness, missing state, or partial updates | No preparation, synchronization, materialization, or carry-forward policy inspected or implemented |
| RoboCasa / RoboCasa365 | **NOT TESTED** | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested |
| ROS 2 / MCAP + TF2 | **NOT TESTED** | No recording selected. A future bounded profile must choose one source/header/bag clock and domain and reject nominal rates, mixed clocks, default timestamps, and unjustified log time | No TF tree tested. A future profile must declare an acyclic path, static/dynamic transforms, and rejection of missing, ambiguous, or undeclared interpolation | Not tested | No source-entity mapping selected | No topic set, trigger, skew limit, staleness limit, or complete-snapshot rule tested | No policy implemented. A future profile must declare trigger, synchronization tolerance, bounded carry-forward, maximum staleness, and rejection behavior |

## Information deliberately excluded from the two GO fixtures

Both proven paths are bounded, position-only evaluations. They exclude source Z,
orientation, velocities, actions, contacts, grasp/controller state, source
outcomes, images, and simulator realism claims. Source-specific records contain
the longer exclusion lists. Neither row proves physical accuracy, general
ManiSkill or robomimic support, general HDF5 support, or production readiness.

The structured status and evidence for every cell are authoritative in
[`matrix.json`](matrix.json).
