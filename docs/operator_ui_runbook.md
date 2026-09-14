<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane Operator UI Runbook

**Audience**: Non-code operators
**Requires**: Python venv active, runner service running

---

## ⚡ One-command Launcher (Recommended)

Use the `metriplane start` command to bring up the full stack:

```bash
# With venv active:
cd <repo>
source .venv/bin/activate

metriplane start --operator             # runner + dashboard, open setup wizard
metriplane start --operator --live      # also start camera-free runtime immediately
metriplane start --operator --live --config configs/fusion_health_300fps.yaml  # camera-backed runtime
metriplane status                        # shows port owners even if state is missing
metriplane stop                          # waits for ports to be released
metriplane stop --force                 # stop + cleanup orphans when state is absent
metriplane cleanup                       # remove orphaned Metriplane processes
metriplane restart --operator           # stop → cleanup → start fresh

# Without venv activation (convenience script):
./tools/start_metriplane.sh --operator
./tools/start_metriplane.sh stop
./tools/start_metriplane.sh status
./tools/start_metriplane.sh cleanup
```

This starts:
- **Runner service** on `http://127.0.0.1:9000/` (powers the operator wizard)
- **Dashboard web server** on `http://127.0.0.1:8088/` (serves all static assets)
- **Runtime stream** only when you start a demo/live session from the UI or pass `--live`

By default, no active run is started. Use the guided setup flow for camera-backed fusion, or use `--live --config configs/fusion_health_300fps.yaml` only when you intentionally want the runtime stream to start at launch.

Browser opens automatically to `http://127.0.0.1:8088/web/dashboard/operator.html`.

State file: `launcher-state.json` in the active platform state directory
Logs: `_launcher/<timestamp>/` in the active platform runs directory

---

## Quick Start (Manual)

```bash
# 1. Activate venv (if not already)
source .venv/bin/activate

# 2. Start the runner service (localhost :9000)
./tools/dashboard_runner.sh

# 3. Serve the dashboard (localhost :8088)
python -m http.server 8088 --directory web/dashboard

# 4. Open Operator Setup
# http://localhost:8088/operator.html
```

---

## What the Operator UI Does

The **Operator Setup** page is a 10-step wizard that guides you through:

| Step | What happens |
|------|-------------|
| 1. Environment | Run doctor / preflight, verify Python + GPU + git |
| 2. Cameras | Scan `/dev/video*`, assign cam0 and cam1 |
| 3. Profile | Create a named calibration profile with board dimensions |
| 4. Anchors | Define ArUco marker IDs and world-space coordinates |
| 5. Calibrate | Run homography calibration for each camera |
| 6. Validate | Verify multi-camera alignment quality |
| 7. Zones | Define spatial zones with presets or manual polygons |
| 8. Config | Build a local YAML runtime config, preview before saving |
| 9. Run | Start/stop live fusion, monitor job output |
| 10. Export | Generate zone reports, ID stability CSV, SHA256 checksum |

---

## Step-by-Step Guide

### Step 1 — Environment

**Before starting**: The runner must be running on `:9000`. Without the runner, buttons are disabled.

- Click **Refresh Info** to see Python version, git commit, GPU, and repo root.
- Click **Run Doctor** to run 8 system health checks.
- Click **Run Preflight** to check dependencies.
- Look for `✓ PASS` in the output log. If you see `✗ FAIL`, follow the error message.

---

### Step 2 — Cameras

- Click **Scan Cameras** — this calls `tools/list_cameras.py` and shows all `/dev/video*` devices.
- Each row shows: path, OpenCV open/read status, resolution, stable by-id symlink.
- Click **cam0** button on the row for your primary camera.
- Click **cam1** button on the row for your second camera (leave blank for single-camera mode).
- Or type the path directly in the input fields.
- Click **Next: Profile →**

**Note**: If cameras appear as `cv2_read: ✗`, the device may not be a capture camera (e.g. metadata-only v4l2 nodes). Try `/dev/video0`, `/dev/video2`, etc.

