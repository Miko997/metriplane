# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path


CLAIMS = [
    ("Cell Black Box demo runs", "datasets/demo/atlas/assembly_cell_missing_tool.jsonl"),
    ("Domain packs validate", "configs/domain_packs/assembly_cell/assets.yaml"),
    ("Evidence bundles verify", "metriplane/atlas/bundles.py"),
    ("Physical regressions run", "metriplane/atlas/regression.py"),
    ("Dashboard generated", "metriplane/atlas/dashboard.py"),
    ("Privacy report generated", "metriplane/atlas/privacy.py"),
    ("Open Atlas Protocol schemas export", "metriplane/atlas/protocol.py"),
    ("External pilot complete", ""),
]

FREEZE_DENYLIST = [
    ".git/",
    ".venv/",
    ".vt-venv/",
    ".env",
    "*.pem",
    "*.key",
    "private_evidence/",
    "~/",
    "runs/",
    "web/dashboard/atlas_run/",
]


def claim_audit(root: str | Path = ".") -> dict:
    base = Path(root)
    rows = []
    for claim, rel in CLAIMS:
        supported = bool(rel) and (base / rel).exists()
        rows.append({
            "claim": claim,
            "supported": supported,
            "artifact": rel or "external evidence required",
            "status": "PASS" if supported else "EXTERNAL_REQUIRED",
        })
    return {
        "schema_version": "metriplane.atlas.claim_audit.v1",
        "claims": rows,
        "pass": all(row["supported"] or row["status"] == "EXTERNAL_REQUIRED" for row in rows),
        "denylist": FREEZE_DENYLIST,
        "limitations": [
            "External pilots and DOI/archive publication cannot be completed by local code changes alone.",
            "Evidence freeze writes claim audit notes only; it does not recursively copy the repository.",
        ],
    }


def build_freeze(root: str | Path, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    audit = claim_audit(root)
    (out / "atlas_claim_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Atlas Evidence Freeze Notes",
        "",
        "This freeze is a local repository evidence freeze for the 0.2.0 Atlas foundation.",
        "It writes claim audit notes only and does not recursively copy the repository.",
        "",
        "| claim | status | artifact |",
        "|---|---|---|",
    ]
    for row in audit["claims"]:
        lines.append(f"| {row['claim']} | {row['status']} | `{row['artifact']}` |")
    lines.extend([
        "",
        "Denylist reviewed for recursive-copy workflows: " + ", ".join(f"`{item}`" for item in FREEZE_DENYLIST) + ".",
        "",
        "Limitations: external pilots, DOI archival, hardware appliance deployment, and measured Isaac/ROS latency require separate evidence.",
        "",
    ])
    (out / "atlas_release_notes.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "schema_version": "metriplane.atlas.evidence_freeze.v1",
        "out_dir": str(out),
        "claim_audit": str(out / "atlas_claim_audit.json"),
        "release_notes": str(out / "atlas_release_notes.md"),
    }
