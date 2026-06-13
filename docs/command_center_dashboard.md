# Command Center Dashboard

A read-only command center that shows physical observability for a run at a glance: live
object map, object table, incidents, and trace summaries. It communicates the project in
~30 seconds.

## Data model

The dashboard is a static page that loads one JSON file produced from a run dir or incident
bundle:

```bash
metriplane command-center export evidence/incidents/INC-DIST-001 \
  --out web/dashboard/command_center_data.json
```

This bundles `summary`, `objects`, `incidents`, `events`, and `traces`. The readers are
pure functions in `metriplane/runner/command_center_api.py` and degrade to empty lists when
artifacts are missing (never 500).

## View it

```bash
metriplane command-center export <run-or-bundle> --out web/dashboard/command_center_data.json
python -m http.server 8088 --directory web/dashboard
# open http://localhost:8088/command_center.html
```

Point at a different data file with `?data=...`:
`command_center.html?data=my_run.json`.

## Panels

| Panel | Content |
|---|---|
| Header | run id, object count, alert count, open incidents, health |
| Live map | 2D SVG plane, object dots colored by type, labeled by name |
| Objects | name, type, zone, x, y, speed |
| Incidents | id, rule, severity, status, summary |
| Traces | object, duration, distance, zones visited, gaps |

## API readers

| Function | Returns |
|---|---|
| `get_live_summary(run_dir)` | counts + health |
| `get_objects(run_dir)` | latest frame object states (resolved names) |
| `get_incidents(run_dir)` | incident records |
| `get_events(run_dir)` | alerts |
| `get_traces(run_dir, object_id=None)` | trace summaries |

## Live mode (no CLI needed for an operator)

`command_center_live.html` talks to the runner's read-only `/operator/*` endpoints and
auto-refreshes the **latest run** under `~/metriplane-runs` every 5 s — including an
"Ask the operator assistant" box. A non-technical operator never touches the CLI:

```bash
# 1) start the runner (serves the read-only endpoints, localhost only)
python -m metriplane.runner.service --port 9000
# 2) serve the dashboard
python -m http.server 8088 --directory web/dashboard
# 3) open http://localhost:8088/command_center_live.html
```

To populate a run, click **"Run Sentinel Demo"** in the operator dashboard (an allowlisted
one-click command) or run `metriplane sentinel run ... --runs-dir ~/metriplane-runs`. A
Sentinel run now writes a self-describing run dir (`session.jsonl`, `incident.json`,
`alerts.jsonl`, `objects.yaml`, `sentinel_summary.json`) that the dashboard reads directly.

### Read-only operator endpoints

| Endpoint | Returns |
|---|---|
| `GET /operator/live-summary` | counts + health for the latest run |
| `GET /operator/objects` | latest-frame object states |
| `GET /operator/incidents` | incident records |
| `GET /operator/traces` | trace summaries |
| `GET /operator/camera-trust` | camera trust report (if present) |
| `POST /operator/ask` | grounded assistant answer + citations |

GET endpoints auto-resolve the latest run; POST endpoints accept an optional `run_dir`
(validated to live under `~/metriplane-runs` or the repo `evidence/` tree — path traversal
is rejected). The assistant uses **no external LLM**.

## Status

The static page (`command_center.html`) reads an exported JSON snapshot; the live page
(`command_center_live.html`) reads the runner endpoints. Both are **read-only**. Only known
run directories are read; no arbitrary file access. Live WebSocket streaming into the map
is still future work.
