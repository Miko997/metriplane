<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Cross-adapter validation audit v1

Audit point: `34099903b3c3fdeb4f794edceddbf845a3f4aba8`.

This audit records the repository state that the cross-adapter compatibility
gate must preserve. It covers the isolated adapter packages, the portable
External Source Contract v1 fixtures, their executable Atlas oracles, and the
current CI routes. It does not turn a bounded adapter profile into a general
compatibility or conformance claim.

## Package inventory

There are five independently packaged components under `adapters/`: one shared
SDK and four source adapters. All declare Python `>=3.12,<3.14`; none is included
in the ordinary `metriplane` wheel. The unified registry deliberately limits the
four adapter source suites to Ubuntu/Python 3.12. The SDK and portable fixtures
have broader exhaustive coverage; a package declaration alone is not treated as
source-conversion evidence on another environment.

| Component | Distribution / module | CLI | Relationship to the SDK |
| --- | --- | --- | --- |
| `adapters/source_adapter_sdk` | `metriplane-source-adapter-sdk` / `metriplane_source_adapter_sdk` | None | Shared capability schema/validation, canonical JSON, SHA-256, and repository-evidence validation |
| `adapters/maniskill_pickcube` | `maniskill-pickcube-adapter` / `maniskill_pickcube` | `maniskill-pickcube` | Isolated converter; its capability record is validated against the SDK after conversion |
| `adapters/robomimic_lowdim` | `robomimic-lowdim-adapter` / `robomimic_lowdim` | `robomimic-lowdim` | Isolated converter; its capability record is validated against the SDK after conversion |
| `adapters/ros2_mcap` | `metriplane-ros2-mcap-adapter` / `ros2_mcap_adapter` | `metriplane-ros2-mcap` | Isolated converter; generated capability evidence is SDK-validated |
| `adapters/massrobotics_amr` | `metriplane-massrobotics-amr-adapter` / `massrobotics_amr_adapter` | `metriplane-massrobotics-amr` | Direct runtime use of the SDK inside the isolated package |

The packages do not have an identical command surface. The registry must store
the supported sync, test, lint, format, type, build, import, CLI, inspection,
conversion, and finalization commands explicitly, including a justified
`null` when a command is not applicable. A gate must not manufacture a common
adapter API that the packages do not provide.

The gate itself is not a sixth adapter or a runtime package. Its environment is
locked under `tests/adapter_conformance/` and installs the root project only for
contract and Atlas testing. Gate-only JSON Schema and REUSE dependencies do not
change the ordinary root lock or any frozen adapter lock.

## Portable fixture inventory

Five fixture families contain nine portable variants. Portable evaluation needs
only the root Metriplane environment and the checked-in fixture: it does not need
the source framework, source archive, or isolated adapter package.

| Family | Classification | Portable path | Variants and exact `frames/events/deviations/incidents` |
| --- | --- | --- | --- |
| Minimal contract fixture | Contract baseline, not an external-source proof | `examples/external_sources/minimal` | baseline `4/5/1/1` |
| ManiSkill PickCube | Proven external source | `examples/external_sources/maniskill_pickcube` | incident `75/4/1/1`; control `75/3/0/0` |
| robomimic Can PH low-dimensional | Proven external source | `examples/external_sources/robomimic_lowdim` | incident `118/4/1/1`; control `118/3/0/0` |
| ROS 2 and MCAP recorded state | Synthetic format engineering | `examples/external_sources/ros2_mcap` | incident `60/4/1/1`; control `60/3/0/0` |
| MassRobotics AMR offline replay | Synthetic format engineering | `examples/external_sources/massrobotics_amr` | incident `9/4/1/1`; control `9/3/0/0` |

Every normalized frame has exactly two objects and an empty source-generated
`events` array. That common shape does not make the expected Atlas results
interchangeable. The exact registered event oracles are:

