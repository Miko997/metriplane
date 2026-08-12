<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Human-readable compatibility and decision matrix

This view summarizes the complete structured rows in [matrix.json](matrix.json).
“Verified” means verified for the exact bounded artifact named in that row—not
for the whole source family. “Not applicable” is distinct from a passing test.

## Decision and artifact identity

| Family | Exact artifact identity | Decision | Contract fit |
| --- | --- | --- | --- |
| ManiSkill | PickCube-v1 `episode 0` / `traj_0`; dataset revision `d674485bbffdd533914e52d272fdda34c0515608`; tagged proof `maniskill-pickcube-proof-v1` at `49c3b37057312c89db030386dd2cc68628d92458` | `GO` | Two frozen complete-snapshot fixtures validate under Contract v1 |
| CALVIN | `calvin_debug_dataset.zip`, published SHA-256 `c66d09147e2c806b244f18ea7d61e388d4dac11f828929779437f728d03e1204`; CALVIN `fa03f01f19c65920e18cf37398a9ce859274af76`; `calvin_env` `1431a46bd36bde5903fb6345e68b5ccc30def666` | `NO-GO` | Blocked independently by rights and authoritative-clock gates |
| robomimic | Can PH `demo_0`; dataset revision `74fa018461f479cd9fd15b924a16103012096203`; frozen adapter `cfc285a3e757fdf742858b1c4cf685c384d01e8b` | `GO` | Two frozen complete-snapshot fixtures validate under Contract v1 |
| MimicGen | Partially audited Square human source at dataset revision `33016f8a62c02334f929f2913af8fdd2a8a129e1`; recorded remote source hash `c917e99362fd9bd11978d6e2642c1ea88272702fbf55b50367ed471febf550e2` | `PARTIALLY SUPPORTED` | Not established; no immutable raw/prepared chain or clock proof |
| RoboCasa / RoboCasa365 | No artifact selected or inspected | `NOT TESTED` | Not tested |
| ROS 2 / MCAP + TF2 | No recording selected; planned work is [MET-46](https://linear.app/metriplane/issue/MET-46/extract-a-minimal-metriplane-source-adapter-sdk-and-prove-a-ros-2mcap) | `NOT TESTED` | Design target only; no compatibility proof |

## Rights and provenance boundary

| Family | Code / dataset / derived-fixture rights | Raw → prepared → derived → normalized boundary |
| --- | --- | --- |
| ManiSkill | ManiSkill and dataset treated as Apache-2.0; independently authored adapter/proof MIT; derived fixture retains Apache-2.0 treatment and modification notice; noncommercial assets excluded | Referenced ZIP/HDF5/JSON → independent state restoration → cube/TCP pose derivation → 75 complete planar snapshots; source bytes and assets excluded |
| CALVIN | Root code MIT; `calvin_env` licensing metadata conflicts; no dataset-specific grant covering archive or derived-state redistribution | NPZ state appears technically usable, but the Phase-0 audit stopped before adapter, fixture, or normalized output |
| robomimic | robomimic/robosuite code MIT; exact dataset revision declares MIT; normalized numeric derivative and Metriplane rules distributed under MIT with attribution/modification notice | Referenced raw state/action/model HDF5 → prepared observations → raw-witnessed Can/TCP positions → 118 complete planar snapshots; HDF5 and simulator assets excluded |
| MimicGen | NVIDIA-restricted code terms are separate from CC BY 4.0 dataset terms; no code may enter Metriplane's MIT adapter | Candidate human HDF5 recorded remotely; no body inspection, authoritative preparation chain, derived output, or normalized fixture |
| RoboCasa / RoboCasa365 | Not inspected | Unknown; no boundary inferred |
| ROS 2 / MCAP + TF2 | Not tested; recording-specific rights remain required | No recording or topic/frame boundary selected |

## State model

| Family | Clock and domain | Frame / transform / units | Identity, completeness, and materialization |
| --- | --- | --- | --- |
| ManiSkill | Fixed `50,000,000 ns` simulation step, 20 Hz, frames 0–74 | `maniskill_world`; metres; X/Y identity; normalized Z `0.0`; separate operator polygon | `cube_1` and `robot_tcp_1`; complete snapshot; omissions rejected; no carry-forward, interpolation, resampling, or action stepping |
| CALVIN | Stored index supplies order only; nominal 30 Hz is not an authoritative per-sample clock | Direct semantic state is plausible, but world handedness and authoritative transform are unresolved; positions appear metric | Array-slot identities are only candidate mappings; completeness and materialization were not fully established |
| robomimic | Raw state establishes fixed `50,000,000 ns` simulation step, 20 Hz, frames 0–117 | `robosuite_world`; right-handed MuJoCo semantics; metres; X/Y identity; normalized Z `0.0`; separate operator polygon | `can_1` and `robot_tcp_1`; complete snapshot; omissions rejected; no carry-forward, interpolation, resampling, or cross-stream synchronization |
| MimicGen | No artifact-specific clock proof | No inspected frame, transform, or unit mapping | No verified identity, completeness, missing-state, or materialization policy |
| RoboCasa / RoboCasa365 | Not tested | Not tested | Not tested |
| ROS 2 / MCAP + TF2 | No clock/domain selected | No TF2 authority/path or units selected | No topic-to-entity identity, completeness, or materialization policy selected |

## Field provenance and information loss

| Family | Field provenance | Information loss |
| --- | --- | --- |
| ManiSkill | Independently restored actor pose supplies cube position; Panda articulation forward kinematics supplies TCP pose | Z, orientation, velocity, articulation beyond TCP, actions, contact/grasp state, source outcomes, and rendering discarded |
| CALVIN | Inspected `scene_obs` and `robot_obs` slots make a direct-state mapping plausible but unimplemented | Not normalized; any loss policy remains hypothetical |
| robomimic | Prepared `obs/object[:,7:10]` supplies Can position and `obs/robot0_eef_pos` supplies TCP; every row is witnessed against raw named joint/site state across 200 demos / 23,207 rows | Z, orientation, velocities, articulation, actions, contacts/grasp, rewards, termination/outcomes, visuals, and `next_obs` discarded |
| MimicGen | No field body inspected | Unknown; no normalization performed |
| RoboCasa / RoboCasa365 | Not tested | Not tested |
| ROS 2 / MCAP + TF2 | Not tested | Not tested |

## Evaluation and reproducibility

| Family | Supported Atlas semantics | Deterministic conversion | Portable evaluation | Evidence / regression | Independent rerun |
| --- | --- | --- | --- | --- | --- |
| ManiSkill | Operator-authored XY arrival/required-presence timing; incident `75/4/1/1`, control `75/3/0/0` | Three clean conversions; 28 byte-equivalent artifacts | Ubuntu/macOS × Python 3.12/3.13 at exact tag | Incident bundle verified and regression passed; control intentionally has neither | `NOT TESTED`—only first-party evidence |
| CALVIN | None | No adapter or conversion | No fixture | Not applicable; no Atlas run | Not applicable |
| robomimic | Operator-authored XY arrival/required-presence timing; incident `118/4/1/1`, control `118/3/0/0` | Frozen three-conversion / 28-artifact equivalence; later first-party source reacquisition produced the same session and mutually equivalent current-head conversions, not frozen-byte fingerprints | Frozen fixtures passed Ubuntu/macOS × Python 3.12/3.13 | Incident bundle verified and regression passed; control intentionally has neither | `NOT TESTED`—only first-party evidence |
| MimicGen | None demonstrated | No converter | No fixture | Not applicable | Not applicable |
| RoboCasa / RoboCasa365 | None demonstrated | No converter | No fixture | Not applicable | Not applicable |
| ROS 2 / MCAP + TF2 | None demonstrated | No converter | No fixture | Not applicable | Not applicable |

## Supported and prohibited interpretation

The two `GO` rows support only source-specific deterministic normalization and
portable evaluation of their operator-authored planar arrival scenarios. They
do not support official task success/failure, grasp correctness, 3D pose,
physical accuracy, simulator realism, safety, production fitness, endorsement,
or family-wide compatibility. See the [semantics register](SEMANTICS.md),
[unsupported-path register](UNSUPPORTED-PATHS.md), and
[reopening criteria](REOPENING.md) for row-specific limits.
