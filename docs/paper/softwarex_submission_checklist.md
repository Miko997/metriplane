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
- [x] Captured Docker local replay/demo smoke logs; bounded smoke evidence only, not benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence.
- [x] Added paper reproduction, claim-evidence, limitations, and release-readiness docs.
- [x] Added reviewer kit walkthrough.
- [x] GitHub Release `v0.2.0` exists.
- [x] Zenodo v0.2.0 DOI minted: `10.5281/zenodo.20736619`.
- [x] Final DOI references updated.

## Completed Release Procedure

- [x] GitHub release tag and release record exist.
- [x] Zenodo archive exists for v0.2.0.
- [x] v0.1.4 remains documented as the historical DOI baseline, not the v0.2.0 artifact.

## SoftwareX Paper Package

- [ ] Confirm manuscript text cites only claims in `docs/paper/claim_evidence_table.md`.
- [ ] Include or reference `evidence/paper_v2_0/` as the reproducibility package.
- [ ] Keep integration language bounded to observe-only adapters unless new runtime evidence is added.
- [ ] Keep Docker bounded to local replay/demo smoke evidence unless new benchmark or production-runtime evidence is generated.
- [ ] Complete external reproduction review, if required.
- [ ] Submit the SoftwareX manuscript.
