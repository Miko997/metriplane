<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can PH low-dimensional adapter

This isolated package converts exactly one pinned official robomimic Can
Proficient Human trajectory into Metriplane External Source Contract v1 bundles.
It is intentionally not a general HDF5 importer. It imports no robomimic,
robosuite, MuJoCo, Torch, or Metriplane module and never replays actions.

The source pair is fixed to
`robomimic/robomimic_datasets@74fa018461f479cd9fd15b924a16103012096203`:

- raw `v1.5/can/ph/demo_v15.hdf5`, 64,932,974 bytes,
  SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d`;
- prepared `v1.5/can/ph/low_dim_v15.hdf5`, 46,889,752 bytes,
  SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962`.

Only `data/demo_0/obs/object[:,7:10]` (Can world position) and
`data/demo_0/obs/robot0_eef_pos` (TCP world position) enter normalized state.
They remain explicitly prepared observations. Conversion first requires, for
all 200 demos and 23,207 rows:

- exact raw/prepared `states`, `actions`, `model_file`, `num_samples`, and mask
  correspondence;
- a 20 Hz raw `states[:,0]` clock aligned one row per source control step;
- array-exact agreement between the prepared Can stream and the named
  `Can_joint0` raw-qpos translation;
- agreement within `2e-12` m between the prepared TCP stream and independently
  authored forward kinematics over the embedded XML tree to the named
  `gripper0_right_grip_site`.

Reward, done, actions, filters, interventions, annotations, `next_obs`, and all
source outcomes are excluded from output semantics. Actions are compared only
as a raw/prepared identity witness. Source Z, orientation, and the relative
object-to-end-effector block are discarded. Every output frame is a complete
two-entity, position-only planar snapshot.

## Environment and commands

From this directory:

```sh
uv sync --frozen --extra test
uv run robomimic-lowdim acquire --out /safe/source-root --json
uv run robomimic-lowdim inspect \
  --raw /safe/source-root/v1.5/can/ph/demo_v15.hdf5 \
  --prepared /safe/source-root/v1.5/can/ph/low_dim_v15.hdf5 --json
uv run robomimic-lowdim compare-raw-prepared \
  --raw /safe/source-root/v1.5/can/ph/demo_v15.hdf5 \
  --prepared /safe/source-root/v1.5/can/ph/low_dim_v15.hdf5 --json
uv run robomimic-lowdim convert \
  --raw /safe/source-root/v1.5/can/ph/demo_v15.hdf5 \
  --prepared /safe/source-root/v1.5/can/ph/low_dim_v15.hdf5 \
  --config config/frozen-config.json \
  --out /safe/clean-conversion-1 \
  --adapter-commit 0123456789abcdef0123456789abcdef01234567 --json
```

Run conversion three times into separate empty roots, then finalize only if all
fixture bytes agree:

```sh
uv run robomimic-lowdim finalize-equivalence \
  --conversion-root /safe/clean-conversion-1 \
  --conversion-root /safe/clean-conversion-2 \
  --conversion-root /safe/clean-conversion-3 \
  --run-id real-source-clean-1 \
  --run-id real-source-clean-2 \
  --run-id real-source-clean-3 \
  --out /safe/final-fixture --json
```

Each acquisition URL and API call uses the immutable dataset revision. Existing
output is refused unless `--overwrite` is explicit. Source/config/output
symlinks, HDF5 soft/external links, source/output overlap, unexpected schemas,
unknown frames or units, checksum drift, source mutation, and nonfinite data are
rejected.

## Claim boundary

The polygon is a Metriplane-authored 0.04 m square centered on demo_0 row-0 Can
XY; the 2.0 s incident and 2.5 s control waits are operator-configured rules.
They are not robomimic or robosuite task-success definitions. The incident and
control share byte-identical normalized state and differ only in declared
operator rule identity/wait and downstream hashes.

Episode selection was outcome-blind only within an upstream success-filtered
corpus. This one trajectory does not establish general robomimic compatibility,
physical or simulator accuracy, safety, quality, independent adoption,
endorsement, or official source-task success. Portable evaluation uses only the
ordinary Metriplane wheel; this adapter and its source dependencies are needed
only for acquisition, audit, and conversion.
