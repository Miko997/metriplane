# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from tempfile import TemporaryDirectory
import zipfile

from metriplane.atlas.event_ledger import read_events
from metriplane.atlas.models import AtlasIncident, BundleManifest


REQUIRED_BUNDLE_FILES = [
    "manifest.json",
    "incident.json",
    "event_timeline.jsonl",
    "state_segment.jsonl",
    "reality_graph_excerpt.json",
    "process_trace_excerpt.json",
    "configs/assets.yaml",
    "configs/workspace.yaml",
    "configs/process.yaml",
    "reports/cell_truth_report.md",
    "checksums.sha256",
    "replay_command.sh",
    "limitations.md",
]

MAX_ZIP_MEMBERS = 1024
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 1000
_CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_incidents(run_dir: Path) -> list[AtlasIncident]:
    incidents = []
    for line in (run_dir / "incidents.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            incidents.append(AtlasIncident.model_validate(json.loads(line)))
    return incidents


def _zip_dir(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(src).as_posix())


def _safe_relative_path(value: str) -> str:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe bundle path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe bundle path: {value}")
    return path.as_posix()


def _validate_zip_archive(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ZIP_MEMBERS:
        raise ValueError(
            f"zip has too many members: {len(members)} (maximum {MAX_ZIP_MEMBERS})"
        )
    seen: set[str] = set()
    total = 0
    for member in members:
        try:
            rel = _safe_relative_path(member.filename.rstrip("/"))
        except ValueError as exc:
            raise ValueError(f"unsafe zip path: {member.filename}") from exc
        if rel in seen:
            raise ValueError(f"duplicate zip member: {rel}")
        seen.add(rel)
        if member.flag_bits & 0x1:
            raise ValueError(f"encrypted zip member is not supported: {rel}")
        # Unix symlink mode, when present in an external archive.
        if ((member.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError(f"zip symlink is not allowed: {rel}")
        if member.is_dir():
            continue
        if member.file_size > MAX_ZIP_MEMBER_BYTES:
            raise ValueError(
                f"zip member is too large: {rel} ({member.file_size} bytes)"
            )
        total += member.file_size
        if total > MAX_ZIP_TOTAL_BYTES:
            raise ValueError(
                f"zip expands beyond {MAX_ZIP_TOTAL_BYTES} bytes"
            )
        if member.file_size and member.compress_size == 0:
            raise ValueError(f"invalid compressed size for zip member: {rel}")
        if (
            member.compress_size
            and member.file_size / member.compress_size > MAX_ZIP_COMPRESSION_RATIO
        ):
            raise ValueError(f"zip compression ratio is too high: {rel}")


def safe_extract(archive: zipfile.ZipFile, dest: str | Path) -> None:
    _validate_zip_archive(archive)
    root = Path(dest).resolve()
    for member in archive.infolist():
        target = (root / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"unsafe zip path: {member.filename}")
    archive.extractall(root)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def export_bundle(
    run_dir: str | Path,
    incident_id: str,
    out_zip: str | Path,
    state_segment_rows: list[dict] | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    run = Path(run_dir)
    if not run.is_dir():
        raise ValueError(f"run directory does not exist: {run}")
    run_manifest = {}
    manifest_path = run / "atlas_manifest.json"
    if manifest_path.exists():
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    incident = next((item for item in _load_incidents(run) if item.incident_id == incident_id), None)
    if incident is None:
        raise ValueError(f"incident not found: {incident_id}")
    out = Path(out_zip)
    if out.suffix.lower() != ".zip":
        raise ValueError(f"bundle output must end in .zip: {out}")
    bundle_dir = out.with_suffix("")
    for destination in (out, bundle_dir):
        destination_resolved = destination.resolve()
        run_resolved = run.resolve()
        if (
            destination_resolved == run_resolved
            or destination_resolved in run_resolved.parents
        ):
            raise ValueError(f"bundle output would replace its source run: {destination}")
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                raise ValueError(
                    f"refusing to replace existing bundle output without --overwrite: {destination}"
                )

    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{out.stem}-", dir=out.parent) as temp_dir:
        stage_root = Path(temp_dir)
        stage_bundle = stage_root / "bundle"
        stage_zip = stage_root / out.name
        stage_bundle.mkdir()

        _json_dump(stage_bundle / "incident.json", incident.model_dump())
        events = [
            event for event in read_events(run / "physical_event_log.jsonl")
            if event.event_id in set(incident.event_ids)
        ]
        with (stage_bundle / "event_timeline.jsonl").open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.model_dump(), sort_keys=True) + "\n")
        rows = state_segment_rows or []
        with (stage_bundle / "state_segment.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        shutil.copyfile(run / "reality_graph.json", stage_bundle / "reality_graph_excerpt.json")
        shutil.copyfile(run / "process_trace.json", stage_bundle / "process_trace_excerpt.json")
        (stage_bundle / "configs").mkdir(exist_ok=True)
        for name in ("assets.yaml", "workspace.yaml", "process.yaml", "contracts.yaml", "work_orders.csv"):
            src = run / "configs" / name
            if src.exists():
                shutil.copyfile(src, stage_bundle / "configs" / name)
        (stage_bundle / "reports").mkdir(exist_ok=True)
        shutil.copyfile(run / "cell_truth_report.md", stage_bundle / "reports" / "cell_truth_report.md")
        (stage_bundle / "generated").mkdir(exist_ok=True)
        (stage_bundle / "provenance").mkdir(exist_ok=True)
        (stage_bundle / "limitations.md").write_text(
            "# Limitations\n\n"
            "- Derived from calibrated planar state streams.\n"
            "- Requires tracked/tagged assets.\n"
            "- Not a certified safety or quality decision system.\n",
            encoding="utf-8",
        )
        (stage_bundle / "replay_command.sh").write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "echo 'Replay state segment with metriplane atlas test or inspect state_segment.jsonl'\n",
            encoding="utf-8",
        )
        (stage_bundle / "provenance" / "command.txt").write_text(
            f"metriplane atlas bundle export --incident-id {incident_id} --run-dir {run} --out {out}\n",
            encoding="utf-8",
        )
        manifest = BundleManifest(
            bundle_id=f"bundle_{incident_id}",
            incident_id=incident_id,
            run_id=str(run_manifest.get("run_id") or incident_id),
            required_files=list(REQUIRED_BUNDLE_FILES),
        )
        _json_dump(stage_bundle / "manifest.json", manifest.model_dump())

        checksum_paths = [
            path for path in sorted(stage_bundle.rglob("*"))
            if path.is_file() and path.name != "checksums.sha256"
        ]
        with (stage_bundle / "checksums.sha256").open("w", encoding="utf-8") as handle:
            for path in checksum_paths:
                handle.write(
                    f"{sha256_file(path)}  {path.relative_to(stage_bundle).as_posix()}\n"
                )
        _zip_dir(stage_bundle, stage_zip)

        if overwrite:
            _remove_path(out)
            _remove_path(bundle_dir)
        shutil.move(str(stage_bundle), str(bundle_dir))
        os.replace(stage_zip, out)
    return out


@contextmanager
def _unpack_bundle(bundle: Path) -> Iterator[Path]:
    if bundle.is_dir():
        yield bundle
        return
    with TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as archive:
            safe_extract(archive, tmp)
        yield Path(tmp)


def _regular_file_inventory(root: Path, checksum_name: str) -> tuple[set[str], list[str]]:
    files: set[str] = set()
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"bundle symlink is not allowed: {rel}")
        elif path.is_file():
            if rel != checksum_name:
                files.add(rel)
        elif not path.is_dir():
            errors.append(f"bundle entry is not a regular file: {rel}")
    return files, errors


def _read_checksum_inventory(path: Path) -> tuple[dict[str, str], list[str]]:
    recorded: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        match = _CHECKSUM_RE.fullmatch(raw_line)
        if match is None:
            errors.append(f"malformed checksum entry on line {line_number}")
            continue
        digest, _, raw_rel = match.groups()
        try:
            rel = _safe_relative_path(raw_rel)
        except ValueError as exc:
            errors.append(f"checksum line {line_number}: {exc}")
            continue
        if rel == "checksums.sha256":
            errors.append("checksum file must not checksum itself")
            continue
        if rel in recorded:
            errors.append(f"duplicate checksum entry: {rel}")
            continue
        recorded[rel] = digest.lower()
    return recorded, errors


def verify_bundle(bundle_path: str | Path) -> dict:
    bundle = Path(bundle_path)
    errors: list[str] = []
    try:
        with _unpack_bundle(bundle) as root:
            for required in REQUIRED_BUNDLE_FILES:
                if not (root / required).is_file():
                    errors.append(f"missing required file: {required}")
            if not errors:
                manifest = BundleManifest.model_validate(json.loads((root / "manifest.json").read_text()))
                manifest_required = set(manifest.required_files)
                missing_manifest_entries = set(REQUIRED_BUNDLE_FILES) - manifest_required
                for rel in sorted(missing_manifest_entries):
                    errors.append(f"manifest omits required file: {rel}")
                recorded, checksum_errors = _read_checksum_inventory(
                    root / "checksums.sha256"
                )
                errors.extend(checksum_errors)
                inventory, inventory_errors = _regular_file_inventory(
                    root, "checksums.sha256"
                )
                errors.extend(inventory_errors)
                for rel in sorted(inventory - set(recorded)):
                    errors.append(f"file missing checksum entry: {rel}")
                for rel in sorted(set(recorded) - inventory):
                    errors.append(f"checksum references missing file: {rel}")
                for rel, digest in recorded.items():
                    path = root / rel
                    if rel in inventory and sha256_file(path) != digest:
                        errors.append(f"checksum mismatch: {rel}")
                event_ids = {
                    json.loads(line)["event_id"]
                    for line in (root / "event_timeline.jsonl").read_text().splitlines()
                    if line.strip()
                }
                incident = AtlasIncident.model_validate(json.loads((root / "incident.json").read_text()))
                for event_id in incident.event_ids:
                    if event_id not in event_ids:
                        errors.append(f"incident references missing event: {event_id}")
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        errors.append(message)
    return {
        "schema_version": "metriplane.atlas.bundle_verifier.v1",
        "bundle": str(bundle),
        "pass": not errors,
        "errors": errors,
    }
