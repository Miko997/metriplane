<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Publication readiness

## Decision

**NOT READY: REVIEW CANDIDATE**

The package starts from public Metriplane commit
`5606b956e9309802570cfa46857714722fd70187`. Its original technical rows
reference frozen public evidence and do not regenerate or modify it. The
non-counted MassRobotics row references additive candidate-head MET-55 evidence
and does not change the frozen two-path aggregate.

## Required review gates

- [x] The candidate machine-readable matrix and JSON Schema pass the official
  Draft 2020-12 validator locally; exact-head CI must repeat the check.
- [x] Every candidate repository path, hash, Metriplane commit, and tagged proof
  identity resolves and matches locally; exact-head CI must repeat the check.
- [x] ManiSkill and robomimic fixture inventories remain unchanged locally.
- [x] CALVIN remains documentation-only with no adapter or fixture.
- [x] The MassRobotics row remains `PARTIALLY SUPPORTED`, synthetic,
  reference-only, non-counted, and free of compatibility/conformance claims.
- [x] The candidate publication archive builds twice with byte-identical output.
- [x] Strict documentation, package scans, and focused matrix tests pass
  locally.
- [ ] Scoped REUSE and the full repository test suite pass on the exact final
  candidate head.
- [ ] Both frozen fixture families pass installed-wheel evaluation on Ubuntu
  and macOS with Python 3.12 and 3.13.
- [ ] Normal repository PR workflows and the focused publication workflow pass
  on the exact PR head.
- [x] Every candidate row passes claim and unsupported-path red-team review.
- [ ] The owner reviews and explicitly approves merge.

The live PR records exact-head workflow results. They are not embedded in the
files they verify.

## Publication identity proposal

After review and merge, the owner may separately approve an immutable tag or
archive such as `external-source-family-matrix-v1`. That action is separate
from this candidate, is not preapproved by this record, and must verify the
exact merged inventory and stable URL before any `READY` claim.

No tag, archive, release, DOI, version bump, or GitHub Release exists or is
created by this candidate. Citation metadata remains `1-candidate` until a
separate publication-identity decision is made.

## Claim gate

Readiness cannot broaden the claim beyond two exact source-specific portable
paths and one CALVIN rejection. Independent validation remains unproven until
an attributable outside evaluator completes the packet.
