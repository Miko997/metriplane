<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Supported and prohibited semantics register

## Supported semantics

| Family | What the frozen evidence supports |
| --- | --- |
| ManiSkill | One PickCube `traj_0` position-only complete-snapshot path. An operator-authored target polygon and `0.20 s` relative wait produce `75/4/1/1`; a `0.30 s` control produces `75/3/0/0`. The result is bounded TCP arrival/required-presence timing. |
| robomimic | One Can PH `demo_0` position-only complete-snapshot path. An operator-authored target polygon and `2.0 s` relative wait produce `118/4/1/1`; a `2.5 s` control produces `118/3/0/0`. The result is bounded TCP arrival/required-presence timing. |
| CALVIN | No Atlas semantics. The audit documents why no contract-valid fixture was emitted. |
| MimicGen | No Atlas semantics demonstrated. |
| RoboCasa / RoboCasa365 | No Atlas semantics demonstrated. |
| ROS 2 / MCAP + TF2 | No Atlas semantics demonstrated. |
| MassRobotics AMR offline replay | One synthetic, two-AMR, current-location-only complete-snapshot mapping. The operator-authored `3.0 s` rendezvous wait produces incident `9/4/1/1` and control `9/3/0/0`. |

In both `GO` rows, the polygon, required role, and wait are Metriplane-authored
Layer-C rules. They are not source-project labels or task-success criteria.
Expected outcomes are test metadata and are never Atlas input.

## Prohibited semantics and claims

The package prohibits interpreting any row as evidence for:

- official PickCube or Can success/failure;
- grasp, contact, controller, retention, or continued co-occupancy correctness;
- 3D pose, orientation, placement, dynamics, physical accuracy, simulator
  realism, or sim-to-real validity;
- quality, safety, certification, production readiness, source-project
  endorsement, or independent adoption;
- general ManiSkill, robomimic, HDF5, CALVIN, MimicGen, RoboCasa, ROS 2,
  rosbag2, MCAP, TF2, MassRobotics, arbitrary-topic, or automatic-discovery
  support;
- three successful integrations or universal source neutrality.

CALVIN's `NO-GO` is a successful enforcement result, not a successful source
integration. MimicGen's `PARTIALLY SUPPORTED` decision describes a partial audit,
not an implemented path. The MassRobotics `PARTIALLY SUPPORTED` row is limited
to the frozen synthetic profile. `NOT TESTED` cells contain no implied facts.

## Claim register

| Claim | Status | Boundary |
| --- | --- | --- |
| Two source-specific portable paths exist | Allowed | Exact ManiSkill and robomimic rows only |
| CALVIN failed closed on rights and timing | Allowed | Documentation-only Phase-0 audit |
| Both `GO` fixtures evaluate on Ubuntu/macOS and Python 3.12/3.13 | Allowed | Frozen portable fixtures; first-party CI |
| Source conversion is portable across all matrix rows | Prohibited | Portable fixture evaluation does not establish portability for every source stack |
| Independent validation or adoption exists | Prohibited | No attributable outside rerun is recorded |
| General source-family support exists | Prohibited | Every `GO` is artifact- and semantics-specific |
| Frozen synthetic MassRobotics-format profile | Implemented | Exact MET-55 incident/control fixtures |
