# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministic External Source Contract v1 bundle construction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, pretty_json_bytes, sha256_bytes
from .constants import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    FROZEN_CONFIG_SHA256,
    FROZEN_LOCK_SHA256,
    MATERIAL_TOPIC,
    OUTCOME_TOPIC,
    PROFILE_ID,
    SOURCE_ARTIFACT_ID,
    SOURCE_CLASSIFICATION,
    SOURCE_FILENAME,
    SOURCE_SHA256,
    TF_TOPIC,
    TOOL_TOPIC,
)
from .decoder import DecodedFrame, DecodedSource


class FixtureError(RuntimeError):
    """Raised when portable fixture construction cannot proceed."""


def _clean_float(value: float) -> float:
    rounded = round(value, 15)
    return 0.0 if rounded == 0 else rounded


def _point_in_polygon_inclusive(x: float, y: float, vertices: Sequence[Sequence[float]]) -> bool:
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


def normalize_frames(
    frames: Sequence[DecodedFrame], config: Mapping[str, Any]
) -> tuple[bytes, dict[str, object]]:
    polygon = config["target_polygon"]
    vertices = polygon["vertices"]
    zone_id = str(polygon["zone_id"])
    outside = str(polygon["outside_label"])
    output: list[bytes] = []
    material_inside: list[int] = []
    tool_inside: list[int] = []
    first_timestamp_ns = frames[0].timestamp_ns
    for index, frame in enumerate(frames):
        positions = {
            "material_1": tuple(_clean_float(value) for value in frame.material_world),
            "tool_1": tuple(_clean_float(value) for value in frame.tool_world),
        }
        zones: dict[str, str] = {}
        for entity_id, position in positions.items():
            zones[entity_id] = (
                zone_id
                if _point_in_polygon_inclusive(position[0], position[1], vertices)
                else outside
            )
        if zones["material_1"] == zone_id:
            material_inside.append(index)
        if zones["tool_1"] == zone_id:
            tool_inside.append(index)
        evaluation_ns = frame.timestamp_ns - first_timestamp_ns
        row = {
            "events": [],
            "frame_id": index,
            "objects": [
                {
                    "id": "material_1",
                    "pos_world": [positions["material_1"][0], positions["material_1"][1], 0.0],
                    "zone": zones["material_1"],
                },
                {
                    "id": "tool_1",
                    "pos_world": [positions["tool_1"][0], positions["tool_1"][1], 0.0],
                    "zone": zones["tool_1"],
                },
            ],
            "schema_version": "1.0",
            "source_backend": "ros2_mcap_recorded_state_v1_synthetic",
            "ts": evaluation_ns / 1_000_000_000,
            "ts_sim_ns": evaluation_ns,
        }
        output.append(canonical_json_bytes(row))
    session = b"".join(output)
    return session, {
        "material_inside_first_frame": material_inside[0] if material_inside else None,
        "material_inside_last_frame": material_inside[-1] if material_inside else None,
        "shared_session_sha256": hashlib.sha256(session).hexdigest(),
        "tool_inside_first_frame": tool_inside[0] if tool_inside else None,
        "tool_inside_last_frame": tool_inside[-1] if tool_inside else None,
    }


def _file_ref(path: str, data: bytes, media_type: str) -> dict[str, str]:
    return {"media_type": media_type, "path": path, "sha256": sha256_bytes(data)}


def _entity_mapping() -> dict[str, object]:
    return {
        "mappings": [
            {
                "atlas_asset_id": "material_1",
                "description": "Explicit configured mapping from the synthetic material PoseStamped channel.",
                "normalized_object_id": "material_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": SOURCE_ARTIFACT_ID,
                        "source_entity_id": f"{MATERIAL_TOPIC}:synthetic_material_1:pose.position",
                    }
                ],
            },
            {
                "atlas_asset_id": "tool_1",
                "description": "Explicit configured mapping from the synthetic tool PoseStamped channel.",
                "normalized_object_id": "tool_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": SOURCE_ARTIFACT_ID,
                        "source_entity_id": f"{TOOL_TOPIC}:synthetic_tool_1:pose.position",
                    }
                ],
            },
        ],
        "schema_version": "metriplane.external_entity_mapping.v1",
    }


