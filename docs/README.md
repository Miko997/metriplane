<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane documentation

**Understand what went wrong in a recorded workcell run and turn it into a
repeatable test.**

Give Metriplane timestamped object positions and process rules. It creates an
incident timeline, a human-readable report, a verified evidence bundle, and a
regression check you can run again.

The bundled example explains a required torque driver that was missing during
an assembly step. Metriplane identifies six events, groups one incident, reports
a 35.0-second delay, verifies the saved evidence, and passes the generated
repeatable check.

```bash
python -m pip install "metriplane==0.4.0.post1"
metriplane demo --open
```

[Run the camera-free quickstart](user-guide/quickstart.md), then follow the
[five-to-ten-minute tutorial](user-guide/use-your-own-run.md) to inspect the
example inputs and use the supported recorded-run interface.

## Start here

- [Quickstart](user-guide/quickstart.md): install v0.4.0.post1 and open the first
  Incident Report.
- [What Metriplane does](user-guide/what-metriplane-does.md): understand the
  problem, result, terms, and limits in ordinary language.
- [Missing-tool example](user-guide/missing-tool-example.md): see the concrete
  input, finding, and generated artifacts.
- [Inputs and outputs](user-guide/inputs-and-outputs.md): learn the exact
  supported data boundary.
- [CLI](user-guide/cli.md): use the beginner commands and the focused incident
  workflow.
- [Process rules](user-guide/process-rules.md): describe one bounded workcell
  without turning Metriplane into a control system.
- [Use your own recorded run](user-guide/use-your-own-run.md): export an
  inspectable example and move toward your own compatible data.
- [External fixtures](user-guide/external-fixtures.md): validate and run a
  portable, contract-compliant fixture without its original source software.
- [External evaluation package](external-evaluation/README.md): scope a bounded
  2-to-4-week recorded-state evaluation, collect the right source information,
  and review the result without requiring a production connection.
- [Integrations and support](user-guide/integrations.md): distinguish supported,
  repository-only, experimental, and unsupported paths.
- [External Source Contract v1](specs/external-source-contract-v1.md): inspect the
  source-neutral conversion contract and its limits. The generic execution path
  does not itself claim that an adapter for any particular source exists.
- [External source-family matrix v1](user-guide/external-source-family-matrix-v1/README.md):
  compare the exact evidence, decisions, limitations, and reopening criteria
  for seven audited, partial, rejected, uninspected, or planned source families.
- [Bounded MassRobotics AMR offline-replay profile](specs/massrobotics-amr-offline-replay-profile-v1.md):
  inspect one synthetic, reference-only two-AMR mapping and its exact incident
  and control replay.
- [Bounded ROS 2 and MCAP recorded-state profile](user-guide/ros2-mcap-recorded-state-profile/README.md):
  inspect the PARTIAL synthetic format-engineering result, three rejected
  external candidates, and the source-neutral capability boundary. This is not
  an external ROS 2 or MCAP compatibility claim.
- [Troubleshooting](user-guide/troubleshooting.md): recover from common setup,
  browser, input, verification, and regression failures.
- [Contributing](user-guide/contributing.md): prepare a focused change safely.
- [Research artifacts](user-guide/research-artifacts.md): reproduce or cite the
  exact historical version that produced a result.
- [Citing Metriplane](user-guide/citing.md): cite the current software, frozen
  research artifact, or manuscript without mixing their version boundaries.

## Scope in one sentence

Metriplane is open-source robotics incident replay and regression testing for
bounded workcells. It analyzes recorded state; it does **not** control machinery,
certify safety or quality, or prove that physical measurements were accurate.

The package quickstart is for v0.4.0.post1, the corrected publication identity
for the reduced Truth Recovery core release. It has no DOI and does not
establish a new research measurement boundary. See
[Research artifacts](user-guide/research-artifacts.md) for the prior v0.3.0
software release and the separate frozen v0.2.0 and v0.1.3 research boundaries.
