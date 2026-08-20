# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from metriplane_source_adapter_sdk import (
    canonical_json_bytes,
    capability_fingerprint,
    validate_capability,
)

from .constants import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    AMR_1_UUID,
    AMR_2_UUID,
    PROFILE_ID,
    SOURCE_BACKEND,
    SOURCE_CLASSIFICATION,
    SOURCE_DESCRIPTION,
    UPSTREAM_SNAPSHOT_COMMIT,
)
from .models import AdapterConfig, SourceTrace
from .reporting import (
    capability_record,
    conversion_environment,
    conversion_inputs_fingerprint,
    coordinate_binding_record,
    file_ref,
    pretty_json_bytes,
    rights_record,
    sha256_bytes,
    upstream_reference_register,
)


class FixtureError(RuntimeError):
    """Raised when deterministic fixture construction fails."""


def _clean_float(value: float) -> float:
    rounded = round(value, 15)
    return 0.0 if rounded == 0 else rounded


def point_in_polygon_inclusive(x: float, y: float, vertices: Sequence[Sequence[float]]) -> bool:
    points = [(float(point[0]), float(point[1])) for point in vertices]
    if len(points) < 3:
        raise FixtureError("zone polygon requires at least three vertices")
    inside = False
    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
        cross = (x - current_x) * (previous_y - current_y) - (y - current_y) * (
            previous_x - current_x
        )
        dot = (x - current_x) * (previous_x - current_x) + (y - current_y) * (
            previous_y - current_y
        )
        length = (previous_x - current_x) ** 2 + (previous_y - current_y) ** 2
        if abs(cross) <= 1e-12 and -1e-12 <= dot <= length + 1e-12:
            return True
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            boundary_x = (previous_x - current_x) * (y - current_y) / (
                previous_y - current_y
            ) + current_x
            if x < boundary_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def normalize_frames(trace: SourceTrace, config: AdapterConfig) -> tuple[bytes, dict[str, object]]:
    output: list[bytes] = []
    first_inside: dict[str, int | None] = {item: None for item in config.entity_order}
    origin = trace.frames[0].timestamp_ns
    for frame_id, frame in enumerate(trace.frames):
        objects: list[dict[str, object]] = []
        for record in frame.statuses:
            position = [
                _clean_float(record.location.x),
                _clean_float(record.location.y),
                _clean_float(record.location.z),
            ]
            inside = point_in_polygon_inclusive(position[0], position[1], config.zone.vertices)
            zone = config.zone.zone_id if inside else config.zone.outside_label
            if inside and first_inside[record.uuid] is None:
                first_inside[record.uuid] = frame_id
            objects.append({"id": record.uuid, "pos_world": position, "zone": zone})
        evaluation_ns = frame.timestamp_ns - origin
        row = {
            "events": [],
            "frame_id": frame_id,
            "objects": objects,
            "schema_version": "1.0",
            "source_backend": SOURCE_BACKEND,
            "ts": evaluation_ns / 1_000_000_000,
            "ts_sim_ns": evaluation_ns,
        }
        output.append(canonical_json_bytes(row))
    session = b"".join(output)
    return session, {
        "conversion_time_event_count": 0,
        "cross_datum_transform_count": 0,
        "first_inside_frame": first_inside,
        "interpolation_operation_count": 0,
        "normalized_frame_count": len(trace.frames),
        "objects_per_frame": 2,
        "prediction_derived_frame_count": 0,
        "resampling_operation_count": 0,
        "session_sha256": hashlib.sha256(session).hexdigest(),
        "carry_forward_operation_count": 0,
    }


def _entity_mapping() -> dict[str, object]:
    return {
        "mappings": [
            {
                "atlas_asset_id": "amr_1",
                "description": "Explicit configured mapping from the synthetic AMR 1 status UUID.",
                "normalized_object_id": AMR_1_UUID,
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "massrobotics_amr_status_jsonl",
                        "source_entity_id": f"statusReport.uuid:{AMR_1_UUID}",
                    },
                ],
            },
            {
                "atlas_asset_id": "amr_2",
                "description": "Explicit configured mapping from the synthetic AMR 2 status UUID.",
                "normalized_object_id": AMR_2_UUID,
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "massrobotics_amr_status_jsonl",
                        "source_entity_id": f"statusReport.uuid:{AMR_2_UUID}",
                    },
                ],
            },
        ],
        "schema_version": "metriplane.external_entity_mapping.v1",
    }


