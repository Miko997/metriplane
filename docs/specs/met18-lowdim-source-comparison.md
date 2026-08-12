<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-18 low-dimensional source comparison

Status: **robomimic GO; it is the first candidate in the approved order to
pass. MimicGen inspection stopped at PARTIAL, and RoboCasa was not inspected.**

Decision date: 2026-08-12

This record freezes the Phase-0 source decision before adapter or fixture
implementation. It does not claim general robomimic compatibility. It identifies
one immutable Can Proficient Human raw/prepared pair and one outcome-blind
candidate trajectory that can be tested through the unchanged External Source
Contract v1.

## 1. Start gate and timebox

| Item | Audited result |
| --- | --- |
| Expected baseline | `a8b67d58e00f7fcb9b090b2c95475d51b0ede81c` |
| Actual `origin/main` | `a8b67d58e00f7fcb9b090b2c95475d51b0ede81c` |
| Did `main` advance? | No |
| Starting tree | Clean |
| Branch | `agent/met18-lowdim-source-fixture` |
| MET-16 | Done |
| MET-17 | Done |
| MET-18 | No blocker; marked In Progress before Phase 0 |
| ManiSkill proof tag | `maniskill-pickcube-proof-v1` -> `49c3b37057312c89db030386dd2cc68628d92458` |
| CALVIN audit | Present on `main`; SHA-256 `e87fb2ee2509afba9633683074a7786325a3104619905a6129dda12655747388` |
| External commands | `metriplane external validate` and `metriplane external run` present |
| External Source Contract v1 schema | SHA-256 `b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4` |
| FrameStateModel | Version `1.0`, unchanged |

The audit started at `2026-08-12T11:47:53Z`. The final robomimic Phase-0
decision was recorded at `2026-08-12T12:18:20Z`, approximately 31 minutes of
parallel active audit. This is within the two-hour maximum. Direct HDF5
inspection preceded any simulator work. No source framework was installed, no
maintainer was contacted, and MET-19 was not started.

The exact raw/prepared pair used 111,822,726 bytes of the two-gigabyte download
budget. No MimicGen or RoboCasa body was downloaded.

## 2. Ordered comparison result

The vocabulary in this table is factual rather than promotional. No weighted or
promotional score is used.

| Order | Candidate | Status | Rights | Clock | Fields and raw relationship | Planar fit | Disposition |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | robomimic Can PH, official v1.5 pair | **GO** | Dataset MIT at immutable revision; modified numeric-state publication supported with notice | **VERIFIED** from artifact-native simulator time and pinned source semantics | Prepared Can and TCP world positions independently reproduced from raw state/model for all 23,207 rows | **VERIFIED in pilot** for lowest numeric `demo_0` | Implement this candidate only |
| 2 | MimicGen Square D0 human source | **PARTIAL** | Dataset CC BY 4.0; code is separately NVIDIA noncommercial-licensed | Not completed | Hosted human source has no official raw/prepared pair; original v1.2-to-v1.4 postprocessing lineage is not immutable | Not inspected from bytes | Inspection halted when robomimic reopened as GO |
| 3 | RoboCasa / RoboCasa365 explicit state | **NOT INSPECTED** | Not inspected | Not inspected | Not inspected | Not inspected | **NOT APPLICABLE** after first-candidate GO |
| 4 | Another source | **NOT APPLICABLE** | Owner approval not requested | Not applicable | Not applicable | Not applicable | Forbidden because an approved candidate passed |

Robomimic temporarily received a provisional NO-GO during the clock audit. The
decision was reopened before this comparison was frozen when the raw flattened
states were proven to contain exact simulator time and the two consumed prepared
fields were independently reconstructed from raw state. The clock, unit, and
provenance gates were closed with stronger evidence; no gate was weakened.

## 3. Robomimic exact source identity

