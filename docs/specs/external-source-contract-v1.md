<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External Source Contract v1

Status: frozen contract proposed by MET-13

Contract version: `metriplane.external_source_contract.v1`

Atlas profile: `metriplane.atlas.complete_snapshot.v1`
Normalized state: unchanged `FrameStateModel` `1.0`

## Purpose and claim boundary

External Source Contract v1 is a source-neutral, provenance-preserving protocol
for converting one bounded recorded robotics fixture into the input Metriplane
already evaluates:

```text
third-party source
  -> source-specific adapter
  -> portable External Fixture Bundle
  -> source-neutral contract validation
  -> unchanged Metriplane Atlas engine and domain pack
  -> events, deviations, incidents, report, evidence bundle, regression
```

The contract may establish only this claim:

> Metriplane has a documented, typed, source-neutral and
> provenance-preserving contract for converting bounded external robotics state
> into its existing incident-evaluation input.

It does not establish compatibility with a source family before a real adapter
and fixture exist. It does not establish source truth, physical accuracy, safety,
quality authority, production readiness, external adoption, or universal
robotics-data compatibility. It adds no robot control or live bidirectional
integration. Consumption remains recorded, local, observe-only, bounded, and
planar.

The contract version is independent of the Metriplane package version and the
`FrameStateModel` version. Metriplane `0.3.0`, FrameStateModel `1.0`, and contract
v1 are three different identities.

## Architectural invariants

1. `FrameStateModel` 1.0 remains the only normalized frame format.
2. Atlas domain packs remain the only process-rule format for this profile.
3. Atlas execution and its event/incident semantics remain unchanged.
4. Source adapters live outside the core contract. The core has no knowledge of
   HDF5, RLDS, ROS, MCAP, LeRobot, simulator, dataset, CSV, or vendor formats.
5. A converted fixture can be consumed without the source framework installed.
6. Conversion provenance and Metriplane evaluation provenance are separate.
7. Source labels do not become hidden incident truth.
8. Unknown observations do not become physical absence.
9. Positions do not automatically become zones.
10. Every transform, projection, temporal alignment, carry-forward operation,
    entity mapping, and zone assignment is explicit and bounded.
11. Rights and redistribution status are explicit even when permission is absent.
12. Source-specific metadata is allowed only in inert namespaced extensions.
13. The fixture is a bounded recording, not a controller or live integration.
14. All resulting claims remain observe-only and reproducibility-bounded.

The source-truth basis for these constraints is recorded in
[`external-source-contract-v1-audit.md`](external-source-contract-v1-audit.md).

## Four non-interchangeable trust layers

The bundle and manifest preserve four layers. Moving information between layers
without declaration invalidates the fixture.

| Layer | What belongs there | Where it is represented | What it cannot do |
| --- | --- | --- | --- |
| A. Source facts | Fields directly contained in identified source artifacts | Source artifact identity, selection, hashes, and `source_fact` field provenance | Cannot be called an Atlas result |
| B. Adapter-derived facts | Replay/restoration output, time conversion, transforms, projections, synchronization, resampling, entity mapping, and zone assignment | Adapter identity/environment/parameters, normalization declarations, entity mapping, and normalization report | Cannot silently become source fact or process rule |
| C. Operator-configured rules | Assets, zones, stations, ordered steps, required assets, and maximum waits | The hashed Atlas domain pack only | Cannot be presented as source annotation or discovered truth |
| D. Metriplane-derived results | Events, deviations, incidents, report, evidence verification, and regression result | A later Atlas run output only | Cannot be supplied in `session.jsonl` or used to normalize the source |

`trust_layers` is a required manifest guard. `expected-outcome.json` belongs to
test metadata, not to any Atlas input. A contract validator may validate and hash
that file, but Atlas receives only `session.jsonl` and `domain-pack/`.

## Portable External Fixture Bundle

The v1 portable layout is:

