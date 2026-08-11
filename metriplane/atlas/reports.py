# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import html
import unicodedata
from pathlib import Path

from metriplane.atlas.models import (
    ATLAS_LIMITATION_STATEMENTS,
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


def _plain_identifier(value: str) -> str:
    return value.replace("_", " ")


def _one_line_untrusted(value: str, *, limit: int = 240) -> str:
    """Keep external labels from creating report structure or unbounded prose."""
    collapsed = " ".join(value.split())
    rendered = "".join(
        character
        if unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
        else f"\\u{ord(character):04x}"
        for character in collapsed
    ).replace("`", "'")
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 1].rstrip() + "…"


def render_markdown(
    manifest: AtlasRunManifest,
    events: list[AtlasEvent],
    deviations: list[AtlasDeviation],
    incidents: list[AtlasIncident],
    metrics: FlowMetrics,
    actions: list[ImprovementAction],
) -> str:
    lines: list[str] = [
        "# Incident Report",
        "",
        "Formal artifact: `Cell Truth Report`.",
        "",
        "This report summarizes one recorded run: a saved sequence of object positions "
        "and timestamps from a bounded workcell.",
        "",
        "## What happened",
        "",
        f"- Metriplane reviewed {_fmt_s(metrics.observed_duration_s)} of recorded activity.",
        f"- It recorded {len(events)} events and grouped them into "
        f"{len(incidents)} {'incident' if len(incidents) == 1 else 'incidents'}.",
        "- An event is one observed change, such as an object arriving or a required tool "
        "being absent.",
        "- An incident groups related events that need review because an expected process "
        "condition was not met.",
    ]
    if incidents:
        for incident in incidents:
            lines.append(
                f"- Incident `{incident.incident_id}` ({incident.severity}): "
                f"{_plain_identifier(incident.title)}. "
                f"{_plain_identifier(incident.summary)}"
            )
    else:
        lines.append("- No incident was generated from this run.")
    if actions:
        for action in actions:
            lines.append(f"- Suggested follow-up: {action.title}. {action.rationale}")

    lines.extend(
        [
            "",
            "## Why it was flagged",
            "",
            "Process rules describe the expected steps, required objects and locations, "
            "and allowed waiting times. Metriplane flags a deviation when the recorded "
            "run does not meet one of those rules.",
            "",
            "| reason | severity | expected step | object | supporting event records |",
            "|---|---|---|---|---|",
        ]
    )
    if deviations:
        for deviation in deviations:
            lines.append(
                f"| {_plain_identifier(deviation.type)} (`{deviation.type}`) | "
                f"{deviation.severity} | `{deviation.process_step_id or '-'}` | "
                f"`{deviation.asset_id or '-'}` | "
                f"{', '.join(f'`{event_id}`' for event_id in deviation.event_ids) or '-'} |"
            )
    else:
        lines.append("| No process rule was broken | info | - | - | - |")

    lines.extend(
        [
            "",
            "## When it happened",
            "",
            "The times below are measured from the start of the recorded run.",
            "",
            "| time | what was observed | object | technical event record |",
            "|---:|---|---|---|",
        ]
    )
    if events:
        for event in events:
            lines.append(
                f"| {event.ts:0.1f} s | {event.message} | `{event.asset_id or '-'}` | "
                f"`{event.event_id}` / `{event.event_type}` |"
            )
    else:
        lines.append("| - | No events were recorded | - | - |")

    lines.extend(
        [
            "",
            "## Evidence that was saved",
            "",
            "An evidence bundle is a checksummed ZIP that keeps the incident report and "
            "supporting records together so another person can verify what was reviewed.",
        ]
    )
    if incidents:
        for incident in incidents:
            lines.append(
                f"- Evidence bundle for `{incident.incident_id}`: "
                f"`{manifest.artifacts.get('evidence_bundles', 'evidence_bundles')}/"
                f"{incident.incident_id}.zip`"
            )
    else:
        lines.append("- No evidence bundle was generated because no incident was found.")
    lines.extend(
        [
            f"- Event records: `{manifest.artifacts.get('physical_event_log', '-')}`",
            f"- Incident records: `{manifest.artifacts.get('incidents', '-')}`",
            f"- Supporting recorded state: `{manifest.artifacts.get('state_segment', '-')}`",
            f"- Formal Cell Truth Report: "
            f"`{manifest.artifacts.get('cell_truth_report_html', '-')}`",
            "",
            "## Repeatable check that was generated",
            "",
            "A regression check is a generated test that replays the saved incident and "
            "checks that the expected events and incident still appear within declared "
            "timing tolerances.",
            "",
            "Deterministic replay uses the saved inputs and recorded time sequence instead "
            "of live timing, so repeated evaluations can be compared consistently.",
        ]
    )
    if incidents:
        for incident in incidents:
            lines.append(
                f"- Repeatable check for `{incident.incident_id}`: "
                f"`{manifest.artifacts.get('regression_tests', 'regression_tests')}/"
                f"{incident.incident_id}.yaml`"
            )
    else:
        lines.append("- No repeatable check was generated because no incident was found.")

    external = manifest.external_source_provenance
    if external is not None:
        lines.extend(
            [
                "",
                "## External fixture provenance",
                "",
                f"- Fixture: `{_one_line_untrusted(external.fixture_id)}`.",
                (
                    "- Contract: "
                    f"`{_one_line_untrusted(external.contract_schema_version)}` / "
                    f"`{_one_line_untrusted(external.contract_profile)}`."
                ),
                (
                    "- Source: "
                    f"`{_one_line_untrusted(external.source_project)}` at revision "
                    f"`{_one_line_untrusted(external.source_revision)}`."
                ),
                (
                    "- Adapter: "
                    f"`{_one_line_untrusted(external.adapter_id)}` "
                    f"version `{_one_line_untrusted(external.adapter_version)}` at commit "
                    f"`{_one_line_untrusted(external.adapter_commit)}`."
                ),
                (
                    "- Full conversion provenance: "
                    f"`{external.path}` (SHA-256 `{external.sha256}`)."
                ),
                (
                    "- This identifies the supplied normalized fixture and its conversion; "
                    "the incident result still comes from the recorded normalized state and "
                    "the supplied process rules."
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## Limits of this result",
            "",
            *(f"- {statement}" for statement in ATLAS_LIMITATION_STATEMENTS),
            (
                "- It does not prove root cause; suggested follow-ups require before-and-after "
                "validation."
            ),
        ]
    )
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
  <title>Metriplane Incident Report</title>
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
