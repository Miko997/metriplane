<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Reproducibility

## Archived artifact

- Software: Metriplane v0.2.0
- GitHub release: https://github.com/Miko997/metriplane/releases/tag/v0.2.0
- Git tag: v0.2.0
- Tag commit: `8e35ed5bb20837f7dc46354777407b848d7ce17a`
- Zenodo DOI: `10.5281/zenodo.20736619`
- License: MIT
- Evidence package: `evidence/paper_v2_0/`

## Evidence provenance

The evidence package records capture commit
`44bed6d85786675c5581154f588a7ad2529c85d6`. It was captured before the final
v0.2.0 tag and included unchanged in the archived release.

## Reproduction

Use temporary output paths so the archived evidence package remains unchanged.

```bash
RUNS=/tmp/metriplane-softwarex-runs \
  ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl

.venv/bin/metriplane atlas validate-pack \
  configs/domain_packs/assembly_cell

.venv/bin/metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out /tmp/metriplane-softwarex-atlas \
  --overwrite

.venv/bin/metriplane atlas bundle verify \
  /tmp/metriplane-softwarex-atlas/evidence_bundles/INC-0001.zip

.venv/bin/metriplane atlas test \
  /tmp/metriplane-softwarex-atlas/regression_tests/INC-0001.yaml \
  --json
```

## Expected results

- deterministic replay: `pass=true`
- 24 frames
- 72 object pairs
- 0.0 cm mean and maximum position difference
- 0 event mismatches
- Atlas run: 6 physical events, 1 process deviation, 1 incident
- bundle verification: `pass=true`
- generated regression test: `pass=true`

## Scope

The reproducible path is camera-free, replay-based, observe-only, and limited to
the checked-in bounded assembly-cell example. It does not establish robot
control, safety certification, arbitrary anomaly detection, marker-free
tracking, full 3D reconstruction, or production-factory deployment readiness.
