# Phase 00B Reviewer Path Report

## Scope

- Branch: `phase-00b-reviewer-path`
- Pre-implementation commit: `d6b391d`
- Goal: remove remaining root/package duplication, make reviewer paths stable, and keep evidence data unchanged.

## Commits

| Task | Commit | Result |
| --- | --- | --- |
| 1. Remove root Python shadows | `180e64f` | Deleted root module shadows and placeholder junk; kept `conftest.py`. |
| 2. Consolidate tools | `87ecdc4` | Made root `tools/` canonical, removed broken legacy helper symlink and package-local tools tree. |
| 3. Track replay fixture | `ece8f5b` | Added clean-clone replay fixture at `datasets/demo/session_001.jsonl`. |
| 4. Move experiment configs | `7581e70` | Moved experiment YAMLs to `configs/examples/` and updated references. |
| 5. Guard pytest plugin autoload | `000c319` | Added CI/script guard for ROS pytest plugin autoload collisions. |
| 6. Docs and report | this report commit | Updated README, changelog, runbook text, stale references, and this report. |

## Task Notes

| Area | Outcome |
| --- | --- |
| Root Python shadows | Removed the approved root module shadows and placeholder junk; `conftest.py` stayed in place. |
| `conftest.py` sys.path prepend | Still useful in this phase for local package/test discovery and early package imports before pytest plugin collection. It was reviewed but not removed. |
| Tools consolidation safety check | `git grep` found no Python imports of `metriplane.tools`, so package-local tools were safe to remove. |
| Legacy milestone helper | The root helper was a broken symlink. The package-local copy was a legacy milestone script referenced only by its own help/error text, so it was removed with the package-local tools tree. |
| Replay fixture | The tracked fixture is the first 325 complete JSONL lines of the local demo session, with byte size 1,045,531. |
| Experiment configs | Root experiment YAML files moved to `configs/examples/`; `config.example.yaml` remains at the repository root. |
| Evidence files | No evidence data, checksums, manifest values, or benchmark numbers are included in Phase 00B commits. |

## Validation Commands

```bash
source .venv/bin/activate && python -m compileall metriplane tests benchmarks tools
```

Result: passed.

```bash
source .venv/bin/activate && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Result: passed, `193 passed in 62.86s (0:01:02)`.

```bash
./tools/mp.sh deterministic-replay
```

Result: passed against `datasets/demo/session_001.jsonl`.

```text
frames_compared: 24
object_pairs_compared: 72
mean_pos_diff_cm: 0.0
max_pos_diff_cm: 0.0
event_mismatch_count: 0
pass: true
```

At Phase 00B validation time, before the later output-routing follow-up, the
replay command rewrote `evidence/experiments/replay_determinism.csv` and
`evidence/experiments/replay_determinism.sha256`; both files were restored to
HEAD immediately after validation.

```bash
git diff -- evidence
```

Result: empty.

```bash
rg -n "<deleted package-local tools path and legacy helper patterns>" README.md CHANGELOG.md docs tools scripts docker .github pyproject.toml metriplane tests evidence || true
```

Result: no matches.

```bash
rg -n "<old root experiment config patterns>" README.md CHANGELOG.md docs tools scripts docker .github pyproject.toml metriplane tests evidence || true
```

Result: no matches.

```bash
rg -n "<deleted root Python shadow patterns>" README.md CHANGELOG.md docs tools scripts docker .github pyproject.toml metriplane tests evidence || true
```

Result: no stale root-file references.

## Observed Validation Failures

| Command | Result | Assessment |
| --- | --- | --- |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` with the bare system interpreter | Failed during collection because the system interpreter lacked project dependencies such as `cv2` and `pydantic`. | Environment issue, not caused by the deletions. |
| `.venv` pytest inside the default sandbox | Failed because sandbox restrictions blocked socket/cache operations. | Sandbox issue; the same `.venv` command passed outside those restrictions. |

## Follow-Up Items

1. Re-run the reviewer quickstart from a fresh clone in a temporary directory.
2. Revisit whether `conftest.py` can stop prepending the repository root once fresh-clone import paths are fully exercised.
3. Consider documenting development dependency installation more explicitly for users who run tests outside the project virtualenv.
4. Create the DOI/Zenodo archive only after stabilization is complete.