---

### Step 3 — Profile & Board

A calibration **profile** stores anchors, homography maps, and zones for a specific physical setup.

- If you have an existing profile, click **Use** next to it.
- Or enter a **profile name** (e.g. `my_lab_board`) — it will be created as `local_my_lab_board`.
- Enter **board width** and **board height** in meters.
- Select **Single (cam0 only)** or **Multi (cam0 + cam1)**.
- Click **Create Profile**.
- Directories are created under `calib/profiles/local_<name>/`.

**Safety**: New profiles always get a `local_` prefix so they will never overwrite shipped profiles.

---

### Step 4 — Anchor Markers

ArUco anchor markers define the physical coordinate system of your board.

- Click **Fill defaults (corners)** to populate corner anchors from board dimensions.
- The 4 default anchors are:
  - ID 0: `(0, 0)` — top-left
  - ID 1: `(0, height)` — bottom-left
  - ID 2: `(width, 0)` — top-right
  - ID 3: `(width, height)` — bottom-right
- Adjust marker IDs to match the ArUco IDs physically placed on your board.
- Add more anchors with **+ Add anchor** for better accuracy.
- Click **Save anchors.yaml** — writes to `calib/profiles/<profile>/anchors.yaml`.

---

### Step 5 — Calibrate Homography

**Requirements**:
- All anchor markers must be visible in the camera frame.
- Camera must be able to open and read frames (tested in Step 2).

- Adjust **Timeout** and **Max frames** if needed (default: 30s, 600 frames).
- The **Command preview** shows exactly what will run.
- Click **Calibrate cam0** → the tool captures frames and computes the homography.
- For multi-camera: click **Calibrate cam1** next.
- Wait for `✓ PASS` in the output log.
- Output file: `calib/profiles/<profile>/cam0/mapping_raw.yaml`

**If calibration fails**: check that markers are visible, unobstructed, and ID numbers match `anchors.yaml`.

---

### Step 6 — Validate Alignment (multi-camera)

This step tests whether cam0 and cam1 agree on physical coordinates.

- Check the command preview shows correct camera paths and mappings.
- Click **Validate Alignment**.
- Results show:
  - **Mean distance**: should be < 1 cm for good calibration
  - **Max distance**: should be < 2 cm
  - **Assessment**: ✓ Good or ⚠ > 2cm
- For single-camera, click **Skip**.

---

### Step 7 — Zone Editor

Zones are polygons in world-space (meters).

**Presets**:
- **Left / Right split**: divides board at horizontal midpoint
- **4 Quadrants**: divides board into 4 equal zones
- **Full board zone**: single zone covering entire board

**Manual zones**:
- Enter a zone **name** (letters/numbers/dash/underscore)
- Enter **polygon** as JSON: `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`
- Click **+ Add zone** for more zones

**YAML Preview** updates live as you edit.

- Click **Save zones.yaml** → writes to `calib/profiles/<profile>/zones.yaml`

---

### Step 8 — Runtime Config

Build a YAML config for your Metriplane session:

| Field | Default | Notes |
|-------|---------|-------|
| Mode | Multi | Single or multi-camera fusion |
| FPS | 30 | Target pipeline FPS (5–300) |
| Backend | cpu | `cpu` or `gpu` (requires CuPy + CUDA) |
| WS port | 8765 | WebSocket streaming port |
| Metrics port | 8000 | REST metrics endpoint |
| Record JSONL | yes | Enable session recording |
| Filename | auto | Saved to `configs/local/<name>.yaml` |

