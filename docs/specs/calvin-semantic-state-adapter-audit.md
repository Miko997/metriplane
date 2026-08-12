<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# CALVIN semantic-state adapter Phase-0 audit

Status: **NO-GO — documentation-only rejection; no adapter or portable fixture
was created.**

Decision date: 2026-08-12

This record answers MET-17's bounded research question for one official CALVIN
debug-dataset sequence. Direct semantic-state extraction is technically
plausible. Publication through the unchanged Metriplane boundary is not
supported by the available primary-source evidence.

Two independent gates stop implementation:

1. The separately hosted dataset archive has no dataset-specific license or
   terms, and the official sources do not clearly grant redistribution of raw
   data or normalized derived state.
2. The inspected timestep files, documented schema, and published renderer
   path provide ordering but no timestamps. The embedded configuration declares
   nominal 30 Hz collection, while the pinned recorder samples on a wall-clock
   inequality. External Source Contract v1 requires a deterministic evaluation
   clock and has no order-only clock. Treating every index as an exact
   1/30-second tick would invent timing.
In addition, the archive has no embedded generator-repository identity, and
official sources do not state whether the May 2022 debug archive was affected
by later dataset corrections. The published whole-archive SHA-256 does freeze
the currently identified content, so this is recorded as a source-era and
correction-provenance limitation rather than a third independent identity
failure.

Rights and clock are each sufficient for NO-GO under the task's stop rules.
This record therefore preserves facts, acquisition instructions, hashes, a
rights matrix, and precise reopening conditions. It does not publish
CALVIN-derived fixture values.

## 1. Metriplane start gate

| Item | Audited result |
| --- | --- |
| Expected starting baseline | 49c3b37057312c89db030386dd2cc68628d92458 |
| Actual public origin/main | 49c3b37057312c89db030386dd2cc68628d92458 |
| main advanced after the proof tag | No; the tag dereferences to the same commit |
| Working branch | agent/calvin-semantic-state-fixture |
| Branch base | Current main, not the proof branch or detached tag |
| MET-16 | Done in Linear |
| MET-17 | Marked In Progress before Phase 0 |
| MET-18 | Not started |
| Annotated proof-tag object | 259d6e16ae4c0bbc18f4864dd1e899e66a1a7f58 |
| Proof-tag target | 49c3b37057312c89db030386dd2cc68628d92458 |
| Tagged proof workflow | Run 31583292137, green |
| Tagged CI workflow | Run 31583292143, green |
| External commands | metriplane external validate and metriplane external run present |
| External Source Contract schema SHA-256 | b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4 |
| FrameStateModel | Version 1.0 unchanged |

The immutable ManiSkill proof, the MET-15/MET-16 evidence, the generic external
contract, Atlas, and FrameStateModel were not modified.

## 2. Phase-0 decision

**Decision: NO-GO.**

The technical state path is credible but cannot be published honestly through
the current contract. A PARTIAL fixture is also rejected: even a state-only or
non-time-based Atlas scenario would still need the contract's required clock
declaration, and derived-state redistribution permission is not established.

No attempt was made to make CALVIN fit by changing Metriplane. Specifically:

- no time-based rule, max_wait_s value, or delay incident was proposed;
- no CALVIN task, language, success, reward, done, action, or annotation range
  was used as Metriplane truth;
- no new incident type or CALVIN-specific core condition was added;
- no simulator restoration or action replay was attempted;
- no full simulator environment was installed;
- no large archive was downloaded; and
- no raw or derived CALVIN data was added to the repository.

## 3. Exact CALVIN code identity

| Item | Exact identity |
| --- | --- |
| Canonical repository | https://github.com/mees/calvin |
| Audited branch | main |
| Audited commit | fa03f01f19c65920e18cf37398a9ce859274af76 |
| Commit date | 2025-09-08 |
| Tags or releases | None in the official repository |
| Environment submodule | https://github.com/mees/calvin_env |
| Pinned calvin_env commit | 1431a46bd36bde5903fb6345e68b5ccc30def666 |
| calvin_env commit date | 2022-04-29 |
| Latest root commit before the archive date | 07b94ffdf33f1d95b6770e080ab1555b0219122f |
| Expected Python | Python 3.8 |
| Root code license | MIT |

