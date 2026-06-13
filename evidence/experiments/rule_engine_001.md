# Rule Engine — Phase 04 Evidence

- phase: 04
- feature: rule_engine
- module: metriplane/sentinel/engine.py
- rule_types: forbidden_zone, max_dwell, min_distance, speed_limit, missing_object, restricted_transition
- command: `metriplane rules run --session <session.jsonl> --rules configs/rules.example.yaml --objects configs/objects.example.yaml`
- output: one RuleAlert line per violation per frame: `<ts>  <rule_id>  <severity>  [<objects>]  zone=<zone>`
- determinism: alert IDs are sequential (`alert_000001`, ...) and identical across repeated replays
- tests: tests/test_rule_engine.py (13 tests; one per rule type plus determinism, run_id capture, marker fallback)
- limitations:
  - Speed uses vel_world when present; otherwise position-diff over consecutive frames
  - min_distance compares only objects present in the same frame
  - Alerts are per-frame; grouping into incidents is Phase 05
