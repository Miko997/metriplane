# MetriPlane System Reliability Summary

**Purpose**: Determinism, backpressure, and provenance evidence for Paper B
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical evidence**: [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md)

## Deterministic Replay

**Evidence**: `evidence/experiments/replay_determinism.csv`

| Metric | Value |
|---|---:|
| Frames compared | 302 |
| Object pairs compared | 906 |
| Mean positional difference | 0.0 cm |
| Max positional difference | 0.0 cm |
| Event mismatches | 0 |
| Pass | true |

This supports the Paper B claim that deterministic replay reproduced the compared frame/object/event outputs exactly for the public replay artifact.

## Backpressure

**Evidence**: `evidence/experiments/backpressure_summary.csv`

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

This supports the claim that bounded queues and `KEEP_LATEST` behavior prevent unbounded backlog growth under a 120 Hz synthetic overload run.

## Provenance

Evidence rows are recorded in `evidence/manifest.csv`, with checksums in `evidence/CHECKSUMS.sha256`. Some raw evidence metadata preserves pre-public git descriptions for provenance; the Paper B canonical source release is `v0.1.2`; `v0.1.1` was the prior canonical evidence release; `v0.1.0` was the initial public release.

## Health Monitoring Boundary

Health monitoring code and tests exist, but full multi-camera degradation evidence remains hardware-constrained in this checkout. It should not be elevated into a primary Paper B quantitative benchmark claim unless a current public artifact is added.

## Regeneration Commands

```bash
./tools/mp.sh deterministic-replay
./tools/mp.sh backpressure
./tools/mp.sh provenance
sha256sum -c evidence/CHECKSUMS.sha256
```
