<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Submission Checklist

## Completed Locally

- [x] Captured branch and commit metadata.
- [x] Captured Python environment and installed package list.
- [x] Captured full local test gate: 580/580 passing.
- [x] Captured deterministic replay output.
- [x] Captured Atlas assembly-cell run output.
- [x] Captured `INC-0001.zip` listing and checksum.
- [x] Captured evidence-bundle verification output.
- [x] Captured generated regression-test output.
- [x] Captured dashboard build output.
- [x] Captured Python package build output.
- [x] Captured `twine check dist/*` output.
- [x] Checked Docker smoke logs; Docker remains attempted but not validated/promoted as current benchmark or production-runtime evidence.
- [x] Added paper reproduction, claim-evidence, limitations, and release-readiness docs.
- [x] Added reviewer kit walkthrough.

## Required Before Tag And Zenodo

- [ ] Review the working-tree diff.
- [ ] Commit the release evidence/documentation package.
- [ ] Push the release branch.
- [ ] Create the GitHub release tag only after review.
- [ ] Archive the tagged release on Zenodo.
- [ ] Update any final DOI references after Zenodo mints the v0.2.0 DOI.

## SoftwareX Paper Package

- [ ] Confirm manuscript text cites only claims in `docs/paper/claim_evidence_table.md`.
- [ ] Include or reference `evidence/paper_v2_0/` as the reproducibility package.
- [ ] Keep integration language bounded to observe-only adapters unless new runtime evidence is added.
- [ ] Keep v0.1.4 described as the historical DOI baseline, not the v0.2.0 artifact.
- [ ] Keep Docker bounded to attempted local smoke evidence unless complete reviewer-approved lifecycle evidence is promoted.
