# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metriplane_source_adapter_sdk import canonical_json_bytes

from .clock import ClockError, parse_timestamp_ns
from .constants import EXPECTED_ORDER, FIRST_STATUS_TIMESTAMP, IDENTITY_TIMESTAMP
from .datum import DatumError, effective_path_datum, finite_number, parse_quaternion, require_uuid
from .models import (
    IdentityRecord,
    Location,
    PredictedLocation,
    SourceFrame,
    SourceTrace,
    StatusRecord,
)


class SourceValidationError(ValueError):
    """Raised for strict source-profile validation failures."""


_IDENTITY_FIELDS = {
    "uuid",
    "timestamp",
    "manufacturerName",
    "robotModel",
    "robotSerialNumber",
    "baseRobotEnvelope",
}
_IDENTITY_REQUIRED = {
    "uuid",
    "timestamp",
    "manufacturerName",
    "robotModel",
    "robotSerialNumber",
    "baseRobotEnvelope",
}
_STATUS_FIELDS = {
    "uuid",
    "timestamp",
    "operationalState",
    "location",
    "velocity",
    "batteryPercentage",
    "remainingRunTime",
    "loadPercentageStillAvailable",
    "errorCodes",
    "destinations",
    "path",
}
_STATUS_REQUIRED = {"uuid", "timestamp", "operationalState", "location"}
_OPERATIONAL_STATES = {
    "navigating",
    "idle",
    "disabled",
    "offline",
    "charging",
    "waitingHumanEvent",
    "waitingExternalEvent",
    "waitingInternalEvent",
    "manualOverride",
}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SourceValidationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _nonfinite(value: str) -> None:
    raise SourceValidationError(f"nonfinite JSON number is prohibited: {value}")