def _domain_pack(config: Mapping[str, Any], max_wait_s: float) -> dict[str, bytes]:
    polygon = config["target_polygon"]
    values = {
        "domain-pack/assets.yaml": {
            "assets": [
                {
                    "asset_id": "material_1",
                    "asset_type": "material",
                    "expected_stations": ["target_station"],
                    "expected_zones": ["target_xy_region"],
                    "label": "Synthetic recorded material",
                    "object_id": "material_1",
                    "work_order_id": "WO-ROS2-MCAP-001",
                },
                {
                    "asset_id": "tool_1",
                    "asset_type": "tool",
                    "expected_stations": ["target_station"],
                    "expected_zones": ["target_xy_region"],
                    "label": "Synthetic recorded tool",
                    "object_id": "tool_1",
                    "work_order_id": "WO-ROS2-MCAP-001",
                },
            ],
            "schema_version": "metriplane.atlas.asset_registry.v1",
        },
        "domain-pack/contracts.yaml": {
            "contracts": [
                {
                    "contract_id": "tool_required_with_material",
                    "kind": "process_asset_presence",
                    "max_wait_s": max_wait_s,
                    "note": "Metriplane-authored format-test rule, not source truth or a safety rule.",
                    "process_step_id": "material_region_requires_tool",
                    "required_asset_id": "tool_1",
                    "severity": "warning",
                    "station_id": "target_station",
                    "zone_id": "target_xy_region",
                }
            ],
            "schema_version": "metriplane.atlas.contracts.v1",
        },
        "domain-pack/process.yaml": {
            "process_id": "synthetic_recorded_material_tool_presence",
            "schema_version": "metriplane.atlas.process_model.v1",
            "steps": [
                {
                    "expected_asset_types": ["material"],
                    "label": "Material in operator region requires tool",
                    "max_wait_s": max_wait_s,
                    "required_assets": ["tool_1"],
                    "required_station": "target_station",
                    "required_zone": "target_xy_region",
                    "step_id": "material_region_requires_tool",
                }
            ],
            "work_order_type": "external_fixture",
        },
        "domain-pack/workspace.yaml": {
            "cell_id": "synthetic_ros2_mcap_recorded_state_fixture",
            "schema_version": "metriplane.atlas.workspace.v1",
            "stations": [
                {
                    "label": "Operator-configured format-test station",
                    "station_id": "target_station",
                    "zone_id": "target_xy_region",
                }
            ],
            "units": "meters",
            "zones": [
                {
                    "label": "Operator-configured format-test region",
                    "polygon": polygon["vertices"],
                    "zone_id": "target_xy_region",
                    "zone_type": "work_station",
                }
            ],
        },
    }
    files = {path: pretty_json_bytes(value) for path, value in values.items()}
    files["domain-pack/work_orders.csv"] = (
        b"work_order_id,process_id,product,priority\n"
        b"WO-ROS2-MCAP-001,synthetic_recorded_material_tool_presence,"
        b"synthetic_format_fixture,normal\n"
    )
    return files


def _rights_record() -> dict[str, object]:
    return {
        "components": [
            {
                "component": "MCAP container and synthetic numeric/message values",
                "license": "MIT",
                "origin": "Metriplane-authored",
                "redistribution": "allowed",
            },
            {
                "component": "std_msgs, builtin_interfaces, and geometry_msgs interface definitions",
                "license": "Apache-2.0",
                "origin": "ROS 2 common_interfaces and rcl_interfaces",
                "redistribution": "allowed with notices",
            },
            {
                "component": "tf2_msgs interface definition",
                "copyright_notice": (
                    "Copyright (c) 2008, Willow Garage, Inc. All rights reserved."
                ),
                "license": "BSD-3-Clause",
                "license_blob": "d79557eefaf84816a7ce5f6201fa32fac60a69b5",
                "origin": "ROS 2 geometry2",
                "redistribution": "allowed with notices",
                "schema_blob": "fda1e4d0985406667d26b7b36cbbedc9bb497074",
                "source_commit": "f6053126926a38ffad5e81588054d793d87fc662",
            },
            {
                "component": "Metriplane SourceOutcome interface definition",
                "license": "MIT",
                "origin": "Metriplane-authored format-test schema",
                "redistribution": "allowed",
            },
            {
                "component": "Portable normalized numeric state and operator rules",
                "license": "MIT",
                "origin": "Metriplane-authored derived fixture; embedded schema bytes excluded",
                "redistribution": "allowed",
            },
        ],
        "conclusion": (
            "The source recording has composite MIT, Apache-2.0, and BSD-3-Clause payload "
            "terms. The portable fixture excludes MCAP and schema bytes and is MIT."
        ),
        "schema_version": "org.metriplane.ros2_mcap.rights.v1",
    }


def _transform_provenance(source: DecodedSource) -> dict[str, object]:
    return {
        "composition_order": "sensor_frame -> cell_frame -> world",
        "interpolation": "none",
        "carry_forward": "none",
        "extrapolation": "none",
        "normalized_projection": "world x/y copied; normalized z set to 0; orientation omitted",
        "schema_version": "org.metriplane.ros2_mcap.transform_provenance.v1",
        "source_field": "geometry_msgs/msg/PoseStamped.pose.position",
        "source_frame": "sensor_frame",
        "source_topic": [MATERIAL_TOPIC, TOOL_TOPIC],
        "target_frame": "world",
        "transform_topic": TF_TOPIC,
        "transforms": [
            {
                "child_frame_id": item.child_frame_id,
                "parent_frame_id": item.header.frame_id,
                "rotation_xyzw": list(item.rotation),
                "timestamp_ns": item.header.stamp_ns,
                "translation_m": list(item.translation),
                "type": "static",
            }
            for item in source.transforms
        ],
        "unit": "m",
    }


