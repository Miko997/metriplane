# MetriPlane Case Study 1 Summary

**Purpose**: Movement-session zone analytics and marker-continuity evidence
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

## Scenario

| Property | Value |
|---|---|
| Session | `case_study_1_movement_20260427_220325` |
| Duration | 300.028 s |
| Motion continuity frames | 88,475 |
| Primary markers | ArUco IDs 4, 7, and 12 |
| Zones | `bl`, `br`, `tl`, `tr` |
| Config | `configs/fusion_health_300fps.yaml` |
| Session JSONL | Large file outside Git; checksum recorded in `evidence/manifest.csv` |

## Evidence Files

| File | Description |
|---|---|
| `evidence/experiments/case_study_1_movement_zone_events.csv` | Zone enter/exit events |
| `evidence/experiments/case_study_1_movement_zone_dwell.csv` | Per-object, per-zone dwell |
| `evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv` | Aggregated dwell by zone |
| `evidence/experiments/case_study_1_movement_zone_transitions.csv` | Cross-zone transition counts |
| `evidence/experiments/id_stability_movement_001.csv` | Marker continuity under motion |

## Zone Dwell

| Zone | Dwell seconds |
|---|---:|
| `bl` | 215.870 |
| `br` | 294.412 |
| `tl` | 170.295 |
| `tr` | 197.270 |
| **Total** | **877.848** |

Paper B rounded value: 877.85 object-seconds.

## Zone Transitions

| From | To | Count |
|---|---|---:|
| `bl` | `br` | 19 |
| `bl` | `tl` | 5 |
| `bl` | `tr` | 6 |
| `br` | `bl` | 22 |
| `br` | `tl` | 7 |
| `br` | `tr` | 3 |
| `tl` | `bl` | 5 |
| `tl` | `br` | 10 |
| `tl` | `tr` | 13 |
| `tr` | `bl` | 3 |
| `tr` | `br` | 3 |
| `tr` | `tl` | 16 |
| **Total** |  | **112** |

## Tracking Continuity Under Motion

| Object ID | Coverage | Gaps | Max gap |
|---:|---:|---:|---:|
| 4 | 98.39% | 11 | 533 frames |
| 7 | 99.17% | 10 | 297 frames |
| 12 | 99.25% | 12 | 141 frames |

## Evaluation Boundaries

- Zone dwell and transition counts are applied analytics computed from MetriPlane state streams.
- They are not a full manually annotated ground-truth zone-detection benchmark.
- The session is planar XY with `Z=0` and ArUco/fiducial IDs.
- Large raw JSONL evidence may be archived outside Git; use `evidence/manifest.csv` for checksums.

## Regeneration

```bash
python tools/zones_report_jsonl.py <session.jsonl> --out evidence/experiments --prefix case_study_1_movement
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_movement_001.csv
```
