<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Submission Artifact

## Decision: Option A

Use the archived Metriplane v0.2.0 GitHub/Zenodo release as the SoftwareX
software artifact. Current `main` is documentation maintenance only.

| Field | Value |
|---|---|
| Software name | Metriplane |
| Submitted artifact | GitHub/Zenodo v0.2.0 release |
| GitHub release URL | `https://github.com/Miko997/metriplane/releases/tag/v0.2.0` |
| Tag | `v0.2.0` |
| Tag commit | `8e35ed5bb20837f7dc46354777407b848d7ce17a` |
| DOI | `10.5281/zenodo.20736619` |
| Zenodo record | `https://zenodo.org/records/20736619` |
| License | MIT, in `LICENSE` |
| Main demo | `https://www.youtube.com/watch?v=7U5nbBbGGbw` |
| Public reproduction issue | `https://github.com/Miko997/metriplane/issues/6` |
| Evidence package | `evidence/paper_v2_0/` |
| Evidence capture commit | `44bed6d85786675c5581154f588a7ad2529c85d6` |

## Do Not Present As The Artifact

Current `main` is not the archived v0.2.0 artifact. Cite the tag, GitHub
release, and DOI when identifying the submitted SoftwareX artifact.

Do not treat unverified form responses or non-public reproduction reports as
independent evidence unless they are exported, consented, and archived in a
reviewable form.

## Reviewer Pointers

- Provenance note: [softwarex_release_provenance.md](softwarex_release_provenance.md)
- Claim/evidence matrix: [softwarex_claim_evidence_matrix.md](softwarex_claim_evidence_matrix.md)
- Repository audit: [softwarex_repository_audit.md](softwarex_repository_audit.md)
- Final readiness: [softwarex_final_readiness.md](softwarex_final_readiness.md)

For reviewer reruns, write new outputs to `/tmp` or another scratch directory.
Compare results against the frozen archived evidence instead of rewriting
`evidence/paper_v2_0/`.
