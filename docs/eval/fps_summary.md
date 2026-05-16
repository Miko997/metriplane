# MetriPlane Update-Rate Note

**Purpose**: clarify update-rate evidence relative to the current Paper B campaign
**Paper B canonical release tag**: [`v0.1.2`](https://github.com/Miko997/metriplane/releases/tag/v0.1.2)
**Initial public release**: [`v0.1.0`](https://github.com/Miko997/metriplane/releases/tag/v0.1.0)
**Canonical timing artifact**: `evidence/experiments/latency_summary.csv`

Paper B uses the current public timing CSV as the canonical latency/update-rate artifact. The current CSV records 4,387 stage-timing samples with:

| Stage | p95 ms |
|---|---:|
| detect.cam0 | 1.242 |
| detect.cam1 | 1.684 |
| fuse | 0.184 |
| build.msg | 0.185 |
| record.jsonl | 0.153 |
| zones | 0.030 |
| map.cam0 | 0.028 |
| map.cam1 | 0.026 |
| ws.send | 0.015 |
| tracking | 0.004 |
| camera.read | 0.002 |

The non-pacing pipeline p95 is approximately 3.55 ms when summing non-sleep stages. Do not cite older frame-count or FPS values as Paper B canonical unless the corresponding archived artifact is explicitly cited as historical.

See [`latency_summary.md`](latency_summary.md) and [`CANONICAL_EVIDENCE.md`](CANONICAL_EVIDENCE.md).
