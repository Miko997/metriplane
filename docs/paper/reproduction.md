<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Reproducing The v0.2.0 Paper Evidence

This guide reproduces the local evidence package for the v0.2.0 SoftwareX
paper artifact. The current package was captured on branch
`feature/release-v0.2.0` at commit
`44bed6d85786675c5581154f588a7ad2529c85d6`.

## Evidence Package

Primary package: `evidence/paper_v2_0/`

Key captured files:

- `environment.txt`
- `git_commit.txt`
- `test_output.txt`
- `logs/deterministic_replay.txt`
- `logs/atlas_validate_pack.txt`
- `logs/atlas_assembly_cell_run.txt`
- `logs/bundle_verify.txt`
- `logs/regression_test.json`
- `logs/python_build.txt`
- `logs/twine_check.txt`
- `atlas_run/cell_truth_report.md`
- `atlas_run/cell_truth_report.html`
- `atlas_run/atlas_dashboard.html`
- `atlas_run/evidence_bundles/INC-0001.zip`
- `atlas_run/regression_tests/INC-0001.yaml`
- `atlas_run/physical_event_log.jsonl`
- `atlas_run/reality_graph.json`
- `atlas_run/process_trace.json`

## Commands

Run from the repository root with Python 3.12 and the project virtual
environment active or available at `.venv/`.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
RUNS=evidence/paper_v2_0/runs ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl
.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell
.venv/bin/metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out evidence/paper_v2_0/atlas_run --overwrite
.venv/bin/metriplane atlas bundle verify evidence/paper_v2_0/atlas_run/evidence_bundles/INC-0001.zip
.venv/bin/metriplane atlas test evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml --json
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## Expected Results

- Test gate: `580 passed`.
- Deterministic replay: `pass=true`, zero mean/max position difference, zero event mismatches.
- Atlas assembly-cell run: 6 physical events and 1 incident.
- Bundle verification: JSON result with `"pass": true`.
- Regression test: JSON result with `"pass": true`.
- Package build: `metriplane-0.2.0.tar.gz` and `metriplane-0.2.0-py3-none-any.whl`.
- Twine check: both distributions pass, with warnings about missing long description metadata.

## Scope

These commands reproduce local, camera-free evidence. They do not run Docker,
Isaac Sim, robot or machine controllers, safety certification workflows,
marker-free tracking, or production integration runtime tests.
