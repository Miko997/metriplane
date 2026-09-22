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

from metriplane.archive_safety import (
    DEFAULT_LIMITS,
    ResourceLimits,
    copy_relative_regular_file,
    stage_directory,
    stage_zip_archive,
    staged_path,
)
from metriplane.atlas.event_ledger import read_events
from metriplane.atlas.models import (
    ATLAS_LIMITATION_STATEMENTS,
    EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
    EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
    AtlasEvent,
    AtlasIncident,
    BundleManifest,
    ExternalSourceProvenanceReference,
    external_source_provenance_reference,
)
from metriplane.publication import (
    PublicationError,
    PublicationTarget,
    publish_transaction,
)
from metriplane.schema import FrameStateModel
from metriplane.strict_parsing import iter_jsonl_path, load_json_path

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
    "requirement_assessment.json",
)

REQUIREMENT_ASSESSMENT_PATH = "requirement_assessment.json"

MAX_ZIP_MEMBERS = DEFAULT_LIMITS.max_entries
MAX_ZIP_MEMBER_BYTES = DEFAULT_LIMITS.max_file_bytes
MAX_ZIP_TOTAL_BYTES = DEFAULT_LIMITS.max_total_bytes
MAX_ZIP_COMPRESSION_RATIO = DEFAULT_LIMITS.max_compression_ratio
_CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64}) ([ *])(.+)$")


