# Trace Store — Phase 02 Evidence

- phase: 02
- feature: trace_store
- module: metriplane/trace/store.py
- command: `metriplane traces summarize --session <session.jsonl>`
- output_format: `<object_id>  dur=<s>s  dist=<m>m  zones=<zones>  gaps=<n>`
- command: `metriplane traces export --session <session.jsonl> --out traces.csv`
- command: `metriplane traces object cart_01 --session <session.jsonl> --objects configs/objects.example.yaml`
- tests: tests/test_trace_store.py
- limitations:
  - Post-processing only (not real-time)
  - Speed from vel_world when available; position-diff fallback not implemented (zero if vel_world absent)
  - Gap threshold hardcoded at 1.0s
  - Registry loading is naive YAML (full validation in Phase 01)
