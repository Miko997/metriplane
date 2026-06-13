# Trace Store

The trace store turns frame-by-frame object observations into compact physical
summaries for incidents, reports, and operator questions.

## Summaries

For each observed object, the store tracks:

- first and last timestamp,
- last known world position,
- total distance traveled,
- approximate speed,
- dwell by zone,
- idle time,
- and last-seen health.

Trace summaries are derived from replay or live frame state. They do not modify
the underlying session JSONL.

## CLI

```bash
metriplane traces summarize --session <session.jsonl>
metriplane traces object cart_01 --session <session.jsonl>
```

## Related files

- `metriplane/trace/store.py`
- `metriplane/trace/cli_traces.py`
- `tests/test_trace_store.py`
- `evidence/experiments/trace_store_001.md`