def _capability_record(
    *, adapter_commit: str, source: DecodedSource, mapping_sha256: str, lock_sha256: str
) -> dict[str, object]:
    evidence_ids = ["ros2_mcap_adapter_commit"]
    base = {"status": "verified", "evidence_ids": evidence_ids}
    return {
        "schema_version": "metriplane.source_adapter_capability.v1",
        "record": {
            "classification": "native",
            "evidence_classification": "synthetic_format_engineering",
            "subject": "candidate_adapter",
            "statement": "Native capability declaration for one bounded Metriplane-authored synthetic format-engineering source.",
        },
        "contract": {
            "version": "metriplane.external_source_contract.v1",
            "profile": "metriplane.atlas.complete_snapshot.v1",
            "frame_state_model_version": "1.0",
            "fit": "verified",
        },
        "adapter": {
            "adapter_id": ADAPTER_ID,
            "version": ADAPTER_VERSION,
            "implementation_commit": adapter_commit,
            "repository_uri": "https://github.com/Miko997/metriplane",
            "entrypoint": "ros2_mcap_adapter.cli:main",
            "environment": {
                "runtime": "CPython",
                "runtime_version": "3.12",
                "operating_system": "Linux",
                "architecture": "x86_64",
                "dependency_lock_sha256": lock_sha256,
            },
            "conversion_dependencies": ["mcap==1.3.0"],
        },
        "source": {
            "family": "Bounded synthetic ROS 2 message streams in one MCAP container",
            "project_uri": "https://github.com/Miko997/metriplane",
            "revision_kind": "adapter_commit",
            "revision": adapter_commit,
            "artifacts": [
                {
                    "artifact_id": SOURCE_ARTIFACT_ID,
                    "role": "synthetic_recorded_robotics_state",
                    "uri": f"urn:sha256:{source.source_sha256}",
                    "sha256": source.source_sha256,
                    "byte_size": source.source_size,
                    "presence": "referenced",
                    "rights_id": "synthetic_mcap_composite_rights",
                }
            ],
            "rights": {
                "source_records": [
                    {
                        "rights_id": "synthetic_mcap_composite_rights",
                        "subject_artifact_ids": [SOURCE_ARTIFACT_ID],
                        "source_use": "verified",
                        "source_redistribution": "allowed",
                        "basis": "Metriplane-authored MIT container and values with embedded Apache-2.0 and BSD-3-Clause ROS interface schema text.",
                    }
                ],
                "derived_fixture": {
                    "rights_id": "synthetic_normalized_fixture",
                    "subject": "normalized_fixture",
                    "redistribution": "verified",
                    "basis": "MIT normalized numeric state and operator rules exclude MCAP and embedded schema bytes.",
                },
                "source_bytes_in_fixture": False,
            },
        },
        "capabilities": {
            "artifact_identity": {**base, "all_required_artifacts_hashed": True},
            "rights": base,
            "clock": {
                **base,
                "authority": "PoseStamped message header stamp in declared ROS_TIME",
                "source_field": "geometry_msgs/msg/PoseStamped.header.stamp",
                "domain": "synthetic declared ROS_TIME source domain",
                "source_unit": "nanoseconds",
                "evaluation_field": "ts_sim_ns",
                "mapping_method": "affine",
                "authoritative": True,
                "order_only": False,
            },
            "coordinates": {
                **base,
                "source_frame": "sensor_frame",
                "target_frame": "world",
                "source_units": "meters",
                "target_units": "meters",
                "transform_method": "declared two-edge static rigid transform",
                "projection_method": "planar_xy",
            },
            "entity_identity": {
                **base,
                "stable": True,
                "explicit_mapping": True,
                "mapping_schema": "metriplane.external_entity_mapping.v1",
                "mapping_sha256": mapping_sha256,
                "normalized_entities": [
                    {"normalized_id": "material_1", "process_relevant": True},
                    {"normalized_id": "tool_1", "process_relevant": True},
                ],
                "required_entities": ["material_1", "tool_1"],
            },
            "field_provenance": {**base, "complete": True, "trust_layers_separated": True},
            "completeness": {
                **base,
                "frame_semantics": "complete_snapshot",
                "unknown_state_policy": "reject_fixture",
                "omission_policy": "reject_omission",
                "source_stream_semantics": "partial_updates",
                "partial_updates_materialized": True,
                "materialization_method": "exact_snapshot_join",
                "synchronization_tolerance_ns": 0,
                "carry_forward": {"method": "none", "fields": [], "max_gap_ns": None},
                "interpolation": "none",
                "resampling": "none",
                "synchronization": "exact_timestamp",
            },
            "information_loss": {
                **base,
                "declared": True,
                "items": ["transformed world z", "complete source pose orientation"],
            },
            "anti_taint": {
                **base,
                "inventory_complete": True,
                "used_as_incident_truth": False,
                "used_as_process_events": False,
                "frame_state_events_policy": "empty",
                "excluded_fields": [
                    f"{OUTCOME_TOPIC}.{name}"
                    for name in ("success", "result", "alarm", "action", "annotation")
                ],
            },
            "deterministic_conversion": {
                "status": "not_demonstrated",
                "evidence_ids": evidence_ids,
                "comparison_policy": "not_demonstrated",
                "clean_run_count": 1,
                "compared_output_count": 0,
                "equivalent": False,
                "input_fingerprint_sha256": sha256_bytes(
                    canonical_json_bytes(
                        {
                            "adapter_commit": adapter_commit,
                            "config_sha256": FROZEN_CONFIG_SHA256,
                            "lock_sha256": lock_sha256,
                            "source_sha256": source.source_sha256,
                        }
                    )
                ),
            },
            "portable_evaluation": {
                "status": "not_demonstrated",
                "source_dependencies_required": False,
                "environments": [
                    {"operating_system": os_name, "python_version": version, "status": "required"}
                    for os_name in ("Ubuntu", "macOS")
                    for version in ("3.12", "3.13")
                ],
                "evidence_ids": evidence_ids,
            },
            "semantics": {
                **base,
                "supported": [
                    "Bounded planar XY arrival and required-presence timing for one exact synthetic recorded-state profile"
                ],
                "prohibited": [
                    "General ROS 2, MCAP, rosbag2, or TF2 compatibility",
                    "Automatic topic discovery or arbitrary message support",
                    "External-source compatibility evidence",
                    "Physical accuracy, safety, simulator realism, or production readiness",
                ],
            },
        },
        "evidence": [
            {
                "evidence_id": "ros2_mcap_adapter_commit",
                "kind": "git_commit",
                "identity": adapter_commit,
                "uri": f"https://github.com/Miko997/metriplane/commit/{adapter_commit}",
            }
        ],
        "limitations": [
            "Synthetic format-engineering evidence only",
            "One exact configured profile and source identity",
            "Portable operating-system rows remain required until CI passes",
        ],
    }


