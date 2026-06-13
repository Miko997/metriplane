# Spatial Contract Language — Phase 16 Evidence

- phase: 16
- feature: spatial_contract_language
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/contracts/
- config_path: configs/contracts/sentinel_demo.yaml
- contract_path: configs/contracts/sentinel_demo.yaml
- objects_file: configs/objects.example.yaml
- replay_input: tests/fixtures/contracts/sentinel_minimal_session.jsonl
- expect_file: tests/fixtures/contracts/sentinel_expected.yaml

## Commands run

```bash
python -m metriplane.contracts.cli validate configs/contracts/sentinel_demo.yaml
python -m metriplane.contracts.cli test \
  --contract configs/contracts/sentinel_demo.yaml \
  --input tests/fixtures/contracts/sentinel_minimal_session.jsonl \
  --expect tests/fixtures/contracts/sentinel_expected.yaml \
  --objects configs/objects.example.yaml \
  --output evidence/experiments/spatial_contract_language_001.json
```

## Result

```text
contract_id=sentinel_demo_warehouse schema=1.0 rules=4 result=PASS
expected_incidents=2 observed_incidents=2 false_positives=0 missed=0
```

- rules_count: 4
- expected_events (incidents): 2
- observed_events (incidents): 2
- false_positive_count: 0
- missed_count: 0
- pass: true

## Rule types implemented

forbidden_zone, minimum_distance (with min_duration + cooldown), zone_occupancy_duration,
speed_limit, missing_object, forbidden_direction, zone_capacity.

## Tests

- tests/test_contract_models.py (10)
- tests/test_contract_loader.py (6)
- tests/test_contract_engine.py (14)
- tests/test_contract_cli.py (5)

## Limitations

- Subject matching is criterion-AND / membership-OR; an empty subject matches nothing.
- Pairwise minimum_distance is O(n²) within matched subjects (acceptable for demo scale).
- forbidden_direction uses world-axis sign convention: left_to_right=+X, right_to_left=-X,
  bottom_to_top=+Y, top_to_bottom=-Y.
- No upstream perception/camera/mapping code was modified; the contract engine is a downstream layer.
- Contract YAML is configuration only: no eval, templating, or shell execution.
