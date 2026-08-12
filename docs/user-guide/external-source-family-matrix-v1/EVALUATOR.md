<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Evaluator packet

This packet is reserved for a later, separately authorized MET-20 evaluation.
MET-19 does not contact evaluators or claim an independent rerun.

## Evaluation question

Can an evaluator who did not create these fixtures install an exact Metriplane
commit and independently validate and run the two frozen, source-specific
portable paths without installing either simulator or source adapter?

This question tests portable fixture evaluation. It does not test source
acquisition, source conversion, physical accuracy, task success, general source
compatibility, or production readiness.

## Inputs

An evaluator receives:

- an owner-approved immutable Metriplane publication commit or tag, supplied
  after MET-19 review;
- `examples/external_sources/maniskill_pickcube/{incident,control}`;
- `examples/external_sources/robomimic_lowdim/{incident,control}`;
- this publication package and its verified `SHA256SUMS`.

No raw HDF5/JSON/ZIP source, simulator asset, source framework, adapter, video,
image, or model binary is required for this portable level.

## Required environment

- Ubuntu or macOS;
- CPython 3.12 or 3.13;
- a fresh virtual environment;
- a wheel built from the exact owner-approved commit, not a differently scoped
  package release.

The evaluator must record OS, architecture, exact Python patch version, wheel
SHA-256, Metriplane commit, command transcript, and whether the work was
performed without project-owner assistance.

## Procedure

1. Verify the repository commit or immutable tag supplied for evaluation.
2. Verify this package's `SHA256SUMS` and both frozen fixture inventories.
3. Build a wheel from that exact commit and install it in a fresh environment.
4. Copy each fixture outside the repository checkout.
5. Run `metriplane external validate FIXTURE --json` for all four fixtures.
6. Run `metriplane external run FIXTURE --out OUTPUT --run-id ID --json` for
   all four fixtures.
7. Verify the two incident evidence bundles and generated regressions.
8. Confirm each no-incident control produces neither an evidence bundle nor a
   generated regression.
9. Move each output directory and repeat evidence/regression verification.
10. Scan outputs for source dependencies and machine-local paths.
11. Complete [evaluator-report-template.md](evaluator-report-template.md) and
    sign or otherwise attribute the report in the evaluator's own name.

## Frozen expected results

| Family | Variant | Frames / events / deviations / incidents | Durable identity |
| --- | --- | --- | --- |
| ManiSkill | incident | `75/4/1/1` | `954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2` |
| ManiSkill | control | `75/3/0/0` | `8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e` |
| robomimic | incident | `118/4/1/1` | `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6` |
| robomimic | control | `118/3/0/0` | `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf` |

The two variants in each family share one session: ManiSkill
`7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`;
robomimic
`bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246`.

## Independence classification

Passing commands alone is not enough to claim independent validation. The
report must identify the evaluator, environment, exact artifact, assistance
received, result, and any deviations. Project-owned CI and maintainer reruns
remain first-party evidence even when they execute on hosted runners.
