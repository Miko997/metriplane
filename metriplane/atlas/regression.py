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

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.models import AtlasIncident, RegressionSpec


@contextmanager
def _bundle_root(bundle: Path) -> Iterator[Path]:
    if bundle.is_dir():
        yield bundle
        return
    with TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(tmp)
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
        actual_events = [
            json.loads(line)
            for line in (root / "event_timeline.jsonl").read_text().splitlines()
            if line.strip()
        ]
        incident = AtlasIncident.model_validate(json.loads((root / "incident.json").read_text()))

    for expected in spec.expected_events:
        if not any(_event_matches(expected, actual) for actual in actual_events):
            errors.append(f"missing expected event: {expected}")
    for expected in spec.expected_incidents:
        if incident.incident_type != expected.get("incident_type"):
            errors.append(f"missing expected incident type: {expected.get('incident_type')}")
        if expected.get("severity") and incident.severity != expected.get("severity"):
            errors.append(f"incident severity mismatch: {expected.get('severity')}")
    return _result(spec, errors)


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
