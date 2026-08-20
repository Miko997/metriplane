<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# External source-family matrix v1

This publication candidate consolidates Metriplane's frozen external-source
evidence at public baseline
`5606b956e9309802570cfa46857714722fd70187`. It does not alter the External
Source Contract, FrameStateModel, Atlas, or any earlier proof. Its seventh row
references additive MET-55 adapter and fixture evidence while leaving the
frozen two-path aggregate unchanged.

> Metriplane's frozen external-source process has produced two successful,
> source-specific portable evaluation paths: ManiSkill and robomimic. It also
> produced one documented CALVIN rejection because public rights and
> authoritative timing did not satisfy the contract.

That is the strongest aggregate claim supported by this package. A `GO` is
bounded to the exact source artifact, fields, clock, normalization, operator
rules, and portable fixture named in its row. A `NO-GO` demonstrates fail-closed
gate enforcement; it is not compatibility.

## Decisions

| Source family | Public label | Decision | Counts as a proven path? |
| --- | --- | --- | --- |
| ManiSkill | GO / proven external source | `GO` | Yes, one pinned PickCube path |
| CALVIN | NO-GO / not supported | `NO-GO` | No |
| robomimic | GO / proven external source | `GO` | Yes, one pinned Can low-dimensional path |
| MimicGen | Partially audited / not implemented | `PARTIALLY SUPPORTED` | No |
| RoboCasa / RoboCasa365 | Not inspected / not tested | `NOT TESTED` | No |
| ROS 2 / MCAP + TF2 | Planned / not tested | `NOT TESTED` | No |
| MassRobotics AMR offline replay | Synthetic offline replay profile | `PARTIALLY SUPPORTED` | No |

The decisions use only the controlled values `GO`, `PARTIALLY SUPPORTED`,
`NO-GO`, `NOT TESTED`, and `NOT APPLICABLE`. The descriptive label does not
silently introduce another decision class.

## Read this package

- [Human-readable matrix](MATRIX.md)
- [Machine-readable matrix](matrix.json) and its
  [documented JSON Schema](matrix.schema.json)
- [Package-local self-validator and deterministic rebuilder](validate.py)
- [Source, version, license, and hash crosswalk](SOURCE-CROSSWALK.md)
- [Raw/prepared/derived/normalized provenance crosswalk](PROVENANCE-CROSSWALK.md)
- [Clock, frame, unit, identity, and completeness crosswalk](STATE-MODEL-CROSSWALK.md)
- [Supported and prohibited semantics register](SEMANTICS.md)
- [Negative-result and unsupported-path register](UNSUPPORTED-PATHS.md)
- [Reopening criteria](REOPENING.md)
- [Evaluator packet](EVALUATOR.md) and
  [report template](evaluator-report-template.md)
- [Partner-facing factual summary](PARTNER-SUMMARY.md)
- [Citation metadata](CITATION.cff)
- [Validation record](VALIDATION.md), [readiness record](READINESS.md), and
  [complete package inventory](SHA256SUMS)

`matrix.json` is the authoritative structured record. The Markdown files are
human views of the same evidence. The package-local `validate.py` verifies the
schema, canonical rows, claims, evidence references, inventory, and archive
determinism after download. The repository-level validator additionally rejects
changed frozen Git evidence and fixture inventories.

## Evidence boundary

The two `GO` rows rely on owner-generated source audits, deterministic
conversion records, portable installed-wheel evaluation, evidence verification,
and regression results. Neither row records an attributable outside rerun or
independent adoption. CALVIN is documentation-only. MimicGen is only partially
audited. RoboCasa and ROS 2 / MCAP + TF2 were not tested. The MassRobotics row
records a reproducible mapping of Metriplane-authored synthetic
MassRobotics-format records and is excluded from the proven-path count.

The External Source Contract v1 schema remains
`b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4`.
Metriplane remains version `0.3.0`.

## Nonclaims

This candidate does not establish three successful integrations, universal
source neutrality, general ManiSkill or robomimic support, general HDF5
support, CALVIN compatibility, ROS 2 or MCAP support, physical accuracy,
simulator realism, safety, production readiness, source-project endorsement,
or independent adoption or validation.

No release, version bump, DOI, tag, or GitHub Release is created by this
candidate. A future immutable tag or archive is only a proposal in
[READINESS.md](READINESS.md) and requires separate owner approval after review.
