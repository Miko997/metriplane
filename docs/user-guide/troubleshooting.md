<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Troubleshooting

## Python is unsupported

Metriplane v0.3.0 supports Python 3.12 and 3.13. Python 3.11 and Python 3.14 or
newer are rejected.

```bash
python3 --version
```

Create the virtual environment with a supported interpreter, for example
`python3.12 -m venv .venv` or `python3.13 -m venv .venv`.

## `externally-managed-environment` or PEP 668 error

Do not install into the operating system's managed Python and do not use
`--break-system-packages`. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "metriplane==0.3.0"
metriplane demo --open
```

## Doctor reports optional capabilities are absent

Run:

```bash
metriplane doctor
```

The required Python, package-import, runtime-dependency, and bundled-resource
checks determine whether the camera-free demo is ready. Required runtime
dependencies are NumPy, OpenCV, PyYAML, websockets, and Pydantic. A missing
camera, GPU, Git checkout, or repository-only helper script is optional and must
not be interpreted as a broken wheel installation. The successful required
result ends with:

```text
Ready for the bundled camera-free demo.
```

## Browser did not open

Browser dispatch is a convenience, not an analysis requirement. The command
prints a warning and the absolute report URI. Open that path manually, or run
without browser dispatch:

```bash
metriplane demo
```

## WSL2: open the report from Windows

Start from a writable Linux directory and use an explicit output path:

```bash
cd ~
metriplane demo --out "$HOME/metriplane-demo"
```

If WSL2 has no Linux HTML handler, open the generated report through Windows:

```bash
explorer.exe "$(wslpath -w "$HOME/metriplane-demo/cell_truth_report.html")"
```

The stable filename remains `cell_truth_report.html` for compatibility, while
the page itself is titled **Incident Report**. Browser opening remains best
effort, and this does not establish native Windows support.

## Headless server, container, or SSH session

Omit `--open`. Find the path under the final `Incident Report:` line. You can
copy `cell_truth_report.html` to your workstation or read
`cell_truth_report.md` in a text editor. No web server is required.

## The output directory already exists

The demo, input export, and Atlas run protect existing paths from accidental
replacement. Choose a new path:

```bash
metriplane demo --out my-demo-2
metriplane demo --export-inputs my-cell-2
```

For `atlas run`, prefer another `--out` directory. `--overwrite` exists for an
explicitly verified disposable Metriplane run, but never use it on an unrelated
directory.

## The exported inputs cannot be found

`--export-inputs` takes its destination directly and cannot be combined with
`--out` or `--open`:

```bash
metriplane demo --export-inputs my-cell
```

Look for `my-cell/session.jsonl` and `my-cell/domain-pack/`.

## Process rules are invalid

Run the validator on the directory, not an individual YAML file:

```bash
metriplane atlas validate-pack my-cell/domain-pack
```

Fix every printed error. Common causes are duplicate IDs, unknown asset/zone/
station references, a process/work-order mismatch, multiple work orders, a
negative or non-finite maximum wait, or a required `assets.yaml`,
`workspace.yaml`, or `process.yaml` file that is missing. `contracts.yaml` and
`work_orders.csv` have compatibility behavior described in
[Process rules](process-rules.md). The validator returns nonzero on failure.

## Recorded data is invalid

Each non-header JSONL line must validate as `FrameStateModel`. Check the line
number in the error, then verify JSON syntax, finite times/positions, non-negative
integer frame IDs, unique nonempty object IDs, and confidence values in the
0-to-1 range. Relevant objects also need zone labels that match the rule files;
positions do not create those labels automatically.

## The run has zero incidents

Zero incidents can be a valid result. It means the replay did not cross the
configured missing-required-asset / maximum-wait condition. Inspect the report,
timeline, object IDs, zone labels, and rule threshold. With no incident, there is
no incident bundle or generated regression path to verify.

## Bundle verification failed

Treat the bundle as unverified. Read every error returned by:

```bash
metriplane atlas bundle verify path/to/INC-….zip
```

Do not edit files inside a bundle or recreate its manifest by hand. Return to the
original run inputs, create a fresh output directory, rerun the analysis, and
verify the newly generated bundle. A failed verification exits nonzero.

## The generated regression failed

Treat the failure as a real mismatch until understood:

```bash
metriplane atlas test path/to/INC-….yaml --json
```

The JSON errors identify missing or stale required outputs. Do not copy a passing
result from another run, edit the spec merely to force a pass, or assume that a
deterministic replay proves physical accuracy. Recreate the run from validated
inputs when outputs are incomplete.

## The report path is unclear

For an explicit run:

```bash
metriplane atlas report --run-dir my-cell-run
```

This prints `my-cell-run/cell_truth_report.html` and exits nonzero if the report
does not exist. For the bundled demo, use the path printed below
`Incident Report:`.
