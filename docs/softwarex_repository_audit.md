<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# SoftwareX Repository Audit

Audit date: 2026-07-12

Scope: publication-readiness audit for the public Metriplane v0.2.0 repository.
This audit checked repository documentation, release metadata, reproducibility
commands, evidence artifacts, local and external links, and website consistency.
It did not change software functionality, algorithms, or evidence outputs.

Local audit context:

- Current branch: `main`
- Current HEAD: `70cb5ed3a1fd854d64bdd54e5d6e8df11e6fc805`
- Local `v0.2.0` tag target: `8e35ed5bb20837f7dc46354777407b848d7ce17a`
- GitHub release page: `https://github.com/Miko997/metriplane/releases/tag/v0.2.0`
- Zenodo DOI: `10.5281/zenodo.20736619`
- Zenodo record: `https://zenodo.org/records/20736619`

## PASS

### PASS-01: Core release metadata exists

Problem: None found for the core metadata files.

Why it matters: SoftwareX reviewers need a clear software identity, version,
license, citation, and archive.

Recommended fix: None. Keep `pyproject.toml`, `CITATION.cff`, `.zenodo.json`,
`LICENSE`, `NOTICE`, `AUTHORS.md`, and the README release links aligned.

Blocks SoftwareX submission: No.

### PASS-02: GitHub and Zenodo release records are reachable

Problem: None found for public release reachability.

Why it matters: Reviewers can verify that v0.2.0 is a public archived software
artifact.

Recommended fix: None. The GitHub release is published and not a draft or
prerelease. Zenodo API metadata reports record `20736619`, DOI
`10.5281/zenodo.20736619`, version `0.2.0`, resource type `software`, and
publication date `2026-06-17`.

Blocks SoftwareX submission: No.

### PASS-03: README and Issue #6 camera-free reproduction path works

Problem: None found for the camera-free reproduction commands when run in the
documented virtual environment.

Why it matters: This is the primary reviewer path.

Recommended fix: None for command correctness. Commands verified:

