# UI Audit Summary — 2026-06-14

This file mirrors `evidence/experiments/ui_qa_2026-06-14_summary.md`.

Static UI/API release gate: **PASS**
Browser E2E release gate: **PASS**
Integration runtime gate: **ROS 2 manual runtime smoke PASS; Omniverse manual evidence PARTIAL; Isaac Sim and Docker runtimes NOT RUN**

Manual integration runtime smoke:

- ROS 2: PASS. See `evidence/experiments/ros2_runtime_manual_2026-06-14.md`; package builds, `ros2 run` resolves the bridge executable, launch publishes `/metriplane/frame_state`, and rosbag capture recorded messages.
- Omniverse: PARTIAL. See `evidence/experiments/omniverse_runtime_manual_2026-06-14.md`; generated USDA replay artifact is checksummed, but no raw open log or screenshot was captured.
- Isaac Sim: NOT RUN. No manual runtime-open evidence captured.
- Docker runtime: NOT RUN. No manual container runtime evidence captured in this pass.

Key result:

- `138` discovered features
- `0` missing UI features
- `0` broken buttons
- `0` duplicate HTML IDs
- `0` JavaScript syntax errors
- `0` duplicate command buttons on the same card
- `0` Atlas-gated buttons stuck disabled
- `6` observe-only endpoints covered by read-only GET fallback
- `0` critical bugs
- `0` high bugs
- Full pytest: `574 passed`
- New UI API and coverage tests: `27 passed`
- Playwright browser smoke: `1 passed`
- Doctor: `8 passed, 0 warnings, 0 failed`
- Camera-free demo replay: passed outside sandbox
- Fresh wheel install/import/doctor smoke: passed
- Screenshots: `evidence/experiments/ui_screenshots_2026-06-14/`

See `evidence/experiments/ui_qa_2026-06-14_summary.md` for the full command log, limitations, and fixed-item list.
