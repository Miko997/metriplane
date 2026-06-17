<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# v0.2.0 Release Readiness Summary

## Repository State

- Branch: `feature/release-v0.2.0`
- Commit: `44bed6d85786675c5581154f588a7ad2529c85d6`
- Status: release candidate; no GitHub tag or Zenodo archive was created in this pass.
- Historical DOI baseline: `v0.1.4` at `10.5281/zenodo.20631037`.

## Test Result

- Command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`
- Captured output: `evidence/paper_v2_0/test_output.txt`
- Result: `580 passed in 68.35s (0:01:08)`
- Supporting captured logs: `evidence/paper_v2_0/logs/03_pytest_q.txt` and `evidence/paper_v2_0/test_output.txt`.

## Evidence Commands Run

```bash
RUNS=evidence/paper_v2_0/runs ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl
.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell
.venv/bin/metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out evidence/paper_v2_0/atlas_run --overwrite
.venv/bin/metriplane atlas bundle verify evidence/paper_v2_0/atlas_run/evidence_bundles/INC-0001.zip
.venv/bin/metriplane atlas test evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml --json
.venv/bin/metriplane atlas dashboard build --run-dir evidence/paper_v2_0/atlas_run
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## Generated Artifacts

- Paper evidence package: `evidence/paper_v2_0/`
- Environment snapshot: `evidence/paper_v2_0/environment.txt`
- Git snapshot: `evidence/paper_v2_0/git_commit.txt`
- Test gate output: `evidence/paper_v2_0/test_output.txt`
- Deterministic replay output: `evidence/paper_v2_0/logs/deterministic_replay.txt`
- Replay determinism CSV/checksum: `evidence/paper_v2_0/runs/demo-evidence/`
- Atlas assembly-cell run: `evidence/paper_v2_0/atlas_run/`
- Cell Truth Report: `evidence/paper_v2_0/atlas_run/cell_truth_report.md` and `.html`
- Atlas dashboard: `evidence/paper_v2_0/atlas_run/atlas_dashboard.html`
- Evidence bundle: `evidence/paper_v2_0/atlas_run/evidence_bundles/INC-0001.zip`
- Bundle listing/checksum: `evidence/paper_v2_0/artifacts/INC-0001_zip_listing.txt`, `INC-0001_zip.sha256`
- Regression spec/output: `evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml`, `evidence/paper_v2_0/logs/regression_test.json`
- Event log, graph, and trace: `physical_event_log.jsonl`, `reality_graph.json`, `process_trace.json`
- Distribution build logs: `evidence/paper_v2_0/logs/python_build.txt`, `logs/twine_check.txt`
- Distribution checksums: `evidence/paper_v2_0/artifacts/dist_checksums.sha256`
- Docker local replay/demo smoke logs: `evidence/paper_v2_0/logs/16_docker_demo_up.txt`, `logs/17_docker_health.json`, `logs/18_docker_clean.txt`
- Paper docs: `docs/paper/`
- Reviewer kit: `docs/review_kit/`

## Remaining Red Blockers Before Tag / Zenodo / SoftwareX

- No local evidence red blocker remains from the captured doctor, test, replay, Atlas, bundle, dashboard-build, regression, build, or twine-check gates.
- Required procedural stop: create the GitHub tag only after reviewing and committing this diff.
- Required procedural stop: create the Zenodo archive only from the tagged release, then update final DOI references.
- Required SoftwareX stop: ensure manuscript claims stay within `docs/paper/claim_evidence_table.md`.
- Integration boundary: Docker local replay/demo smoke was captured in the v0.2.0 paper package: build/start, health endpoint JSON, and cleanup. This is bounded smoke evidence only and is not promoted as benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence. Isaac Sim remains NOT RUN.
- Omniverse boundary: keep Omniverse bounded to USDA/export evidence unless a raw Omniverse open log or screenshot is added.
- Packaging status: `python -m build` produced the v0.2.0 sdist/wheel and `twine check dist/*` passes without warnings after adding release metadata.
