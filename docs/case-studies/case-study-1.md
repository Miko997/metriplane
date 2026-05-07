# Case Study 1: Multi-Camera Zone Analytics (Two-Zone Tabletop)

**Purpose**: Demonstrate Metriplane's core value proposition: real-time zone analytics via camera-first sensing  
**Status**: ✅ COMPLETE — Full 5-minute movement session with multi-camera fusion, zone analytics, and ID continuity evidence.  
**Session Date**: 2026-04-27  
**Git Commit**: 9ac336657989bc96f407ce4ca8e66acf89fb8e81  
**Required for**: Evaluation RQ1 (value), RQ2 (integration), RQ3 (sufficiency)

---

## Scenario Description

**Use Case**: Tabletop object tracking with two-zone spatial analytics  
**Objective**: Demonstrate that a camera-first digital twin can:
1. Track multiple ArUco markers (representing objects/assets) in real time
2. Detect zone entry/exit events via polygon-based zone definitions
3. Measure dwell time per object per zone over a 5-minute session
4. Record the session for offline replay and analysis
5. Operate with 2 USB cameras in a Kalman-filtered multi-camera fusion pipeline

**Why This Represents Experimentation Value**:
- No expensive sensors required (2 USB webcams total)
- Expected setup time: < 1 hour; to be validated by onboarding evidence.
- Zone analytics produced automatically without custom code
- Session replayable for iterative analysis

**Alternative (sensor-heavy)**: Implementing equivalent functionality with LiDAR + IMU would require significant additional hardware cost plus custom integration work.

---

## Hardware Setup

| Component | Value |
|-----------|-------|
| Camera 0 | USB webcam at /dev/video0 (cam0) |
| Camera 1 | USB webcam at /dev/video2 (cam1) |
| Tracked Objects | ArUco markers: IDs 4, 7, 12 (4×4 dictionary) |
| Workspace | board_55x40 (55cm × 40cm) |
| Zones | 2 zones: "left", "right" (polygon in world XY) |
| Mounting | Cameras above board, downward-facing |
| Compute | x86_64, Ubuntu 24.04, no GPU required (CPU mode) |

---

## Configuration

**Config File**: `configs/fusion_health_300fps.yaml`  
**Config SHA256**: `374489919f82bd800d922f4492405680bff9812c085916e854034047c284d481`  
**Calibration Profile**: `board_55x40_warehouse_story_v1_fusion`  
**Fusion Method**: Kalman filter (with weighted average fallback)  
**Compute Backend**: cpu_numpy (default)  
**Git Commit**: 9ac336657989bc96f407ce4ca8e66acf89fb8e81

**Zones**:
- `left`: polygon enclosing left half of board workspace  
- `right`: polygon enclosing right half of board workspace

---

## Execution

### Command Used

```bash
cd <repo> && source .venv/bin/activate
RUN_ID=case_study_1_movement_$(date +%Y%m%d_%H%M%S)
python -m metriplane.run_fusion \
  --config configs/fusion_health_300fps.yaml \
  --runs-dir ~/metriplane-runs \
  --run-id "$RUN_ID" \
  --duration-s 300
```

> Note: `metriplane-fusion` is not a registered entry point. Use `python -m metriplane.run_fusion` directly, or `./tools/mp.sh run-fusion cpu 300 <run_id>`.

### Session Details

| Property | Value |
|----------|-------|
| Run directory | `~/metriplane-runs/case_study_1_movement_20260427_220325/` |
| Session JSONL | `session.jsonl` (327 MB — not in git) |
| SHA256 | `a639b5180e533c585981bccb740cb31f782580bae72f96af7649ac5674839f16` |
| Duration | **300.02 seconds** (5 minutes) |
| Frames processed | **87,608** |
| Objects tracked (primary) | IDs 4, 7, 12 (ArUco 4×4 markers) |

---

## Primary Results (Movement Session)

### Zone Dwell Summary

**Evidence**: `evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv`  
**SHA256**: `d4d1ee5a1f65a25ebc4de3ad60d306fbc2acbd48fd7eb6848634ee315a291d69`

| Zone | Total Dwell (object-seconds) |
|------|------------------------------|
| **left** | **336.3 s** |
| **right** | **543.7 s** |

| Object | Zone left (s) | Zone right (s) |
|--------|--------------|----------------|
| ID 4 | 86.6 | 201.5 |
| ID 7 | 115.1 | 179.5 |
| ID 12 | 134.5 | 162.7 |

