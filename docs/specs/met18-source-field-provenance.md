<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-18 robomimic Can field provenance and normalization loss

Status: **implemented and demonstrated for the exact pinned source pair,
`demo_0`, adapter commit `cfc285a3e757fdf742858b1c4cf685c384d01e8b`,
and the two frozen incident/control rules.**

This record defines the complete source-to-normalized map for the selected
robomimic Can Proficient Human `demo_0` fixture. The portable record
contains 118 complete snapshots of one Can and one robot TCP. It intentionally
does not contain source outcomes, actions, `next_obs`, orientation, task labels,
or a source success definition.

Prepared observations are never described as raw data. The exact prepared HDF5
bytes are source-artifact facts, but the values in `obs` were derived by the
source simulator's observation pipeline. Independent reconstruction from the
raw state and embedded model is a provenance witness, not a reclassification of
those fields as raw.

## 1. Trust layers

| Layer | Meaning in this fixture |
| --- | --- |
| A — source fact | Exact pinned raw and prepared HDF5 bytes; artifact metadata; source demo and row order; raw flattened states, excluded actions, embedded model XML, and prepared observation bytes. A prepared byte remains a prepared observation, not a raw measurement. |
| B — adapter-derived fact | Stable Metriplane IDs, named-field extraction, independent raw witnesses, world-XY projection, integer-index clock, explicit information-loss declarations, and deterministic zone assignment against separately frozen Layer-C rules. |
| C — operator-configured rule | Entity roles, the complete target polygon, inclusive boundary, overlap/outside policy, station and process declarations, and the incident/control relative waits. |
| D — Metriplane result | Atlas events, deviations, incidents, reports, evidence bundles, and generated regressions. These do not feed conversion. |

The raw/prepared/normalized distinction is orthogonal to these trust layers.
For example, an exact value in the official prepared artifact is a Layer-A
artifact fact, while selecting its named components and projecting them into a
normalized position are Layer-B operations.

## 2. Frozen source-artifact identities

| Artifact ID | Repository path | Size | SHA-256 / LFS OID | Fixture treatment |
| --- | --- | ---: | --- | --- |
| `can_ph_raw_hdf5` | `v1.5/can/ph/demo_v15.hdf5` | 64,932,974 | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` | Required external audit/conversion input; not redistributed. |
| `can_ph_prepared_lowdim_hdf5` | `v1.5/can/ph/low_dim_v15.hdf5` | 46,889,752 | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` | Required external conversion input; not redistributed. |

Both artifacts belong to `robomimic/robomimic_datasets` at immutable revision
`74fa018461f479cd9fd15b924a16103012096203`. Different paths, sizes, hashes,
or revisions must fail closed.

## 3. Raw/prepared/normalized provenance graph

```text
official raw demo_v15.hdf5
  data/demo_0/states + model_file + environment metadata
        |                              |
        | independent Can lookup       | independent named-site FK
        v                              v
  raw Can world XYZ witness      raw robot TCP world XYZ witness
        |                              |
        +---------- equality ----------+
                       |
official prepared low_dim_v15.hdf5
  data/demo_0/obs/object[:, 7:10]
  data/demo_0/obs/robot0_eef_pos[:, 0:3]
                       |
                       | independently authored adapter
                       v
       118 complete planar snapshots under Layer-C rules
                       |
                       v
             unchanged External Source Contract v1
```

The current robomimic commit
`d309eaecc18acf4152a830a895a6984b8ac71b05` is the code-audit identity. The
hosted prepared file does not record a generator commit, so this document does
not claim that current commit, release `v0.5.0`, or another unrecorded commit
generated the hosted bytes. The release-era preparation algorithm is cited to
explain the observed layout and alignment; the independently verified raw
witnesses bind the consumed prepared coordinates to the frozen raw artifact.

## 4. Source field inventory and raw witnesses

