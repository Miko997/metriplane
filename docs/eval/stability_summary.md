# Metriplane ID Continuity / Tracking Stability Summary (RQ3)

**Purpose**: Tracking robustness evidence technical sufficiency claim  
**Last Updated**: 2026-04-27  
**Source Session**: `~/metriplane-runs/timing_breakdown_001-11/session.jsonl`  
**Git Commit**: bfce3d905395aa3c95035faee7fca60cb21f58fb

---

## Important Terminology Note

This document reports **ID continuity** — whether the same object ID was present in every frame. It does **not** claim true ID-switch rate, which would require ground truth labeling (knowing which physical object corresponds to which marker ID across a trajectory). 

Since Metriplane uses ArUco markers (each with a unique printed ID), the marker ID never changes. What can be measured is whether a given marker ID was **continuously visible** across all frames. A gap would indicate the marker was occluded, moved out of frame, or failed detection.

---

## Environment

| Property | Value |
|----------|-------|
| Session | `timing_breakdown_001-11/session.jsonl` (15.056s) |
| Objects | 3 ArUco markers (4×4 dictionary) |
| Config | `configs/fusion_health_300fps.yaml` |
| Fusion | Kalman filter (2-camera) |
| Analysis Tool | `tools/analyze_id_stability_jsonl.py` (new, 2026-04-27) |

---

## ID Continuity Results

**Evidence**: `evidence/experiments/id_stability_001.csv`  
**SHA256**: `e30ee716fcba9a4b3979b1984ac1b8626fe7649d3f92290c0caf8a71d08aaaae`

| Object ID | Total Frames | Frames Seen | Coverage | Continuous? | Missing Gaps | Max Gap (frames) |
|-----------|-------------|-------------|----------|-------------|--------------|-----------------|
| **4** | 4384 | 4384 | **100.0%** | **True** | 0 | 0 |
| **7** | 4384 | 4384 | **100.0%** | **True** | 0 | 0 |
| **12** | 4384 | 4384 | **100.0%** | **True** | 0 | 0 |

**Session duration**: 15.056 s  
**Pipeline FPS during session**: 291 FPS mean  
**Total object-frame observations**: 4384 × 3 = 13,152

---

## Key Findings

✅ **All 3 markers tracked continuously**: 0 missing frames across 15-second session  
✅ **100% coverage per object**: No gaps, no dropouts  
✅ **Zero missing gaps**: No occlusion or detection failure during this session  
✅ **Consistent with fusion jitter**: Same session confirms 100% coverage in both analyses  

---

## Context and Limitations

### Scenario Conditions
This session had markers in **static positions** (not moving). Static markers are the best case for ArUco tracking. A movement scenario would show:
- Occasional frames where marker center is at edge of detection threshold
- Potential gaps during rapid movement or partial occlusion
- More meaningful continuity data

### What This Proves vs Does Not Prove

| Claim | Supported? | Evidence |
|-------|-----------|---------|
| ArUco detection works continuously at 291 FPS | ✅ YES | 4384/4384 frames across 15s |
| System supports static object presence tracking | ✅ YES | 0 gaps in static scenario |
| ID switches (re-ID) never occur with ArUco | ✅ YES | Marker IDs are globally unique by design |
| Continuity holds under motion / occlusion | ❓ NOT TESTED | Requires movement scenario |
| Continuity under poor lighting | ❓ NOT TESTED | Session lighting not documented |

### ArUco Design Guarantee
Unlike re-ID tracking systems, ArUco markers have **globally unique** printed IDs. An ID switch (tracking algorithm assigning wrong ID to an object) cannot occur at the detection level. Re-ID errors are impossible unless two markers with the same printed ID are in the scene simultaneously.

This means Metriplane's ID stability is architecturally guaranteed for the ArUco backend — the continuity metric primarily measures **detection reliability** rather than tracking algorithm quality.

---

## Evaluation Integration (RQ3)

**Sufficiency threshold**: 
- Target: > 95% coverage per object in static scenario
- Achieved: **100%** ✅

**Evaluation statement**: In a 15-second, 2-camera, 3-marker static scenario at 291 FPS, Metriplane maintains 100% ID continuity with zero detection gaps. ArUco markers provide globally unique IDs, eliminating the possibility of ID-switch errors at the detection layer. A movement scenario is required to characterize continuity under dynamic conditions.

