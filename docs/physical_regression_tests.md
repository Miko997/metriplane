<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Physical Regression Tests

Metriplane can turn a real-world physical incident into a **replayable regression test**.
An incident evidence bundle plus an `expected.yaml` becomes a CI-compatible check that
answers:

- Does the current code still detect this incident?
- Do the current rules still detect it?
- Did the incident/event counts change unexpectedly?
- Is replay still deterministic?
- Did evaluation latency regress?

## Workflow

1. Export an incident evidence bundle (Phase 06):
   ```bash
   metriplane incidents bundle <id> --session s.jsonl \
     --rules configs/rules.example.yaml --objects configs/objects.example.yaml \
     --out evidence/incidents/INC-0001
   ```
2. Add an `expected.yaml` describing what the bundle should reproduce.
3. Run the test:
   ```bash
   metriplane test evidence/incidents/INC-0001
   ```

## expected.yaml

```yaml
schema_version: "1.0"
expected:
  incidents:
    - type: forbidden_zone_entry
      rule_id: no_cart_in_exit_lane
      min_count: 1
      object_ids_any_order: [cart_01]
      zones: [exit_lane]
      severity_at_least: warning
  events:
    - rule_id: no_cart_in_exit_lane
      min_count: 1
  replay:
    deterministic_hash_match: true
  latency:
    p95_update_ms_max: 50
```

## Output

```text
Physical regression test: INC-0001
  PASS checksums: ok
  PASS replay.deterministic_hash_match: 331fa2168a2d8151
  PASS incident[forbidden_zone_entry/no_cart_in_exit_lane]: matched 1 (expected >=1)
  PASS event[no_cart_in_exit_lane]: matched 3 (expected >=1)
  PASS latency.p95_update_ms: 0.021ms (max 50.0ms)
Result: PASS
```

Exit code is 0 on PASS, 1 on FAIL — suitable for CI.

## Strict vs non-strict

By default, extra incidents/events beyond what's expected are tolerated. Use
`--strict-extra-incidents` / `--strict-extra-events` to fail when unexpected violations
appear. Use `--skip-checksums` to evaluate a bundle whose non-evaluated files changed.

## Limitations

- The runner evaluates offline (no camera/WebSocket); it replays `session_excerpt.jsonl`
  through the rule + incident engines.
- Incident matching enforces the expected `type` by resolving the incident's rule type,
  then checks any requested rule ID, severity, objects, and zones.
- Bundles are treated as data — no code in a bundle is executed.
