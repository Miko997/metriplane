<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Command-line interface

Start with the installed command itself:

```bash
metriplane --help
metriplane --version
```

## Beginner actions

| Command | Outcome |
| --- | --- |
| `metriplane doctor` | Checks required installation pieces separately from optional camera, GPU, and source-development capabilities. |
| `metriplane demo` | Runs the complete bundled example without opening a browser. |
| `metriplane demo --open` | Runs the example and asks the default browser to open the local report. |
| `metriplane demo --export-inputs my-cell` | Copies the bundled session and process-rule directory so they can be inspected. |

Use `metriplane <command> --help` for command-specific options. The demo export
destination must not already exist. `--export-inputs` is mutually exclusive with
`--out` and `--open`.

## Explicit recorded-run workflow

The `atlas` namespace exposes the stages used after the bundled demo. The name is
a stable technical command namespace; you do not need to learn an architecture
to use these commands.

```bash
# Check all process-rule files and cross-references.
metriplane atlas validate-pack my-cell/domain-pack

# Analyze one FrameStateModel JSONL recording into a new output directory.
metriplane atlas run \
  --session-jsonl my-cell/session.jsonl \
  --pack my-cell/domain-pack \
  --out my-cell-run

# Print the HTML report path and fail if it is missing.
metriplane atlas report --run-dir my-cell-run

# Verify the missing-tool example's checksummed incident bundle.
metriplane atlas bundle verify \
  my-cell-run/evidence_bundles/INC-0001.zip

# Rerun the missing-tool example's generated repeatable check.
metriplane atlas test \
  my-cell-run/regression_tests/INC-0001.yaml \
  --json
```

Each command exits nonzero when its required validation or verification fails.
Do not ignore the exit status in scripts or CI.

`atlas run` refuses to replace an existing output directory unless the explicit
`--overwrite` option is used. Prefer a fresh path. Use `--overwrite` only after
you have verified that the named directory is a disposable Metriplane run; it is
not a general directory-cleanup command.

The exact `INC-0001` paths above apply to the exported, unchanged missing-tool
example. A compatible run with no configured incident has no incident bundle or
regression file. A run with incidents may use different IDs; inspect the report
and output directories instead of assuming an ID.

## Portable external fixtures

If someone gives you a directory that follows External Source Contract v1, use
the directory-oriented `external` commands. They bind the manifest, normalized
session, mapping, normalization report, and domain pack together so unrelated
artifacts cannot be selected accidentally.

```bash
metriplane external validate path/to/fixture
metriplane external validate path/to/fixture --json

metriplane external run path/to/fixture \
  --out external-run
metriplane external run path/to/fixture \
  --out external-run \
  --json
```

`external run` performs the full external preflight before it calls the existing
Atlas engine. It accepts `--run-id` and the same explicit `--overwrite` control as
`atlas run`. It never downloads a referenced source or executes the historical
adapter named in the manifest.

See [Validate and run an external fixture](external-fixtures.md) for the evaluator
workflow, adapter-author requirements, provenance, and claim limits.

## Other command groups

Root help also lists replay, comparison, incident, and live-runtime functions for
existing users. They are not required for the bundled-demo promise and some have
narrower support boundaries. The Atlas workflow documented above, including its
generated regression check, is part of the v0.4.0.post1 recorded-state path. In
particular, `metriplane test` checks an incident evidence bundle against its
stored expectations, while `metriplane atlas test` runs the YAML regression spec
generated for an incident. The namespaces are intentionally different.
