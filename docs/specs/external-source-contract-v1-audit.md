<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-13 source-truth audit

Audit baseline: `1c5ee2dec7a363aeb00c02c9f151214a3605bbc1` on the `main`
branch. This note records the compatibility boundary that was established before
implementing External Source Contract v1.

## Sources reconciled

The audit read the current implementation and documentation together, with code
and tests taking precedence over historical examples:

- `metriplane/schema.py`;
- `metriplane/atlas/runtime.py`, `process_model.py`, `domain_packs.py`, and
  `models.py`;
- `metriplane/recording/jsonl.py` and
  `metriplane/provenance/run_provenance.py`;
- `metriplane/atlas/cli.py`;
- `docs/user-guide/inputs-and-outputs.md`, `use-your-own-run.md`, and
  `integrations.md`;
- `docs/contributor_extension_rules.md` and `ROADMAP.md`;
- the current schema, recording, Atlas, evidence, demo, CLI, documentation,
  package-boundary, and release-fixture tests; and
- `pyproject.toml`, `mkdocs.yml`, and the package configuration.

`ROADMAP.md` still lists a possible read-only rosbag2/MCAP importer as future
work. That is not current support and does not override MET-13's source-neutral
boundary or the formal MET-15 ManiSkill-first pilot direction. MET-13 implements
neither route. Any later importer or adapter remains downstream of this contract
and produces the same portable bundle.

## Authoritative input boundary

Atlas consumes one `FrameStateModel` 1.0 JSON object per JSONL frame plus one
Atlas domain-pack directory. The existing `metriplane atlas run` path validates
the frames with the Pydantic model in `metriplane/schema.py` and validates the
domain pack before evaluating it. MET-13 must wrap that boundary; it must not
replace it with another state model or change Atlas execution.

`FrameStateModel` requires `source_backend`, `ts`, `frame_id`, and `objects`.
Positions, velocities, zones, confidence, fixed-step time, fused state, raw
camera state, events, metrics, and run provenance are optional. The base model
rejects nonfinite numbers and duplicate IDs within each object collection, but
it intentionally remains backward compatible and does not forbid every unknown
field. External Source Contract strictness therefore belongs in the new profile
validator, not in `FrameStateModel`.

## Clock and ordering behavior

Atlas evaluates a frame at `ts_sim_ns / 1e9` when `ts_sim_ns` is present and at
`ts` otherwise. Fixed-step time therefore overrides source time per frame. The
runtime accepts nondecreasing evaluation time and does not currently require a
uniform clock field, contiguous frame IDs, or ordered frame IDs. Contract profile
`metriplane.atlas.complete_snapshot.v1` must declare one clock mapping, use it
consistently, require deterministic ordered frame IDs, and validate time before
passing the unchanged session to Atlas.

## Objects, assets, zones, and stations

Atlas uses `fused` whenever it is not `None`, including when it is an empty list;
otherwise it uses `objects`. `raw_per_camera` does not drive Atlas process
evaluation. The external manifest must identify the authoritative collection and
the profile validator must enforce that declaration.

`assets.yaml` maps a normalized object ID to an Atlas asset. Unmapped objects are
ignored. Atlas consumes each object's supplied `zone` label directly: workspace
polygons do not derive zones from `pos_world`. A station is derived only from the
domain pack's exact zone-to-station mapping. Position-to-zone conversion must
therefore remain an explicit, deterministic adapter operation with a declared
boundary and overlap policy.

## Omission and unknown state

Atlas evaluates only the current frame and has no carry-forward or tri-state
presence representation. A required mapped asset omitted from the authoritative
collection, or present outside its required zone or station, can become a
missing-required-asset condition. `FrameStateModel` cannot itself distinguish
confirmed physical absence from an unknown or unobserved entity.

The complete-snapshot profile must resolve this before Atlas. Every
process-relevant mapped entity must have known state in every evaluated frame.
Partial updates must be materialized under declared bounded policies or rejected;
unknown state and ambiguous omission must fail validation and must never silently
become physical absence. Forward fill, interpolation, resampling, and
synchronization are prohibited unless explicitly declared with their limits.

## Domain-pack behavior

The current pack requires `assets.yaml`, `workspace.yaml`, and `process.yaml`.
`contracts.yaml` and `work_orders.csv` are loader-optional, but the portable
external-fixture profile requires both so the bundle is inspectable. Validation
checks unique IDs, cross-file asset/zone/station/type references, station-to-zone
consistency, finite nonnegative waits, and exactly one effective work order.
Process steps execute in order. Contracts are validated metadata, not an
alternative executable rules engine.

## Provenance and hashing

`metriplane/provenance/run_provenance.py` already exposes canonical JSON and
streaming SHA-256 helpers. Existing run provenance describes Metriplane capture
or evaluation. External conversion provenance must remain a separate manifest:
source identity, adapter identity, parameters and environment, derivations, and
normalized output hashes cannot be collapsed into an Atlas run record.

Atlas evidence bundles also establish the existing safe pattern for relative
paths and checksum inventories: no absolute, backslash, dot, or parent-traversal
paths; no symlinks; every included file is inventoried; and the checksum file
does not checksum itself.

## Compatibility constraints frozen by MET-13

- Keep `FrameStateModel` 1.0 and its existing JSONL compatibility unchanged.
- Keep Atlas's `fused` precedence, clock selection, process evaluation, output,
  evidence-bundle, and regression behavior unchanged.
- Keep existing domain packs and their loader/validator behavior unchanged.
- Do not add source-framework fields, dependencies, importers, or a public
  conversion/run command in MET-13.
- Require `FrameStateModel.events` to be empty for this v1 profile. Source
  success, failure, reward, termination, task, subtask, event, and incident labels
  remain source-selection or provenance metadata only.
- Preserve the observe-only, bounded planar interpretation. The contract does not
  establish source truth, physical accuracy, safety, production readiness,
  external adoption, or compatibility with a source family before an adapter and
  fixture exist.
- Leave the frozen v0.1.3 and v0.2.0 artifacts, tags, evidence, and manuscript
  boundaries untouched, and do not change the v0.3.0 package boundary.

Historical or illustrative documents that conflict with the current Pydantic
models, Atlas runtime, tests, or current user guide are not source truth for this
contract.
