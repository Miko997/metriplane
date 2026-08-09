# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import html
from pathlib import Path

from metriplane.atlas.models import (
    AtlasDeviation,
    AtlasEvent,
    AtlasIncident,
    AtlasRunManifest,
    FlowMetrics,
    ImprovementAction,
)


def _render_inline(text: str) -> str:
    parts = text.split("`")
    rendered: list[str] = []
    for idx, part in enumerate(parts):
        escaped = html.escape(part)
        if idx % 2:
            rendered.append(f"<code>{escaped}</code>")
        else:
            rendered.append(escaped)
    return "".join(rendered)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_divider(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(set(cell.replace(":", "").replace("-", "")) <= {""} for cell in cells)


def _render_table(lines: list[str]) -> str:
    header = _split_table_row(lines[0])
    rows = lines[2:] if len(lines) > 1 and _is_table_divider(lines[1]) else lines[1:]
    thead = "".join(f"<th>{_render_inline(cell)}</th>" for cell in header)
    body_rows = []
    for row in rows:
        cells = _split_table_row(row)
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        elif len(cells) > len(header):
            cells = cells[:len(header) - 1] + [" | ".join(cells[len(header) - 1:])]
        body_rows.append("<tr>" + "".join(f"<td>{_render_inline(cell)}</td>" for cell in cells) + "</tr>")
    return (
        '<div class="report-table-wrap"><table class="report-table">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def _fmt_s(value: float) -> str:
    return f"{value:.1f} s"


def render_markdown(
    manifest: AtlasRunManifest,
    events: list[AtlasEvent],
    deviations: list[AtlasDeviation],
    incidents: list[AtlasIncident],
    metrics: FlowMetrics,
    actions: list[ImprovementAction],
) -> str:
    lines: list[str] = [
        "# Cell Truth Report",
        "",
        "## Executive summary",
        "",
        f"- Observed duration: {_fmt_s(metrics.observed_duration_s)}.",
        f"- Physical events recorded: {len(events)}.",
        f"- Process deviations detected: {len(deviations)}.",
        f"- Incidents generated: {len(incidents)}.",
        f"- Evidence bundles generated: {len(incidents)}.",
        "- This report is derived from replayed planar state, not raw video judgement.",
        "",
        "## Timeline",
        "",
    ]
    for event in events:
        lines.append(f"- {event.ts:0.1f}: {event.message} (`{event.event_id}`)")
    if not events:
        lines.append("- No Atlas events were emitted.")

    lines.extend(["", "## Time loss table", "", "| issue | asset | station/zone | duration | evidence |", "|---|---|---|---:|---|"])
    delayed = [event for event in events if event.event_type == "step_delayed"]
    if delayed:
        for event in delayed:
            lines.append(
                f"| {event.message} | {event.asset_id or '-'} | "
                f"{event.station_id or event.zone_id or '-'} | {event.value or 0} s | "
                f"{', '.join(event.evidence)} |"
            )
    else:
        lines.append("| No time loss detected | - | - | 0 s | - |")

    lines.extend(["", "## Deviations", "", "| deviation | severity | process step | assets | evidence |", "|---|---|---|---|---|"])
    for deviation in deviations:
        lines.append(
            f"| {deviation.type} | {deviation.severity} | {deviation.process_step_id or '-'} | "
            f"{deviation.asset_id or '-'} | {', '.join(deviation.event_ids)} |"
        )
    if not deviations:
        lines.append("| No deviations detected | info | - | - | - |")

    lines.extend(["", "## Incidents and evidence", "", "| incident | severity | summary | events |", "|---|---|---|---|"])
    for incident in incidents:
        lines.append(
            f"| {incident.incident_id}: {incident.title} | {incident.severity} | "
            f"{incident.summary} | {', '.join(incident.event_ids)} |"
        )
    if not incidents:
        lines.append("| No incidents generated | info | - | - |")

    lines.extend(["", "## Training and improvement", ""])
    if actions:
        for action in actions:
            lines.append(f"- {action.title}: {action.rationale} Caveat: {action.caveat}")
    else:
        lines.append("- No improvement actions generated.")

    lines.extend([
        "",
        "## Artifact links",
        "",
        f"- Event ledger: `{manifest.artifacts.get('physical_event_log', '-')}`",
        f"- Reality graph: `{manifest.artifacts.get('reality_graph', '-')}`",
        f"- Regression tests: `{manifest.artifacts.get('regression_tests', '-')}`",
        "",
        "## Limitations",
        "",
        "- This report is derived from calibrated planar state streams.",
        "- It depends on tracked/tagged assets.",
        "- It is not a certified safety or quality decision system.",
    ])
    return "\n".join(lines) + "\n"


def render_html(markdown_text: str) -> str:
    body = []
    lines = markdown_text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("# "):
            body.append(f"<h1>{_render_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{_render_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            body.append(f"<p class=\"bullet\">{_render_inline(line[2:])}</p>")
        elif line.startswith("|"):
            table_lines = []
            while idx < len(lines) and lines[idx].startswith("|"):
                table_lines.append(lines[idx])
                idx += 1
            body.append(_render_table(table_lines))
            continue
        elif not line.strip():
            body.append("")
        else:
            body.append(f"<p>{_render_inline(line)}</p>")
        idx += 1
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Metriplane Cell Truth Report</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #090d11;
      --panel: #10171d;
      --panel-2: #121b22;
      --line: #24343e;
      --line-soft: rgba(93, 220, 211, 0.18);
      --text: #e8eef2;
      --muted: #9cb1ba;
      --accent: #64ded6;
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 40px 24px; background: var(--bg); color: var(--text);
           font: 14px/1.55 Inter, system-ui, sans-serif; }
    main { max-width: 1180px; margin: 0 auto; }
    h1, h2 { color: #ffffff; letter-spacing: 0; }
    h1 { font-size: clamp(30px, 4vw, 46px); line-height: 1.05; margin: 0 0 28px; }
    h2 { margin: 32px 0 14px; border-top: 1px solid var(--line); padding-top: 22px; }
    p { margin: 8px 0; background: var(--panel); border: 1px solid var(--line);
        border-radius: 6px; padding: 10px 12px; }
    code { color: var(--accent); font-family: "JetBrains Mono", ui-monospace, monospace; }
    .bullet { display: flex; gap: 8px; align-items: baseline; }
    .bullet::before { content: "•"; color: var(--accent); font-weight: 700; }
    .report-table-wrap { overflow-x: auto; margin: 12px 0 20px; border: 1px solid var(--line);
                         border-radius: 8px; background: var(--panel); }
    .report-table { width: 100%; border-collapse: collapse; min-width: 720px; table-layout: fixed; }
    .report-table th { color: var(--accent); background: var(--panel-2); text-align: left;
                       font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .report-table th, .report-table td { padding: 12px 14px; border-bottom: 1px solid var(--line-soft);
                                         vertical-align: top; overflow-wrap: anywhere; }
    .report-table tr:last-child td { border-bottom: 0; }
    .report-table td { color: #d6e3e8; }
  </style>
</head>
<body><main>
""" + "\n".join(body) + "\n</main></body></html>\n"


def write_report(path_md: str | Path, path_html: str | Path, markdown_text: str) -> None:
    md = Path(path_md)
    html_path = Path(path_html)
    md.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(render_html(markdown_text), encoding="utf-8")
