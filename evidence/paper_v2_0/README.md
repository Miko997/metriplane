<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane v0.2.0 Paper Evidence Package

This directory contains the local reproducibility package for the v0.2.0
SoftwareX paper artifact and release candidate. It was captured before tagging
or Zenodo archival.

## Captured Run

- Branch: `feature/release-v0.2.0`
- Commit: `44bed6d85786675c5581154f588a7ad2529c85d6`
- Test gate: 580/580 passing
- Deterministic replay: pass with zero positional difference and zero event mismatches
- Atlas assembly-cell run: 6 events and 1 incident
- Bundle verification: pass
- Generated regression test: pass
- Dashboard build: pass
- Package build: wheel and sdist built
- Twine check: pass
- Docker dummy-mode local smoke: build/start, health endpoint JSON, and cleanup logs captured after package creation; bounded smoke evidence only, not benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence

## Important Files

- `environment.txt`
- `git_commit.txt`
- `test_output.txt`
- `logs/`
- `atlas_run/cell_truth_report.md`
- `atlas_run/cell_truth_report.html`
- `atlas_run/atlas_dashboard.html`
- `atlas_run/evidence_bundles/INC-0001.zip`
- `atlas_run/regression_tests/INC-0001.yaml`
- `atlas_run/physical_event_log.jsonl`
- `atlas_run/reality_graph.json`
- `atlas_run/process_trace.json`
- `artifacts/INC-0001_zip_listing.txt`
- `artifacts/INC-0001_zip.sha256`
- `artifacts/dist_listing.txt`
- `artifacts/dist_checksums.sha256`
- `generated_file_list.txt`
- `CHECKSUMS.sha256`

## Boundaries

This package includes Docker dummy-mode local smoke evidence only. It does not
add Docker benchmark, production-runtime, live-camera, replay-mode, reliability,
or safety evidence, nor Isaac Sim runtime, safety certification, robot or
machine control, quality-release approval, or marker-free tracking evidence.