def _domain_pack(config: AdapterConfig) -> dict[str, bytes]:
    work_order_id = "WO-MET55-001"
    process_id = "synthetic_two_amr_rendezvous"
    values: dict[str, object] = {
        "domain-pack/assets.yaml": {
            "assets": [
                {
                    "asset_id": "amr_1",
                    "asset_type": "rendezvous_trigger_amr",
                    "expected_stations": [config.zone.station_id],
                    "expected_zones": [config.zone.zone_id],
                    "label": "Synthetic trigger AMR",
                    "object_id": AMR_1_UUID,
                    "work_order_id": work_order_id,
                },
                {
                    "asset_id": "amr_2",
                    "asset_type": "rendezvous_required_amr",
                    "expected_stations": [config.zone.station_id],
                    "expected_zones": [config.zone.zone_id],
                    "label": "Synthetic required AMR",
                    "object_id": AMR_2_UUID,
                    "work_order_id": work_order_id,
                },
            ],
            "schema_version": "metriplane.atlas.asset_registry.v1",
        },
        "domain-pack/contracts.yaml": {
            "contracts": [
                {
                    "contract_id": "two_amr_rendezvous_deadline",
                    "kind": "process_asset_presence",
                    "max_wait_s": 3.0,
                    "note": (
                        "Operator-authored engineering rule; not source truth, not a "
                        "MassRobotics requirement, and not a safety rule."
                    ),
                    "process_step_id": "two_amr_rendezvous",
                    "required_asset_id": "amr_2",
                    "severity": "warning",
                    "station_id": config.zone.station_id,
                    "zone_id": config.zone.zone_id,
                }
            ],
            "schema_version": "metriplane.atlas.contracts.v1",
        },
        "domain-pack/process.yaml": {
            "process_id": process_id,
            "schema_version": "metriplane.atlas.process_model.v1",
            "steps": [
                {
                    "expected_asset_types": ["rendezvous_trigger_amr"],
                    "label": "Second AMR reaches the rendezvous zone",
                    "max_wait_s": 3.0,
                    "required_assets": ["amr_2"],
                    "required_station": config.zone.station_id,
                    "required_zone": config.zone.zone_id,
                    "step_id": "two_amr_rendezvous",
                }
            ],
            "work_order_type": "external_fixture",
        },
        "domain-pack/workspace.yaml": {
            "cell_id": "synthetic_massrobotics_amr_rendezvous_fixture",
            "schema_version": "metriplane.atlas.workspace.v1",
            "stations": [
                {
                    "label": "Operator-configured rendezvous station",
                    "station_id": config.zone.station_id,
                    "zone_id": config.zone.zone_id,
                }
            ],
            "units": "meters",
            "zones": [
                {
                    "label": "Operator-configured rendezvous zone",
                    "polygon": [list(point) for point in config.zone.vertices],
                    "zone_id": config.zone.zone_id,
                    "zone_type": "work_station",
                }
            ],
        },
    }
    files = {path: pretty_json_bytes(value) for path, value in values.items()}
    files["domain-pack/work_orders.csv"] = (
        b"work_order_id,process_id,product,priority\n"
        b"WO-MET55-001,synthetic_two_amr_rendezvous,synthetic_format_fixture,normal\n"
    )
    return files


def _expected_outcome(variant: str) -> dict[str, object]:
    incident = variant == "incident"
    fixture_id = f"massrobotics_amr_synthetic_{variant}_v1"
    return {
        "atlas_input": False,
        "deviation_count": 1 if incident else 0,
        "event_count": 4 if incident else 3,
        "event_types": (
            [
                "required_asset_missing",
                "step_delayed",
                "required_asset_present",
                "step_completed",
            ]
            if incident
            else ["required_asset_missing", "required_asset_present", "step_completed"]
        ),
        "evidence_bundle_verified": incident,
        "fixture_id": fixture_id,
        "frame_count": 9,
        "incident_count": 1 if incident else 0,
        "incident_types": ["missing_tool_caused_delay"] if incident else [],
        "regression_passed": incident,
        "role": "test_metadata_only",
        "schema_version": "metriplane.external_expected_outcome.v1",
    }


