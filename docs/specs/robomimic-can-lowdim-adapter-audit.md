<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can low-dimensional adapter audit

Status: **GO boundary and fixture design frozen; adapter implementation, three
clean conversions, portable runs, evidence, regression, and CI verification
pending.**

This audit authorizes implementation of one exact source-specific boundary:
Can Proficient Human `demo_0` from the official robomimic v1.5 raw/prepared
pair. It does not authorize a universal HDF5 importer, simulator replay,
general robomimic support, or a source-success evaluator.

## 1. Frozen upstream identity

| Item | Immutable or audited identity |
| --- | --- |
| Official code repository | [`ARISE-Initiative/robomimic`](https://github.com/ARISE-Initiative/robomimic) |
| Audited current code commit | `d309eaecc18acf4152a830a895a6984b8ac71b05` |
| Latest release / tag commit | `v0.5.0` / `ae5799f0fae05c4559ee1f9645b0f77eb5251929` |
| Package version | `0.5.0` |
| Source simulator repository | [`ARISE-Initiative/robosuite`](https://github.com/ARISE-Initiative/robosuite) |
| Raw-artifact simulator identity | robosuite `1.5.0`, tag commit `1a8701b90c07c6595ace4af9935d7c5ebe1baed3` |
| Prepared-artifact simulator identity | robosuite `1.5.1`, tag commit `51cc01785bab80ffeed20da15e67d7dd4140e76a` |
| Official dataset repository | `robomimic/robomimic_datasets` |
| Immutable dataset revision | `74fa018461f479cd9fd15b924a16103012096203` |
| Task / dataset type | `Can` / Proficient Human (`ph`) |
| Selected record | `data/demo_0`, 118 source/prepared rows |

The current robomimic commit is an **audit identity**, not a claimed historical
generator. The prepared artifact does not embed its robomimic generator commit.
Release-era code documents the preparation behavior and pinned robosuite code
documents field semantics, while exact raw/prepared copies and independent raw
reconstruction bind the consumed values to the frozen raw artifact.

Primary code paths used by the audit include:

- robomimic `robomimic/scripts/dataset_states_to_obs.py` for stored-state to
  `obs` / `next_obs` alignment and copied datasets;
- robosuite `robosuite/environments/manipulation/pick_place.py` for the
  `PickPlaceCan` object observables and insertion order;
- robosuite robot-observable code that produces `robot0_eef_pos` from the named
  grip site's `sim.data.site_xpos`;
- robosuite `robosuite/controllers/parts/arm/osc.py` for Cartesian position
  limits documented in metres; and
- robosuite `robosuite/controllers/parts/controller.py` for direct assignment
  of world `site_xpos` to the controller reference position.

The exact pinned-source findings are summarized in
[`met18-lowdim-source-comparison.md`](met18-lowdim-source-comparison.md). This
adapter audit does not broaden them.

## 2. Immutable acquisition record

Acquisition date: `2026-08-12`.

```console
hf download robomimic/robomimic_datasets \
  v1.5/can/ph/demo_v15.hdf5 \
  v1.5/can/ph/low_dim_v15.hdf5 \
  --repo-type dataset \
  --revision 74fa018461f479cd9fd15b924a16103012096203 \
  --local-dir SOURCE_ROOT
```

`SOURCE_ROOT` is a placeholder, not a durable path. The adapter must accept an
operator-supplied source root, resolve the two exact relative paths, reject
source/output overlap, and omit all absolute paths from durable output.

| Artifact | Exact path | Size | SHA-256 / LFS OID |
| --- | --- | ---: | --- |
| Raw | `v1.5/can/ph/demo_v15.hdf5` | 64,932,974 | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` |
| Prepared | `v1.5/can/ph/low_dim_v15.hdf5` | 46,889,752 | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |

The raw Git pointer blob is
`169f3bb22e96a17021dab96557ebaec39336f687`; its final CDN ETag is
`822b4fae03f0862717bc8c49ca6b8e70221d9f3ca53438543f733b195ff8c6c3`.
The prepared Git pointer blob is
`e4ae06be04279b070c87f284003fe71fe4b118ee`; its final CDN ETag is
`2785b50f81fde3f7cb522e6fe9ee14b162194ebb213ce8da6a4011b58bb98adb`.

The accepted prepared body replaced an older body. The rejected older identity
is 57,589,168 bytes with SHA-256
`e5c322d12a46f0f906db6256ae716b5a2b58575e37a096a8b465e23061ac1ac2`.
The adapter must never accept it by path alone.

Source files remain outside the repository and read-only. Size and SHA-256 are
verified before HDF5 inspection and recomputed after every comparison and
conversion to prove that conversion did not mutate either file.

## 3. Raw/prepared provenance graph and comparison

```text
raw demo_v15.hdf5 (robosuite 1.5.0 metadata)
  states + actions + model_file + environment metadata
               |
               | official release-era state-to-observation process
               | under robosuite 1.5.1 semantics
               v
prepared low_dim_v15.hdf5 (robosuite 1.5.1 metadata)
  derived obs / next_obs + copied states/actions/model/source metadata
               |
               | exact copied-field comparison
               | independent raw Can and TCP witnesses
               v
selected prepared obs rows -> independent planar adapter -> portable fixture
```

The corpus-wide comparison demonstrated:

| Check | Result |
| --- | --- |
| Demo names | Exact `demo_0` through `demo_199` in both files. |
| Root `total` | `23,207` in both files. |
| Per-demo `num_samples` | Exact for 200/200 demos. |
| `states` shape, dtype, values | Array-exact for 200/200 demos. |
| `actions` shape, dtype, values | Array-exact for 200/200 demos; actions remain excluded from conversion. |
| `model_file` | Byte-exact for 200/200 demos. |
| `ep_meta` | Absent in both files for 200/200 demos. |
| Masks | Eight opaque membership arrays byte-identical; all named demos resolve. Their meanings are not conversion inputs. |
| Reward/done values | Not read. |

The raw/prepared simulator-version difference is preserved. It is not rewritten
as a single generation version.

## 4. `obs`, `next_obs`, and stored-state alignment

The official preparation path resets the simulator to stored state `t` to emit
`obs[t]`. For non-final rows it resets to stored state `t+1` for
`next_obs[t]`. At the final row no stored state `T` exists, so it steps the last
action to create final `next_obs[T-1]`.

The frozen adapter therefore:

1. consumes exactly the 118 prepared `obs` rows aligned to the 118 stored
   source states;
2. consumes no `next_obs` value;
3. never replays or integrates an action;
4. does not fabricate a 119th or `T+1` state; and
5. rejects conversion if source/prepared row counts or copied states differ.

This avoids importing the action-integrated final observation merely for
sequence symmetry.

## 5. Consumed fields and source authority

| Normalized entity | Prepared field | Exact meaning | Raw provenance witness |
| --- | --- | --- | --- |
| `can_1` material | `data/demo_0/obs/object[:,7:10]` | `Can_pos`, the Can body world XYZ in metres | Locate `Can_joint0` in the per-demo embedded XML and recover its free-joint qpos translation at `data/demo_0/states[:,31:34]`; exact equality. The named lookup, not a universal magic slice, proves the address. |
| `robot_tcp_1` tool | `data/demo_0/obs/robot0_eef_pos[:,0:3]` | Panda `gripper0_right_grip_site` world XYZ in metres | Independently parse the XML body/joint tree, apply raw hinge qpos, and evaluate the named site; all rows within `2e-12`. |

The prepared Can `object` vector is fully named and ordered: relative position
`[0:3]`, relative quaternion `xyzw` `[3:7]`, world position `[7:10]`, and
world quaternion `xyzw` `[10:14]`. Only world-position X/Y are normalized.

`robot0_eef_pos` is produced directly from the named world's
`sim.data.site_xpos`; no relative-vector field is substituted. The embedded
controller is `OSC_POSE` with world input reference frame. Pinned robosuite
source connects direct world `site_xpos` values to Cartesian limits documented
in metres without an intervening conversion. The Can body position and TCP site
position share the same right-handed MuJoCo world coordinate system.

Prepared observations remain simulator-derived. Exact Can equality and the TCP
FK equivalence are independent provenance witnesses; they do not turn `obs`
into raw source facts and do not prove that the current robomimic commit
generated the artifact.

## 6. Clock decision

Clock status: **VERIFIED**.

Both artifacts embed `control_freq=20`. Pinned robosuite flattened state starts
with simulation time, followed by qpos and qvel. Across the complete corpus,
all 200 demos begin at `0.0` and all 23,007 adjacent intervals are 0.05
simulated seconds within floating representation error. No zero, doubled,
missing, repeated, or irregular interval was found, and prepared `states` are
exact copies of raw `states`.

The exact normalized mapping is:

```text
ts_sim_ns(i) = i * 50_000_000
ts(i) = ts_sim_ns(i) / 1_000_000_000
```

For `demo_0`, frame `0` is at `0` ns and frame `117` is at
`5_850_000_000` ns. The embedded higher-rate teleoperation/controller metadata
is not the evaluation clock. The registry horizon `400` is evaluation rollout
metadata only; it is not timing, a process deadline, a truncation instruction,
or an Atlas rule.

## 7. Normalization and information loss

For both entities, source world X maps to normalized X and source world Y maps
to normalized Y in metres. Normalized Z is literal `0.0`. There is no hidden
translation, rotation, scale, axis swap, interpolation, carry-forward, or
resampling.

The adapter discards both source Z values, both complete orientations, all
quaternions, yaw, roll, pitch, relative object/TCP vectors, full robot state,
velocities, contacts, grasp state, controller state, and all outcome or visual
material. No discarded value is placed in `extra` or another entity.

Every one of 118 frames must be a complete snapshot containing exactly
`can_1` and `robot_tcp_1`. Missing, duplicate, nonfinite, partial, or ambiguous
state is fatal.

## 8. Frozen operator geometry and existing-Atlas scenario

The entire target region is Layer C. It is an inclusive square centered on the
exact float64 Can XY at prepared row 0,
`(0.123724912698951, -0.20150121318116285)` m, with half-extent `0.02` m. Its
stable vertices are:

1. `(0.103724912698951, -0.22150121318116284)`;
2. `(0.143724912698951, -0.22150121318116284)`;
3. `(0.143724912698951, -0.18150121318116286)`; and
4. `(0.103724912698951, -0.18150121318116286)`.

> The target region is a Metriplane-authored compatibility-test rule informed
> by inspection of the selected source geometry. It is not the source task's
> official success definition.

The pilot and freeze establish the natural interval required by the existing
Atlas rule:

- at row 0 the Can occupies the region and the TCP does not;
- the TCP first enters at row 42, source time `2.10` s;
- the Can first leaves at row 64;
- the incident variant allows a relative wait of `2.0` s; and
- the control variant allows a relative wait of `2.5` s.

The waits begin from the existing process condition; they are not absolute
trajectory timestamps. The incident is expected to cross the 2.0-second wait
before TCP arrival, while the control is expected to receive the TCP within
2.5 seconds. Actual Atlas event, deviation, and incident counts remain pending
verified runs and must not be invented from this pilot.

The incident and control variants must use byte-identical normalized sessions,
entity mappings, source identities, field maps, coordinate maps, clocks, and
polygons. Permitted differences are variant/domain-pack identifiers, the
relative wait, expected-outcome metadata, and hashes resulting from those
declared differences.

The frozen adapter configuration names adapter
`org.metriplane.robomimic_lowdim`, source backend
`external:robomimic_lowdim_prepared_obs`, and has SHA-256
`dc01dd3f300be3d660216bc07a0df67b3c57fc88416032fd54a2974abe964017`.
The incident fixture/domain-pack IDs are
`robomimic-can-ph-demo-0-planar-incident-v1` and
`robomimic-can-ph-planar-incident-v1`; the control IDs are
`robomimic-can-ph-demo-0-planar-control-v1` and
`robomimic-can-ph-planar-control-v1`. Conversion must reject configuration
drift. Fixture and domain-pack content hashes remain pending generation.

## 9. Isolated adapter architecture

The allowed implementation boundary is:

```text
adapters/robomimic_lowdim/
  pyproject.toml
  uv.lock
  README.md
  src/robomimic_lowdim/
  tests/
```

It may use its own locked `h5py` and `numpy` dependencies. It must not import
robomimic, robosuite, MuJoCo, Torch, or the source simulator. Standard-library
XML parsing and independently authored forward kinematics may implement the raw
TCP witness. No adapter or adapter dependency enters the ordinary Metriplane
wheel.

The source-specific commands should implement immutable acquisition metadata,
safe inspection, fail-closed raw/prepared comparison, and deterministic
conversion. HDF5 opening must not permit pickle or arbitrary code execution.
Output/source overlap, unsafe paths, changed hashes, source mutation, and
overwrite without explicit authorization must be rejected. JSON command output
must be deterministic and must not expose absolute paths.

The portable fixture contains normalized JSON/YAML/CSV and deterministic
provenance records only. It requires the ordinary installed Metriplane wheel,
not the adapter or any source framework.

## 10. Outcome, annotation, and action exclusion

Rewards, dones, success/failure signals, filter meanings, annotations, desired
outcomes, policy actions, `next_obs`, subtask labels, horizon, and episode-end
metadata are not incident truth and do not feed conversion, geometry, waits, or
episode selection. Actions are compared only to establish raw/prepared copy
identity; conversion does not read them to reconstruct state.

Episode selection was outcome-blind only within an upstream success-filtered
corpus.

The official PH corpus contains 200 successful trajectories from one RoboTurk
operator. This fixture is therefore neither an unbiased sample nor evidence
about arbitrary Can behavior or failures.

## 11. Required implementation and adversarial verification

The following work is required and is **pending** unless a later dated section
records exact evidence:

- fail-closed tests for wrong repository/dataset revision, both wrong hashes,
  old prepared body, demo mismatch, count/state/action/model mismatch, malformed
  HDF5, unexpected key/shape, missing entity, nonfinite value, relative/world
  confusion, unknown units/frame/frequency, incomplete snapshots, unsafe paths,
  source/output overlap, mutation, overwrite, local-path leaks, and
  incident/control state mismatch;
- anti-taint mutation of rewards, dones, success/failure fields, masks/actions,
  episode metadata, horizon, `next_obs`, and excluded quaternions with
  byte-identical normalized state and unchanged Atlas semantics;
- three clean source conversions into separate roots with canonical or byte
  identity for every durable artifact and unchanged source hashes;
- three clean incident runs and three clean control runs from the exact branch
  wheel, with semantic equivalence, evidence/regression verification where
  applicable, and no fabricated control evidence;
- installed-wheel portability without source dependencies, relocation checks,
  ZIP/content path-leak scans, and the requested OS/Python matrix where
  practical; and
- root-package protection, prior-proof immutability, generic-fixture
  regression, and CI verification.

## 12. Audit conclusion and claims

The source, rights, field, clock, raw/prepared, entity, and planar gates support
implementation of this exact one-demo boundary. No schema change, Atlas branch,
action replay, source outcome, source dependency, or new incident type is
needed.

Allowed after this audit, before implementation verification:

- the exact raw/prepared pair is immutable and internally corresponding;
- the two consumed prepared position streams have complete independent raw
  witnesses;
- the exact fixed-step clock is evidenced; and
- the frozen trajectory naturally supports the proposed bounded planar rule.

Not yet allowed:

- that a portable fixture, deterministic three-conversion result, Atlas
  incident/control result, evidence bundle, regression, wheel matrix, CI result,
  PR-ready implementation, or general robomimic adapter has been demonstrated;
- that planar occupancy equals official Can success or failure;
- that source or simulator state is physically accurate or safety qualified;
  or
- that robomimic, robosuite, Hugging Face, or any source maintainer endorses
  Metriplane.