- `.venv/bin/python -m metriplane.cli doctor`: 8 passed, 0 warnings, 0 failed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`: 580 passed in 68.56 s.
- `./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl` with `RUNS=/tmp/metriplane-audit-runs`: `pass=true`, 24 frames, 72 object pairs, zero position difference, zero event mismatches.
- `.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell`: PASS.
- `.venv/bin/metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out /tmp/metriplane-audit-atlas-run`: 6 events, 1 incident.
- `.venv/bin/metriplane atlas bundle verify /tmp/metriplane-audit-atlas-run/evidence_bundles/INC-0001.zip`: `"pass": true`.
- `.venv/bin/metriplane atlas test /tmp/metriplane-audit-atlas-run/regression_tests/INC-0001.yaml`: PASS.

Blocks SoftwareX submission: No.

### PASS-04: Paper evidence package checksums verify

Problem: None found inside `evidence/paper_v2_0/CHECKSUMS.sha256`.

Why it matters: The paper evidence package is internally checksum-verifiable.

Recommended fix: None. `sha256sum -c evidence/paper_v2_0/CHECKSUMS.sha256`
passed.

Blocks SoftwareX submission: No.

### PASS-05: Atlas paper metrics reproduce

Problem: None found for the core Atlas values.

Why it matters: These are the headline v0.2.0 paper evidence values.

Recommended fix: None. `evidence/paper_v2_0/atlas_run/metrics.json` and the
fresh temp run both report 6 events, 1 incident, observed duration 70.0 s, and
35.0 s wait time for `torque_driver_available`.

Blocks SoftwareX submission: No.

### PASS-06: CLI surfaces used in documentation exist

Problem: None found for the checked top-level CLI surfaces.

Why it matters: Stale command names cause immediate reviewer failures.

Recommended fix: None. Help commands succeed for `atlas`, `sentinel`,
`command-center`, `test`, `rules`, `traces`, `camera-trust`, `counterfactual`,
`contracts`, `ask`, `replay`, `start`, `status`, `stop`, `cleanup`, `restart`,
`objects`, `query`, and `incidents`.

Blocks SoftwareX submission: No.

### PASS-07: Internal Markdown anchors are clean after cleanup

Problem: Stale anchors were found and fixed in `docs/PREREQUISITES.md` and
`docs/archive/README_pre_website_refresh.md`.

Why it matters: Broken local documentation navigation makes the reviewer path
look stale.

Recommended fix: Done. The rerun local link scan found 0 bad anchors.

Blocks SoftwareX submission: No.

### PASS-08: External links are mostly reachable

Problem: No confirmed broken external links among the checked public URLs.

Why it matters: Release, DOI, website, issue, demo, and reference links need to
be usable by reviewers.

Recommended fix: None for links returning 200. The automated checker verified
47 unique non-local external URLs; 45 returned 200. Two reference links returned
403 to the automated checker and are listed as warnings, not confirmed broken.

Blocks SoftwareX submission: No.

## WARNING

### WARNING-01: Product capitalization is inconsistent

Problem: Release-facing files use both `Metriplane` and an older mixed-case
spelling. The lowercase `metriplane` is correct for the package, CLI, URLs, and
repository name.

Why it matters: Mixed product spelling can look unpolished in a SoftwareX
submission and can leak into manuscript citations.

Recommended fix: Use `Metriplane` in new human-facing manuscript and repository
prose. Leave immutable DOI, release, and checksummed evidence titles unchanged
where editing would change archival provenance.

Blocks SoftwareX submission: No, but it should be cleaned up before manuscript
submission.

### WARNING-02: Current HEAD is not the v0.2.0 tag

Problem: Current HEAD is `70cb5ed`, while the local and GitHub `v0.2.0` tag
points to `8e35ed5`. Current `main` includes documentation maintenance after
the tag.

Why it matters: Reviewers may not know whether to evaluate the tagged DOI
artifact or current `main`.

Recommended fix: Done in the final publication-preparation pass. Option A
selects the Zenodo/GitHub `v0.2.0` tag as the SoftwareX artifact, and current
`main` is documented as post-release documentation maintenance only.

Blocks SoftwareX submission: No after Option A, provided the manuscript keeps
the tag/DOI artifact identity.

### WARNING-03: Paper evidence provenance was captured before the final tag

Problem: `evidence/paper_v2_0/git_commit.txt` records branch
`feature/release-v0.2.0` at commit `44bed6d85786675c5581154f588a7ad2529c85d6`
with a dirty worktree. The final tag is `8e35ed5`, and current HEAD is
`70cb5ed`.

Why it matters: A reviewer may ask why the captured evidence commit, the release
tag, and current HEAD differ.

Recommended fix: Done in `docs/softwarex_release_provenance.md`. The manuscript
should state that the paper evidence package was captured before final
tag/Zenodo archival and then included in the v0.2.0 release tree.

Blocks SoftwareX submission: No after disclosure. It would become a blocker only
if exact tag-to-run provenance were claimed without explanation.

### WARNING-04: Aggregate release-tree evidence audit fails on current HEAD

Problem: `scripts/audit_evidence.py` fails on current HEAD. Reported items were:
`docs/archive/README_pre_website_refresh.md` missing from
`evidence/CHECKSUMS.sha256`, `README.md` hash mismatch, `README.md` missing the
script's authoritative metric-table warning, and hash mismatches for the
documentation files edited during this audit. This new
`docs/softwarex_repository_audit.md` file is also a post-release current-HEAD
document and is not part of the frozen v0.2.0 checksum set.

Why it matters: `ARTIFACTS.md` documents `sha256sum -c evidence/CHECKSUMS.sha256`
as a verification command, but that aggregate checksum now fails for current
HEAD.

Recommended fix: Do not regenerate evidence casually. Under Option A, treat the
aggregate checksum as release-tree provenance for the archived tag, not as a
current-HEAD verification surface. If a future release is created, refresh only
release metadata/checksums through the release process and document that no
benchmark/evidence outputs were regenerated.

Blocks SoftwareX submission: No under Option A, where the submitted artifact is
the existing v0.2.0 tag/Zenodo archive.

### WARNING-05: Duplicate deterministic replay artifacts report different frame counts

Problem: Replay determinism artifacts differ by evidence layer:
`evidence/experiments/replay_determinism.csv` reports 302 frames and 906 object
pairs; `evidence/paper_v2_0/runs/demo-evidence/replay_determinism.csv` reports
24 frames and 72 object pairs; `evidence/paper_v2_0/artifacts/replay_determinism.csv`
reports 2 frames and 6 object pairs.

Why it matters: The differences are explainable as separate historical,
paper-demo, and stale copied artifacts, but reviewers may see them as
conflicting replay statistics.

Recommended fix: Add a note distinguishing the historical benchmark replay
artifact from the v0.2.0 paper demo replay. Consider removing or clearly
labeling the stale copied `artifacts/replay_determinism.csv` in the next release.

Blocks SoftwareX submission: No for the documented reviewer path, but it can
cause reviewer confusion.

### WARNING-06: A copied privacy report has a stale run path

Problem: `evidence/paper_v2_0/artifacts/privacy_report.json` records
`"run_dir": "runs/atlas/assembly_cell_missing_tool"`, while
`evidence/paper_v2_0/atlas_run/privacy_report.json` records
`"run_dir": "evidence/paper_v2_0/atlas_run"`.

Why it matters: The metrics are otherwise consistent, but copied artifacts with
different run roots can make provenance look messy.

Recommended fix: Leave current evidence unchanged for v0.2.0. In the next
release, avoid carrying duplicate copied artifacts unless their paths are
clearly scoped.

Blocks SoftwareX submission: No.

### WARNING-07: Generated dashboard links are missing in a clean checkout

Problem: Local link scan found missing generated targets:
`web/dashboard/atlas.html` links to
`web/dashboard/atlas_run/protocol/open_atlas_protocol_index.json`, and
`web/dashboard/integrations.html` links to
`web/dashboard/atlas_run/isaac/metriplane_replay.usda`. These exist only after
local generation, not in the tracked clean tree. The copied
`evidence/paper_v2_0/artifacts/atlas_dashboard.html` also has relative links to
`evidence_bundles/`, `regression_tests/`, and `training_cases/` that are not
present next to that copied HTML file.

Why it matters: Static dashboard links can appear broken if a reviewer opens the
HTML before running the generator or opens the copied artifact outside its full
run directory.

Recommended fix: Document that those links require generated Atlas run outputs,
or in a future release copy the dependent files with the dashboard artifact.

Blocks SoftwareX submission: No, because the full
`evidence/paper_v2_0/atlas_run/` dashboard context is present.

### WARNING-08: Website reproduction command writes into evidence paths

Problem: The website reproduce page and review-kit docs use
`RUNS=evidence/paper_v2_0/runs ./tools/mp.sh deterministic-replay ...` and
`--out evidence/paper_v2_0/atlas_run --overwrite`.

Why it matters: Running these commands in-place rewrites evidence-package paths,
which conflicts with the usual expectation that release evidence is frozen.

Recommended fix: For reviewers, recommend a temporary output path such as
`RUNS=/tmp/metriplane-runs` and `--out /tmp/metriplane-atlas-run`, then compare
against expected values. If preserving exact commands, warn reviewers to use a
fresh checkout or copy.

Blocks SoftwareX submission: No, but it is easy to improve.

### WARNING-09: Stale release-readiness wording remains in a checksummed paper doc

Problem: `docs/paper/v0_2_0_release_readiness_summary.md` still says no GitHub
tag or Zenodo archive was created in that pass, although the release and DOI now
exist.

Why it matters: It conflicts with README, checklist, website, GitHub release,
and Zenodo metadata.

Recommended fix: Because this file is pinned by
`evidence/paper_v2_0/CHECKSUMS.sha256`, do not edit it in-place for v0.2.0.
Add a separate note explaining that the file records a pre-release readiness
pass and that tag/Zenodo creation happened later.

Blocks SoftwareX submission: No if explained.

### WARNING-10: Some older/template docs reference non-existent generated paths

Problem: Static path scanning found missing example/template paths in older
docs, including `configs/fusion_health_local_2cam.yaml`,
`configs/examples/config.m8_fusion_local.yaml`, several `docs/evidence_manifest_spec.md`
example evidence filenames, and unimplemented helper names such as
`tools/generate_evidence_manifest.py`.

Why it matters: These are mostly examples or future-tool placeholders, but they
can look stale if reviewers browse beyond the SoftwareX path.

Recommended fix: Mark those docs as historical/template material or replace
non-existent paths with existing examples. Do not present them as required
SoftwareX reproduction commands.

Blocks SoftwareX submission: No for the documented v0.2.0 reviewer path.

### WARNING-11: Two external reference links could not be verified automatically

Problem: The automated external link checker received HTTP 403 for
`https://doi.org/10.1201/b16868` and
`https://www.acm.org/publications/policies/artifact-review-and-badging-current`.

