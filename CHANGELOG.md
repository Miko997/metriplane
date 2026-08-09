<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Changelog

All notable changes to Metriplane are documented here.

---

## [Unreleased]

### Added

- Added a wheel-contained, camera-free `metriplane demo --open` path that produces
  and verifies an incident report, evidence bundle, and generated regression check.
- Added built-wheel demo coverage across Ubuntu and macOS with Python 3.12 and 3.13.

### Changed

- Made the root help screen expose the primary demo, Atlas, runtime, and
  verification commands.
- Made fixed replay clocks authoritative across Atlas, Sentinel, contracts, and
  trace output, and clarified the privacy export as deterministic pseudonymization.
- Expanded full-suite CI to Linux and macOS on Python 3.12 and 3.13; native
  Windows remains outside the supported platform scope.

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
