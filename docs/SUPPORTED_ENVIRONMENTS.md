<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Supported Environments

This page is the authoritative compatibility statement for the active Metriplane
development line. It describes workflows that are currently exercised, rather
than environments that are merely expected to work.

The Python package requires Python 3.12 or 3.13.

| Environment | Python | Current validation | Support statement |
| --- | --- | --- | --- |
| Ubuntu Linux | 3.12, 3.13 | Automated repository run: 815 passed, 1 optional GPU test skipped; installed-wheel camera-free demo; owner Ubuntu 24.04/Python 3.12 run | Camera-free and core repository workflows are fully tested. Live-camera use additionally requires local V4L2 hardware and configuration. |
| macOS | 3.12, 3.13 | Camera-free repository run: 814 passed, 2 optional browser/GPU tests skipped; installed-wheel demo | Camera-free core workflows are tested. No live-camera support claim is made. |
| WSL2 Ubuntu | — | No clean manual v0.3.0 run recorded yet | Not advertised for v0.3.0 until that run is recorded. |
| Native Windows | — | Not tested or implemented as a supported path | Unsupported and not advertised. |

The automated evidence is maintained in
[`ci.yml`](../.github/workflows/ci.yml) and
[`release-gates.yml`](../.github/workflows/release-gates.yml). The wheel demo runs
outside the source checkout and is required to finish within two minutes.

Some archived v0.2.0 reproduction documents describe a WSL2 Ubuntu path. Those
instructions remain part of the frozen research-artifact record; they are not a
v0.3.0 compatibility claim. Native Windows and WSL2 are different environments,
and neither should be inferred from the other.