| Variant | Exact ordered `frame @ time: event` sequence |
| --- | --- |
| Minimal baseline | `0 @ 0.0: step_completed`; `1 @ 1.0: required_asset_missing`; `2 @ 3.5: step_delayed`; `3 @ 4.0: required_asset_present`; `3 @ 4.0: step_completed` |
| ManiSkill incident | `66 @ 3.30: required_asset_missing`; `70 @ 3.50: step_delayed`; `71 @ 3.55: required_asset_present`; `71 @ 3.55: step_completed` |
| ManiSkill control | `66 @ 3.30: required_asset_missing`; `71 @ 3.55: required_asset_present`; `71 @ 3.55: step_completed` |
| robomimic incident | `0 @ 0.0: required_asset_missing`; `40 @ 2.0: step_delayed`; `42 @ 2.1: required_asset_present`; `42 @ 2.1: step_completed` |
| robomimic control | `0 @ 0.0: required_asset_missing`; `42 @ 2.1: required_asset_present`; `42 @ 2.1: step_completed` |
| ROS 2/MCAP incident | `5 @ 0.5: required_asset_missing`; `10 @ 1.0: step_delayed`; `15 @ 1.5: required_asset_present`; `15 @ 1.5: step_completed` |
| ROS 2/MCAP control | `5 @ 0.5: required_asset_missing`; `15 @ 1.5: required_asset_present`; `15 @ 1.5: step_completed` |
| MassRobotics incident | `2 @ 2.0: required_asset_missing`; `5 @ 5.0: step_delayed`; `6 @ 6.0: required_asset_present`; `6 @ 6.0: step_completed` |
| MassRobotics control | `2 @ 2.0: required_asset_missing`; `4 @ 4.0: required_asset_present`; `4 @ 4.0: step_completed` |

The minimal baseline and all four incident variants produce one
`missing_tool_caused_delay` incident, a verifiable evidence bundle, and a
passing generated regression. Every control produces no incident, no evidence
bundle, and no generated regression. Absence is the control oracle; a gate must
not create placeholder control artifacts.

## Existing evidence boundaries

All nine variants have a strict source manifest, entity mapping, normalization
report, expected outcome, five-file domain pack, normalized session, and
`CHECKSUMS.sha256`. The checksum inventories validate. Expected outcomes are
test oracles and are not conversion inputs. Portable runs use External Source
Contract v1 validation before unchanged Atlas evaluation.

Evidence is intentionally heterogeneous:

- ManiSkill has the dedicated proof at `proofs/maniskill-pickcube-v1/` and
  references pinned upstream source bytes without committing them.
- MassRobotics has the dedicated proof at
  `proofs/massrobotics-amr-offline-replay-v1/`; the standard is reference-only,
  while the included JSONL source is Metriplane-authored synthetic material.
- robomimic carries its exact source, rights, conversion, and verification
  evidence across the fixture and `docs/specs/robomimic-can-lowdim-*.md`; the
  referenced upstream HDF5 files are not committed.
- ROS 2/MCAP carries its synthetic composite-rights and transform evidence in
  `examples/external_sources/ros2_mcap/` and
  `docs/user-guide/ros2-mcap-recorded-state-profile/`.
- The minimal fixture is a repository-authored MIT contract baseline and has no
  separate proof directory.

The compatibility gate validates fixture rights declarations and closed checksum
inventories, required-notice presence, package licence metadata, registered wheel
content patterns, dependency isolation, and known reference-only artifact
digests. It also runs `reuse lint-file` over the new workflow, gate code,
schemas, tests, and these two documents. That is a scoped REUSE check, not a
claim that the gate repairs or certifies the repository-wide REUSE baseline. It
does not require all families to use the same license, proof layout,
source-materialization policy, or capability-record location.

## Current executable coverage

Root external-source tests cover contract validation, trust-layer behavior,
relocation, checksums, Atlas outcomes, bundle verification, generated
regressions, controls, deterministic replay, and fixture-specific negative
cases. The audit run of `uv run pytest -q tests/external_sources` completed with
`192 passed`.

Dedicated workflows add isolated package checks and deeper family-specific
conversion checks:

- `ManiSkill PickCube Proof` is path-filtered and has Ubuntu/macOS portable
  coverage for Python 3.12 and 3.13.
- `robomimic Low-Dimensional Fixture` runs on every pull request and has the
  same portable OS/Python matrix.
- `Bounded ROS 2 and MCAP Recorded-State Profile` is path-filtered and has the
  same portable matrix, with exact source conversion only on pull request or
  manual dispatch.
