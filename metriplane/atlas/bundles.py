# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import zipfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from metriplane.atlas.event_ledger import read_events
from metriplane.atlas.models import (
    EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
    EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
    AtlasEvent,
    AtlasIncident,
    BundleManifest,
    ExternalSourceProvenanceReference,
    external_source_provenance_reference,
)
from metriplane.schema import FrameStateModel

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

REQUIRED_EXPORT_SOURCE_FILES = (
    "incidents.jsonl",
    "physical_event_log.jsonl",
    "reality_graph.json",
    "process_trace.json",
    "configs/assets.yaml",
    "configs/workspace.yaml",
    "configs/process.yaml",
    "cell_truth_report.md",
)
OPTIONAL_EXPORT_SOURCE_FILES = (
    "atlas_manifest.json",
    "state_segment.jsonl",
    "configs/contracts.yaml",
    "configs/work_orders.csv",
    EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
)

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


def _reject_duplicate_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number is prohibited: {value}")


def _load_external_source_provenance(path: Path) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except Exception as exc:
        raise ValueError(f"invalid external source provenance {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - invalid persisted content
            f"external source provenance must be a JSON object: {path}"
        )
    return value


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


def _validate_export_source_file(
    run: Path,
    relative_path: str,
    *,
    required: bool,
) -> None:
    rel = _safe_relative_path(relative_path)
    current = run
    for part in PurePosixPath(rel).parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"source run path must not be a symlink: {rel}")

    if current.exists():
        if not current.is_file():
            raise ValueError(f"source run path is not a regular file: {rel}")
    elif required:
        raise ValueError(f"source run is missing required file: {rel}")


def _validate_export_sources(run: Path) -> None:
    for relative_path in REQUIRED_EXPORT_SOURCE_FILES:
        _validate_export_source_file(run, relative_path, required=True)
    for relative_path in OPTIONAL_EXPORT_SOURCE_FILES:
        _validate_export_source_file(run, relative_path, required=False)


def _external_source_provenance_for_export(
    run: Path,
    run_manifest: dict[str, Any],
) -> ExternalSourceProvenanceReference | None:
    source_path = run / EXTERNAL_SOURCE_PROVENANCE_RUN_PATH
    raw_reference = run_manifest.get("external_source_provenance")
    raw_artifacts = run_manifest.get("artifacts")
    artifact_path = (
        raw_artifacts.get("external_source_provenance")
        if isinstance(raw_artifacts, dict)
        else None
    )
    has_source = source_path.exists() or source_path.is_symlink()
    if raw_reference is None and artifact_path is None and not has_source:
        return None
    if raw_reference is None:
        raise ValueError(
            "source run external provenance has no atlas_manifest.json reference"
        )
    try:
        reference = ExternalSourceProvenanceReference.model_validate(raw_reference)
    except Exception as exc:
        raise ValueError(
            f"invalid external source provenance reference in atlas_manifest.json: {exc}"
        ) from exc
    if reference.path != EXTERNAL_SOURCE_PROVENANCE_RUN_PATH:
        raise ValueError(
            "atlas_manifest.json external provenance path must be "
            f"{EXTERNAL_SOURCE_PROVENANCE_RUN_PATH!r}"
        )
    if artifact_path != reference.path:
        raise ValueError(
            "atlas_manifest.json artifacts.external_source_provenance does not match "
            "the external provenance reference path"
        )
    _validate_export_source_file(
        run,
        EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
        required=True,
    )
    actual_sha256 = sha256_file(source_path)
    if actual_sha256 != reference.sha256:
        raise ValueError(
            "external source provenance sha256 does not match atlas_manifest.json: "
            f"expected {reference.sha256}, computed {actual_sha256}"
        )
    payload = _load_external_source_provenance(source_path)
    expected_reference = external_source_provenance_reference(
        payload,
        path=EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
        sha256=actual_sha256,
    )
    if reference != expected_reference:
        raise ValueError(
            "external source provenance identity does not match atlas_manifest.json"
        )
    return reference


def _validated_state_segment_rows(
    rows: list[dict] | None,
    source: Path,
) -> list[dict]:
    if rows is None:
        rows = []
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid state segment JSON on line {line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"invalid state segment record on line {line_number}: expected object"
                )
            rows.append(record)
    if not rows:
        raise ValueError("state segment must contain at least one frame")

    validated: list[dict] = []
    previous_time: float | None = None
    for index, row in enumerate(rows, start=1):
        try:
            frame = FrameStateModel.model_validate(row)
            if frame.ts_sim_ns is not None:
                if frame.ts_sim_ns < 0:
                    raise ValueError("ts_sim_ns must be non-negative")
                frame_time = float(frame.ts_sim_ns) / 1_000_000_000.0
            else:
                frame_time = float(frame.ts)
        except Exception as exc:
            raise ValueError(f"invalid state segment frame {index}: {exc}") from exc
        if not math.isfinite(frame_time):
            raise ValueError(f"invalid state segment frame {index}: non-finite time")
        if previous_time is not None and frame_time < previous_time:
            raise ValueError(
                f"state segment time decreases at frame {index}: "
                f"{frame_time} follows {previous_time}"
            )
        previous_time = frame_time
        validated.append(dict(row))
    return validated