---

### Zone Transitions

**Evidence**: `evidence/experiments/case_study_1_movement_zone_transitions.csv`  
**SHA256**: `f362652ef02e9be72ddcd6e01c5e43203b58ddd04c2600656caa6c6834ae341c`

| Direction | Count |
|-----------|-------|
| left → right | **39** |
| right → left | **38** |
| **Total transitions** | **77** |

**Mean transition rate**: 77 / 300s ≈ **0.26 transitions/second** (marker moved ~every 4 seconds on average)

---

### Zone Event Counts

**Evidence**: `evidence/experiments/case_study_1_movement_zone_events.csv`  
**SHA256**: `7e1d4cb4bbfa33d36bc905ccd0b831530aadbeda8de842f0315b22f3a5b3135c`

| Object | Zone | Enters | Exits |
|--------|------|--------|-------|
| ID 4 | left | 17 | 17 |
| ID 4 | right | 23 | 23 |
| ID 7 | left | 12 | 12 |
| ID 7 | right | 25 | 24 ¹ |
| ID 12 | left | 23 | 23 |
| ID 12 | right | 20 | 19 ¹ |

> ¹ Exit count 1 less than enter count: marker was in zone at session end (final frame), so last exit was not recorded. This is expected behavior.

---

### Per-Object Dwell CSV

**Evidence**: `evidence/experiments/case_study_1_movement_zone_dwell.csv`  
**SHA256**: `11ff13ba4c9d3e2369e8f9b2110649255a37558df080c2245141ab3efd9c11d2`

---

## ID Continuity Under Motion (RQ3)

**Evidence**: `evidence/experiments/id_stability_movement_001.csv`  
**SHA256**: `cbdee40988bacc90a4e39a11455183d453ff96ffa228c9d67f6a349c052cc3de`  
**Tool**: `tools/analyze_id_stability_jsonl.py`

### Primary Objects (IDs 4, 7, 12)

| Object ID | Frames Seen | Total Frames | Coverage | Gaps | Max Gap (frames) |
|-----------|-------------|--------------|----------|------|-----------------|
| **4** | 85,349 | 87,608 | **97.4%** | 19 | 445 |
| **7** | 86,128 | 87,608 | **98.3%** | 16 | 268 |
| **12** | 86,832 | 87,608 | **99.1%** | 13 | 179 |

**Interpretation**: Gaps correspond to brief occlusion or edge-of-board detection failures during rapid movement. Max gap of 445 frames (ID 4) ≈ 1.5 seconds at 291 FPS — recovers quickly without ID change.

### Incidental Low-Coverage IDs (IDs 17, 37)

| Object ID | Frames Seen | Coverage | Classification |
|-----------|-------------|----------|----------------|
| 17 | 2,194 | 2.5% | Incidental — not a primary tracked object |
| 37 | 3,147 | 3.6% | Incidental — not a primary tracked object |

These are either nearby markers briefly entering the camera field-of-view, spurious detections, or ArUco markers from an adjacent board printed with overlapping IDs. They are not counted as primary case-study objects.

---

## Multi-Camera Fusion Contribution

| Metric | Value |
|--------|-------|
| Session frames | 87,608 |
| Cam1 stale frames | **17** (0.019%) |
| Object-frames fused with sensors=1 | 44,763 (17.1%) |
| Object-frames fused with sensors=2 | 218,887 (**83.0%**) |

**Interpretation**: In 83% of object observations, both cameras contributed to the fused position (sensors=2). The 17 cam1-stale frames at session start/brief intervals had no measurable impact on zone analytics. This confirms multi-camera Kalman fusion works reliably across a 5-minute session.

---

## Earlier Technical Session (Reference)

A 15.056-second static session (`timing_breakdown_001-11/session.jsonl`) captured detailed per-stage latency and confirmed pipeline sufficiency. It remains valid as technical evidence:

| Metric | Value |
|--------|-------|
| Latency p95 (total pipeline) | ~4.0 ms |
| FPS mean | 291.2 (target: 300) |
| Fusion jitter | < 0.23 mm |
| Mapping error mean | 0.40 cm |

Those results apply to the same hardware/config used in the movement case study.

---

## Value Demonstration (RQ1)

### Camera-First Benefits

