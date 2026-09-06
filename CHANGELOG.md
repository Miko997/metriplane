<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Changelog

All notable changes to Metriplane are documented here.

---

## [Unreleased]

No additional changes are recorded.

## [0.4.0.post2] — 2026-09-06 — Reduced Truth Recovery publication recovery

### Publication recovery

- Reproduces release qualification and build tooling from the repository's
  canonical lock, including the pinned browser/runtime path, instead of
  independently resolving governed tools.
- Uses `0.4.0.post2` / `v0.4.0.post2` as the replacement publication identity and
  accepts that exact PEP 440 post-release version in current external-fixture
  manifests without weakening package/version equality.
- Preserves `v0.4.0` at commit
  `6a87936b5471c320efa6bcd7f5d1fe5569ca57b9` as history of the failed attempt.
  Its release qualification failed before registry publication because the tag
  workflow did not reproduce the locked environment; no 0.4.0 package or GitHub
  Release was published, and no artifact from that run is reused.
- Preserves `v0.4.0.post1` at commit
  `69f3d88c0779ff19962c455637a12701ff043876` as the retired unpublished
  production candidate. Its locked qualification and TestPyPI staging passed,
  but production stopped before lease creation or upload when GitHub exposed a
  narrow future-step status mismatch. The broker repair advanced protected main,
  so no post1 bytes are reused or published to production.

### Scope and deferred assurance

- This post-release publishes the existing reduced Truth Recovery core scope.
  It adds no product capability or assurance claim.
- MP2-007 and MP2-014 through MP2-017 remain deferred to v0.4.1 Assurance
  Hardening; they are not completed, waived, or implied by this release.

## [0.4.0.post1] — 2026-09-05 — Retired unpublished production candidate

- Locked qualification and exact retained-artifact TestPyPI staging passed.
- Production workflow `33963231781` stopped before publication-lease creation,
  fenced blocker execution, final artifact rehash, PyPI upload, or production
  verification because GitHub represented future publication steps as
  `pending` at the exact lease-wait boundary.
- The fail-closed broker repair was merged through protected main before any
  production upload. That required main advancement retired post1 under the
  release contract. The annotated tag, retained artifacts and hashes, TestPyPI
  files, and cancelled-run evidence remain immutable; no post1 package or
  GitHub Release was published to production.

## [0.4.0] — 2026-09-02 — Failed publication attempt

This immutable tag contains the reduced Truth Recovery candidate described
below, but its publication qualification failed before registry publication.
It is not a published package or GitHub Release.

### Added

- Added strict, portable external-fixture validation and recorded-state
  evaluation through `metriplane external validate` and `metriplane external
  run`. The repository includes bounded fixtures and adapters for specific
  ManiSkill, robomimic, ROS 2/MCAP, and MassRobotics inputs; these are not a
  claim of generic compatibility with those ecosystems.
- Added an audited baseline and deterministic governed inventories for the
  command line, UI declarations, public Python surface, maintained resources,
  configurations, examples, proofs, workflows, claims, and artifact-manifest
  keys. Stable identifiers, source digests, and no-write currentness checks make
  drift visible without treating a static census as runtime support evidence.
- Added fail-closed protected-main health and release-serialization contracts
  for repository administration. These maintainer controls do not change
  Metriplane's observe-only product boundary.

### Changed

- Made run and generated-output storage portable across supported host path
  conventions while retaining explicit no-clobber behavior and binding writes,
  cleanup, and publication to validated filesystem identities.
- Pinned the maintained lint, formatting, type-checking, documentation, and test
  toolchain and made generated functional inventories part of the governed
  release checks.
- Preserved source-specific v0.3.0 fixture trees as historical evidence while
  requiring any v0.4.0 evaluation to use an explicit current-version
  materialization with a recomputed checksum inventory.

### Fixed

- Closed public-surface discovery gaps for nested manifests, structured return
  effects, unresolved shapes, and exact binding stability.
- Hardened local-run lifecycle, reservation, overwrite, cleanup, and generated
  file-mode handling against ambiguous, stale, replaced, or unsafe paths.
