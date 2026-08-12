<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Publication readiness

## Decision

**NOT READY**

This is the publication-candidate decision as of `2026-08-12`. Miko Parkkinen
has explicitly approved the bounded proof candidate and publication-identity
model and has authorized controlled finalization after the required correction
and exact-head verification. That approval is conditional: the proof has not
been merged, the proposed tag has not been created, its workflow has not run,
and the stable tagged URL has not been verified. This file records the owner's
approval; it does not sign or approve anything on Miko's behalf.

## Candidate identity

| Item | Candidate value |
| --- | --- |
| MET-15 correction merge | `1549d0a05e03db51efc0ee08edb7d9db66196b4e` |
| MET-16 starting baseline | `1549d0a05e03db51efc0ee08edb7d9db66196b4e` |
| Public adapter commit | `95d1134d9fb9273318c552c507952f1c5c26877e` |
| Proposed proof tag | `maniskill-pickcube-proof-v1` |
| Proof-record candidate commit | `f9c78e60f73793e465061a8ea270afbb1f9e1631` |
| Dedicated evidence head | `488ef555732012b302db6795ba5796b8fa8e7f10` |
| Reviewed pre-approval PR head | `a4371d009ed9c0ad71237417e4627dc0905eacdd` |
| Corrected final PR head | Resolved externally by PR #51 after this hashed document is committed and verified |
| Final merge / tagged commit | Does not yet exist; it will be resolved externally by the immutable annotated tag rather than embedded here |
| Stable URL | Pending tag creation and URL verification |
| Owner approval | Explicitly provided by Miko Parkkinen on `2026-08-12` for controlled finalization and a later READY decision only if every remaining gate succeeds |

The owner approval is recorded, but it is not a declaration that the current
candidate is READY.

The proof-record candidate commit identifies the locally built Metriplane wheel
and durable run provenance. The dedicated evidence head identifies the tree for
the first recorded four-cell matrix. The reviewed pre-approval head identifies
the complete candidate that Miko approved. The corrected final PR head and the
eventual squash-merge commit are necessarily resolved through GitHub rather
than embedded in a file that they contain. The immutable annotated tag will
resolve the canonical publication commit externally. No self-referential
commit identity is fabricated.

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

All required workflows also passed on reviewed pre-approval head
`a4371d009ed9c0ad71237417e4627dc0905eacdd`: [Documentation](https://github.com/Miko997/metriplane/actions/runs/31577823731),
[CI](https://github.com/Miko997/metriplane/actions/runs/31577823712),
[CodeQL](https://github.com/Miko997/metriplane/actions/runs/31577823667),
[Release Gates](https://github.com/Miko997/metriplane/actions/runs/31577823797),
and [ManiSkill PickCube Proof](https://github.com/Miko997/metriplane/actions/runs/31577823683).
The required full-history reachability check and the ordinary shallow-checkout
CI behavior are both resolved and passed on that head. Because this readiness
correction changes hashed publication material, every required workflow must
pass again on the resulting corrected PR head before merge.

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
  structure job on reviewed pre-approval head
  `a4371d009ed9c0ad71237417e4627dc0905eacdd`.
- [x] 7. `SHA256SUMS` covered and recomputed the complete proof inventory in
  the dedicated structure and deterministic-build jobs on that reviewed head.
- [x] 8. Level A passed from clean installed wheels in all four recorded
  Ubuntu/macOS and Python 3.12/3.13 cells on that reviewed head, without
  simulator dependencies.
- [x] 9. Level-B acquisition and conversion instructions are complete, and the
  underlying frozen source conversion was previously verified.
- [x] 10. Reviewed-head incident and control artifacts were regenerated and
  matched the frozen `75/4/1/1` and `75/3/0/0` results.
- [x] 11. The representative incident evidence bundle verified in the
  deterministic builder, red-team job, and portable jobs.
- [x] 12. The representative generated regression passed after the proof
  output was moved and rechecked.
- [x] 13. Ubuntu Python 3.12, Ubuntu Python 3.13, macOS Python 3.12, and macOS
  Python 3.13 installed-wheel proof jobs all passed on the reviewed head in
  dedicated run `31577823683`; the first exact patch versions, runner images,
  job IDs, and result hashes remain recorded above and in
  `artifacts/environment-matrix.json` from run `31576927627`.
- [x] 14. Reviewed-head proof artifacts passed machine-local path, username,
  moved-output, and durable-artifact leak scans.
- [x] 15. Reviewed-head proof artifacts passed raw-source and upstream-asset
  exclusion scans.
- [x] 16. Reviewed-head proof artifacts passed the prohibited-wording,
  source-neutral wording, trust-layer, rights-boundary, and control-honesty
  red-team checks.
- [x] 17. `CITATION.cff` passed CFF 1.2 validation in the dedicated proof
  structure job.
- [ ] 18. Candidate source and commit identities and the reviewed PR-head URLs
  resolve publicly. The final merge identity, exact-tag URLs, and stable tagged
  URL remain pending until controlled publication completes.
- [ ] 19. The immutable annotated tag exists at the exact verified merge commit,
  and its tag-triggered workflow is green.
- [x] 20. Miko explicitly approved the bounded candidate and
  publication-identity model on `2026-08-12`, and authorized the READY decision
  only after every remaining merge, workflow, tag, and stable-URL gate succeeds.

## Current blockers

The remaining blockers are objective publication gates:

1. This documentation correction and its regenerated hashes must be frozen on
   one corrected PR head, and every required workflow must pass on that exact
   head without changing frozen technical semantics.
2. PR #51 must be marked ready for review and squash-merged at that verified
   head. The final merge commit does not yet exist.
3. Every required post-merge workflow must pass on the exact merge commit.
4. The immutable annotated tag `maniskill-pickcube-proof-v1` must be created at
   that verified merge commit, and its tag-triggered workflow must pass.
5. The stable tagged proof URL must resolve to that exact commit and complete
   proof inventory.

Do not merge until blocker 1 closes. After the owner-authorized merge, readiness
remains NOT READY until blockers 3 through 5 close. Until then, do not describe
the proof as published, mark the owning work item complete, unblock downstream
work, begin outreach, or classify this record as independent evidence.

## Required final review

During controlled finalization, the maintainer must attach the corrected PR
head's and final publication commit's direct evidence and repeat the adversarial
review, including
public commit reachability, exact-tag installation, package-version distinction,
portable incident/control reruns, moved evidence/regression behavior, control
honesty, shared session identity, operator-rule origin, upstream
success-filtered-corpus limitation, lost Z/orientation, source-version
distinctions, raw-source absence, Apache/MIT boundary, source-drift detection,
path-leak scan, source-neutral output, claims classification, exact-tag URLs,
four-job matrix, and immutable hashes.

Miko's explicit conditional owner approval is recorded above. An automated
check, maintainer recommendation, PR approval, merge, or tag creation cannot
weaken its conditions or substitute for any remaining objective gate.
