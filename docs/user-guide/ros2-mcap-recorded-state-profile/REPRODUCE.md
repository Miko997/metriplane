<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Reproduction guide

This guide applies to the Metriplane-authored synthetic format-engineering path.
It does not acquire or convert an external recording.

## Isolated SDK validation

```sh
cd adapters/source_adapter_sdk
uv sync --frozen --extra test
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Validate the capability schema and the post-hoc ManiSkill and robomimic records.
The SDK has no runtime dependencies.

## Isolated adapter validation

```sh
cd adapters/ros2_mcap
uv sync --frozen --extra test
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Use the adapter's CLI help to obtain the exact generate, inspect, convert, and
finalize commands supported by the frozen implementation. Generate the
Metriplane-authored MCAP once, verify its byte size and SHA-256, then convert it
three times into three clean output directories with the same frozen config,
lock, and adapter implementation commit.

Finalization must require byte or SHA-256 equality for every declared conversion
output. It must reject a missing, extra, or unequal artifact.

## Portable fixture evaluation

Build the ordinary Metriplane wheel from the same exact branch head. Inspect the
wheel and confirm that it contains no Source Adapter SDK, ROS2/MCAP adapter,
MCAP library, ROS package, source MCAP, or source-specific schema.

Install only that wheel and its ordinary dependencies into a clean environment.
For each finalized incident and control fixture:

```sh
metriplane external validate path/to/fixture
metriplane external run path/to/fixture --out path/to/output
```

Run each variant three times, compare canonical state and Atlas outputs, verify
evidence bundles, execute generated regressions, relocate the output, verify it
again, and scan durable files and ZIP entries for machine-local paths.

The required portable matrix is Ubuntu and macOS on Python 3.12 and 3.13.

## Candidate audit reproduction

Candidate identities, immutable repository revisions, metadata paths, license
files, sizes, hashes, and rejection reasons are listed in
[SOURCE-CANDIDATES.md](SOURCE-CANDIDATES.md). Candidate recordings are not
conversion inputs. Reproducing their metadata inspection does not turn them into
supported sources.

## Pending freeze values

Final commands and output identities are complete only after the adapter freeze
commit and generated fixtures stabilize. [READINESS.md](READINESS.md) lists the
values that must replace the explicit pending state before review readiness.

