<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Citing Metriplane

Choose the citation that matches what you actually used. The current product,
the frozen research artifact, and the manuscript are separate objects with
separate version boundaries.

## Exact v0.3.0 software release

Metriplane v0.3.0 has no DOI. Cite the exact `v0.3.0` GitHub software release;
if a citation style requires a release date, use the date shown on the release
record:

> Parkkinen, Miko. *Metriplane v0.3.0* [Computer software].
> GitHub. https://github.com/Miko997/metriplane/releases/tag/v0.3.0

No v0.3.0 DOI exists. Do not use the v0.2.0 DOI for v0.3.0. If a separate
v0.3.0 archive is created later, use its DOI only after its metadata and version
boundary have been verified.

## Frozen v0.2.0 research artifact

The root `CITATION.cff` and `.zenodo.json` intentionally describe the frozen
SoftwareX research artifact, not the current package. For work that used that
exact archived artifact, cite:

> Parkkinen, Miko. (2026). *MetriPlane v0.2.0: Open-Source Physical
> Observability for Workcell Evidence, Replay, and Regression Testing*
> [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.20736619

Use the exact `v0.2.0` tag for reproduction. Do not attribute v0.3.0 behavior,
outputs, compatibility, or measurements to this DOI.

## Manuscript

Cite the manuscript separately through its SSRN record:
[10.2139/ssrn.7166858](https://doi.org/10.2139/ssrn.7166858). The paper citation
does not replace the exact software-version citation.

The TIM measurements retain their evaluated software boundary at v0.1.3.
Later package capability must not be described as part of that evaluation.

## Interpretation boundary

Deterministic replay means the software gives the same substantive result for
the same validated input and configuration. It does not prove physical
measurement accuracy, safety, quality, or production fitness. Cite package
capability separately from any narrower research validation.
