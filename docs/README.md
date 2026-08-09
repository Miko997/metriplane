<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane documentation

**Understand what went wrong in a recorded workcell run—and turn it into a
repeatable test.**

Give Metriplane timestamped object positions and process rules. It creates an
incident timeline, a human-readable report, a verified evidence bundle, and a
regression check you can run again.

The bundled example explains a required torque driver that was missing during
an assembly step. Metriplane identifies six events, groups one incident, reports
a 35.0-second delay, verifies the saved evidence, and passes the generated
repeatable check.

[Run the camera-free quickstart](user-guide/quickstart.md), then follow the
[five-to-ten-minute tutorial](user-guide/use-your-own-run.md) to inspect the
example inputs and use the supported recorded-run interface.

## Start here

- [Quickstart](user-guide/quickstart.md): install the current preview and open
  the first Incident Report.
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
- [Integrations and support](user-guide/integrations.md): distinguish supported,
  repository-only, experimental, and unsupported paths.
- [Troubleshooting](user-guide/troubleshooting.md): recover from common setup,
  browser, input, verification, and regression failures.
- [Contributing](user-guide/contributing.md): prepare a focused change safely.
- [Research artifacts](user-guide/research-artifacts.md): reproduce or cite the
  exact historical version that produced a result.

## Scope in one sentence

Metriplane is open-source robotics incident replay and regression testing for
bounded workcells. It analyzes recorded state; it does **not** control machinery,
certify safety or quality, or prove that physical measurements were accurate.

The public PyPI package remains v0.2.1 while v0.3.0 is prepared. Documentation
that uses `metriplane demo` is explicitly a current-`main` preview until v0.3.0
is published. See [Research artifacts](user-guide/research-artifacts.md) for the
separate frozen v0.2.0 and v0.1.3 research boundaries.
