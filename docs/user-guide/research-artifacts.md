<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Research artifacts and exact-version reproduction

Product development and historical research results have separate version
boundaries. Reproduce and cite the exact version that produced the result.

| Purpose | Exact boundary | Status |
| --- | --- | --- |
| Current PyPI package | v0.2.1 | Published package while v0.3.0 is prepared; it predates the bundled `demo` command. |
| Usability/adoption release | v0.3.0 | Planned, not yet published, tagged, or assigned a DOI. Current-main preview results must not be described as published v0.3.0 results. |
| SoftwareX research artifact | v0.2.0 | Frozen tag and DOI archive: [10.5281/zenodo.20736619](https://doi.org/10.5281/zenodo.20736619). |
| TIM evaluated software boundary | v0.1.3 | Historical measurement boundary; later package behavior must not be attributed to that evaluation. |
| Manuscript preprint | Paper, cited separately | SSRN DOI: [10.2139/ssrn.7166858](https://doi.org/10.2139/ssrn.7166858). |

The v0.2.0 DOI belongs to the frozen v0.2.0 research artifact. Do **not** attach
that DOI to v0.3.0 or imply that a v0.3.0 output produced the SoftwareX or TIM
measurements. No v0.3.0 DOI exists unless a separate archive is created later
with truthful metadata.

For the frozen SoftwareX path, use the exact v0.2.0 tag and follow
[SoftwareX reproducibility](https://github.com/Miko997/metriplane/blob/main/docs/softwarex_reproducibility.md)
or the
[paper reproduction guide](https://github.com/Miko997/metriplane/blob/main/docs/paper/reproduction.md).
Those documents preserve historical commands and evidence boundaries; they are
not current product quickstarts or current environment claims.

For the active compatibility statement, use
[Supported Environments](https://github.com/Miko997/metriplane/blob/main/docs/SUPPORTED_ENVIRONMENTS.md).
Archived WSL2 wording in v0.2.0 material does not advertise WSL2 for v0.3.0, and
native Windows remains unsupported.

Deterministic replay means identical validated inputs and configuration produce
the same software result. It does not prove physical measurement accuracy,
safety, quality, or production deployment validity. Package capability must also
not be confused with the narrower scope that a paper evaluated.
