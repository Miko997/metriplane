<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External fixture execution implementation audit

This note records the source audit completed before adding the installed-package
validation and execution path. The starting commit is
`eeedeaa362a4c9bb7f74bf0770ee24a963051552`.

## Existing validation boundary

`load_external_source_manifest()` performs strict JSON and Pydantic validation of
the External Source Contract v1 manifest. `validate_external_fixture_bundle()` is
the complete source-neutral preflight and returns a `ValidatedExternalFixture`.
It already validates the checksum inventory and local hashes, rejects symlinks and
unsafe paths, reuses Atlas domain-pack validation, validates the entity mapping and
`FrameStateModel` 1.0 session, enforces complete known snapshots, and checks the
normalization report and test-only expected-outcome metadata for agreement.

The execution layer must call that validator rather than recreate any of its
contract, frame, mapping, zone, or process checks. What remains is orchestration:
stable result summaries, installed CLI commands, output-root safety, invocation of
the existing Atlas engine, verification of generated evidence and regression
artifacts, and propagation of external-source provenance.

## Atlas integration point

`run_atlas()` validates and evaluates the session and domain pack in a temporary
staging directory. `_run_atlas_in_place()` writes the report, manifest, evidence
bundles, and regressions before the completed directory is published atomically.
The smallest backwards-compatible integration is therefore an optional external
provenance payload on `run_atlas()`, defaulting to absent. When present, Atlas can
write and hash `external_source_provenance.json` before rendering the report and
exporting incident bundles. Ordinary Atlas runs require no new input or artifact.

`export_bundle()` currently copies a fixed set of run files, generates a dynamic
checksum inventory, and verifies every regular file in the bundle. An external run
can conditionally copy the provenance artifact into `provenance/`, list it in that
bundle's manifest, and reuse the existing checksum and safe-extraction behavior.

## Preserved boundary

External execution consumes only the manifest-declared normalized session and
domain-pack directory. It never executes the recorded adapter entrypoint, fetches
referenced sources, imports source annotations as incident truth, or consumes
`expected-outcome.json` as Atlas input. Generic validation can establish declared
and hash-bound normalization plus reproducible Atlas evaluation; it cannot prove
that an arbitrary upstream conversion, physical measurement, or source artifact
was correct.
