# Case Study 1: Multi-Camera Zone Analytics

**Purpose**: Demonstrate MetriPlane's camera-first planar zone analytics workflow
**Status**: Complete movement-session evidence with multi-camera fusion, zone analytics, and fiducial-continuity artifacts
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`../eval/CANONICAL_EVIDENCE.md`](../eval/CANONICAL_EVIDENCE.md)

## Scenario

| Property | Value |
|---|---|
| Use case | Tabletop object tracking with polygon zone analytics |
| Cameras | Two USB cameras (`cam0`, `cam1`) |
| Primary markers | ArUco IDs 4, 7, and 12 |
| Workspace | 55 cm x 40 cm planar board |
| World model | Planar XY only; `Z=0` |
| Zones | Four zones: `bl`, `br`, `tl`, `tr` |
| Duration | 300.028 s |
| Motion-continuity frames | 88,475 |
| Session JSONL | Large file outside Git; checksum recorded in `evidence/manifest.csv` |

The case study demonstrates applied zone analytics from MetriPlane state streams. It is not a manually annotated ground-truth zone-detection benchmark.

## Evidence Files

| Artifact | Path |
|---|---|
| Zone events | `evidence/experiments/case_study_1_movement_zone_events.csv` |
| Zone dwell | `evidence/experiments/case_study_1_movement_zone_dwell.csv` |
| Zone dwell by zone | `evidence/experiments/case_study_1_movement_zone_dwell_by_zone.csv` |
| Zone transitions | `evidence/experiments/case_study_1_movement_zone_transitions.csv` |
| Motion continuity | `evidence/experiments/id_stability_movement_001.csv` |

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

## Fiducial Continuity Under Motion

| Object ID | Total frames | Frames seen | Coverage | Gaps | Max gap |
|---:|---:|---:|---:|---:|---:|
| 4 | 88,475 | 87,047 | 98.39% | 11 | 533 |
| 7 | 88,475 | 87,741 | 99.17% | 10 | 297 |
| 12 | 88,475 | 87,812 | 99.25% | 12 | 141 |

Gaps represent temporary fiducial detection loss, not ID switches. ArUco marker IDs are printed fiducial IDs, not marker-free object identities.

## Related Technical Evidence

| Result | Current canonical value | Artifact |
|---|---:|---|
| Latency | 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms | `evidence/experiments/latency_summary.csv` |
| Mapping | 0.63 cm mean; 1.07 cm max; N=9 | `evidence/experiments/mapping_error_001.csv` |
| Fusion jitter | 0.067-0.080 mm jitter std; absolute fused accuracy not measured | `evidence/experiments/fusion_jitter_001.csv` |

## Value Demonstration

- Standard cameras plus printed fiducials are sufficient for planar zone analytics in this tabletop setup.
- Zone definitions are data/configuration, not custom code.
- JSONL session recording allows offline analysis and reproducibility checks.
- The measured boundary is the WebSocket/JSONL state stream.

## Limitations

- Planar XY only; `Z=0`.
- Fiducial markers are required.
- Zone dwell and transitions are applied analytics, not a fully annotated ground-truth benchmark.
- Large raw JSONL sessions may be archived outside Git; use the manifest checksums for verification.
- Omniverse and ROS 2 are external/experimental unless separately measured.

## Regeneration

```bash
RUN_ID=case_study_1_movement_$(date +%Y%m%d_%H%M%S)
python -m metriplane.run_fusion \
  --config configs/fusion_health_300fps.yaml \
  --runs-dir ~/metriplane-runs \
  --run-id "$RUN_ID" \
  --duration-s 300

python tools/zones_report_jsonl.py <session.jsonl> --out evidence/experiments --prefix case_study_1_movement
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_movement_001.csv
```
