<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MetriPlane v0.2.0 Claim Boundaries

This table is the release-candidate claim map for the local MetriPlane
v0.2.0 branch. It separates validated local behavior from adapter surfaces and
environment-specific work.

Static UI/API release gate: **PASS**
Browser E2E release gate: **PASS**
Integration runtime gate: **ROS 2 manual runtime smoke PASS; Omniverse manual evidence PARTIAL; Isaac Sim and Docker runtimes NOT RUN**

## Manual Integration Runtime Smoke

| Runtime | Result | Evidence | Boundary |
|---|---|---|---|
| ROS 2 | PASS | `evidence/experiments/ros2_runtime_manual_2026-06-14.md` | Manual one-environment smoke; bridge package builds, `ros2 run` resolves, launch publishes `/metriplane/frame_state`, and bag capture recorded messages. No latency, reliability, robot-control, safety, or production-runtime claim. |
| Omniverse | PARTIAL | `evidence/experiments/omniverse_runtime_manual_2026-06-14.md` | Generated USDA replay artifact is checksummed; no raw Omniverse open log or screenshot captured. No simulator runtime, latency, physics-correctness, or production-runtime claim. |
| Isaac Sim | NOT RUN | - | No manual runtime-open evidence captured. |
| Docker runtime | NOT RUN | - | No manual container runtime evidence captured in this pass. |

| Claim | Status | Evidence | Limitation |
|---|---|---|---|
| UI static coverage has no missing P0/P1 actions | validated | `docs/qa/ui_parity_report.md`, `evidence/experiments/ui_coverage_latest.json` | Static coverage; does not prove every runtime branch |
| Dashboard JavaScript has no syntax errors | validated | `node --check web/dashboard/*.js`, UI audit summary | Syntax only; not browser behavior |
| Duplicate dashboard HTML IDs are blocked by tests | validated | `tests/ui_coverage/test_dashboard_static_integrity.py`, UI audit summary | Per-file duplicate ID check |
| MetriPlane starts as one local console | validated | `metriplane start`, `docs/dashboard_multicam_runbook.md` | `--live` or a UI run action is required for runtime stream ports |
| Browser pages render with Playwright | validated | `tests/e2e`, `docs/qa/ui_testing.md` | Browser evidence passed with Playwright and Chromium installed locally |
| Camera-free demo builds Command Center and Evidence Review artifacts | validated | `tools/run_ui_demo_replay.py`, UI QA summary | Demo replay only |
| Evidence Review demo produces an incident bundle | validated | Atlas release gate, `metriplane atlas bundle verify` | Assembly-cell demo domain pack |
| Physical regression replays state through Atlas logic | validated | Atlas mutation regression test | Local JSONL replay/domain-pack scope |
| Safe bundle verification rejects zip-slip paths | validated | Atlas bundle safety test | Local zip validation, not general malware scanning |
| ROS 2 bridge manual runtime smoke | manual runtime smoke PASS | `evidence/experiments/ros2_runtime_manual_2026-06-14.md` | One maintainer environment; no latency, reliability, robot-control, safety, or production-runtime claim |
| Omniverse USD manual evidence | PARTIAL | `evidence/experiments/omniverse_runtime_manual_2026-06-14.md` | Generated USDA replay artifact is checksummed; no raw Omniverse open log or screenshot captured; no simulator runtime, latency, physics-correctness, or production-runtime claim |
| Isaac Sim runtime | NOT RUN | `integrations/isaac/`, `evidence/experiments/isaac_omniverse_replay_001.md` | No manual Isaac runtime-open evidence captured |
| Docker runtime | NOT RUN | `tools/docker_demo_up.sh`, `evidence/experiments/docker_demo_proof_001.md` | Existing Docker proof is historical local demo evidence; no new Docker runtime smoke was run in this pass |
| Sentinel risk forecasts are available | experimental local report | forecasting tests and docs | Advisory only; not a certified safety signal |
| Grounded operator Q&A is available | experimental local evidence Q&A | operator assistant tests and docs | Local citations only; not an external LLM validation |

MetriPlane is observe-only. It does not control robots or machines, is not
safety-certified, and is not a production collision-avoidance or quality-release
system. It requires a calibrated planar workspace and tracked/tagged assets for
the local release workflows.