def _normalization_report(
    *,
    fixture_id: str,
    source: DecodedSource,
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
                    "run_id": f"{fixture_id}-current-conversion",
                }
            ],
            "status": "not_demonstrated",
        },
        "fixture_id": fixture_id,
        "limitations": [
            "Synthetic format-engineering source only; no external-source compatibility evidence.",
            "Position-only planar evaluation discards transformed world Z and pose orientation.",
            "The target polygon and waits are operator-authored test rules, not source truth.",
            "No interpolation, extrapolation, carry-forward, discovery, or inferred absence is supported.",
            "Excluded outcome values cannot drive normalized state or Atlas semantics.",
        ],
        "normalized_frame_count": len(source.frames),
        "omitted_process_relevant_observations": 0,
        "operations": [
            {
                "applied": True,
                "declaration_path": "normalization.clock",
                "kind": "time_mapping",
                "operation_id": "map-header-ros-time-to-relative-integer-nanoseconds",
                "summary": "Subtract the first authoritative header.stamp from each exact ROS_TIME timestamp.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.entity_mapping",
                "kind": "entity_mapping",
                "operation_id": "apply-explicit-entity-mapping",
                "summary": "Map the two configured stable source entities one-to-one to normalized IDs.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.coordinates.transform",
                "kind": "coordinate_transform",
                "operation_id": "compose-two-static-tf-edges",
                "summary": "Resolve the declared sensor_frame to world path with two exact static transforms.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.coordinates.projection",
                "kind": "projection",
                "operation_id": "project-world-xy",
                "summary": "Copy transformed world x/y, set normalized z to zero, and omit orientation.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.zone_assignment",
                "kind": "zone_assignment",
                "operation_id": "assign-operator-polygon",
                "summary": "Assign the inclusive operator-authored polygon after world-frame projection.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.completeness.materialization",
                "kind": "partial_update_materialization",
                "operation_id": "materialize-exact-co-timestamp-snapshot",
                "summary": "Materialize a complete snapshot only from both exact co-timestamped required messages.",
            },
            {
                "applied": True,
                "declaration_path": "normalization.temporal_alignment.synchronization",
                "kind": "synchronization",
                "operation_id": "exact-co-timestamp-snapshot-join",
                "summary": "Join both required PoseStamped streams only at exactly equal header timestamps.",
            },
            {
                "applied": False,
                "declaration_path": "normalization.temporal_alignment.resampling",
                "kind": "resampling",
                "operation_id": "no-resampling",
                "summary": "Every exact source timestamp is retained one-for-one.",
            },
            {
                "applied": False,
                "declaration_path": "normalization.completeness.carry_forward",
                "kind": "carry_forward",
                "operation_id": "no-carry-forward",
                "summary": "Missing required state rejects the recording.",
            },
            {
                "applied": False,
                "declaration_path": "normalization.temporal_alignment.interpolation",
                "kind": "interpolation",
                "operation_id": "no-interpolation-or-extrapolation",
                "summary": "Only exact source timestamps and static transforms are allowed.",
            },
        ],
        "process_relevant_entity_count": 2,
        "result": "pass",
        "schema_version": "metriplane.external_normalization_report.v1",
        "source_record_count": len(source.frames),
        "unknown_process_relevant_observations": 0,
        "warnings": [],
    }


def _annotation_policy() -> dict[str, object]:
    return {
        "annotations": [
            {
                "name": name,
                "retained_in": "not_retained",
                "source_artifact_ids": [SOURCE_ARTIFACT_ID],
                "source_field": f"{OUTCOME_TOPIC}.{name}",
                "treatment": "excluded",
            }
            for name in ("success", "result", "alarm", "action", "annotation")
        ],
        "frame_state_events_policy": "empty",
        "inventory_complete": True,
        "source_incident_ids_in_normalized_input": False,
        "used_as_incident_truth": False,
        "used_as_process_events": False,
    }


