# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from metriplane.atlas.query import index_runs


def compare_cells(root: str | Path, out_json: str | Path | None = None, out_md: str | Path | None = None) -> dict:
    index = index_runs(root)
    cells: dict[str, dict] = {}
    for run in index["runs"]:
        cell = run.get("cell_id") or "unknown"
        entry = cells.setdefault(cell, {"cell_id": cell, "runs": 0, "events": 0, "incidents": 0, "run_dirs": []})
        entry["runs"] += 1
        entry["events"] += int(run.get("event_count") or 0)
        entry["incidents"] += int(run.get("incident_count") or 0)
        entry["run_dirs"].append(run.get("run_dir"))
    result = {
        "schema_version": "metriplane.atlas.multi_cell_comparison.v1",
        "root": str(root),
        "cells": [cells[key] for key in sorted(cells)],
        "limitations": ["Compares local run summaries only; no permission model is enforced."],
    }
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if out_md:
        lines = [
            "# Atlas Multi-Cell Summary",
            "",
            "| cell | runs | events | incidents |",
            "|---|---:|---:|---:|",
        ]
        for cell in result["cells"]:
            lines.append(f"| {cell['cell_id']} | {cell['runs']} | {cell['events']} | {cell['incidents']} |")
        lines.extend([
            "",
            "Limitations: local run summaries only; no production authorization or permission model is implied.",
            "",
        ])
        Path(out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(out_md).write_text("\n".join(lines), encoding="utf-8")
    return result
