# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import shutil
from tempfile import TemporaryDirectory
import zipfile
from pathlib import Path

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


def safe_extract(archive: zipfile.ZipFile, dest: str | Path) -> None:
    root = Path(dest).resolve()
    for member in archive.infolist():
        target = (root / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"unsafe zip path: {member.filename}")
    archive.extractall(root)


def export_bundle(
    run_dir: str | Path,
    incident_id: str,
    out_zip: str | Path,
    state_segment_rows: list[dict] | None = None,
) -> Path:
    run = Path(run_dir)
    run_manifest = {}
    manifest_path = run / "atlas_manifest.json"
    if manifest_path.exists():
        run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    incident = next((item for item in _load_incidents(run) if item.incident_id == incident_id), None)
    if incident is None:
        raise ValueError(f"incident not found: {incident_id}")
    out = Path(out_zip)
    bundle_dir = out.with_suffix("")
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    _json_dump(bundle_dir / "incident.json", incident.model_dump())
    events = [
        event for event in read_events(run / "physical_event_log.jsonl")
        if event.event_id in set(incident.event_ids)
    ]
    with (bundle_dir / "event_timeline.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.model_dump(), sort_keys=True) + "\n")
    if state_segment_rows is None:
        state_segment_rows = []
    with (bundle_dir / "state_segment.jsonl").open("w", encoding="utf-8") as handle:
        for row in state_segment_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    shutil.copyfile(run / "reality_graph.json", bundle_dir / "reality_graph_excerpt.json")
    shutil.copyfile(run / "process_trace.json", bundle_dir / "process_trace_excerpt.json")
    (bundle_dir / "configs").mkdir(exist_ok=True)
    for name in ("assets.yaml", "workspace.yaml", "process.yaml", "contracts.yaml", "work_orders.csv"):
        src = run / "configs" / name
        if src.exists():
            shutil.copyfile(src, bundle_dir / "configs" / name)
    (bundle_dir / "reports").mkdir(exist_ok=True)
    shutil.copyfile(run / "cell_truth_report.md", bundle_dir / "reports" / "cell_truth_report.md")
    (bundle_dir / "generated").mkdir(exist_ok=True)
    (bundle_dir / "provenance").mkdir(exist_ok=True)
    (bundle_dir / "limitations.md").write_text(
        "# Limitations\n\n"
        "- Derived from calibrated planar state streams.\n"
        "- Requires tracked/tagged assets.\n"
        "- Not a certified safety or quality decision system.\n",
        encoding="utf-8",
    )
    (bundle_dir / "replay_command.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo 'Replay state segment with metriplane atlas test or inspect state_segment.jsonl'\n",
        encoding="utf-8",
    )
    (bundle_dir / "provenance" / "command.txt").write_text(
        f"metriplane atlas bundle export --incident-id {incident_id} --run-dir {run} --out {out}\n",
        encoding="utf-8",
    )
    manifest = BundleManifest(
        bundle_id=f"bundle_{incident_id}",
        incident_id=incident_id,
        run_id=str(run_manifest.get("run_id") or incident_id),
        required_files=list(REQUIRED_BUNDLE_FILES),
    )
    _json_dump(bundle_dir / "manifest.json", manifest.model_dump())

    checksum_paths = [path for path in sorted(bundle_dir.rglob("*")) if path.is_file() and path.name != "checksums.sha256"]
    with (bundle_dir / "checksums.sha256").open("w", encoding="utf-8") as handle:
        for path in checksum_paths:
            handle.write(f"{sha256_file(path)}  {path.relative_to(bundle_dir).as_posix()}\n")
    _zip_dir(bundle_dir, out)
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


def verify_bundle(bundle_path: str | Path) -> dict:
    bundle = Path(bundle_path)
    errors: list[str] = []
    try:
        with _unpack_bundle(bundle) as root:
            for required in REQUIRED_BUNDLE_FILES:
                if not (root / required).exists():
                    errors.append(f"missing required file: {required}")
            if not errors:
                manifest = BundleManifest.model_validate(json.loads((root / "manifest.json").read_text()))
                if manifest.schema_version != "metriplane.atlas.evidence_bundle.v1":
                    errors.append(f"unsupported schema_version: {manifest.schema_version}")
                recorded: dict[str, str] = {}
                for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    digest, rel = line.split(maxsplit=1)
                    recorded[rel.lstrip("*")] = digest
                for rel, digest in recorded.items():
                    path = root / rel
                    if not path.exists():
                        errors.append(f"checksum references missing file: {rel}")
                    elif sha256_file(path) != digest:
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
    except ValueError as exc:
        errors.append(str(exc))
    return {
        "schema_version": "metriplane.atlas.bundle_verifier.v1",
        "bundle": str(bundle),
        "pass": not errors,
        "errors": errors,
    }