def _annotation_policy() -> dict[str, object]:
    identity_fields = (
        "manufacturerName",
        "robotModel",
        "robotSerialNumber",
        "baseRobotEnvelope",
    )
    status_fields = (
        "operationalState",
        "location.angle",
        "velocity",
        "batteryPercentage",
        "remainingRunTime",
        "loadPercentageStillAvailable",
        "errorCodes",
        "destinations",
        "path",
    )
    annotations = [
        {
            "name": name,
            "retained_in": "source_artifact",
            "source_artifact_ids": ["massrobotics_amr_identity_jsonl"],
            "source_field": f"identityReport.{name}",
            "treatment": "provenance_only",
        }
        for name in identity_fields
    ]
    annotations.extend(
        {
            "name": name,
            "retained_in": "source_artifact",
            "source_artifact_ids": ["massrobotics_amr_status_jsonl"],
            "source_field": f"statusReport.{name}",
            "treatment": "provenance_only",
        }
        for name in status_fields
    )
    return {
        "annotations": annotations,
        "frame_state_events_policy": "empty",
        "inventory_complete": True,
        "source_incident_ids_in_normalized_input": False,
        "used_as_incident_truth": False,
        "used_as_process_events": False,
    }


def _operations() -> list[dict[str, object]]:
    return [
        {
            "applied": True,
            "declaration_path": "normalization.clock",
            "kind": "time_mapping",
            "operation_id": "map-source-utc-to-relative-integer-nanoseconds",
            "summary": "Parse strict UTC timestamps and subtract the first status timestamp.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.entity_mapping",
            "kind": "entity_mapping",
            "operation_id": "apply-explicit-uuid-entity-mapping",
            "summary": "Map both configured source UUIDs one-to-one in deterministic order.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.coordinates.transform",
            "kind": "coordinate_transform",
            "operation_id": "identity-operator-coordinate-binding",
            "summary": "Apply no transform under the explicit fixture-specific metre binding.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.coordinates.projection",
            "kind": "projection",
            "operation_id": "preserve-current-location-xyz",
            "summary": "Copy explicit current-location x, y, and z without projection.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.zone_assignment",
            "kind": "zone_assignment",
            "operation_id": "assign-inclusive-rendezvous-polygon",
            "summary": "Assign the operator-authored inclusive polygon after coordinate binding.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.completeness.materialization",
            "kind": "partial_update_materialization",
            "operation_id": "materialize-exact-two-amr-snapshot",
            "summary": "Join both required status records only at exactly equal timestamps.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.temporal_alignment.synchronization",
            "kind": "synchronization",
            "operation_id": "exact-status-timestamp-join",
            "summary": "Join both process-relevant AMRs with zero timestamp skew.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.resampling",
            "kind": "resampling",
            "operation_id": "no-resampling",
            "summary": "Every complete source timestamp produces one normalized frame.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.interpolation",
            "kind": "interpolation",
            "operation_id": "no-interpolation",
            "summary": "No current state or prediction is interpolated.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.completeness.carry_forward",
            "kind": "carry_forward",
            "operation_id": "no-carry-forward",
            "summary": "Missing required current status rejects the source before Atlas.",
        },
    ]