- Made protected-main admission reconcile exact provider attempts, immutable
  commits, state generations, repository rules, and owner-request evidence
  before the broker may merge.

### Security and integrity

- Split production PyPI promotion from the tag-triggered TestPyPI workflow.
  Production now requires a separate owner-only manual dispatch naming the
  successful tag run, exact version, and explicit confirmation phrase; the
  protected environment remains an additional safeguard.
- Production publication is serialized by an App-owned release lease. Exact
  artifacts are built once, verified on TestPyPI, promoted without rebuilding,
  and checked by hash again after production publication.
- Frozen v0.2.0 research evidence and source-specific historical proof records
  remain unchanged.

### Scope and deferred assurance

- The v0.4.0 candidate carries the reduced Truth Recovery core scope. MP2-007 and MP2-014 through
  MP2-017 remain deferred to v0.4.1 Assurance Hardening; they are not completed,
  waived, or implied by this release.
- Static inventory and deterministic replay results do not establish production
  safety, physical accuracy, generic robotics compatibility, or completion of
  the v1.0 assurance programme. Metriplane remains recorded, local, bounded,
  planar, and observe-only.
- Historical v2.5.x authority packets are not release evidence for v0.4.0 and
  are neither consumed nor recreated.

### Research scope

- The v0.4.0 candidate does not replace or modify the frozen v0.2.0 SoftwareX artifact, its
  DOI, checksums, or measurements, and it does not change the TIM evaluated
  software boundary at v0.1.3. No v0.4.0 DOI is claimed.

## [0.3.0] — 2026-08-09 — Usability and adoption

### Added

- Added a package-contained, camera-free `metriplane demo --open` path that turns
  the recorded missing-torque-driver scenario into an incident timeline, an
  Incident Report, a verified evidence bundle, and a repeatable regression check.
- Added package-resource checks and installed-wheel/source-distribution smoke
  tests so the bundled session, process rules, and report templates work outside
  a source checkout and offline after installation.
- Added `metriplane --version` and a clearer `metriplane doctor` result that
  distinguishes required demo readiness from optional camera, GPU, and
  source-checkout capabilities.
- Added a documentation front door, an after-demo tutorial for supported recorded
  workcell data, troubleshooting, support boundaries, and exact-version citation
  guidance.
- Added contribution, support, security, conduct, issue-form, and pull-request
  guidance for privacy-conscious community participation.
- Added built-wheel demo coverage across Ubuntu and macOS with Python 3.12 and
  3.13, plus a reusable build-once release workflow that validates the wheel and
  source distribution independently.

### Changed

- Made the root help screen lead with the complete demo and installation doctor,
  while keeping advanced Atlas, runtime, and verification commands available.
- Rewrote the README first screen, demo output, active report headings, and current
  UI copy around the missing-tool incident in plain language. Active product copy
  now uses “Metriplane” while compatibility-sensitive identifiers remain stable.
- Made the intended published quickstart
  `python -m pip install "metriplane==0.3.0"` followed by
  `metriplane demo --open`.
- Made output replacement explicit: demo, run, bundle, and example-export paths
  no longer silently replace an existing destination.
- Made fixed replay clocks authoritative across Atlas, Sentinel, contracts, and
  trace output, and clarified the privacy export as deterministic pseudonymization.
- Defined support accurately: Linux/Ubuntu receives the full suite; macOS receives
  the bundled camera-free demo gates; WSL2 Ubuntu 24.04 has a bounded owner-run
  Python 3.12.3 installed-wheel and headless demo check that completed in seven
  seconds, without a claim for automatic browser opening. A later
  owner-reported native-Windows Command Prompt demo completion is recorded only
  as a bounded observation, not a broader support claim.

### Fixed

- Hardened Atlas and Sentinel evidence verification against incomplete checksum
  inventories, unsafe archives, contradictory records, malformed state, and
  regression false passes.
- Made Atlas run, bundle, and pseudonymized-output publication transactional and
  prevented source/output overlap or implicit destructive replacement.
