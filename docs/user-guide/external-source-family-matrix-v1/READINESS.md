<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Publication readiness

## Decision

**NOT READY — REVIEW CANDIDATE**

The package starts from public Metriplane commit
`5606b956e9309802570cfa46857714722fd70187`. Its technical rows reference
frozen public evidence; they do not regenerate or modify that evidence.

## Required review gates

- [x] The candidate machine-readable matrix and JSON Schema pass the official
  Draft 2020-12 validator locally; exact-head CI must repeat the check.
- [x] Every candidate repository path, hash, Metriplane commit, and tagged proof
  identity resolves and matches locally; exact-head CI must repeat the check.
- [x] ManiSkill and robomimic fixture inventories remain unchanged locally.
- [x] CALVIN remains documentation-only with no adapter or fixture.
- [x] The candidate publication archive builds twice with byte-identical output.
- [x] Strict documentation, package scans, focused tests, scoped REUSE, and the
  full repository test suite pass locally.
- [ ] Both frozen fixture families pass installed-wheel evaluation on Ubuntu
  and macOS with Python 3.12 and 3.13.
- [ ] Normal repository PR workflows and the focused publication workflow pass
  on the exact PR head.
- [x] Every candidate row passes claim and unsupported-path red-team review.
- [ ] The owner reviews and explicitly approves merge.

The live PR and Linear issue are the authoritative place for exact-head workflow
results. This hashed file does not manufacture a self-referential commit ID.

## Publication identity proposal

After review and merge, the owner may separately approve an immutable tag or
archive such as `external-source-family-matrix-v1`. That action is not part of
MET-19 implementation, is not preapproved by this record, and must verify the
exact merged inventory and stable URL before any `READY` claim.

No tag, archive, release, DOI, version bump, or GitHub Release exists or is
created by this candidate. Citation metadata remains `1-candidate` until a
separate publication-identity decision is made.

## Claim gate

Readiness cannot broaden the claim beyond two exact source-specific portable
paths and one CALVIN rejection. Independent validation remains unproven until
an attributable outside evaluator completes the packet.
