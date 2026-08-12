<!--
SPDX-FileCopyrightText: NOASSERTION
SPDX-License-Identifier: MIT
-->

# robomimic Can PH example

This example evaluates one pinned low-dimensional trajectory from the
[robomimic](https://github.com/ARISE-Initiative/robomimic) Can Proficient Human
dataset. It includes an incident fixture and a control fixture built from the
same 118-frame position stream.

| Fixture | Rule | Result |
| --- | --- | --- |
| `incident` | TCP must reach the region within `2.0 s` | 4 events, 1 deviation, 1 `missing_tool_caused_delay` incident |
| `control` | TCP must reach the region within `2.5 s` | 3 events, no deviation, no incident |

The region and wait limits are Metriplane scenario inputs. They are not
robomimic task labels or success criteria.

## Run the fixtures

With Metriplane installed, run these commands from the repository root:

```bash
metriplane external validate \
  examples/external_sources/robomimic_lowdim/incident --json

metriplane external run \
  examples/external_sources/robomimic_lowdim/incident \
  --out robomimic-incident-run \
  --run-id robomimic_incident \
  --json

metriplane external validate \
  examples/external_sources/robomimic_lowdim/control --json

metriplane external run \
  examples/external_sources/robomimic_lowdim/control \
  --out robomimic-control-run \
  --run-id robomimic_control \
  --json
```

The incident run produces one verifiable evidence bundle and one generated
regression. The control run produces neither. Portable evaluation uses only the
ordinary Metriplane installation; robomimic, robosuite, MuJoCo, the adapter, and
the source HDF5 files are not runtime dependencies.

## What was converted

The fixture uses `demo_0` from an immutable revision of the official
`robomimic/robomimic_datasets` repository:

| Item | Pinned identity |
| --- | --- |
| Dataset revision | `74fa018461f479cd9fd15b924a16103012096203` |
| Raw file | `v1.5/can/ph/demo_v15.hdf5` |
| Raw SHA-256 | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` |
| Prepared file | `v1.5/can/ph/low_dim_v15.hdf5` |
| Prepared SHA-256 | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |
| Adapter commit | `cfc285a3e757fdf742858b1c4cf685c384d01e8b` |
| Shared session SHA-256 | `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246` |
| Incident fingerprint | `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6` |
| Control fingerprint | `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf` |

Each frame contains two entities:

- `can_1`, from the prepared Can world-position stream;
- `robot_tcp_1`, from the prepared robot end-effector world-position stream.

The adapter checks both streams against the raw simulator state and embedded
model data before conversion. Metriplane copies world X/Y, sets normalized Z to
`0.0`, and uses the verified `50 ms` source interval. Source Z, orientation,
robot articulation, actions, rewards, done flags, success labels, and source
outcomes are not part of the normalized session.

The two fixtures contain the same session. Only the declared wait rule and the
metadata and hashes caused by that rule differ.

## Attribution and modification notice

The pinned dataset revision declares the dataset under the MIT license:

- [immutable dataset revision](https://huggingface.co/datasets/robomimic/robomimic_datasets/tree/74fa018461f479cd9fd15b924a16103012096203)
- [license declaration at that revision](https://huggingface.co/datasets/robomimic/robomimic_datasets/blob/74fa018461f479cd9fd15b924a16103012096203/README.md)
- [robomimic source revision](https://github.com/ARISE-Initiative/robomimic/tree/d309eaecc18acf4152a830a895a6984b8ac71b05)

The derived fixture files in this subtree are distributed under MIT, as
recorded in the repository's REUSE metadata.

Metriplane did not create the source demonstration. This directory contains
modified, normalized numeric state plus Metriplane-authored fixture metadata and
rules. Raw HDF5, source-framework code, simulator assets, images, video, and
model binaries are not included.

## Scope

This is one position-only trajectory selected from an upstream
success-filtered corpus. Episode selection did not use rewards, done flags,
success labels, filter membership, desired event counts, or Atlas outcomes.

The example demonstrates the recorded conversion and evaluation boundary only.
It does not establish official Can task success or failure, general robomimic
compatibility, 3D placement or grasp correctness, physical or simulator
accuracy, safety, independent adoption, or robomimic endorsement.

Detailed records:

- [field provenance](../../../docs/specs/met18-source-field-provenance.md)
- [adapter audit](../../../docs/specs/robomimic-can-lowdim-adapter-audit.md)
- [source selection](../../../docs/specs/robomimic-can-lowdim-source-selection.md)
- [rights matrix](../../../docs/specs/robomimic-can-lowdim-rights-matrix.md)
