# UI QA Summary — 2026-06-14

Repo state: final release-gate working tree on `feature/release-v0.2.0`.

## Result

Static UI/API release gate: **PASS**
Browser E2E release gate: **PASS**
Integration runtime gate: **ROS 2 manual runtime smoke PASS; Omniverse manual evidence PARTIAL; Isaac Sim and Docker runtimes NOT RUN**

Static coverage found no broken dashboard command buttons and no unresolved P0/P1 missing UI coverage.
The hardening audit found no duplicate HTML IDs, no dashboard JavaScript syntax errors,
no duplicate command buttons on the same card, and no Atlas-gated buttons stuck disabled.
The clean-checkout fixture integrity test is part of CI so release tests fail early
if required deterministic fixtures are missing from a fresh clone.

## Manual Integration Runtime Smoke

| Runtime | Result | Evidence | Boundary |
|---|---|---|---|
| ROS 2 | PASS | `evidence/experiments/ros2_runtime_manual_2026-06-14.md` | Manual one-environment smoke; bridge package builds, `ros2 run` resolves, launch publishes `/metriplane/frame_state`, and bag capture recorded messages. No latency, reliability, robot-control, safety, or production-runtime claim. |
| Omniverse | PARTIAL | `evidence/experiments/omniverse_runtime_manual_2026-06-14.md` | Generated USDA replay artifact is checksummed; no raw Omniverse open log or screenshot captured. No simulator runtime, latency, physics-correctness, or production-runtime claim. |
| Isaac Sim | NOT RUN | - | No manual runtime-open evidence captured. |
| Docker runtime | NOT RUN | - | No manual container runtime evidence captured in this pass. |

## Clean Checkout Fixture Gate

| Gate | Result | Evidence | Boundary |
|---|---|---|---|
| Release fixture integrity | PASS | `tests/test_release_fixture_integrity.py`, `.github/workflows/ci.yml`, `.github/workflows/release-gates.yml` | Small deterministic fixtures only; raw local runs and large media remain ignored. |

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
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_release_fixture_integrity.py -q` | PASS: `1 passed in 0.01s` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` | PASS after rerun outside sandbox: `580 passed in 68.28s` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/ui_api tests/ui_coverage -q` | PASS: `27 passed in 2.66s` |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/e2e -q` | PASS after installing Playwright and Chromium: `1 passed in 1.16s` |
| `.venv/bin/python -m metriplane.cli doctor` | PASS: `8 passed, 0 warnings, 0 failed` |
| `bash -n tools/mp.sh tools/dashboard_runner.sh tools/validate-replay.sh` | PASS |
| `.venv/bin/python tools/audit_ui_functionality.py --out evidence/experiments/ui_coverage_latest.csv --json evidence/experiments/ui_coverage_latest.json` | PASS: no duplicate IDs, no JS syntax errors, no broken command buttons |
| `.venv/bin/python tools/run_ui_demo_replay.py` | PASS after rerun outside sandbox; generated local run, report, evidence workspace, and USD replay |
| `for f in web/dashboard/*.js; do node --check "$f"; done` | PASS |
| `./tools/mp.sh deterministic-replay` | PASS: 2 frames, 6 object pairs, 0 event mismatches |
| `.venv/bin/python -m metriplane.cli atlas validate-pack/run/bundle verify/test` | PASS: assembly-cell pack, incident bundle, and regression result passed |
| `.venv/bin/python tools/check_ros2_adapters.py` | PASS: `18 passed` |
| `.venv/bin/python -m build` | PASS after network-approved isolated build; sdist and wheel built, including `metriplane/` and top-level `integrations/` |
| Fresh venv wheel install from `dist/*.whl` | PASS after network-approved dependency install; installed `metriplane 0.2.0` |
| `/tmp/metriplane-wheel-smoke/bin/python -m metriplane.cli doctor` | PASS from outside checkout: `5 passed, 3 warnings, 0 failed` |
| `/tmp/metriplane-wheel-smoke/bin/metriplane doctor` | PASS from outside checkout: `5 passed, 3 warnings, 0 failed` |
| Wheel import smoke | PASS: imports came from `/tmp/metriplane-wheel-smoke/lib/python3.12/site-packages`, including Isaac and Omniverse integration modules |
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
- Added Playwright smoke test and documentation under `tests/e2e/` and `docs/qa/ui_testing.md`.
- Added UI consumption of runner `/commands` and `/jobs` endpoints.
- Added duplicate HTML ID, command allowlist, and Command Center merge-artifact regression tests.
- Extended the UI audit to report duplicate IDs, JavaScript syntax errors, duplicate command buttons per card, Atlas-gated enable wiring, and read-only fallback endpoint coverage.
- Added visible UI actions for camera scan, provenance check, Command Center sample build, and Isaac USD export.
- Added Command Center trace summary UI backed by `/operator/traces`.
- Hardened operator profile creation so dict-shaped/unsafe camera specs are rejected instead of silently ignored.
- Improved `tools/dashboard_runner.sh` and runner service port-conflict messages.
- Hardened `metriplane doctor` so installed-wheel runs outside the source checkout warn on repo-only helpers instead of failing.

## Critical And High Bugs

None open after this pass.

## Missing Features

None open in P0/P1 static coverage.

Lower-level developer scripts remain classified as `cli_only_documented` unless they are part of a primary local UI workflow.

## Limitations

- The coverage audit is static and conservative; it does not prove every runtime branch.
- The plain `python` executable outside the repo venv does not have project dependencies installed; final QA used the repo `.venv`.
- ROS 2 was launched manually in one maintainer environment and passed the bridge smoke; Omniverse has generated USDA artifact evidence but no open log/screenshot; Isaac Sim and Docker runtime behavior were not launched in this pass.
- Headless screenshots were captured with the runner offline, so they validate layout and assets, not live runner data refresh.
- The first sandboxed demo replay attempt failed because `/home/miko/metriplane-runs` was read-only in the sandbox; the same command passed outside the sandbox.
- The first sandboxed full pytest run failed because sockets and `/home/miko/.cache` writes were blocked; the same command passed outside the sandbox. After Playwright was installed, the full suite includes the browser smoke instead of skipping it.
- The first sandboxed package build/install attempts failed because DNS/network access to PyPI was blocked; the same commands passed with network approval.