| Property | Frozen value |
| --- | --- |
| Official code repository | [`ARISE-Initiative/robomimic`](https://github.com/ARISE-Initiative/robomimic) |
| Audited current commit | `d309eaecc18acf4152a830a895a6984b8ac71b05` |
| Latest release | `v0.5.0` |
| Release tag commit | `ae5799f0fae05c4559ee1f9645b0f77eb5251929` |
| Package version | `0.5.0` |
| Code license | MIT |
| Source simulator repository | [`ARISE-Initiative/robosuite`](https://github.com/ARISE-Initiative/robosuite) |
| Raw metadata simulator | robosuite `1.5.0`, tag commit `1a8701b90c07c6595ace4af9935d7c5ebe1baed3` |
| Prepared metadata simulator | robosuite `1.5.1`, tag commit `51cc01785bab80ffeed20da15e67d7dd4140e76a` |
| Official dataset repository | `robomimic/robomimic_datasets` |
| Immutable dataset revision | `74fa018461f479cd9fd15b924a16103012096203` |
| Task | `Can` / embedded environment `PickPlaceCan` |
| Dataset type | Proficient Human, `ph` |
| Corpus | 200 successful trajectories from one RoboTurk operator |

The current code registry names the canonical Hugging Face repository. Older
documentation links the legacy `amandlek/robomimic` alias, which redirects to
the canonical repository. Durable identity uses the canonical repository and
immutable revision, never either repository's mutable `main`.

The robomimic registry's Can PH horizon is 400. Pinned source calls this an
**evaluation rollout horizon**. It is not source timing, a process deadline, a
trajectory truncation rule, or an Atlas rule.

## 4. Dataset files, rights, and acquisition

| Property | Raw artifact | Prepared artifact |
| --- | --- | --- |
| Path | `v1.5/can/ph/demo_v15.hdf5` | `v1.5/can/ph/low_dim_v15.hdf5` |
| Meaning | Raw flattened MuJoCo states, actions, embedded models, and collection metadata | Simulator-derived low-dimensional `obs` / `next_obs` plus copied state and source fields |
| Size | 64,932,974 bytes | 46,889,752 bytes |
| Body SHA-256 / LFS OID | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |
| Git pointer blob | `169f3bb22e96a17021dab96557ebaec39336f687` | `e4ae06be04279b070c87f284003fe71fe4b118ee` |
| Xet hash / final CDN ETag | `822b4fae03f0862717bc8c49ca6b8e70221d9f3ca53438543f733b195ff8c6c3` | `2785b50f81fde3f7cb522e6fe9ee14b162194ebb213ce8da6a4011b58bb98adb` |
| Last file commit | `941a36d895a49f847804566c3a24be1ff46546cb` | `c87faeff743603b2d1fbcf993dc08ca2a620c8a8` |

The immutable dataset card declares `license: mit`; the repository is public
and ungated, and no path-specific terms override that declaration. Raw and
prepared artifacts therefore share the repository-level MIT grant. Publishing
a modified numeric-state derivative is supported when the MIT notice,
attribution, immutable source identity, and modified-data notice are retained.
Embedded model XML, simulator assets, source code, images, and video will not be
redistributed in the portable fixture.

The prepared file was replaced on 2025-04-13. The prior body was 57,589,168
bytes with SHA-256
`e5c322d12a46f0f906db6256ae716b5a2b58575e37a096a8b465e23061ac1ac2`.
No older prepared identity is accepted. The current immutable revision and
current 46,889,752-byte hash are frozen together.

Pinned acquisition, performed on 2026-08-12, was equivalent to:

```console
hf download robomimic/robomimic_datasets \
  v1.5/can/ph/demo_v15.hdf5 \
  v1.5/can/ph/low_dim_v15.hdf5 \
  --repo-type dataset \
  --revision 74fa018461f479cd9fd15b924a16103012096203 \
  --local-dir SOURCE_ROOT
```

Both bodies were hashed before inspection and remained outside the repository.
All subsequent conversion must reject any different byte count or hash.

## 5. Raw/prepared relationship

The official preparation algorithm in
`robomimic/scripts/dataset_states_to_obs.py` resets an environment to stored
state 0, emits `obs[0]`, resets to each later stored state to produce subsequent
observations, and copies source `states` and `actions`. Its final
`next_obs[T-1]` is different: the script steps `actions[T-1]` because no stored
state `T` exists.

Accordingly, the admissible sequence is exactly the `T` prepared `obs` rows
corresponding to the `T` stored source states. No `next_obs` value, action replay,
or fabricated `T+1` state is permitted.

The hosted prepared artifact does not embed a robomimic generator commit. This
record does not assert that `d309eae...`, `v0.5.0`, or any other unrecorded
commit historically generated it. Instead, it establishes the narrower and
testable provenance boundary needed by the fixture:

1. freeze both official file bodies;
2. prove every source field that official preparation should copy is equal;
3. identify the release-era algorithm and pinned simulator field semantics;
4. independently reconstruct every consumed prepared coordinate from raw state
   and the per-demo embedded model; and
5. reject any prepared value that fails that raw-state witness.

The corpus-wide comparison found:

| Check | Result |
| --- | --- |
| Demo names | Exact `demo_0` through `demo_199` in both files |
| Root `total` | 23,207 in both files |
| Per-demo `num_samples` | Equal for 200/200 demos |
| `states` shape, dtype, and values | Array-exact for 200/200 demos |
| `actions` shape, dtype, and values | Array-exact for 200/200 demos |
| `model_file` | Byte-exact for 200/200 demos |
| `ep_meta` | Absent in both for 200/200 demos |
| Mask key set and opaque membership arrays | Eight arrays byte-identical; every name resolves |
| Reward/done values | Not read |

The raw artifact declares robosuite 1.5.0 while the prepared artifact declares
1.5.1. This is preserved as an intentional collection/preparation version
boundary, not normalized into one source version.

## 6. Source-authoritative field semantics

The smallest entity set is the manipulated Can as `material` and the Panda
grip-site / TCP as `tool`.

| Entity | Prepared HDF5 path | Prepared semantics | Independent raw witness | Status |
| --- | --- | --- | --- | --- |
| Can | `data/<demo>/obs/object[:, 7:10]` | `Can_pos`: MuJoCo world body XYZ | Locate named `Can_joint0` in embedded XML, calculate its qpos address, and read its free-joint translation from raw `states` | VERIFIED; array-exact for 23,207/23,207 rows |
| TCP | `data/<demo>/obs/robot0_eef_pos[:, 0:3]` | Panda `gripper0_right_grip_site` world XYZ | Independently parse the embedded XML body/joint tree and apply raw hinge qpos through forward kinematics to the named site | VERIFIED; 23,207/23,207 rows within `2e-12` absolute tolerance |

Pinned robosuite `PickPlaceCan` fixes single-object mode to Can. It inserts
active object observables in this order, and the base environment concatenates
the object modality in insertion order:

| `obs/object` slice | Meaning | Fixture use |
| --- | --- | --- |
| `[0:3]` | Can position relative to the end effector | Excluded; not world coordinates |
| `[3:7]` | Can-to-end-effector relative quaternion, `xyzw` | Excluded |
| `[7:10]` | Can world body position | X/Y retained; Z discarded |
| `[10:14]` | Can world quaternion, `xyzw` | Excluded |

Robosuite produces `robot0_eef_pos` directly from the named grip site's
`sim.data.site_xpos`, and robomimic preserves robot-prefixed observations. The
prepared field is simulator-derived, not raw. Its independent reconstruction
uses neither robosuite nor robomimic, never steps an action, and produced:

- maximum TCP absolute error: `1.1102230246251565e-15`;
- TCP RMSE: `2.3609042912280844e-16`;
- reconstructed TCP stream SHA-256:
  `3e878face68a437d4cb334fba19276eb7b00b2a3828bbecc3d7e856a02e98227`;
- raw-derived Can stream SHA-256:
  `536cc7e0b6fb1185cc27716d41b02742fee3c62b9be8d70cb066ce26d7e8cb36`.

The artifact metadata selects `OSC_POSE` with world input reference frame.
Pinned robosuite source documents OSC Cartesian position limits in metres,
assigns the same world `site_xpos` directly to the controller reference
position, and adds Cartesian deltas without unit conversion. MuJoCo requires a
model to use one consistent length unit, so the same embedded model's world
body and site positions are metres. World X and Y are therefore suitable for
an identity metric mapping.

## 7. Clock decision

Clock status: **VERIFIED**.

Both artifacts embed `control_freq=20`. More importantly, pinned robosuite
defines flattened state as simulation time followed by qpos and qvel. The first
raw state scalar was inspected across the complete corpus:

- every one of 200 demos begins at simulator time `0.0`;
- all 23,007 adjacent row differences are `0.05` simulated seconds;
- minimum observed difference: `0.04999999999999449` seconds;
- maximum observed difference: `0.050000000000000044` seconds;
- maximum absolute floating representation error from 0.05:
  `5.509481759702339e-15` seconds;
- no zero, doubled, missing, repeated, or irregular interval exists; and
- prepared `states` are exact raw copies.

The higher-rate teleoperation/controller metadata is not the evaluation clock.
Wall-clock timestamps, collection speed, file times, download times, and the
400-step evaluation horizon are excluded.

The exact integer mapping is:

```text
ts_sim_ns(i) = i * 50_000_000
```

For selected `demo_0`, 118 source states become 118 normalized frames, from
`0` through `5_850_000_000` nanoseconds. No action-integrated final frame is
added.

## 8. Outcome-blind selection and planar pilot

The predeclared rule is:

> Select the lowest numeric demo satisfying every predeclared structural,
> finiteness, completeness, entity-identity, raw/prepared correspondence,
> timing, rights, and non-degenerate planar-fit criterion.

Allowed checks were demo correspondence, copied-array equality, required named
and fully mapped fields, finite complete rows, stable entity identity, verified
clock, non-degenerate XY motion, distinguishable planar regions, and rights.
No reward, done, success value, filter meaning, task completion, desired event,
desired incident, or Atlas result was used.

`demo_0` is the lowest numeric candidate and passed:

| Field | Frozen Phase-0 fact |
| --- | --- |
| HDF5 group | `data/demo_0` |
| Source/prepared samples | 118 / 118 |
| Raw `states` | `(118, 71)`, `float64` |
| Raw `actions` | `(118, 7)`, `float64`; excluded |
| Prepared `obs/object` | `(118, 14)`, `float64`, finite |
| Prepared `obs/robot0_eef_pos` | `(118, 3)`, `float64`, finite |
| Can first XYZ | `[0.1237249127, -0.2015012132, 0.8600000000]` m |
| Can final XYZ | `[0.2008898308, 0.3489171369, 0.8601717125]` m |
| Can XY first-to-final displacement | `0.5558010298` m |
| TCP first XYZ | `[-0.0655735877, -0.0858587773, 0.9929706124]` m |
| TCP final XYZ | `[0.1910255357, 0.3289658572, 1.0142795811]` m |
| TCP XY first-to-final displacement | `0.4877730902` m |

A pilot-only square centered on the initial Can XY with 0.02 m half-extent
showed a genuine interval: the Can is inside and TCP outside at row 0; the TCP
first joins the Can in that polygon at row 42 / 2.10 seconds; the Can first
leaves at row 64. This supports, but does not yet freeze, a Metriplane-authored
missing-tool compatibility experiment using existing Atlas semantics.

The pilot geometry is not source truth and was not a selection criterion. The
final polygon, boundary policy, and relative waits must be frozen before final
evidence and may not later be tuned to obtain an incident.

The official PH corpus is already outcome-filtered. The required limitation is:

> Episode selection was outcome-blind only within an upstream success-filtered
> corpus.

## 9. Coordinate and information-loss decision

The candidate normalization is position-only and planar:

- source world X -> normalized world X;
- source world Y -> normalized world Y;
- normalized Z = `0`;
- no translation, rotation, scaling, or axis swap;
- source Z is discarded and declared;
- both source quaternions, yaw, roll, and pitch are discarded and declared;
- relative object/TCP fields are excluded;
- robot joints, velocities, contacts, grasp state, and controller state are
  excluded; and
- no excluded information is hidden in `extra`.

The world frame is right-handed under pinned MuJoCo spatial-frame semantics.
The fixture will not claim 3D placement, orientation, official task success,
physical accuracy, simulator accuracy, or source endorsement.

## 10. Required environment and implementation burden

Phase-0 acquisition and inspection required only direct HDF5 access. The
proposed isolated adapter requires `h5py` and `numpy`; it imports neither
robomimic, robosuite, MuJoCo, Torch, nor simulator assets. Standard-library XML
parsing and independently authored forward kinematics supply the raw TCP
witness. The portable fixture requires only the ordinary Metriplane wheel.

Estimated implementation burden: **bounded/moderate**. Work consists of an
isolated exact-pair adapter, fail-closed raw/prepared comparison, two portable
variants using one normalized session, anti-taint and negative tests, three
clean conversions, installed-wheel execution, and claim-safe documentation.
No simulator repair, generic schema change, universal HDF5 importer, new Atlas
incident, or root dependency is required.

## 11. MimicGen partial audit

MimicGen inspection began only while robomimic carried a provisional rejection.
It stopped when artifact-native robomimic evidence closed the first candidate.

| Property | Partial finding |
| --- | --- |
| Official code | `NVlabs/mimicgen` at `72bd767c255545f462e7ccfb2731f2e5d4c1d9bb` |
| Latest actual tag | `v1.0.0` at `ea0988523f468ccf7570475f1906023f854962e9` |
| Code terms | NVIDIA source license; noncommercial research/evaluation restriction; separate from data |
| Dataset | `amandlek/mimicgen_datasets` at `33016f8a62c02334f929f2913af8fdd2a8a129e1` |
| Dataset terms | CC BY 4.0 at that immutable revision |
| Candidate human source | `source/square.hdf5`, 16,451,426 bytes, SHA-256 `c917e99362fd9bd11978d6e2642c1ea88272702fbf55b50367ed471febf550e2` |
| Generated artifact | `core/square_d0.hdf5`, 1,621,351,476 bytes; not a prepared counterpart and not downloaded |
| Pair result | No separately hosted official prepared human-source counterpart |
| Historical provenance | Docs say paper data originated on robosuite v1.2 and were postprocessed to v1.4, without immutable original-raw identity or exact transformation command/lock |
| 2025 parser correction | Hosted artifacts predate it; Square's sole parsed termination signal makes old/new indices mathematically identical, but Metriplane would exclude the signal regardless |

MimicGen's current dataset rights would support a normalized numeric derivative
with attribution, license link, modified-data notice, and no endorsement. Its
NVIDIA-licensed code must not enter the MIT package. Those favorable rights do
not manufacture a raw/prepared pair or historical preparation lineage.

Had robomimic remained rejected, MimicGen would have required an explicit
narrower-boundary decision or an official immutable original-raw/preparation
record, artifact-specific clock proof, and a deterministic local preparation
audit. Those are the reopening criteria. They are not pursued after the
first-candidate GO.

## 12. Phase-0 claim register

Allowed at this point:

- the exact robomimic pair has immutable identity and an MIT dataset grant;
- raw/prepared correspondence passed for all 200 demos;
- the two proposed prepared position fields were independently tied to raw
  state for all 23,207 rows;
- the source simulation clock is exactly representable as 50,000,000 integer
  nanoseconds per retained row;
- `demo_0` is the outcome-blind lowest structural candidate within an upstream
  success-filtered corpus; and
- a bounded planar existing-Atlas experiment is structurally supported.

Not yet allowed:

- that a fixture, incident/control pair, three-conversion result, evidence
  bundle, regression, installed-wheel matrix, or CI result exists;
- that current robomimic code historically generated the hosted prepared bytes;
- that one trajectory establishes general robomimic compatibility;
- that planar occupancy is official Can success or failure;
- that source or simulator behavior is physically accurate; or
- that robomimic, robosuite, NVIDIA, or Hugging Face endorses Metriplane.

## 13. Decision

**GO: implement the exact robomimic Can PH boundary above.**

Implementation must retain both raw and prepared provenance, require both exact
source hashes, reproduce the raw witnesses, emit only the selected prepared
`obs` rows, preserve all 118 complete two-entity frames, and keep source
dependencies outside the root wheel. MimicGen and RoboCasa must not receive a
second successful adapter merely because time remains.
