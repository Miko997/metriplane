# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Mapping
from typing import Any

from metriplane_source_adapter_sdk import canonical_json_bytes

from .constants import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    SOURCE_CLASSIFICATION,
    SOURCE_DESCRIPTION,
    UPSTREAM_BLOBS,
    UPSTREAM_RAW_SHA256,
    UPSTREAM_RELEASE_COMMIT,
    UPSTREAM_SNAPSHOT_COMMIT,
)
from .models import AdapterConfig, SourceTrace


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_ref(path: str, data: bytes, media_type: str) -> dict[str, str]:
    return {"media_type": media_type, "path": path, "sha256": sha256_bytes(data)}


def conversion_environment() -> dict[str, str]:
    """Return truthful stable fields for the process performing conversion."""

    return {
        "architecture": platform.machine() or "unknown",
        "operating_system": platform.system() or "unknown",
        "runtime": platform.python_implementation(),
        "runtime_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def upstream_reference_register() -> dict[str, object]:
    roles = {
        "AMR_Interop_Standard.json": "referenced_schema",
        "AMR_Interop_Standard.pdf": "referenced_standard_document",
        "README.md": "repository_scope_context",
        "examples/identityReport1.json": "official_example_identity_message",
        "examples/statusReport1.json": "official_example_status_message",
    }
    artifacts = []
    for path, blob in UPSTREAM_BLOBS.items():
        artifacts.append(
            {
                "artifact_name": path,
                "git_blob": blob,
                "immutable_url": (
                    "https://github.com/MassRobotics-AMR/AMR_Interop_Standard/blob/"
                    f"{UPSTREAM_SNAPSHOT_COMMIT}/{path}"
                ),
                "included": False,
                "raw_sha256": UPSTREAM_RAW_SHA256[path],
                "repository_path": path,
                "retrieval_date": "2026-08-20",
                "rights_decision": "reference_only",
                "role": roles[path],
                "snapshot_commit": UPSTREAM_SNAPSHOT_COMMIT,
            }
        )
    return {
        "artifacts": artifacts,
        "formal_release": {
            "commit": "7161a0d2b26606941f5a012cd03c7f113beb7a22",
            "release_url": "https://github.com/MassRobotics-AMR/AMR_Interop_Standard/releases/tag/1.0",
            "short_commit": UPSTREAM_RELEASE_COMMIT,
            "tag": "1.0",
            "version": "1.0",
        },
        "repository": "https://github.com/MassRobotics-AMR/AMR_Interop_Standard",
        "rights_decision": "reference_only",
        "schema_version": "org.metriplane.massrobotics_amr.source_reference.v1",
        "snapshot_commit": UPSTREAM_SNAPSHOT_COMMIT,
        "upstream_artifacts_included": False,
    }


def rights_record() -> dict[str, object]:
    return {
        "claim_classification": "Owner-generated standards mapping and reproducible technical artifact",
        "components": [
            {
                "component": "Metriplane-authored synthetic identity and status JSONL records",
                "license": "MIT",
                "origin": "Metriplane repository",
                "redistribution": "allowed",
            },
            {
                "component": "Portable normalized fixture and operator-authored domain pack",
                "license": "MIT",
                "origin": "Metriplane-authored",
                "redistribution": "allowed",
            },
            {
                "component": "MassRobotics AMR Interoperability Standard repository materials",
                "included": False,
                "origin": "MassRobotics-AMR/AMR_Interop_Standard",
                "redistribution": "reference_only",
            },
        ],
        "conclusion": (
            "Only Metriplane-authored MIT source and derived bytes are included. Upstream "
            "MassRobotics materials remain immutable references and are not copied or packaged."
        ),
        "schema_version": "org.metriplane.massrobotics_amr.rights.v1",
    }


def coordinate_binding_record(config: AdapterConfig) -> dict[str, object]:
    binding = config.coordinate_binding
    return {
        "cross_datum_transforms": 0,
        "expected_planar_datum_uuid": config.expected_planar_datum_uuid,
        "source_linear_unit": binding.source_linear_unit,
        "schema_version": "org.metriplane.massrobotics_amr.coordinate_binding.v1",
        "target_frame": binding.target_frame,
        "target_linear_unit": binding.target_linear_unit,
        "transform": binding.transform,
        "unit_authority": binding.unit_authority,
        "warning": (
            "The metre binding is a fixture-specific operator interpretation and is not a "
            "universal MassRobotics standard fact."
        ),
        "zone_boundary_policy": config.zone.boundary_policy,
    }


def capability_record(
    *,
    trace: SourceTrace,
    config: AdapterConfig,
    adapter_commit: str,
    lock_sha256: str,
    mapping_sha256: str,
    environment: Mapping[str, str],
    deterministic: bool = False,
) -> dict[str, object]:
    evidence_ids = ["massrobotics_amr_adapter_commit"]
    base = {"evidence_ids": evidence_ids, "status": "verified"}
    artifacts = [
        {
            "artifact_id": "massrobotics_amr_identity_jsonl",
            "byte_size": len(trace.identity_bytes),
            "presence": "included",
            "rights_id": "metriplane_synthetic_source_rights",
            "role": "synthetic_identity_reports",
            "sha256": trace.identity_sha256,
            "uri": f"urn:sha256:{trace.identity_sha256}",
        },
        {
            "artifact_id": "massrobotics_amr_status_jsonl",
            "byte_size": len(trace.status_bytes),
            "presence": "included",
            "rights_id": "metriplane_synthetic_source_rights",
            "role": "synthetic_status_reports",
            "sha256": trace.status_sha256,
            "uri": f"urn:sha256:{trace.status_sha256}",
        },
    ]
    return {
        "adapter": {
            "adapter_id": ADAPTER_ID,
            "conversion_dependencies": ["metriplane-source-adapter-sdk==1.0.0"],
            "entrypoint": "massrobotics_amr_adapter.cli:main",
            "environment": {
                "architecture": environment["architecture"],
                "dependency_lock_sha256": lock_sha256,
                "operating_system": environment["operating_system"],
                "runtime": environment["runtime"],
                "runtime_version": environment["runtime_version"],
            },
            "implementation_commit": adapter_commit,
            "repository_uri": "https://github.com/Miko997/metriplane",
            "version": ADAPTER_VERSION,
        },
        "capabilities": {
            "anti_taint": {
                **base,
                "excluded_fields": [
                    "statusReport.operationalState",
                    "statusReport.errorCodes",
                    "statusReport.destinations",
                    "statusReport.path",
                ],
                "frame_state_events_policy": "empty",
                "inventory_complete": True,
                "used_as_incident_truth": False,
                "used_as_process_events": False,
            },
            "artifact_identity": {**base, "all_required_artifacts_hashed": True},
            "clock": {
                **base,
                "authority": "statusReport.timestamp with explicit UTC designator or offset",
                "authoritative": True,
                "domain": "UTC",
                "evaluation_field": "ts_sim_ns",
                "mapping_method": "affine",
                "order_only": False,
                "source_field": "statusReport.timestamp",
                "source_unit": "nanoseconds",
            },
            "completeness": {
                **base,
                "carry_forward": {"fields": [], "max_gap_ns": None, "method": "none"},
                "frame_semantics": "complete_snapshot",
                "interpolation": "none",
                "materialization_method": "exact_snapshot_join",
                "omission_policy": "reject_omission",
                "partial_updates_materialized": True,
                "resampling": "none",
                "source_stream_semantics": "partial_updates",
                "synchronization": "exact_timestamp",
                "synchronization_tolerance_ns": 0,
                "unknown_state_policy": "reject_fixture",
            },
            "coordinates": {
                **base,
                "projection_method": "identity_3d",
                "source_frame": "metriplane_world",
                "source_units": "meters",
                "target_frame": "metriplane_world",
                "target_units": "meters",
                "transform_method": "identity operator-configured fixture binding",
            },
            "deterministic_conversion": {
                "clean_run_count": 3 if deterministic else 1,
                "compared_output_count": 3 if deterministic else 0,
                "comparison_policy": "byte_identity" if deterministic else "not_demonstrated",
                "equivalent": deterministic,
                "evidence_ids": evidence_ids,
                "input_fingerprint_sha256": hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "config": config.sha256,
                            "identity": trace.identity_sha256,
                            "status": trace.status_sha256,
                        }
                    )
                ).hexdigest(),
                "status": "verified" if deterministic else "not_demonstrated",
            },
            "entity_identity": {
                **base,
                "explicit_mapping": True,
                "mapping_schema": "metriplane.external_entity_mapping.v1",
                "mapping_sha256": mapping_sha256,
                "normalized_entities": [
                    {"normalized_id": item, "process_relevant": True}
                    for item in config.entity_order
                ],
                "required_entities": list(config.entity_order),
                "stable": True,
            },
            "field_provenance": {**base, "complete": True, "trust_layers_separated": True},
            "information_loss": {
                **base,
                "declared": True,
                "items": [
                    "validated current orientation is not normalized",
                    "linear velocity is not converted to Cartesian vel_world",
                    "path and destinations remain predictions",
                    "battery, runtime, load, error, and operational state do not drive Atlas",
                    "live transport and session metadata do not exist",
                ],
            },
            "portable_evaluation": {
                "environments": [
                    {"operating_system": os_name, "python_version": version, "status": "required"}
                    for os_name in ("Ubuntu", "macOS")
                    for version in ("3.12", "3.13")
                ],
                "evidence_ids": evidence_ids,
                "source_dependencies_required": False,
                "status": "not_demonstrated",
            },
            "rights": base,
            "semantics": {
                **base,
                "prohibited": [
                    "General MassRobotics compatibility or conformance",
                    "Live MQTT, WebSocket, QoS, retained-message, or transport semantics",
                    "Cross-datum transforms, automatic unit inference, carry-forward, interpolation, or resampling",
                    "Fleet management, task dispatch, path planning, robot control, production, safety, or ISO 21423 claims",
                    "External-source evidence, organizational validation, endorsement, or vendor adoption",
                ],
                "supported": [
                    "One bounded two-AMR rendezvous replay from Metriplane-authored synthetic MassRobotics-format identity and current-status records"
                ],
            },
        },
        "contract": {
            "fit": "verified",
            "frame_state_model_version": "1.0",
            "profile": "metriplane.atlas.complete_snapshot.v1",
            "version": "metriplane.external_source_contract.v1",
        },
        "evidence": [
            {
                "evidence_id": evidence_ids[0],
                "identity": adapter_commit,
                "kind": "git_commit",
                "uri": f"https://github.com/Miko997/metriplane/commit/{adapter_commit}",
            }
        ],
        "limitations": [
            SOURCE_DESCRIPTION,
            "One exact configured single-datum current-location profile",
            "Upstream standard materials are reference-only and excluded",
            "Portable operating-system rows remain required until CI passes",
        ],
        "record": {
            "classification": "native",
            "evidence_classification": SOURCE_CLASSIFICATION,
            "statement": "Native capability declaration for one bounded Metriplane-authored synthetic format-engineering source.",
            "subject": "candidate_adapter",
        },
        "schema_version": "metriplane.source_adapter_capability.v1",
        "source": {
            "artifacts": artifacts,
            "family": "Bounded synthetic MassRobotics AMR identity and status JSONL records",
            "project_uri": "https://github.com/Miko997/metriplane",
            "revision": adapter_commit,
            "revision_kind": "adapter_commit",
            "rights": {
                "derived_fixture": {
                    "basis": "MIT Metriplane-authored normalized state and operator rules.",
                    "redistribution": "verified",
                    "rights_id": "synthetic_normalized_fixture",
                    "subject": "normalized_fixture",
                },
                "source_bytes_in_fixture": True,
                "source_records": [
                    {
                        "basis": "Metriplane-authored synthetic records under the repository MIT license.",
                        "rights_id": "metriplane_synthetic_source_rights",
                        "source_redistribution": "allowed",
                        "source_use": "verified",
                        "subject_artifact_ids": [item["artifact_id"] for item in artifacts],
                    }
                ],
            },
        },
    }


def conversion_inputs_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Mirror External Source Contract v1's canonical Stage-1 fingerprint."""

    source_artifacts = json.loads(json.dumps(manifest["source_artifacts"]))
    for artifact in source_artifacts:
        for key in ("sha256", "uri", "path", "immutable_identifier"):
            artifact.setdefault(key, None)
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
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "capability_record",
    "conversion_environment",
    "conversion_inputs_fingerprint",
    "coordinate_binding_record",
    "file_ref",
    "pretty_json_bytes",
    "rights_record",
    "sha256_bytes",
    "upstream_reference_register",
]
