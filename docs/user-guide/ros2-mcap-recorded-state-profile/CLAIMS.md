<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Claims register

## Allowed claims

The following claims are allowed after their corresponding exact-head tests pass:

- Metriplane has a small, isolated Source Adapter capability schema extracted
  from repeated ManiSkill and robomimic adapter responsibilities.
- The frozen ManiSkill and robomimic adapters can be classified post hoc against
  that schema without modifying their proofs.
- One Metriplane-authored synthetic recording exercises a bounded
  `metriplane.ros2_mcap_recorded_state.v1` format-engineering path.
- The synthetic path uses explicit schemas, topics, message-header clock, static
  transforms, units, identities, complete-snapshot rules, provenance, loss, and
  anti-taint exclusions.
- Portable synthetic fixture evaluation does not require ROS 2, rosbag2, MCAP,
  or the adapter environment, once verified.
- Three external candidates were rejected without weakening Contract v1 gates.

## Required headline

> This is a PARTIAL, synthetic-only format-engineering result. No external ROS 2
> or MCAP recording passed every source gate, so no external compatibility claim
> exists.

## Prohibited claims

Do not claim:

- Metriplane supports ROS 2, rosbag2, MCAP, or TF2;
- arbitrary bag, channel, topic, message, schema, or transform support;
- automatic semantic or topic discovery;
- general Gazebo, Isaac, ROS-Industrial, or simulator compatibility;
- an external ROS 2/MCAP source path;
- a third successful external integration;
- universal source neutrality or robotics-data compatibility;
- raw sensor interpretation, image perception, or state estimation;
- physical accuracy, calibration validity, simulator realism, or real-world
  incident detection;
- safety, quality certification, production readiness, or robot-control
  correctness;
- source-project endorsement, independent adoption, or independent validation.

The capability schema validates declarations. It does not prove their truth.
The synthetic path validates format and boundary engineering. It does not
validate an external source family.

## Existing aggregate claim

The prior source-family matrix aggregate claim remains unchanged: two
source-specific portable paths, ManiSkill and robomimic, plus the documented
CALVIN rejection. This synthetic work does not add a third external path.