Why it matters: HTTP 403 may be bot protection rather than a broken link, but it
means the audit could not prove availability automatically.

Recommended fix: Manually open both links in a browser before submission, or add
alternate publisher/reference URLs where appropriate.

Blocks SoftwareX submission: No.

### WARNING-12: Website has minor wording and path ambiguity

Problem: The website mostly matches repository claims, but it contains minor
presentation issues: automated text extraction shows the nav/logo text as
"Metri plane", one table says "assembly-cell re play", and the SoftwareX page
references `artifacts/INC-0001_zip_listing.txt` without the full
`evidence/paper_v2_0/` prefix.

Why it matters: These are small, but SoftwareX reviewers may follow the website
as a reproduction guide.

Recommended fix: Update the website wording and artifact paths to match the
repository exactly.

Blocks SoftwareX submission: No.

## ERROR (Resolved By Option A)

### ERROR-01: Released artifact identity needed explicit resolution

Problem: During the audit, release-facing materials pointed to `v0.2.0`, while
current `main` was ahead of the tag, the evidence package was captured from an
earlier pre-tag commit, and current HEAD had documentation changes not covered
by the aggregate release-tree checksums.

Why it matters: SoftwareX reviewers need to know exactly which artifact they are
reviewing: the Zenodo/GitHub `v0.2.0` release, current `main`, or a future
post-audit release.

