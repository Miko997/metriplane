# Operator UI Final Smoke Test — Evaluation Summary

**Evidence ID**: `operator_ui_final_smoke_001`  
**Date**: 2026-04-28  
**Git Commit**: `469d51c` (v1.0.0-4-g469d51c)  
**Status**: ✅ PASS  
**Supports**: RQ1 (productization/adoption), RQ2 (extensibility/integration)

---

## What Was Validated

The Metriplane Operator UI ten-step wizard was executed end-to-end on a live two-camera setup. The goal of this test is to validate the **UI workflow and export pipeline**, not to benchmark tracking accuracy.

The 10-step workflow covers the full user journey from environment check through calibration, zone definition, config generation, fusion run, and analytics export.

---

## Results Summary

| Category | Result |
|---|---|
| UI workflow (Steps 1–10) | ✅ All steps passed |
| Calibration (cam0 + cam1 homography) | ✅ PASS |
| Alignment validation | ✅ PASS |
| Config generation | ✅ PASS (schema-valid YAML, config_hash recorded) |
| Fusion run | ✅ PASS — 1797 frames, 59.99 s |
| Zone analytics export | ✅ PASS — 5 CSVs |
| ID stability export | ✅ PASS — CSV with honest coverage values |
| Session SHA256 recorded | ✅ PASS |

---

## Session

| Field | Value |
|---|---|
| Run ID | `operator_run_20260428_211011` |
| Duration | 59.992 s |
| Frames | 1797 |
| Session size | 9.5 MB (not in git) |
| Session SHA256 | `5a814d7afb728f2f50d6e4e046b86f6f25846da0628b140b565df987d940bfa8` |
| Config hash | `3ce26849183877dc4fc58bc30e0b2f263483e3d047ec690f1ede915b235b0cee` |
| Resolved profile | `board_55x40_warehouse_story_v1_fusion` |

---

## Zone Analytics

| Metric | Value |
|---|---|
| Zones defined | 2 (left, right) |
| Total dwell time | 252.3 s |
| — left | 104.96 s |
| — right | 147.33 s |
| Zone transitions | 4 (left→right: 2, right→left: 2) |
| Zone events exported | 249 |

---

## ID Stability — Honest Values

> This is a **workflow proof**, not a tracking benchmark. The values below are the real tracking output from the 60-second session and are reported without adjustment.

| Object ID | Coverage | Gaps | Note |
|---|---|---|---|
| 0 | 100.0% | 0 | Fully continuous |
| 1 | 98.83% | 1 (max 21 fr) | Brief occlusion |
| 2 | 100.0% | 0 | Fully continuous |
| 3 | 100.0% | 0 | Fully continuous |
| 7 | 71.95% | 1 (max 504 fr) | Extended occlusion period |
| 12 | 76.46% | 1 (max 423 fr) | Extended occlusion period |

IDs 7 and 12 experienced extended occlusion during the session (objects left the camera's field of view). This is expected real-world behaviour and does not affect the UI workflow validation claim. The ID stability benchmark for tracking sufficiency is reported separately in `docs/eval/stability_summary.md`.

---

## Exported Evidence Artifacts

| Artifact | Path | SHA256 |
|---|---|---|
| Smoke test log (full) | `evidence/experiments/operator_ui_final_smoke_001.md` | — |
| Session SHA256 | `evidence/experiments/operator_ui_final_smoke_001_session.sha256` | (contains session hash) |
| CSV checksums | `evidence/experiments/operator_ui_final_smoke_001_csvs.sha256` | — |
| ID stability | `evidence/experiments/operator_ui_final_smoke_001_id_stability.csv` | `92fbb8d9…` |
| Zone dwell by zone | `evidence/experiments/operator_ui_final_smoke_001_zone_dwell_by_zone.csv` | `a7d1ee7f…` |
| Zone dwell | `evidence/experiments/operator_ui_final_smoke_001_zone_dwell.csv` | `c083fc89…` |
| Zone events | `evidence/experiments/operator_ui_final_smoke_001_zone_events.csv` | `4303c27e…` |
| Zone transitions | `evidence/experiments/operator_ui_final_smoke_001_zone_transitions.csv` | `2ae3a80a…` |

---

## Evaluation Interpretation

This evidence supports the following product claims:

1. **RQ1 — Productization value**: The Operator UI provides a guided, non-expert path from hardware setup to analytics export. All 10 steps completed without manual intervention in the core path.

2. **RQ2 — Extensibility**: The UI generates schema-valid YAML configs (config_hash recorded in meta.json), interoperates with the calibration profile system, and exports structured analytics CSVs compatible with downstream analysis tools.

The UI workflow proof does **not** claim that all tracked objects achieve ≥95% ID coverage. Tracking sufficiency under controlled conditions is demonstrated by the dedicated ID stability benchmark (`evidence/experiments/id_stability_001.csv`, `id_stability_movement_001.csv`).

---

*Full evidence log: `evidence/experiments/operator_ui_final_smoke_001.md`*  
*Runbook: `docs/operator_ui_runbook.md` — section "Final Validated Smoke Test (2026-04-28)"*
