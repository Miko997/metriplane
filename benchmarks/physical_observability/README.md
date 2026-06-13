# Metriplane-Bench — Physical Observability Benchmark

A reproducible benchmark suite for low-cost physical observability. Each scenario is a
small, deterministic replay session plus an object registry, rules, and expected
alerts/incidents. The runner re-evaluates each scenario and scores it.

## Tasks measured

| Task | Metric |
|---|---|
| Replay determinism | incident fingerprint hash equality across two runs |
| Rule alerts | precision / recall / F1 (by rule id) |
| Incidents | precision / recall / F1 (by rule id) |
| Latency | p50 / p95 / p99 per-frame evaluation time |

## Run

```bash
python benchmarks/physical_observability/run_bench.py --scenario all \
  --out evidence/experiments/physical_observability_bench_001.csv \
  --report evidence/experiments/physical_observability_bench_001.md
```

Run a single scenario with `--scenario blocked_path_001`. Exit code is 0 if every check
passes, 1 otherwise.

## Scenarios

| Scenario | What it exercises | Expected |
|---|---|---|
| `blocked_path_001` | pallet dwells in exit lane > 5 s | `pallet_blocks_exit` |
| `restricted_zone_001` | cart briefly enters restricted exit lane | `no_cart_in_exit_lane` |
| `unsafe_proximity_001` | cart and human proxy within 0.6 m | `cart_person_distance` |

## Scenario format

```text
scenarios/<id>/
  scenario.yaml          # id, description, expected summary
  input_session.jsonl    # deterministic replay frames
  object_registry.yaml   # marker -> named asset
  rules.yaml             # rules evaluated (all rules, to test precision)
  expected_alerts.json   # rule_ids that should fire
  expected_incidents.json
```

Each scenario includes the full rule set so the benchmark also measures **precision**
(no spurious alerts), not just recall.

## Adding a scenario

Create a new folder under `scenarios/` with the files above. The runner discovers any
folder containing `input_session.jsonl`. Keep sessions small and deterministic.

## Honesty

These are **synthetic** scenarios for regression and reproducibility, clearly separated
from real-world case studies. They validate the detection pipeline end to end, not
real-world accuracy.
