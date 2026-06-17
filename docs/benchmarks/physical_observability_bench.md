<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Physical Observability Benchmark (Metriplane-Bench)

Metriplane-Bench is a reproducible suite that scores the physical-observability pipeline
on small deterministic scenarios. It is the public, regenerable proof that the
detection chain (rules → alerts → incidents) behaves correctly and deterministically.

## Reproduce

```bash
python benchmarks/physical_observability/run_bench.py --scenario all \
  --out evidence/experiments/physical_observability_bench_001.csv \
  --report evidence/experiments/physical_observability_bench_001.md
cat evidence/experiments/physical_observability_bench_001.md
```

## Output

CSV/Markdown rows of `scenario, task, metric, value, pass, notes`. On the reference run all
24 checks pass across three scenarios (`blocked_path_001`, `restricted_zone_001`,
`unsafe_proximity_001`).

## Tasks

- **Replay determinism** — the incident fingerprint must be identical across two
  evaluations of the same session.
- **Rule alerts / Incidents** — precision, recall, and F1 against the expected rule-id
  sets. Each scenario ships the full rule set, so precision catches spurious alerts.
- **Latency** — p50/p95/p99 per-frame evaluation time (offline).

See [`benchmarks/physical_observability/README.md`](../../benchmarks/physical_observability/README.md)
for the scenario format and how to add new scenarios.

## Limitations

- Synthetic scenarios — separated from real-world case studies on purpose.
- Latency is offline per-frame rule evaluation, not live runtime latency.
- Accuracy/localization tasks (mean/max position error) are reserved for camera-based
  case studies, not these synthetic replays.
