<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Supported Environments

This page is the authoritative compatibility statement for the active Metriplane
development line. v0.4.0.post2 support is accepted only from its exact protected
release workflows; historical results are labeled separately.

The v0.4.0.post2 reduced Truth Recovery core release requires Python 3.12 or 3.13.

| Environment | Python | v0.4.0.post2 release validation | Support statement |
| --- | --- | --- | --- |
| Ubuntu Linux | 3.12, 3.13 | Protected Release Gates run the complete repository suite and an installed-wheel camera-free demo on each Python version. Exact v0.4.0.post2 results belong in the final release record. | Camera-free and core repository workflows are release-gated. Live-camera use additionally requires local V4L2 hardware and configuration. |
| macOS | 3.12, 3.13 | Protected Release Gates run the complete repository suite and an installed-wheel camera-free demo on each Python version. Exact v0.4.0.post2 results belong in the final release record. | Camera-free core workflows are release-gated. No live-camera support claim is made. |
| WSL2 Ubuntu 24.04 | Not recorded for v0.4.0.post2 | No fresh exact-v0.4.0.post2 candidate run is recorded. | No v0.4.0.post2 WSL2 support claim is made. Automatic browser opening remains environment-dependent; headless users may omit `--open` or open the report path manually. |
| Native Windows | Not recorded for v0.4.0.post2 | No fresh exact-v0.4.0.post2 candidate run is recorded. | No v0.4.0.post2 native-Windows support claim is made. |

The automated evidence is maintained in
[`ci.yml`](../.github/workflows/ci.yml) and
[`release-gates.yml`](../.github/workflows/release-gates.yml). The wheel demo runs
outside the source checkout and is required to finish within two minutes.

The historical v0.3.0 WSL2 result is recorded in the
[owner-run validation note](validation/wsl2-v0.3.0-owner-run.md). Some archived
v0.2.0 reproduction documents also describe a WSL2 Ubuntu path. Those archived
instructions remain part of the frozen research-artifact record and are not the
basis for the v0.3.0 compatibility statement. Native Windows and WSL2 are
different environments, and support for one must not be inferred from the other.
The reported v0.3.0 Windows demo completion does not substitute for the
automated platform matrix above. These retained v0.3.0 manual observations are
not a separate WSL2 or native-Windows validation of v0.4.0.post2.
