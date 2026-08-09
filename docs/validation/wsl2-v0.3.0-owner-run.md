<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# WSL2 v0.3.0 owner-run validation

This note records one manual, owner-run validation of the v0.3.0 installed-wheel
camera-free path. It is a bounded compatibility result, not an automated full
suite or native-Windows support claim.

## Environment

- Date: 2026-08-09
- Candidate commit: `75bb31e801410df5f94ea60514fc1177811a999a`
- WSL version: WSL2
- Distribution: Ubuntu 24.04
- Python: 3.12.3
- Artifact: locally built `metriplane-0.3.0-py3-none-any.whl`
- Execution location: `/tmp`, outside the source checkout

## Recorded result

The owner created separate build and run virtual environments, built the wheel,
installed it into the run environment, and exercised the installed CLI outside
the checkout. The recorded results were:

- wheel build and installation: passed;
- `python -m pip check`: `No broken requirements found`;
- `metriplane --version`: `metriplane 0.3.0`;
- `metriplane doctor`: four required checks passed and
  `Ready for the bundled camera-free demo.`;
- `metriplane demo --open`: generated the report and completed successfully;
- install-to-report elapsed time: 7 seconds, below the two-minute gate;
- incident timeline: 6 events;
- incident report: 1 incident;
- evidence bundle verification: passed with no errors;
- generated regression check: passed with no errors;
- a second `metriplane demo` run without `--open`: passed and generated the
  same substantive six-event/one-incident result.

The scenario remained the required missing torque driver with a 35.0-second
fastening delay.

## Browser boundary

Automatic browser opening was **not** validated. The command printed a browser
dispatch success message, but `gio` then reported that the WSL environment had
no default application for `text/html`. The HTML report itself existed and was
non-empty, and the failure did not affect the demo, bundle, regression, or
headless results.

On WSL2 without a configured HTML handler, omit `--open`:

```bash
metriplane demo
```

Then open the printed `cell_truth_report.html` path manually with a browser that
can access the WSL filesystem.

## Claim boundary

This run supports a WSL2 Ubuntu 24.04/Python 3.12.3 claim for the installed-wheel
camera-free and headless workflow. It does not establish:

- the complete Linux CI suite on WSL2;
- automatic browser opening on WSL2;
- live-camera, GPU, ROS 2, Isaac Sim, Docker, or hardware behavior; or
- native Windows support.

Native Windows remains unsupported and unadvertised.
