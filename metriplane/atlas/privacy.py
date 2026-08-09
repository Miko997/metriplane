# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IDENTITY_KEYS = {"face_id", "person_id", "worker_id", "biometric_id", "name"}
IDENTITY_NAME_KEYS = {
    "display_name",
    "first_name",
    "full_name",
    "last_name",
    "operator_name",
    "person_name",
    "worker_name",
}
IDENTITY_IDENTIFIER_KEYS = {
    "employee_id",
    "operator_id",
    "subject_id",
    "user_id",
}
ASSET_IDENTIFIER_KEYS = {
    "asset_id",
    "asset_ids",
    "asset_identifier",
    "asset_identifiers",
    "asset_tag",
    "device_id",
    "device_ids",
    "equipment_id",
    "equipment_ids",
    "machine_id",
    "machine_ids",
    "object_id",
    "object_ids",
    "part_id",
    "part_ids",
    "required_asset_id",
    "required_asset_ids",
    "serial_number",
    "tool_id",
    "tool_ids",
    "workpiece_id",
    "workpiece_ids",
}
ASSET_CONTAINER_KEYS = {
    "asset",
    "assets",
    "equipment",
    "fused",
    "machine",
    "machines",
    "object",
    "objects",
    "tool",
    "tools",
    "workpiece",
    "workpieces",
}
PRIVATE_CONTEXT_KEYS = {
    "domain_pack",
    "source_session_jsonl",
    "work_order_id",
    "work_order_ids",
}
ANONYMIZED_JSONL_FILES = (
    "physical_event_log.jsonl",
    "incidents.jsonl",
    "deviations.jsonl",
)
ANONYMIZED_JSON_FILES = (
    "atlas_manifest.json",
    "metrics.json",
    "improvement_actions.json",
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def privacy_report(
    run_dir: str | Path,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    run = Path(run_dir)
    if run.is_symlink() or not run.is_dir():
        raise ValueError(f"run directory must be a regular directory: {run}")
    files: list[Path] = []
    for path in run.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"run path must not be a symlink: {path.relative_to(run)}")
        if path.is_file():
            files.append(path)
    video_files = [str(path.relative_to(run)) for path in files if path.suffix.lower() in VIDEO_EXTENSIONS]
    identity_hits: list[str] = []
    for path in files:
        if path.suffix.lower() not in {".json", ".jsonl", ".yaml", ".yml", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for key in IDENTITY_KEYS:
            if key in text:
                identity_hits.append(f"{path.relative_to(run)}:{key}")
    displayed_run = str(run)
    if out_path is not None:
        try:
            Path(out_path).resolve().relative_to(run.resolve())
            displayed_run = "."
        except ValueError:
            pass
    result = {
        "schema_version": "metriplane.atlas.privacy_report.v1",
        "run_dir": displayed_run,
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
    digest = hashlib.sha256(f"{prefix}\0{value.casefold()}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _normalized_key(key: object) -> str:
    split_camel_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    return re.sub(r"[^a-z0-9]+", "_", split_camel_case.casefold()).strip("_")


def _sensitive_kind(key: object, parents: tuple[str, ...]) -> str | None:
    normalized = _normalized_key(key)
    if (
        normalized in IDENTITY_KEYS
        or normalized in IDENTITY_IDENTIFIER_KEYS
        or normalized in IDENTITY_NAME_KEYS
    ):
        return "person"
    if normalized in ASSET_IDENTIFIER_KEYS:
        return "asset"
    if normalized == "id" and any(parent in ASSET_CONTAINER_KEYS for parent in parents):
        return "asset"
    if normalized in PRIVATE_CONTEXT_KEYS:
        return "context"
    return None


def _scalar_text(value: object) -> str | None:
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _collect_sensitive_values(
    value: object,
    found: dict[tuple[str, str], str],
    *,
    parents: tuple[str, ...] = (),
    forced_kind: str | None = None,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            kind = forced_kind or _sensitive_kind(key, parents)
            _collect_sensitive_values(
                item,
                found,
                parents=(*parents, normalized),
                forced_kind=kind,
            )
        return
    if isinstance(value, list):
        for item in value:
            _collect_sensitive_values(
                item,
                found,
                parents=parents,
                forced_kind=forced_kind,
            )
        return
    if forced_kind is None:
        return
    text = _scalar_text(value)
    if text is None:
        return
    lookup = (forced_kind, text.casefold())
    found.setdefault(lookup, _proxy(text, forced_kind))


def _replace_text_references(text: str, replacements: dict[str, str]) -> str:
    result = text
    # Replace longer identifiers first so an identifier contained in another does
    # not consume only part of the value. Identifier-character boundaries avoid
    # rewriting unrelated IDs such as ``evt_0001`` when an asset ID is ``1``.
    for original, proxy in sorted(
        replacements.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if not original:
            continue
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(original)}(?![A-Za-z0-9_])",
            flags=re.IGNORECASE,
        )
        result = pattern.sub(proxy, result)
    return result


def _pseudonymize(
    value: object,
    proxies: dict[tuple[str, str], str],
    text_replacements: dict[str, str],
    *,
    parents: tuple[str, ...] = (),
    forced_kind: str | None = None,
) -> object:
    if isinstance(value, dict):
        return {
            key: _pseudonymize(
                item,
                proxies,
                text_replacements,
                parents=(*parents, _normalized_key(key)),
                forced_kind=forced_kind or _sensitive_kind(key, parents),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _pseudonymize(
                item,
                proxies,
                text_replacements,
                parents=parents,
                forced_kind=forced_kind,
            )
            for item in value
        ]
    if forced_kind is not None:
        text = _scalar_text(value)
        if text is not None:
            return proxies[(forced_kind, text.casefold())]
        return value
    if isinstance(value, str):
        return _replace_text_references(value, text_replacements)
    return value


def pseudonymize_run(
    run_dir: str | Path,
    out_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    run = Path(run_dir)
    out = Path(out_dir)
    if run.is_symlink() or not run.is_dir():
        raise ValueError(f"run directory does not exist: {run}")
    run_resolved = run.resolve()
    out_resolved = out.resolve()
    if (
        run_resolved == out_resolved
        or run_resolved in out_resolved.parents
        or out_resolved in run_resolved.parents
    ):
        raise ValueError("source run and pseudonymized output must not overlap")
    if (out.exists() or out.is_symlink()) and not overwrite:
        raise ValueError(
            f"refusing to replace existing pseudonymized output without --overwrite: {out}"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    documents: dict[str, Any] = {}
    for rel in ANONYMIZED_JSONL_FILES:
        source = run / rel
        if source.is_symlink():
            raise ValueError(f"source run path must not be a symlink: {rel}")
        if source.exists() and not source.is_file():
            raise ValueError(f"source run path is not a regular file: {rel}")
        documents[rel] = _jsonl(source)
    for rel in ANONYMIZED_JSON_FILES:
        src = run / rel
        if src.is_symlink():
            raise ValueError(f"source run path must not be a symlink: {rel}")
        if src.exists():
            if not src.is_file():
                raise ValueError(f"source run path is not a regular file: {rel}")
            documents[rel] = json.loads(src.read_text(encoding="utf-8"))

    proxies: dict[tuple[str, str], str] = {}
    for document in documents.values():
        _collect_sensitive_values(document, proxies)

    # Free-text fields can repeat an identifier found in a structured field. Keep
    # those references correlated while ensuring the source value does not leak.
    text_replacements: dict[str, str] = {}
    for (kind, original), proxy in proxies.items():
        existing = text_replacements.get(original)
        if existing is None or kind == "person":
            text_replacements[original] = proxy

    with TemporaryDirectory(prefix=f".{out.name}-", dir=out.parent) as temp_dir:
        stage = Path(temp_dir) / "pseudonymized"
        stage.mkdir()
        for rel in ANONYMIZED_JSONL_FILES:
            rows = documents[rel]
            with (stage / rel).open("w", encoding="utf-8") as handle:
                for row in rows:
                    pseudonymized = _pseudonymize(row, proxies, text_replacements)
                    handle.write(json.dumps(pseudonymized, sort_keys=True) + "\n")
        for rel in ANONYMIZED_JSON_FILES:
            if rel in documents:
                (stage / rel).write_text(
                    json.dumps(
                        _pseudonymize(documents[rel], proxies, text_replacements),
                        indent=2,
                        sort_keys=True,
                    ) + "\n",
                    encoding="utf-8",
                )
        (stage / "privacy_metadata.json").write_text(
            json.dumps(
                {
                    "schema_version": "metriplane.atlas.pseudonymization.v1",
                    "privacy_method": "deterministic_pseudonymization",
                    "mapped_values": len(proxies),
                    "mapping_exported": False,
                    "limitations": [
                        (
                            "Pseudonymization reduces direct identifier exposure but is not "
                            "guaranteed anonymization."
                        ),
                        (
                            "Review shareable output for domain-specific sensitive fields "
                            "before disclosure."
                        ),
                    ],
                },
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        backup = Path(temp_dir) / "previous"
        had_previous = out.exists() or out.is_symlink()
        if had_previous and not overwrite:
            raise ValueError(
                "refusing to replace pseudonymized output created while staging "
                f"without --overwrite: {out}"
            )
        if had_previous:
            os.replace(out, backup)
        try:
            os.replace(stage, out)
        except Exception:
            if had_previous and (backup.exists() or backup.is_symlink()):
                os.replace(backup, out)
            raise
    return {
        "schema_version": "metriplane.atlas.pseudonymized_proxy.v1",
        "privacy_method": "deterministic_pseudonymization",
        "source_run_dir": str(run),
        "out_dir": str(out),
        "mapped_values": len(proxies),
        "mapping_exported": False,
    }


def anonymize_run(
    run_dir: str | Path,
    out_dir: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Compatibility alias for :func:`pseudonymize_run`.

    Deterministic proxies reduce direct identifier exposure but are not
    guaranteed anonymization.
    """
    return pseudonymize_run(run_dir, out_dir, overwrite=overwrite)
