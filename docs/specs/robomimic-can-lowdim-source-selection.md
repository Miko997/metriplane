<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can low-dimensional source-selection record

Status: **source identity, outcome-blind selection, geometry, clock, entity map,
and operator waits frozen; conversion and run verification pending.**

## 1. Predeclared selection rule

> Select the lowest numeric demo satisfying every predeclared structural,
> finiteness, completeness, entity-identity, raw/prepared correspondence,
> timing, rights, and non-degenerate planar-fit criterion.

The allowed checks were declared before reading source outcomes or Atlas
results:

1. the same numeric demo exists in the raw and prepared files;
2. both demo groups declare the same sample count;
3. source `states`, `actions`, `model_file`, and required structural metadata
   correspond exactly where official preparation should copy them;
4. the named prepared Can and TCP world-position fields exist with the expected
   fully proven shapes, component order, dtype, frame, and units;
5. all required values are finite and every retained row can become one complete
   two-entity snapshot;
6. the named Can and TCP identities remain stable for the complete demo;
7. each consumed prepared position has a valid independent witness from raw
   state and the embedded per-demo model;
8. the source clock is verified and every retained row is one source control
   step without gaps, repetition, subsampling, or irregularity;
9. the source and target planar regions can be distinguished without images,
   outcome labels, or a misleading coordinate transform;
10. the Can has non-degenerate world-XY motion; and
11. the immutable source identity, dataset grant, and modified-data publication
    treatment pass the rights gate.

Prohibited selection inputs were reward, done, success, failure, task
completion, good/bad label, filter meaning, desired incident, desired event
count, desired Atlas outcome, and convenient wait timing. Actions were compared
only as copied provenance bytes; their values and meanings were not selection
criteria and are not conversion inputs.

## 2. Frozen source inventory