| Benefit | Evidence |
|---------|----------|
| **Hardware cost** | 2 USB webcams (~€50–100 total) |
| **Setup time** | Expected < 1 hour (calibrate + configure; to be validated by onboarding evidence) |
| **Zone analytics** | 77 transitions, per-zone dwell times extracted automatically |
| **Replayability** | 327 MB JSONL enables offline analysis without re-running hardware |
| **No custom sensors** | Standard USB cameras, v4l2 compatible |

### Experimentation Value

A researcher can:
1. Place ArUco markers on objects in the workspace
2. Define zones in a YAML config
3. Run Metriplane — get real-time zone enter/exit events
4. Move objects and observe live zone transitions (77 detected in 5 minutes)
5. Replay the session for analysis or extended metrics computation
6. Tune zone definitions without repeating physical experiments

---

## Architecture Validation (RQ2)

**Integration Points Demonstrated**:
- ✅ WebSocket streaming (port 8765): Frames streamed during run
- ✅ Metrics endpoint (port 8000): Prometheus metrics available during run
- ✅ JSONL recording: 327 MB, 87,608 frames saved
- ✅ Zone analytics: 77 zone transitions, dwell times captured in schema
- ✅ Multi-camera fusion: 83% of object-frames used 2 sensors
- ✅ Provenance: git_commit `9ac3366`, config_hash in every frame

---

## Sufficiency Assessment (RQ3)

| Criterion | Target | Result |
|-----------|--------|--------|
| Latency p95 (pipeline) | < 10ms | **4.0ms** ✅ |
| Mapping error mean | < 1 cm | **0.40 cm** ✅ |
| Mapping error max | < 2 cm | **1.09 cm** ✅ |
| Tracking coverage (under motion) | > 95% | **97.4–99.1%** ✅ |
| Zone transition detection | Detected | **77 transitions** ✅ |
| Dwell time tracking | Per zone | **336–544 object-s** ✅ |
| Multi-camera fusion rate | Majority | **83% dual-sensor** ✅ |

---

## Limitations

1. **Markers static vs. dynamic tracking**: ArUco IDs are globally unique by design, so ID switches cannot occur. Coverage gaps (max 445 frames) represent detection loss, not re-ID failures.
2. **Ground truth not available**: Exact movement trajectory was not logged; dwell times are deduced from zone membership, not from a reference sensor.
3. **2 zones only**: Current config uses 2 adjacent rectangular zones. More complex zone layouts would require separate calibration.
4. **No screenshot/video**: Dashboard session not captured. See `tools/dashboard_runner.sh` to run dashboard.
5. **Setup time unvalidated**: Onboarding measurement still pending.

---

## Evidence Checklist

| Artifact | Status | Path |
|----------|--------|------|
| Session JSONL (movement) | ✅ Exists (327 MB, not in git) | `~/metriplane-runs/case_study_1_movement_20260427_220325/session.jsonl` |
| Zone events CSV | ✅ Complete | `evidence/experiments/case_study_1_movement_zone_events.csv` |
| Zone dwell CSV | ✅ Complete | `evidence/experiments/case_study_1_movement_zone_dwell.csv` |
| Zone dwell by zone CSV | ✅ Complete | `evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv` |
| Zone transitions CSV | ✅ Complete | `evidence/experiments/case_study_1_movement_zone_transitions.csv` |
| ID continuity under motion | ✅ Complete | `evidence/experiments/id_stability_movement_001.csv` |
| Static session (latency/FPS) | ✅ Complete | `~/metriplane-runs/timing_breakdown_001-11/session.jsonl` |
| Screenshot/video | ❌ Not captured | Requires manual execution of dashboard |

---

## Regeneration

```bash
cd <repo> && source .venv/bin/activate

# Re-run movement scenario (5 minutes)
RUN_ID=case_study_1_movement_$(date +%Y%m%d_%H%M%S)
python -m metriplane.run_fusion \
  --config configs/fusion_health_300fps.yaml \
  --runs-dir ~/metriplane-runs \
  --run-id "$RUN_ID" \
  --duration-s 300

# Extract zone analytics
python tools/zones_report_jsonl.py ~/metriplane-runs/${RUN_ID}-*/session.jsonl

# Extract ID continuity
python tools/analyze_id_stability_jsonl.py \
  ~/metriplane-runs/${RUN_ID}-*/session.jsonl \
  --out evidence/experiments/id_stability_movement_001.csv
```
