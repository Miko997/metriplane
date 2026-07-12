<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Final Readiness

## Current SoftwareX Artifact

The selected SoftwareX artifact is Option A: the archived Metriplane v0.2.0
GitHub/Zenodo release.

| Field | Value |
|---|---|
| Artifact | GitHub/Zenodo release `v0.2.0` |
| Tag commit | `8e35ed5bb20837f7dc46354777407b848d7ce17a` |
| DOI | `10.5281/zenodo.20736619` |
| GitHub release | `https://github.com/Miko997/metriplane/releases/tag/v0.2.0` |
| Evidence package | `evidence/paper_v2_0/` |
| Evidence capture commit | `44bed6d85786675c5581154f588a7ad2529c85d6` |
| Current `main` | Documentation maintenance only |

## Why Option A Was Selected

Option A is the lowest-risk publication path because the release already has a
stable GitHub tag, Zenodo DOI, license metadata, citation metadata, checked-in
evidence package, and verified reviewer reproduction path. It avoids creating a
new release, rewriting checksums, or regenerating scientific evidence.

The manuscript should evaluate the archived v0.2.0 artifact. Current `main`
contains later documentation maintenance and must not be described as the
archived software artifact.

## Current Repository Status

- Feature state: frozen for SoftwareX manuscript preparation.
- Runtime behavior: unchanged in this publication-preparation pass.
- Algorithms: unchanged.
- Evidence and benchmarks: not regenerated.
- Release state: no new tag, release, or Zenodo update.
- Documentation state: SoftwareX artifact, provenance, claim/evidence, audit,
  and final readiness documents are present.
- Naming convention: use `Metriplane` in human-facing prose and `metriplane` for
  package, CLI, import, path, and URL identifiers.

## Remaining Known Limitations

- The paper evidence package was captured before the final v0.2.0 tag and then
  included in the release tree. This must be disclosed.
- Replay statistics differ by evidence layer: 24 frames / 72 object pairs is
  the current v0.2.0 camera-free demo value; 302 frames / 906 object pairs is
  historical benchmark lineage; 2 frames / 6 object pairs is a stale/minimal
  copied artifact and should not be used as the main manuscript value.
- Public Issue #6 contains useful external technical feedback, but not a clean
  external full-suite pass. Report it with that boundary.
- Named or form-based feedback not present in the repository or public issue is
  not independently auditable without author confirmation and permission.
- The website remains broadly consistent with the repository, but automated text
  extraction still shows a split nav/logo string, the reproduce path writes to
  evidence-package paths, and minor wording/path issues remain as noted in the
  repository audit. The website was not changed in this pass.
- Scope remains intentionally bounded: observe-only, replay-first,
  planar/tagged-asset scoped, no robot or machine control, no safety
  certification, no marker-free tracking, no full 3D reconstruction, and no
  production-factory deployment validation.

## What Still Must Be Done Before Submission

- Write the SoftwareX manuscript using the safe wording in
  [softwarex_claim_evidence_matrix.md](softwarex_claim_evidence_matrix.md).
- Cite the v0.2.0 tag, GitHub release, and Zenodo DOI as the artifact.
- Explain the evidence capture commit and final tag commit difference in the
  reproducibility or availability section.
- Omit or anonymize non-public feedback unless permission and reviewable
  evidence are available.
- Perform final author review of manuscript claims against
  [softwarex_claim_evidence_matrix.md](softwarex_claim_evidence_matrix.md) and
  [softwarex_release_provenance.md](softwarex_release_provenance.md).

## Related SoftwareX Documents

- Artifact decision: [softwarex_submission_artifact.md](softwarex_submission_artifact.md)
- Release provenance: [softwarex_release_provenance.md](softwarex_release_provenance.md)
- Claim/evidence matrix: [softwarex_claim_evidence_matrix.md](softwarex_claim_evidence_matrix.md)
- Repository audit: [softwarex_repository_audit.md](softwarex_repository_audit.md)

## Expected Next Phase

SoftwareX manuscript writing