def _archive_limits() -> ResourceLimits:
    return ResourceLimits(
        max_entries=MAX_ZIP_MEMBERS,
        max_file_bytes=MAX_ZIP_MEMBER_BYTES,
        max_total_bytes=MAX_ZIP_TOTAL_BYTES,
        max_compression_ratio=MAX_ZIP_COMPRESSION_RATIO,
    )


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
        value = load_json_path(
            path,
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
    for value in iter_jsonl_path(run_dir / "incidents.jsonl"):
        incidents.append(AtlasIncident.model_validate(value))
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


def safe_extract(archive: zipfile.ZipFile, dest: str | Path) -> None:
    root = Path(dest).absolute()
    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
        raise ValueError("ZIP staging destination must be a real empty directory")
    root.rmdir()
    stage_zip_archive(archive, root, limits=_archive_limits())


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
        for line_number, record in enumerate(iter_jsonl_path(source), start=1):
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
        run_manifest = load_json_path(manifest_path)
    external_provenance = _external_source_provenance_for_export(run, run_manifest)
    has_assessment = (
        (run / REQUIREMENT_ASSESSMENT_PATH).exists()
        or run_manifest.get("requirement_assessment_sha256") is not None
        or "requirement_assessment" in run_manifest.get("artifacts", {})
    )
    assessment = None
    if has_assessment:
        from metriplane.atlas.run_assessment import read_run_assessment

        assessment = read_run_assessment(run)
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
        include_assessment = assessment is not None and (
            sha256_file(stage_bundle / "state_segment.jsonl")
            == assessment["evidence_sha256"]["state_segment.jsonl"]
        )
        assessment_omitted = has_assessment and not include_assessment
        copy_relative_regular_file(
            run,
            "reality_graph.json",
            stage_bundle,
            "reality_graph_excerpt.json",
            limits=_archive_limits(),
        )
        copy_relative_regular_file(
            run,
            "process_trace.json",
            stage_bundle,
            "process_trace_excerpt.json",
            limits=_archive_limits(),
        )
        (stage_bundle / "configs").mkdir(exist_ok=True)
        for name in ("assets.yaml", "workspace.yaml", "process.yaml", "contracts.yaml", "work_orders.csv"):
            src = run / "configs" / name
            if src.exists():
                copy_relative_regular_file(
                    run,
                    f"configs/{name}",
                    stage_bundle,
                    f"configs/{name}",
                    limits=_archive_limits(),
                )
        (stage_bundle / "reports").mkdir(exist_ok=True)
        copy_relative_regular_file(
            run,
            "cell_truth_report.md",
            stage_bundle,
            "reports/cell_truth_report.md",
            limits=_archive_limits(),
        )
        if assessment_omitted:
            with (stage_bundle / "reports" / "cell_truth_report.md").open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n## Custom exported segment\n\n"
                    "The report above describes the complete source run. This bundle "
                    "contains a custom recorded-state segment, so the full-run "
                    "requirement_assessment.json is omitted. Its requirement outcomes "
                    "and completion times do not assess this custom segment.\n"
                )
        (stage_bundle / "generated").mkdir(exist_ok=True)
        (stage_bundle / "provenance").mkdir(exist_ok=True)
        if include_assessment:
            copy_relative_regular_file(
                run,
                REQUIREMENT_ASSESSMENT_PATH,
                stage_bundle,
                REQUIREMENT_ASSESSMENT_PATH,
                limits=_archive_limits(),
            )
        if external_provenance is not None:
            copy_relative_regular_file(
                run,
                EXTERNAL_SOURCE_PROVENANCE_RUN_PATH,
                stage_bundle,
                EXTERNAL_SOURCE_PROVENANCE_BUNDLE_PATH,
                limits=_archive_limits(),
            )
        (stage_bundle / "limitations.md").write_text(
            "# Limitations\n\n"
            + "".join(f"- {statement}\n" for statement in ATLAS_LIMITATION_STATEMENTS)
            + (
                "- Custom exported segment: full-run requirement assessment omitted; "
                "the copied source report does not assess this segment.\n"
                if assessment_omitted else ""
            ),
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
        if include_assessment:
            required_files.append(REQUIREMENT_ASSESSMENT_PATH)
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
        validated_stage_bundle = stage_root / "validated-bundle"
        stage_directory(
            stage_bundle,
            validated_stage_bundle,
            limits=_archive_limits(),
        )
        stage_bundle = validated_stage_bundle
        _zip_dir(stage_bundle, stage_zip)

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
            publish_transaction(
                [
                    PublicationTarget(stage_bundle, bundle_dir),
                    PublicationTarget(stage_zip, out),
                ],
                overwrite=overwrite,
                replace_fn=os.replace,
            )
        except PublicationError as exc:
            if not overwrite and "without overwrite" in str(exc):
                raise ValueError(
                    "refusing to replace bundle output created while staging "
                    "without --overwrite"
                ) from exc
            raise
    return out


@contextmanager
def _unpack_bundle(bundle: Path) -> Iterator[Path]:
    with staged_path(bundle, limits=_archive_limits()) as root:
        yield root


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


def _verify_bundled_assessment(root: Path, manifest: BundleManifest) -> list[str]:
    path = root / REQUIREMENT_ASSESSMENT_PATH
    if not path.exists():
        return []
    from metriplane.atlas.assessment import RequirementAssessment
    from metriplane.atlas.run_assessment import RUN_ASSESSMENT_SCHEMA

    errors: list[str] = []
    if REQUIREMENT_ASSESSMENT_PATH not in manifest.required_files:
        errors.append("bundled requirement assessment is not listed in required_files")
    payload = load_json_path(
        path,
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=_reject_nonfinite_json_constant,
    )
    if not isinstance(payload, dict) or payload.get("schema_version") != RUN_ASSESSMENT_SCHEMA:
        return [*errors, "unsupported bundled requirement assessment schema"]
    assessment = RequirementAssessment.model_validate(payload["process_assessment"])
    if assessment.run_id != manifest.run_id:
        errors.append("bundled requirement assessment run_id does not match manifest")
    evidence = payload.get("evidence_sha256", {})
    # A bundle retains the full state and configs but only an incident-specific
    # event excerpt. Check the source bindings that are actually present here.
    for name in (
        "state_segment.jsonl", "configs/assets.yaml", "configs/workspace.yaml",
        "configs/process.yaml", "configs/contracts.yaml", "configs/work_orders.csv",
    ):
        retained = root / name
        actual = sha256_file(retained) if retained.is_file() else None
        expected = evidence.get(name)
        required = name in {
            "state_segment.jsonl", "configs/assets.yaml", "configs/workspace.yaml",
            "configs/process.yaml",
        }
        if (required and actual is None) or expected != actual:
            errors.append(f"bundled requirement assessment state/config binding mismatch: {name}")
    return errors


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
                manifest = BundleManifest.model_validate(load_json_path(root / "manifest.json"))
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

                errors.extend(_verify_bundled_assessment(root, manifest))

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
                for line_number, value in enumerate(
                    iter_jsonl_path(root / "event_timeline.jsonl"), start=1
                ):
                    try:
                        events.append(AtlasEvent.model_validate(value))
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

                incident = AtlasIncident.model_validate(load_json_path(root / "incident.json"))
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