| Entity | Prepared field consumed | Source unit/frame | Raw witness | Validation | Excluded information |
| --- | --- | --- | --- | --- | --- |
| Can | `data/demo_0/obs/object[:, 7:10]` | metres; MuJoCo/robosuite world XYZ | `data/demo_0/states[:,31:34]`, whose model-dependent address is established by finding named free joint `Can_joint0` in the `data/demo_0` attribute `model_file` rather than trusting a magic offset | Corpus-wide array equality, 23,207/23,207 rows; raw-derived stream SHA-256 `536cc7e0b6fb1185cc27716d41b02742fee3c62b9be8d70cb066ce26d7e8cb36` | Prepared relative position `[0:3]`, relative quaternion `[3:7]`, world Z, and world quaternion `[10:14]` are excluded. |
| Robot TCP | `data/demo_0/obs/robot0_eef_pos[:, 0:3]` | metres; named Panda grip-site world XYZ | `data/demo_0/states` plus `model_file`: independently parse the body/joint tree, apply raw hinge qpos, and evaluate named site `gripper0_right_grip_site` | Corpus-wide 23,207/23,207 rows within `2e-12`; maximum error `1.1102230246251565e-15`, RMSE `2.3609042912280844e-16`; witness stream SHA-256 `3e878face68a437d4cb334fba19276eb7b00b2a3828bbecc3d7e856a02e98227` | Robot articulation, joint state, TCP Z, orientation, velocities, contacts, and controller state are excluded. |

The complete prepared `obs/object` component order is:

| Slice | Pinned meaning | Use |
| --- | --- | --- |
| `[0:3]` | Can position relative to the end effector | Excluded; it is not a world position. |
| `[3:7]` | Can-to-end-effector relative quaternion in `xyzw` order | Excluded. |
| `[7:10]` | Can world body position | X/Y retained; Z discarded. |
| `[10:14]` | Can world quaternion in `xyzw` order | Excluded completely. |

Unknown keys, shapes, units, frames, entity names, or vector orders are fatal;
the adapter must not guess an offset or accept an unnamed concatenated vector.

## 5. Complete `session.jsonl` field map

Every field emitted in each normalized frame is listed below. The 118-row
canonical JSONL serialization is byte-identical between the two variants and
has SHA-256
`bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246`.

| Output field | Layer | Source file / HDF5 key | Transform and parameters | Information loss / missing behavior | Validation and Atlas use | Claim limitation |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | B | External Source Contract v1, not a source HDF5 value | Emit FrameStateModel `1.0`. | None; reject another schema version. | Generic validation selects the frozen frame schema. | Says nothing about robomimic-wide compatibility. |
| `source_backend` | B | Frozen adapter identity, not a source HDF5 value | Emit `external:robomimic_lowdim_prepared_obs`. | None; reject a missing or different identity. | Provenance/routing only; no source-specific Atlas branch. | Identifies Metriplane's adapter, not an official upstream backend. |
| `frame_id` | B | `data/demo_0/obs/*` ordered row index `i`, `0..117` | Emit integer `i` without reordering, subsampling, or resampling. | None; missing or duplicate rows are rejected. | Complete-snapshot ordering. | Row identity is not source wall-clock time. |
| `ts_sim_ns` | B | Raw `data/demo_0/states[i][0]`, exact copied prepared `states`, and row index | Require the verified 0.05-second sequence, then emit `i * 50_000_000` ns. | Floating representation noise is replaced by exact integer nanoseconds; irregular timing is rejected. | Authoritative Atlas evaluation clock. | The 400-step rollout horizon is not timing or a deadline. |
| `ts` | B | Same row index and `ts_sim_ns` | Emit `ts_sim_ns / 1_000_000_000`. | No independent clock; reject disagreement with `ts_sim_ns`. | Descriptive seconds required by the frame model. | Must not be represented as wall-clock collection time. |
| `events` | B | No source event field | Emit `[]` for every input snapshot. | All source labels and annotations are excluded; missing is not substituted. | Atlas derives Layer-D events from state plus Layer-C rules. | No source event, reward, done, success, or subtask label is imported. |
| `objects[0].id` | B | Named Can field and frozen entity map | Emit `can_1` in stable object order. | Original source naming is retained only in provenance; unknown identity is rejected. | Joins the material asset declaration. | `can_1` is a Metriplane ID, not an upstream globally stable identifier. |
| `objects[0].pos_world[0]` | B | Prepared `data/demo_0/obs/object[i,7]`, witnessed by raw Can qpos | Copy source world X exactly as the normalized X in metres. | None in X; nonfinite/missing values are rejected. | Planar position and zone membership. | Does not establish physical or simulator accuracy. |
| `objects[0].pos_world[1]` | B | Prepared `data/demo_0/obs/object[i,8]`, witnessed by raw Can qpos | Copy source world Y exactly as the normalized Y in metres. | None in Y; nonfinite/missing values are rejected. | Planar position and zone membership. | Does not establish official Can-task success. |
| `objects[0].pos_world[2]` | B | Prepared `data/demo_0/obs/object[i,9]` exists but is not retained | Emit literal `0.0`. | Complete source Z is discarded; missing source Z is still rejected before projection. | Satisfies position-only FrameStateModel shape; Atlas scenario is planar. | Normalized Z is not the source object's height. |
| `objects[0].zone` | B assignment using C definitions | Normalized Can XY plus frozen polygon | Inclusive point-in-polygon; emit `target_xy_region` inside, otherwise `outside_workspace`; reject overlap or ambiguous assignment. | Full 3D geometry and official source regions are not represented. | Starts/stops the Layer-C material-presence condition. | The region is operator authored, not source truth. |
| `objects[1].id` | B | Named grip-site field and frozen entity map | Emit `robot_tcp_1` in stable object order. | Robot articulation is not emitted; unknown identity is rejected. | Joins the required-tool asset declaration. | TCP identity does not imply robot calibration or safety qualification. |
| `objects[1].pos_world[0]` | B | Prepared `data/demo_0/obs/robot0_eef_pos[i,0]`, witnessed by raw FK | Copy source world X exactly as normalized X in metres. | None in X; nonfinite/missing values are rejected. | Planar tool position and zone membership. | This is named-site simulation state, not a physical measurement. |
| `objects[1].pos_world[1]` | B | Prepared `data/demo_0/obs/robot0_eef_pos[i,1]`, witnessed by raw FK | Copy source world Y exactly as normalized Y in metres. | None in Y; nonfinite/missing values are rejected. | Planar tool position and zone membership. | This is named-site simulation state, not a physical measurement. |
| `objects[1].pos_world[2]` | B | Prepared `data/demo_0/obs/robot0_eef_pos[i,2]` exists but is not retained | Emit literal `0.0`. | Complete TCP Z is discarded; missing source Z is still rejected before projection. | Satisfies position-only FrameStateModel shape; Atlas scenario is planar. | Normalized Z is not the source TCP height. |
| `objects[1].zone` | B assignment using C definitions | Normalized TCP XY plus frozen polygon | Same inclusive assignment and fail-closed overlap policy as the Can. | Full 3D geometry and source contacts are not represented. | Determines whether the required tool is present. | Planar co-occupancy is not grasp, contact, or task success. |

