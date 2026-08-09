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
| Ubuntu Linux | 3.12, 3.13 | Automated repository run on each Python version: 926 passed, 1 optional GPU test skipped; installed-wheel camera-free demo; owner Ubuntu 24.04/Python 3.12 run | Camera-free and core repository workflows are fully tested. Live-camera use additionally requires local V4L2 hardware and configuration. |
| macOS | 3.12, 3.13 | Camera-free repository run on each Python version: 925 passed, 2 optional browser/GPU tests skipped; installed-wheel demo | Camera-free core workflows are tested. No live-camera support claim is made. |
| WSL2 Ubuntu 24.04 | 3.12.3 (manual) | Owner-run installed-wheel check on 2026-08-09: `pip check`, version, doctor, six-event/one-incident demo, bundle verification, regression check, and a second headless demo all passed; install-to-report took 7 seconds | The installed-wheel camera-free and headless path is manually validated. This is not full-suite coverage. Automatic browser opening is not claimed because the test environment had no default HTML handler; omit `--open` or open the report path manually. |
| Native Windows | Not recorded | Owner-reported bundled camera-free demo completion from Command Prompt on 2026-08-09; no complete transcript, interpreter version, full suite, or wheel matrix was recorded | The single demo result is a useful compatibility observation, not a broad support claim. Other native-Windows workflows remain unvalidated and are not advertised as supported. |

The automated evidence is maintained in
[`ci.yml`](../.github/workflows/ci.yml) and
[`release-gates.yml`](../.github/workflows/release-gates.yml). The wheel demo runs
outside the source checkout and is required to finish within two minutes.

The WSL2 result above is recorded in the
[owner-run validation note](validation/wsl2-v0.3.0-owner-run.md). Some archived
v0.2.0 reproduction documents also describe a WSL2 Ubuntu path. Those archived
instructions remain part of the frozen research-artifact record and are not the
basis for the v0.3.0 compatibility statement. Native Windows and WSL2 are
different environments, and support for one must not be inferred from the other.
The reported Windows demo completion does not substitute for the automated
platform matrix above.