- `Bounded MassRobotics AMR Offline Replay` is path-filtered and currently runs
  only Ubuntu with Python 3.12.
- `External Source-Family Matrix` is path-filtered; its portable job exercises
  only ManiSkill and robomimic.

The root `CI` workflow runs the root test suite on Ubuntu and macOS with Python
3.12 and 3.13, but it does not execute the isolated package test suites.
Specialized workflows are useful defense in depth; their different triggers and
path filters do not provide one stable, always-present compatibility status.

### Pull-request skip risks before the unified gate

| Existing workflow | Pull-request selection | Changes that could skip its adapter or evidence |
| --- | --- | --- |
| ManiSkill PickCube Proof | Path-filtered | Changes to unlisted shared tooling, the Source Adapter SDK, root packaging, or source-family matrix records could avoid this workflow even when cross-adapter assumptions changed. |
| robomimic Low-Dimensional Fixture | Unfiltered | No path-based pull-request skip; job failure, cancellation, or missing status remained separate risks. |
| Bounded ROS 2 and MCAP Recorded-State Profile | Path-filtered | Its adapter, SDK, fixture, schema, and root package paths are covered, but unlisted cross-family proof, matrix, or validation-tooling changes could avoid it. |
| Bounded MassRobotics AMR Offline Replay | Path-filtered | Unlisted root modules, generic build/release tooling, or changes confined to another adapter could avoid it despite a shared compatibility risk. |
| External Source-Family Matrix | Path-filtered | ROS 2/MCAP and MassRobotics adapter and fixture paths were outside its portable job, which executed only ManiSkill and robomimic. |

The new workflow removes this selection gap by having no pull-request path
filter. Its Level A matrix is Ubuntu/Python 3.12 and emits 16 records. The
scheduled or manually dispatched Level B matrix emits 53 records: four SDK
environments, four Ubuntu/Python 3.12 adapter source suites, four
Ubuntu/Python 3.13 adapter package-only checks, 36 portable-fixture
environments, four root-wheel environments, and one shared-contract record.

### Coverage and known gaps by layer

| Layer or family | Source and adapter coverage | Portable and adversarial coverage | Current gap |
| --- | --- | --- | --- |
| Source Adapter SDK | Package tests, lint, format, sdist/wheel inspection, and clean install; exhaustive Ubuntu/macOS and Python 3.12/3.13 | Shared contract, registry, mutation-catalog, matrix determinism, scoped REUSE, and result-aggregation tests | No package-local static type-check command; its post-hoc catalog covers ManiSkill and robomimic only. |
| Minimal contract fixture | No source adapter; contract baseline only | Exact five-event oracle, incident bundle/regression, relocation, tamper, rights, privacy, and installed-root-wheel replay | No control variant and no source-conversion claim. |
| ManiSkill | Full adapter package suite on Ubuntu/Python 3.12; package-only build/install evidence on Python 3.13; Ruff migration on an ephemeral copy with exact rewrite-set and syntax-tree checks | Incident/control exact oracles; shared and profile negative/metamorphic tests; wheel/sdist isolation and portable four-environment exhaustive replay | Reference-only ZIP/HDF5 is absent, so the unified gate cannot rerun the frozen source conversion. Published proof bytes remain unchanged rather than being reformatted in place. |
| robomimic | Full adapter package suite on Ubuntu/Python 3.12; package-only build/install evidence on Python 3.13 | Incident/control exact oracles; shared and profile negative/metamorphic tests; wheel/sdist isolation and portable four-environment exhaustive replay | Reference-only raw/prepared HDF5 is absent, so the unified gate cannot rerun the frozen source conversion. |
| ROS 2/MCAP | On Ubuntu/Python 3.12, regenerate the synthetic MCAP, run three clean conversions, finalize them, and diff the checked-in fixtures; package-only evidence on Python 3.13 | Incident/control exact oracles; stream/TF and shared mutations; distribution isolation and portable four-environment exhaustive replay | Source-family matrix publication still says `NOT TESTED`; source conversion is not registered for Python 3.13 or macOS. |
| MassRobotics AMR | On Ubuntu/Python 3.12, run three clean conversions per synthetic source variant, finalize them, and diff the checked-in fixtures; package-only evidence on Python 3.13 | Incident/control exact oracles; clock/datum/snapshot and shared mutations; upstream-byte exclusions and portable four-environment exhaustive replay | Source conversion remains Linux/Python 3.12 only; portable replay does not establish general protocol or transport support. |