def _normalization_report(
    *,
    variant: str,
    input_fingerprint: str,
    session_sha256: str,
    mapping_sha256: str,
) -> dict[str, object]:
    return {
        "contract_schema_version": "metriplane.external_source_contract.v1",
        "conversion_reproducibility": {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": False,
            "input_fingerprint_sha256": input_fingerprint,
            "runs": [
                {
                    "artifacts": {
                        "entity-mapping.json": mapping_sha256,
                        "session.jsonl": session_sha256,
                    },
                    "run_id": "conversion-candidate",
                }
            ],
            "status": "not_demonstrated",
        },
        "fixture_id": f"massrobotics_amr_synthetic_{variant}_v1",
        "limitations": [
            SOURCE_DESCRIPTION,
            "The metre binding is a fixture-specific operator interpretation.",
            "Orientation is validated but not normalized into Atlas state.",
            "Velocity, battery, runtime, load, errors, operational state, destinations, and path do not participate in evaluation.",
            "Predictions never become observed frames or positions.",
            "No transport/session semantics, datum transform, carry-forward, interpolation, or resampling is reconstructed.",
        ],
        "normalized_frame_count": 9,
        "omitted_process_relevant_observations": 0,
        "operations": _operations(),
        "process_relevant_entity_count": 2,
        "result": "pass",
        "schema_version": "metriplane.external_normalization_report.v1",
        "source_record_count": 18,
        "unknown_process_relevant_observations": 0,
        "warnings": [],
    }