```text
external-fixture/
├── source-manifest.json
├── session.jsonl
├── entity-mapping.json
├── domain-pack/
│   ├── assets.yaml
│   ├── workspace.yaml
│   ├── process.yaml
│   ├── contracts.yaml
│   └── work_orders.csv
├── normalization-report.json
├── expected-outcome.json
├── source/                         # optional included source material
└── CHECKSUMS.sha256
```

An original source artifact does not have to be redistributed. An artifact may be
`included`, `referenced`, or `withheld`. An included artifact requires a bundle
path and SHA-256. A referenced or withheld artifact requires an absolute URI and
either a SHA-256 or documented immutable identifier. A source trajectory and its
metadata sidecar are separate artifacts with separate roles, identities, and
artifact-scoped rights records.

Every bundle path uses `/`, is relative, contains no empty, dot, parent, Windows
drive, NUL, or backslash segment, and resolves only to a regular nonsymlink file.
`CHECKSUMS.sha256` inventories every included file except itself, uses lowercase
SHA-256 values, and is sorted by path. It must never contain a self-reference.
The session, normalization report, and expected outcome have distinct paths and
cannot be reused as source, adapter-parameter, environment, transform, mapping,
or other conversion-input roles. In particular, test expectations cannot feed
conversion or evaluation.

