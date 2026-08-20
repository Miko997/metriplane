# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from typing import Any

from metriplane_source_adapter_sdk import artifact_sha256, load_json

from .constants import EXPECTED_ORDER, FRAME_INTERVAL_NS, PLANAR_DATUM_UUID, PROFILE_ID
from .datum import finite_number, require_uuid
from .models import AdapterConfig, OperatorCoordinateBinding, ZoneConfig


class ConfigValidationError(ValueError):
    """Raised when a requested policy exceeds the frozen profile."""


_TOP_LEVEL = {
    "carry_forward",
    "expected_outcome_is_input",
    "expected_planar_datum_uuid",
    "frame_interval_ns",
    "interpolation",
    "operator_coordinate_binding",
    "outside_zone_label",
    "process_relevant_entity_order",
    "profile_id",
    "promote_predictions_to_observations",
    "resampling",
    "upstream_artifacts_included",
    "upstream_rights",
    "zone",
}


def _object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{field}: object is required")
    return value


def _exact_fields(value: dict[str, Any], *, expected: set[str], field: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise ConfigValidationError(f"{field}: missing={missing}; unknown={unknown}")


def load_config(path: str | Path) -> AdapterConfig:
    config_path = Path(path)
    try:
        raw = load_json(config_path)
        digest = artifact_sha256(config_path)
    except (ValueError, OSError) as exc:
        raise ConfigValidationError(f"frozen config: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigValidationError("frozen config: JSON root must be an object")
    forbidden = sorted(
        set(raw)
        & {
            "expected_outcome",
            "expected_outcome_path",
            "expected-outcome.json",
            "atlas_result",
        }
    )
    if forbidden:
        raise ConfigValidationError("expected outcome declared as converter input")
    _exact_fields(raw, expected=_TOP_LEVEL, field="config")
    if raw["profile_id"] != PROFILE_ID:
        raise ConfigValidationError("profile_id differs from frozen profile")
    if raw["carry_forward"] != "none":
        raise ConfigValidationError("requested carry-forward is prohibited")
    if raw["interpolation"] != "none":
        raise ConfigValidationError("requested interpolation is prohibited")
    if raw["resampling"] != "none":
        raise ConfigValidationError("requested resampling is prohibited")
    if raw["expected_outcome_is_input"] is not False:
        raise ConfigValidationError("expected outcome cannot be converter input")
    if raw["promote_predictions_to_observations"] is not False:
        raise ConfigValidationError("prediction promoted to current observation is prohibited")
    if raw["upstream_artifacts_included"] is not False:
        raise ConfigValidationError("upstream official artifact cannot be marked included")
    if raw["upstream_rights"] != "reference_only":
        raise ConfigValidationError("upstream rights must remain reference_only")
    if raw["frame_interval_ns"] != FRAME_INTERVAL_NS:
        raise ConfigValidationError("frame interval differs from frozen fixture profile")
    datum = require_uuid(raw["expected_planar_datum_uuid"], field="expected_planar_datum_uuid")
    if datum != PLANAR_DATUM_UUID:
        raise ConfigValidationError("configured datum differs from frozen profile")
    order = raw["process_relevant_entity_order"]
    if not isinstance(order, list) or tuple(order) != EXPECTED_ORDER:
        raise ConfigValidationError("process-relevant entity order differs from frozen profile")
    binding = _object(raw["operator_coordinate_binding"], field="operator_coordinate_binding")
    binding_fields = {
        "source_linear_unit",
        "target_linear_unit",
        "target_frame",
        "transform",
        "unit_authority",
    }
    _exact_fields(binding, expected=binding_fields, field="operator_coordinate_binding")
    if binding["source_linear_unit"] != "m" or binding["target_linear_unit"] != "m":
        raise ConfigValidationError("unsupported or unknown coordinate-unit binding")
    if binding["target_frame"] != "metriplane_world":
        raise ConfigValidationError("target frame differs from frozen profile")
    if binding["transform"] != "identity":
        raise ConfigValidationError("requested non-identity transform is prohibited in profile v1")
    if binding["unit_authority"] != "operator_configured_fixture_binding":
        raise ConfigValidationError("missing operator coordinate binding authority")
    zone = _object(raw["zone"], field="zone")
    _exact_fields(
        zone,
        expected={"zone_id", "station_id", "outside_label", "boundary_policy", "vertices"},
        field="zone",
    )
    if zone["zone_id"] != "rendezvous_zone" or zone["station_id"] != "rendezvous_station":
        raise ConfigValidationError("zone or station identity differs from frozen profile")
    if (
        zone["outside_label"] != "outside_workspace"
        or raw["outside_zone_label"] != "outside_workspace"
    ):
        raise ConfigValidationError("outside label differs from frozen profile")
    if zone["boundary_policy"] != "inclusive":
        raise ConfigValidationError("unsupported polygon boundary policy")
    vertices = zone["vertices"]
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise ConfigValidationError("zone vertices require a polygon")
    parsed_vertices: list[tuple[float, float]] = []
    for index, point in enumerate(vertices):
        if not isinstance(point, list) or len(point) != 2:
            raise ConfigValidationError(f"zone.vertices[{index}]: xy pair is required")
        parsed_vertices.append(
            (
                finite_number(point[0], field=f"zone.vertices[{index}][0]"),
                finite_number(point[1], field=f"zone.vertices[{index}][1]"),
            )
        )
    expected_vertices = ((4.0, -1.0), (6.0, -1.0), (6.0, 1.0), (4.0, 1.0))
    if tuple(parsed_vertices) != expected_vertices:
        raise ConfigValidationError("zone polygon differs from frozen profile")
    return AdapterConfig(
        path=config_path.resolve(),
        raw=raw,
        sha256=digest,
        profile_id=PROFILE_ID,
        expected_planar_datum_uuid=datum,
        frame_interval_ns=FRAME_INTERVAL_NS,
        entity_order=EXPECTED_ORDER,
        coordinate_binding=OperatorCoordinateBinding(
            source_linear_unit="m",
            target_linear_unit="m",
            target_frame="metriplane_world",
            transform="identity",
            unit_authority="operator_configured_fixture_binding",
        ),
        zone=ZoneConfig(
            zone_id="rendezvous_zone",
            station_id="rendezvous_station",
            outside_label="outside_workspace",
            boundary_policy="inclusive",
            vertices=expected_vertices,
        ),
    )


__all__ = ["ConfigValidationError", "load_config"]