Each frame must contain both objects exactly once. There is no interpolation,
carry-forward, resampling, partial-update materialization, or unknown-state
substitution.

## 6. Entity-mapping field map

The emitted `entity-mapping.json` uses schema
`metriplane.external_entity_mapping.v1`. Its semantic fields are frozen as
follows; both variants use byte-identical mapping bytes with SHA-256
`51735e2c4e416c951d5d355dbb271a89f467354a9cab41fef386fa105c671a8c`.

| Output field | Layer | Frozen meaning and source | Validation / Atlas use | Claim limitation |
| --- | --- | --- | --- | --- |
| `mappings[*].normalized_object_id` | B | `can_1` for prepared `obs/object[:,7:10]`; `robot_tcp_1` for prepared `obs/robot0_eef_pos[:,0:3]`. | Unique, complete one-to-one mapping. | Metriplane-authored IDs only. |
| `mappings[*].atlas_asset_id` | C | Same stable IDs as the two domain-pack assets. | Joins normalized objects to Atlas assets. | Asset role is operator configured. |
| `mappings[*].process_relevant` | C | `true` for both entities. | Requires both in every snapshot. | Does not make either an official source process entity. |
| `mappings[*].source_entities[*].source_artifact_id` | A metadata | Prepared artifact ID, with raw artifact separately recorded as the provenance witness. | Must resolve to exact manifest entries. | Prepared and raw identities remain distinct. |
| `mappings[*].source_entities[*].source_entity_id` | A/B | Exact selected prepared HDF5 path and named component slice; raw witness path/model name described separately. | Reject unexpected key, slice, vector order, or entity name. | No universal HDF5 interpretation is claimed. |
| `mappings[*].description` | B/C documentation | One-to-one Can/material or TCP/tool mapping and provenance boundary. | Claim-safety metadata only. | Descriptive, not source authority. |

## 7. Layer-C configured field map

The following values are authored by Metriplane. They are not read from HDF5
and must be byte-identical between incident and control except for the declared
variant IDs, relative wait, and hashes caused by those differences.

