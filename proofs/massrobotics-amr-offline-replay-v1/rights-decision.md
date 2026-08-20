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
| Official sender/receiver code | Referenced MassRobotics repository artifacts | No | Not vendored, executed, modified, packaged, or redistributed |
| ISO 21423 text | ISO copyrighted material | No | Public metadata note only; no implementation or conformance claim |

No upstream file byte, excerpt, schema fragment, example record, sender code, or
receiver code is required to build, install, convert, validate, or execute the
profile. The converter does not fetch upstream content. The exact reference
identities are recorded in [`source-identity.json`](source-identity.json).

## Origin distinction

The actual source artifacts are the four independently authored JSONL files in
`adapters/massrobotics_amr/source/`. Their source project is the Metriplane
repository. MassRobotics is recorded only as the identity of the referenced
interoperability specification; it is not named as creator, owner, provider,
recorder, reviewer, or validator of the synthetic fixture.

The fixture description is:

> Metriplane-authored synthetic MassRobotics-format engineering fixture

The description does not imply vendor data, real AMR state, an official
example, production use, permission, adoption, endorsement, or organizational
evaluation.

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

## Claim boundary

This rights treatment permits an owner-generated mapping and reproducible
technical artifact. It does not establish MassRobotics or Vecna validation,
general compatibility, certification, conformance, organizational review,
external adoption, or permission to reproduce the referenced standard.

ISO 21423 is a related future interoperability audit target. MET-55 does not
implement or claim conformance with ISO 21423.