def _jsonl(path: Path, *, label: str) -> tuple[list[dict[str, Any]], bytes]:
    if path.is_symlink() or not path.is_file():
        raise SourceValidationError(f"{label}: required regular non-symlink file is missing")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceValidationError(f"{label}: source must be UTF-8") from exc
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise SourceValidationError(f"{label}: blank JSONL line {line_number} is prohibited")
        try:
            value = json.loads(line, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        except (json.JSONDecodeError, SourceValidationError) as exc:
            raise SourceValidationError(
                f"{label}: malformed source JSON on line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise SourceValidationError(f"{label}: line {line_number} must be a JSON object")
        records.append(value)
    if not records:
        raise SourceValidationError(f"{label}: source contains no records")
    return records, data


def _strict_fields(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    field: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing or unknown:
        raise SourceValidationError(
            f"{field}: missing={missing}; unexpected source fields={unknown}"
        )


def _nonblank(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceValidationError(f"{field}: nonblank string is required")
    return value


def _vector3(
    value: object,
    *,
    field: str,
    required_xy: bool = False,
    require_z: bool = False,
) -> tuple[float, float, float]:
    if not isinstance(value, Mapping):
        raise SourceValidationError(f"{field}: object is required")
    required = {"x", "y"} if required_xy else {"x", "y", "z"}
    if require_z:
        required.add("z")
    allowed = {"x", "y", "z"}
    _strict_fields(value, allowed=allowed, required=required, field=field)
    return (
        finite_number(value["x"], field=f"{field}.x"),
        finite_number(value["y"], field=f"{field}.y"),
        finite_number(value.get("z", 0.0), field=f"{field}.z"),
    )


def _parse_identity(value: dict[str, Any], *, index: int) -> IdentityRecord:
    field = f"identity[{index}]"
    _strict_fields(value, allowed=_IDENTITY_FIELDS, required=_IDENTITY_REQUIRED, field=field)
    timestamp = _nonblank(value["timestamp"], field=f"{field}.timestamp")
    if timestamp != IDENTITY_TIMESTAMP:
        raise SourceValidationError(f"{field}.timestamp: frozen identity timestamp differs")
    return IdentityRecord(
        uuid=require_uuid(value["uuid"], field=f"{field}.uuid"),
        timestamp=timestamp,
        timestamp_ns=parse_timestamp_ns(timestamp, field=f"{field}.timestamp"),
        manufacturer_name=_nonblank(value["manufacturerName"], field=f"{field}.manufacturerName"),
        robot_model=_nonblank(value["robotModel"], field=f"{field}.robotModel"),
        robot_serial_number=_nonblank(
            value["robotSerialNumber"], field=f"{field}.robotSerialNumber"
        ),
        base_robot_envelope=_vector3(
            value["baseRobotEnvelope"], field=f"{field}.baseRobotEnvelope", required_xy=True
        ),
        raw=value,
    )


def _parse_prediction(
    value: object,
    *,
    current_datum: str,
    field: str,
) -> PredictedLocation:
    if not isinstance(value, Mapping):
        raise SourceValidationError(f"{field}: predicted location object is required")
    allowed = {"timestamp", "x", "y", "z", "angle", "planarDatumUUID"}
    required = {"timestamp", "x", "y", "angle"}
    _strict_fields(value, allowed=allowed, required=required, field=field)
    timestamp = _nonblank(value["timestamp"], field=f"{field}.timestamp")
    declared, effective = effective_path_datum(
        value.get("planarDatumUUID"), current=current_datum, field=f"{field}.planarDatumUUID"
    )
    return PredictedLocation(
        timestamp=timestamp,
        timestamp_ns=parse_timestamp_ns(timestamp, field=f"{field}.timestamp"),
        x=finite_number(value["x"], field=f"{field}.x"),
        y=finite_number(value["y"], field=f"{field}.y"),
        z=finite_number(value.get("z", 0.0), field=f"{field}.z"),
        angle=parse_quaternion(value["angle"], field=f"{field}.angle"),
        declared_planar_datum=declared,
        effective_planar_datum=effective,
    )


def _optional_status_fields(value: Mapping[str, Any], *, field: str) -> None:
    if "velocity" in value:
        velocity = value["velocity"]
        if not isinstance(velocity, Mapping):
            raise SourceValidationError(f"{field}.velocity: object is required")
        _strict_fields(velocity, allowed={"linear"}, required={"linear"}, field=f"{field}.velocity")
        finite_number(velocity["linear"], field=f"{field}.velocity.linear")
    for name, minimum, maximum in (
        ("batteryPercentage", 0.0, 100.0),
        ("remainingRunTime", 0.0, math.inf),
        ("loadPercentageStillAvailable", 0.0, 100.0),
    ):
        if name in value:
            number = finite_number(value[name], field=f"{field}.{name}")
            if not minimum <= number <= maximum:
                raise SourceValidationError(f"{field}.{name}: value outside allowed range")
    if "errorCodes" in value:
        errors = value["errorCodes"]
        if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
            raise SourceValidationError(f"{field}.errorCodes: unique string array is required")
        if len(errors) != len(set(errors)):
            raise SourceValidationError(f"{field}.errorCodes: duplicate values are prohibited")


def _parse_status(value: dict[str, Any], *, index: int) -> StatusRecord:
    field = f"status[{index}]"
    _strict_fields(value, allowed=_STATUS_FIELDS, required=_STATUS_REQUIRED, field=field)
    uuid_value = require_uuid(value["uuid"], field=f"{field}.uuid")
    timestamp = _nonblank(value["timestamp"], field=f"{field}.timestamp")
    state = value["operationalState"]
    if state not in _OPERATIONAL_STATES:
        raise SourceValidationError(f"{field}.operationalState: unsupported value")
    location = value["location"]
    if not isinstance(location, Mapping):
        raise SourceValidationError(f"{field}.location: complete current location is required")
    _strict_fields(
        location,
        allowed={"x", "y", "z", "angle", "planarDatum"},
        required={"x", "y", "z", "angle", "planarDatum"},
        field=f"{field}.location",
    )
    current_datum = require_uuid(location["planarDatum"], field=f"{field}.location.planarDatum")
    parsed_location = Location(
        x=finite_number(location["x"], field=f"{field}.location.x"),
        y=finite_number(location["y"], field=f"{field}.location.y"),
        z=finite_number(location["z"], field=f"{field}.location.z"),
        angle=parse_quaternion(location["angle"], field=f"{field}.location.angle"),
        planar_datum=current_datum,
    )
    _optional_status_fields(value, field=field)
    predictions: dict[str, tuple[PredictedLocation, ...]] = {}
    for name in ("path", "destinations"):
        raw = value.get(name, [])
        if not isinstance(raw, list) or len(raw) > 10:
            raise SourceValidationError(f"{field}.{name}: array with at most 10 items is required")
        parsed = tuple(
            _parse_prediction(
                item, current_datum=current_datum, field=f"{field}.{name}[{position}]"
            )
            for position, item in enumerate(raw)
        )
        fingerprints = [
            canonical_json_bytes(dict(item)) if isinstance(item, Mapping) else b"" for item in raw
        ]
        if len(fingerprints) != len(set(fingerprints)):
            raise SourceValidationError(f"{field}.{name}: duplicate predictions are prohibited")
        predictions[name] = parsed
    return StatusRecord(
        uuid=uuid_value,
        timestamp=timestamp,
        timestamp_ns=parse_timestamp_ns(timestamp, field=f"{field}.timestamp"),
        operational_state=state,
        location=parsed_location,
        path=predictions["path"],
        destinations=predictions["destinations"],
        raw=value,
    )


def load_source(
    source_root: str | Path,
    *,
    expected_datum: str,
    frame_interval_ns: int,
    entity_order: tuple[str, ...],
) -> SourceTrace:
    root = Path(source_root)
    if root.is_symlink() or not root.is_dir():
        raise SourceValidationError("source root must be a regular non-symlink directory")
    variant = root.name
    if variant not in {"incident", "control"}:
        raise SourceValidationError("source root basename must be incident or control")
    identity_values, identity_bytes = _jsonl(root / "identity.jsonl", label="identity report")
    status_values, status_bytes = _jsonl(root / "status.jsonl", label="status report")
    identities = tuple(
        _parse_identity(value, index=index) for index, value in enumerate(identity_values)
    )
    if len(identities) != 2:
        raise SourceValidationError("identity report must contain exactly two AMRs")
    identity_ids = tuple(item.uuid for item in identities)
    if identity_ids != entity_order or identity_ids != EXPECTED_ORDER:
        raise SourceValidationError("identity UUIDs must match deterministic configured order")
    if len(set(identity_ids)) != len(identity_ids):
        raise SourceValidationError("identity UUID must be stable and unique")
    status_records = tuple(
        _parse_status(value, index=index) for index, value in enumerate(status_values)
    )
    if any(item.uuid not in set(identity_ids) for item in status_records):
        raise SourceValidationError("status UUID without matching identity")
    previous = -1
    seen: dict[tuple[str, int], bytes] = {}
    groups: dict[int, list[StatusRecord]] = {}
    ordered_timestamps: list[int] = []
    for record in status_records:
        if record.timestamp_ns < previous:
            raise SourceValidationError("status timestamps are nonmonotonic; input is not sorted")
        previous = record.timestamp_ns
        key = (record.uuid, record.timestamp_ns)
        fingerprint = canonical_json_bytes(record.raw)
        if key in seen:
            kind = "duplicate" if seen[key] == fingerprint else "conflicting duplicate state"
            raise SourceValidationError(f"{kind} for robot/timestamp")
        seen[key] = fingerprint
        if record.timestamp_ns not in groups:
            groups[record.timestamp_ns] = []
            ordered_timestamps.append(record.timestamp_ns)
        groups[record.timestamp_ns].append(record)
    if len(status_records) != 18 or len(ordered_timestamps) != 9:
        raise SourceValidationError("frozen profile requires 18 statuses at 9 timestamps")
    origin = parse_timestamp_ns(FIRST_STATUS_TIMESTAMP, field="frozen first status timestamp")
    if ordered_timestamps[0] != origin:
        raise SourceValidationError("first status frame must be the frozen evaluation origin")
    frames: list[SourceFrame] = []
    for index, timestamp_ns in enumerate(ordered_timestamps):
        expected_timestamp = origin + index * frame_interval_ns
        if timestamp_ns != expected_timestamp:
            raise SourceValidationError("frame gap must be exactly 1,000,000,000 ns")
        records = groups[timestamp_ns]
        ids = tuple(record.uuid for record in records)
        if ids != entity_order:
            missing = sorted(set(entity_order) - set(ids))
            unknown = sorted(set(ids) - set(entity_order))
            raise SourceValidationError(
                f"source snapshot incomplete or entity order invalid; missing={missing}; unknown={unknown}"
            )
        datums = {record.location.planar_datum for record in records}
        if len(datums) != 1:
            raise SourceValidationError("two process-relevant AMRs use different datums")
        if datums != {expected_datum}:
            raise SourceValidationError(
                "current location datum changes or differs from configured datum"
            )
        frames.append(SourceFrame(timestamp_ns=timestamp_ns, statuses=tuple(records)))
    for record in status_records:
        for prediction in (*record.path, *record.destinations):
            if prediction.timestamp_ns < record.timestamp_ns:
                raise SourceValidationError("predicted timestamp precedes current observation")
    return SourceTrace(
        source_root=root.resolve(),
        variant=variant,
        identities=identities,
        status_records=status_records,
        frames=tuple(frames),
        identity_bytes=identity_bytes,
        status_bytes=status_bytes,
        identity_sha256=hashlib.sha256(identity_bytes).hexdigest(),
        status_sha256=hashlib.sha256(status_bytes).hexdigest(),
    )


__all__ = ["ClockError", "DatumError", "SourceValidationError", "load_source"]
