<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Publication readiness

## Decision

**NOT READY**

This is the publication-candidate decision as of `2026-08-12`. The proof has
not been merged, Miko has not approved final publication, the proposed tag has
not been created, and the stable tagged URL has not been verified. This file
does not sign or approve anything on Miko's behalf.

## Candidate identity

| Item | Candidate value |
| --- | --- |
| MET-15 correction merge | `1549d0a05e03db51efc0ee08edb7d9db66196b4e` |
| MET-16 starting baseline | `1549d0a05e03db51efc0ee08edb7d9db66196b4e` |
| Public adapter commit | `95d1134d9fb9273318c552c507952f1c5c26877e` |
| Proposed proof tag | `maniskill-pickcube-proof-v1` |
| Proof-record candidate commit | `f9c78e60f73793e465061a8ea270afbb1f9e1631` |
| Dedicated evidence head | `488ef555732012b302db6795ba5796b8fa8e7f10` |
| Current PR publication head | Pending after the shallow-clone reachability fix and deterministic proof rebuild; it must not be conflated with either identity above |
| Final merge / tagged commit | Does not yet exist |
| Stable URL | Pending tag creation and URL verification |
| Owner approval | Not provided |

Final owner approval remains pending.

The proof-record candidate commit identifies the locally built Metriplane wheel
and durable run provenance. The later evidence head identifies the exact tree
on which the dedicated four-cell workflow ran. The eventual current PR head
will be a third identity because it includes the shallow-clone test correction
and rebuilt proof metadata. None of these is represented here as a final merge
or tagged publication commit.

## Recorded candidate evidence

