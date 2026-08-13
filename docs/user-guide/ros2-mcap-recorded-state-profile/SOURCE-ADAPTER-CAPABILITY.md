<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Source Adapter capability specification v1

## Purpose

`metriplane.source_adapter_capability.v1` is a strict metadata record that
states whether one adapter has the evidence and declared behavior required to
construct one External Source Contract v1 bundle.

It is not a decoder, plugin interface, registry, state model, or compatibility
claim. It does not authorize conversion merely because a file parses. The
record is evaluated together with the evidence it identifies.

The authoritative schema and validator are isolated in:

- `adapters/source_adapter_sdk/src/metriplane_source_adapter_sdk/schemas/metriplane.source_adapter_capability.v1.schema.json`
- `adapters/source_adapter_sdk/src/metriplane_source_adapter_sdk/validation.py`

The package has no runtime dependencies and is not included in the ordinary
Metriplane wheel.

## Evidence basis

The field set comes from repeated responsibilities in the frozen ManiSkill and
robomimic adapters. It does not contain a field merely because ROS needs it.

| Field group | Class | Basis |
| --- | --- | --- |
| Contract, profile, and FrameStateModel identity | A | Required by External Source Contract v1 |
| Source artifacts, immutable revisions, hashes, and rights | A | Required by Contract v1 |
| Clock authority, field, domain, unit, and mapping | B | Existing Contract v1 declaration with reusable fail-closed checks |
| Frames, units, transform, projection, and information loss | B | Existing Contract v1 semantics reusable across adapters |
| Stable source and normalized identity | B | Existing Contract v1 entity mapping responsibility |
| Complete snapshots, omission, unknown state, interpolation, resampling, synchronization, and carry-forward | B | Existing complete-snapshot profile responsibility |
| Field provenance and trust-layer separation | B | Existing Contract v1 provenance responsibility |
| Source-annotation inventory and anti-taint policy | B | Existing Contract v1 source-annotation responsibility |
| Adapter commit and isolated environment lock | C | Repeated conversion-provenance responsibility |
| Deterministic clean-run result | C | Repeated adapter permission gate |
| Conversion dependency isolation and portable evaluation | C | Repeated source-dependency boundary |
| Supported and prohibited Atlas semantics | C | Repeated claim-boundary responsibility |
| ROS topic, MCAP channel, message schema, TF chain, HDF5 key, or simulator API | D | Source-specific configuration, excluded from the shared schema |

Class A is already required by the contract. Class B reuses contract semantics.
Class C captures a repeated adapter responsibility not represented as one common
permission gate. Class D stays source-specific.

## Required record sections

| Section | Meaning |
| --- | --- |
| `schema_version` | Immutable capability schema identifier |
| `record` | Post-hoc or native classification, evidence class, subject, and statement |
| `contract` | Exact contract/profile/state-model identity and fit status |
| `adapter` | Adapter ID, version, implementation commit, entry point, isolated runtime, lock hash, and conversion dependencies |
| `source` | Source family, project, immutable revision, artifacts, and separate rights boundary |
| `capabilities` | Artifact, rights, clock, coordinate, identity, provenance, completeness, loss, anti-taint, deterministic conversion, portability, and semantics declarations |
| `evidence` | Hashed repository files, immutable Git identities, or workflow identities |
| `limitations` | Nonempty, record-specific limits |

Unknown fields fail validation. IDs, commits, hashes, paths, statuses, and
enumerations have strict syntax. JSON input rejects duplicate keys and nonfinite
numbers.

## Evidence classification

The record distinguishes:

- `external_source`: reviewed evidence for one exact external source boundary;
- `synthetic_format_engineering`: a Metriplane-authored format exercise.

A complete synthetic record may validate structurally. It still cannot be
assessed as permission for an external-source claim. This distinction is
mandatory and is not overridden by test coverage or deterministic conversion.

## Canonical form and fingerprint

Canonical capability JSON uses UTF-8, sorted object keys, compact separators,
finite values, and one final line feed. This is a bounded repository canonical
form, not an RFC 8785 claim. The capability fingerprint is SHA-256 over those
validated canonical bytes.

Repository evidence verification rehashes each referenced regular file and
rejects unsafe paths, symlinks, missing paths, and drift. Fingerprint equality
does not prove the declarations are true. It proves only that the same validated
record bytes were assessed.

## Permission decision

An external-source-permitted assessment requires verified contract fit, artifact
identity, rights, authoritative non-order-only clock, coordinates, stable
identity, complete provenance, complete-snapshot behavior, declared loss,
anti-taint separation, deterministic conversion, portable source-independent
evaluation, and bounded semantics. Any missing or `not_demonstrated` required
capability fails closed.

The synthetic evidence class is never external-source-permitted.

## Nonfeatures

The SDK intentionally has no dynamic plugin discovery, source reader, topic
discovery, source registration, dependency-injection framework, state schema,
runtime Atlas hook, or automatic semantic inference.

