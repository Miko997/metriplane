# Operator UI End-to-End Smoke Test — Summary

**Date**: 2026-04-28  
**Run ID**: `operator_run_20260428_094902`  
**Git Commit**: `ac186ef` (ac186efbf319a3042ba25a4fc4a30aa16c9ebec6)  
**Status**: ✅ **PASS** — Full 10-step low-code workflow executed without errors.

---

## Purpose

This document records the first successful end-to-end execution of the Metriplane Operator UI
(the 10-step setup wizard in `web/dashboard/operator.html`).

The Operator UI is the primary productization artifact for RQ1 and RQ2 of the evaluation:

> — What measurable product value does a camera-first digital twin provide vs sensor-heavy
> approaches in early-stage experimentation scenarios?
>
> — Which architectural choices best support extensibility, integration, and adoption as
> a reusable platform product?

This smoke test demonstrates that a complete digital twin session — calibration through analytics
export — can be completed via a browser-based wizard with no manual terminal commands beyond
starting the runner service.

---

## Workflow Validated

All 10 Operator UI steps were executed in sequence:

| Step | Action | Result |
|------|--------|--------|
| 1 | Environment (doctor / preflight) | ✅ All checks passed |
| 2 | Camera scan — `/dev/video0`, `/dev/video2` | ✅ 2 cameras readable |
| 3 | Profile creation — `board_55x40_warehouse_story_v1_fusion` | ✅ Profile created |
| 4 | Anchor definition — 4 ArUco world-space anchors | ✅ Saved to `anchors.yaml` |
| 5a | cam0 homography calibration | ✅ `mapping_raw.yaml` written |
| 5b | cam1 homography calibration | ✅ `mapping_raw.yaml` written |
| 6 | Planar alignment validation (`report_alignment.py`, no intrinsics) | ✅ Alignment verified |
| 7 | Zone writing — 2 zones (`left`, `right`) | ✅ `zones.yaml` written |
| 8 | Runtime config generation — `board_55x40_warehouse_story_v1_fusion_multi_local.yaml` | ✅ Config saved with correct CameraSpec field names |
| 9 | 60-second fusion run (`python -m metriplane.run_fusion`) | ✅ Session JSONL written |
| 10 | Export: zone report + ID stability + SHA256 checksum | ✅ 5 CSVs exported |

---

## Run Metadata

| Property | Value |
|----------|-------|
| Run ID | `operator_run_20260428_094902` |
| Config | `configs/local/board_55x40_warehouse_story_v1_fusion_multi_local.yaml` |
| Duration | 59.992 s |
| Frames | 1797 |
| Session path | `~/metriplane-runs/operator_run_20260428_094902/session.jsonl` |
| Session size | 14 MB |
| Session SHA256 | `de6d0fa9e817476342a60fdb56c1ee096c03a2b2f3c7039c8a70acc219972c40` |
| Hardware | Linux 6.17, RTX 5070 Ti, /dev/video0 + /dev/video2 |
| Git commit | `ac186ef` |

> **Note**: The 14 MB session JSONL is not tracked in git. Its path, size, and SHA256 are
> recorded above for reproducibility.

---

## Exported Evidence

All CSVs are committed to git under `evidence/experiments/`:

| File | SHA256 (first 16) | Size |
|------|-------------------|------|
| `operator_ui_smoke_001.md` | `2851558e22f58d7e` | 1.2 KB |
| `operator_id_stability.csv` | `d71b04fc3f7d263c` | 0.4 KB |
| `operator_zone_events.csv` | `9d23723ffd0df441` | 10.5 KB |
| `operator_zone_dwell.csv` | `a23284984fdebee2` | 0.2 KB |
| `operator_zone_dwell_by_zone.csv` | `b9451c9ca43687f8` | 0.1 KB |
| `operator_zone_transitions.csv` | `2ae3a80ac7509c5f` | 0.05 KB |

---

## Key Metrics

### ID Stability (1797 frames, 59.992 s)

| Metric | Value |
|--------|-------|
| Unique IDs tracked | 7 |
| Frames per ID | 1797 / 1797 |
| Coverage | **100%** for all IDs |
| Gaps | **0** |

### Zone Dwell (2 zones)

| Zone | Total dwell (s) |
|------|----------------|
| left | 69.45 |
| right | 143.54 |

### Zone Transitions

| Transition | Count |
|------------|-------|
| left → right | 2 |
| right → left | 2 |

---

## Why This Supports Evaluation Claims

**RQ1 — Product value vs sensor-heavy approaches**

The entire workflow from raw cameras to exportable analytics completed in under 15 minutes of
operator time with no hardware beyond two USB cameras and a flat ArUco board. A sensor-heavy
approach (IMUs, LIDAR, proprietary SDK) would require days of integration effort for comparable
spatial tracking results.

**RQ2 — Extensibility and adoption**

The wizard generates a schema-valid YAML config that passes directly to `metriplane.run_fusion`
without modification. The runner service exposes a validated REST API that enforces safe field
names (`name`, `device`/`index`, `mapping_file`) before writing config files, preventing the
silent schema failures that blocked previous raw-terminal attempts.

The session output (JSONL) feeds the same analytics tools used in Case Study 1, confirming
the platform is reusable across both operator-guided and script-driven workflows.

---

## Limitations

| Limitation | Notes |
|------------|-------|
| No live video preview in UI | User must trust calibration output; frame overlay available via separate `tools/preview_world_overlay.py` |
| Single-user runner | One concurrent job slot by design; not an issue for lab/bench use |
| Intrinsics calibration not performed | Planar-only alignment used (no undistort); sufficient for flat-board scenarios |
| Session JSONL not in git | 14 MB exceeds VCS threshold; SHA256 ensures integrity |
| GPU backend not used for this run | CPU backend used; GPU path validated separately in M9.6 |

---

## Reproduction Steps

```bash
# Prerequisites: venv active, runner service running
cd <repo>
source .venv/bin/activate

# 1. Start the runner service
./tools/dashboard_runner.sh &

# 2. Serve the operator dashboard
python -m http.server 8088 --directory web/dashboard &

# 3. Open in browser
#    http://localhost:8088/operator.html

# 4. Follow Steps 1–10 in the wizard.
#    Use /dev/video0 (cam0), /dev/video2 (cam1)
#    Profile: board_55x40_warehouse_story_v1_fusion
#    Duration: 60 s

# 5. After Step 10:
#    Session: ~/metriplane-runs/<run_id>/session.jsonl
#    CSVs:    evidence/experiments/operator_*.csv
```

---

## Related Evidence

- `evidence/experiments/operator_ui_smoke_001.md` — raw smoke test log
- `evidence/manifest.csv` — rows `operator_ui_*` for all artifact checksums
- `docs/operator_ui_runbook.md` — step-by-step operator guide with validated smoke test section
- `docs/eval/benchmark_summary.md` — summary row for this run
- `docs/case-studies/case-study-1.md` — comparable 300 s movement study for benchmarking context
