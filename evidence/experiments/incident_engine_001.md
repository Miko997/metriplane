# Incident Engine — Phase 05 Evidence

- phase: 05
- feature: incident_engine
- module: metriplane/sentinel/incidents.py
- behavior: groups RuleAlerts sharing (rule_id, object set, zone) into incidents; an open incident closes after a gap longer than `gap_close_s` (default 1.0s)
- command: `metriplane incidents run --session <session.jsonl> --rules configs/rules.example.yaml --objects configs/objects.example.yaml --out incidents.json`
- command: `metriplane incidents list --incidents incidents.json`
- command: `metriplane incidents show <incident_id> --incidents incidents.json`
- determinism: incident IDs are sequential (`inc_0001`, ...) and stable across replays; incidents ordered by open time
- severity: incident severity escalates to the most severe alert in the group
- tests: tests/test_incident_engine.py (10 tests: grouping, gap splitting, rule/object separation, escalation, determinism, summary text)
- limitations:
  - Grouping key is exact object-set match; partial overlaps form distinct incidents
  - gap_close_s is a fixed engine config, not per-rule