- The **YAML Preview** updates live as you change fields.
- Click **Save to configs/local/** — will confirm before overwriting.
- The saved path and config hash are shown in the log.

---

### Step 9 — Run Metriplane

- Select a config from the dropdown (your saved config appears under **Local configs**).
- Set **Duration** in seconds (5–7200). Set to max (7200) for long sessions.
- Optionally set a **Run ID** for the output directory name (auto-generated if empty).
- The **Command preview** shows the exact `python -m metriplane.run_fusion` call.
- Click **▶ Start** to launch the fusion pipeline.
- Output log shows live job status.
- Click **■ Stop** to cancel the run.
- **Latest Run Directory** shows the output path and session file status.

**Run output** is written to `<platform-runs-dir>/<run_id>/` (the UI displays the resolved path):
- `session.jsonl` — frame-by-frame recording
- `meta.json` — run metadata (run_id, git commit, config hash)

---

### Step 10 — Export Evidence

After a run completes:

- The **Session File** section auto-fills the latest session path.
- Set an **Output prefix** (e.g. `my_run_001`).

**Generate Zone Report** — calls `tools/zones_report_jsonl.py`:
- Outputs per-object zone dwell CSV and zone transitions CSV
- Saved to `evidence/experiments/<prefix>_*.csv`

**Generate ID Stability Report** — calls `tools/analyze_id_stability_jsonl.py`:
- Outputs per-object tracking continuity CSV
- Saved to `evidence/experiments/<prefix>_id_stability.csv`

**Compute SHA256** — streams SHA256 over the session file:
- Shows hash, file size
- Use this to fill `evidence/manifest.csv` entries

---

## Runner API Reference

The runner service at `:9000` exposes these operator endpoints:

| Method | Path | Action |
|--------|------|--------|
| GET | `/operator/env` | System info (Python, git, GPU) |
| GET | `/operator/cameras` | Camera scan results |
| GET | `/operator/profiles` | List calibration profiles |
| GET | `/operator/configs` | List YAML configs |
| GET | `/operator/latest-run` | Latest run directory info |
| POST | `/operator/create-profile` | Create profile + write anchors.yaml |
| POST | `/operator/write-zones` | Write zones.yaml to profile |
| POST | `/operator/save-config` | Save config to configs/local/ |
| POST | `/operator/calibrate` | Run homography calibration |
| POST | `/operator/validate-alignment` | Run alignment validation |
| POST | `/operator/start-fusion` | Start live fusion run |
| POST | `/operator/generate-report` | Generate zone/ID stability report |
| POST | `/operator/checksum` | Compute SHA256 of session file |

---

## Safety Rules

- All endpoints validate inputs. Profile names must match `[a-zA-Z0-9][a-zA-Z0-9_-]*`.
- New profiles are prefixed `local_` to avoid overwriting shipped profiles.
- Generated configs go to `configs/local/` only.
- Session files and evidence are in the active platform runs directory and `evidence/experiments/` only.
- Camera paths are validated: must be `/dev/video*`, `/dev/v4l/by-id/*`, or integer `0-99`.
- No `shell=True` is used anywhere. All commands are pre-validated argument lists.
- Localhost-only: runner binds to `127.0.0.1:9000`.

---

## Known Limitations

| Limitation | Workaround |
|------------|-----------|
| Calibration requires anchors visible in frame | Use CLI: `python tools/calibrate_planar_homography.py` |
| No live camera preview in the UI | Use `tools/preview_world_overlay.py` separately |
| Zone editor is table-based, no canvas drawing | Use preset or enter coordinates manually |
| GPU backend requires CuPy + CUDA env sourced | Source `tools/env/vt_cuda13_env.sh` before starting runner |
| Health degradation test (M9.3) requires 2 capture cameras | Known hardware limitation |
| Single-user only (runner has one job slot) | By design; queue model not needed for lab use |

---

## Troubleshooting

**Runner won't start**:
```bash
# Check the venv is active
source .venv/bin/activate
python -m metriplane.runner.service --help
```

**"runner :9000 — not connected" in UI**:
- Start the runner: `./tools/dashboard_runner.sh`
- Check no other process is using port 9000: `ss -tlnp | grep 9000`

**Calibration times out**:
- Ensure anchor markers are in frame
- Reduce `--max-frames` or `--timeout-s`
- Try running from CLI to see CV2 output

**Zones report fails**:
- Session JSONL must be under the active platform runs directory shown by the UI
- Ensure the run was configured with `record_jsonl: true`

**GPU backend fails**:
- Source CUDA env: `source tools/env/vt_cuda13_env.sh`
- Run doctor: `python -m metriplane.cli doctor`

---

## UI Design and Integrated Runbook

**Status**: ✅ MVP redesign complete — 2026-04-28

### Shared Visual System

Both the runtime dashboard (`index.html`) and the Operator Setup wizard (`operator.html`) now share a single design system (`style.css`) with unified:

- Deep navy background (`#070d14` / `#0b1220`)
- Rounded card panels with subtle borders and elevation
- Consistent button hierarchy: cyan primary, dark-outlined secondary, muted danger
- Status chips in the top bar (WebSocket, Health, Metrics, Evidence)
- Consistent sidebar with brand logo, nav sections, and bottom CTA card

### Runtime Dashboard (`index.html`)

The runtime dashboard was redesigned with:

- **Expanded sidebar** (220 px) with labelled nav sections (Overview, Operator, Diagnostics) and a bottom CTA card "Open Operator Setup"
- **Top status bar** showing WebSocket / Health / Metrics / Evidence chips with animated dot indicators
- **5-column stat row** (Frame ID, Run ID, Schema, Objects, Fusion)
- **Quick Guide card** — embedded 4-step guide visible without leaving the dashboard
- **Evidence manifest** and **System Health** panels in the right column
- Graceful empty states with hints ("Start a run from Operator Setup to stream live state.")

### Operator Setup (`operator.html`)

The wizard was redesigned with:

- **Horizontal progress stepper** — 10 numbered bubbles across the top, active/done/error states, visible labels at ≥ 1100 px width
- **Left sidebar** preserved for step navigation, upgraded with brand logo
- **Right embedded Step Guide panel** — automatically updates on every step change. For each step shows:
  - Purpose (why this step exists)
  - Prerequisites (what must be done first)
  - What happens (what the buttons actually do)
  - Success criteria (how to know it worked)
  - Quick tip
  - Troubleshooting (collapsed by default)
  - "Open full runbook" link
- **Runner connection chip** in the step header

The step guide content lives in `RUNBOOK_STEPS` in `operator.js` and references the same information documented in this runbook. Users do not need to search separate documentation for basic workflow instructions.

### Functional Preservation

All existing actions, IDs, and button onclick handlers are preserved exactly. The redesign does not change any runner API endpoints, config schema validation, or session recording behaviour. The existing smoke test passes unchanged.

---

## Validated Smoke Test

**Status**: ✅ PASS — 2026-04-28  
**Git commit**: `ac186ef` (ac186efbf319a3042ba25a4fc4a30aa16c9ebec6)

### Run Details

| Property | Value |
|----------|-------|
| Run ID | `operator_run_20260428_094902` |
| Date | 2026-04-28 |
| Duration | 59.992 s |
| Frames | 1797 |
| Session SHA256 | `de6d0fa9e817476342a60fdb56c1ee096c03a2b2f3c7039c8a70acc219972c40` |
| Session size | 14 MB (not in git) |

### Steps Validated

| Step | Result |
|------|--------|
| 1 — Environment (doctor / preflight) | ✅ PASS |
| 2 — Camera scan (/dev/video0 + /dev/video2) | ✅ PASS |
| 3 — Profile creation | ✅ PASS |
| 4 — Anchor definition (4 markers) | ✅ PASS |
| 5a — cam0 homography calibration | ✅ PASS |
| 5b — cam1 homography calibration | ✅ PASS |
| 6 — Planar alignment validation | ✅ PASS |
| 7 — Zone writing (left / right) | ✅ PASS |
| 8 — Config generation (schema-valid YAML) | ✅ PASS |
| 9 — 60-second fusion run | ✅ PASS — 1797 frames |
| 10 — Export (zone report + ID stability + SHA256) | ✅ PASS |

### Evidence Paths

| Artifact | Path |
|----------|------|
| Smoke test log | `evidence/experiments/operator_ui_smoke_001.md` |
| ID stability CSV | `evidence/experiments/operator_id_stability.csv` |
| Zone events CSV | `evidence/experiments/operator_zone_events.csv` |
| Zone dwell CSV | `evidence/experiments/operator_zone_dwell.csv` |
| Zone dwell-by-zone CSV | `evidence/experiments/operator_zone_dwell_by_zone.csv` |
| Zone transitions CSV | `evidence/experiments/operator_zone_transitions.csv` |
| Full summary | `docs/eval/operator_ui_summary.md` |

---

## Final Validated Smoke Test (2026-04-28)

### Run: `operator_run_20260428_211011`

**Status**: ✅ PASS — All 10 steps completed end-to-end.

| Field | Value |
|---|---|
| Date | 2026-04-28 21:10:12 +03:00 |
| Git commit | `469d51c` (v1.0.0-4-g469d51c) |
| Config hash | `3ce26849183877dc4fc58bc30e0b2f263483e3d047ec690f1ede915b235b0cee` |
| Resolved profile | `board_55x40_warehouse_story_v1_fusion` |
| Duration | 59.992 s |
| Frames | 1797 |
| Session SHA256 | `5a814d7afb728f2f50d6e4e046b86f6f25846da0628b140b565df987d940bfa8` |
| Session size | 9.5 MB (not in git) |

### Steps Validated

| Step | Result |
|------|--------|
| 1 — Environment (doctor / preflight) | ✅ PASS |
| 2 — Camera scan (/dev/video0 + /dev/video2) | ✅ PASS |
| 3 — Profile creation | ✅ PASS |
| 4 — Anchor definition (4 markers) | ✅ PASS |
| 5a — cam0 homography calibration | ✅ PASS |
| 5b — cam1 homography calibration | ✅ PASS |
| 6 — Planar alignment validation | ✅ PASS |
| 7 — Zone writing (left / right) | ✅ PASS |
| 8 — Config generation (schema-valid YAML) | ✅ PASS |
| 9 — 60-second fusion run | ✅ PASS — 1797 frames |
| 10 — Export (zone report + ID stability + SHA256) | ✅ PASS |

### ID Stability — Honest Values

> This run is a **UI workflow/export proof**, not a tracking benchmark. ID coverage values reflect real-world occlusion events during the 60-second session.

| ID | Coverage | Gaps | Max Gap |
|----|----------|------|---------|
| 0 | 100.0% | 0 | — |
| 1 | 98.83% | 1 | 21 frames |
| 2 | 100.0% | 0 | — |
| 3 | 100.0% | 0 | — |
| 7 | 71.95% | 1 | 504 frames |
| 12 | 76.46% | 1 | 423 frames |

IDs 7 and 12 experienced extended occlusion. This does not affect the UI export proof.

### Zone Results

| Zone | Dwell (s) | Transitions |
|------|-----------|-------------|
| left | 104.96 | 2 outbound |
| right | 147.33 | 2 outbound |
| **total** | **252.29** | **4** |

### Evidence Paths

| Artifact | Path |
|----------|------|
| Full smoke evidence | `evidence/experiments/operator_ui_final_smoke_001.md` |
| Session SHA256 | `evidence/experiments/operator_ui_final_smoke_001_session.sha256` |
| ID stability CSV | `evidence/experiments/operator_ui_final_smoke_001_id_stability.csv` |
| Zone events CSV | `evidence/experiments/operator_ui_final_smoke_001_zone_events.csv` |
| Zone dwell CSV | `evidence/experiments/operator_ui_final_smoke_001_zone_dwell.csv` |
| Zone dwell-by-zone CSV | `evidence/experiments/operator_ui_final_smoke_001_zone_dwell_by_zone.csv` |
| Zone transitions CSV | `evidence/experiments/operator_ui_final_smoke_001_zone_transitions.csv` |
| Thesis summary | `docs/eval/operator_ui_final_smoke_summary.md` |
