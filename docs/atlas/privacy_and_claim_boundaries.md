<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Privacy and Claim Boundaries

Atlas is designed around asset, tool, material, zone, station, and process
evidence. It should prefer physical-process language over worker-monitoring
language.

Allowed claims for the checked-in implementation:

- Replayable event ledger for tagged planar object state.
- Domain-pack validation for bounded workcells.
- Observe-only process deviations from configured assets, zones, and stations.
- Evidence bundles with checksums and generated regression tests.
- Training and improvement artifacts grounded in local incident evidence.

Disallowed claims without separate implementation and evidence:

- Certified safety control or collision avoidance.
- Robot, PLC, or machine-controller command authority.
- Marker-free or general object/person recognition.
- Face recognition, biometrics, hidden surveillance, or individual blame.
- Full 3D reconstruction, SLAM, or measured Isaac/ROS latency.
- Quality release approval or GMP disposition authority.

Use the Cell Black Box as a record of observable physical state. Treat every
recommendation as a hypothesis that needs before/after validation.
