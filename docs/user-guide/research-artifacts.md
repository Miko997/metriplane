<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Research artifacts and exact-version reproduction

Product development and historical research results have separate version
boundaries. Reproduce and cite the exact version that produced the result.

| Purpose | Exact boundary | Status |
| --- | --- | --- |
| Reduced Truth Recovery core software release | v0.4.0 | Exact software tag `v0.4.0`; no DOI and no new research measurement boundary. |
| Usability and adoption software release | v0.3.0 | Prior exact software tag `v0.3.0`; no DOI and no new research measurement boundary. |
| Published packaging predecessor | v0.2.1 | Historical packaging release that predates the bundled `demo` command; it is not a v0.3.0, v0.4.0, or research-evidence boundary. |
| SoftwareX research artifact | v0.2.0 | Frozen tag and DOI archive: [10.5281/zenodo.20736619](https://doi.org/10.5281/zenodo.20736619). |
| TIM evaluated software boundary | v0.1.3 | Historical measurement boundary; later package behavior must not be attributed to that evaluation. |
| Manuscript preprint | Paper, cited separately | SSRN DOI: [10.2139/ssrn.7166858](https://doi.org/10.2139/ssrn.7166858). |

The v0.2.0 DOI belongs to the frozen v0.2.0 research artifact. Do **not** attach
that DOI to v0.3.0 or imply that a v0.3.0 output produced the SoftwareX or TIM
measurements. No v0.3.0 DOI exists. A later, separately approved archive may add
one only after its metadata and version boundary are verified. Do not attach the
v0.2.0 DOI to v0.4.0 or imply that a v0.4.0 output produced those measurements.
No v0.4.0 DOI exists.

For the frozen SoftwareX path, use the exact v0.2.0 tag and follow
[SoftwareX reproducibility](https://github.com/Miko997/metriplane/blob/main/docs/softwarex_reproducibility.md)
or the
[paper reproduction guide](https://github.com/Miko997/metriplane/blob/main/docs/paper/reproduction.md).
Those documents preserve historical commands and evidence boundaries; they are
not v0.4.0 product quickstarts or v0.4.0 environment claims.

For the active compatibility statement, use
[Supported Environments](https://github.com/Miko997/metriplane/blob/main/docs/SUPPORTED_ENVIRONMENTS.md).
Archived WSL2 wording in v0.2.0 material does not establish the active v0.4.0
support scope. The retained v0.3.0 WSL2 validation and one owner-reported
native-Windows demo completion do not establish v0.4.0 validation, a research
boundary, or a broader platform-validation boundary.

Deterministic replay means identical validated inputs and configuration produce
the same software result. It does not prove physical measurement accuracy,
safety, quality, or production deployment validity. Package capability must also
not be confused with the narrower scope that a paper evaluated.