Recommended fix: Done. Option A selects the DOI/tagged v0.2.0 artifact and keeps
current `main` as documentation maintenance only. The manuscript should cite the
tag, GitHub release, and DOI as the software artifact.

Blocks SoftwareX submission: No after Option A, provided the manuscript does not
present current `main` as the archived software artifact.

## Documentation Cleanup Performed

The following documentation-only fixes were made during this audit:

- Fixed stale README anchor in `docs/PREREQUISITES.md`.
- Fixed malformed support links in `docs/PREREQUISITES.md`.
- Updated `docs/PREREQUISITES.md` references from planned
  `docs/INTEGRATION.md` to existing `docs/INTEGRATIONS.md`.
- Fixed archive README navigation anchor for the operator dashboard section.
- Corrected `docs/backpressure.md` timeseries filename from
  `backpressure_001_timeseries.csv` to `backpressure_timeseries_001.csv`.
- Replaced a missing systems-demo shot-list path with the checked-in Docker demo
  proof path in `docs/backpressure.md`.

## Commands Verified

Commands run successfully:

- `.venv/bin/python -m metriplane.cli doctor`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`
- `RUNS=/tmp/metriplane-audit-runs ./tools/mp.sh deterministic-replay datasets/demo/session_001.jsonl`
- `.venv/bin/metriplane atlas validate-pack configs/domain_packs/assembly_cell`
- `.venv/bin/metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out /tmp/metriplane-audit-atlas-run`
- `.venv/bin/metriplane atlas bundle verify /tmp/metriplane-audit-atlas-run/evidence_bundles/INC-0001.zip`
- `.venv/bin/metriplane atlas test /tmp/metriplane-audit-atlas-run/regression_tests/INC-0001.yaml`
- `.venv/bin/metriplane atlas bundle verify evidence/paper_v2_0/atlas_run/evidence_bundles/INC-0001.zip`
- `.venv/bin/metriplane atlas test evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml --json`
- `sha256sum -c evidence/paper_v2_0/CHECKSUMS.sha256`
- `sha256sum -c evidence/paper_v2_0/runs/demo-evidence/replay_determinism.sha256`
- `sha256sum -c evidence/paper_v2_0/artifacts/INC-0001_zip.sha256`

Commands checked by installed tooling or captured evidence, not rerun exactly:

- `python -m build`: build module is installed and captured logs pass; exact
  command was not rerun to avoid replacing local `dist/` artifacts.
- `python -m twine check dist/*`: twine is installed and captured logs pass.

Commands not fully verified automatically:

- Docker commands, live-camera commands, ROS 2 runtime commands, Omniverse/Isaac
  runtime commands, GPU benchmark commands, hardware calibration commands, and
  placeholder commands using `SESSION_JSONL`, `<run_dir>`, or local config
  filenames.

## Website Consistency Summary

The website at `https://www.metriplane.com` is broadly consistent with the
repository:

- It describes v0.2.0 as DOI-archived and camera-free for reproduction.
- It uses the same headline evidence values: 580 tests, 6 physical events,
  1 incident, 35.0 s missing-tool delay, bundle verification pass, and
  regression pass.
- It preserves the same limitations: observe-only, bounded workcell,
  planar/tagged-asset scoped, no robot control, no safety certification, no
  quality-release approval, no people recognition, no marker-free tracking, no
  full 3D reconstruction, and no production-factory validation.

Website differences to address are listed in WARNING-08 and WARNING-12.

## Final Recommendation

The repository is ready to move into SoftwareX manuscript writing under Option
A: submit the existing v0.2.0 DOI/tag as the frozen artifact, explain the
pre-tag evidence capture, and treat current `main` documentation cleanup as
post-release repository maintenance. Do not create a new archive, tag, or
evidence package unless the publication plan changes.