def _manifest(
    *,
    trace: SourceTrace,
    config: AdapterConfig,
    adapter_commit: str,
    environment: Mapping[str, str],
    files: Mapping[str, bytes],
) -> dict[str, object]:
    variant = trace.variant
    fixture_id = f"massrobotics_amr_synthetic_{variant}_v1"
    refs = {
        name: file_ref(name, files[name], media)
        for name, media in {
            "domain-pack/assets.yaml": "application/yaml",
            "domain-pack/contracts.yaml": "application/yaml",
            "domain-pack/process.yaml": "application/yaml",
            "domain-pack/work_orders.csv": "text/csv",
            "domain-pack/workspace.yaml": "application/yaml",
            "entity-mapping.json": "application/json",
            "expected-outcome.json": "application/json",
            "normalization-report.json": "application/json",
            "session.jsonl": "application/x-ndjson",
            "source/frozen-config.json": "application/json",
            "source/identity.jsonl": "application/x-ndjson",
            "source/status.jsonl": "application/x-ndjson",
            "source/uv.lock": "text/plain",
        }.items()
    }
    entity_mapping_ref: dict[str, object] = dict(refs["entity-mapping.json"])
    entity_mapping_ref["schema_version"] = "metriplane.external_entity_mapping.v1"
    source_base = (
        "https://github.com/Miko997/metriplane/blob/"
        f"{adapter_commit}/adapters/massrobotics_amr/source/{variant}"
    )
    rights = {
        "citation": [
            {
                "text": f"{SOURCE_DESCRIPTION}: {variant}",
                "uri": f"{source_base}/identity.jsonl",
            }
        ],
        "license": {
            "identifier": "MIT",
            "status": "declared",
            "uri": "https://github.com/Miko997/metriplane/blob/main/LICENSE",
        },
        "permission_basis": "The synthetic records were authored for this MIT-licensed repository.",
        "redistribution": "allowed",
        "redistribution_permission": "not_required",
        "rights_id": "metriplane-synthetic-massrobotics-format-rights-v1",
        "source_access": "public",
        "source_use_permission": "not_required",
    }
    status_artifact = "massrobotics_amr_status_jsonl"
    field_provenance = [
        {
            "derivation": "Set the frozen FrameStateModel 1.0 schema version.",
            "layer": "adapter_derived_fact",
            "normalized_field": "schema_version",
            "source_artifact_ids": [status_artifact],
        },
        {
            "derivation": "Set the bounded synthetic profile backend identifier.",
            "layer": "adapter_derived_fact",
            "normalized_field": "source_backend",
            "source_artifact_ids": [status_artifact],
        },
        {
            "derivation": "Parse strict UTC and subtract the first status timestamp in seconds.",
            "layer": "adapter_derived_fact",
            "normalized_field": "ts",
            "source_artifact_ids": [status_artifact],
            "source_fields": ["statusReport.timestamp"],
        },
        {
            "derivation": "Parse strict UTC and subtract the first status timestamp as integer nanoseconds.",
            "layer": "adapter_derived_fact",
            "normalized_field": "ts_sim_ns",
            "source_artifact_ids": [status_artifact],
            "source_fields": ["statusReport.timestamp"],
        },
        {
            "derivation": "Assign contiguous frame IDs after exact two-AMR timestamp joins.",
            "layer": "adapter_derived_fact",
            "normalized_field": "frame_id",
            "source_artifact_ids": [status_artifact],
            "source_fields": ["statusReport.timestamp", "statusReport.uuid"],
        },
        {
            "derivation": "Apply the separately hashed one-to-one UUID mapping.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].id",
            "parameter_references": [refs["entity-mapping.json"]],
            "source_artifact_ids": ["massrobotics_amr_identity_jsonl", status_artifact],
            "source_fields": ["identityReport.uuid", "statusReport.uuid"],
        },
        {
            "derivation": "Apply the explicit operator-configured metre/frame binding and copy current location xyz.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].pos_world",
            "parameter_references": [refs["source/frozen-config.json"]],
            "source_artifact_ids": [status_artifact],
            "source_fields": [
                "statusReport.location.x",
                "statusReport.location.y",
                "statusReport.location.z",
                "statusReport.location.planarDatum",
            ],
        },
        {
            "derivation": "Apply the operator-authored inclusive rendezvous polygon.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].zone",
            "parameter_references": [refs["domain-pack/workspace.yaml"]],
            "source_artifact_ids": [status_artifact],
            "source_fields": ["statusReport.location.x", "statusReport.location.y"],
        },
    ]
    origin_ns = trace.frames[0].timestamp_ns
    return {
        "adapter": {
            "adapter_id": ADAPTER_ID,
            "commit": adapter_commit,
            "entrypoint": "massrobotics_amr_adapter.cli:main",
            "environment": {
                "architecture": environment["architecture"],
                "dependency_lock": refs["source/uv.lock"],
                "description": (
                    f"Pinned isolated {environment['runtime']} "
                    f"{environment['runtime_version']} offline JSONL conversion environment "
                    f"on {environment['operating_system']} {environment['architecture']}; "
                    "no network or transport runtime required."
                ),
                "operating_system": environment["operating_system"],
                "runtime": environment["runtime"],
                "runtime_version": environment["runtime_version"],
            },
            "name": "Metriplane bounded MassRobotics AMR offline-replay adapter",
            "parameters": {
                "reference": refs["source/frozen-config.json"],
                "sha256": config.sha256,
            },
            "repository_uri": "https://github.com/Miko997/metriplane",
            "version": ADAPTER_VERSION,
        },
        "contract_profile": "metriplane.atlas.complete_snapshot.v1",
        "domain_pack": {
            "assets": refs["domain-pack/assets.yaml"],
            "contracts": refs["domain-pack/contracts.yaml"],
            "domain_pack_id": fixture_id,
            "process": refs["domain-pack/process.yaml"],
            "rationale": "Operator-authored two-AMR rendezvous deadline; not source truth, not a MassRobotics requirement, and not a safety rule.",
            "rule_origin": "operator_configured_rules",
            "source_annotations_used": False,
            "work_orders": refs["domain-pack/work_orders.csv"],
            "workspace": refs["domain-pack/workspace.yaml"],
        },
        "evaluation": {
            "domain_pack_id": fixture_id,
            "engine": "atlas",
            "expected_outcome_is_input": False,
            "metriplane_version": "0.3.0",
            "provenance_layer": "metriplane_derived_results",
        },
        "extensions": {
            "org.metriplane.massrobotics_amr_offline_replay": {
                "complete_snapshot_policy": "exact two-record UTC timestamp join; missing status rejects",
                "current_location_datum_authority": "statusReport.location.planarDatum",
                "identity_report_count": 2,
                "operator_coordinate_binding": coordinate_binding_record(config),
                "path_policy": "validate prediction timestamps, poses, and datum inheritance; never normalize as observations",
                "prediction_derived_frame_count": 0,
                "profile": PROFILE_ID,
                "referenced_standard": {
                    "formal_release_short_commit": "7161a0d",
                    "post_release_snapshot_commit": UPSTREAM_SNAPSHOT_COMMIT,
                    "rights": "reference_only",
                    "upstream_artifacts_included": False,
                    "version": "1.0",
                },
                "source_classification": SOURCE_CLASSIFICATION,
                "source_description": SOURCE_DESCRIPTION,
                "status_record_count": 18,
                "transport_semantics": "not reconstructed",
            }
        },
        "fixture": {
            "bounded_recording": True,
            "description": f"Nine complete two-AMR synthetic current-status snapshots for the {variant} rendezvous case.",
            "distribution": "public",
            "fixture_id": fixture_id,
            "title": f"Bounded synthetic MassRobotics AMR {variant} fixture",
        },
        "limitations": [
            SOURCE_DESCRIPTION,
            "Profile scope: the frozen two-AMR synthetic incident and control fixtures.",
            "The metre/frame binding and rendezvous rule are operator-configured.",
            "Accepted current-location fields: identity, UTC timestamp, XYZ, validated quaternion, and one datum.",
            "Orientation, velocity, operational state, battery, runtime, load, errors, destinations, and path are retained outside Atlas inputs.",
            "Path predictions are validation-only and never become observations or frames.",
            "Out of scope: live transport, retained messages, MQTT, WebSocket, QoS, fleet functions, planning, dispatch, control, cross-datum transforms, production use, safety use, and ISO 21423.",
        ],
        "normalization": {
            "atlas_asset_mapping": refs["domain-pack/assets.yaml"],
            "authoritative_object_collection": "objects",
            "clock": {
                "description": "Parse statusReport.timestamp as strict UTC nanoseconds, require monotonic exact one-second frames, and subtract the first status timestamp.",
                "evaluation_field": "ts_sim_ns",
                "mapping_method": "affine",
                "offset": -origin_ns,
                "scale": 1.0,
                "source_clock": "UTC statusReport timestamp",
                "source_field": "statusReport.timestamp",
                "source_unit": "nanoseconds",
            },
            "completeness": {
                "carry_forward": {"fields": [], "method": "none"},
                "frame_semantics": "complete_snapshot",
                "materialization": {
                    "carry_forward_dependency": "none",
                    "fields": ["objects[*].pos_world", "objects[*].zone"],
                    "implementation": "Join both configured status UUIDs only when UTC timestamps are exactly equal.",
                    "method": "source_snapshot_join",
                    "parameters": refs["source/frozen-config.json"],
                },
                "omission_policy": "reject_omission",
                "partial_updates_materialized": True,
                "process_relevant_entity_policy": "known_in_every_frame",
                "source_stream_semantics": "partial_update",
                "unknown_state_policy": "reject_fixture",
            },
            "confidence": {"mode": "absent"},
            "coordinates": {
                "information_loss": [],
                "projection": {
                    "dropped_axes": [],
                    "implementation": "Copy explicitly present current-location x, y, and z.",
                    "method": "identity_3d",
                    "output_z_policy": "preserve",
                },
                "source_frame": "metriplane_world",
                "source_units": "meters",
                "target_frame": "metriplane_world",
                "target_units": "meters",
                "transform": {
                    "implementation": "No transform; explicit operator binding maps the frozen source datum and metre unit to metriplane_world.",
                    "method": "identity",
                },
            },
            "entity_mapping": entity_mapping_ref,
            "field_provenance": field_provenance,
            "frame_state_model_version": "1.0",
            "source_annotations": _annotation_policy(),
            "source_backend": SOURCE_BACKEND,
            "temporal_alignment": {
                "interpolation": {"fields": [], "method": "none"},
                "resampling": {"fields": [], "method": "none"},
                "synchronization": {
                    "fields": ["objects[*].pos_world", "objects[*].zone"],
                    "max_skew_ns": 0,
                    "method": "exact_timestamp",
                    "reference_stream": f"statusReport.uuid:{AMR_1_UUID}",
                },
            },
            "zone_assignment": {
                "boundary_policy": config.zone.boundary_policy,
                "definitions": refs["domain-pack/workspace.yaml"],
                "implementation": "Apply the single configured polygon after the identity operator coordinate binding.",
                "method": "polygon",
                "outside_workspace_policy": "explicit_label",
                "outside_zone_label": config.zone.outside_label,
                "overlap_policy": "reject",
                "zone_priority": [],
            },
        },
        "normalized_artifacts": {
            "checksums_path": "CHECKSUMS.sha256",
            "expected_outcome": {
                **refs["expected-outcome.json"],
                "atlas_input": False,
                "role": "test_metadata_only",
            },
            "normalization_report": refs["normalization-report.json"],
            "session": {
                **refs["session.jsonl"],
                "frame_count": 9,
                "frame_state_model_version": "1.0",
            },
        },
        "rights": {
            "fixture": {
                "access": "public",
                "citation": [
                    {
                        "text": SOURCE_DESCRIPTION,
                        "uri": "https://github.com/Miko997/metriplane",
                    }
                ],
                "license": {
                    "identifier": "MIT",
                    "status": "declared",
                    "uri": "https://github.com/Miko997/metriplane/blob/main/LICENSE",
                },
                "permission_basis": "Metriplane-authored source, normalized state, and operator rules under the repository MIT license.",
                "redistribution": "allowed",
                "redistribution_permission": "not_required",
            },
            "source_artifacts": [rights],
        },
        "schema_version": "metriplane.external_source_contract.v1",
        "selection": {
            "artifact_ids": [
                "massrobotics_amr_identity_jsonl",
                "massrobotics_amr_status_jsonl",
            ],
            "method": "entire_artifact",
            "rationale": "Select both complete Metriplane-authored source files without inspecting Atlas results.",
        },
        "source_artifacts": [
            {
                "artifact_id": "massrobotics_amr_identity_jsonl",
                "description": f"Metriplane-authored synthetic MassRobotics-format identity reports for the {variant} fixture.",
                "immutable_identifier": f"sha256:{trace.identity_sha256}",
                "media_type": "application/x-ndjson",
                "path": "source/identity.jsonl",
                "presence": "included",
                "rights_id": rights["rights_id"],
                "role": "synthetic_identity_reports",
                "sha256": trace.identity_sha256,
                "uri": f"{source_base}/identity.jsonl",
            },
            {
                "artifact_id": "massrobotics_amr_status_jsonl",
                "description": f"Metriplane-authored synthetic MassRobotics-format current status reports for the {variant} fixture.",
                "immutable_identifier": f"sha256:{trace.status_sha256}",
                "media_type": "application/x-ndjson",
                "path": "source/status.jsonl",
                "presence": "included",
                "rights_id": rights["rights_id"],
                "role": "synthetic_status_reports",
                "sha256": trace.status_sha256,
                "uri": f"{source_base}/status.jsonl",
            },
        ],
        "source_project": {
            "canonical_uri": "https://github.com/Miko997/metriplane",
            "name": "Metriplane synthetic MassRobotics-format engineering source",
            "revision": {"kind": "git_commit", "value": adapter_commit},
            "version": "1.0.0",
        },
        "trust_layers": {
            "adapter_derived_facts": "adapter_and_normalization",
            "expected_outcome_is_atlas_input": False,
            "metriplane_derived_results": "atlas_outputs_only",
            "operator_configured_rules": "domain_pack_only",
            "source_annotations_can_drive_incidents": False,
            "source_facts": "source.artifacts_and_field_provenance",
        },
    }


