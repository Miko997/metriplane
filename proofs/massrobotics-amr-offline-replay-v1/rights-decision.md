<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MET-55 rights decision

Decision date: `2026-08-20`

Decision: **proceed with independently authored synthetic source; keep all
upstream materials reference-only**.

## Artifact-scoped decision

| Material | Origin / owner representation | Included? | Public treatment |
| --- | --- | ---: | --- |
| Synthetic identity/status JSONL | Metriplane-authored synthetic records | Yes | MIT under normal repository notices |
| Portable normalized fixtures | Metriplane-generated from the synthetic records | Yes | MIT under normal repository notices |
| Mapping, proof metadata, tests, and adapter | Metriplane-authored | Yes | MIT under normal repository notices |
| `AMR_Interop_Standard.json` | Referenced MassRobotics repository artifact | No | Immutable URL, commit, Git blob, and paraphrased factual role only |
| `AMR_Interop_Standard.pdf` | Referenced MassRobotics repository artifact | No | Immutable URL, commit, Git blob, and short paraphrase only |
| Official identity/status examples | Referenced MassRobotics repository artifacts | No | Immutable URL, commit, Git blob, and factual role only; not copied or derived |
| Official sender/receiver code | Referenced MassRobotics repository artifacts | No | Immutable reference only |
| ISO 21423 text | ISO copyrighted material | No | Public metadata note only |

No upstream file byte, excerpt, schema fragment, example record, sender code, or
receiver code is required to build, install, convert, validate, or execute the
profile. The converter does not fetch upstream content. The exact reference
identities are recorded in [`source-identity.json`](source-identity.json).

## Origin distinction

The actual source artifacts are the four independently authored JSONL files in
`adapters/massrobotics_amr/source/`. Their source project is the Metriplane
repository. MassRobotics identifies the referenced interoperability
specification, not the synthetic fixture.

The fixture description is:

> Metriplane-authored synthetic MassRobotics-format engineering fixture

## Redistribution boundary

Upstream rights are represented as `reference_only`, and
`upstream_artifacts_included` is `false`. If a future change proposes including
an upstream byte, this decision does not authorize it. That proposal requires a
new artifact-scoped review and must not weaken the current fail-closed contract
record.

The synthetic source and normalized fixture remain subject to the project's
MIT license and normal notices. That MIT statement applies only to
Metriplane-authored material and does not relicense any referenced upstream
artifact.

## Profile scope

This decision covers the included synthetic source, adapter, normalized
fixtures, mapping, and proof metadata. MassRobotics materials remain immutable
references. ISO 21423 is outside the MET-55 profile.
