# Metriplane-Bench — Physical Observability

Scenarios: 3 | Checks: 24 | Passed: 24

| scenario | task | metric | value | result | notes |
|---|---|---|---|---|---|
| blocked_path_001 | replay_determinism | hash_match | True | PASS | 10c653123a0bd1b6 |
| blocked_path_001 | rule_alerts | precision | 1.0 | PASS | fp=0 |
| blocked_path_001 | rule_alerts | recall | 1.0 | PASS | fn=0 |
| blocked_path_001 | rule_alerts | f1 | 1.0 | PASS | observed=['pallet_blocks_exit'] |
| blocked_path_001 | incidents | precision | 1.0 | PASS | fp=0 |
| blocked_path_001 | incidents | recall | 1.0 | PASS | fn=0 |
| blocked_path_001 | incidents | f1 | 1.0 | PASS | count=1 |
| blocked_path_001 | latency | p50_ms | 0.009989 | PASS | p95=0.02091 p99=0.02091 |
| restricted_zone_001 | replay_determinism | hash_match | True | PASS | 331fa2168a2d8151 |
| restricted_zone_001 | rule_alerts | precision | 1.0 | PASS | fp=0 |
| restricted_zone_001 | rule_alerts | recall | 1.0 | PASS | fn=0 |
| restricted_zone_001 | rule_alerts | f1 | 1.0 | PASS | observed=['no_cart_in_exit_lane'] |
| restricted_zone_001 | incidents | precision | 1.0 | PASS | fp=0 |
| restricted_zone_001 | incidents | recall | 1.0 | PASS | fn=0 |
| restricted_zone_001 | incidents | f1 | 1.0 | PASS | count=1 |
| restricted_zone_001 | latency | p50_ms | 0.009147 | PASS | p95=0.0158 p99=0.0158 |
| unsafe_proximity_001 | replay_determinism | hash_match | True | PASS | 98fe9f6777df04a8 |
| unsafe_proximity_001 | rule_alerts | precision | 1.0 | PASS | fp=0 |
| unsafe_proximity_001 | rule_alerts | recall | 1.0 | PASS | fn=0 |
| unsafe_proximity_001 | rule_alerts | f1 | 1.0 | PASS | observed=['cart_person_distance'] |
| unsafe_proximity_001 | incidents | precision | 1.0 | PASS | fp=0 |
| unsafe_proximity_001 | incidents | recall | 1.0 | PASS | fn=0 |
| unsafe_proximity_001 | incidents | f1 | 1.0 | PASS | count=1 |
| unsafe_proximity_001 | latency | p50_ms | 0.016271 | PASS | p95=0.016943 p99=0.016943 |

## Reproduce

```bash
python benchmarks/physical_observability/run_bench.py --scenario all \
  --out evidence/experiments/physical_observability_bench_001.csv \
  --report evidence/experiments/physical_observability_bench_001.md
```
