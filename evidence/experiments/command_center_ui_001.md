# Command Center Dashboard — Phase 11 Evidence

- phase: 11
- feature: command_center_dashboard
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- backend: metriplane/runner/command_center_api.py
- frontend: web/dashboard/command_center.{html,js,css}
- demo data: evidence/experiments/command_center/command_center_data.json

## Commands run

```bash
python -m pytest tests/test_operator_command_center_api.py -q

metriplane command-center export evidence/incidents/INC-DIST-001 \
  --out web/dashboard/command_center_data.json
python -m http.server 8088 --directory web/dashboard
# open http://localhost:8088/command_center.html
```

## Result (live summary for INC-DIST-001)

```json
{
  "run_id": "INC-DIST-001",
  "objects_count": 2,
  "alerts_count": 1,
  "open_incidents_count": 0,
  "incidents_count": 1,
  "health": {"overall": "OK"}
}
```

The exported `command_center_data.json` contains 2 objects (`cart_01`, `human_proxy_01`),
1 incident (`cart_person_distance`), 1 alert, and 2 trace summaries. The static page renders
the header summary, a 2D SVG map with type-colored object dots, and object/incident/trace
tables.

## Tests

- tests/test_operator_command_center_api.py (10): objects/incidents/traces/events readers,
  filtered traces, live summary, missing-artifact empty handling, CLI export + summary.

## Note on screenshots

A static HTML+SVG page is included and renders from the committed demo JSON. Screenshots
are a manual capture step; the API + data export that feed the page are what this evidence
covers and are fully tested.

## Live operator endpoints (added for low-code usability)

Read-only `/operator/*` endpoints expose the Sentinel views to the browser so a
non-technical operator never needs the CLI:

- `GET /operator/live-summary | objects | incidents | traces | camera-trust`
- `POST /operator/ask` (grounded assistant, no external LLM)

Verified live over HTTP against a real run:

```text
GET  /operator/live-summary -> run_id=sentinel_demo objects_count=1 incidents_count=1 health=OK
GET  /operator/incidents    -> [no_asset_in_exit_lane]
POST /operator/ask {"question":"what incident happened?"} -> incident_search | 1 incident(s) found.
```

A Sentinel run now writes a self-describing run dir (`session.jsonl`, `incident.json`,
`alerts.jsonl`, `objects.yaml`, `sentinel_summary.json`). The dashboard auto-refreshes the
latest run; a one-click allowlisted "Run Sentinel Demo" command populates it.

- frontend: web/dashboard/command_center_live.html + command_center_live.js
- tests: tests/test_operator_command_center_endpoints.py (10) — endpoints + path-traversal rejection

## Limitations

- Read-only over the latest run/bundle artifacts (no live WebSocket streaming yet).
- Only known run directories are read (under ~/metriplane-runs or repo evidence/); path
  traversal is rejected.
