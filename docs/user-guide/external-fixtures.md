<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Validate and run an external fixture

An External Fixture Bundle is a portable, recorded input that has already been
converted to Metriplane's `FrameStateModel` 1.0 JSONL and Atlas process rules. The
software that produced the original source data is needed during conversion, not
when the finished bundle is validated or evaluated.

The person who gives you a fixture should provide one directory anchored by
`source-manifest.json`. Keep the directory together. You do not need to select its
session, mapping, or domain pack separately.

## Validate a fixture

Run the complete preflight before creating an Atlas run:

```bash
metriplane external validate path/to/fixture
```

For a machine-readable result, add `--json`:

```bash
metriplane external validate path/to/fixture --json
```

The JSON document uses schema version
`metriplane.external_validation_summary.v1` and includes the validated artifact
hashes, declared and installed versions, counts, checks, warnings, errors, and
limitations.

Validation checks the strict contract manifest, all included file hashes and the
checksum inventory, the normalized session, the entity-to-asset mapping, the
normalization report, and the existing Atlas domain pack. It also checks agreement
between those files. A referenced or withheld original source may remain outside
the bundle; Metriplane records its immutable identity but does not download it.

A normal validation failure prints an actionable error and exits nonzero without
running Atlas. Metriplane does not execute the adapter or any command named in the
manifest, and it does not modify the fixture.

## Run a validated fixture

Use a new output directory outside the fixture:

```bash
metriplane external run path/to/fixture --out external-run
```

The command repeats the full preflight, then passes the manifest-declared session
and domain pack to the existing Atlas engine. Atlas creates the event and incident
records and Incident Report. For each incident, it creates an evidence bundle and
generated regression check; a run with no incident has neither. The test-only
`expected-outcome.json` file is never supplied to Atlas and does not determine the
result.

For automation, request one JSON result on standard output:

```bash
metriplane external run path/to/fixture \
  --out external-run \
  --json
```

This document uses schema version `metriplane.external_run_summary.v1`. It nests
the complete validation result and reports the Atlas counts, generated artifact
paths, evidence verification, regression results, and provenance identity.

An explicit run identity and Atlas's existing overwrite control are optional:

```bash
metriplane external run path/to/fixture \
  --out external-run \
  --run-id inspection-replay-1 \
  --overwrite
```

Without `--overwrite`, an existing output is rejected. Even with it, the output
may not be the fixture, contain the fixture, or be placed inside the fixture.
An explicit `--run-id` is limited to 1-128 ASCII letters, digits, dots,
underscores, or hyphens and must start with a letter or digit. When it is omitted,
Metriplane derives a deterministic operational ID without using unsafe fixture
characters in generated artifacts.

## Provenance saved with the run

An external run writes the versioned
`metriplane.external_source_provenance.v1` record as
`external_source_provenance.json` in the run directory and references it from
`atlas_manifest.json`. The compact record preserves the
fixture and contract identities, source project and immutable revision, bounded
selection, source artifact identities, adapter version and commit, conversion
parameters and environment, normalized artifact hashes, domain-pack hashes,
clock and coordinate declarations, completeness policy, limitations, and the
Metriplane evaluation identity.

The Incident Report includes a concise external-source provenance section. Each
incident evidence bundle includes the versioned provenance record under
`provenance/` and covers it with the bundle checksum inventory. Conversion
provenance remains separate from the events and incidents derived by Metriplane.

## What an adapter must produce

An adapter runs outside this execution path. Before handing a bundle to someone
else, its author must produce a directory that satisfies the
[External Source Contract v1](../specs/external-source-contract-v1.md), including:

- a strict `source-manifest.json` with source, selection, rights, adapter,
  normalization, trust-layer, and limitation declarations;
- a complete-snapshot `FrameStateModel` 1.0 `session.jsonl` with deterministic
  IDs, monotonic authoritative time, known process-relevant state, and empty
  frame events;
- a hashed entity mapping from source entities to normalized objects and Atlas
  assets;
- the five declared domain-pack files containing only operator-configured process
  rules;
- a normalization report that accounts for every transform, projection,
  synchronization, resampling, interpolation, carry-forward, and zone-assignment
  operation;
- test-only expected-outcome metadata that is explicitly excluded from Atlas
  input; and
- a sorted `CHECKSUMS.sha256` inventory covering every included file except
  itself.

Source-specific metadata belongs only in inert namespaced extensions. Source
success, failure, reward, termination, task, or incident labels remain provenance
or selection metadata and cannot drive Atlas events or incidents. The adapter
must materialize partial updates into declared bounded complete snapshots or
reject them; unknown state cannot be encoded as physical absence.

An adapter author should validate the finished directory with the same public
command an evaluator will use. Once it passes, the recipient needs only the
portable fixture and a normal Metriplane installation. They do not need the
adapter, the original source framework, or access to a remote source that is
legally recorded as referenced or withheld.

## What a successful run means

A successful run establishes only that:

- the provided fixture satisfied its declared contract and local integrity
  checks;
- Metriplane evaluated its normalized recorded state under the supplied process
  rules; and
- the generated evidence and regression results passed under the tested
  conditions.

It does not prove that the original source was correct, that the state is physical
ground truth, that a simulator is realistic, that a sensor is accurate, or that
the workcell is safe or production-ready. It is not an endorsement, independent
adoption claim, quality-release decision, or universal source-format compatibility
claim. Metriplane remains recorded, local, observe-only, bounded, and planar.
