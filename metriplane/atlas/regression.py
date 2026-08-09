# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypeVar
import zipfile

import yaml

from metriplane.atlas.bundles import safe_extract, verify_bundle
from metriplane.atlas.models import AtlasIncident, RegressionSpec


_TActual = TypeVar("_TActual")


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
    bundle = Path(bundle_path).resolve()
    output = Path(out_path)
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
                "ts": event.get("ts"),
            }
            for event in events
        ],
        expected_incidents=[
            {
                "incident_type": incident.incident_type,
                "severity": incident.severity,
                "start_ts": incident.start_ts,
                "end_ts": incident.end_ts,
                "duration_s": incident.end_ts - incident.start_ts,
            }
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_bundle = Path(os.path.relpath(bundle, output.parent.resolve())).as_posix()
    except ValueError:  # Different Windows drives cannot be represented relatively.
        source_bundle = str(bundle)
    spec = spec.model_copy(update={"source_bundle": source_bundle})
    output.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=True), encoding="utf-8")
    return spec


def _resolve_source_bundle(spec_path: Path, source_bundle: str) -> Path:
    source = Path(source_bundle)
    if source.is_absolute():
        return source
    candidates = [(spec_path.parent / source).resolve(), (Path.cwd() / source).resolve()]
    candidates.extend((parent / source).resolve() for parent in spec_path.parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _tolerance(spec: RegressionSpec, name: str, errors: list[str]) -> float:
    value = spec.tolerances.get(name, 0.0)
    if not math.isfinite(value) or value < 0:
        errors.append(f"invalid {name} tolerance: {value}")
        return 0.0
    return value


def run_regression(spec_path: str | Path) -> dict:
    spec_file = Path(spec_path).resolve()
    spec = RegressionSpec.model_validate(yaml.safe_load(spec_file.read_text()) or {})
    bundle = _resolve_source_bundle(spec_file, spec.source_bundle)
    verify = verify_bundle(bundle)
    errors: list[str] = []
    if not verify["pass"]:
        errors.extend(f"bundle: {err}" for err in verify["errors"])
        return _result(spec, errors)

    event_time_tolerance = _tolerance(spec, "event_time_s", errors)
    duration_tolerance = _tolerance(spec, "duration_s", errors)
    if errors:
        return _result(spec, errors)

    with _bundle_root(bundle) as root:
        actual_events, actual_incidents = _replay_bundle_logic(root, spec, errors)
        if errors:
            return _result(spec, errors)

    event_matches = _maximum_one_to_one_matching(
        spec.expected_events,
        actual_events,
        lambda expected, actual: _event_matches(
            expected, actual, event_time_tolerance
        ),
    )
    for index, expected in enumerate(spec.expected_events):
        if index not in event_matches:
            errors.append(f"missing expected event: {expected}")
    incident_matches = _maximum_one_to_one_matching(
        spec.expected_incidents,
        actual_incidents,
        lambda expected, actual: _incident_matches(
            expected,
            actual,
            event_time_tolerance,
            duration_tolerance,
        ),
    )
    for index, expected in enumerate(spec.expected_incidents):
        if index in incident_matches:
            continue
        same_type = [
            incident for incident in actual_incidents
            if incident.incident_type == expected.get("incident_type")
        ]
        if not same_type:
            errors.append(f"missing expected incident type: {expected.get('incident_type')}")
            continue
        if expected.get("severity") and not any(
            incident.severity == expected.get("severity") for incident in same_type
        ):
            errors.append(f"incident severity mismatch: {expected.get('severity')}")
            continue
        errors.append(f"missing distinct expected incident: {expected}")
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


def _maximum_one_to_one_matching(
    expected: Sequence[dict[str, Any]],
    actual: Sequence[_TActual],
    predicate: Callable[[dict[str, Any], _TActual], bool],
) -> dict[int, int]:
    """Return a maximum mapping from expected indexes to unique actual indexes."""
    actual_to_expected: dict[int, int] = {}

    def assign(expected_index: int, seen_actual: set[int]) -> bool:
        for actual_index, actual_item in enumerate(actual):
            if actual_index in seen_actual or not predicate(
                expected[expected_index], actual_item
            ):
                continue
            seen_actual.add(actual_index)
            previous_expected = actual_to_expected.get(actual_index)
            if previous_expected is None or assign(previous_expected, seen_actual):
                actual_to_expected[actual_index] = expected_index
                return True
        return False

    for expected_index in range(len(expected)):
        assign(expected_index, set())

    return {
        expected_index: actual_index
        for actual_index, expected_index in actual_to_expected.items()
    }


def _event_matches(
    expected: dict[str, Any],
    actual: dict[str, Any],
    event_time_tolerance: float = 0.0,
) -> bool:
    for key in ("event_type", "asset_id", "process_step_id", "severity", "zone_id", "station_id"):
        if expected.get(key) is not None and expected.get(key) != actual.get(key):
            return False
    if expected.get("ts") is not None:
        if actual.get("ts") is None:
            return False
        if abs(float(expected["ts"]) - float(actual["ts"])) > event_time_tolerance:
            return False
    return True


def _incident_matches(
    expected: dict[str, Any],
    actual: AtlasIncident,
    event_time_tolerance: float = 0.0,
    duration_tolerance: float = 0.0,
) -> bool:
    if actual.incident_type != expected.get("incident_type"):
        return False
    if expected.get("severity") and actual.severity != expected.get("severity"):
        return False
    for key in ("start_ts", "end_ts"):
        if expected.get(key) is not None:
            if abs(float(expected[key]) - float(getattr(actual, key))) > event_time_tolerance:
                return False
    if expected.get("duration_s") is not None:
        actual_duration = actual.end_ts - actual.start_ts
        if abs(float(expected["duration_s"]) - actual_duration) > duration_tolerance:
            return False
    return True


def _result(spec: RegressionSpec, errors: list[str]) -> dict:
    return {
        "schema_version": "metriplane.atlas.regression_result.v1",
        "test_id": spec.test_id,
        "pass": not errors,
        "errors": errors,
    }