def export_bundle(
    run_dir: str | Path,
    incident_id: str,
    out_zip: str | Path,
    state_segment_rows: list[dict] | None = None,
    *,
    overwrite: bool = False,
) -> Path:
    run = Path(run_dir)
    if run.is_symlink():
        raise ValueError(f"source run directory must not be a symlink: {run}")
    if not run.is_dir():
        raise ValueError(f"run directory does not exist: {run}")
    _validate_export_sources(run)
    run_manifest = {}
    manifest_path = run / "atlas_manifest.json"
    if manifest_path.exists():
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    external_provenance = _external_source_provenance_for_export(run, run_manifest)
    incident = next((item for item in _load_incidents(run) if item.incident_id == incident_id), None)
    if incident is None:
        raise ValueError(f"incident not found: {incident_id}")
    state_source = run / "state_segment.jsonl"
    if state_segment_rows is None and not state_source.is_file():
        fallback_rel = f"evidence_bundles/{incident_id}/state_segment.jsonl"
        _validate_export_source_file(run, fallback_rel, required=True)
        state_source = run / fallback_rel
    state_segment_rows = _validated_state_segment_rows(
        state_segment_rows,
        state_source,
    )
    out = Path(out_zip)
    if out.suffix.lower() != ".zip":
        raise ValueError(f"bundle output must end in .zip: {out}")
    bundle_dir = out.with_suffix("")
    run_resolved = run.resolve()
    generated_bundle_root = (run / "evidence_bundles").resolve()
    for destination in (out, bundle_dir):
        destination_resolved = destination.resolve()
        inside_source_run = run_resolved in destination_resolved.parents
        inside_generated_bundle_root = (
            destination_resolved == generated_bundle_root
            or generated_bundle_root in destination_resolved.parents
        )
        if (
            destination_resolved == run_resolved
            or destination_resolved in run_resolved.parents
            or (inside_source_run and not inside_generated_bundle_root)
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
        with (stage_bundle / "state_segment.jsonl").open("w", encoding="utf-8") as handle:
            for row in state_segment_rows:
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
        if external_provenance is not None:
            shutil.copyfile(
                run / EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
                stage_bundle / EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
            )
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
            "metriplane atlas bundle export "
            f"--incident-id {incident_id} --run-dir <atlas-run> --out <bundle.zip>\n",
            encoding="utf-8",
        )
        required_files = list(REQUIRED_BUNDLE_FILES)
        bundled_external_provenance = None
        if external_provenance is not None:
            required_files.append(EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH)
            bundled_external_provenance = external_provenance.model_copy(
                update={"path": EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH}
            )
        manifest = BundleManifest(
            bundle_id=f"bundle_{incident_id}",
            incident_id=incident_id,
            run_id=str(
                run_manifest.get("run_id")
                or (events[0].run_id if events else incident_id)
            ),
            required_files=required_files,
            external_source_provenance=bundled_external_provenance,
        )
        _json_dump(
            stage_bundle / "manifest.json",
            manifest.model_dump(exclude_none=True),
        )

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

        previous: dict[Path, Path] = {}
        published: list[Path] = []
        try:
            destinations = (bundle_dir, out)
            if not overwrite and any(
                destination.exists() or destination.is_symlink()
                for destination in destinations
            ):
                raise ValueError(
                    "refusing to replace bundle output created while staging "
                    "without --overwrite"
                )
            for index, destination in enumerate(destinations):
                if destination.exists() or destination.is_symlink():
                    backup = stage_root / f"previous-{index}"
                    os.replace(destination, backup)
                    previous[destination] = backup
            os.replace(stage_bundle, bundle_dir)
            published.append(bundle_dir)
            os.replace(stage_zip, out)
            published.append(out)
        except Exception:
            for destination in published:
                if destination.exists() or destination.is_symlink():
                    _remove_path(destination)
            for destination, backup in previous.items():
                if backup.exists() or backup.is_symlink():
                    os.replace(backup, destination)
            raise
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
            inventory, inventory_errors = _regular_file_inventory(
                root, "checksums.sha256"
            )
            errors.extend(inventory_errors)
            for required in REQUIRED_BUNDLE_FILES:
                required_path = root / required
                if required_path.is_symlink() or not required_path.is_file():
                    errors.append(f"missing required file: {required}")
            if not errors:
                manifest = BundleManifest.model_validate(json.loads((root / "manifest.json").read_text()))
                manifest_required: set[str] = set()
                for raw_rel in manifest.required_files:
                    rel = _safe_relative_path(raw_rel)
                    if rel in manifest_required:
                        errors.append(f"duplicate manifest required file: {rel}")
                        continue
                    manifest_required.add(rel)
                    if not (root / rel).is_file():
                        errors.append(f"manifest references missing required file: {rel}")
                missing_manifest_entries = set(REQUIRED_BUNDLE_FILES) - manifest_required
                for rel in sorted(missing_manifest_entries):
                    errors.append(f"manifest omits required file: {rel}")
                recorded, checksum_errors = _read_checksum_inventory(
                    root / "checksums.sha256"
                )
                errors.extend(checksum_errors)
                for rel in sorted(inventory - set(recorded)):
                    errors.append(f"file missing checksum entry: {rel}")
                for rel in sorted(set(recorded) - inventory):
                    errors.append(f"checksum references missing file: {rel}")
                for rel, digest in recorded.items():
                    path = root / rel
                    if rel in inventory and sha256_file(path) != digest:
                        errors.append(f"checksum mismatch: {rel}")

                external_reference = manifest.external_source_provenance
                external_present = EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH in inventory
                external_required = (
                    EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH in manifest_required
                )
                if external_reference is None:
                    if external_present or external_required:
                        errors.append(
                            "external source provenance file or requirement has no "
                            "manifest reference"
                        )
                else:
                    if external_reference.path != EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH:
                        errors.append(
                            "bundle external provenance path must be "
                            f"{EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH!r}"
                        )
                    if not external_required:
                        errors.append(
                            "bundle manifest external provenance is not listed in "
                            "required_files"
                        )
                    if not external_present:
                        errors.append(
                            "bundle manifest references missing external source provenance"
                        )
                    recorded_digest = recorded.get(
                        EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH
                    )
                    if (
                        recorded_digest is not None
                        and recorded_digest != external_reference.sha256
                    ):
                        errors.append(
                            "external source provenance reference sha256 does not match "
                            "checksums.sha256"
                        )
                    if external_present:
                        external_path = root / EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH
                        actual_digest = sha256_file(external_path)
                        if actual_digest != external_reference.sha256:
                            errors.append(
                                "external source provenance reference sha256 does not "
                                "match the bundled file"
                            )
                        try:
                            external_payload = _load_external_source_provenance(
                                external_path
                            )
                            expected_reference = external_source_provenance_reference(
                                external_payload,
                                path=EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
                                sha256=actual_digest,
                            )
                            if external_reference != expected_reference:
                                errors.append(
                                    "external source provenance identity does not match "
                                    "the bundle manifest reference"
                                )
                        except ValueError as exc:
                            errors.append(str(exc))
                try:
                    _validated_state_segment_rows(
                        None,
                        root / "state_segment.jsonl",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                events: list[AtlasEvent] = []
                for line_number, line in enumerate(
                    (root / "event_timeline.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines(),
                    start=1,
                ):
                    if not line.strip():
                        continue
                    try:
                        events.append(AtlasEvent.model_validate(json.loads(line)))
                    except Exception as exc:
                        errors.append(
                            f"invalid timeline event on line {line_number}: {exc}"
                        )

                timeline_ids = [event.event_id for event in events]
                duplicate_timeline_ids = sorted(
                    event_id
                    for event_id, count in Counter(timeline_ids).items()
                    if count > 1
                )
                for event_id in duplicate_timeline_ids:
                    errors.append(f"duplicate timeline event ID: {event_id}")

                incident = AtlasIncident.model_validate(
                    json.loads((root / "incident.json").read_text(encoding="utf-8"))
                )
                if manifest.incident_id != incident.incident_id:
                    errors.append(
                        "manifest incident_id does not match incident: "
                        f"{manifest.incident_id!r} != {incident.incident_id!r}"
                    )
                for event in events:
                    if event.run_id != manifest.run_id:
                        errors.append(
                            "manifest run_id does not match timeline event "
                            f"{event.event_id}: {manifest.run_id!r} != {event.run_id!r}"
                        )

                duplicate_incident_ids = sorted(
                    event_id
                    for event_id, count in Counter(incident.event_ids).items()
                    if count > 1
                )
                for event_id in duplicate_incident_ids:
                    errors.append(f"duplicate incident event ID: {event_id}")

                incident_event_ids = set(incident.event_ids)
                timeline_event_ids = set(timeline_ids)
                if not incident.event_ids:
                    errors.append("incident must reference at least one timeline event")
                if not events:
                    errors.append("event timeline must contain at least one event")
                if incident_event_ids != timeline_event_ids:
                    missing = sorted(incident_event_ids - timeline_event_ids)
                    extra = sorted(timeline_event_ids - incident_event_ids)
                    errors.append(
                        "incident event IDs do not exactly match timeline: "
                        f"missing={missing}, extra={extra}"
                    )
                for event in events:
                    if not incident.start_ts <= event.ts <= incident.end_ts:
                        errors.append(
                            "timeline event falls outside incident window: "
                            f"{event.event_id} at {event.ts} not in "
                            f"[{incident.start_ts}, {incident.end_ts}]"
                        )
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        errors.append(message)
    return {
        "schema_version": "metriplane.atlas.bundle_verifier.v1",
        "bundle": str(bundle),
        "pass": not errors,
        "errors": errors,
    }
