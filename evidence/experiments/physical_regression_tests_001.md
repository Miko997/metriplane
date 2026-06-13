# Physical Regression Test Harness — Phase 20 Evidence

- phase: 20
- feature: physical_regression_tests
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/testing/
- bundle_path: evidence/incidents/INC-0001
- expected_file: evidence/incidents/INC-0001/expected.yaml

## Commands run

```bash
python -m pytest tests/test_physical_expected_models.py \
  tests/test_physical_compare.py tests/test_physical_regression_runner.py -q

metriplane test evidence/incidents/INC-0001 \
  --output evidence/experiments/physical_regression_tests_001.json
echo $?   # 0
```

## Result

```text
Physical regression test: INC-0001
  PASS checksums: ok
  PASS replay.deterministic_hash_match: 331fa2168a2d8151
  PASS incident[forbidden_zone_entry/no_cart_in_exit_lane]: matched 1 (expected >=1)
  PASS event[no_cart_in_exit_lane]: matched 3 (expected >=1)
  PASS latency.p95_update_ms: 0.021ms (max 50.0ms)
Result: PASS
```

- checks_run: 5
- checks_passed: 5
- checks_failed: 0
- output_hash: 331fa2168a2d81515f08f7fc6eaa8270e09f5d1e5fd38b7f1cbb37616e4599c6
- p95_update_ms: ~0.02

A controlled failure was also verified: replacing `expected.yaml` with a rule that does
not occur in the bundle yields `Result: FAIL` and exit code 1.

## What the harness checks

1. Bundle checksum integrity (CHECKSUMS.sha256).
2. Replay determinism (incident fingerprint identical across two evaluations).
3. Expected incidents (rule_id, severity_at_least, object set, zones, count range).
4. Expected events (alert counts by rule).
5. Latency budget (p95 per-frame evaluation time).

## Tests

- tests/test_physical_expected_models.py (6)
- tests/test_physical_compare.py (10)
- tests/test_physical_regression_runner.py (8)

## Limitations

- Offline evaluator uses the Phase 04 rule engine over the bundle's `session_excerpt.jsonl`
  with the bundled `rules.yaml` + `objects.yaml` (no camera/WebSocket services).
- Incident matching ignores the descriptive `type` label; it matches on rule_id, severity,
  objects, and zones.
- Latency is offline per-frame evaluation time, not live runtime latency.
- Bundles are treated as data; no code from a bundle is executed.
