# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Iterator
import zipfile

import yaml

from metriplane.atlas.bundles import safe_extract, verify_bundle
from metriplane.atlas.models import AtlasIncident, RegressionSpec


@contextmanager
def _bundle_root(bundle: Path) -> Iterator[Path]:
    if bundle.is_dir():
        yield bundle
        return
    with TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as archive:
            safe_extract(archive, tmp)
        yield Path(tmp)


def create_regression_from_bundle(bundle_path: str | Path, out_path: str | Path) -> RegressionSpec:
    bundle = Path(bundle_path)
    with _bundle_root(bundle) as root:
        incident = AtlasIncident.model_validate(json.loads((root / "incident.json").read_text()))
        events = [
            json.loads(line)
            for line in (root / "event_timeline.jsonl").read_text().splitlines()
            if line.strip()
        ]
    spec = RegressionSpec(
        test_id=f"{incident.incident_type}_{incident.incident_id}",
        source_bundle=str(bundle),
        expected_events=[
            {
                "event_type": event["event_type"],
                "asset_id": event.get("asset_id"),
                "process_step_id": event.get("process_step_id"),
                "severity": event.get("severity"),
            }
            for event in events
        ],
        expected_incidents=[
            {
                "incident_type": incident.incident_type,
                "severity": incident.severity,
            }
        ],
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(yaml.safe_dump(spec.model_dump(), sort_keys=True), encoding="utf-8")
    return spec


def run_regression(spec_path: str | Path) -> dict:
    spec = RegressionSpec.model_validate(yaml.safe_load(Path(spec_path).read_text()) or {})
    verify = verify_bundle(spec.source_bundle)
    errors: list[str] = []
    if not verify["pass"]:
        errors.extend(f"bundle: {err}" for err in verify["errors"])
        return _result(spec, errors)

    with _bundle_root(Path(spec.source_bundle)) as root:
        actual_events, actual_incidents = _replay_bundle_logic(root, spec, errors)
        if errors:
            return _result(spec, errors)

    for expected in spec.expected_events:
        if not any(_event_matches(expected, actual) for actual in actual_events):
            errors.append(f"missing expected event: {expected}")
    for expected in spec.expected_incidents:
        matches = [
            incident for incident in actual_incidents
            if incident.incident_type == expected.get("incident_type")
        ]
        if not matches:
            errors.append(f"missing expected incident type: {expected.get('incident_type')}")
            continue
        if expected.get("severity") and not any(
            incident.severity == expected.get("severity") for incident in matches
        ):
            errors.append(f"incident severity mismatch: {expected.get('severity')}")
    return _result(spec, errors)


def _replay_bundle_logic(root: Path, spec: RegressionSpec, errors: list[str]) -> tuple[list[dict], list[AtlasIncident]]:
    state_segment = root / "state_segment.jsonl"
    configs = root / "configs"
    required_configs = ["assets.yaml", "workspace.yaml", "process.yaml"]
    if state_segment.exists() and all((configs / name).exists() for name in required_configs):
        try:
            from metriplane.atlas.event_ledger import read_events
            from metriplane.atlas.runtime import run_atlas

            with TemporaryDirectory() as tmp:
                out_dir = Path(tmp) / "regression_replay"
                run_atlas(
                    state_segment,
                    configs,
                    out_dir,
                    run_id=f"regression_{spec.test_id[:48]}",
                    overwrite=True,
                )
                actual_events = [
                    event.model_dump()
                    for event in read_events(out_dir / "physical_event_log.jsonl")
                ]
                actual_incidents = [
                    AtlasIncident.model_validate(json.loads(line))
                    for line in (out_dir / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                return actual_events, actual_incidents
        except Exception as exc:
            errors.append(f"pipeline replay failed: {type(exc).__name__}: {exc}")
            return [], []

    actual_events = [
        json.loads(line)
        for line in (root / "event_timeline.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual_incidents = [AtlasIncident.model_validate(json.loads((root / "incident.json").read_text(encoding="utf-8")))]
    errors.append("bundle lacks state_segment.jsonl or Atlas configs; used stored records only")
    return actual_events, actual_incidents


def _event_matches(expected: dict, actual: dict) -> bool:
    for key in ("event_type", "asset_id", "process_step_id", "severity", "zone_id", "station_id"):
        if expected.get(key) is not None and expected.get(key) != actual.get(key):
            return False
    return True


def _result(spec: RegressionSpec, errors: list[str]) -> dict:
    return {
        "schema_version": "metriplane.atlas.regression_result.v1",
        "test_id": spec.test_id,
        "pass": not errors,
        "errors": errors,
    }