- Made replay, live-camera, fusion, launcher, and local-runner failures propagate
  cleanly, including stale camera frames, truncated primary recordings, startup
  rollback, cancellation races, and unsafe local runner requests.
- Strengthened domain-pack, frame, rule, expected-result, and persisted-config
  validation, including non-finite values and credential redaction.

### Security and integrity

- Made evidence verification fail closed for corrupted, incomplete, unsafe,
  contradictory, missing, or stale inputs so they cannot produce a false bundle
  or regression pass.
- Added a verified private GitHub security-advisory reporting route and guidance
  that keeps sensitive vulnerability details out of public issues.
- Preserved the frozen v0.2.0 evidence, checksums, DOI metadata, and tag without
  presentation-only rewrites.

### Research scope

- This release adds usability, packaging, documentation, and hardening. It does
  not add new measurements or change a paper evaluation boundary.
- The SoftwareX research artifact remains frozen at v0.2.0 with DOI
  `10.5281/zenodo.20736619`; the TIM evaluated software boundary remains v0.1.3.
  No v0.3.0 DOI is claimed.

---

## [0.2.1] — 2026-08-03 — PyPI packaging and release automation

### Added

- Added explicit PEP 517 build-system metadata and complete PyPI project links.
- Added a trusted-publishing workflow that stages the exact distributions on TestPyPI, verifies the installed package, and then promotes the same artifacts to PyPI after environment approval.
- Added an exact release runbook for the first PyPI publication and later releases.

### Changed

- Exported the package version as `metriplane.__version__` and made it the single source for distribution metadata.
- Switched the OpenCV dependency to `opencv-contrib-python-headless`, which includes the ArUco APIs used by Metriplane.
- Strengthened the wheel gate with strict metadata validation, dependency checking, version checking, ArUco import checking, and a command executed outside the source checkout.
- Clarified which features work from the PyPI wheel and which reproducibility assets require a source checkout.

### Evidence scope

- This is a packaging and delivery release. It does not alter the frozen v0.2.0 paper evidence, reported measurements, or associated DOI.

---

## [0.2.0] — 2026-06-17 — Physical Observability, Evidence Bundles, and Command Center

### Added

- Added Sentinel observe-only auditing over replayed physical-space state.
- Added spatial contracts, rule validation, incident grouping, short-horizon risk forecasting, and evidence bundles.
- Added physical regression tests, counterfactual incident reports, camera trust analysis, and a local grounded operator assistant.
- Added the Command Center UI/API for read-only inspection of objects, incidents, traces, trust, and operator questions.
- Added object registry, trace store, operational events, query CLI, MetriPlane-Bench scenarios, Jetson deployment notes, fleet heartbeat artifacts, and scalable event exporters.
- Added the Atlas Cell Black Box / Evidence Review foundation: domain packs, deterministic assembly-cell demo replay, reality graph, physical event ledger, Cell Truth Report, dashboard, USDA replay export, evidence bundle v3, generated regression tests, training cases, improvement actions, saved queries, SQLite evidence lake, connector exports, edge helpers, multi-cell comparison, privacy reports, protocol export, pilot kit, freeze audit, and Atlas-Bench core.
- Added Atlas documentation for quickstart, domain packs, Open Atlas Protocol v1, privacy/claim boundaries, and the 0.2.0 phase matrix.
- Added phase evidence files for Atlas phases 24-50 with explicit local status and limitations.
- Added ROS 2, Isaac, and Omniverse adapter/example surfaces for downstream integration.
- Archived the v0.2.0 software release on Zenodo: `10.5281/zenodo.20736619`.

### Changed

- Promoted MetriPlane from a camera-to-coordinate demo into a physical-observability and evidence platform.
- Expanded automated coverage to 580 passing tests for the 0.2.0 release.
- Preserved the historical v0.1.3 benchmark evidence baseline while adding 0.2.0 operational evidence.
- Documented v0.1.4 as the historical DOI-archived baseline: `10.5281/zenodo.20631037`.

### Safety and scope

