<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane v0.2.0 Claim Boundaries

This table is the release-candidate claim map for the local MetriPlane
v0.2.0 branch. It separates validated local behavior from adapter surfaces and
environment-specific work.

| Claim | Status | Evidence | Limitation |
|---|---|---|---|
| UI static coverage has no missing P0/P1 actions | validated | `docs/qa/ui_parity_report.md`, `evidence/experiments/ui_coverage_latest.json` | Static coverage; does not prove every runtime branch |
| Dashboard JavaScript has no syntax errors | validated | `node --check web/dashboard/*.js`, UI audit summary | Syntax only; not browser behavior |
| Duplicate dashboard HTML IDs are blocked by tests | validated | `tests/ui_coverage/test_dashboard_static_integrity.py`, UI audit summary | Per-file duplicate ID check |
| MetriPlane starts as one local console | validated | `metriplane start`, `docs/dashboard_multicam_runbook.md` | `--live` or a UI run action is required for runtime stream ports |
| Browser pages render with Playwright | skipped in this environment | `tests/e2e`, `docs/qa/ui_testing.md` | Browser evidence requires Playwright and Chromium installed |
| Camera-free demo builds Command Center and Evidence Review artifacts | validated | `tools/run_ui_demo_replay.py`, UI QA summary | Demo replay only |
| Evidence Review demo produces an incident bundle | validated | Atlas release gate, `metriplane atlas bundle verify` | Assembly-cell demo domain pack |
| Physical regression replays state through Atlas logic | validated | Atlas mutation regression test | Local JSONL replay/domain-pack scope |
| Safe bundle verification rejects zip-slip paths | validated | Atlas bundle safety test | Local zip validation, not general malware scanning |
| ROS 2 bridge exists | adapter | `tools/check_ros2_adapters.py`, docs | No live ROS runtime latency claim |
| USD/OpenUSD export exists | adapter/export | Isaac/Omniverse export commands and generated USD text | No measured simulator runtime claim |
| Sentinel risk forecasts are available | experimental local report | forecasting tests and docs | Advisory only; not a certified safety signal |
| Grounded operator Q&A is available | experimental local evidence Q&A | operator assistant tests and docs | Local citations only; not an external LLM validation |

MetriPlane is observe-only. It does not control robots or machines, is not
safety-certified, and is not a production collision-avoidance or quality-release
system. It requires a calibrated planar workspace and tracked/tagged assets for
the local release workflows.
