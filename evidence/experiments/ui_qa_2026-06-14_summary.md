# UI QA Summary — 2026-06-14

Repo commit: `a142346`

## Result

Release gate: **PASS**

Static coverage found no broken dashboard command buttons and no unresolved P0/P1 missing UI coverage.
The hardening audit found no duplicate HTML IDs, no dashboard JavaScript syntax errors,
no duplicate command buttons on the same card, and no Atlas-gated buttons stuck disabled.

## Coverage Summary

| Metric | Value |
|---|---:|
| total_discovered_features | 138 |
| ui_full | 63 |
| ui_partial | 16 |
| ui_copy_command_only | 12 |
| ui_disabled_with_reason | 0 |
| ui_missing | 0 |
| cli_only_documented | 47 |
| planned_only | 0 |
| broken_buttons | 0 |
| unsupported_claims_found | 0 |
| duplicate_html_ids | 0 |
| js_syntax_errors | 0 |
| js_syntax_check_unavailable | 0 |
| buttons_with_duplicate_command_id_on_same_card | 0 |
| data_needs_atlas_buttons_never_enabled | 0 |
| read_only_fallback_endpoints | 6 |
| critical_bugs | 0 |
| high_bugs | 0 |

Generated coverage files:

- `docs/qa/ui_functionality_inventory.md`
- `docs/qa/ui_functionality_coverage_matrix.md`
- `docs/qa/ui_missing_features_report.md`
- `docs/qa/ui_parity_report.md`
- `evidence/experiments/ui_coverage_latest.csv`
- `evidence/experiments/ui_coverage_latest.json`

## Commands Run

| Command | Result |
|---|---|
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` | Initial system-Python run failed because the active interpreter was not the repo venv and lacked dependencies such as `pydantic` and `cv2` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PATH="/home/miko/projects/metriplane-public/.venv/bin:$PATH" python -m pytest -q` | PASS: `553 passed, 1 skipped in 67.09s` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PATH="/home/miko/projects/metriplane-public/.venv/bin:$PATH" python -m pytest tests/ui_api tests/ui_coverage -q` | PASS: `23 passed in 2.64s` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PATH="/home/miko/projects/metriplane-public/.venv/bin:$PATH" python -m pytest tests/e2e -q` | SKIP: `1 skipped`; Playwright is not installed, so this is not final browser release evidence |
| `PATH="/home/miko/projects/metriplane-public/.venv/bin:$PATH" python -m metriplane.cli doctor` | PASS: `8 passed, 0 warnings, 0 failed` |
| `bash -n tools/mp.sh tools/dashboard_runner.sh` | PASS |
| `PATH="/home/miko/projects/metriplane-public/.venv/bin:$PATH" python tools/audit_ui_functionality.py --out evidence/experiments/ui_coverage_latest.csv --json evidence/experiments/ui_coverage_latest.json` | PASS: no duplicate IDs, no JS syntax errors, no broken command buttons |
| `.venv/bin/python tools/run_ui_demo_replay.py` | PASS after rerun outside sandbox; generated local run, report, evidence workspace, and USD replay |
| `for f in web/dashboard/*.js; do node --check "$f"; done` | PASS |
| Static dashboard page smoke | PASS: 11 dashboard pages found and loaded as HTML |
| Headless Chrome screenshot capture | PASS: 6 screenshots captured |

## Screenshots

Screenshots were saved under:

`evidence/experiments/ui_screenshots_2026-06-14/`

Captured pages:

- `index.png`
- `run.png`
- `command_center_live.png`
- `atlas.png`
- `integrations.png`
- `settings.png`

Each screenshot is a nonempty `1440 x 1000` PNG.

## Fixes Completed

- Added `tools/audit_ui_functionality.py` for static feature/UI coverage inventory.
- Added generated QA docs under `docs/qa/`.
- Added runner/operator API safety tests under `tests/ui_api/`.
- Added parser coverage tests under `tests/ui_coverage/`.
- Added optional Playwright smoke test and documentation under `tests/e2e/` and `docs/qa/ui_testing.md`.
- Added UI consumption of runner `/commands` and `/jobs` endpoints.
- Added duplicate HTML ID, command allowlist, and Command Center merge-artifact regression tests.
- Extended the UI audit to report duplicate IDs, JavaScript syntax errors, duplicate command buttons per card, Atlas-gated enable wiring, and read-only fallback endpoint coverage.
- Added visible UI actions for camera scan, provenance check, Command Center sample build, and Isaac USD export.
- Added Command Center trace summary UI backed by `/operator/traces`.
- Hardened operator profile creation so dict-shaped/unsafe camera specs are rejected instead of silently ignored.
- Improved `tools/dashboard_runner.sh` and runner service port-conflict messages.

## Critical And High Bugs

None open after this pass.

## Missing Features

None open in P0/P1 static coverage.

Lower-level developer scripts remain classified as `cli_only_documented` unless they are part of a primary local UI workflow.

## Limitations

- The coverage audit is static and conservative; it does not prove every runtime branch.
- Playwright is not installed in this environment, so browser automation is documented and skipped. This is not final browser release evidence.
- The plain `python` executable outside the repo venv does not have project dependencies installed; final QA used the repo `.venv` first in `PATH`.
- ROS 2, Docker container runtime behavior, Isaac Sim, and Omniverse runtime behavior were not launched; their local check/export actions are visible and gated in the UI.
- Headless screenshots were captured with the runner offline, so they validate layout and assets, not live runner data refresh.
- The first sandboxed demo replay attempt failed because `/home/miko/metriplane-runs` was read-only in the sandbox; the same command passed outside the sandbox.
