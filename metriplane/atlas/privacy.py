# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IDENTITY_KEYS = {"face_id", "person_id", "worker_id", "biometric_id", "name"}


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def privacy_report(run_dir: str | Path, out_path: str | Path | None = None) -> dict:
    run = Path(run_dir)
    files = [path for path in run.rglob("*") if path.is_file()]
    video_files = [str(path.relative_to(run)) for path in files if path.suffix.lower() in VIDEO_EXTENSIONS]
    identity_hits: list[str] = []
    for path in files:
        if path.suffix.lower() not in {".json", ".jsonl", ".yaml", ".yml", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for key in IDENTITY_KEYS:
            if key in text:
                identity_hits.append(f"{path.relative_to(run)}:{key}")
    result = {
        "schema_version": "metriplane.atlas.privacy_report.v1",
        "run_dir": str(run),
        "raw_video_files": video_files,
        "identity_key_hits": sorted(identity_hits),
        "video_free": not video_files,
        "biometric_free": not identity_hits,
        "retention_default": "derived_state_and_reports_only",
        "limitations": [
            "String scan is a repository-level guard, not legal compliance advice.",
            "Deployment privacy review is still required.",
        ],
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _proxy(value: str, prefix: str = "asset") -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def anonymize_run(run_dir: str | Path, out_dir: str | Path) -> dict:
    run = Path(run_dir)
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}

    def replace_asset(value: object) -> object:
        if isinstance(value, dict):
            return {key: replace_asset(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_asset(item) for item in value]
        if isinstance(value, str) and any(token in value for token in ("asset", "tool", "workpiece", "kit", "torque", "gauge")):
            mapping.setdefault(value, _proxy(value))
            return mapping[value]
        return value

    for rel in ("physical_event_log.jsonl", "incidents.jsonl", "deviations.jsonl"):
        rows = _jsonl(run / rel)
        with (out / rel).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(replace_asset(row), sort_keys=True) + "\n")
    for rel in ("atlas_manifest.json", "metrics.json", "improvement_actions.json"):
        src = run / rel
        if src.exists():
            (out / rel).write_text(json.dumps(replace_asset(json.loads(src.read_text(encoding="utf-8"))), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "asset_proxy_map.json").write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "metriplane.atlas.anonymized_proxy.v1",
        "source_run_dir": str(run),
        "out_dir": str(out),
        "mapped_values": len(mapping),
    }
