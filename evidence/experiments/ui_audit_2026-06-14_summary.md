# UI Audit Summary — 2026-06-14

This file mirrors `evidence/experiments/ui_qa_2026-06-14_summary.md`.

Static UI/API release gate: **PASS**
Browser E2E release gate: **SKIPPED in this environment**
Integration runtime gate: **NOT RUN for external ROS 2, Isaac, Omniverse, and Docker runtimes**

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
- Full pytest: `570 passed, 1 skipped`
- New UI API and coverage tests: `27 passed`
- Doctor: `8 passed, 0 warnings, 0 failed`
- Camera-free demo replay: passed outside sandbox
- Screenshots: `evidence/experiments/ui_screenshots_2026-06-14/`

See `evidence/experiments/ui_qa_2026-06-14_summary.md` for the full command log, limitations, and fixed-item list.