### Local performance observation

The implementation audit used Linux, Python 3.12, and a warm locked `uv` cache.
These measurements are diagnostic observations, not CI thresholds. Every
workflow run records its own exact per-job duration in the machine result
artifacts; GitHub Actions remains authoritative for parallel wall-clock time on
each commit.

| Measurement | Local audit value |
| --- | --- |
| Source Adapter SDK | 3.39--8.08 s across repeated runs |
| ManiSkill adapter | 17.31 s |
| robomimic adapter | 13.04 s |
| ROS 2/MCAP adapter and source conversion | 26.03 s |
| MassRobotics adapter and source conversion | 33.86 s |
| Shared contract and mutation suite | 8.97 s |
| Portable fixture jobs | 0.31--0.61 s each |
| Installed root-wheel job | 26.65 s |
| Sum of the 16 recorded Level A job durations | 133.61 s |
| Result artifacts | 2,050--6,997 bytes; 42,834 bytes total |

## Findings requiring reconciliation

1. The published source-family matrix still describes ROS 2/MCAP as
   `NOT TESTED`, with no converter or fixture. The repository now contains an
   executable bounded synthetic ROS profile, adapter, and incident/control
   fixtures. This is a stale matrix fact, not a reason to relabel synthetic
   evidence as an external-source proof.
2. The matrix's portable workflow tests only ManiSkill and robomimic. It cannot
   be treated as coverage of all five current fixture families.
3. The MassRobotics matrix row mentions exact-head cross-platform CI, while the
   dedicated workflow is Ubuntu/Python 3.12 only and its capability evidence
   records portability as not demonstrated. That claim needs evidence-bound
   reconciliation.
4. There is no single strict registry connecting packages, fixtures, expected
   results, proofs, rights, workflows, and source-family matrix decisions.
5. There is no stable summary check that rejects a missing, skipped, or canceled
   required component on every pull request and merge-group candidate.
6. Proof layouts and adapter command surfaces differ. Treating that difference
   as failure would erase legitimate bounded-profile decisions; leaving it
   unregistered would make coverage accidental.

The gate records these as explicit known gaps while enforcing executable facts.
It must not silently rewrite the human-readable source-family matrix.

## CALVIN remains NO-GO

CALVIN is not a sixth adapter or fixture. The authoritative record is
`docs/specs/calvin-semantic-state-adapter-audit.md`, status **NO-GO**. Unresolved
dataset and derived-state redistribution rights and the absence of an
authoritative per-sample evaluation clock are each sufficient blockers. No
CALVIN adapter, normalized fixture, or source bytes were created.

The registry must pin that audit evidence and discover any prohibited CALVIN
adapter or fixture path. Such a path is a registry failure, not an invitation to
run or generate a CALVIN golden fixture.

## Registry facts required by the gate

The source-controlled registry at `tests/adapter_conformance/registry.json` is
validated by `tests/adapter_conformance/registry.schema.json`. It must carry:

- the audited commit and all five package identities, locations, supported
  environments, exact commands, known gaps, and dedicated-workflow facts;
- the four adapter IDs, evidence classification, source origin and rights,
  source-conversion boundary, proof paths, required notices, package content
  rules, mutation groups, limitations, claim boundary, and matrix row;
- the five fixture family IDs and nine variant IDs, paths, fixture IDs,
  fingerprints, session hashes, exact event/count/artifact oracles,
  deterministic-run requirement, and relocation/test-only rules;
- discovery roots for adapters, fixtures, proofs, and the source-family matrix;
  and
- CALVIN's NO-GO evidence hash, blockers, and forbidden adapter/fixture globs.

Discovery is fail-closed: a new package or portable fixture directory must be
registered; a registered path must exist; variant IDs, fixture IDs, hashes, and
oracles must be unique and exact; executable matrix decisions must map to
registered evidence; explicit non-executable decisions remain non-executable.
The registry is the reviewable coverage declaration, not an automatic inventory
of whatever happens to be present.
