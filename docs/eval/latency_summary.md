# MetriPlane Latency Summary

**Purpose**: Paper B latency and stage-timing evidence
**Evidence source**: `evidence/experiments/latency_summary.csv`
**Paper B canonical release tag**: [`v0.1.1`](https://github.com/Miko997/metriplane/releases/tag/v0.1.1)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

## Two-Camera Timing Run

| Property | Value |
|---|---|
| Run ID | `timing_breakdown_001` |
| Git commit recorded in CSV | `382be2dff875cba78f028ea2240f1acf99699e1e` |
| Config hash | `374489919f82bd800d922f4492405680bff9812c085916e854034047c284d481` |
| Timing samples per non-sleep stage | 4,387 |
| Tracked objects | ArUco IDs 4, 7, and 12 |
| Compute backend | CPU NumPy by default |

## Stage Breakdown

| Stage | Mean ms | p50 ms | p95 ms | Max ms | Count |
|---|---:|---:|---:|---:|---:|
| detect.cam1 | 1.360 | 1.319 | 1.684 | 5.290 | 4,387 |
| detect.cam0 | 0.957 | 0.901 | 1.242 | 11.417 | 4,387 |
| sleep | 0.685 | 0.722 | 0.937 | 2.120 | 4,195 |
| build.msg | 0.161 | 0.160 | 0.185 | 0.520 | 4,387 |
| fuse | 0.150 | 0.150 | 0.184 | 0.352 | 4,387 |
| record.jsonl | 0.133 | 0.134 | 0.153 | 0.348 | 4,387 |
| zones | 0.025 | 0.025 | 0.030 | 0.070 | 4,387 |
| map.cam0 | 0.025 | 0.025 | 0.028 | 0.074 | 4,387 |
| map.cam1 | 0.022 | 0.022 | 0.026 | 0.060 | 4,387 |
| ws.send | 0.013 | 0.011 | 0.015 | 0.181 | 4,387 |
| tracking | 0.003 | 0.003 | 0.004 | 0.010 | 4,387 |
| camera.read | 0.001 | 0.001 | 0.002 | 0.007 | 4,387 |

The non-pacing pipeline p95 is approximately 3.55 ms when summing the non-sleep stages. ArUco detection dominates the measured stage timing.

## Evaluation Statement

MetriPlane's current public timing artifact supports the claim that two-camera planar fiducial tracking has sub-2 ms per-camera detection p95 and sub-0.2 ms fusion p95 in the measured setup. This is a stage-timing claim, not an end-to-end client-display latency claim.

## Regeneration Command

```bash
./tools/mp.sh timing-breakdown
```
