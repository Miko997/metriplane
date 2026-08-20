# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Quaternion:
    x: float
    y: float
    z: float
    w: float


@dataclass(frozen=True)
class Location:
    x: float
    y: float
    z: float
    angle: Quaternion
    planar_datum: str


@dataclass(frozen=True)
class PredictedLocation:
    timestamp: str
    timestamp_ns: int
    x: float
    y: float
    z: float
    angle: Quaternion
    declared_planar_datum: str | None
    effective_planar_datum: str


@dataclass(frozen=True)
class IdentityRecord:
    uuid: str
    timestamp: str
    timestamp_ns: int
    manufacturer_name: str
    robot_model: str
    robot_serial_number: str
    base_robot_envelope: tuple[float, float, float]
    raw: dict[str, Any]


@dataclass(frozen=True)
class StatusRecord:
    uuid: str
    timestamp: str
    timestamp_ns: int
    operational_state: str
    location: Location
    path: tuple[PredictedLocation, ...]
    destinations: tuple[PredictedLocation, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class SourceFrame:
    timestamp_ns: int
    statuses: tuple[StatusRecord, ...]


@dataclass(frozen=True)
class SourceTrace:
    source_root: Path
    variant: str
    identities: tuple[IdentityRecord, ...]
    status_records: tuple[StatusRecord, ...]
    frames: tuple[SourceFrame, ...]
    identity_bytes: bytes
    status_bytes: bytes
    identity_sha256: str
    status_sha256: str


@dataclass(frozen=True)
class OperatorCoordinateBinding:
    source_linear_unit: str
    target_linear_unit: str
    target_frame: str
    transform: str
    unit_authority: str


@dataclass(frozen=True)
class ZoneConfig:
    zone_id: str
    station_id: str
    outside_label: str
    boundary_policy: str
    vertices: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class AdapterConfig:
    path: Path
    raw: dict[str, Any]
    sha256: str
    profile_id: str
    expected_planar_datum_uuid: str
    frame_interval_ns: int
    entity_order: tuple[str, ...]
    coordinate_binding: OperatorCoordinateBinding
    zone: ZoneConfig
