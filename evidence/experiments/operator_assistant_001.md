# Grounded Operator Assistant — Phase 23 Evidence

- phase: 23
- feature: grounded_operator_assistant
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/assistant/
- demo run dir: evidence/experiments/assistant_demo (INC-DIST-001 artifacts + camera_trust.json)

## Commands run

```bash
python -m pytest tests/test_assistant_intents.py tests/test_assistant_retrieval.py \
  tests/test_assistant_answer.py tests/test_assistant_citations.py -q

metriplane ask --run-dir evidence/experiments/assistant_demo "what incident happened?"
metriplane ask --run-dir evidence/experiments/assistant_demo "where did cart_01 go?"
metriplane ask --run-dir evidence/experiments/assistant_demo "was the exit lane blocked?"
metriplane ask --run-dir evidence/experiments/assistant_demo "which rule triggered this incident?"
metriplane ask --run-dir evidence/experiments/assistant_demo "which camera was unreliable?"
```

## Result

- questions_tested: 5
- answers_with_citations: 5
- external_llm_used: false
- pass: true (all 5 intents recognized and answered with citations)

| question | intent | citations |
|---|---|---|
| what incident happened? | incident_search | 1 |
| where did cart_01 go? | object_history | 1 |
| was the exit lane blocked? | zone_occupancy | 2 |
| which rule triggered this incident? | rule_explanation | 1 |
| which camera was unreliable? | camera_health | 1 |

## Tests

- tests/test_assistant_intents.py (7)
- tests/test_assistant_retrieval.py (7)
- tests/test_assistant_answer.py (8): includes "no invented incident when absent" and
  "missing data reports limitation".
- tests/test_assistant_citations.py (6): source path present, paths inside root, traversal
  rejected.

## Limitations

- Deterministic keyword intent classification; no external LLM (by design).
- Answers reflect artifact contents; missing artifacts are surfaced as limitations.
- Citation paths are validated to stay inside the run/bundle root.
