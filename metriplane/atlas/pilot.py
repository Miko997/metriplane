# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path


FILES = {
    "pilot_checklist.md": """# Atlas External Pilot Checklist

- Confirm the reviewer can install the repository.
- Run the assembly-cell demo from a clean checkout.
- Validate the domain pack.
- Open the Cell Truth Report and dashboard.
- Verify the evidence bundle.
- Run the generated regression test.
- Record only approved, public-safe feedback.
""",
    "reviewer_questionnaire.md": """# Atlas Reviewer Questionnaire

1. Which recorded state change did the report make easiest to understand?
2. Which evidence artifact felt most trustworthy?
3. Which limitation was unclear?
4. Would this help a team discuss process improvement without blame?
5. What would block use on a real cell?
""",
    "success_report_template.md": """# Atlas Pilot Success Report

## Context

- Site:
- Cell:
- Date:
- Reviewer:

## Result

- Demo ran:
- Bundle verified:
- Regression passed:
- Useful finding:

## Public-safe notes

Do not include confidential customer data or quotes without permission.
""",
    "reproduction_notes.md": """# Atlas Pilot Reproduction Notes

```bash
metriplane atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out runs/atlas/pilot_demo
metriplane atlas bundle verify runs/atlas/pilot_demo/evidence_bundles/INC-0001.zip
metriplane atlas test runs/atlas/pilot_demo/regression_tests/INC-0001.yaml
```
""",
}


def create_pilot_kit(out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for name, text in FILES.items():
        path = out / name
        path.write_text(text, encoding="utf-8")
        files.append(str(path))
    return {
        "schema_version": "metriplane.atlas.external_pilot_kit.v1",
        "out_dir": str(out),
        "files": files,
        "status": "template_only",
        "limitations": ["External pilot evidence requires real external reviewers and cannot be fabricated locally."],
    }
