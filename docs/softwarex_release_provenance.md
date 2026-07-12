<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Release Provenance

## Artifact Decision: Option A

Option A is the selected publication path: the SoftwareX manuscript evaluates
the archived Metriplane v0.2.0 software release:

- GitHub release: `https://github.com/Miko997/metriplane/releases/tag/v0.2.0`
- Tag: `v0.2.0`
- Tag commit: `8e35ed5bb20837f7dc46354777407b848d7ce17a`
- Zenodo DOI: `10.5281/zenodo.20736619`
- Zenodo record: `https://zenodo.org/records/20736619`
- License: MIT, in `LICENSE`

Current `main` is documentation maintenance only. At audit time it was
`70cb5ed3a1fd854d64bdd54e5d6e8df11e6fc805`, which is not the same commit as the
v0.2.0 tag. Manuscript and reviewer materials should not present current `main`
as identical to the archived release.

## Evidence Package Provenance

The checked-in paper evidence package is `evidence/paper_v2_0/`. Its own
provenance files record that the evidence was captured before the final tag:

- Evidence capture commit: `44bed6d85786675c5581154f588a7ad2529c85d6`
- Evidence paths: `evidence/paper_v2_0/README.md`,
  `evidence/paper_v2_0/git_commit.txt`, and
  `evidence/paper_v2_0/01_git_revision.txt`

Safe wording: the evidence package was captured before tagging and then included
in the v0.2.0 release tree. Do not claim the checked-in evidence was generated
directly from the final tag commit.

The evidence package and paper/review-kit files are frozen provenance material.
For Option A, do not regenerate, rewrite, move, or delete them.

## Replay Statistics

Use these values carefully:

- `24` frames and `72` object pairs: current v0.2.0 camera-free demo
  reproduction, from `evidence/paper_v2_0/logs/deterministic_replay.txt` and
  `evidence/paper_v2_0/runs/demo-evidence/replay_determinism.csv`.
- `302` frames and `906` object pairs: historical benchmark lineage, from
  `evidence/experiments/replay_determinism.csv`.
- `2` frames and `6` object pairs: stale/minimal copied artifact, from
  `evidence/paper_v2_0/artifacts/replay_determinism.csv` and
  `evidence/paper_v2_0/logs/04_deterministic_replay.txt`; do not use as the main
  manuscript replay value unless explicitly explaining its provenance.

## Reviewer-Safe Reproduction

Reviewer-facing reproduction should write fresh outputs to temporary paths and
compare the result with the archived expected values:

```bash
RUNS=/tmp/metriplane-softwarex-runs ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl

.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell

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

Expected headline values:

- deterministic replay: `pass=true`, 24 frames, 72 object pairs, 0.0 cm mean and
  maximum positional difference, 0 event mismatches
- Atlas run: 6 physical events, 1 process deviation, 1 incident
- bundle verification: `pass=true`
- generated regression test: `pass=true`

## Naming Convention

Use `Metriplane` for human-facing product prose in new manuscript and repository
documentation. Keep lowercase `metriplane` for the Python package, import name,
CLI command, paths, and URLs.

Older immutable archive metadata and checksummed evidence may preserve older
capitalization. Leave those files unchanged to preserve release provenance.