def _checksums(files: Mapping[str, bytes]) -> bytes:
    return "".join(f"{sha256_bytes(files[path])}  {path}\n" for path in sorted(files)).encode(
        "ascii"
    )


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build_fixture_files(
    *,
    trace: SourceTrace,
    config: AdapterConfig,
    adapter_commit: str,
    config_bytes: bytes,
    lock_bytes: bytes,
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, bytes], dict[str, object]]:
    if hashlib.sha256(config_bytes).hexdigest() != config.sha256:
        raise FixtureError("authenticated config bytes changed during conversion")
    environment = dict(environment or conversion_environment())
    session, summary = normalize_frames(trace, config)
    files = _domain_pack(config)
    mapping = pretty_json_bytes(_entity_mapping())
    files.update(
        {
            "entity-mapping.json": mapping,
            "expected-outcome.json": pretty_json_bytes(_expected_outcome(trace.variant)),
            "session.jsonl": session,
            "source/adapter-environment.txt": (
                f"{environment['runtime']} {environment['runtime_version']}\n"
                f"{environment['operating_system']} {environment['architecture']}\n"
                f"adapter={ADAPTER_ID}@{adapter_commit}\n"
            ).encode(),
            "source/frozen-config.json": config_bytes,
            "source/identity.jsonl": trace.identity_bytes,
            "source/status.jsonl": trace.status_bytes,
            "source/uv.lock": lock_bytes,
        }
    )
    report: dict[str, Any] = _normalization_report(
        variant=trace.variant,
        input_fingerprint="0" * 64,
        session_sha256=sha256_bytes(session),
        mapping_sha256=sha256_bytes(mapping),
    )
    files["normalization-report.json"] = pretty_json_bytes(report)
    provisional = _manifest(
        trace=trace,
        config=config,
        adapter_commit=adapter_commit,
        environment=environment,
        files=files,
    )
    report["conversion_reproducibility"]["input_fingerprint_sha256"] = (
        conversion_inputs_fingerprint(provisional)
    )
    files["normalization-report.json"] = pretty_json_bytes(report)
    files["source-manifest.json"] = pretty_json_bytes(
        _manifest(
            trace=trace,
            config=config,
            adapter_commit=adapter_commit,
            environment=environment,
            files=files,
        )
    )
    files["CHECKSUMS.sha256"] = _checksums(files)
    return files, summary


