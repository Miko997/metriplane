# Phase 00D Metadata Formatting Validation Report

## Summary

- Branch: `phase-00d-metadata-formatting-validation`
- Commit before changes: `1c7aed3`
- DOI: `10.5281/zenodo.20631037`
- Scope: metadata validity, Markdown placeholder readability, and package version metadata.

## Files changed

- `README.md`
- `ARTIFACTS.md`
- `pyproject.toml`
- `docs/reports/phase00d_metadata_formatting_report.md`

`CITATION.cff` and `.zenodo.json` were fully replaced during the work pass with the requested valid metadata content, but the replacement matched the existing tracked content and produced no final diff.

## Repository state confirmation

- Phase 00A duplicate-root cleanup is already present in history: `99316dd phase00: remove duplicate root package directories`.
- Phase 00B reviewer-path hardening is already present in history, including tool consolidation, the tracked demo replay fixture, CI guard hardening, and reviewer-path documentation updates.
- No duplicate root package directories were deleted in this task.
- No directories were deleted in this task.

## Metadata validation

- `CITATION.cff` parses with PyYAML.
- `CITATION.cff` contains version `0.1.4` and DOI `10.5281/zenodo.20631037`.
- `.zenodo.json` parses with `python -m json.tool`.
- `.zenodo.json` contains version `0.1.4`.
- `pyproject.toml` parses with `tomllib`.
- `pyproject.toml` now reports project version `0.1.4`.

## Markdown formatting

- Replaced angle-bracket session placeholders in `README.md` and `ARTIFACTS.md` with `SESSION_JSONL`.
- Replaced the output path placeholder in `README.md` with `RUNS/RUN_ID/session.jsonl`.
- Verified the requested Markdown files no longer contain the hidden-HTML session placeholders.
- README public release identity remains the v0.1.4 Zenodo software release.
- README footer remains the open research software description.

## Validation commands and results

- `git status --short`: clean before edits.
- `git log --oneline --decorate -n 20`: confirmed Phase 00A, Phase 00B, and Phase 00C history.
- `find . -maxdepth 1 -type d | sort`: inspected root directories; no cleanup performed.
- `python` CFF parse check with PyYAML: passed.
- `python -m json.tool .zenodo.json >/tmp/zenodo_validated.json`: passed.
- `python` JSON assertions for `.zenodo.json`: passed.
- `python` `tomllib` assertions for `pyproject.toml`: passed.
- Repository-wide stale identity grep: remaining matches are in older evaluation, case-study, GPU, and scope/provenance documents that preserve historical benchmark-evidence context. The public README, citation, Zenodo, and artifact identity files do not carry the stale public release identity.
- `python -m compileall metriplane tests benchmarks tools`: passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`: failed in system Python because `cv2` and `pydantic` are not installed there.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`: failed in the sandbox because local sockets are blocked and `~/.cache/metriplane` is read-only.
- Unsandboxed `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`: passed, `193 passed in 62.84s`.
- `python -m metriplane.cli doctor`: failed in the sandbox because local socket creation is blocked.
- Unsandboxed `python -m metriplane.cli doctor`: passed, `8 passed, 0 warnings, 0 failed`.
- `./tools/mp.sh deterministic-replay`: passed with `pass=true`, zero positional difference, and zero event mismatches.
- `git diff -- evidence`: empty.

## Evidence confirmation

No evidence files changed. Benchmark CSVs, JSONL evidence, checksums, manifest metric values, and benchmark values were not edited or regenerated.

## Remaining stale wording

The repository-wide stale identity search still reports legacy benchmark-evidence wording in older evaluation and provenance-oriented files under `docs/eval/`, `docs/case-studies/`, `docs/gpu_compute_backend.md`, and `docs/scope_rules.md`. Those files were left unchanged because this task forbids evidence changes and benchmark-claim changes, and the matches refer to historical evidence context rather than the current public README/citation/Zenodo release identity.
