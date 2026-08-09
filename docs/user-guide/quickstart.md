<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Quickstart

This preview turns the bundled missing-tool recording into an Incident Report,
a verified evidence bundle, and a passing repeatable regression check. It needs
Python 3.12 or 3.13, but no camera, GPU, Docker, ROS, or network connection after
installation.

## Install the current preview

Metriplane v0.3.0 is not published yet. PyPI still serves v0.2.1, which does not
contain `metriplane demo`. Until the release, install current `main` in a virtual
environment:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
metriplane doctor
metriplane demo --open
```

This source-checkout installation is a **manual pre-release path**. Release gates
exercise the bundled demo from a built wheel on Ubuntu and macOS with Python
3.12/3.13, but they do not claim that the current source-preview sequence is a
published-package quickstart. Opening the visible browser window is also a local
manual check.

`metriplane doctor` should finish with:

```text
Ready for the bundled camera-free demo.
```

The demo should report:

```text
Scenario:
A required torque driver is missing during an assembly step.
The fastening step is delayed by 35.0 seconds.

Result:
PASS  Incident timeline: 6 events
PASS  Incident report: 1 incident
PASS  Evidence bundle: verified
PASS  Repeatable regression check: passed
```

The command prints the full path to `cell_truth_report.html`. The visible page
is titled **Incident Report**; the stable filename and formal “Cell Truth Report”
artifact name remain for compatibility.

If no browser is available, omit `--open`:

```bash
metriplane demo
```

The analysis still runs and prints the report path. Browser-opening failure is
nonfatal; open the printed `file://` address later.

## Planned published-package path

After v0.3.0 is actually published, the final installation path will be:

```bash
python -m pip install "metriplane==0.3.0"
metriplane demo --open
```

These two commands describe the planned release path. They are **not** a claim
that v0.3.0 can currently be installed from PyPI.

## Next step

Continue to [Use your own recorded run](use-your-own-run.md). It exports the
bundled session and its process-rule files so you can inspect the real input,
rerun every stage explicitly, and then adapt copies to compatible workcell data.