def write_conversion(
    *,
    trace: SourceTrace,
    config: AdapterConfig,
    adapter_commit: str,
    output_root: Path,
    config_bytes: bytes,
    lock_bytes: bytes,
) -> dict[str, object]:
    environment = conversion_environment()
    fixture_files, normalized = build_fixture_files(
        trace=trace,
        config=config,
        adapter_commit=adapter_commit,
        config_bytes=config_bytes,
        lock_bytes=lock_bytes,
        environment=environment,
    )
    mapping_sha256 = sha256_bytes(fixture_files["entity-mapping.json"])
    capability = capability_record(
        trace=trace,
        config=config,
        adapter_commit=adapter_commit,
        lock_sha256=sha256_bytes(lock_bytes),
        mapping_sha256=mapping_sha256,
        environment=environment,
    )
    validate_capability(capability)
    _write_files(output_root / "fixture", fixture_files)
    root_files = {
        "capability-record.json": pretty_json_bytes(capability),
        "coordinate-binding.json": pretty_json_bytes(coordinate_binding_record(config)),
        "rights-record.json": pretty_json_bytes(rights_record()),
        "source-reference-register.json": pretty_json_bytes(upstream_reference_register()),
    }
    summary = {
        "adapter_commit": adapter_commit,
        "capability_fingerprint_sha256": capability_fingerprint(capability),
        "config_sha256": config.sha256,
        "conversion_reproducibility": {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": False,
            "status": "not_demonstrated",
        },
        "fixture_fingerprint_sha256": sha256_bytes(fixture_files["CHECKSUMS.sha256"]),
        "fixture_id": f"massrobotics_amr_synthetic_{trace.variant}_v1",
        "profile": PROFILE_ID,
        "schema_version": "org.metriplane.massrobotics_amr.conversion_summary.v1",
        "source_classification": SOURCE_CLASSIFICATION,
        "source_description": SOURCE_DESCRIPTION,
        "source_identity_count": len(trace.identities),
        "source_identity_sha256": trace.identity_sha256,
        "source_status_sha256": trace.status_sha256,
        "source_status_record_count": len(trace.status_records),
        "source_status_timestamp_count": len(trace.frames),
        "source_unchanged_during_conversion": True,
        "variant": trace.variant,
        **normalized,
    }
    root_files["conversion-summary.json"] = pretty_json_bytes(summary)
    _write_files(output_root, root_files)
    all_files = {
        path.relative_to(output_root).as_posix(): path.read_bytes()
        for path in output_root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    (output_root / "SHA256SUMS").write_bytes(_checksums(all_files))
    return summary


__all__ = [
    "FixtureError",
    "build_fixture_files",
    "normalize_frames",
    "point_in_polygon_inclusive",
    "write_conversion",
]
