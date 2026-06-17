# Operational Event Schema — Phase 03 Evidence

- phase: 03
- feature: event_schema
- modules: metriplane/sentinel/events.py, metriplane/sentinel/rules.py
- command: `metriplane rules validate configs/rules.example.yaml`
- expected: PASS: rules.yaml valid
- command: `metriplane rules list --config configs/rules.example.yaml`
- expected: four lines, one per rule
- tests: tests/test_sentinel_events.py
- forward_compatibility: RuleAlert and IncidentRecord are the data contract for Phase 04 (Rule Engine) and Phase 05 (Incident Engine)
- limitations: schema only — no evaluation logic in this phase
