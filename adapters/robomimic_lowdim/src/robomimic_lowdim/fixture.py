# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministic construction of the two portable External Source bundles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .constants import (
    CONTROL_PERIOD_NS,
    DATASET_REPOSITORY,
    DATASET_REVISION,
    DEFAULT_LOCK,
    FRAME_COUNT,
    FROZEN_CONFIG_SHA256,
    PREPARED_REPOSITORY_PATH,
    PREPARED_ROBOSUITE_COMMIT,
    PREPARED_SHA256,
    PREPARED_SIZE,
    PROJECT_COMMIT,
    RAW_REPOSITORY_PATH,
    RAW_ROBOSUITE_COMMIT,
    RAW_SHA256,
    RAW_SIZE,
    SOURCE_BACKEND,
)
from .hdf5_audit import SourceAuditError, SourceFrame, reject_symlink_components, sha256_file


class FixtureError(RuntimeError):
    """Raised when deterministic fixture construction cannot proceed safely."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def load_config(path: str | Path) -> dict[str, Any]:
    try:
        supplied = reject_symlink_components(path, label="frozen config")
    except SourceAuditError as exc:
        raise FixtureError(str(exc)) from exc
    if supplied.is_symlink() or not supplied.is_file():
        raise FixtureError(f"frozen config: expected regular, non-symlink file: {supplied}")
    source = supplied.resolve()
    actual_hash = sha256_file(source)
    if actual_hash != FROZEN_CONFIG_SHA256:
        raise FixtureError(
            f"frozen config: SHA-256 mismatch; expected {FROZEN_CONFIG_SHA256}, "
            f"computed {actual_hash}"
        )
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"frozen config: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise FixtureError("frozen config: root must be an object")
    required = {
        "adapter",
        "coordinate_mapping",
        "selection",
        "source",
        "target_polygon",
        "timing",
        "variants",
        "witnesses",
    }
    missing = sorted(required - set(value))
    if missing:
        raise FixtureError(f"frozen config: missing fields {missing}")
    source_config = value["source"]
    if not isinstance(source_config, dict):
        raise FixtureError("frozen config: source must be an object")
    expected = {
        "dataset_repository": DATASET_REPOSITORY,
        "dataset_revision": DATASET_REVISION,
        "project_commit": PROJECT_COMMIT,
        "prepared_robosuite_commit": PREPARED_ROBOSUITE_COMMIT,
        "raw_robosuite_commit": RAW_ROBOSUITE_COMMIT,
    }
    for name, wanted in expected.items():
        if source_config.get(name) != wanted:
            raise FixtureError(f"frozen config: unexpected source.{name}")
    if (
        value["selection"].get("demo_id") != "demo_0"
        or value["selection"].get("rows") != FRAME_COUNT
    ):
        raise FixtureError("frozen config: only demo_0 with 118 rows is supported")
    return value


def _point_on_segment(
    x: float, y: float, ax: float, ay: float, bx: float, by: float, *, tolerance: float = 1e-12
) -> bool:
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    if abs(cross) > tolerance:
        return False
    dot = (x - ax) * (bx - ax) + (y - ay) * (by - ay)
    if dot < -tolerance:
        return False
    squared = (bx - ax) ** 2 + (by - ay) ** 2
    return dot <= squared + tolerance


def point_in_polygon_inclusive(x: float, y: float, vertices: Sequence[Sequence[float]]) -> bool:
    points = [(float(point[0]), float(point[1])) for point in vertices]
    if len(points) < 3:
        raise FixtureError("target polygon requires at least three vertices")
    if any(
        _point_on_segment(x, y, ax, ay, bx, by)
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=True)
    ):
        return True
    inside = False
    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
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
    frames: Sequence[SourceFrame], config: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    if len(frames) != FRAME_COUNT:
        raise FixtureError(f"normalization: expected {FRAME_COUNT} frames, got {len(frames)}")
    polygon = config["target_polygon"]
    if not isinstance(polygon, Mapping):
        raise FixtureError("normalization: malformed polygon configuration")
    vertices = polygon["vertices"]
    zone_id = str(polygon["zone_id"])
    outside = str(polygon["outside_label"])
    output: list[bytes] = []
    can_inside: list[int] = []
    tcp_inside: list[int] = []
    for index, frame in enumerate(frames):
        values = (*frame.can_xyz, *frame.tcp_xyz)
        if any(
            not isinstance(value, float) or not (-float("inf") < value < float("inf"))
            for value in values
        ):
            raise FixtureError(f"normalization: frame {index} contains nonfinite state")
        can_zone = (
            zone_id
            if point_in_polygon_inclusive(frame.can_xyz[0], frame.can_xyz[1], vertices)
            else outside
        )
        tcp_zone = (
            zone_id
            if point_in_polygon_inclusive(frame.tcp_xyz[0], frame.tcp_xyz[1], vertices)
            else outside
        )
        if can_zone == zone_id:
            can_inside.append(index)
        if tcp_zone == zone_id:
            tcp_inside.append(index)
        timestamp_ns = index * CONTROL_PERIOD_NS
        row = {
            "events": [],
            "frame_id": index,
            "objects": [
                {
                    "id": "can_1",
                    "pos_world": [float(frame.can_xyz[0]), float(frame.can_xyz[1]), 0.0],
                    "zone": can_zone,
                },
                {
                    "id": "robot_tcp_1",
                    "pos_world": [float(frame.tcp_xyz[0]), float(frame.tcp_xyz[1]), 0.0],
                    "zone": tcp_zone,
                },
            ],
            "schema_version": "1.0",
            "source_backend": SOURCE_BACKEND,
            "ts": timestamp_ns / 1_000_000_000,
            "ts_sim_ns": timestamp_ns,
        }
        output.append(canonical_json_bytes(row))
    session = b"".join(output)
    return session, {
        "can_inside_first_frame": can_inside[0] if can_inside else None,
        "can_inside_last_frame": can_inside[-1] if can_inside else None,
        "tcp_inside_first_frame": tcp_inside[0] if tcp_inside else None,
        "tcp_inside_last_frame": tcp_inside[-1] if tcp_inside else None,
        "shared_session_sha256": hashlib.sha256(session).hexdigest(),
    }


def _yaml_bytes(value: object) -> bytes:
    # JSON is a strict YAML 1.2 subset. This keeps the isolated adapter free of a
    # YAML dependency while producing deterministic Atlas-compatible YAML files.
    return pretty_json_bytes(value)


def _file_reference(path: str, data: bytes, media_type: str) -> dict[str, str]:
    return {
        "media_type": media_type,
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _entity_mapping() -> dict[str, object]:
    return {
        "mappings": [
            {
                "atlas_asset_id": "can_1",
                "description": (
                    "One-to-one mapping from the named prepared Can world-position field "
                    "to the normalized material object, witnessed by raw Can_joint0 qpos."
                ),
                "normalized_object_id": "can_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "can_ph_prepared_lowdim_hdf5",
                        "source_entity_id": "data/demo_0/obs/object[:,7:10]",
                    }
                ],
            },
            {
                "atlas_asset_id": "robot_tcp_1",
                "description": (
                    "One-to-one mapping from the named prepared robot0_eef_pos world field "
                    "to the normalized tool, witnessed by independent XML-tree FK."
                ),
                "normalized_object_id": "robot_tcp_1",
                "process_relevant": True,
                "source_entities": [
                    {
                        "source_artifact_id": "can_ph_prepared_lowdim_hdf5",
                        "source_entity_id": "data/demo_0/obs/robot0_eef_pos",
                    }
                ],
            },
        ],
        "schema_version": "metriplane.external_entity_mapping.v1",
    }


def _domain_pack_files(config: Mapping[str, Any], max_wait_s: float) -> dict[str, bytes]:
    polygon = config["target_polygon"]
    assets = {
        "schema_version": "metriplane.atlas.asset_registry.v1",
        "assets": [
            {
                "object_id": "can_1",
                "asset_id": "can_1",
                "asset_type": "material",
                "label": "Prepared Can world position (planar material object)",
                "work_order_id": "WO-ROBOMIMIC-CAN-001",
                "expected_zones": ["target_xy_region"],
                "expected_stations": ["target_station"],
            },
            {
                "object_id": "robot_tcp_1",
                "asset_id": "robot_tcp_1",
                "asset_type": "tool",
                "label": "Prepared Panda TCP world position (planar required tool)",
                "work_order_id": "WO-ROBOMIMIC-CAN-001",
                "expected_zones": ["target_xy_region"],
                "expected_stations": ["target_station"],
            },
        ],
    }
    workspace = {
        "schema_version": "metriplane.atlas.workspace.v1",
        "cell_id": "robomimic_can_ph_planar_fixture",
        "units": "meters",
        "zones": [
            {
                "zone_id": "target_xy_region",
                "zone_type": "work_station",
                "label": "Operator-configured planar compatibility region",
                "polygon": polygon["vertices"],
            }
        ],
        "stations": [
            {
                "station_id": "target_station",
                "zone_id": "target_xy_region",
                "label": "Operator-configured planar compatibility station",
            }
        ],
    }
    process = {
        "schema_version": "metriplane.atlas.process_model.v1",
        "process_id": "robomimic_can_ph_planar_tcp_presence",
        "work_order_type": "external_fixture",
        "steps": [
            {
                "step_id": "can_region_requires_tcp",
                "label": "Can in operator region requires robot TCP",
                "expected_asset_types": ["material"],
                "required_assets": ["robot_tcp_1"],
                "required_zone": "target_xy_region",
                "required_station": "target_station",
                "max_wait_s": max_wait_s,
            }
        ],
    }
    contracts = {
        "schema_version": "metriplane.atlas.contracts.v1",
        "contracts": [
            {
                "contract_id": "robot_tcp_required_with_can",
                "kind": "process_asset_presence",
                "process_step_id": "can_region_requires_tcp",
                "required_asset_id": "robot_tcp_1",
                "zone_id": "target_xy_region",
                "station_id": "target_station",
                "max_wait_s": max_wait_s,
                "severity": "warning",
                "note": (
                    "Observe-only Metriplane-authored planar rule; not official robomimic "
                    "task success, safety, or source truth."
                ),
            }
        ],
    }
    work_orders = (
        b"work_order_id,process_id,product,priority\n"
        b"WO-ROBOMIMIC-CAN-001,robomimic_can_ph_planar_tcp_presence,"
        b"robomimic_can_planar_fixture,normal\n"
    )
    return {
        "domain-pack/assets.yaml": _yaml_bytes(assets),
        "domain-pack/contracts.yaml": _yaml_bytes(contracts),
        "domain-pack/process.yaml": _yaml_bytes(process),
        "domain-pack/work_orders.csv": work_orders,
        "domain-pack/workspace.yaml": _yaml_bytes(workspace),
    }


def _source_artifacts() -> list[dict[str, object]]:
    base = f"https://huggingface.co/datasets/{DATASET_REPOSITORY}/resolve/{DATASET_REVISION}/"
    return [
        {
            "artifact_id": "can_ph_raw_hdf5",
            "description": (
                "Pinned official raw Can PH HDF5 used only for correspondence, clock, "
                "named-qpos, and FK witnesses; referenced and never included."
            ),
            "media_type": "application/x-hdf5",
            "presence": "referenced",
            "rights_id": "robomimic-dataset-mit",
            "role": "raw_simulation_demonstration",
            "sha256": RAW_SHA256,
            "uri": base + RAW_REPOSITORY_PATH,
        },
        {
            "artifact_id": "can_ph_prepared_lowdim_hdf5",
            "description": (
                "Pinned official prepared low-dimensional Can PH HDF5 supplying the two "
                "named world-position observations; referenced and never included."
            ),
            "media_type": "application/x-hdf5",
            "presence": "referenced",
            "rights_id": "robomimic-dataset-mit",
            "role": "prepared_low_dimensional_observations",
            "sha256": PREPARED_SHA256,
            "uri": base + PREPARED_REPOSITORY_PATH,
        },
    ]


def _rights() -> dict[str, object]:
    citation = [
        {
            "text": "robomimic official datasets repository, Can Proficient Human v1.5 raw and low-dimensional artifacts",
            "uri": f"https://huggingface.co/datasets/{DATASET_REPOSITORY}/tree/{DATASET_REVISION}/v1.5/can/ph",
        },
        {
            "text": "robomimic project",
            "uri": "https://github.com/ARISE-Initiative/robomimic",
        },
    ]
    license_record = {
        "identifier": "MIT",
        "status": "declared",
        "uri": f"https://huggingface.co/datasets/{DATASET_REPOSITORY}/blob/{DATASET_REVISION}/README.md",
    }
    return {
        "fixture": {
            "access": "public",
            "citation": citation,
            "license": license_record,
            "permission_basis": (
                "The pinned dataset card declares MIT. The normalized coordinates are "
                "modified/derived data distributed with attribution and the MIT notice; "
                "raw/prepared HDF5, simulator assets, and source framework code are absent."
            ),
            "redistribution": "allowed",
            "redistribution_permission": "verified",
        },
        "source_artifacts": [
            {
                "citation": citation,
                "license": license_record,
                "permission_basis": (
                    "The MIT declaration is repository-wide at the exact immutable dataset "
                    "revision and covers both files in the same Can/ph directory."
                ),
                "redistribution": "allowed",
                "redistribution_permission": "verified",
                "rights_id": "robomimic-dataset-mit",
                "source_access": "public",
                "source_use_permission": "verified",
            }
        ],
    }


def _annotation_policy() -> dict[str, object]:
    raw = "can_ph_raw_hdf5"
    prepared = "can_ph_prepared_lowdim_hdf5"
    values = [
        ("raw actions", "data/demo_*/actions", raw),
        ("prepared actions", "data/demo_*/actions", prepared),
        ("reward", "data/demo_*/rewards", prepared),
        ("done", "data/demo_*/dones", prepared),
        ("prepared next observation", "data/demo_*/next_obs/*", prepared),
        ("controller information", "data/demo_*/controller_info", raw),
        ("interventions", "data/demo_*/interventions", raw),
        ("policy acting", "data/demo_*/policy_acting", raw),
        ("user acting", "data/demo_*/user_acting", raw),
        ("user information", "data/demo_*/user_info", raw),
        ("filter membership", "mask/*", (raw, prepared)),
    ]
    return {
        "annotations": [
            {
                "name": name,
                "retained_in": "not_retained",
                "source_artifact_ids": list(artifact)
                if isinstance(artifact, tuple)
                else [artifact],
                "source_field": field,
                "treatment": "excluded",
            }
            for name, field, artifact in values
        ],
        "frame_state_events_policy": "empty",
        "inventory_complete": True,
        "source_incident_ids_in_normalized_input": False,
        "used_as_incident_truth": False,
        "used_as_process_events": False,
    }


def _normalization_operations() -> list[dict[str, object]]:
    return [
        {
            "applied": True,
            "declaration_path": "normalization.clock",
            "kind": "time_mapping",
            "operation_id": "map-verified-source-row-to-fixed-nanoseconds",
            "summary": "Verified raw states[:,0] equals i/20 and mapped row i to i*50000000 ns.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.entity_mapping",
            "kind": "entity_mapping",
            "operation_id": "map-can-and-tcp",
            "summary": "Applied the hashed one-to-one Can and robot TCP mapping.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.coordinates.transform",
            "kind": "coordinate_transform",
            "operation_id": "identity-robosuite-world-frame",
            "summary": "Source and target use the same metre-valued robosuite world frame.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.coordinates.projection",
            "kind": "projection",
            "operation_id": "project-planar-xy",
            "summary": "Copied source world x/y, set normalized z to zero, and omitted orientation.",
        },
        {
            "applied": True,
            "declaration_path": "normalization.zone_assignment",
            "kind": "zone_assignment",
            "operation_id": "assign-frozen-operator-polygon",
            "summary": "Applied the Layer-C inclusive polygon and explicit outside label.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.synchronization",
            "kind": "synchronization",
            "operation_id": "no-synchronization",
            "summary": "Each prepared obs row supplies both named observations synchronously.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.resampling",
            "kind": "resampling",
            "operation_id": "no-resampling",
            "summary": "All 118 prepared obs rows are retained one-for-one.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.temporal_alignment.interpolation",
            "kind": "interpolation",
            "operation_id": "no-interpolation",
            "summary": "No position or time value is interpolated.",
        },
        {
            "applied": False,
            "declaration_path": "normalization.completeness.carry_forward",
            "kind": "carry_forward",
            "operation_id": "no-carry-forward",
            "summary": "Every retained obs row is complete; no observation is carried forward.",
        },
    ]


def _manifest(
    *,
    config: Mapping[str, Any],
    variant: str,
    adapter_commit: str,
    files: Mapping[str, bytes],
    config_sha256: str,
) -> dict[str, object]:
    variant_config = config["variants"][variant]
    fixture_id = str(variant_config["fixture_id"])
    domain_pack_id = str(variant_config["domain_pack_id"])
    mapping_file_ref = _file_reference(
        "entity-mapping.json", files["entity-mapping.json"], "application/json"
    )
    mapping_ref = {**mapping_file_ref, "schema_version": "metriplane.external_entity_mapping.v1"}
    workspace_ref = _file_reference(
        "domain-pack/workspace.yaml", files["domain-pack/workspace.yaml"], "application/yaml"
    )
    assets_ref = _file_reference(
        "domain-pack/assets.yaml", files["domain-pack/assets.yaml"], "application/yaml"
    )
    environment_ref = _file_reference("source/uv.lock", files["source/uv.lock"], "text/plain")
    parameter_ref = _file_reference(
        "source/frozen-config.json", files["source/frozen-config.json"], "application/json"
    )
    raw = "can_ph_raw_hdf5"
    prepared = "can_ph_prepared_lowdim_hdf5"
    limitations = [
        "This fixture evaluates bounded XY occupancy and timing only; it does not evaluate 3D placement, orientation, grasp state, reward, or official Can task success.",
        "Prepared named observations are consumed as prepared fields, not represented as raw source truth; raw states and embedded XML are correspondence witnesses.",
        "Source Z and complete source quaternions, including yaw, roll, and pitch, are excluded from normalized evaluation.",
        "Episode selection was outcome-blind only within an upstream success-filtered corpus.",
        "The target polygon and both waits are operator-authored compatibility-test rules, not robomimic or robosuite task semantics.",
        "This single trajectory establishes no general robomimic compatibility, physical accuracy, safety, quality, or source-project endorsement.",
    ]
    return {
        "adapter": {
            "adapter_id": "org.metriplane.robomimic_lowdim",
            "commit": adapter_commit,
            "entrypoint": "robomimic_lowdim.cli:main",
            "environment": {
                "architecture": "x86_64",
                "dependency_lock": environment_ref,
                "description": (
                    "Pinned isolated Linux direct-HDF5 conversion environment; no robomimic, "
                    "robosuite, MuJoCo, Torch, or source simulator is imported."
                ),
                "operating_system": "Linux",
                "runtime": "CPython",
                "runtime_version": "3.12",
            },
            "name": "Metriplane robomimic low-dimensional adapter",
            "parameters": {"reference": parameter_ref, "sha256": config_sha256},
            "repository_uri": "https://github.com/Miko997/metriplane",
            "version": "1.0.0",
        },
        "contract_profile": "metriplane.atlas.complete_snapshot.v1",
        "domain_pack": {
            "assets": assets_ref,
            "contracts": _file_reference(
                "domain-pack/contracts.yaml",
                files["domain-pack/contracts.yaml"],
                "application/yaml",
            ),
            "domain_pack_id": domain_pack_id,
            "process": _file_reference(
                "domain-pack/process.yaml", files["domain-pack/process.yaml"], "application/yaml"
            ),
            "rationale": (
                "The operator froze a 0.04 m square around the selected source Can row-0 XY. "
                "It is a compatibility-test rule, not the source task's success definition."
            ),
            "rule_origin": "operator_configured_rules",
            "source_annotations_used": False,
            "work_orders": _file_reference(
                "domain-pack/work_orders.csv", files["domain-pack/work_orders.csv"], "text/csv"
            ),
            "workspace": workspace_ref,
        },
        "evaluation": {
            "domain_pack_id": domain_pack_id,
            "engine": "atlas",
            "expected_outcome_is_input": False,
            "metriplane_version": "0.3.0",
            "provenance_layer": "metriplane_derived_results",
        },
        "extensions": {
            "org.robomimic.can_ph": {
                "code_identity_context": {
                    "robomimic_commit": PROJECT_COMMIT,
                    "robomimic_package": "0.5.0",
                    "prepared_robosuite_commit": PREPARED_ROBOSUITE_COMMIT,
                    "prepared_robosuite_release": "v1.5.1",
                    "raw_robosuite_commit": RAW_ROBOSUITE_COMMIT,
                    "raw_robosuite_release": "v1.5.0",
                    "hosted_artifact_generation_commit_claimed": False,
                },
                "artifact_environment_boundary": {
                    "raw_robosuite_version": "1.5.0",
                    "prepared_robosuite_version": "1.5.1",
                    "current_project_commits_used_as_generation_identity": False,
                },
                "corpus_limitation": (
                    "Episode selection was outcome-blind only within an upstream "
                    "success-filtered corpus."
                ),
                "prepared_field_witnesses": {
                    "can": "array-exact named Can_joint0 qpos translation",
                    "tcp": "independent embedded-XML FK to gripper0_right_grip_site within 2e-12",
                },
                "selection_accounting": {
                    "demo_id": "demo_0",
                    "normalized_frames": FRAME_COUNT,
                    "prepared_observation_rows": FRAME_COUNT,
                    "raw_state_rows": FRAME_COUNT,
                },
                "source_byte_sizes": {"prepared_hdf5": PREPARED_SIZE, "raw_hdf5": RAW_SIZE},
                "source_field_exclusions": [
                    "object relative-to-EFF position/quaternion block",
                    "object and TCP z",
                    "object and TCP quaternion",
                    "actions",
                    "next_obs",
                    "rewards",
                    "dones",
                    "filter membership",
                ],
            }
        },
        "fixture": {
            "bounded_recording": True,
            "description": (
                "All 118 prepared obs rows from pinned Can PH demo_0, normalized as complete "
                "position-only Can and robot TCP planar snapshots."
            ),
            "distribution": "derived_only",
            "fixture_id": fixture_id,
            "title": f"robomimic Can PH demo_0 planar {variant} fixture",
        },
        "limitations": limitations,
        "normalization": {
            "atlas_asset_mapping": assets_ref,
            "authoritative_object_collection": "objects",
            "clock": {
                "description": (
                    "Require raw and prepared states to match and raw states[:,0] to equal "
                    "i/20 within 1e-12 s; map row i to ts_sim_ns=i*50000000."
                ),
                "evaluation_field": "ts_sim_ns",
                "fixed_step_ns": CONTROL_PERIOD_NS,
                "fixed_step_origin_ns": 0,
                "mapping_method": "fixed_step",
                "source_clock": "raw MuJoCo simulation time sampled once per source control step",
                "source_field": "data/demo_0/states[:,0]",
                "source_unit": "seconds",
            },
            "completeness": {
                "carry_forward": {"fields": [], "method": "none"},
                "frame_semantics": "complete_snapshot",
                "omission_policy": "reject_omission",
                "partial_updates_materialized": False,
                "process_relevant_entity_policy": "known_in_every_frame",
                "source_stream_semantics": "complete_snapshot",
                "unknown_state_policy": "reject_fixture",
            },
            "confidence": {"mode": "absent"},
            "coordinates": {
                "information_loss": [
                    {
                        "impact": (
                            "Atlas receives only world x/y with z=0 and no orientation; 3D pose, "
                            "relative geometry, grasp state, and official task success cannot be evaluated."
                        ),
                        "lost_information": [
                            "Can source z coordinate",
                            "robot TCP source z coordinate",
                            "Can complete source quaternion",
                            "robot TCP complete source quaternion",
                            "relative Can-to-EFF position and quaternion",
                            "yaw, roll, and pitch",
                        ],
                        "operation": "position-only planar projection",
                    }
                ],
                "projection": {
                    "dropped_axes": ["z"],
                    "implementation": "Copy proven robosuite-world x/y, set normalized z to 0.0, omit orientation.",
                    "method": "planar_xy",
                    "output_z_policy": "zero",
                },
                "source_frame": "robosuite_world",
                "source_units": "meters",
                "target_frame": "robosuite_world",
                "target_units": "meters",
                "transform": {
                    "implementation": "No translation, rotation, scaling, or axis swap.",
                    "method": "identity",
                },
            },
            "entity_mapping": mapping_ref,
            "field_provenance": [
                {
                    "derivation": "Set the frozen FrameStateModel 1.0 schema version.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "schema_version",
                    "source_artifact_ids": [raw, prepared],
                },
                {
                    "derivation": "Set the stable namespaced prepared-observation backend.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "source_backend",
                    "source_artifact_ids": [raw, prepared],
                },
                {
                    "derivation": "Derive seconds from the exact integer nanosecond mapping.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "ts",
                    "source_artifact_ids": [raw],
                    "source_fields": ["data/demo_0/states[:,0]"],
                },
                {
                    "derivation": "Require raw time i/20 and multiply row index by 50000000 ns.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "ts_sim_ns",
                    "source_artifact_ids": [raw],
                    "source_fields": ["data/demo_0/states[:,0]"],
                },
                {
                    "derivation": "Assign sequential normalized IDs from prepared obs row order.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "frame_id",
                    "source_artifact_ids": [raw, prepared],
                    "source_fields": ["data/demo_0/states row order", "data/demo_0/obs row order"],
                },
                {
                    "derivation": "Apply the separately hashed one-to-one entity mapping.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].id",
                    "parameter_references": [mapping_file_ref],
                    "source_artifact_ids": [prepared],
                    "source_fields": [
                        "data/demo_0/obs/object[:,7:10]",
                        "data/demo_0/obs/robot0_eef_pos",
                    ],
                },
                {
                    "derivation": (
                        "Read only the two named prepared world-position fields after requiring "
                        "exact raw Can qpos and independent XML-FK TCP witnesses; copy x/y and set z=0."
                    ),
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].pos_world",
                    "source_artifact_ids": [raw, prepared],
                    "source_fields": [
                        "data/demo_0/obs/object[:,7:10]",
                        "data/demo_0/obs/robot0_eef_pos",
                        "data/demo_0/states[:,31:34]",
                        "data/demo_0/states[:,1:38]",
                        "data/demo_0@model_file/Can_joint0",
                        "data/demo_0@model_file/gripper0_right_grip_site",
                    ],
                },
                {
                    "derivation": "Apply the separately hashed Layer-C inclusive polygon.",
                    "layer": "adapter_derived_fact",
                    "normalized_field": "objects[*].zone",
                    "parameter_references": [workspace_ref],
                    "source_artifact_ids": [prepared],
                    "source_fields": [
                        "data/demo_0/obs/object[:,7:10]",
                        "data/demo_0/obs/robot0_eef_pos",
                    ],
                },
            ],
            "frame_state_model_version": "1.0",
            "source_annotations": _annotation_policy(),
            "source_backend": SOURCE_BACKEND,
            "temporal_alignment": {
                "interpolation": {"fields": [], "method": "none"},
                "resampling": {"fields": [], "method": "none"},
                "synchronization": {"fields": [], "method": "not_applicable"},
            },
            "zone_assignment": {
                "boundary_policy": "inclusive",
                "definitions": workspace_ref,
                "implementation": (
                    "Test each x/y point against the frozen polygon including its boundary, "
                    "reject overlap, and emit outside_workspace when outside."
                ),
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
                **_file_reference(
                    "expected-outcome.json", files["expected-outcome.json"], "application/json"
                ),
                "atlas_input": False,
                "role": "test_metadata_only",
            },
            "normalization_report": _file_reference(
                "normalization-report.json", files["normalization-report.json"], "application/json"
            ),
            "session": {
                **_file_reference("session.jsonl", files["session.jsonl"], "application/x-ndjson"),
                "frame_count": FRAME_COUNT,
                "frame_state_model_version": "1.0",
            },
        },
        "rights": _rights(),
        "schema_version": "metriplane.external_source_contract.v1",
        "selection": {
            "artifact_ids": [raw, prepared],
            "episode_id": "demo_0",
            "method": "episode",
            "rationale": (
                "Select the lowest numeric demo satisfying predeclared structural, finiteness, "
                "identity, raw/prepared, timing, rights, and non-degenerate planar criteria. "
                "Selection was outcome-blind within an upstream success-filtered corpus."
            ),
        },
        "source_artifacts": _source_artifacts(),
        "source_project": {
            "canonical_uri": f"https://huggingface.co/datasets/{DATASET_REPOSITORY}",
            "name": "robomimic official datasets",
            "revision": {"kind": "dataset_revision", "value": DATASET_REVISION},
            "version": "v1.5/can/ph",
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


def _conversion_inputs_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Mirror External Source Contract v1's pydantic model-dump fingerprint."""
    source_artifacts = json.loads(json.dumps(manifest["source_artifacts"]))
    for artifact in source_artifacts:
        artifact.setdefault("path", None)
        artifact.setdefault("immutable_identifier", None)
    selection = json.loads(json.dumps(manifest["selection"]))
    for key in (
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
    for key in ("scale", "offset", "lookup"):
        normalization["clock"].setdefault(key, None)
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
    payload = {
        "schema_version": manifest["schema_version"],
        "contract_profile": manifest["contract_profile"],
        "source_project": manifest["source_project"],
        "source_artifacts": source_artifacts,
        "selection": selection,
        "rights": manifest["rights"],
        "adapter": adapter,
        "normalization": normalization,
    }
    # The contract fingerprints canonical JSON text, not the NDJSON helper's
    # trailing record delimiter.
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _normalization_report(
    *, fixture_id: str, input_fingerprint: str, session_sha256: str, mapping_sha256: str
) -> dict[str, object]:
    artifacts = {"entity-mapping.json": mapping_sha256, "session.jsonl": session_sha256}
    return {
        "contract_schema_version": "metriplane.external_source_contract.v1",
        "conversion_reproducibility": {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": False,
            "input_fingerprint_sha256": input_fingerprint,
            "runs": [{"artifacts": artifacts, "run_id": f"{fixture_id}-current-conversion"}],
            "status": "not_demonstrated",
        },
        "fixture_id": fixture_id,
        "limitations": [
            "Position-only planar conversion discards source Z and complete object/TCP orientation.",
            "Prepared observations remain explicitly prepared fields; raw state and XML are independent witnesses, not emitted values.",
            "The result does not evaluate grasp state, official Can success, physical accuracy, simulator realism, or safety.",
            "The row-0-centered polygon and waits are wholly operator-configured Layer-C rules.",
            "Episode selection was outcome-blind only within an upstream success-filtered corpus.",
        ],
        "normalized_frame_count": FRAME_COUNT,
        "omitted_process_relevant_observations": 0,
        "operations": _normalization_operations(),
        "process_relevant_entity_count": 2,
        "result": "pass",
        "schema_version": "metriplane.external_normalization_report.v1",
        "source_record_count": FRAME_COUNT,
        "unknown_process_relevant_observations": 0,
        "warnings": [],
    }


def _expected_outcome(variant: str, fixture_id: str) -> dict[str, object]:
    incident = variant == "incident"
    event_types = (
        ["required_asset_missing", "step_delayed", "required_asset_present", "step_completed"]
        if incident
        else ["required_asset_missing", "required_asset_present", "step_completed"]
    )
    return {
        "atlas_input": False,
        "deviation_count": 1 if incident else 0,
        "event_count": len(event_types),
        "event_types": event_types,
        "evidence_bundle_verified": incident,
        "fixture_id": fixture_id,
        "frame_count": FRAME_COUNT,
        "incident_count": 1 if incident else 0,
        "incident_types": ["missing_tool_caused_delay"] if incident else [],
        "regression_passed": incident,
        "role": "test_metadata_only",
        "schema_version": "metriplane.external_expected_outcome.v1",
    }


def _adapter_environment(config_sha256: str, adapter_commit: str) -> bytes:
    runtime_version = platform.python_version()
    architecture = platform.machine()
    operating_system = platform.system()
    if not runtime_version.startswith("3.12."):
        raise FixtureError(f"conversion environment: CPython 3.12 required, got {runtime_version}")
    if operating_system != "Linux" or architecture != "x86_64":
        raise FixtureError("conversion environment: frozen lock declaration requires Linux x86_64")
    if platform.python_implementation() != "CPython":
        raise FixtureError("conversion environment: CPython implementation required")
    for package, expected in {
        "h5py": "3.16.0",
        "huggingface-hub": "1.27.0",
        "numpy": "2.5.2",
    }.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise FixtureError(f"conversion environment: missing {package}") from exc
        if actual != expected:
            raise FixtureError(
                f"conversion environment: {package}=={expected} required, got {actual}"
            )
    return (
        "adapter=robomimic-lowdim-adapter==1.0.0\n"
        f"adapter_commit={adapter_commit}\n"
        f"frozen_config_sha256={config_sha256}\n"
        f"python=CPython=={runtime_version}\n"
        f"operating_system={operating_system}\n"
        f"architecture={architecture}\n"
        "h5py==3.16.0\n"
        "huggingface-hub==1.27.0\n"
        "numpy==2.5.2\n"
        "robomimic_imported=false\n"
        "robosuite_imported=false\n"
        "mujoco_imported=false\n"
        "action_replay=false\n"
        "portable_fixture_requires_source_framework=false\n"
    ).encode()


def _checksum_inventory(files: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n"
        for path, data in sorted(files.items())
        if path != "CHECKSUMS.sha256"
    ).encode("utf-8")


def _write_bytes(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, data in files.items():
        if relative.startswith("/") or ".." in Path(relative).parts or "\\" in relative:
            raise FixtureError(f"unsafe durable path: {relative!r}")
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


FIXTURE_FILE_INVENTORY = {
    "CHECKSUMS.sha256",
    "domain-pack/assets.yaml",
    "domain-pack/contracts.yaml",
    "domain-pack/process.yaml",
    "domain-pack/work_orders.csv",
    "domain-pack/workspace.yaml",
    "entity-mapping.json",
    "expected-outcome.json",
    "normalization-report.json",
    "session.jsonl",
    "source/adapter-environment.txt",
    "source/frozen-config.json",
    "source/uv.lock",
    "source-manifest.json",
}

SHARED_VARIANT_FILES = {
    "domain-pack/assets.yaml",
    "domain-pack/work_orders.csv",
    "domain-pack/workspace.yaml",
    "entity-mapping.json",
    "session.jsonl",
    "source/adapter-environment.txt",
    "source/frozen-config.json",
    "source/uv.lock",
}


def write_fixtures(
    frames: Sequence[SourceFrame],
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    audit_report: Mapping[str, Any] | None = None,
    allow_unbound_test_fixture: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", adapter_commit) is None:
        raise FixtureError("adapter commit: expected one exact lowercase 40-hex commit")
    try:
        config_supplied = reject_symlink_components(config_path, label="frozen config")
        output_supplied = reject_symlink_components(output_root, label="output")
    except SourceAuditError as exc:
        raise FixtureError(str(exc)) from exc
    if config_supplied.is_symlink():
        raise FixtureError("frozen config symlinks are prohibited")
    if output_supplied.is_symlink():
        raise FixtureError("output symlinks are prohibited")
    config_source = config_supplied.resolve()
    if DEFAULT_LOCK.is_symlink():
        raise FixtureError("adapter dependency lock symlinks are prohibited")
    lock_source = DEFAULT_LOCK.resolve()
    output = output_supplied.resolve()
    for semantic_input in (config_source, lock_source):
        if (
            output == semantic_input
            or output in semantic_input.parents
            or semantic_input in output.parents
        ):
            raise FixtureError(
                f"output/input overlap: output {output} and semantic input must be disjoint"
            )
    config = load_config(config_source)
    if audit_report is None and not allow_unbound_test_fixture:
        raise FixtureError("real-source audit report is required for claim-bearing fixture output")
    if audit_report is not None:
        required_audit = {
            "demo_count": 200,
            "clock_rows_verified": 23_207,
            "can_named_qpos_rows_verified": 23_207,
            "selected_demo": "demo_0",
            "selected_frame_count": 118,
            "states_actions_model_sample_masks_equal": True,
            "mask_membership_equal": True,
            "raw_sha256": RAW_SHA256,
            "prepared_sha256": PREPARED_SHA256,
        }
        for name, expected in required_audit.items():
            if audit_report.get(name) != expected:
                raise FixtureError(f"real-source audit report: unexpected {name}")
        if float(audit_report.get("max_fk_abs_error", float("inf"))) > 2e-12:
            raise FixtureError("real-source audit report: FK tolerance not satisfied")
    config_sha256 = sha256_file(config_source)
    if not lock_source.is_file() or lock_source.is_symlink():
        raise FixtureError(f"adapter dependency lock missing or unsafe: {lock_source}")
    session, accounting = normalize_frames(frames, config)
    if (
        normalize_frames(frames, config)[0] != session
        or normalize_frames(frames, config)[0] != session
    ):
        raise FixtureError("normalization determinism: repeated session bytes differ")
    session_sha256 = hashlib.sha256(session).hexdigest()
    if audit_report is not None and accounting != {
        "can_inside_first_frame": 0,
        "can_inside_last_frame": 63,
        "tcp_inside_first_frame": 42,
        "tcp_inside_last_frame": 64,
        "shared_session_sha256": "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246",
    }:
        raise FixtureError("audited selected-frame stream differs from frozen source stream")
    mapping_bytes = pretty_json_bytes(_entity_mapping())
    mapping_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    if output.exists() and not overwrite:
        raise FixtureError(f"output {output}: already exists; pass --overwrite explicitly")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        summaries: dict[str, Any] = {}
        frozen_config_bytes = config_source.read_bytes()
        lock_bytes = lock_source.read_bytes()
        environment_bytes = _adapter_environment(config_sha256, adapter_commit)
        for variant in ("incident", "control"):
            variant_config = config["variants"][variant]
            fixture_id = str(variant_config["fixture_id"])
            files: dict[str, bytes] = {
                "entity-mapping.json": mapping_bytes,
                "session.jsonl": session,
                "source/adapter-environment.txt": environment_bytes,
                "source/frozen-config.json": frozen_config_bytes,
                "source/uv.lock": lock_bytes,
                **_domain_pack_files(config, float(variant_config["max_wait_s"])),
            }
            files["expected-outcome.json"] = pretty_json_bytes(
                _expected_outcome(variant, fixture_id)
            )
            files["normalization-report.json"] = pretty_json_bytes(
                _normalization_report(
                    fixture_id=fixture_id,
                    input_fingerprint="0" * 64,
                    session_sha256=session_sha256,
                    mapping_sha256=mapping_sha256,
                )
            )
            manifest = _manifest(
                config=config,
                variant=variant,
                adapter_commit=adapter_commit,
                files=files,
                config_sha256=config_sha256,
            )
            input_fingerprint = _conversion_inputs_fingerprint(manifest)
            files["normalization-report.json"] = pretty_json_bytes(
                _normalization_report(
                    fixture_id=fixture_id,
                    input_fingerprint=input_fingerprint,
                    session_sha256=session_sha256,
                    mapping_sha256=mapping_sha256,
                )
            )
            files["source-manifest.json"] = pretty_json_bytes(
                _manifest(
                    config=config,
                    variant=variant,
                    adapter_commit=adapter_commit,
                    files=files,
                    config_sha256=config_sha256,
                )
            )
            files["CHECKSUMS.sha256"] = _checksum_inventory(files)
            _write_bytes(stage / variant, files)
            summaries[variant] = {
                "fixture_fingerprint_sha256": hashlib.sha256(files["CHECKSUMS.sha256"]).hexdigest(),
                "fixture_id": fixture_id,
                "max_wait_s": variant_config["max_wait_s"],
            }
        summary = {
            "adapter_commit": adapter_commit,
            "config_sha256": config_sha256,
            "control": summaries["control"],
            "incident": summaries["incident"],
            "schema_version": "org.metriplane.robomimic_lowdim.conversion_summary.v1",
            "shared_session_sha256": session_sha256,
            "source_sha256": {"prepared_hdf5": PREPARED_SHA256, "raw_hdf5": RAW_SHA256},
            **accounting,
        }
        if audit_report is not None:
            summary["real_source_audit"] = {
                "can_named_qpos_rows_verified": audit_report["can_named_qpos_rows_verified"],
                "clock_rows_verified": audit_report["clock_rows_verified"],
                "demo_count": audit_report["demo_count"],
                "mask_membership_equal": audit_report["mask_membership_equal"],
                "max_fk_abs_error": audit_report["max_fk_abs_error"],
                "prepared_environment_version": audit_report["source_environment"][
                    "prepared_environment_version"
                ],
                "raw_environment_version": audit_report["source_environment"][
                    "raw_environment_version"
                ],
                "selected_demo": audit_report["selected_demo"],
                "selected_frame_count": audit_report["selected_frame_count"],
                "states_actions_model_sample_masks_equal": audit_report[
                    "states_actions_model_sample_masks_equal"
                ],
            }
        (stage / "conversion-summary.json").write_bytes(pretty_json_bytes(summary))
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise FixtureError(f"output {output}: refusing non-directory replacement")
            shutil.rmtree(output)
        stage.replace(output)
        return summary
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def relative_file_inventory(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _verify_variant_integrity(root: Path, variant: str) -> None:
    """Verify checksum coverage and the manifest/report's direct byte references."""
    checksum_path = root / "CHECKSUMS.sha256"
    manifest_path = root / "source-manifest.json"
    recorded: dict[str, str] = {}
    order: list[str] = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise FixtureError(f"equivalence {root}: malformed checksum inventory")
        digest, relative = match.groups()
        if relative in recorded or relative.startswith("/") or ".." in Path(relative).parts:
            raise FixtureError(f"equivalence {root}: unsafe or duplicate checksum path")
        recorded[relative] = digest
        order.append(relative)
    if order != sorted(order):
        raise FixtureError(f"equivalence {root}: checksum inventory is not sorted")
    if set(recorded) != FIXTURE_FILE_INVENTORY - {"CHECKSUMS.sha256"}:
        raise FixtureError(f"equivalence {root}: checksum inventory coverage mismatch")
    for relative, digest in recorded.items():
        if sha256_file(root / relative) != digest:
            raise FixtureError(f"equivalence {root}: checksum mismatch for {relative}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"equivalence {root}: invalid manifest JSON") from exc
    if manifest.get("schema_version") != "metriplane.external_source_contract.v1":
        raise FixtureError(f"equivalence {root}: unexpected contract schema version")
    if manifest.get("contract_profile") != "metriplane.atlas.complete_snapshot.v1":
        raise FixtureError(f"equivalence {root}: unexpected contract profile")
    if manifest.get("source_project", {}).get("revision") != {
        "kind": "dataset_revision",
        "value": DATASET_REVISION,
    }:
        raise FixtureError(f"equivalence {root}: unexpected source revision")
    if manifest.get("normalization", {}).get("frame_state_model_version") != "1.0":
        raise FixtureError(f"equivalence {root}: unexpected FrameStateModel version")
    clock = manifest.get("normalization", {}).get("clock", {})
    if (
        clock.get("mapping_method") != "fixed_step"
        or clock.get("fixed_step_ns") != CONTROL_PERIOD_NS
        or clock.get("fixed_step_origin_ns") != 0
    ):
        raise FixtureError(f"equivalence {root}: unexpected clock declaration")
    references = [
        manifest["adapter"]["environment"]["dependency_lock"],
        manifest["adapter"]["parameters"]["reference"],
        manifest["normalization"]["entity_mapping"],
        manifest["normalization"]["atlas_asset_mapping"],
        manifest["normalization"]["zone_assignment"]["definitions"],
        *[
            manifest["domain_pack"][name]
            for name in ("assets", "workspace", "process", "contracts", "work_orders")
        ],
        manifest["normalized_artifacts"]["session"],
        manifest["normalized_artifacts"]["normalization_report"],
        manifest["normalized_artifacts"]["expected_outcome"],
    ]
    for declaration in manifest["normalization"]["field_provenance"]:
        references.extend(declaration.get("parameter_references", []))
    for reference in references:
        relative = reference["path"]
        if sha256_file(root / relative) != reference["sha256"]:
            raise FixtureError(f"equivalence {root}: manifest reference mismatch for {relative}")
    report = json.loads((root / "normalization-report.json").read_text(encoding="utf-8"))
    if report.get("schema_version") != "metriplane.external_normalization_report.v1":
        raise FixtureError(f"equivalence {root}: unexpected report schema version")
    expected_fingerprint = _conversion_inputs_fingerprint(manifest)
    if (
        report.get("conversion_reproducibility", {}).get("input_fingerprint_sha256")
        != expected_fingerprint
    ):
        raise FixtureError(f"equivalence {root}: conversion input fingerprint mismatch")
    expected_artifacts = {
        "entity-mapping.json": sha256_file(root / "entity-mapping.json"),
        "session.jsonl": sha256_file(root / "session.jsonl"),
    }
    for run in report["conversion_reproducibility"]["runs"]:
        if run["artifacts"] != expected_artifacts:
            raise FixtureError(f"equivalence {root}: conversion-run artifacts do not match bytes")
    config_path = root / "source/frozen-config.json"
    if sha256_file(config_path) != FROZEN_CONFIG_SHA256:
        raise FixtureError(f"equivalence {root}: frozen config hash mismatch")
    config = load_config(config_path)
    adapter_commit = manifest.get("adapter", {}).get("commit", "")
    if re.fullmatch(r"[0-9a-f]{40}", adapter_commit) is None:
        raise FixtureError(f"equivalence {root}: invalid adapter commit")
    files = {
        relative: (root / relative).read_bytes()
        for relative in FIXTURE_FILE_INVENTORY
        if relative not in {"CHECKSUMS.sha256", "source-manifest.json"}
    }
    expected_manifest = _manifest(
        config=config,
        variant=variant,
        adapter_commit=adapter_commit,
        files=files,
        config_sha256=FROZEN_CONFIG_SHA256,
    )
    if manifest != expected_manifest:
        raise FixtureError(f"equivalence {root}: manifest differs from frozen construction")
    expected_report = _normalization_report(
        fixture_id=str(config["variants"][variant]["fixture_id"]),
        input_fingerprint=_conversion_inputs_fingerprint(expected_manifest),
        session_sha256=sha256_file(root / "session.jsonl"),
        mapping_sha256=sha256_file(root / "entity-mapping.json"),
    )
    if report != expected_report:
        raise FixtureError(
            f"equivalence {root}: normalization report differs from frozen construction"
        )


def finalize_conversion_equivalence(
    conversion_roots: Sequence[str | Path],
    *,
    output_root: str | Path,
    run_ids: Sequence[str] = ("clean-conversion-1", "clean-conversion-2", "clean-conversion-3"),
    overwrite: bool = False,
    allow_unbound_test_fixture: bool = False,
) -> dict[str, Any]:
    if len(conversion_roots) != 3:
        raise FixtureError("equivalence: exactly three clean conversion roots are required")
    if len(run_ids) != 3 or len(set(run_ids)) != 3 or any(not value.strip() for value in run_ids):
        raise FixtureError("equivalence: exactly three unique nonblank run IDs are required")
    try:
        root_supplied = [
            reject_symlink_components(value, label="equivalence root") for value in conversion_roots
        ]
        output_supplied = reject_symlink_components(output_root, label="equivalence output")
    except SourceAuditError as exc:
        raise FixtureError(str(exc)) from exc
    if any(root.is_symlink() for root in root_supplied):
        raise FixtureError("equivalence: conversion root symlinks are prohibited")
    if output_supplied.is_symlink():
        raise FixtureError("equivalence: output symlinks are prohibited")
    roots = [value.resolve() for value in root_supplied]
    output = output_supplied.resolve()
    if len(set(roots)) != 3:
        raise FixtureError("equivalence: conversion roots must be distinct")
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            raise FixtureError(f"equivalence: unsafe or missing root {root}")
        if output == root or output in root.parents or root in output.parents:
            raise FixtureError("equivalence: output and conversion roots must be disjoint")
        expected_root_entries = {"incident", "control", "conversion-summary.json"}
        if {path.name for path in root.iterdir()} != expected_root_entries:
            raise FixtureError(
                f"equivalence {root}: top-level inventory must be exactly "
                "incident/, control/, conversion-summary.json"
            )
        if not (root / "incident").is_dir() or not (root / "control").is_dir():
            raise FixtureError(f"equivalence {root}: incident/control must be directories")
        if not (root / "conversion-summary.json").is_file():
            raise FixtureError(f"equivalence {root}: conversion-summary.json must be a file")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise FixtureError(f"equivalence {root}: symlink prohibited: {path}")
        for relative in sorted(SHARED_VARIANT_FILES):
            if (root / "incident" / relative).read_bytes() != (
                root / "control" / relative
            ).read_bytes():
                raise FixtureError(
                    f"equivalence {root}: incident/control shared artifact differs: {relative}"
                )
    if output.exists() and not overwrite:
        raise FixtureError(f"equivalence output {output}: exists; pass --overwrite")
    compared: dict[str, str] = {}
    for variant in ("incident", "control"):
        for root in roots:
            inventory = relative_file_inventory(root / variant)
            if inventory != FIXTURE_FILE_INVENTORY:
                raise FixtureError(
                    f"equivalence {root / variant}: inventory mismatch; "
                    f"missing={sorted(FIXTURE_FILE_INVENTORY - inventory)}, "
                    f"extra={sorted(inventory - FIXTURE_FILE_INVENTORY)}"
                )
            _verify_variant_integrity(root / variant, variant)
        for relative in sorted(FIXTURE_FILE_INVENTORY):
            values = [(root / variant / relative).read_bytes() for root in roots]
            if values[0] != values[1] or values[0] != values[2]:
                raise FixtureError(f"equivalence: {variant}/{relative} differs across roots")
            compared[f"{variant}/{relative}"] = hashlib.sha256(values[0]).hexdigest()
    summaries = [(root / "conversion-summary.json").read_bytes() for root in roots]
    if summaries[0] != summaries[1] or summaries[0] != summaries[2]:
        raise FixtureError("equivalence: conversion-summary.json differs across roots")
    summary_document = json.loads(summaries[0])
    for variant in ("incident", "control"):
        expected_fingerprint = hashlib.sha256(
            (roots[0] / variant / "CHECKSUMS.sha256").read_bytes()
        ).hexdigest()
        if (
            summary_document.get(variant, {}).get("fixture_fingerprint_sha256")
            != expected_fingerprint
        ):
            raise FixtureError(
                f"equivalence: {variant} fixture fingerprint is not bound to its bytes"
            )
    if not allow_unbound_test_fixture:
        required_summary = {
            "config_sha256": FROZEN_CONFIG_SHA256,
            "shared_session_sha256": "bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246",
            "can_inside_first_frame": 0,
            "can_inside_last_frame": 63,
            "tcp_inside_first_frame": 42,
            "tcp_inside_last_frame": 64,
            "source_sha256": {"prepared_hdf5": PREPARED_SHA256, "raw_hdf5": RAW_SHA256},
        }
        for name, expected in required_summary.items():
            if summary_document.get(name) != expected:
                raise FixtureError(f"equivalence: unbound or unexpected summary field {name}")
        audit = summary_document.get("real_source_audit")
        if (
            not isinstance(audit, dict)
            or audit.get("demo_count") != 200
            or audit.get("clock_rows_verified") != 23_207
        ):
            raise FixtureError("equivalence: exact real-source audit attestation is required")
        for root in roots:
            for variant in ("incident", "control"):
                actual_session = sha256_file(root / variant / "session.jsonl")
                if actual_session != summary_document["shared_session_sha256"]:
                    raise FixtureError(
                        f"equivalence {root}: {variant} session is not the frozen audited session"
                    )
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        # Rebuild only the exact declared tree instead of copying arbitrary root
        # contents into a public portable artifact.
        for variant in ("incident", "control"):
            for relative in sorted(FIXTURE_FILE_INVENTORY):
                source = roots[0] / variant / relative
                destination = stage / variant / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
        (stage / "conversion-summary.json").write_bytes(
            (roots[0] / "conversion-summary.json").read_bytes()
        )
        fingerprints: dict[str, str] = {}
        for variant in ("incident", "control"):
            variant_root = stage / variant
            report_path = variant_root / "normalization-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            runs = [
                {
                    "artifacts": {
                        relative: sha256_file(roots[index] / variant / relative)
                        for relative in ("entity-mapping.json", "session.jsonl")
                    },
                    "run_id": run_id,
                }
                for index, run_id in enumerate(run_ids)
            ]
            report["conversion_reproducibility"].update(
                {"equivalent": True, "runs": runs, "status": "demonstrated"}
            )
            report_path.write_bytes(pretty_json_bytes(report))
            manifest_path = variant_root / "source-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["normalized_artifacts"]["normalization_report"]["sha256"] = sha256_file(
                report_path
            )
            manifest_path.write_bytes(pretty_json_bytes(manifest))
            files = {
                relative: (variant_root / relative).read_bytes()
                for relative in FIXTURE_FILE_INVENTORY
                if relative != "CHECKSUMS.sha256"
            }
            checksums = _checksum_inventory(files)
            (variant_root / "CHECKSUMS.sha256").write_bytes(checksums)
            fingerprints[variant] = hashlib.sha256(checksums).hexdigest()
        summary_path = stage / "conversion-summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["conversion_reproducibility"] = {
            "comparison_policy": "sha256_byte_identity",
            "equivalent": True,
            "run_ids": list(run_ids),
            "status": "demonstrated",
        }
        for variant, fingerprint in fingerprints.items():
            summary[variant]["fixture_fingerprint_sha256"] = fingerprint
        summary_path.write_bytes(pretty_json_bytes(summary))
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise FixtureError("equivalence: refusing non-directory output replacement")
            shutil.rmtree(output)
        stage.replace(output)
        return {
            "compared_artifact_count": len(compared),
            "control_fixture_fingerprint_sha256": fingerprints["control"],
            "equivalent": True,
            "incident_fixture_fingerprint_sha256": fingerprints["incident"],
            "run_ids": list(run_ids),
            "schema_version": "org.metriplane.robomimic_lowdim.equivalence.v1",
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def translate_audit_error(exc: SourceAuditError) -> FixtureError:
    return FixtureError(str(exc))
