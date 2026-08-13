<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Reproduction guide

This guide applies only to the Metriplane-authored synthetic
format-engineering path. It does not acquire or convert an external recording.

## Exact implementation identities

Start from a Metriplane checkout whose object database contains these commits:

| Component | Commit |
| --- | --- |
| Public baseline | `f8a3a48752101d74f658124e23354f0816e20a21` |
| Candidate audit | `782712f8b87c5daf237b55101594dcf91abed103` |
| Source Adapter SDK | `975fda022962b9f1f6a1b986693557600a320916` |
| Frozen ROS 2/MCAP adapter | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |

Create a clean detached worktree at the literal adapter freeze:

```sh
git fetch origin agent/met46-ros2-mcap-recorded-state-profile
git worktree add --detach ../metriplane-ros2-mcap-freeze \
  04090e510fa2bccd4fe3ac90521d3201a7c1b7c7
cd ../metriplane-ros2-mcap-freeze
git rev-parse HEAD
git status --short
```

`git rev-parse HEAD` must print
`04090e510fa2bccd4fe3ac90521d3201a7c1b7c7`, and status must be empty before
conversion.

## Isolated SDK validation

```sh
cd adapters/source_adapter_sdk
uv sync --frozen --extra test
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd ../..
```

The expected result is 146 passing tests. The SDK has no runtime dependencies.
Its schema and lock SHA-256 values are:

```text
30f42190171f9adcc51387909b738378143821c624187604a6d8d89256f103da  metriplane.source_adapter_capability.v1.schema.json
bc2aee5afdd495b57238a03e450beac1ee9344cadd1657cd6f8d8df746fcd1de  uv.lock
```

## Isolated adapter validation

```sh
cd adapters/ros2_mcap
uv sync --frozen --extra test
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
sha256sum source/metriplane-synthetic-recorded-state-v1.mcap \
  config/frozen-config.json uv.lock
```

The expected result is 101 passing tests and these three identities:

```text
c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99  metriplane-synthetic-recorded-state-v1.mcap
a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962  frozen-config.json
864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6  uv.lock
```

The source must also be exactly 28,735 bytes.

## Three clean conversions

Run conversion from the detached freeze worktree. The converter authenticates
the exact clean Git identity, source, config, lock, schemas, and source bytes
before publishing output.

```sh
ros2_mcap_runs="$(mktemp -d)"
ros2_mcap_source="$PWD/source/metriplane-synthetic-recorded-state-v1.mcap"
ros2_mcap_config="$PWD/config/frozen-config.json"
ros2_mcap_commit="04090e510fa2bccd4fe3ac90521d3201a7c1b7c7"

uv run metriplane-ros2-mcap inspect --source "$ros2_mcap_source"
for ros2_mcap_run in 1 2 3; do
  uv run metriplane-ros2-mcap convert \
    --source "$ros2_mcap_source" \
    --config "$ros2_mcap_config" \
    --adapter-commit "$ros2_mcap_commit" \
    --out "$ros2_mcap_runs/run-$ros2_mcap_run"
done

uv run metriplane-ros2-mcap finalize-equivalence \
  --conversion-root "$ros2_mcap_runs/run-1" \
  --conversion-root "$ros2_mcap_runs/run-2" \
  --conversion-root "$ros2_mcap_runs/run-3" \
  --run-id clean-conversion-1 \
  --run-id clean-conversion-2 \
  --run-id clean-conversion-3 \
  --out "$ros2_mcap_runs/final"
```

Finalization must report three byte-equivalent conversions. The canonical
conversion-tree digest is
`56a70b440f3105ae01a2913940db664008a829dae05d4442dc610aaa99b80505`.
The finalized conversion summary SHA-256 is
`bff6ff0456178798bd3d987f3c3a687b900aa0c511e571b72d06503765067218`.

## Portable fixture evaluation

Build the ordinary Metriplane wheel from the exact review head, not the adapter
freeze. Confirm the wheel contains no Source Adapter SDK, ROS 2/MCAP adapter,
MCAP library, ROS package, source MCAP, or source-specific schema. Install only
that wheel and its ordinary dependencies into a clean environment.

For each finalized incident and control fixture:

```sh
metriplane external validate path/to/fixture
metriplane external run path/to/fixture --out path/to/output
```

Run each variant three times, compare canonical state and Atlas outputs, verify
the incident evidence bundle, execute the incident regression, assert the
control remains incident-free, relocate outputs, verify again, and scan durable
files and ZIP entries for machine-local paths.

The required public matrix is Ubuntu and macOS on Python 3.12 and 3.13. Those
exact-head workflow results are pending until the review branch is published.

## Candidate audit reproduction

Candidate identities, immutable repository revisions, metadata paths, license
files, sizes, hashes, and rejection reasons are listed in
[SOURCE-CANDIDATES.md](SOURCE-CANDIDATES.md). Candidate recordings are not
conversion inputs. Reproducing their metadata inspection does not turn them
into supported sources.