def _conversion_inputs_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Mirror External Source Contract v1's canonical Stage-1 fingerprint."""
    source_artifacts = json.loads(json.dumps(manifest["source_artifacts"]))
    for artifact in source_artifacts:
        artifact.setdefault("sha256", None)
        artifact.setdefault("uri", None)
        artifact.setdefault("path", None)
        artifact.setdefault("immutable_identifier", None)
    selection = json.loads(json.dumps(manifest["selection"]))
    for key in (
        "episode_id",
        "group_path",
        "start_index",
        "end_index_exclusive",
        "start_time",
        "end_time",
        "selector",
    ):
        selection.setdefault(key, None)
    adapter = json.loads(json.dumps(manifest["adapter"]))
    adapter["environment"].setdefault("container_image_digest", None)
    adapter["parameters"].setdefault("inline", None)
    normalization = json.loads(json.dumps(manifest["normalization"]))
    mapping_path = normalization["entity_mapping"]["path"]
    normalization["entity_mapping"].pop("sha256")
    for key in ("fixed_step_ns", "fixed_step_origin_ns", "scale", "offset", "lookup"):
        normalization["clock"].setdefault(key, None)
    if normalization["clock"]["offset"] is not None:
        normalization["clock"]["offset"] = float(normalization["clock"]["offset"])
    normalization["coordinates"]["transform"].setdefault("parameters", None)
    normalization["coordinates"]["projection"].setdefault("parameters", None)
    normalization["completeness"].setdefault("materialization", None)
    normalization["completeness"]["carry_forward"].setdefault("max_gap_ns", None)
    confidence = normalization["confidence"]
    for key in (
        "source_field",
        "algorithm",
        "implementation",
        "parameters",
        "output_semantics",
        "placeholder_or_invented_values",
    ):
        confidence.setdefault(key, None)
    confidence.setdefault("input_fields", [])
    for declaration in normalization["field_provenance"]:
        declaration.setdefault("source_fields", [])
        declaration.setdefault("derivation", None)
        declaration.setdefault("parameter_references", [])
        declaration.setdefault("confidence_origin", None)
        for reference in declaration["parameter_references"]:
            if reference["path"] == mapping_path:
                reference.pop("sha256")
    for annotation in normalization["source_annotations"]["annotations"]:
        annotation.setdefault("retained_reference", None)
    interpolation = normalization["temporal_alignment"]["interpolation"]
    interpolation.setdefault("max_gap_ns", None)
    resampling = normalization["temporal_alignment"]["resampling"]
    resampling.setdefault("output_period_ns", None)
    resampling.setdefault("max_gap_ns", None)
    synchronization = normalization["temporal_alignment"]["synchronization"]
    synchronization.setdefault("reference_stream", None)
    synchronization.setdefault("max_skew_ns", None)
    normalization["zone_assignment"].setdefault("parameters", None)
    rights = json.loads(json.dumps(manifest["rights"]))
    for citation in rights["fixture"]["citation"]:
        citation.setdefault("uri", None)
    for source_rights in rights["source_artifacts"]:
        for citation in source_rights["citation"]:
            citation.setdefault("uri", None)
    payload = {
        "schema_version": manifest["schema_version"],
        "contract_profile": manifest["contract_profile"],
        "source_project": manifest["source_project"],
        "source_artifacts": source_artifacts,
        "selection": selection,
        "rights": rights,
        "adapter": adapter,
        "normalization": normalization,
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _manifest(
    *,
    variant: str,
    config: Mapping[str, Any],
    adapter_commit: str,
    source: DecodedSource,
    files: Mapping[str, bytes],
) -> dict[str, object]:
    variant_config = config["variants"][variant]
    fixture_id = str(variant_config["fixture_id"])
    domain_pack_id = str(variant_config["domain_pack_id"])
    refs = {
        name: _file_ref(name, files[name], media)
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
            "source/uv.lock": "text/plain",
        }.items()
    }
    source_uri = (
        "https://github.com/Miko997/metriplane/blob/"
        f"{adapter_commit}/adapters/ros2_mcap/source/{SOURCE_FILENAME}"
        if source.source_sha256 == SOURCE_SHA256
        else f"urn:sha256:{source.source_sha256}"
    )
    source_rights = {
        "citation": [
            {
                "text": "Metriplane-authored synthetic ROS 2/MCAP format-engineering source",
                "uri": source_uri,
            }
        ],
        "license": {
            "identifier": "MIT AND Apache-2.0 AND BSD-3-Clause",
            "status": "declared",
            "uri": "https://github.com/Miko997/metriplane",
        },
        "permission_basis": (
            "Container and synthetic values are Metriplane-authored MIT content; embedded "
            "ROS interface schema text retains Apache-2.0 and BSD-3-Clause terms."
        ),
        "redistribution": "allowed",
        "redistribution_permission": "verified",
        "rights_id": "synthetic-mcap-composite-rights-v1",
        "source_access": "public",
        "source_use_permission": "verified",
    }
    field_provenance = [
        {
            "derivation": "Set the frozen FrameStateModel 1.0 schema version.",
            "layer": "adapter_derived_fact",
            "normalized_field": "schema_version",
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
        },
        {
            "derivation": "Set the namespaced bounded profile backend.",
            "layer": "adapter_derived_fact",
            "normalized_field": "source_backend",
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
        },
        {
            "derivation": "Subtract the first authoritative ROS_TIME header stamp and divide nanoseconds by 1e9.",
            "layer": "adapter_derived_fact",
            "normalized_field": "ts",
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": ["geometry_msgs/msg/PoseStamped.header.stamp"],
        },
        {
            "derivation": "Subtract the first authoritative ROS_TIME header stamp as exact integer nanoseconds.",
            "layer": "adapter_derived_fact",
            "normalized_field": "ts_sim_ns",
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": ["geometry_msgs/msg/PoseStamped.header.stamp"],
        },
        {
            "derivation": "Assign sequential normalized snapshot IDs after exact timestamp join.",
            "layer": "adapter_derived_fact",
            "normalized_field": "frame_id",
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": ["geometry_msgs/msg/PoseStamped.header.stamp"],
        },
        {
            "derivation": "Apply the explicit hashed entity mapping; topic names are not discovered.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].id",
            "parameter_references": [refs["entity-mapping.json"]],
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": [MATERIAL_TOPIC, TOOL_TOPIC],
        },
        {
            "derivation": "Decode source metres, compose the declared static TF path, retain world x/y, and set z to zero.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].pos_world",
            "parameter_references": [refs["source/frozen-config.json"]],
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": [
                "geometry_msgs/msg/PoseStamped.pose.position",
                "tf2_msgs/msg/TFMessage.transforms",
            ],
        },
        {
            "derivation": "Apply the operator-authored inclusive polygon after the source transform.",
            "layer": "adapter_derived_fact",
            "normalized_field": "objects[*].zone",
            "parameter_references": [refs["domain-pack/workspace.yaml"]],
            "source_artifact_ids": [SOURCE_ARTIFACT_ID],
            "source_fields": ["geometry_msgs/msg/PoseStamped.pose.position"],
        },
    ]
    return {
        "adapter": {
            "adapter_id": ADAPTER_ID,
            "commit": adapter_commit,
            "entrypoint": "ros2_mcap_adapter.cli:main",
            "environment": {
                "architecture": "x86_64",
                "dependency_lock": refs["source/uv.lock"],
                "description": "Pinned isolated CPython 3.12 MCAP conversion environment; no ROS installation required.",
                "operating_system": "Linux",
                "runtime": "CPython",
                "runtime_version": "3.12",
            },
            "name": "Metriplane bounded ROS 2/MCAP recorded-state adapter",
            "parameters": {
                "reference": refs["source/frozen-config.json"],
                "sha256": FROZEN_CONFIG_SHA256,
            },
            "repository_uri": "https://github.com/Miko997/metriplane",
            "version": ADAPTER_VERSION,
        },
        "contract_profile": "metriplane.atlas.complete_snapshot.v1",
        "domain_pack": {
            "assets": refs["domain-pack/assets.yaml"],
            "contracts": refs["domain-pack/contracts.yaml"],
            "domain_pack_id": domain_pack_id,
            "process": refs["domain-pack/process.yaml"],
            "rationale": "Operator-authored bounded format-test region and timing rule; not source truth.",
            "rule_origin": "operator_configured_rules",
            "source_annotations_used": False,
            "work_orders": refs["domain-pack/work_orders.csv"],
            "workspace": refs["domain-pack/workspace.yaml"],
        },
        "evaluation": {
            "domain_pack_id": domain_pack_id,
            "engine": "atlas",
            "expected_outcome_is_input": False,
            "metriplane_version": "0.3.0",
            "provenance_layer": "metriplane_derived_results",
        },
        "extensions": {
            "org.metriplane.ros2_mcap_recorded_state": {
                "channel_inventory": list(source.channel_inventory),
                "clock_domain": "ROS_TIME",
                "evaluation_clock_field": "geometry_msgs/msg/PoseStamped.header.stamp",
                "log_time_role": "container_provenance_only",
                "outcome_stream_message_count": source.outcome_message_count,
                "outcome_stream_present": source.outcome_stream_present,
                "profile": PROFILE_ID,
                "publish_time_role": "transport_provenance_only",
                "schema_inventory": list(source.schema_inventory),
                "source_classification": SOURCE_CLASSIFICATION,
                "source_size": source.source_size,
                "tf_policy": "exact configured /tf_static chain; no interpolation, latest, or extrapolation",
            }
        },
        "fixture": {
            "bounded_recording": True,
            "description": "Sixty complete synthetic position snapshots converted through a declared two-edge static TF path.",
            "distribution": "derived_only",
            "fixture_id": fixture_id,
            "title": f"Bounded synthetic ROS 2/MCAP {variant} fixture",
        },
        "limitations": [
            "This is synthetic format-engineering evidence and not external-source evidence.",
            "This one exact profile is not general ROS 2, MCAP, rosbag2, or TF2 support.",
            "Evaluation is position-only planar world XY and discards source Z and pose orientation.",
            "Only exact co-timestamped state with the configured static transform chain is accepted.",
            "No discovery, interpolation, extrapolation, carry-forward, or inferred absence is supported.",
            "The region and waits are operator-authored test rules, not physical, safety, or source truth.",
        ],
        "normalization": {
            "atlas_asset_mapping": refs["domain-pack/assets.yaml"],
            "authoritative_object_collection": "objects",
            "clock": {
                "description": "Use PoseStamped header.stamp in declared ROS_TIME, require exact co-timestamps, and subtract the first timestamp.",
                "evaluation_field": "ts_sim_ns",
                "mapping_method": "affine",
                "offset": -1_000_000_000,
                "scale": 1.0,
                "source_clock": "message header ROS_TIME in synthetic declared source domain",
                "source_field": "geometry_msgs/msg/PoseStamped.header.stamp",
                "source_unit": "nanoseconds",
            },
            "completeness": {
                "carry_forward": {"fields": [], "method": "none"},
                "frame_semantics": "complete_snapshot",
                "materialization": {
                    "carry_forward_dependency": "none",
                    "fields": ["objects[*].pos_world", "objects[*].zone"],
                    "implementation": "Join both configured PoseStamped messages only when header timestamps are exactly equal.",
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
                "information_loss": [
                    {
                        "impact": "Atlas receives transformed world x/y with z=0 and no orientation; 3D pose and rotational semantics cannot be evaluated.",
                        "lost_information": [
                            "transformed world z",
                            "complete source pose orientation",
                        ],
                        "operation": "position-only planar projection",
                    }
                ],
                "projection": {
                    "dropped_axes": ["z"],
                    "implementation": "Retain transformed world x/y, set normalized z to zero, and omit orientation.",
                    "method": "planar_xy",
                    "output_z_policy": "zero",
                },
                "source_frame": "sensor_frame",
                "source_units": "meters",
                "target_frame": "world",
                "target_units": "meters",
                "transform": {
                    "implementation": "Compose configured world->cell_frame and cell_frame->sensor_frame static rigid transforms in reverse for child-to-parent point conversion.",
                    "method": "rigid_matrix",
                    "parameters": refs["source/frozen-config.json"],
                },
            },
            "entity_mapping": {
                **refs["entity-mapping.json"],
                "schema_version": "metriplane.external_entity_mapping.v1",
            },
            "field_provenance": field_provenance,
            "frame_state_model_version": "1.0",
            "source_annotations": _annotation_policy(),
            "source_backend": "ros2_mcap_recorded_state_v1_synthetic",
            "temporal_alignment": {
                "interpolation": {"fields": [], "method": "none"},
                "resampling": {"fields": [], "method": "none"},
                "synchronization": {
                    "fields": ["objects[*].pos_world"],
                    "max_skew_ns": 0,
                    "method": "exact_timestamp",
                    "reference_stream": MATERIAL_TOPIC,
                },
            },
            "zone_assignment": {
                "boundary_policy": "inclusive",
                "definitions": refs["domain-pack/workspace.yaml"],
                "implementation": "Apply the single configured polygon after TF composition and planar projection.",
                "method": "polygon",
                "outside_workspace_policy": "explicit_label",
                "outside_zone_label": "outside_workspace",
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
                "frame_count": len(source.frames),
                "frame_state_model_version": "1.0",
            },
        },
        "rights": {
            "fixture": {
                "access": "public",
                "citation": [{"text": "Metriplane bounded synthetic ROS 2/MCAP fixture"}],
                "license": {
                    "identifier": "MIT",
                    "status": "declared",
                    "uri": "https://github.com/Miko997/metriplane/blob/main/LICENSE",
                },
                "permission_basis": "Metriplane-authored derived numeric state and rules; MCAP and embedded ROS schema bytes are excluded.",
                "redistribution": "allowed",
                "redistribution_permission": "verified",
            },
            "source_artifacts": [source_rights],
        },
        "schema_version": "metriplane.external_source_contract.v1",
        "selection": {
            "artifact_ids": [SOURCE_ARTIFACT_ID],
            "method": "entire_artifact",
            "rationale": "Metriplane-authored deterministic fallback after three external candidates failed hard gates; selection does not inspect Atlas results.",
        },
        "source_artifacts": [
            {
                "artifact_id": SOURCE_ARTIFACT_ID,
                "description": "Exact Metriplane-authored synthetic MCAP source with composite payload rights; referenced and omitted from the portable fixture.",
                "immutable_identifier": source.source_sha256,
                "media_type": "application/vnd.mcap",
                "presence": "referenced",
                "rights_id": "synthetic-mcap-composite-rights-v1",
                "role": "synthetic_recorded_robotics_state",
                "sha256": source.source_sha256,
                "uri": source_uri,
            }
        ],
        "source_project": {
            "canonical_uri": "https://github.com/Miko997/metriplane",
            "name": "Metriplane synthetic ROS 2/MCAP format-engineering source",
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


def _expected_outcome(variant: str, fixture_id: str, frame_count: int) -> dict[str, object]:
    incident = variant == "incident"
    return {
        "atlas_input": False,
        "deviation_count": 1 if incident else 0,
        "event_count": 4 if incident else 3,
        "event_types": (
            ["required_asset_missing", "step_delayed", "required_asset_present", "step_completed"]
            if incident
            else ["required_asset_missing", "required_asset_present", "step_completed"]
        ),
        "evidence_bundle_verified": incident,
        "fixture_id": fixture_id,
        "frame_count": frame_count,
        "incident_count": 1 if incident else 0,
        "incident_types": ["missing_tool_caused_delay"] if incident else [],
        "regression_passed": incident,
        "role": "test_metadata_only",
        "schema_version": "metriplane.external_expected_outcome.v1",
    }


def _checksums(files: Mapping[str, bytes]) -> bytes:
    return "".join(f"{sha256_bytes(files[path])}  {path}\n" for path in sorted(files)).encode()


def build_variant_files(
    *,
    variant: str,
    config: Mapping[str, Any],
    adapter_commit: str,
    source: DecodedSource,
    session: bytes,
    session_summary: Mapping[str, object],
    config_bytes: bytes,
    lock_bytes: bytes,
) -> dict[str, bytes]:
    variant_config = config["variants"][variant]
    fixture_id = str(variant_config["fixture_id"])
    files = _domain_pack(config, float(variant_config["max_wait_s"]))
    mapping = pretty_json_bytes(_entity_mapping())
    session_sha256 = sha256_bytes(session)
    mapping_sha256 = sha256_bytes(mapping)
    files.update(
        {
            "entity-mapping.json": mapping,
            "expected-outcome.json": pretty_json_bytes(
                _expected_outcome(variant, fixture_id, len(source.frames))
            ),
            "normalization-report.json": pretty_json_bytes(
                _normalization_report(
                    fixture_id=fixture_id,
                    source=source,
                    input_fingerprint="0" * 64,
                    session_sha256=session_sha256,
                    mapping_sha256=mapping_sha256,
                )
            ),
            "session.jsonl": session,
            "source/adapter-environment.txt": (
                f"CPython 3.12\nLinux x86_64\nadapter={ADAPTER_ID}@{adapter_commit}\n"
            ).encode(),
            "source/frozen-config.json": config_bytes,
            "source/uv.lock": lock_bytes,
        }
    )
    provisional = _manifest(
        variant=variant,
        config=config,
        adapter_commit=adapter_commit,
        source=source,
        files=files,
    )
    input_fingerprint = _conversion_inputs_fingerprint(provisional)
    files["normalization-report.json"] = pretty_json_bytes(
        _normalization_report(
            fixture_id=fixture_id,
            source=source,
            input_fingerprint=input_fingerprint,
            session_sha256=session_sha256,
            mapping_sha256=mapping_sha256,
        )
    )
    files["source-manifest.json"] = pretty_json_bytes(
        _manifest(
            variant=variant,
            config=config,
            adapter_commit=adapter_commit,
            source=source,
            files=files,
        )
    )
    files["CHECKSUMS.sha256"] = _checksums(files)
    return files


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def write_conversion(
    *,
    config: Mapping[str, Any],
    adapter_commit: str,
    source: DecodedSource,
    output_root: Path,
    config_bytes: bytes,
    lock_bytes: bytes,
) -> dict[str, object]:
    if sha256_bytes(config_bytes) != FROZEN_CONFIG_SHA256:
        raise FixtureError("frozen config bytes differ from authenticated identity")
    if sha256_bytes(lock_bytes) != FROZEN_LOCK_SHA256:
        raise FixtureError("adapter lock bytes differ from authenticated identity")
    try:
        authenticated_config = json.loads(config_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:  # pragma: no cover - hash-bound bytes
        raise FixtureError(f"frozen config bytes are not valid JSON: {exc}") from exc
    if authenticated_config != config:
        raise FixtureError("parsed config differs from authenticated frozen bytes")
    session, session_summary = normalize_frames(source.frames, config)
    variants: dict[str, dict[str, object]] = {}
    for variant in ("incident", "control"):
        files = build_variant_files(
            variant=variant,
            config=config,
            adapter_commit=adapter_commit,
            source=source,
            session=session,
            session_summary=session_summary,
            config_bytes=config_bytes,
            lock_bytes=lock_bytes,
        )
        _write_files(output_root / variant, files)
        variants[variant] = {
            "fixture_fingerprint_sha256": sha256_bytes(files["CHECKSUMS.sha256"]),
            "fixture_id": config["variants"][variant]["fixture_id"],
            "max_wait_s": config["variants"][variant]["max_wait_s"],
        }
    root_files = {
        "capability-record.json": pretty_json_bytes(
            _capability_record(
                adapter_commit=adapter_commit,
                source=source,
                mapping_sha256=sha256_bytes(pretty_json_bytes(_entity_mapping())),
                lock_sha256=sha256_bytes(lock_bytes),
            )
        ),
        "rights-record.json": pretty_json_bytes(_rights_record()),
        "transform-provenance.json": pretty_json_bytes(_transform_provenance(source)),
    }
    _write_files(output_root, root_files)
    capability_value = _capability_record(
        adapter_commit=adapter_commit,
        source=source,
        mapping_sha256=sha256_bytes(pretty_json_bytes(_entity_mapping())),
        lock_sha256=sha256_bytes(lock_bytes),
    )
    summary = {
        "adapter_commit": adapter_commit,
        "capability_fingerprint_sha256": sha256_bytes(canonical_json_bytes(capability_value)),
        "config_sha256": FROZEN_CONFIG_SHA256,
        "control": variants["control"],
        "incident": variants["incident"],
        "outcome_stream_message_count": source.outcome_message_count,
        "outcome_stream_present": source.outcome_stream_present,
        "profile": PROFILE_ID,
        "schema_version": "org.metriplane.ros2_mcap.conversion_summary.v1",
        "shared_session_sha256": session_summary["shared_session_sha256"],
        "source_classification": SOURCE_CLASSIFICATION,
        "source_sha256": source.source_sha256,
        "source_size": source.source_size,
        "source_unchanged_during_conversion": True,
        **{key: value for key, value in session_summary.items() if key != "shared_session_sha256"},
    }
    (output_root / "conversion-summary.json").write_bytes(pretty_json_bytes(summary))
    return summary


__all__ = [
    "FixtureError",
    "build_variant_files",
    "normalize_frames",
    "write_conversion",
]
