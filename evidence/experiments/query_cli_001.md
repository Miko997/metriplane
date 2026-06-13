# Query CLI — Phase 07 Evidence

- phase: 07
- feature: query_cli
- module: metriplane/sentinel/cli_query.py
- commands:
  - `metriplane query incidents --incidents incidents.json [--severity ...] [--rule ...] [--object ...] [--zone ...]`
  - `metriplane query alerts --alerts alerts.jsonl [--severity ...] [--rule ...] [--object ...] [--zone ...]`
  - `metriplane query traces --session <session.jsonl> [--objects objects.yaml] [--object ...] [--zone ...]`
- output: filtered rows plus a trailing `# <n> of <total> matched` count line
- tests: tests/test_query_cli.py (13 tests: rules run, incidents run/list/show, severity/object/rule/zone filters across incidents/alerts/traces, end-to-end bundle + verify)
- limitations:
  - Read-only over existing artifacts (incidents.json, alerts.jsonl, session JSONL)
  - Filters are AND-combined exact matches
