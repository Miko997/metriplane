<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Use your own recorded run

This five-to-ten-minute path starts with the same packaged inputs as the bundled
demo, exposes every stage, and shows where compatible workcell data fits. Run it
after the [Quickstart](quickstart.md).

The unchanged export, validation, run, report, verification, and regression
sequence is exercised by focused tests and the installed-wheel release gate.
Adapting the exported copies to your own recording is necessarily manual.

## 1. Export inspectable inputs

From any writable directory:

```bash
metriplane demo --export-inputs my-cell
```

The command creates a new directory and refuses to replace an existing one:

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

Open `session.jsonl` in a text editor. It is the actual `FrameStateModel` JSONL
recording used by the demo, not pseudocode. Then inspect the five rule files and
follow the object ID `12` / asset ID `torque_driver_1` across them.

## 2. Validate the process rules

```bash
metriplane atlas validate-pack my-cell/domain-pack
```

Expected result:

```text
PASS my-cell/domain-pack
```

The command returns nonzero and prints each error if a file is malformed, an ID
reference is inconsistent, a wait is invalid, or the pack has anything other
than exactly one work order.

## 3. Run the recording explicitly

```bash
metriplane atlas run \
  --session-jsonl my-cell/session.jsonl \
  --pack my-cell/domain-pack \
  --out my-cell-run
```

Use a new output path. Metriplane will not silently replace an existing run. The
unchanged example prints `events=6 incidents=1` and the report path.

## 4. Find the report

```bash
metriplane atlas report --run-dir my-cell-run
```

Open the printed `cell_truth_report.html` path in a browser, or read
`cell_truth_report.md` in a terminal or editor. Start with “What happened” and
“Why it was flagged,” then inspect the saved evidence and generated check.

## 5. Verify the evidence

For the unchanged example:

```bash
metriplane atlas bundle verify \
  my-cell-run/evidence_bundles/INC-0001.zip
```

The JSON result must contain `"pass": true`. A nonzero exit and any listed error
mean the bundle must not be treated as verified.

## 6. Rerun the generated check

```bash
metriplane atlas test \
  my-cell-run/regression_tests/INC-0001.yaml \
  --json
```

The unchanged example returns `"pass": true`. This confirms that the stored
incident expectation matches the required current artifacts. It does not prove
physical accuracy and does not control machinery.

## 7. Move toward your recording

Keep the exported directory as a working template and make changes in a copy:

1. Convert your already-estimated, preclassified object states into one
   `FrameStateModel` JSON object per line.
2. Give every relevant object a stable string `id`, timestamp, finite position,
   and a zone label assigned by your upstream system.
3. Map those IDs to assets in `assets.yaml`.
4. Define the bounded zones and station references in `workspace.yaml`.
5. Express the ordered required-asset and maximum-wait expectation in
   `process.yaml`.
6. If you keep `contracts.yaml`, keep its claims observe-only. Retain an explicit
   `work_orders.csv` with exactly one matching work order; the loader's default
   exists for compatibility, not as the recommended adaptation path.
7. Run `validate-pack`, then `run`, then inspect the report before verifying any
   generated bundle or regression.

The supported boundary begins with already-estimated object states. There is no
v0.4.0.post1 raw-video, rosbag, rosbag2, or MCAP importer, and positions alone do not
derive zone labels.

A compatible run may correctly produce zero incidents. In that case, inspect the
report and rules to confirm that no configured missing-required-asset wait was
violated. Do not expect or fabricate an `INC-0001` bundle or regression path.

For exact fields and limits, continue with [Inputs and outputs](inputs-and-outputs.md),
[Process rules](process-rules.md), and [Troubleshooting](troubleshooting.md).
