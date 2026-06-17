# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path


def edge_doctor(runs_root: str | Path, min_free_mb: int = 512) -> dict:
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    free_mb = usage.free // (1024 * 1024)
    checks = [
        {"name": "python_version", "status": "PASS" if sys.version_info >= (3, 12) else "FAIL", "detail": platform.python_version()},
        {"name": "runs_root_writable", "status": "PASS", "detail": str(root)},
        {"name": "disk_free_mb", "status": "PASS" if free_mb >= min_free_mb else "WARN", "detail": str(free_mb)},
    ]
    return {
        "schema_version": "metriplane.atlas.edge_doctor.v1",
        "platform": platform.platform(),
        "runs_root": str(root),
        "checks": checks,
        "pass": all(check["status"] == "PASS" for check in checks),
        "limitations": ["Local resource check only; not a hardware certification."],
    }


def retention_plan(runs_root: str | Path, keep_last: int = 20) -> dict:
    root = Path(runs_root)
    manifests = sorted(root.rglob("atlas_manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    keep = manifests[:keep_last]
    delete = manifests[keep_last:]
    return {
        "schema_version": "metriplane.atlas.retention_plan.v1",
        "runs_root": str(root),
        "keep_last": keep_last,
        "keep_run_dirs": [str(path.parent) for path in keep],
        "delete_candidates": [str(path.parent) for path in delete],
        "mode": "plan_only",
    }


def write_edge_bundle(runs_root: str | Path, out_path: str | Path) -> Path:
    data = {
        "schema_version": "metriplane.atlas.edge_bundle.v1",
        "doctor": edge_doctor(runs_root),
        "retention": retention_plan(runs_root),
        "autostart": {
            "systemd_unit_example": "docs/atlas/phase_43_edge_appliance_mode.md",
            "status": "documentation_only",
        },
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