| Output artifact / fields | Layer | Frozen value or rule | Atlas use | Claim limitation |
| --- | --- | --- | --- | --- |
| `domain-pack/assets.yaml`: schema; `object_id`; `asset_id`; `asset_type`; labels; work-order, expected-zone, and expected-station references | C | `can_1` is `material`; `robot_tcp_1` is `tool`; both join one fixture work order, `target_xy_region`, and `target_station`. | Asset registry and process-role joins. | Roles are compatibility-test roles, not official robomimic taxonomy. |
| `domain-pack/workspace.yaml`: schema; `cell_id`; `units`; zone and station records | C | Units `meters`; one work-station zone `target_xy_region`; one associated `target_station`; outside label `outside_workspace`. | Planar zone and station resolution. | The source does not define this Metriplane cell, zone, or station. |
| `workspace.yaml` polygon | C | Inclusive square centered at exact row-0 Can XY `(0.123724912698951, -0.20150121318116285)` m, with half-extent `0.02` m. Stable vertices are `(0.103724912698951, -0.22150121318116284)`, `(0.143724912698951, -0.22150121318116284)`, `(0.143724912698951, -0.18150121318116286)`, and `(0.103724912698951, -0.18150121318116286)`. | Inclusive point-in-polygon. Reject overlaps; otherwise use `outside_workspace`. | This is a Metriplane-authored compatibility rule, not source target/bin geometry or official success. |
| `domain-pack/process.yaml`: schema; process ID; work-order type; step ID/label; expected asset types; required assets; required zone/station; `max_wait_s` | C | One external-fixture process step: material in target region requires `robot_tcp_1`. Incident wait `2.0`; control wait `2.5`. | Existing Atlas process-asset-presence semantics only. | Waits are relative rules, not absolute timestamps, source horizons, or source deadlines. |
| `domain-pack/contracts.yaml`: schema; contract ID/kind; step and asset references; zone/station; `max_wait_s`; severity; note | C | `process_asset_presence`, required `robot_tcp_1`, warning severity, same per-variant waits, and a note denying task-success/safety use. | Existing missing-tool/delay semantics. | No new incident type and no source outcome oracle. |
| `domain-pack/work_orders.csv`: work-order, process, product, priority | C | One deterministic fixture work order with normal priority and stable identifiers. | Activates the frozen process model. | Administrative fixture metadata only. |

The frozen variant IDs are
`robomimic-can-ph-demo-0-planar-incident-v1` with domain pack
`robomimic-can-ph-planar-incident-v1`, and
`robomimic-can-ph-demo-0-planar-control-v1` with domain pack
`robomimic-can-ph-planar-control-v1`. The final serializer retained these IDs
and the declared labels. `CHECKSUMS.sha256` binds every YAML/CSV byte; the
finalized incident and control fixture fingerprints are respectively
`6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6` and
`dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf`.

The verified Atlas behavior is deliberately one-shot. The Can is inside on
frames 0 through 63; the TCP first enters on frame 42 and is inside through
frame 64. Both variants complete the single process step at frame 42, so Atlas
does not reopen it when the Can or TCP later exits. This fixture therefore
checks arrival and required presence, not continued co-occupancy or retention.
For missing and delayed events, the unchanged evaluator emits its existing
`unknown_required_asset` placeholder in the event `asset_type` field. That
placeholder does not replace or weaken the stable Layer-C identity and role:
the configured required asset remains `robot_tcp_1`, whose registry type is
`tool`.

## 8. Other durable outputs

