# MetriPlane Fiducial Continuity Summary

**Purpose**: Paper B static and motion marker-continuity evidence
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

## Terminology

This document reports fiducial continuity: whether each ArUco marker ID is visible in each frame. It is not a marker-free recognition claim and not a general re-identification benchmark. ArUco markers provide printed IDs; gaps represent detection loss, occlusion, or leaving the field of view, not ID switches.

## Static Continuity

**Evidence**: `evidence/experiments/id_stability_001.csv`

| Object ID | Total frames | Frames seen | Coverage | Missing gaps | Max gap |
|---:|---:|---:|---:|---:|---:|
| 4 | 4,387 | 4,387 | 100.0% | 0 | 0 |
| 7 | 4,387 | 4,387 | 100.0% | 0 | 0 |
| 12 | 4,387 | 4,387 | 100.0% | 0 | 0 |

Static continuity result: all three primary markers are present for every frame in the static timing session.

## Motion Continuity

**Evidence**: `evidence/experiments/id_stability_movement_001.csv`

| Object ID | Total frames | Frames seen | Coverage | Missing gaps | Max gap |
|---:|---:|---:|---:|---:|---:|
| 4 | 88,475 | 87,047 | 98.39% | 11 | 533 |
| 7 | 88,475 | 87,741 | 99.17% | 10 | 297 |
| 12 | 88,475 | 87,812 | 99.25% | 12 | 141 |

Motion continuity result: primary-marker coverage ranges from 98.39% to 99.25% over 88,475 frames. The maximum observed gap is 533 frames for marker ID 4.

## Evaluation Boundaries

- The continuity artifacts use ArUco/fiducial IDs.
- They do not establish marker-free recognition.
- They do not establish full 3D scene reconstruction.
- They do not measure safety-certified industrial control behavior.

## Regeneration Commands

```bash
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_001.csv
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_movement_001.csv
```
