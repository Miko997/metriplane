# MetriPlane Benchmark Summary

**Purpose**: Paper B benchmark evidence summary
**Paper B canonical release tag**: [`v0.1.1`](https://github.com/Miko997/metriplane/releases/tag/v0.1.1)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

This summary reflects the current public evidence campaign. Historical pre-public git descriptions may remain inside raw evidence metadata for provenance, but Paper B claims use the values below.

## Canonical Benchmark Results

| Benchmark | Status | Key result | Evidence |
|---|---|---:|---|
| Deterministic replay | PASS | 302 frames; 906 object pairs; 0.0 cm mean/max positional difference; 0 event mismatches | `evidence/experiments/replay_determinism.csv` |
| Backpressure | PASS | 120 Hz synthetic input; queue_max=5; 3,600 generated; 995 published; 2,605 dropped; p95 latency 69.830 ms | `evidence/experiments/backpressure_summary.csv` |
| Latency breakdown | PASS | 4,387 samples; detect.cam0 p95 1.242 ms; detect.cam1 p95 1.684 ms; fuse p95 0.184 ms; non-pacing pipeline p95 approx. 3.55 ms | `evidence/experiments/latency_summary.csv` |
| Mapping error | PASS | 0.63 cm mean; 1.07 cm max; N=9 grid points | `evidence/experiments/mapping_error_001.csv` |
| Static fiducial continuity | PASS | IDs 4, 7, and 12: 100.0% coverage over 4,387 frames; 0 missing gaps | `evidence/experiments/id_stability_001.csv` |
| Motion fiducial continuity | PASS | 88,475 frames; primary-marker coverage 98.39-99.25%; max gap 533 frames | `evidence/experiments/id_stability_movement_001.csv` |
| Fusion jitter | PASS | 0.067-0.080 mm jitter std; 100.0% coverage; absolute fused accuracy not measured | `evidence/experiments/fusion_jitter_001.csv` |
| CPU/GPU equivalence | PASS | 13,161 samples; 0.0 cm RMSE diff; 0.0 cm max diff; `cpu_numpy` vs `gpu_cupy` | `evidence/experiments/compute_equivalence_001.csv` |
| CPU/GPU fusion performance | PASS | GPU backend is correct but slower than CPU for tested N=1-1000 fusion-compute workloads | `evidence/experiments/gpu_benchmark_001.csv` |
| Zone analytics | PASS | Four zones (`bl`, `br`, `tl`, `tr`); 877.85 object-seconds dwell; 112 transitions | `evidence/experiments/case_study_1_movement_zone_*.csv` |

## Latency Breakdown

| Stage | Mean ms | p50 ms | p95 ms | Max ms | Count |
|---|---:|---:|---:|---:|---:|
| detect.cam1 | 1.360 | 1.319 | 1.684 | 5.290 | 4,387 |
| detect.cam0 | 0.957 | 0.901 | 1.242 | 11.417 | 4,387 |
| build.msg | 0.161 | 0.160 | 0.185 | 0.520 | 4,387 |
| fuse | 0.150 | 0.150 | 0.184 | 0.352 | 4,387 |
| record.jsonl | 0.133 | 0.134 | 0.153 | 0.348 | 4,387 |
| zones | 0.025 | 0.025 | 0.030 | 0.070 | 4,387 |
| map.cam0 | 0.025 | 0.025 | 0.028 | 0.074 | 4,387 |
| map.cam1 | 0.022 | 0.022 | 0.026 | 0.060 | 4,387 |
| ws.send | 0.013 | 0.011 | 0.015 | 0.181 | 4,387 |
| tracking | 0.003 | 0.003 | 0.004 | 0.010 | 4,387 |
| camera.read | 0.001 | 0.001 | 0.002 | 0.007 | 4,387 |

Non-pacing pipeline p95 is approximately 3.55 ms when summing the stages above and excluding `sleep`.

## Backpressure

| Metric | Value |
|---|---:|
| Duration | 30.0 s |
| Input rate | 120.0 Hz |
| Simulated detection time | 30.0 ms |
| Queue max | 5 |
| Policy | KEEP_LATEST |
| Frames generated | 3,600 |
| Frames accepted | 3,600 |
| Dropped | 2,605 |
| Detect processed | 995 |
| Published | 995 |
| Max queue depth | 5 |
| Mean latency | 50.891 ms |
| p50 latency | 50.873 ms |
| p95 latency | 69.830 ms |
| Pass | true |

## Fusion Jitter

| Object ID | Frames seen | Total frames | Coverage | Jitter std |
|---:|---:|---:|---:|---:|
| 4 | 4,387 | 4,387 | 100.0% | 0.067 mm |
| 7 | 4,387 | 4,387 | 100.0% | 0.080 mm |
| 12 | 4,387 | 4,387 | 100.0% | 0.075 mm |

`max_error_m` is `NaN` in this artifact, so the result supports jitter/stability only, not absolute fused accuracy.

## CPU/GPU Performance

| N objects | CPU p50 ms | CPU p95 ms | GPU p50 ms | GPU p95 ms | Relation |
|---:|---:|---:|---:|---:|---|
| 1 | 0.005631 | 0.006708 | 0.322591 | 0.478844 | GPU slower |
| 10 | 0.024406 | 0.026089 | 0.343555 | 0.491760 | GPU slower |
| 50 | 0.109910 | 0.120303 | 0.432770 | 0.564343 | GPU slower |
| 200 | 0.437469 | 0.447466 | 0.773220 | 1.148387 | GPU slower |
| 1000 | 2.225280 | 2.270170 | 2.574817 | 2.728293 | GPU slower |

This benchmark covers fusion compute only. CPU remains the default backend for current workloads; GPU remains optional for larger future batched workloads.

## Regeneration Commands

```bash
./tools/mp.sh deterministic-replay
./tools/mp.sh backpressure
./tools/mp.sh timing-breakdown
python benchmarks/run_mapping_error.py --help
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_001.csv
python tools/analyze_id_stability_jsonl.py <session.jsonl> --out evidence/experiments/id_stability_movement_001.csv
python benchmarks/run_fusion_jitter.py <session.jsonl> --out evidence/experiments/fusion_jitter_001.csv
python benchmarks/run_compute_equivalence.py --session-jsonl <session.jsonl> --out-csv evidence/experiments/compute_equivalence_001.csv --method weighted --require-gpu
./tools/mp.sh gpu-benchmark
python tools/zones_report_jsonl.py <session.jsonl> --out evidence/experiments --prefix case_study_1_movement
```
