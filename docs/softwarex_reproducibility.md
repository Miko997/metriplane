<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Reproducibility

## Archived artifact

- Software: Metriplane v0.2.0
- GitHub release: https://github.com/Miko997/metriplane/releases/tag/v0.2.0
- Git tag: `v0.2.0`
- Tag commit: `8e35ed5bb20837f7dc46354777407b848d7ce17a`
- Zenodo DOI: `10.5281/zenodo.20736619`
- License: MIT
- Included author-run evidence package: `evidence/paper_v2_0/`

## Evidence provenance

The checked-in evidence package records capture commit
`44bed6d85786675c5581154f588a7ad2529c85d6`. It was captured before the final
`v0.2.0` tag and included unchanged in the archived release. The tag identifies
the cited software artifact; the capture commit identifies the code state that
generated the included author-run results.

## Core artifact reproduction

This path is camera-free and uses only the declared runtime package. It does not
require Playwright or Chromium. Use temporary output paths so the archived
evidence package and ordinary repository run directories remain unchanged.

```bash
git clone --branch v0.2.0 --depth 1 https://github.com/Miko997/metriplane.git
cd metriplane

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

python -m metriplane.cli doctor

RUNS=/tmp/metriplane-softwarex-runs \
  ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl

metriplane atlas validate-pack configs/domain_packs/assembly_cell
metriplane atlas run \
  --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl \
  --pack configs/domain_packs/assembly_cell \
  --out /tmp/metriplane-softwarex-atlas \
  --overwrite

metriplane atlas bundle verify \
  /tmp/metriplane-softwarex-atlas/evidence_bundles/INC-0001.zip

metriplane atlas test \
  /tmp/metriplane-softwarex-atlas/regression_tests/INC-0001.yaml \
  --json
```

## Expected core results

- doctor completes with passes and at most non-blocking warnings
- deterministic replay: `pass=true`
- 24 frames and 72 object pairs
- 0.0 cm mean and maximum position difference
- 0 event mismatches
- Atlas run: 6 physical events, 1 process deviation, 1 incident
- bundle verification: `pass=true`
- generated regression check: `pass=true`

## Full maintainer test gate

The maintainer gate is separate from core artifact reproduction. The archived
Linux CI sequence installs the package, test tooling, Chromium and its system
dependencies, and then runs the full pytest suite with automatic third-party
plugin loading disabled.

```bash
python -m pip install -e .
python -m pip install pytest playwright
python -m playwright install chromium --with-deps
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

The `v0.2.0` tag does not define a development dependency extra; the commands
above reproduce the explicit dependency sequence used by the archived Linux CI
workflow. The core artifact path does not require these browser dependencies.

## Scope

The reproducible path is replay-based, observe-only, and limited to the
checked-in assembly-cell example. It establishes software behavior for the
preserved replay condition. It does not establish robot control, remediation,
safety certification, arbitrary anomaly detection, marker-free tracking, full
3D reconstruction, or production-factory deployment readiness.
