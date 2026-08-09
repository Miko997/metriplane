# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import html
import json
from pathlib import Path

from metriplane.atlas.event_ledger import read_events
from metriplane.atlas.models import AtlasIncident


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dashboard_payload(
    run_dir: str | Path,
    *,
    displayed_run_dir: str | None = None,
) -> dict:
    run = Path(run_dir)
    manifest = _read_json(run / "atlas_manifest.json", {})
    metrics = _read_json(run / "metrics.json", {})
    actions = _read_json(run / "improvement_actions.json", [])
    events = [event.model_dump() for event in read_events(run / "physical_event_log.jsonl")]
    incidents = _read_jsonl(run / "incidents.jsonl")
    bundles = sorted(path.name for path in (run / "evidence_bundles").glob("*.zip"))
    regressions = sorted(path.name for path in (run / "regression_tests").glob("*.yaml"))
    training = sorted(path.name for path in (run / "training_cases").glob("*.md"))
    return {
        "schema_version": "metriplane.atlas.dashboard_payload.v1",
        "run_dir": displayed_run_dir if displayed_run_dir is not None else str(run),
        "manifest": manifest,
        "metrics": metrics,
        "events": events,
        "incidents": incidents,
        "bundles": bundles,
        "regressions": regressions,
        "training": training,
        "actions": actions,
        "limitations": [
            "Derived from replayed planar state.",
            "Tracks tagged assets, not people.",
            "Not a certified safety or quality decision system.",
        ],
    }


def build_dashboard(run_dir: str | Path, out_html: str | Path | None = None) -> Path:
    run = Path(run_dir)
    out = Path(out_html) if out_html else run / "atlas_dashboard.html"
    payload = dashboard_payload(run, displayed_run_dir=".")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_dashboard_html(payload), encoding="utf-8")
    return out


def render_dashboard_html(payload: dict) -> str:
    manifest = payload.get("manifest", {})
    metrics = payload.get("metrics", {})
    events = payload.get("events", [])
    incidents = payload.get("incidents", [])
    bundles = payload.get("bundles", [])
    regressions = payload.get("regressions", [])
    training = payload.get("training", [])
    actions = payload.get("actions", [])
    run_id = html.escape(str(manifest.get("run_id", "unknown")))
    cell_id = html.escape(str(manifest.get("cell_id", "unknown")))
    cards = [
        ("Recorded events", str(len(events))),
        ("Flagged incidents", str(len(incidents))),
        ("Observed duration", f"{metrics.get('observed_duration_s', 0)} s"),
        ("Evidence bundles", str(len(bundles))),
    ]
    card_html = "\n".join(
        f"<section class='metric'><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></section>"
        for label, value in cards
    )
    event_rows = "\n".join(
        "<tr>"
        f"<td>{event.get('ts', '')}</td>"
        f"<td>{html.escape(str(event.get('event_type', '')))}</td>"
        f"<td>{html.escape(str(event.get('asset_id') or '-'))}</td>"
        f"<td>{html.escape(str(event.get('message', '')))}</td>"
        "</tr>"
        for event in events
    )
    incident_cards = "\n".join(
        "<article class='incident'>"
        f"<h3>{html.escape(str(item.get('incident_id', 'incident')))}: {html.escape(str(item.get('title', '')))}</h3>"
        f"<p>{html.escape(str(item.get('summary', '')))}</p>"
        f"<code>{html.escape(', '.join(item.get('event_ids', [])))}</code>"
        "</article>"
        for item in incidents
    ) or "<p>No incidents generated.</p>"
    buttons = [
        ("Open incident report", "cell_truth_report.html"),
        ("Open evidence bundle", f"evidence_bundles/{bundles[0]}" if bundles else "#"),
        ("Open repeatable check", f"regression_tests/{regressions[0]}" if regressions else "#"),
        ("Open review note", f"training_cases/{training[0]}" if training else "#"),
    ]
    button_html = "\n".join(
        f"<a class='button' href='{html.escape(href)}'>{html.escape(label)}</a>"
        for label, href in buttons
    )
    action_html = "\n".join(
        f"<li>{html.escape(str(action.get('title', 'Action')))}: {html.escape(str(action.get('rationale', '')))}</li>"
        for action in actions
    ) or "<li>No improvement actions generated.</li>"
    payload_json = html.escape(json.dumps(payload, sort_keys=True))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Metriplane Incident Review</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; background: #080b0e; color: #eef4f6; font: 14px/1.5 Inter, system-ui, sans-serif; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header {{ border-bottom: 1px solid #24313a; padding-bottom: 18px; margin-bottom: 22px; }}
    h1 {{ margin: 0 0 6px; font-size: 28px; }}
    h2 {{ margin-top: 28px; font-size: 18px; color: #dfeef1; }}
    .sub {{ color: #9fb3bb; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .metric, .incident {{ border: 1px solid #24313a; background: #0f151a; border-radius: 6px; padding: 14px; }}
    .metric span {{ color: #9fb3bb; display: block; }}
    .metric strong {{ font-size: 22px; }}
    table {{ width: 100%; border-collapse: collapse; background: #0f151a; border: 1px solid #24313a; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid #22303a; text-align: left; vertical-align: top; }}
    th {{ color: #9fd8d2; font-weight: 700; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 24px; }}
    .button {{ color: #061014; background: #72d8cf; border-radius: 5px; padding: 9px 12px; text-decoration: none; font-weight: 700; }}
    code {{ color: #9fd8d2; }}
    @media (max-width: 760px) {{ .metrics {{ grid-template-columns: 1fr 1fr; }} main {{ padding: 18px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Incident Review</h1>
    <div class="sub">Recorded run {run_id} / workspace {cell_id}. A recorded run is a saved
      sequence of object positions and timestamps. Results are replay-derived and observe-only.</div>
  </header>
  <nav class="actions">{button_html}</nav>
  <section class="metrics">{card_html}</section>
  <h2>What happened</h2>
  <p>This recorded run produced {len(events)} events and {len(incidents)} flagged
    incidents. An event is one observed change; an incident groups related events
    that need review.</p>
  <h2>Why it was flagged</h2>
  <p>An incident groups related events because an expected process rule was not met.
    Process rules describe expected steps, objects, locations, and waiting times.</p>
  {incident_cards}
  <h3>Suggested follow-up</h3>
  <ul>{action_html}</ul>
  <h2>When it happened</h2>
  <p>The table keeps each timestamp, technical event type, object, and message available
    for detailed review.</p>
  <table>
    <thead><tr><th>time</th><th>event</th><th>asset</th><th>message</th></tr></thead>
    <tbody>{event_rows}</tbody>
  </table>
  <h2>Evidence that was saved</h2>
  <p>An evidence bundle is a checksummed ZIP that keeps the incident and supporting
    records together. Use the links above to open the report or verify the bundle.</p>
  <h2>Repeatable check that was generated</h2>
  <p>A regression check deterministically replays the saved inputs and checks that the
    expected incident is still detected. Deterministic replay makes software results
    comparable; it does not prove that the original measurements were physically accurate.</p>
  <h2>Limits of this result</h2>
  <ul>
    <li>Derived from calibrated planar state streams.</li>
    <li>Depends on tracked/tagged assets.</li>
    <li>Not a certified safety or quality decision system.</li>
  </ul>
  <script type="application/json" id="atlas-dashboard-payload">{payload_json}</script>
</main>
</body>
</html>
"""


def incident_from_payload(payload: dict, incident_id: str) -> AtlasIncident | None:
    for item in payload.get("incidents", []):
        if item.get("incident_id") == incident_id:
            return AtlasIncident.model_validate(item)
    return None
