<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

<p align="center">
  <img src="docs/assets/metriplane.png" alt="Metriplane" width="760">
</p>

# Metriplane

Open-source workcell black box for replayable physical evidence.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release: v0.2.0](https://img.shields.io/badge/release-v0.2.0-blue)](https://github.com/Miko997/metriplane/releases/tag/v0.2.0)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20736619.svg)](https://doi.org/10.5281/zenodo.20736619)
[![Website](https://img.shields.io/badge/website-metriplane.com-2ea44f)](https://www.metriplane.com/)

## Official Links

- Official site: https://www.metriplane.com/
- 3-minute v0.2.0 demo: https://www.youtube.com/watch?v=7U5nbBbGGbw
- v0.2.0 release: https://github.com/Miko997/metriplane/releases/tag/v0.2.0
- Zenodo DOI: https://doi.org/10.5281/zenodo.20736619
- External reproduction issue: https://github.com/Miko997/metriplane/issues/6
- Short feedback form: https://docs.google.com/forms/d/e/1FAIpQLSfnMZ4b3fSVVtwA89hZt3A09gf85eLfhW00FDD76TGRLNpirQ/viewform

## Summary

Metriplane v0.2.0 is an open-source physical-observability artifact for bounded workcells. It converts replayed or calibrated workcell state into physical event logs, Cell Truth Reports, portable evidence bundles, local bundle verification, and generated regression tests. The current release is observe-only and camera-free for reproduction.

## Why this exists

Robotics teams often need more than raw logs after an incident. Metriplane explores a structured evidence layer where replayed workcell state becomes an inspectable incident bundle, a verification target, and a generated regression test.

## Evidence Workflow

```text
replayed workcell state
→ physical event
→ incident
→ Cell Truth Report
→ evidence bundle
→ bundle verification
→ generated regression test
```

## Current v0.2.0 Evidence Result

The author-run evidence package included in the archived release records:

- 580 tests passed
- deterministic replay pass=true
- 6 physical events
- 1 incident
- 35.0 second missing-tool delay
- bundle verify: pass=true
- generated regression test: PASS

## Quick Reproduction Path

The core SoftwareX reproduction is camera-free, uses the exact `v0.2.0` tag,
and writes rerun outputs to temporary directories rather than the archived
evidence package.

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

The full maintainer gate is separate from the core artifact path and adds test
and browser dependencies:

```bash
python -m pip install -e .
python -m pip install pytest playwright
python -m playwright install chromium --with-deps
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

## What Metriplane Is

- observe-only
- local-first
- replay-first, camera-compatible
- bounded workcell scoped
- research-software oriented
- focused on evidence, not robot control

## What Metriplane Does Not Claim

- no robot or machine control
- no safety certification
- no quality-release approval
- no people recognition
- no marker-free tracking claim
- no full 3D reconstruction claim
- no production-factory deployment validation
- no factory-wide deployment readiness

## Relationship to ROS Bags and Logs

Robotics teams often debug incidents using recorded sensor data, ROS bags, logs, traces, and simulation replays. Those artifacts are valuable raw evidence. Metriplane is not a replacement for ROS bags or logs. It explores the next structured layer: incident context, evidence bundle, verification result, and generated regression test.

## External Feedback

External technical feedback and public discussion links are collected on the official site:

https://www.metriplane.com/feedback/

## Citation / DOI

If you use or evaluate Metriplane v0.2.0, cite the archived release:

https://doi.org/10.5281/zenodo.20736619

## Reproducibility and Archived Release

The SoftwareX manuscript evaluates the archived Metriplane v0.2.0 release.
Reproduction commands, expected outputs, and evidence provenance are documented
in [docs/softwarex_reproducibility.md](docs/softwarex_reproducibility.md).

## Repository Orientation

The public Python package and command-line entry points remain named `metriplane`.

| Area | Path | Purpose |
|---|---|---|
| Package | `metriplane/` | Python package and CLI implementation |
| Domain packs | `configs/domain_packs/` | Workcell-specific Atlas configuration |
| Demo datasets | `datasets/demo/` | Checked-in replay inputs for reproduction |
| Evidence | `evidence/` | Release evidence, manifests, and experiment artifacts |
| Tools | `tools/` | Supported local helper scripts |
| Docs | `docs/` | Technical documentation and runbooks |
| Web UI | `web/` | Local operator and review interfaces |

## Canonical SoftwareX Commands

Use the **Quick Reproduction Path** above for the camera-free core artifact.
The same commands, expected outputs, evidence provenance, and the separate
maintainer-gate sequence are maintained in
[docs/softwarex_reproducibility.md](docs/softwarex_reproducibility.md) and the
[review kit](docs/review_kit/00_start_here.md).

## Documentation

- Atlas evidence workflow: [docs/atlas/README.md](docs/atlas/README.md)
- Physical observability scope: [docs/physical_observability.md](docs/physical_observability.md)
- Development setup: [docs/development.md](docs/development.md)
- Prerequisites: [docs/PREREQUISITES.md](docs/PREREQUISITES.md)
- SoftwareX reproducibility: [docs/softwarex_reproducibility.md](docs/softwarex_reproducibility.md)
- Evidence matrix: [docs/eval/evidence_matrix.md](docs/eval/evidence_matrix.md)
- Integration notes: [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)
- Previous detailed README archive: [docs/archive/README_pre_website_refresh.md](docs/archive/README_pre_website_refresh.md)

## License

MIT License. See [LICENSE](LICENSE).