| Artifact | Layers represented | Required contents | Current status |
| --- | --- | --- | --- |
| `source-manifest.json` | A-C metadata; D evaluation declaration | Exact code/dataset identities; both artifact paths, sizes and hashes; adapter `org.metriplane.robomimic_lowdim` at `cfc285a3e757fdf742858b1c4cf685c384d01e8b`; frozen-config SHA-256 `3cfa88b1512215d8545c1404bcc80e18bf780d1dfc899553ccc69c2517c623c5`; clock and coordinate maps; field provenance; exclusions, limitations, domain-pack hashes, and immutable relative paths only. | Demonstrated. Incident manifest SHA-256 `866b98ad23e21942985d3be051715e0291ba5ba3323f852184dfe214c04e9d35`; control `46e06a7bf345a695947edbccfac7f9abeaa77ffd8716f965422ff3200868e6b6`. |
| `normalization-report.json` | A-C audit record | 118-to-118 frame accounting, declared operations/loss, and three byte-identical real-source conversion records. Exact source correspondence and before/after source hashes are bound in each manifest and the conversion summary. | Demonstrated. Incident SHA-256 `a95c263f5c18c39f649c4849ff4a38a1abe82b9dfd1deb39274ac073b1d49ea4`; control `d81b1cfe1dc1967c2c713abcea8a4b45c8f7a3397b92b476f2a568e7334ead1c`. |
| `expected-outcome.json` | Test metadata about D; never Atlas input | `atlas_input: false`. Incident: four ordered events, one deviation, one `missing_tool_caused_delay` incident, verified evidence, and passing regression. Control: three ordered events, no deviation or incident, and no fabricated evidence/regression. | Demonstrated against the frozen session and rules. |
| `CHECKSUMS.sha256` | Artifact integrity | Sorted complete relative-path inventory and content hashes; no machine-local paths or mutable references. | Demonstrated. Its file hash is the per-variant fingerprint: incident `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6`; control `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf`. |
| `source/*` records | A-C provenance | Frozen config, dependency lock SHA-256 `86dab2c05dce00cb40db03ddea9848da227451661cd30aaa0f3eda72a35fc4ff`, and exact Linux x86_64 / CPython 3.12 conversion environment; no raw HDF5, model XML, simulator asset, or absolute path. | Demonstrated and byte-identical between variants and across three conversions. |

Production conversion and public finalization bind the durable adapter commit
to the running checkout instead of trusting caller-supplied 40-hex text. They
require the supplied commit to equal verified `HEAD`, reject a dirty or
untracked adapter subtree, enumerate its complete `HEAD` tree, and compare every
regular tracked file byte-for-byte with its Git blob. Wrong commits, modified
files hidden by `assume-unchanged` or `skip-worktree`, mode/type/symlink drift,
hostile Git environment overrides, and missing critical files fail closed.
Portable fixture validation and execution do not require Git or this adapter.
Final source-tree and Linux installed-wheel three-run equivalence passed on
Python 3.12 and 3.13, including moved-root and recursive ZIP/path-leak checks.
The scoped REUSE check passed for all MET-18 paths. macOS and fresh-runner CI,
PR review, merge, and post-merge verification remain separate gates; none
permits a change to this frozen field map.

## 9. Excluded source inputs and anti-taint boundary

Conversion must not consume or semantically depend on:

- rewards, dones, success, failure, task-completion checks, or episode-end
  metadata;
- filter meanings, good/bad labels, or mask membership semantics;
- actions or action dictionaries;
- `next_obs`, including the final action-stepped value;
- relative Can/TCP vectors;
- source horizon, source episode labels, or rollout configuration as a rule;
- any quaternion or orientation field;
- images, video, rendering, contacts, grasp state, or policy outputs.

`states`, `actions`, `model_file`, and opaque mask arrays were compared across
raw and prepared files for provenance. Comparison is not consumption: actions
and filter semantics do not contribute to normalized state or Atlas rules.
The anti-taint suite changed paired mask membership, horizon, actions, episode
metadata, raw controller/intervention/policy/user arrays, prepared rewards and
dones, relative object pose, excluded object/TCP quaternions, and all
`next_obs` positions in safe source-shaped copies. The extracted `SourceFrame`
sequence remained exactly equal to the baseline. Because mapping, domain pack,
and waits are frozen writer outputs, unchanged frames reproduce the identical
session and Atlas inputs. Durable-session scans also confirmed that outcome,
action, `next_obs`, and local-path fields are absent. These checks are adapter
tests; they do not reclassify synthetic source-shaped test bodies as the real
source conversion.

## 10. Information loss and claim boundary

The adapter deliberately discards source Z for both entities, every quaternion,
yaw, roll, pitch, the full robot articulation, velocities, contact/grasp state,
controller state, relative pose vectors, outcomes, annotations, and all visual
material. Nothing discarded is hidden in `extra` or another auxiliary stream.

Consequently, the fixture can evaluate only bounded world-XY occupancy and a
deterministic relative wait. It cannot evaluate 3D placement, orientation,
grasp/contact, official Can success or failure, physical accuracy, simulator
accuracy, source endorsement, safety, or general robomimic compatibility.

Episode selection was outcome-blind only within an upstream success-filtered
corpus.
