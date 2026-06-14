# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.counterfactuals.models import CounterfactualReport


def write_json(report: CounterfactualReport, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.model_dump(by_alias=True), indent=2))
    return p


def render_md(report: CounterfactualReport) -> str:
    o = report.original_summary
    lines = [
        f"# Counterfactual report: {report.incident_id}",
        "",
        f"Original incident: `{o['rule_id']}` ({o['severity']}) "
        f"objects={', '.join(o['objects'])}",
        "",
        "## Cases",
        "",
    ]
    for c in report.cases:
        mark = "kept" if c.original_incident_present else "PREVENTED"
        lines.append(f"- [{mark}] {c.summary}")
    lines += ["", "## Limitations", ""]
    for lim in report.limitations:
        lines.append(f"- {lim}")
    lines.append("")
    return "\n".join(lines)


def write_md(report: CounterfactualReport, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_md(report))
    return p


def print_summary(report: CounterfactualReport) -> None:
    o = report.original_summary
    print(f"Original: {o['rule_id']} ({o['severity']}) objects={','.join(o['objects'])}")
    for c in report.cases:
        mark = "kept" if c.original_incident_present else "PREVENTED"
        print(f"  [{mark}] {c.summary}")