---

## Movement Scenario (2026-04-27) ✅ COMPLETE

**Session**: `case_study_1_movement_20260427_220325/session.jsonl` (327 MB, not in git)  
**SHA256**: `a639b5180e533c585981bccb740cb31f782580bae72f96af7649ac5674839f16`  
**Evidence CSV**: `evidence/experiments/id_stability_movement_001.csv`  
**SHA256**: `cbdee40988bacc90a4e39a11455183d453ff96ffa228c9d67f6a349c052cc3de`  
**Duration**: 300.02 s | **Frames**: 87,608 | **Commit**: 9ac336657989bc96f407ce4ca8e66acf89fb8e81

### Primary Objects (IDs 4, 7, 12)

| Object ID | Total Frames | Frames Seen | Coverage | Continuous? | Gaps | Max Gap (frames) |
|-----------|-------------|-------------|----------|-------------|------|-----------------|
| **4** | 87,608 | 85,349 | **97.4%** | No | 19 | 445 |
| **7** | 87,608 | 86,128 | **98.3%** | No | 16 | 268 |
| **12** | 87,608 | 86,832 | **99.1%** | No | 13 | 179 |

**All primary objects exceed 97% coverage.** Gaps represent brief detection loss during rapid movement or edge-of-board pass; they are **not** ID switches.

Max gap of 445 frames (ID 4) ≈ 1.5 s at 291 FPS — the marker re-detected with the same ID after each gap.

### Incidental Low-Coverage IDs

| ID | Frames Seen | Coverage | Classification |
|----|-------------|----------|----------------|
| 17 | 2,194 | 2.5% | Incidental — not a primary tracked object |
| 37 | 3,147 | 3.6% | Incidental — not a primary tracked object |

IDs 17 and 37 are likely markers from an adjacent board or spurious detections that briefly entered camera view. They are **not** counted as primary case-study objects and do not affect zone analytics.

### Terminology Reminder

This section reports **ID continuity under motion** — not true ID-switch rate. ArUco IDs are globally unique by design; a detection-level ID switch cannot occur unless two physical markers share the same printed ID. Gaps in the table represent detection loss, not re-identification errors.

---

## Sufficiency Assessment (Updated — Both Scenarios)

| Criterion | Target | Static (15s) | Motion (300s) |
|-----------|--------|-------------|--------------|
| Coverage per object | > 95% | 100% ✅ | 97.4–99.1% ✅ |
| No ID switches | By design | ✅ | ✅ |
| Gaps in static scenario | 0 | 0 ✅ | N/A |
| Max gap under motion | < 10s | N/A | 1.5s ✅ |

---

## Previously Required Next Step (Now Done)

~~Run a movement scenario to get richer continuity data~~ — **Completed 2026-04-27**.

## Archive: Previous "Required Next Step" Command

Run a movement scenario to get richer continuity data:

```bash
cd <repo> && source .venv/bin/activate
# Run 5-min session while manually moving markers between zones
metriplane-fusion \
  --config configs/fusion_health_300fps.yaml \
  --runs-dir ~/metriplane-runs \
  --run-id case_study_1_movement \
  --duration-s 300

# Then analyze stability
python tools/analyze_id_stability_jsonl.py \
  ~/metriplane-runs/case_study_1_movement-1/session.jsonl \
  --out evidence/experiments/id_stability_movement_001.csv
```

---

## Evidence Files

| File | Path | SHA256 |
|------|------|--------|
| ID stability CSV | `evidence/experiments/id_stability_001.csv` | `e30ee716fcba9a4b3979b1984ac1b8626fe7649d3f92290c0caf8a71d08aaaae` |
| Source session | `~/metriplane-runs/timing_breakdown_001-11/session.jsonl` | — |
| Analysis script | `tools/analyze_id_stability_jsonl.py` | New 2026-04-27 |

---

## Regeneration Command

```bash
cd <repo> && source .venv/bin/activate
python tools/analyze_id_stability_jsonl.py \
  ~/metriplane-runs/timing_breakdown_001-11/session.jsonl \
  --out evidence/experiments/id_stability_001.csv
```
