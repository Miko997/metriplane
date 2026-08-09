<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# The missing-tool example

The bundled example is a small, camera-free assembly-cell recording. It is
designed to make the complete result inspectable, not to simulate an entire
factory.

## Scenario

The process rules require `torque_driver_1` at `station_a` before fastening and
allow a maximum wait of 30.0 seconds. In the recording, the workpiece is at the
station while the driver remains absent long enough to cross that limit. The
driver later appears, after a measured delay of 35.0 seconds.

The expected substantive result is:

- six timeline events;
- one missing-required-asset incident;
- required torque driver missing;
- fastening delayed by 35.0 seconds;
- evidence-bundle verification passes;
- the generated regression check passes;
- a local HTML Incident Report is generated.

## What is supplied

The session is newline-delimited JSON containing already-estimated object states.
Each usable frame includes a timestamp, a frame identifier, and objects with
stable identifiers, positions, and zone labels. The rule directory maps those
object IDs to workcell assets and defines zones, one ordered process, a maximum
wait, and exactly one work order.

The sample is packaged inside the wheel, so an installed user does not need a
source checkout to run it. To inspect copies of the real inputs, use:

```bash
metriplane demo --export-inputs my-cell
```

This writes:

```text
my-cell/
  session.jsonl
  domain-pack/
    assets.yaml
    workspace.yaml
    process.yaml
    contracts.yaml
    work_orders.csv
```

The export command refuses to replace an existing destination. It is separate
from `--out` and `--open`: export the files first, then use the explicit commands
in [Use your own recorded run](use-your-own-run.md).

## What is created

The run directory includes the timeline and process trace, the HTML and Markdown
report, a zipped evidence bundle for each incident, and a YAML regression spec
for each incident. The main user-facing paths for this example are:

```text
cell_truth_report.html
evidence_bundles/INC-0001.zip
regression_tests/INC-0001.yaml
```

`cell_truth_report.html` remains the stable filename. Its visible title is
“Incident Report”; “Cell Truth Report” is the secondary formal artifact name.

The verified bundle shows that the saved files match its manifest. It does not
certify that the original measurement or classification was physically correct.
The regression check confirms that the stored incident expectation still matches
the required outputs; it does not control the workcell.

