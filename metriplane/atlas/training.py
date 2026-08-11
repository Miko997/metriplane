# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.atlas.models import AtlasIncident, TrainingCase


def training_case_from_incident(incident: AtlasIncident) -> TrainingCase:
    return TrainingCase(
        training_case_id=f"training_{incident.incident_id}",
        title=f"Training case: {incident.title}",
        what_happened=incident.summary,
        why_it_matters="The evaluated state did not meet a supplied process rule.",
        evidence_links=[f"event:{event_id}" for event_id in incident.event_ids],
        what_to_do_next=[
            "Review the evidence bundle.",
            "Confirm the expected tool/material staging rule.",
            "Use the regression test before changing the process or layout.",
        ],
        quiz_questions=[
            {
                "question": "Which evidence should be checked before changing the process?",
                "answer": "The linked event timeline, state segment, and incident bundle.",
            },
            {
                "question": "Does this report prove individual blame?",
                "answer": (
                    "No. It supports review of recorded normalized state against supplied "
                    "process rules."
                ),
            },
        ],
    )


def render_training_markdown(case: TrainingCase) -> str:
    lines = [
        f"# {case.title}",
        "",
        "## What happened",
        case.what_happened,
        "",
        "## Why it matters",
        case.why_it_matters,
        "",
        "## Evidence links",
    ]
    lines.extend(f"- {link}" for link in case.evidence_links)
    lines.extend(["", "## What to do next"])
    lines.extend(f"- {item}" for item in case.what_to_do_next)
    lines.extend(["", "## Quiz"])
    for item in case.quiz_questions:
        lines.append(f"- Q: {item['question']}")
        lines.append(f"  A: {item['answer']}")
    lines.extend(["", "## Limitations"])
    lines.extend(f"- {limitation}" for limitation in case.limitations)
    return "\n".join(lines) + "\n"


def write_training_case(case: TrainingCase, path_md: str | Path, path_json: str | Path | None = None) -> None:
    md = Path(path_md)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_training_markdown(case), encoding="utf-8")
    if path_json:
        Path(path_json).write_text(json.dumps(case.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