The positive fixture is
[`examples/external_sources/minimal`](https://github.com/Miko997/metriplane/tree/main/examples/external_sources/minimal).
It deliberately uses a new synthetic inspection-bench scenario rather than the
bundled torque-driver demo.

## Manifest sections

The authoritative machine-readable definition is the strict Pydantic model in
`metriplane/external_sources/contract.py`; the generated schema is
`schemas/metriplane.external_source_contract.v1.schema.json`. Every shared model
forbids unknown fields. The only escape hatch is `extensions`.

The manifest requires these sections:

| Section | Required semantics |
| --- | --- |
| `fixture` | Stable fixture identity, bounded-recording assertion, description, and distribution class |
| `source_project` | Canonical project URI, version, and immutable revision kind/value |
| `source_artifacts` | One or more role-bearing artifacts with media type and verifiable identity |
| `selection` | Bounded whole-artifact, episode, group, index, time, or externally hashed selection |
| `rights` | Artifact-scoped source rights plus separate normalized-fixture access, license, citation, permission, and redistribution boundaries |
| `adapter` | Namespaced ID, version, immutable commit, entry point, repository, exact environment identity, and canonical parameters hash |
| `normalization` | FrameState version/backend, authoritative collection, clock, coordinates, projection/loss, mappings, completeness, temporal policies, confidence, and annotation treatment |
| `domain_pack` | Stable ID, operator-configured origin, source-annotation exclusion, rationale, and separate hashes for all five canonical Atlas files |
| `normalized_artifacts` | Hashed session, report, test-only expected outcome, and checksum path |
| `evaluation` | Atlas, exact Metriplane version, domain-pack ID, and evaluation-provenance boundary |
| `trust_layers` | Fixed declarations that keep the four truth layers separate |
| `limitations` | Concrete information loss, exclusions, and unsupported claims |
| `extensions` | Optional inert JSON-safe source metadata under reverse-domain-like keys |

Large entity mappings and adapter parameters should use separately hashed files.
Every operational parameter reference carries its own path and hash. They are not
inlined merely for convenience.

## Complete-snapshot profile rules

The profile exists because Atlas has no unknown/absent tri-state. Atlas evaluates
the current authoritative object list only. An omitted mapped required asset, or
one outside its required zone/station, can satisfy its missing-required-asset
condition. Contract validation therefore fails closed before Atlas runs.

For `metriplane.atlas.complete_snapshot.v1`:

- `frame_semantics` is exactly `complete_snapshot`.
- Every process-relevant mapped entity is represented with known finite position
  and known deterministic zone in every evaluated frame.
- Omission is rejected. v1 does not encode physical absence by omission.
- Partial-update source streams must be materialized into complete snapshots with
  a structured, hashed materialization operation, or rejected. Bounded
  last-observation materialization must name the same fields and maximum gap as
  the declared carry-forward policy. Every materialization also declares a
  machine-readable `carry_forward_dependency`; no value represents unbounded or
  undeclared forward filling.
- Unknown, unavailable, invalid, or unobserved process-relevant state rejects the
  fixture. It never becomes absence.
- Carry-forward is either `none` or explicitly bounded by fields and maximum gap.
- Interpolation, resampling, and synchronization are always present as policy
  objects, including when their method is `none` or `not_applicable`.
- Linear, nearest-neighbor, hold, fixed-rate, and windowed policies require their
  fields and maximum gap/skew parameters.
- Frame IDs start at zero and are contiguous and ordered for this profile.
- The declared evaluation clock is used consistently and is strictly monotonic.
- `ts_sim_ns` is required on every frame when it is authoritative and prohibited
  when the manifest declares `ts` authoritative.
- Object IDs are stable, nonempty, and unique in each authoritative snapshot.
- Nonfinite JSON values and duplicate JSON keys are invalid.
- `objects` authority requires `fused` to be absent or null. `fused` authority
  requires `fused` on every frame and an empty mandatory `objects` collection.
- Metriplane run/config/git provenance is not embedded as conversion provenance.
- Frame metrics, object `extra`, and raw-camera metadata are outside this profile;
  source-specific material belongs in namespaced manifest extensions.

Known source state outside a required work area may use another declared workspace
zone or the declared outside-workspace label. This is distinct from unknown state.
Every authoritative object ID must occur in `entity-mapping.json`; every declared
mapping must occur in the bounded session. This prevents Atlas's silent ignoring
of an undeclared object from hiding a mapping error.

## Clock, coordinates, projection, and zones

Clock mapping records the source clock and field, source unit, chosen evaluation
field, method, parameters, and description. Supported declarations are identity
seconds, fixed step with an explicit nanosecond origin, affine mapping, and a
separately hashed lookup table. The validator checks the fixed-step formula and
any declared fixed-rate or selected-frame interval bound. The
manifest does not change Atlas's existing rule that `ts_sim_ns`, when present,
wins over `ts`; it ensures only one interpretation is supplied.

Coordinates require source/target frame and units, an explicit transform object,
an explicit projection object, and information loss for every nonidentity
projection. Identity is legal only when both frame and units match. A matrix,
homography, or custom operation requires a separately hashed parameter file.

Zone assignment is a distinct operation. `pos_world` does not cause Atlas to
evaluate workspace polygons. The adapter assigns the final zone under its declared
method, definitions hash, boundary policy, overlap policy, outside policy, and
implementation. Contract validation verifies that normalized zone labels are
declared by the workspace or equal the explicit outside label. For the v1 polygon
method it also recomputes inclusive or exclusive polygon membership, rejects or
resolves overlap under the declared policy, and compares the result with the
emitted zone. Other methods remain bound to their separately hashed implementation
or lookup parameters. A zero-output projection is checked against normalized z.

## Identity and asset mapping

`entity-mapping.json` uses
`metriplane.external_entity_mapping.v1`. Each record separates:

1. one or more source artifact/entity identities;
2. normalized `ObjectStateModel.id`;
3. Atlas `asset_id` in `assets.yaml`;
4. whether the mapping is process-relevant.

Normalized-object to Atlas-asset mapping is one-to-one in v1. One normalized
object may declare several source identities only with an explicit, hashed fusion
method; this supports multi-stream state without a source-specific core field.
Contract validation verifies every source artifact, normalized object ID, Atlas
asset ID, and `assets.yaml.object_id` relationship.
Every asset referenced by a process required-asset rule, or by an expected asset
type, must have a process-relevant mapping.

## Field provenance and confidence

Every normalized semantic field that appears in the authoritative session has one
`field_provenance` record. A direct source fact identifies source artifact(s) and
source field(s). Except for the declared schema/backend constants, an
adapter-derived fact supplies explicit source fields, a derivation, and any
separately hashed parameter references. Identity assignment, nonidentity clock mapping,
transforms, projections, zone algorithms, synchronization, resampling,
interpolation, materialization, and carry-forward are cross-checked against the
affected adapter-derived fields. Temporal policy field names are restricted to
normalized fields rather than free text.

Confidence has exactly one policy:

- `absent`: confidence is not emitted;
- `source`: every authoritative observation receives a direct source value and its
  source field is declared; or
- `documented_algorithm`: every authoritative value is attributed to a named
  algorithm, hashed implementation and parameters, declared input fields,
  explicit output semantics, matching adapter-derived field provenance, and the
  machine-readable `placeholder_or_invented_values: false` attestation.

An emitted confidence value with no declared origin is prohibited. The contract
cannot represent a placeholder or invented confidence as compliant. It does not
infer calibration, fabrication, or physical accuracy from output variance;
identical values may be legitimate algorithm output when the declared inputs,
implementation, parameters, semantics, and non-invention attestation are present.
The declaration is auditable provenance, not proof that an algorithm or source
was correct.

## Source annotation policy

Success, failure, reward, terminated/truncated flags, language/task/subtask labels,
and similar annotations may be retained only as provenance or source-selection
metadata. The inventory is complete, names the source field and artifact, and
states where each value is retained. An annotation source field may not also feed
normalized time, identity, pose, zone, or confidence provenance. For this profile:

- `used_as_incident_truth` is always false;
- `used_as_process_events` is always false;
- source incident IDs are absent from normalized input;
- `FrameStateModel.events` is empty on every frame; and
- no upstream event bypasses Atlas's domain-pack process rules.

The positive source sidecar intentionally contains success, reward, termination,
and task annotations. None appears in `session.jsonl` and none affects the five
Atlas events or incident.

## Namespaced extensions

`extensions` keys use a reverse-domain-like namespace with at least three
segments, for example `org.maniskill.trajectory`. Values must be ordinary JSON
with finite numbers and string keys. Extensions are inert. They cannot use the
reserved `metriplane.*` namespace or contain fields that claim to override
validation, domain-pack rules, events, or incident truth.

If several independent adapters need the same semantic field, that field is
considered only in a future versioned contract change. It is not added ad hoc as
`maniskill_*`, `calvin_*`, `robomimic_*`, or similar shared state.

## Rights and distribution profiles

The contract represents restrictions; it does not grant permission.

Each source artifact points to a specific source-rights record. This allows a
trajectory, metadata sidecar, calibration file, and prepared derivative to carry
different access, license, citation, source-use, and redistribution terms. A
separate fixture-rights record governs the normalized bundle; it cannot silently
inherit or override source permission.

| Fixture profile | Source handling |
| --- | --- |
| `public` | Public manifest/derived fixture; source license and use permission must be resolved |
| `reference_only` | Source artifact stays external and is identified by hash or immutable ID |
| `derived_only` | Only an authorized normalized derivative is distributed |
| `proprietary` | Rights and restrictions are declared; source material is not presumed redistributable |
| `private` | Source and fixture remain private; included source material requires verified private use and redistribution permission |

An included public artifact requires allowed or verified redistribution. A
`reference_only` or `derived_only` fixture cannot include source bytes. A private
fixture may include source bytes only when both its fixture boundary and that
artifact's use/redistribution permission are explicitly verified as private. A
public fixture rejects an unknown source or fixture license and unresolved
source-use permission. Unresolved or restrictive status may be recorded for a
nonincluded private, proprietary, or referenced source, but it is never permission
to use or publish it.

## Reproducibility is two separate stages

### Stage 1: conversion reproducibility

```text
same identified source artifacts and bounded selection
+ same adapter commit, parameters, and environment
-> equivalent normalized session and mapping artifacts
```

`conversion_inputs_sha256()` fingerprints only Stage 1 declarations. The
normalization report records the comparison policy, run identities, input fingerprint,
and a separate artifact-hash map for every conversion run. Equal inputs are
necessary but do not by themselves prove equal output. A demonstrated result
requires at least two named runs whose complete declared output maps are equal.
For v1, those maps contain exactly `session.jsonl` and `entity-mapping.json`;
operator rules, source inputs, evaluation results, and test metadata cannot be
folded into the conversion-equivalence claim. The positive
reference conversion regenerates and byte-compares both twice. The entity mapping
hash is treated as an output rather than folded tautologically into the Stage 1
input fingerprint; its deterministic mapping rules are part of the hashed adapter
parameters. The generated mapping path itself cannot also serve as an adapter,
selection, environment, transform, or other Stage 1 input.

### Stage 2: Metriplane evaluation reproducibility

```text
same normalized session
+ same Metriplane version
+ same domain pack
-> equivalent events and incidents, passing evidence verification,
   and the same generated regression result
```

`evaluation_inputs_sha256()` fingerprints Stage 2 inputs separately. The positive
test runs Atlas twice, compares event and incident artifacts, verifies both evidence
bundles, and runs both generated regressions. Stage 2 makes no statement about
whether Stage 1 correctly represented the source.

The normalization report also has exact operation coverage. Every clock, mapping,
transform, projection, zone, materialization (when applicable), synchronization,
resampling, interpolation, and carry-forward declaration appears exactly once with
an `applied` value consistent with the manifest.

## Adapter-author checklist

- [ ] Give every source artifact a role, media type, rights-record reference, hash
      or immutable identifier, license/citation, use/redistribution permission,
      and inclusion/reference/withholding status. Declare fixture rights separately.
- [ ] Select exactly one bounded episode, group, index range, time range, or small
      complete artifact.
- [ ] Pin the adapter ID, version, immutable commit, environment, and canonical
      parameters hash.
- [ ] Declare direct versus replay/restored/derived source state.
- [ ] Declare the evaluation clock and every time conversion.
- [ ] Declare source/target frames, units, transforms, projection, and information
      loss.
- [ ] Create the source entity/entities -> normalized object -> Atlas asset map;
      hash any declared multi-source fusion operation.
- [ ] Select `objects` or `fused` authority and honor its exact profile rule.
- [ ] Produce complete known snapshots for every process-relevant entity; reject
      unknowns and omissions.
- [ ] Declare synchronization, interpolation, resampling, and carry-forward even
      when not used.
- [ ] Assign zones deterministically and declare boundaries, overlaps, and outside
      handling. Never assume Atlas converts position to zone.
- [ ] Omit confidence or prove its direct source/algorithm origin.
- [ ] Keep source reward, success, fail, termination, task, event, and incident
      labels out of Atlas semantics and keep `FrameStateModel.events` empty.
- [ ] Put only inert JSON-safe source detail in namespaced extensions.
- [ ] Include and hash all five domain-pack files and explain the operator rule.
      Assert that no source annotation was used to create or bypass that rule.
- [ ] Keep `expected-outcome.json` test-only and out of Atlas input.
- [ ] Produce a normalization report with exact operation coverage and two
      independent per-run output-hash maps for session and entity mapping.
- [ ] Validate the portable bundle without the source framework installed.
- [ ] Run Atlas twice; compare events/incidents; verify evidence; rerun regression.
- [ ] Record limitations and use only the permitted contract claim.

## Pilot data-requirement table

| Requirement | Minimum acceptable material | Reject or stop when |
| --- | --- | --- |
| Bounded selection | Stable episode/group/file plus start/stop where applicable | Selection can drift or requires an unbounded dataset copy |
| Artifact identity | SHA-256 or documented immutable identifier for every source/sidecar | A required source file can change without detection |
| Rights | Per-artifact source rights plus separate fixture license, citation, use/redistribution permission, and basis | A public fixture is unresolved, or private inclusion lacks verified private permission |
| Entity identity | Stable source entity/entities -> normalized object -> Atlas asset mapping, with hashed fusion when needed | IDs are reused, inferred nondeterministically, or cannot be stabilized |
| State | Known finite pose/position and zone for every process-relevant entity per frame | Data is partial/unknown and cannot be safely materialized |
| Clock | Source clock/field/unit plus deterministic evaluation mapping | Time decreases, mixes clocks, or alignment has no bounded gap |
| Coordinates | Source/target frame, units, transform, projection, loss | Frame/unit conversion is implicit or parameters are unavailable |
| Zones | Deterministic method, definitions hash, boundaries, overlaps, outside policy | Zone labels are guessed or derived by undocumented thresholds |
| Confidence | None, direct source value, or documented algorithm | A constant is invented to satisfy the field |
| Annotations | Provenance/selection-only list | Success/reward/failure/event/incident label would drive Atlas |
| Adapter | Version, immutable commit, parameters, environment lock/digest | Conversion cannot be recreated or environment identity is missing |
| Domain pack | All five files, one work order, observe-only rule rationale | Rule encodes source outcome or unsupported safety/quality authority |
| Reproducibility | Two equivalent conversions and two equivalent evaluations | Either stage is collapsed into or used to prove the other |

## Source-family compatibility matrix

This matrix is a design fit analysis, not an implemented compatibility claim.

| Source family | Source artifacts and extraction | Direct vs derived fields | Clock and coordinates | Completeness and zones | Rights and annotations | v1 fit |
| --- | --- | --- | --- | --- | --- | --- |
| ManiSkill trajectory HDF5 + metadata | HDF5 trajectory plus exact metadata sidecar; use official replay or environment-state restoration and stable actor extraction | Stored trajectory values are source facts; replayed poses, actor mapping, projection, and zones are adapter-derived | Record stored step/time and configured horizon separately; pin source frame and workcell transform | Materialize every relevant actor each evaluated step; assign zones after projection | Pin source revision/license; success, fail, reward, terminated, and truncated remain provenance only | Yes, with a source-specific adapter and no shared-schema change |
| CALVIN direct semantic state | Episode files plus task/language metadata; extract already-semantic scene and robot/object state | Named state is direct where stored; reshaping, entity mapping, projection, and zones are derived | Declare dataset timestamps/index mapping and CALVIN/world-to-workcell transform | Verify each timestep is complete or restore/materialize before export | Preserve dataset citation/license; language/task success is selection/provenance only | Yes, without shared fields |
| robomimic low-dimensional HDF5 | Dataset HDF5 and environment metadata; read low-dimensional observations or use official environment restoration | Stored observations are direct; restored simulator poses and normalization are derived | Demonstration index/time mapping and environment/world frame are explicit | Observation keys may be incomplete; reject or restore a full relevant snapshot | Dataset/source licenses can differ; rewards/dones/task labels are not incident truth | Yes, when completeness is established |
| MimicGen raw + preparation pipeline | Raw source HDF5 plus generated/prepared artifacts and preparation configuration | Raw states are source facts; `datagen_info`, restored poses, transforms, and preparation output are separately derived | Record raw and prepared clocks and every alignment; declare environment transform | Preparation must not hide omitted entities; generate complete snapshots and deterministic zones | Hash raw and prepared artifacts separately; success/task/subtask labels remain provenance | Yes, with separate derivation identities |
| ROS 2 / MCAP pose or TF stream | Bag/MCAP plus message definitions and optional calibration/TF sidecars; read already-estimated poses/TF only | Message fields are direct; TF composition, synchronization, resampling, entity naming, and zones are derived | Choose ROS/header/bag clock; pin TF chain, units, maximum skew, and interpolation gaps | Topic streams are usually partial; materialize bounded snapshots or reject | Respect recording privacy/ownership; diagnostics/events are not Atlas incidents | Yes for already-estimated state, not raw sensor interpretation |
| Custom JSONL/CSV export | One or more files plus schema/data dictionary; declarative field extraction | Exported cells/keys are direct; parsing, time/unit conversion, IDs, and zones are derived | Declare column/key clock and coordinate mapping | Require complete rows/groups or a bounded materialization policy | Record owner permission and redistribution; source status columns remain provenance | Yes, without format fields in the shared model |
| Proprietary bounded workcell export | Private files, schema/data dictionary, calibration, and immutable internal identifiers; source may be withheld | Authorized exported fields are direct; anonymization, transforms, mapping, and zones are derived | Pin vendor/site clock mapping and approved coordinate transform | Validate complete relevant state inside the authorized environment before creating a permitted derivative | Use private/proprietary/reference/derived-only profile; do not infer publication permission; production labels remain provenance | Yes, even when source is not redistributed |

All seven families fit without a source-specific shared field. A request for one
would be routed to adapter parameters, an inert namespaced extension, or a future
versioned contract proposal.

## Versioning and migration policy

- Contract identifiers are immutable. v1 meaning is not changed in place.
- Editorial clarification may be made without changing machine semantics, but the
  checked-in schema and normative model remain the arbiter.
- A new required field, changed default/condition, widened incident influence, or
  new authoritative semantics requires a new contract/profile identifier.
- Optional source-specific metadata never changes v1 validation or Atlas behavior.
- A field observed across several independent source families is promoted only by
  a reviewed, versioned contract change with migration examples.
- Consumers reject unsupported contract/profile versions; they do not guess.
- A future migration tool must preserve the original manifest and record the
  migrator identity, parameters, input/output hashes, information loss, and reason.
- Updating Metriplane does not automatically migrate a contract. Updating a
  contract does not change FrameStateModel 1.0.
- JSON Schema regeneration is intentional. The byte-for-byte drift test must be
  updated only with reviewed Pydantic/model changes.

## MET-15 ManiSkill handoff

MET-13 does not implement or claim ManiSkill support. MET-15 should build the first
real adapter under these exact conditions:

1. Identify the exact HDF5 trajectory and exact metadata sidecar separately, with
   roles, hashes/immutable IDs, source repository/version/revision, license,
   citation, and redistribution status.
2. Record the selected trajectory/episode and full stored trajectory length. Keep
   the configured RL/task horizon as separate metadata; do not substitute one for
   the other.
3. Use and pin the official replay or environment-state restoration route. Prefer
   state restoration where action replay may diverge; declare the route and any
   divergence limitation.
4. Extract stable actor/entity identities and record the one-to-one source actor ->
   normalized object -> Atlas asset map.
5. Pin the source frame, units, source-to-workcell transform, planar projection,
   dropped information, and deterministic zone-assignment policy.
6. Generate a complete known snapshot for every process-relevant mapped actor at
   each evaluated frame. Reject unknown state and do not encode it as absence.
7. Keep source success, fail, reward, terminated, truncated, task, and subtask
   annotations in provenance/selection only. Do not populate source incidents or
   `FrameStateModel.events`.
8. Pin the adapter repository, version, full commit, canonical parameters, Python
   and dependency lock/container identity, simulator/source revision, and command.
9. Run conversion twice from the same identified source/selection and demonstrate
   byte-equivalent normalized session and mapping hashes.
10. Deliver the portable fixture with the manifest, session, full domain pack,
    mapping, normalization report, test-only expected outcome, and checksum
    inventory. Consumption and Atlas evaluation must succeed after ManiSkill and
    its heavy dependencies are removed from the environment.
11. Run Atlas twice and separately demonstrate equivalent events/incidents,
    evidence verification, and regression results.
12. Report limitations and make no compatibility, physical-truth, safety,
    production, or independent-adoption claim beyond the exact tested fixture.

Source-specific conversion remains outside the generic consumer. A finished
fixture is validated and evaluated without executing its adapter or installing
the original source framework.

## Canonical validation and Atlas consumption

The source-neutral model API remains available:

```python
from metriplane.external_sources import validate_external_fixture_bundle

fixture = validate_external_fixture_bundle("external-fixture")
```

Installed users can validate the whole fixture without selecting its files
individually:

```console
metriplane external validate external-fixture
metriplane external run external-fixture --out external-fixture-run
```

The external command verifies the manifest, included hashes, normalized session,
mapping, normalization report, and domain pack before passing only the declared
`session.jsonl` and `domain-pack/` to Atlas. It never fetches a referenced source
or executes the historical adapter command. Source artifacts, extensions, and
`expected-outcome.json` do not bypass or modify Atlas process rules.
