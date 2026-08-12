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
| Candidate proof commit | Recorded in `proof-record.json`; not final until merge |
| Stable URL | Pending tag creation and URL verification |
| Owner approval | Not provided |

Final owner approval remains pending.

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
- [ ] 6. The final `proof-record.json` and closed schema validate against the
  exact publication-candidate head and later the merge commit.
- [ ] 7. The final `SHA256SUMS` inventory recomputes after every publication
  artifact has stopped changing.
- [ ] 8. The final Level-A reproduction passes from an installed wheel built
  from the exact publication-candidate head, with no simulator dependency.
- [x] 9. Level-B acquisition and conversion instructions are complete, and the
  underlying frozen source conversion was previously verified.
- [ ] 10. Exact-head incident and control artifacts are regenerated and match
  the frozen `75/4/1/1` and `75/3/0/0` results.
- [ ] 11. The representative incident evidence bundle from the exact candidate
  verifies.
- [ ] 12. The representative generated regression from the exact candidate
  passes after moving the proof output.
- [ ] 13. Ubuntu Python 3.12, Ubuntu Python 3.13, macOS Python 3.12, and macOS
  Python 3.13 installed-wheel proof jobs all pass on the exact final head.
- [ ] 14. Final proof artifacts pass local-path and username leak scans.
- [ ] 15. Final proof artifacts pass raw-source and upstream-asset exclusion
  scans.
- [ ] 16. Final proof artifacts pass the prohibited-wording and trust-boundary
  review.
- [ ] 17. `CITATION.cff` passes a CFF 1.2 validator in the final tree.
- [ ] 18. Every canonical public commit, source URL, candidate PR URL, and final
  tagged URL resolves from an unauthenticated public context.
- [ ] 19. The immutable annotated tag exists at the exact verified merge commit,
  and its tag-triggered workflow is green.
- [ ] 20. Miko has explicitly approved final publication after seeing the
  complete technical and publication checklist.

## Current blockers

At least these blockers remain:

1. The focused proof PR has not been reviewed or merged.
2. The exact final merge commit does not yet exist.
3. Final artifact hashes and `SHA256SUMS` cannot be frozen before the candidate
   tree stops changing.
4. The four-job installed-wheel matrix, proof-record/schema checks,
   deterministic double build, red-team scans, documentation/build checks, and
   all exact-head workflows still require final recorded results.
5. Post-merge workflows have not run.
6. Miko has not provided the required explicit owner approval.
7. The proposed annotated tag has not been created, its workflow has not run,
   and the stable URL has not been verified.

While any blocker remains, do not merge for publication, create or move the
tag, describe the proof as published, mark the owning work item complete,
unblock downstream outreach, or classify this record as independent evidence.

## Required final review

Before requesting owner approval, the maintainer must attach direct evidence
for all checklist items and answer the adversarial review, including public
commit reachability, exact-tag installation, package-version distinction,
portable incident/control reruns, moved evidence/regression behavior, control
honesty, shared session identity, operator-rule origin, upstream
success-filtered-corpus limitation, lost Z/orientation, source-version
distinctions, raw-source absence, Apache/MIT boundary, source-drift detection,
path-leak scan, source-neutral output, claims classification, exact-tag URLs,
four-job matrix, and immutable hashes.

Only Miko may provide the final owner approval. An automated check, maintainer
recommendation, PR approval, merge, or tag creation is not a substitute for
that explicit decision.