The pre-archive root commit is only a temporal source-era candidate. The debug
archive does not embed that commit, the current commit, or the calvin_env
commit, so none can be asserted as the exact generator identity.

The official installation is historical and not fully locked. Relevant files
include install.sh, calvin_models/requirements.txt, calvin_models/setup.py, and
the Hydra configuration under calvin_env/conf. The current quickstart requests
Python 3.8; the requirements include old PyTorch, Hydra, and
PyTorch-Lightning-era dependencies. There is no complete dependency lock or
Python-version marker that establishes a byte-reproducible environment.

No dependency repair was attempted because direct NPZ extraction does not
require the simulator. The proposed adapter would not import CALVIN.

### Code-license conflict inside the pinned environment

The root CALVIN repository LICENSE is MIT. The pinned calvin_env repository
also contains an MIT LICENSE file, but calvin_env/calvin_env/__init__.py
declares GPLv3 and calvin_env/setup.py consumes that package metadata. This is
an internal primary-source conflict and is not silently resolved here. No
calvin_env code or simulator asset is copied or redistributed by this audit.

Primary code sources:

- [pinned CALVIN tree](https://github.com/mees/calvin/tree/fa03f01f19c65920e18cf37398a9ce859274af76)
- [dataset documentation](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/README.md)
- [official download script](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/dataset/download_data.sh)
- [official disk loader](https://github.com/mees/calvin/blob/fa03f01f19c65920e18cf37398a9ce859274af76/calvin_models/calvin_agent/datasets/disk_dataset.py)
- [pinned scene observation code](https://github.com/mees/calvin_env/blob/1431a46bd36bde5903fb6345e68b5ccc30def666/calvin_env/scene/play_table_scene.py)
- [pinned robot observation code](https://github.com/mees/calvin_env/blob/1431a46bd36bde5903fb6345e68b5ccc30def666/calvin_env/robot/robot.py)
- [pinned recorder](https://github.com/mees/calvin_env/blob/1431a46bd36bde5903fb6345e68b5ccc30def666/calvin_env/io_utils/data_recorder.py)
- [pinned renderer](https://github.com/mees/calvin_env/blob/1431a46bd36bde5903fb6345e68b5ccc30def666/calvin_env/datarenderer.py)

## 4. Dataset identity and minimal acquisition route

The smallest currently supported official route is:

http://calvin.cs.uni-freiburg.de/dataset/calvin_debug_dataset.zip

No state-only or individual-sequence route is documented by the current
official repository or dataset sources. The obsolete automatic 50steps
fallback was removed as outdated in official commit
[59103e970982f7d1ecd158d8da9d7906ce02f0ef](https://github.com/mees/calvin/commit/59103e970982f7d1ecd158d8da9d7906ce02f0ef)
and is not an acceptable source.

| Property | Exact observed value |
| --- | --- |
| Archive size | 1,299,150,917 bytes |
| Official published SHA-256 | c66d09147e2c806b244f18ea7d61e388d4dac11f828929779437f728d03e1204 |
| Last-Modified | Fri, 13 May 2022 13:34:38 GMT |
| ETag | "4d6f7845-5dee4bc6ca437" |
| Server range support | bytes |
| ZIP member count | 4,477 |
| Timestep NPZ count | 4,446 |
| Embedded license/notice/terms/readme | None |
| Embedded repository or release ID | None |

The official checksum inventory is:

http://calvin.cs.uni-freiburg.de/dataset/sha256sum.txt

Its currently observed SHA-256 is
049e80a3d75a10f511827b9d56b1daf28fdfa6c6c026e80daced2b454085dd53.
The checksum inventory and archive are mutable, unsigned HTTP resources on the
same origin. The archive digest was recorded from the official inventory but
was not independently recomputed because the full 1.3 GB archive was not
downloaded.

Phase 0 inspected approximately 1.56 MB of unique HTTP byte ranges from the ZIP
directory and selected members; repeated requests may make transferred traffic
larger. This stayed within the minimal-data gate.

### Exact split and sequence metadata

| Split | Inclusive interval | Samples | Completeness |
| --- | --- | ---: | --- |
| training | 358482 through 361252 | 2,771 | Structurally consecutive by directory plus ep_start_end_ids.npy; full content not validated |
| validation | 553567 through 555241 | 1,675 | Structurally consecutive by directory plus ep_start_end_ids.npy; full content not validated |

Relevant embedded member identities:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| training/ep_start_end_ids.npy | 144 | 1c35e84fa9f49bf52c70e5e3a5df1fda392c90ee2c8d2af03af94c0eb99e4dcf |
| training/ep_lens.npy | 136 | 9d2b82f5e9c360dff84975040f0e8a93d6eb90a7935674a2074fb6341da680d5 |
| training/scene_info.npy | 428 | 6c3b73ad0d6eab3c142dc70b5cd225ea1a01841cd361f5ec7387395e6328ef72 |
| training/.hydra/merged_config.yaml | 7,287 | 75c1c15067e4bd543d1b69a654769836f6cbbf55c4e44ae30da255c45609523f |
| validation/ep_start_end_ids.npy | 144 | c644558d5a51f78470f35126d70034d5f6b54a9e0cd687706aec6442d4c9febe |
| validation/ep_lens.npy | 136 | 5b360250d0be1cfb0c07256ef5c8472850e357b1e1de1e7f58dd7cb46072a637 |
| validation/scene_info.npy | 428 | 92a0f1236d46a1437b7ccafb04732c19d076f65c9cb5b42e9f2cdae106d53605 |
| validation/.hydra/merged_config.yaml | 7,287 | 75c1c15067e4bd543d1b69a654769836f6cbbf55c4e44ae30da255c45609523f |

The range audit also inspected the four boundary timestep files:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| training/episode_0358482.npz | 255,417 | 6bbee1da09cea1f22198872fcc87ce9d6ccc2bfa7f7577a8d3e899e56a981089 |
| training/episode_0361252.npz | 244,377 | 5d6102dc51e5dcd76f2bca7b1175c11e64c9673bd0b4940d9b90d875b28e9f15 |
| validation/episode_0553567.npz | 255,525 | 2a19ef6b4499a0b510cc676ebaf199d8da5b805fef7b7cb4f6bc1524e0464161 |
| validation/episode_0555241.npz | 268,893 | 383e9d0dea2ac742c66eca7e381a1c1d19e33723474d5705a0c2e3cd4f6536e9 |

The full candidate sequence was not downloaded. Although every uncompressed
member size is present in the ZIP central directory, a complete size inventory
was not recorded and per-member SHA-256 values for all 2,771 timestep files
were not computed. The official whole-archive digest would cover them only
after a full independent digest check. This audit does not claim full-sequence
content validation.

## 5. Outcome-blind candidate selection

The selection rule was fixed before examining any source outcome:

> Choose the lowest numeric training sequence for which the official boundary
> file, every numerically expected timestep file, required scene_obs and
> robot_obs arrays, finite values, complete snapshots, stable entity ordering,
> non-degenerate planar movement, supported coordinates, supported clock,
> immutable source identity, and publication rights all pass.

Allowed structural checks were file presence, numeric continuity, array shape,
finiteness, entity availability and order, movement, coordinates, clock, and
rights. The audit did not inspect language tasks, task IDs, rewards, success,
done flags, annotation intervals, policy results, desired Atlas output, or
whether an incident would occur.

The debug archive contains only one training sequence. The lowest numeric
candidate was therefore predeclared as:

training/episode_0358482.npz through
training/episode_0361252.npz, inclusive, 2,771 source samples.

The central-directory order is not numeric. Any future converter must derive
the expected inclusive range from ep_start_end_ids.npy, numeric-sort file
indices, reject gaps and duplicates, and never use ZIP member order.

The candidate passed the range-audited boundary checks for shape, finiteness,
declared keys, non-degenerate block XY change, and best-available content
identity through the published whole-archive digest. It was rejected before
full selection because rights and a contract-compatible clock did not pass.
Generator/correction provenance remains unresolved and limits source-era
claims. No episode was selected for fixture publication.

## 6. Explicit state semantics

Each inspected timestep NPZ contains actions, rel_actions, robot_obs,
scene_obs, RGB, depth, and tactile arrays. Language annotation files are
separate. The timestep files do not contain language text, task IDs, source
success, rewards, or done flags.

Direct inspection found:

| Array | Actual inspected shape | Actual inspected dtype | Finiteness |
| --- | --- | --- | --- |
| scene_obs | (24,) | float64 | All finite in inspected boundary samples |
| robot_obs | (15,) | float64 | All finite in inspected boundary samples |

The official dataset README documents both arrays as float32. The archive's
actual boundary arrays are float64. This discrepancy must be handled by
validating source bytes and reporting the observed dtype; an adapter must not
pretend the source was float32.

### Exact scene_obs index map

| Indices | Official meaning | Unit or encoding |
| --- | --- | --- |
| 0 | sliding-door joint state | Source joint coordinate |
| 1 | drawer joint state | Source joint coordinate |
| 2 | button joint state | Source joint coordinate |
| 3 | switch joint state | Source joint coordinate |
| 4 | lightbulb | 1 on, 0 off |
| 5 | green light/LED | 1 on, 0 off |
| 6:9 | red block X, Y, Z | PyBullet base position; world/metre interpretation inferred from source and metric configuration |
| 9:12 | red block Euler X, Y, Z | PyBullet-derived Euler values; radian interpretation inferred from source/API use |
| 12:15 | blue block X, Y, Z | PyBullet base position; world/metre interpretation inferred from source and metric configuration |
| 15:18 | blue block Euler X, Y, Z | PyBullet-derived Euler values; radian interpretation inferred from source/API use |
| 18:21 | pink block X, Y, Z | PyBullet base position; world/metre interpretation inferred from source and metric configuration |
| 21:24 | pink block Euler X, Y, Z | PyBullet-derived Euler values; radian interpretation inferred from source/API use |

The order is corroborated by the dataset README, the pinned scene concatenation
code, and the embedded Scene D configuration, whose movable-object declaration
order is red, blue, pink.

### Exact robot_obs index map

| Indices | Official meaning | Unit or encoding |
| --- | --- | --- |
| 0:3 | robot TCP X, Y, Z | World coordinates, metres |
| 3:6 | robot TCP Euler X, Y, Z | PyBullet Euler angles, radians |
| 6 | gripper opening width | metres |
| 7:14 | seven arm joint states | radians |
| 14 | gripper action | binary: close -1, open 1 |

The embedded configuration sets euler_obs true. The pinned robot source builds
robot_obs in exactly this order.

Each NPZ is one explicit snapshot; no simulator restoration or action replay is
needed to obtain scene_obs or robot_obs. Within Scene D, entity identity is
stable by the fixed array order and embedded movable-object configuration.
A safe adapter would emit every declared entity on every normalized frame and
reject missing keys, wrong shapes, nonfinite values, gaps, duplicates, or a
changed configuration. It would not interpolate, resample, or carry state
forward.

These completeness and identity conclusions were confirmed only for the
inspected boundary files plus official structure/code. They were not proven
over all 2,771 candidate samples because implementation stopped before the
archive download.

## 7. Time semantics

Classification: **PARTIALLY VERIFIED.**

Primary sources establish:

- the dataset README describes actions at the collection cadence used by the
  environment;
- the embedded configuration declares control_freq 30, record_fps 30.0, and
  bullet_time_step 240.0;
- source filenames and ep_start_end_ids.npy establish sample order; and
- the source recorder saves when wall-clock delta_t is greater than or equal to
  1 / record_fps, or when done.

The recorder serializes a raw wall-clock time in its environment storage, but
the pinned renderer writes the published NPZ without that field. None of the
inspected timestep NPZs contains a timestamp. Therefore the exact elapsed time
and collection jitter for published samples cannot be reconstructed.

Nominal 30 Hz is not evidence that every adjacent published sample is separated
by exactly 33,333,333 or 33,333,334 nanoseconds. Source index is authoritative
for order only. It must not be converted into exact physical seconds, and it
cannot support max_wait_s or a delay incident.

External Source Contract v1 requires normalization.clock and accepts only
identity_seconds, fixed_step, affine, or lookup_table. It also requires a
strictly monotonic evaluation clock on every frame. The published CALVIN files
provide no identity or lookup timestamps; affine mapping has the same missing
input; and fixed_step would overstate the recorder evidence. The contract has
no order-only clock. It permits source_unit index with fixed_step, but that
still requires choosing fixed_step_ns; doing so without an authoritative
per-sample cadence would invent duration. The blocker is insufficient timing
evidence, not absence of an index option. Changing the contract is prohibited
by MET-17.

This is why a non-time-based PARTIAL fixture is not emitted: Atlas could in
principle evaluate an operator-authored zone step without a delay rule, but the
portable fixture would still require an invented contract clock.

## 8. Coordinate and orientation interpretation

The README explicitly calls the robot TCP values world X, Y, Z coordinates, and
the scene code reads movable-object base positions from the same PyBullet
environment. World/metre interpretation for block positions is a supported
source/API-derived inference from the base-pose calls, metric configuration,
task displacement values, and observed magnitudes; CALVIN's dataset table does
not label the block unit or frame explicitly. The exact world-frame origin is
defined by the Scene D assets and configuration.

The pinned source uses PyBullet conversion functions for Euler observations.
The component order is Euler X, Y, Z. Radians are a supported inference from
source/API use rather than an explicit unit in CALVIN's dataset table. A prose
statement of world-frame handedness was not found in the official CALVIN
sources inspected here. Orientation is unnecessary for the proposed
position-only mapping and would not be emitted.

If the other gates were resolved, the bounded planar policy would be:

- source X maps directly to normalized X;
- source Y maps directly to normalized Y;
- metres remain metres;
- no translation, rotation, scaling, or axis swap is applied;
- normalized Z is set to 0 with explicit disclosure that source Z is discarded;
- source Euler angles are discarded; and
- no orientation is hidden in extension fields.

The future converter would report source Z and orientation ranges for the
selected entity as information-loss evidence. No such full-sequence ranges are
claimed by this stopped audit.

## 9. Rights and redistribution matrix

| Material | Primary-source evidence | MET-17 disposition |
| --- | --- | --- |
| CALVIN root code | Root MIT LICENSE | Reuse permitted with notice |
| calvin_env code | MIT LICENSE conflicts with GPLv3 package metadata | Do not copy; record conflict |
| Dataset documentation | Stored in the MIT repository | Cite and paraphrase factual documentation |
| Raw debug/full archives | Separate host; no archive license or dataset-specific terms | Redistribution not established |
| scene_obs numeric state | Dataset contents | Derived-state redistribution not established |
| robot_obs numeric state | Dataset contents | Derived-state redistribution not established |
| Language annotations | Separate dataset content | Rights unclear and technically prohibited for truth |
| RGB, depth, tactile data | Dataset content and simulator assets | Do not inspect beyond keys; do not redistribute |
| Simulator assets | Multiple asset files/terms; not needed for direct extraction | Do not include |
| Independently authored adapter code | Would copy no CALVIN code | Metriplane could license its own code |
| Normalized portable fixture | Transformation of dataset numeric state | Do not publish without an express basis |
| Audit, hashes, and acquisition instructions | Facts and references only | Documentation-only publication supported |

The CALVIN website describes the environments, baselines, and benchmarks as
available for academic usage and released under MIT. The repository LICENSE
defines its covered material as the software and associated documentation.
Neither source expressly identifies the separately hosted ZIP files as
licensed dataset material, grants raw-data redistribution, or addresses
redistribution of transformed numeric state.

Public download access, benchmark wording, and a citation request are not a
precise redistribution grant under MET-17's evidence standard. The root code's
MIT license is not extended to the dataset by assumption.

This unresolved derived-state permission is a publication stop condition. It
rules out raw files and a normalized session. No CALVIN data, rendered output,
language, or assets are included in Metriplane.

## 10. Dataset correction and version state

The official changelog records material changes:

- 2022-01-10: evaluation initial-state breaking change;
- 2022-02-07: task distribution/success-criteria change and use_nullspace
  configuration correction;
- 2022-05-13: the debug dataset route was added;
- 2022-09-16: ABC/ABCD language annotations and scene_info corrections;
- 2023-02-24: an incorrect scene_info.npy in the full D dataset was replaced
  and its checksum updated; and
- 2023-12-18: the obsolete automatic 50steps fallback was removed.

The debug embedded configuration contains use_nullspace true, so it reflects
that February 2022 configuration correction. Its server timestamp predates the
February 2023 full-D scene_info correction. The changelog names the D-to-D
archive, not the debug archive. The debug scene_info values are internally
consistent with the observed ranges, but official sources do not say whether
debug was unaffected, independently corrected, or intentionally unchanged.

**Debug correction applicability: UNKNOWN.**

The server's current archive digest, length, ETag, and Last-Modified value give
a best-available content identity, but not an immutable revision record. There
is no DOI, release ID, signed manifest, embedded generator revision, or official
per-member SHA-256 inventory.

## 11. Planar fit

The smallest honest source entity would be one explicitly indexed movable
block, preferably block_red. A robot TCP would be included only if a supported
operator rule genuinely required it. No language/task identity, fixture state,
full robot articulation, policy action, rendered observation, or source outcome
would be emitted.

Boundary inspection shows non-degenerate red-block XY change, so an
operator-authored condition such as “red block enters a declared XY polygon”
is technically plausible. A future full scan would have to predeclare the
polygon-selection method without looking at Atlas results, verify every sample,
and preserve the same source session between variants.

The condition would mean only:

> A Metriplane-authored bounded compatibility-test rule applied to normalized
> CALVIN state.

It would not mean CALVIN task completion, failure, success, correctness, or
benchmark performance. No Atlas incident is supportable from this path:
the current incident semantics are missing-required-asset delay semantics, and
exact elapsed time is unavailable. A step-completed event without an incident
could be technically honest only after the clock and rights gates are resolved.

Planar-fit result: **technically plausible but not sufficient for
publication**.

## 12. Proposed adapter boundary if reopened

The isolated design would be:

    adapters/calvin_semantic_state/
      pyproject.toml
      lock file
      README.md
      src/calvin_semantic_state/
      tests/

It would:

- use direct NPZ extraction with its own small locked environment;
- require the exact archive digest, embedded configuration digest, boundary
  metadata digests, and complete numeric sequence;
- avoid CALVIN, PyBullet, policy, language, image, and simulator imports;
- numeric-sort and validate every source index;
- emit only complete snapshots of the minimal entity set;
- fail closed on hashes, shapes, dtypes, nonfinite values, identity changes,
  missing files, unsafe paths, output overlap, or source mutation;
- exclude actions even though they are colocated in each NPZ;
- produce a portable Metriplane bundle needing no CALVIN installation; and
- leave the root pyproject, root lock, Metriplane package, contract, Atlas, and
  FrameStateModel unchanged.

This is a boundary proposal, not an implemented adapter and not a claim of
general CALVIN support.

## 13. Trust layers and candidate normalized mapping

No field crossed a trust layer during this audit.

| Layer | Candidate facts |
| --- | --- |
| A — source facts | Archive/member identities; source index; scene_obs and robot_obs bytes; embedded configuration; numeric ordering |
| B — adapter-derived facts | Stable block ID; source index to frame ID; direct XY projection; Z removal; polygon membership |
| C — operator-configured rules | Workspace polygon; target polygon; required material; non-time-based ordered step |
| D — Metriplane results | Validation, events, deviations, incidents, reports, evidence, regression |

If reopened, the narrow mapping would be:

| Output field | Source | Transform | Loss and claim limit |
| --- | --- | --- | --- |
| frame_id | numeric source file index relative to 358482 | subtract sequence start | Order only; not elapsed time |
| object_id | embedded Scene D object name block_red | fixed adapter mapping to red_block_1 | Adapter identity, not source task identity |
| object kind | block_red | operator maps to material | Metriplane role only |
| position.x | scene_obs[6] | identity | World X in metres |
| position.y | scene_obs[7] | identity | World Y in metres |
| position.z | no emitted source dimension | constant 0 | Source scene_obs[8] discarded and disclosed |
| zone | projected X/Y plus operator polygons | deterministic membership | Not CALVIN success |

There is deliberately no proposed timestamp field because no compliant mapping
is supported. Orientation, velocity, contact, joint state, fixture state,
gripper state, language, images, actions, rewards, success, done, and annotation
ranges are excluded.

## 14. Annotation and action anti-taint

The source layout supports a clean extraction boundary:

- language annotations and task IDs live in separate annotation files;
- source success and rewards are not keys in inspected timestep files;
- done and raw episode-end values are not keys in published timestep NPZs;
- action arrays are colocated but unnecessary for direct state extraction; and
- source sequence boundaries are used only for completeness and selection, not
  as event or incident truth.

No converter was implemented, so mutation-based anti-taint tests were not run.
Their required future form is explicit: remove or mutate annotation files,
task labels, actions, and any outcome fields in temporary copies; normalized
state, field mapping, operator rules, and Atlas result must remain identical
when scene_obs and robot_obs are identical. Any dependency would invalidate the
architecture.

## 15. Implementation and verification disposition

The stop conditions fired before substantive implementation. Therefore:

| Gate | Result |
| --- | --- |
| Adapter implementation | Not started |
| Portable fixture | Not created |
| Incident/control variants | Not created |
| Raw CALVIN redistribution | None |
| Derived CALVIN redistribution | None |
| Full 1.3 GB download | Not performed |
| CALVIN/PyBullet environment install | Not performed |
| Three clean conversions | Not applicable |
| Three installed-wheel Atlas runs | Not applicable |
| Evidence bundles/regressions | Not applicable |
| Wheel portability matrix | Not applicable |
| Output relocation/path-leak scan | Not applicable |
| Adapter negative-test matrix | Not applicable |
| New release, version bump, tag, DOI, or merge created by MET-17 | None |

Not-applicable entries are not passes. They are deliberately unsupported
outputs of a documentation-only NO-GO.

The Metriplane root dependency set and package version remain unchanged. No
CALVIN reference was added under metriplane/. The external contract schema,
FrameStateModel, Atlas process semantics, bundled demo, immutable ManiSkill
proof, and prior evidence directories remain byte-untouched. Runtime checks,
including the bundled demo, are recorded separately after the Phase-0 commit;
byte preservation alone is not represented as an execution pass.

## 16. Allowed and prohibited claims

Allowed:

- The current official CALVIN debug archive exposes directly stored scene_obs
  and robot_obs state with documented index meanings.
- The inspected boundary files use shape (24,) and (15,) float64 arrays and are
  finite, despite the README's float32 statement.
- The single training sequence is numerically contiguous by official metadata
  and archive directory inspection.
- A one-block XY projection is technically plausible without images, actions,
  language, tasks, or simulator replay.
- Metriplane rejected publication because rights, clock, and version/correction
  evidence did not meet its external-source gate.

Prohibited:

- CALVIN compatibility or CALVIN support;
- CALVIN task success, failure, or incident detection;
- exact 30 Hz physical timestamps or delay duration;
- benchmark performance, policy validity, physical accuracy, simulator realism,
  safety, production readiness, adoption, or endorsement;
- a claim that CALVIN's root MIT license covers the dataset;
- permission to redistribute raw or derived dataset values;
- full candidate-sequence validation or deterministic conversion;
- proof that the debug archive includes or is unaffected by later corrections;
- exact generator-repository identity; or
- generalization to other CALVIN scenes, splits, episodes, or dataset versions.

## 17. Timebox, unresolved questions, and reopening criteria

Phase-0 start: 2026-08-12T09:57:37Z

Written decision: 2026-08-12T10:14:06Z

Elapsed wall time to written decision: approximately 17 minutes. The audit was
accelerated by parallel, independent start-gate, code/timing, and data/rights
checks. It stayed below the two-hour Phase-0 maximum. Environment-repair time
was zero.

Unresolved questions:

1. What official terms govern the separately hosted debug archive?
2. Do those terms permit redistribution of normalized derived numeric state?
3. What exact CALVIN/calvin_env commits generated the debug archive?
4. Was the debug archive affected by the 2023 full-D scene_info correction?
5. Are per-sample timestamps available in an official sidecar, or does an
   official guarantee establish exact fixed-step sampling despite the recorder
   implementation?
6. What official statement establishes the world frame's handedness if a future
   mapping needs orientation?

Reopen GO or PARTIAL only after all applicable evidence is available:

- an official dataset license or explicit permission covering the debug archive
  and public derived-state redistribution;
- an immutable archive/revision and correction-status record;
- a source-authoritative timestamp/lookup or an exact fixed-step guarantee that
  can satisfy External Source Contract v1 without invention; and
- full archive verification followed by outcome-blind, complete candidate
  validation.

Obtaining clarification from CALVIN maintainers requires separate owner
authorization. MET-17 does not authorize contact. MET-18 remains blocked until
MET-17 is completed under the project's merge and post-merge rules.
