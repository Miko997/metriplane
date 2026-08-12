<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-18 robomimic Can field provenance and normalization loss

Status: **field and rule mapping frozen; adapter serialization, fixture hashes,
anti-taint execution, and Atlas run verification pending.**

This record defines the complete source-to-normalized map for the selected
robomimic Can Proficient Human `demo_0` fixture. The proposed portable record
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
| `robomimic_can_ph_raw` | `v1.5/can/ph/demo_v15.hdf5` | 64,932,974 | `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` | Required external audit/conversion input; not redistributed. |
| `robomimic_can_ph_low_dim` | `v1.5/can/ph/low_dim_v15.hdf5` | 46,889,752 | `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` | Required external conversion input; not redistributed. |

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

Every field planned for each normalized frame is listed below. The exact JSON
serialization and durable file hash remain pending implementation.

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

The planned `entity-mapping.json` uses schema
`metriplane.external_entity_mapping.v1`. Its semantic fields are frozen as
follows; byte identity is pending implementation.

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
`robomimic-can-ph-planar-control-v1`. Exact remaining durable IDs, labels,
YAML/CSV serialization, and domain-pack hashes must be reported by the
implementation. If implementation identifiers differ from this record, the
record must be updated before evidence freeze; semantic equivalence alone is
not a substitute for an exact provenance record.

## 8. Other durable outputs

| Artifact | Layers represented | Required contents | Current status |
| --- | --- | --- | --- |
| `source-manifest.json` | A-C metadata; D evaluation declaration | Exact code/dataset identities; both artifact paths, sizes and hashes; adapter `org.metriplane.robomimic_lowdim`; frozen-config SHA-256 `dc01dd3f300be3d660216bc07a0df67b3c57fc88416032fd54a2974abe964017`; lock/config identities; clock and coordinate maps; field provenance; exclusions, limitations, domain-pack hashes, and immutable relative paths only. | Schema-level content frozen; manifest bytes/hashes pending. |
| `normalization-report.json` | A-C audit record | Raw/prepared comparison result, both raw witnesses, 118-to-118 frame accounting, finite/complete checks, no-taint declarations, source non-mutation hashes, and deterministic-conversion comparison. | Source comparison demonstrated; conversion and determinism fields pending. |
| `expected-outcome.json` | Test metadata about D; never Atlas input | `atlas_input: false`; incident expected to exercise existing missing-tool delay semantics; control expected to remain non-incident. Actual event/deviation/incident counts and hashes must be frozen from verified runs, not invented here. | Pending Atlas runs. |
| `CHECKSUMS.sha256` | Artifact integrity | Sorted relative paths and content hashes; no machine-local paths or mutable references. | Pending fixture generation. |
| `source/*` records | A-C provenance | Deterministic frozen adapter config, dependency lock, and conversion environment record; no raw HDF5, model XML, simulator asset, or absolute path. | Pending fixture generation. |

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
Required anti-taint tests must change or remove excluded values in safe copies
and demonstrate byte-identical normalized session, entity mapping, domain pack,
waits, and Atlas semantics whenever normalized state is unchanged. Those
implementation tests remain pending.

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