- Sentinel is observe-only. It does not control robots, machines, or safety systems.
- Atlas is observe-only and asset/process focused. It does not control machines, certify safety, approve quality release, recognize people, or claim marker-free tracking.
- 0.2.0 remains planar XY and marker/fiducial based.
- Hardware-specific integrations are documented honestly as adapters or deployment paths unless separate measured evidence is included.
- External pilots, hardware appliance packaging, full USD/Isaac replay, and network connectors remain explicitly scoped for future work unless separate evidence is added.

---

## [0.1.4] — 2026-06-10 — Repository stabilization and Zenodo DOI release

### Changed

- Cleaned the repository root so the canonical Python package lives under `metriplane/`.
- Removed duplicate root package directories and root Python module shadows.
- Consolidated command-line helper scripts into the canonical root `tools/` directory.
- Moved experiment configuration YAMLs into `configs/examples/`, leaving `config.example.yaml` at the root.
- Added a tracked demo replay fixture at `datasets/demo/session_001.jsonl` for clean-clone deterministic replay.
- Added CI and script guards for ROS pytest plugin autoload collisions.
- Archived the v0.1.4 software release on Zenodo: `10.5281/zenodo.20631037`.

### Evidence

- No benchmark values changed from v0.1.3.
- Evidence data, checksums, and benchmark values were preserved.

---

## [0.1.0] — 2026-05-06 — Initial public release

### Summary

First public release of MetriPlane. The system was developed privately through milestones M1-M9 and is now released as an open-source project under the MIT license.

### Features included

**Core pipeline**
- USB and RTSP camera ingest via v4l2 / OpenCV
- ArUco marker detection with stable object IDs
- Planar homography mapping: pixel coordinates → world meters
- Multi-camera sensor fusion (nearest-neighbor, weighted average, Kalman filter)
- Object tracking registry with configurable timeout and zone enter/exit/dwell events
- JSONL session recording for deterministic replay

**Systems reliability**
- Deterministic replay: fixed-step clock, bit-exact frame reproducibility
- Backpressure handling: bounded queues with configurable drop policies
- Health monitoring: component-level registry for cameras, compute, WebSocket
- Config provenance: automatic stamping with git commit hash, config SHA256, run ID
- Per-stage observability: latency breakdown (detect, map, fuse, stream)

**Compute backends**
- CPU backend: NumPy-based (default)
- GPU backend: CuPy-based (optional, requires CUDA 12.x or 13.x)
- Note: CPU backend is faster than GPU in tested workloads (N=1–1000 objects)

**Operator dashboard**
- Browser-based 10-step setup wizard (environment → cameras → profile → anchors → calibrate → validate → zones → config → run → export)
- Runner service REST API on `:9000`
- Live state dashboard with WebSocket stream visualization

**Docker**
- `compose.yaml` for single-command deployment
- Replay demo mode (no camera required)
- Live camera pass-through mode

**Testing**
- 193 automated tests (unit + integration)
- 7 benchmark scripts covering determinism, backpressure, latency, GPU equivalence, and fusion jitter
- CI via GitHub Actions on ubuntu-latest

### Known limitations (initial release)

- Onboarding evidence was collected on the development machine with a warm pip cache; clean-machine installation time is not measured.
- `fusion_jitter_001.csv`: absolute fused position accuracy (`max_error_m`) was not compared against ground truth; relative jitter stability is measured.
- CPU backend is faster than GPU at small vector sizes (N ≤ 1000). GPU backend exists for larger workloads and future use.
- NVIDIA Omniverse and ROS 2 integrations are external/experimental community examples. No live latency measurements are claimed for these.
- Large session JSONL files are not included in git (size). SHA256 checksums are retained in `evidence/manifest.csv`.

### Removed from private history

This public release was prepared from the private development history with the following categories removed:
- School/research writing planning documents
- Private internal audit documents
- Personal machine-specific paths and usernames
- Unexecuted template evidence files

---

_For detailed evidence and benchmarks, see [`docs/eval/evidence_index.md`](docs/eval/evidence_index.md)._