Dedicated workflow
[`31576927627`](https://github.com/Miko997/metriplane/actions/runs/31576927627)
passed every proof-structure, artifact-red-team, deterministic-build, and
portable installed-wheel job at evidence head
`488ef555732012b302db6795ba5796b8fa8e7f10`. The portability jobs recorded:

| Environment | Runner image | GitHub job | Reproduction-result SHA-256 |
| --- | --- | ---: | --- |
| Ubuntu 24.04.4 x86_64, Python 3.12.13 | `ubuntu-24.04@20260810.271.1` | [`94051127016`](https://github.com/Miko997/metriplane/actions/runs/31576927627/job/94051127016) | `836ad5b4f74657c2f4e97a05b8d909bd23a9b2168961c47aa824448709db273b` |
| Ubuntu 24.04.4 x86_64, Python 3.13.15 | `ubuntu-24.04@20260810.271.1` | [`94051127003`](https://github.com/Miko997/metriplane/actions/runs/31576927627/job/94051127003) | `b2eb0e1d4f9a53d0c279056ea1ef4d9e9cfd301f254fa464638923f3626cb4ac` |
| macOS 26.5.2 arm64, Python 3.12.10 | `macos-26-arm64@20260728.0273.1` | [`94051126999`](https://github.com/Miko997/metriplane/actions/runs/31576927627/job/94051126999) | `001d8e664926e1a90b3185283a795e2f30fc5a154abefbbe4986ac77b0bacef7` |
| macOS 26.5.2 arm64, Python 3.13.14 | `macos-26-arm64@20260728.0273.1` | [`94051127104`](https://github.com/Miko997/metriplane/actions/runs/31576927627/job/94051127104) | `95d20fae57192ce00c7aec34c41ef7018d4c7ea065cb6a7cf708a903e04d3268` |

Documentation, CodeQL, and Release Gates also passed on that evidence head.
Generic CI failed only because a public-object reachability assertion ran in a
shallow clone. The test has been corrected locally to skip only object
reachability in a shallow repository; the dedicated proof workflow retains
`fetch-depth: 0` and remains the enforcement surface. That correction and its
rebuilt proof still require green checks on the eventual current PR head.

## Mandatory publication checklist

Checked items below are facts already closed before or within this candidate.
Unchecked items remain publication blockers until direct evidence is recorded.
The final publication review must recompute the entire checklist against the
exact merge commit rather than carrying candidate checks forward by assumption.

- [x] 1. MET-15 is merged and Done. The correction merge is
  `1549d0a05e03db51efc0ee08edb7d9db66196b4e`.
- [x] 2. The source, dataset, conversion, adapter, fixture, and baseline commits
  referenced by the frozen fixtures were verified as public at the MET-16
  start gate.
- [x] 3. Source identities, source-byte hashes, raw-source exclusions, and the
  mixed rights boundary are documented.
- [x] 4. Canonical fixture paths, inventories, shared session hash, and incident
  and control fixture fingerprints are complete.
- [x] 5. The candidate proof landing page is complete in the required public
  reading order.
- [x] 6. `proof-record.json` and its closed schema validated in the dedicated
  structure job at evidence head `488ef555732012b302db6795ba5796b8fa8e7f10`.
- [x] 7. `SHA256SUMS` covered and recomputed the complete proof inventory in
  the dedicated structure and deterministic-build jobs at the evidence head.
- [x] 8. Level A passed from clean installed wheels in all four recorded
  Ubuntu/macOS and Python 3.12/3.13 cells, without simulator dependencies.
- [x] 9. Level-B acquisition and conversion instructions are complete, and the
  underlying frozen source conversion was previously verified.
- [x] 10. Evidence-head incident and control artifacts were regenerated and
  matched the frozen `75/4/1/1` and `75/3/0/0` results.
- [x] 11. The representative incident evidence bundle verified in the
  deterministic builder, red-team job, and portable jobs.
- [x] 12. The representative generated regression passed after the proof
  output was moved and rechecked.
- [x] 13. Ubuntu Python 3.12, Ubuntu Python 3.13, macOS Python 3.12, and macOS
  Python 3.13 installed-wheel proof jobs all passed in dedicated run
  `31576927627`; exact patch versions, runner images, job IDs, and result hashes
  are recorded above and in `artifacts/environment-matrix.json`.
- [x] 14. Evidence-head proof artifacts passed machine-local path, username,
  moved-output, and durable-artifact leak scans.
- [x] 15. Evidence-head proof artifacts passed raw-source and upstream-asset
  exclusion scans.
- [x] 16. Evidence-head proof artifacts passed the prohibited-wording,
  source-neutral wording, trust-layer, rights-boundary, and control-honesty
  red-team checks.
- [x] 17. `CITATION.cff` passed CFF 1.2 validation in the dedicated proof
  structure job.
- [ ] 18. Public source and commit identities used by the candidate have been
  checked, but the eventual PR-head URLs, final merge identity, immutable tag,
  and stable tagged URL cannot all be verified before those identities exist.
- [ ] 19. The immutable annotated tag exists at the exact verified merge commit,
  and its tag-triggered workflow is green.
- [ ] 20. Miko has explicitly approved final publication after seeing the
  complete technical and publication checklist.

## Current blockers

The remaining blockers are publication and owner-decision gates:

1. The shallow-clone test correction, rebuilt environment matrix, proof record,
   and checksums must be frozen on one new current PR head. Required workflows
   must pass on that exact head; the evidence above belongs to
   `488ef555732012b302db6795ba5796b8fa8e7f10`, not the future head.
2. The focused proof PR still requires final review and merge. The final merge
   commit does not yet exist, and post-merge workflows have not run.
3. Miko has not provided the required explicit owner approval after reviewing
   the final current-head evidence and complete checklist.
4. The proposed annotated tag has not been created, its tag workflow has not
   run, and the stable tagged URL has not been verified.
5. Publication identity has an inherent self-reference: a Git commit cannot
   contain its own SHA-1. Before publication, the owner must approve a truthful
   model that distinguishes the embedded recorded candidate commit, the later
   evidence/current PR commits, the final merge commit, and the commit resolved
   externally by the annotated tag. No self-commit hash may be fabricated or
   represented as embedded proof content.

While any blocker remains, do not merge for publication, create or move the
tag, describe the proof as published, mark the owning work item complete,
unblock downstream outreach, or classify this record as independent evidence.

## Required final review

Before requesting owner approval, the maintainer must attach the eventual
current PR head's direct evidence and answer the adversarial review, including
public commit reachability, exact-tag installation, package-version distinction,
portable incident/control reruns, moved evidence/regression behavior, control
honesty, shared session identity, operator-rule origin, upstream
success-filtered-corpus limitation, lost Z/orientation, source-version
distinctions, raw-source absence, Apache/MIT boundary, source-drift detection,
path-leak scan, source-neutral output, claims classification, exact-tag URLs,
four-job matrix, and immutable hashes.

Only Miko may provide the final owner approval. An automated check, maintainer
recommendation, PR approval, merge, or tag creation is not a substitute for
that explicit decision.
