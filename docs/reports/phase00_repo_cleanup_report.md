# Phase 00A Repo Cleanup Report

## Scope

- Branch: `phase-00-repo-stabilization`
- Pre-cleanup commit hash: `ef26b07c40d76c6dd476f80bc2ad2b4504b2ef40`
- Commit scope: remove stale duplicate root package directories only.

## Directories Deleted

`backends/`, `calibration/`, `camera/`, `compute/`, `config/`, `fusion/`,
`mapping/`, `metriplane-icon-pack/`, `observability/`, `pipeline/`, `preview/`,
`provenance/`, `recording/`, `replay/`, `streaming/`, `system/`, `time/`.

## Directories Kept

`.github/`, `benchmarks/`, `calib/`, `configs/`, `docker/`, `docs/`,
`evidence/`, `metriplane/`, `scripts/`, `tests/`, `tools/`, `web/`.

## Legacy Milestone Helper

Command run:

```bash
git grep -n "<legacy milestone helper name>"
```

Result at Phase 00A time: references were found in the package-local M9 helper,
so the root helper symlink was left untouched per the Phase 00A instructions.

## Validation Commands

```bash
git status --short
```

Result: staged deletions for the approved directories only, plus pre-existing
untracked `paper_a_*` files.

```bash
git grep -nE '(^from |^import )(backends|calibration|camera|compute|fusion|mapping|observability|pipeline|preview|provenance|recording|replay|streaming|system)\b' . || true
```

Result: no matches.

```bash
python -m compileall metriplane tests benchmarks tools
```

Result: passed.

```bash
python -m pytest -q
```

Result: failed during collection before running tests because the active
`python` environment does not have `cv2` installed:

```text
ModuleNotFoundError: No module named 'cv2'
```

This appears unrelated to the root-directory deletion.

```bash
./tools/mp.sh deterministic-replay
```

Result: passed using the local ignored fallback dataset
`datasets/demo/session_001.jsonl`.

Observed replay summary:

```text
frames_compared: 102
object_pairs_compared: 306
mean_pos_diff_cm: 0.0
max_pos_diff_cm: 0.0
event_mismatch_count: 0
pass: true
```

The replay command wrote `evidence/experiments/replay_determinism.csv` and
`evidence/experiments/replay_determinism.sha256`; those generated evidence
changes were restored to HEAD immediately.

## Evidence Confirmation

No evidence data, checksums, manifest rows, metric values, release metadata, or
benchmark numbers are included in this commit. `git diff -- evidence` was empty
after restoring the replay-generated files.

## Phase 00B Follow-Up List Recorded At Phase 00A

1. Audit root Python files shadowing package modules (diff vs `metriplane/`
   counterparts, find direct execution references).
2. Fix deterministic replay to work on a clean clone (tracked demo fixture).
3. Move root experiment config files into `configs/examples/`.
4. Re-run reviewer quickstart from a fresh clone in a temp dir.
5. DOI/Zenodo archive after stabilization.
6. Audit and repair or remove the legacy milestone helper; Phase 00A left it
   untouched because the package-local helper referenced its own name.
