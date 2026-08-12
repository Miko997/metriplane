<!--
SPDX-FileCopyrightText: NOASSERTION
SPDX-License-Identifier: MIT
-->

# robomimic Can PH position-only fixtures

This directory contains two portable compatibility fixtures derived from one
trajectory in the official robomimic Can Proficient Human (`ph`) dataset. The
incident and control variants contain the same 118 normalized snapshots and
the same operator-authored planar region. They differ only in their fixture and
domain-pack identities, relative wait, expected-outcome metadata, and hashes
that follow from those declared differences.

The fixtures do not establish official Can task success or failure. They do
not evaluate grasp state, 3D placement, orientation, physical accuracy,
simulator realism, robot safety, or general robomimic compatibility.

## License, attribution, and modification notice

The immutable dataset card declares `mit` for the public, ungated repository.
The raw and prepared files used here are in that same repository and have no
file-specific override. The normalized coordinates and compatibility metadata
in this subtree are distributed under the MIT terms recorded by the repository
REUSE metadata. This fixture-scoped treatment does not change Metriplane's
repository-wide licensing boundary.

Attribution:

- [robomimic project](https://github.com/ARISE-Initiative/robomimic/tree/d309eaecc18acf4152a830a895a6984b8ac71b05)
- [immutable robomimic dataset revision](https://huggingface.co/datasets/robomimic/robomimic_datasets/tree/74fa018461f479cd9fd15b924a16103012096203)
- [immutable dataset license declaration](https://huggingface.co/datasets/robomimic/robomimic_datasets/blob/74fa018461f479cd9fd15b924a16103012096203/README.md)

Modification notice: Metriplane did not create the source demonstrations. The
adapter selected two named prepared world-position streams, required their
correspondence to the raw artifact, projected source world X/Y without hidden
translation, rotation, scaling, or axis swapping, set normalized Z to `0.0`,
discarded orientation, applied an operator-authored polygon, and mapped each
verified source row to an exact integer timestamp. Raw HDF5, source code,
simulator assets, images, video, and model binaries are not included.

## Exact identities

| Identity | Frozen value |
| --- | --- |
| robomimic audit commit / package | `d309eaecc18acf4152a830a895a6984b8ac71b05` / `0.5.0` |
| Raw-artifact robosuite boundary | `v1.5.0` / `1a8701b90c07c6595ace4af9935d7c5ebe1baed3` |
| Prepared-artifact robosuite boundary | `v1.5.1` / `51cc01785bab80ffeed20da15e67d7dd4140e76a` |
| Dataset repository | `robomimic/robomimic_datasets` |
| Dataset revision | `74fa018461f479cd9fd15b924a16103012096203` |
| Task / dataset type | `Can` / Proficient Human (`ph`) |
| Selected episode | `demo_0` |
| Source / normalized rows | `118` / `118` |
| Adapter commit | `cfc285a3e757fdf742858b1c4cf685c384d01e8b` |
| Frozen config SHA-256 | `3cfa88b1512215d8545c1404bcc80e18bf780d1dfc899553ccc69c2517c623c5` |
| Shared session SHA-256 | `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246` |
| Incident fixture fingerprint | `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6` |
| Control fixture fingerprint | `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf` |

The referenced source bytes are:

| Artifact | Bytes | SHA-256 / LFS OID |
| --- | ---: | --- |
| `v1.5/can/ph/demo_v15.hdf5` | 64,932,974 | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` |
| `v1.5/can/ph/low_dim_v15.hdf5` | 46,889,752 | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |

The prepared file changed at an earlier mutable repository revision. These
fixtures therefore pin both the immutable dataset commit and exact content
hashes; mutable `main` is not a source identity. The frozen External Source
Contract v1 schema SHA-256 is
`b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4`.

## Raw, prepared, and normalized provenance

The source boundary is:

1. the official raw HDF5 supplies stored simulator states, embedded model XML,
   source row order, environment metadata, and correspondence witnesses;
2. the official low-dimensional HDF5 supplies prepared `obs` values;
3. the isolated adapter verifies all 200 demos and 23,207 rows before selecting
   `demo_0`; and
4. Metriplane receives only the normalized, position-only session.

Across all 200 demos, raw and prepared `num_samples`, `states`, `actions`,
`model_file`, and eight filter-membership arrays are required to agree exactly.
Actions and filters are read only for correspondence and never drive normalized
state. `ep_meta` is absent from both artifacts. The adapter consumes no
`next_obs`; this avoids importing the final observation that official
postprocessing can obtain by stepping the final action.

Each frame contains exactly two complete entities:

| Normalized entity | Atlas role | Prepared source field | Independent witness |
| --- | --- | --- | --- |
| `can_1` | `material` | `data/demo_0/obs/object[:,7:10]` | Array-exact translation from named raw `Can_joint0` qpos |
| `robot_tcp_1` | `tool` | `data/demo_0/obs/robot0_eef_pos` | Embedded-XML forward kinematics to named `gripper0_right_grip_site` |

The official observable order establishes that `object[:,7:10]` is Can world
XYZ rather than a relative vector. The TCP observable is the robot grip-site
world position. The real-source audit verified all 23,207 Can rows exactly and
the TCP stream with maximum absolute forward-kinematics error
`1.1102230246251565e-15` metres.

## Clock and information loss

The raw flattened state stores simulator time in `states[:,0]`. Every one of
the 23,007 within-demo differences across all 200 demos is `0.05 s` within
floating-point error, with no zero, repeated, dropped, or doubled interval, and
prepared states are byte-identical to raw states. The authoritative mapping is
`ts_sim_ns(i) = i * 50_000_000`, for `i = 0..117`.

The descriptive `ts` is `ts_sim_ns / 1_000_000_000`. The source rollout
horizon is not used as timing, a deadline, or a truncation rule. There is no
resampling, interpolation, carry-forward, wall-clock input, action replay, or
fabricated confidence.

Normalization copies only proven world X/Y. It deliberately discards source Z,
both complete source quaternions (including yaw, roll, and pitch), the relative
Can-to-end-effector block, robot articulation, velocities, contact/grasp state,
reward, done, success, actions, filters, annotations, and all source outcomes.
No orientation is hidden in another field.

## Operator-authored scenario

The target is an inclusive 0.04 m square centered on the selected Can's row-0
source-world XY `(0.123724912698951, -0.20150121318116285)` metres. Its ordered
vertices are:

- `(0.103724912698951, -0.22150121318116284)`;
- `(0.143724912698951, -0.22150121318116284)`;
- `(0.143724912698951, -0.18150121318116286)`; and
- `(0.103724912698951, -0.18150121318116286)`.

The zone and station are `target_xy_region` and `target_station`; the outside
label is `outside_workspace`, the boundary is inclusive, and overlap is
rejected.

> The target region is a Metriplane-authored compatibility-test rule informed by inspection of the selected source geometry. It is not the source task's official success definition.

The Can is inside at frames `0..63`. The TCP is outside initially, enters at
frame `42` (`2.10 s`), remains inside through frame `64`, and exits at frame
`65`. “Required asset missing” therefore means that the TCP entity is outside
the operator region; the entity is present in every complete snapshot.

| Variant | Relative wait | Frozen Atlas result |
| --- | ---: | --- |
| `incident` | `2.0 s` | Missing at frame 0, delayed at frame 40, present and complete at frame 42; four events, one deviation, one `missing_tool_caused_delay` incident |
| `control` | `2.5 s` | Missing at frame 0, present and complete at frame 42; three events, no deviation, no incident |

The incident ends at the `2.0 s` threshold, not at the later `2.10 s` TCP
arrival. Atlas marks this one process step complete at frame 42 and does not
reopen it, so later Can/TCP exits are intentionally inert. This is an arrival
and required-presence timing check, not continued co-occupancy or retention
monitoring. The evaluator's missing/delay event payload uses its existing
`unknown_required_asset` placeholder for `asset_type`; the required stable
asset identity remains `robot_tcp_1` in the process configuration.

Episode selection was outcome-blind only within an upstream success-filtered corpus.

The selected trajectory is not an unbiased sample of arbitrary or failing Can
behavior. Reward, done, success, filter membership, desired event counts, and
Atlas outcomes were prohibited selection criteria.

## Reproduction

Acquisition, auditing, and conversion use the isolated package under
`adapters/robomimic_lowdim/`. That environment uses direct safe HDF5 reads and
does not import robomimic, robosuite, MuJoCo, Torch, or Metriplane. Production
conversion and finalization require a clean Git checkout whose verified `HEAD`
equals the recorded adapter commit and whose adapter files equal their HEAD
blobs. See the adapter README for exact commands.

Portable validation and evaluation require only the ordinary Metriplane wheel
and its runtime dependencies:

```bash
metriplane external validate <fixture-root>/incident --json
metriplane external run <fixture-root>/incident \
  --out <incident-run> --run-id robomimic_incident --json

metriplane external validate <fixture-root>/control --json
metriplane external run <fixture-root>/control \
  --out <control-run> --run-id robomimic_control --json
```

The incident run generates one verifiable evidence bundle and one passing
generated regression. The no-incident control must generate neither.

## Claim boundary

Allowed claims are limited to this exact dataset revision, file pair, demo,
adapter commit, deterministic clock, field mapping, polygon, waits, and tested
Metriplane runtime. It is accurate to say that these bytes produce a validated
position-only fixture and the recorded incident/control outcomes without source
dependencies during portable execution.

Do not claim or imply:

- official robomimic Can success, failure, or source-outcome prediction;
- raw status for prepared observation values;
- source authorship of the polygon or waits;
- 3D pose, orientation, grasp, contact, continued retention, or task-completion
  evaluation;
- physical accuracy, calibration, simulator realism, sim-to-real validity,
  safety, certified quality, or machinery control;
- general or native robomimic compatibility beyond this trajectory;
- an unbiased corpus sample;
- source-project endorsement; or
- independent adoption, independent validation, or third-party deployment of
  Metriplane.

For the full trust map and decision record, see the
[field-provenance map](../../../docs/specs/met18-source-field-provenance.md),
[adapter audit](../../../docs/specs/robomimic-can-lowdim-adapter-audit.md),
[source-selection record](../../../docs/specs/robomimic-can-lowdim-source-selection.md),
and [rights matrix](../../../docs/specs/robomimic-can-lowdim-rights-matrix.md).