| Property | Value |
| --- | --- |
| Dataset repository | `robomimic/robomimic_datasets` |
| Immutable revision | `74fa018461f479cd9fd15b924a16103012096203` |
| Raw artifact | `v1.5/can/ph/demo_v15.hdf5`, 64,932,974 bytes, SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` |
| Prepared artifact | `v1.5/can/ph/low_dim_v15.hdf5`, 46,889,752 bytes, SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |
| Raw demo names | Exact `demo_0` through `demo_199` |
| Prepared demo names | Exact `demo_0` through `demo_199` |
| Root sample total | `23,207` in both artifacts |
| Corpus description | 200 successful Can trajectories from one RoboTurk operator |

All 200 demos were structurally inventoried to prove name, count, copied-state,
copied-action, embedded-model, and opaque-mask correspondence. Reward and done
values were not read. The selection algorithm evaluates candidates in numeric
order and stops when the lowest candidate passes every declared criterion; it
does not rank later candidates.

## 3. Selected record

`demo_0` is the lowest numeric candidate and passed every predeclared gate.

| Field | Frozen value |
| --- | --- |
| Raw HDF5 group | `data/demo_0` in `demo_v15.hdf5` |
| Prepared HDF5 group | `data/demo_0` in `low_dim_v15.hdf5` |
| Raw `num_samples` / prepared `num_samples` | `118` / `118` |
| Raw `states` | shape `(118, 71)`, dtype `float64`; exact prepared copy |
| Raw `actions` | shape `(118, 7)`, dtype `float64`; exact prepared copy, excluded from selection semantics and conversion |
| Prepared Can field | `obs/object`, shape `(118, 14)`, dtype `float64`, finite; consume only `[7:10]` |
| Prepared TCP field | `obs/robot0_eef_pos`, shape `(118, 3)`, dtype `float64`, finite |
| Normalized frames | `118`, one per prepared `obs` row and stored source state |
| First frame | row `0`, `ts_sim_ns=0` |
| Last frame | row `117`, `ts_sim_ns=5_850_000_000` |

Descriptive geometry from the selected source record:

| Value | Audit display in metres |
| --- | --- |
| Can first world XYZ | `[0.1237249127, -0.2015012132, 0.8600000000]` |
| Can final world XYZ | `[0.2008898308, 0.3489171369, 0.8601717125]` |
| Can first-to-final XY displacement | `0.5558010298` |
| TCP first world XYZ | `[-0.0655735877, -0.0858587773, 0.9929706124]` |
| TCP final world XYZ | `[0.1910255357, 0.3289658572, 1.0142795811]` |
| TCP first-to-final XY displacement | `0.4877730902` |

These rounded values are audit displays. The converter must retain the exact
float64 prepared X/Y values when producing normalized frames and when deriving
the frozen row-0-centered polygon.

## 4. Raw/prepared correspondence gate

For `demo_0`, raw and prepared sample count, `states`, `actions`, and
`model_file` correspond exactly. The consumed prepared Can world XYZ is
array-exact to the named `Can_joint0` free-joint translation recovered from raw
state. The consumed TCP world XYZ matches independent named-site forward
kinematics from raw state and the embedded model with maximum absolute error
`1.1102230246251565e-15`, far inside the frozen `2e-12` audit tolerance.

The selected rows are prepared `obs` rows, not raw values. The independent
witnesses establish their relation to raw state; they do not change the
prepared classification or assert a missing historical generator identity.

`next_obs` is excluded. In the official preparation behavior, final
`next_obs[T-1]` is produced by stepping the final action because no stored state
`T` exists. Selection and conversion retain exactly the 118 `obs` rows aligned
to the 118 stored source states and add no action-integrated final frame.

## 5. Clock and horizon accounting

Both artifacts embed `control_freq=20`, and raw flattened state records
simulator time as its first scalar. Across the corpus all adjacent row intervals
are 0.05 simulated seconds within floating representation error, with no
missing, repeated, doubled, or irregular step. Prepared states are exact raw
copies.

The selected record therefore uses:

```text
ts_sim_ns(i) = i * 50_000_000, for i = 0..117
```

The robomimic Can PH rollout horizon `400` is evaluation metadata only. It did
not select or truncate `demo_0`, is not elapsed time, is not a process deadline,
and does not set either operator wait.

## 6. Planar-fit criterion and post-selection freeze

After `demo_0` passed the outcome-blind selection rule, a pilot inspected only
the named Can/TCP world-XY streams to determine whether an honest existing-Atlas
rule was possible. It did not read reward, done, success, filter meaning,
actions, task completion, or Atlas results.

The pilot found:

- the Can is in a 0.02 m half-extent square centered on its row-0 XY;
- the TCP is outside that square at row 0;
- the TCP first enters at row 42, `2.10` simulated seconds; and
- the Can first leaves at row 64.

The following Layer-C decisions are now frozen:

| Rule | Frozen value |
| --- | --- |
| Material | `can_1` |
| Required tool | `robot_tcp_1` |
| Polygon center | Exact prepared `obs/object[0,7:9]` float64 Can XY: `(0.123724912698951, -0.20150121318116285)` m |
| Polygon | Inclusive axis-aligned square; half-extent `0.02` m; stable vertices `(0.103724912698951, -0.22150121318116284)`, `(0.143724912698951, -0.22150121318116284)`, `(0.143724912698951, -0.18150121318116286)`, and `(0.103724912698951, -0.18150121318116286)` |
| Transform | World X to X, world Y to Y, metres; no translation, rotation, scaling, or axis swap |
| Outside / overlap policy | Explicit `outside_workspace`; reject overlap or ambiguous assignment |
| Incident relative wait | `2.0` s |
| Control relative wait | `2.5` s |

> The target region is a Metriplane-authored compatibility-test rule informed
> by inspection of the selected source geometry. It is not the source task's
> official success definition.

The polygon and waits were frozen after selection. They were not selection
criteria. They may not be tuned after final conversion to obtain a preferred
incident or control result. If the exact Atlas outcome differs from the pilot
expectation, the actual frozen result must be preserved.

## 7. Rejection and non-selection record

No lower demo exists, and no candidate was rejected before `demo_0` passed.
`demo_1` through `demo_199` were not ranked by motion, outcome, event timing,
or convenience and were not alternatives after the first candidate passed.
Their corpus-wide structural inventory supports the raw/prepared audit only.

The selection does not show that `demo_0` is representative of failures,
arbitrary operators, arbitrary Can trajectories, or robomimic generally.

Episode selection was outcome-blind only within an upstream success-filtered
corpus.

## 8. Freeze integrity and pending evidence

The following values may not change merely to obtain a desired Atlas result:

- repository and dataset identities;
- both artifact paths, sizes, and hashes;
- `demo_0` and its 118-row accounting;
- named prepared fields and independent raw witnesses;
- exact row-index clock;
- entity IDs and roles;
- identity world-XY mapping and complete Z/orientation loss;
- exact row-0-centered inclusive polygon and half-extent;
- relative incident/control waits; and
- exclusion of outcomes, actions, `next_obs`, horizon, and annotations.

Pending implementation evidence includes the frozen adapter-config hash,
incident/control session hash, fixture fingerprints, anti-taint results, three
clean conversion identities, Atlas event/deviation/incident accounting, three
run equivalence, evidence/regression verification, installed-wheel results,
path-leak scan, and CI results. This record must be extended with exact values
after those gates pass; none is claimed by the source selection alone.
