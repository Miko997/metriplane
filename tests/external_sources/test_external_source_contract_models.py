# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from metriplane.external_sources.contract import (
    CONTRACT_PROFILE,
    CONTRACT_SCHEMA_VERSION,
    EntityMappingDocument,
    ExpectedOutcome,
    ExternalSourceManifestV1,
    SourceArtifact,
    conversion_inputs_sha256,
    evaluation_inputs_sha256,
    validate_external_fixture_bundle,
    validate_safe_relative_path,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
VALID_BUNDLE = REPOSITORY_ROOT / "examples" / "external_sources" / "minimal"
INVALID_CASES = sorted((Path(__file__).parent / "fixtures" / "invalid").glob("*.json"))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_session(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_session(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_checksums(root: Path) -> None:
    checksum_path = root / "CHECKSUMS.sha256"
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path != checksum_path),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    checksum_path.write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in paths),
        encoding="utf-8",
    )


def _mutate_invalid_case(root: Path, case: str) -> None:
    manifest_path = root / "source-manifest.json"
    session_path = root / "session.jsonl"
    report_path = root / "normalization-report.json"
    manifest = _read_json(manifest_path)
    rows = _read_session(session_path)
    report = _read_json(report_path)
    session_changed = False
    report_changed = False

    if case == "unsupported_contract_version":
        manifest["schema_version"] = "metriplane.external_source_contract.v2"
    elif case == "unknown_top_level_field":
        manifest["unexpected_shared_field"] = "prohibited"
    elif case == "malformed_hash":
        manifest["source_artifacts"][0]["sha256"] = "not-a-sha256"
    elif case == "missing_source_artifact_hash":
        del manifest["source_artifacts"][0]["sha256"]
    elif case == "unsafe_path_traversal":
        manifest["normalized_artifacts"]["session"]["path"] = "../session.jsonl"
    elif case == "unresolved_public_rights":
        manifest["rights"]["source_artifacts"][0]["source_use_permission"] = "unresolved"
    elif case == "partial_update_as_complete":
        completeness = manifest["normalization"]["completeness"]
        completeness["source_stream_semantics"] = "partial_update"
        completeness["partial_updates_materialized"] = False
    elif case == "undeclared_transform":
        del manifest["normalization"]["coordinates"]["transform"]
    elif case == "undeclared_projection":
        del manifest["normalization"]["coordinates"]["projection"]
    elif case == "missing_zone_assignment_method":
        del manifest["normalization"]["zone_assignment"]["method"]
    elif case == "unknown_state_as_absence":
        manifest["normalization"]["completeness"]["unknown_state_policy"] = "treat_as_absence"
    elif case == "undeclared_resampling":
        del manifest["normalization"]["temporal_alignment"]["resampling"]
    elif case == "undeclared_interpolation":
        del manifest["normalization"]["temporal_alignment"]["interpolation"]
    elif case == "fabricated_confidence":
        for row in rows:
            for item in row["objects"]:
                item["confidence"] = 1.0
        session_changed = True
        environment = manifest["adapter"]["environment"]["dependency_lock"]
        metadata = next(
            artifact
            for artifact in manifest["source_artifacts"]
            if artifact["artifact_id"] == "metadata"
        )
        implementation_reference = {
            "path": environment["path"],
            "sha256": environment["sha256"],
            "media_type": environment["media_type"],
        }
        parameters_reference = {
            "path": metadata["path"],
            "sha256": metadata["sha256"],
            "media_type": metadata["media_type"],
        }
        manifest["normalization"]["confidence"] = {
            "mode": "documented_algorithm",
            "algorithm": "Prohibited placeholder confidence generator.",
            "implementation": implementation_reference,
            "input_fields": ["samples[*].entities[*].position_xyz"],
            "parameters": parameters_reference,
            "output_semantics": "Placeholder value with no observation-quality meaning.",
            "placeholder_or_invented_values": True,
        }
        manifest["normalization"]["field_provenance"].append(
            {
                "normalized_field": "objects[*].confidence",
                "layer": "adapter_derived_fact",
                "source_artifact_ids": ["trajectory"],
                "source_fields": ["samples[*].entities[*].position_xyz"],
                "derivation": "Emit a prohibited invented placeholder.",
                "parameter_references": [
                    implementation_reference,
                    parameters_reference,
                ],
                "confidence_origin": "documented_algorithm",
            }
        )
    elif case == "source_label_as_incident_truth":
        manifest["normalization"]["source_annotations"]["used_as_incident_truth"] = True
    elif case == "extension_without_namespace":
        manifest["extensions"] = {"maniskill": {"trajectory_id": "0"}}
    elif case == "extension_semantic_override":
        manifest["extensions"] = {"org.example.bad": {"incident_truth": True}}
    elif case == "extension_camelcase_semantic_override":
        manifest["extensions"] = {"org.example.bad": {"domainPackOverride": True}}
    elif case == "domain_pack_role_alias":
        alias = manifest["domain_pack"]["contracts"]
        manifest["domain_pack"]["assets"] = alias
        manifest["normalization"]["atlas_asset_mapping"] = alias
    elif case == "blank_coordinate_frame":
        manifest["normalization"]["coordinates"]["source_frame"] = "   "
    elif case == "mutable_adapter_commit":
        manifest["adapter"]["commit"] = "main"
    elif case == "contradictory_source_selection":
        manifest["selection"]["group_path"] = "/data/demo_0"
    elif case == "identity_clock_with_fixed_step":
        manifest["normalization"]["clock"]["fixed_step_ns"] = 1_000_000_000
    elif case == "reject_outside_with_label":
        zone = manifest["normalization"]["zone_assignment"]
        zone["outside_workspace_policy"] = "reject"
    elif case == "expected_outcome_as_adapter_input":
        expected = manifest["normalized_artifacts"]["expected_outcome"]
        manifest["adapter"]["parameters"] = {
            "reference": {
                "path": expected["path"],
                "sha256": expected["sha256"],
                "media_type": expected["media_type"],
            },
            "sha256": expected["sha256"],
        }
    elif case == "entity_mapping_as_adapter_input":
        mapping_reference = {
            key: value
            for key, value in manifest["normalization"]["entity_mapping"].items()
            if key != "schema_version"
        }
        manifest["adapter"]["parameters"] = {
            "reference": mapping_reference,
            "sha256": mapping_reference["sha256"],
        }
    elif case == "source_annotation_feeds_zone":
        provenance = manifest["normalization"]["field_provenance"][6]
        provenance["source_artifact_ids"] = ["metadata"]
        provenance["source_fields"] = ["source_annotations.reward"]
    elif case == "resampling_field_marked_source_fact":
        manifest["normalization"]["temporal_alignment"]["resampling"] = {
            "method": "selected_source_frames",
            "fields": ["frame_id"],
            "max_gap_ns": 3_000_000_000,
        }
    elif case == "nonexistent_provenance_parameter":
        manifest["normalization"]["field_provenance"][4]["parameter_references"] = [
            {
                "path": "missing-parameters.json",
                "sha256": "0" * 64,
                "media_type": "application/json",
            }
        ]
    elif case == "trust_layer_zone_contradiction":
        provenance = manifest["normalization"]["field_provenance"][6]
        provenance["layer"] = "source_fact"
        provenance["source_fields"] = ["samples[*].entities[*].zone"]
        provenance.pop("derivation")
        provenance.pop("parameter_references")
    elif case == "undeclared_forward_fill":
        completeness = manifest["normalization"]["completeness"]
        mapping_reference = {
            key: value
            for key, value in manifest["normalization"]["entity_mapping"].items()
            if key != "schema_version"
        }
        completeness["source_stream_semantics"] = "partial_update"
        completeness["partial_updates_materialized"] = True
        completeness["materialization"] = {
            "method": "documented_algorithm",
            "fields": ["objects[*].pos_world"],
            "implementation": "Attempt to conceal unbounded last-observation carry-forward.",
            "parameters": mapping_reference,
            "carry_forward_dependency": "declared_bounded_policy",
        }
    elif case == "fusion_parameters_missing_from_stage_1":
        mapping_path = root / "entity-mapping.json"
        mapping = _read_json(mapping_path)
        metadata = next(
            artifact
            for artifact in manifest["source_artifacts"]
            if artifact["artifact_id"] == "metadata"
        )
        entry = mapping["mappings"][0]
        entry["source_entities"].append(
            {
                "source_artifact_id": "metadata",
                "source_entity_id": "carrier_metadata",
            }
        )
        entry["fusion"] = {
            "method": "priority",
            "implementation": "Prefer trajectory identity over metadata identity.",
            "parameters": {
                "path": metadata["path"],
                "sha256": metadata["sha256"],
                "media_type": metadata["media_type"],
            },
        }
        _write_json(mapping_path, mapping)
        mapping_sha256 = _sha256(mapping_path)
        manifest["normalization"]["entity_mapping"]["sha256"] = mapping_sha256
        for provenance in manifest["normalization"]["field_provenance"]:
            if provenance["normalized_field"] == "objects[*].id":
                provenance["parameter_references"][0]["sha256"] = mapping_sha256
        for run in report["conversion_reproducibility"]["runs"]:
            run["artifacts"]["entity-mapping.json"] = mapping_sha256
        report_changed = True
    elif case == "normalization_report_operation_mismatch":
        report["operations"] = [
            operation for operation in report["operations"] if operation["kind"] != "carry_forward"
        ]
        report_changed = True
    elif case == "stage_1_run_includes_expected_outcome":
        expected = manifest["normalized_artifacts"]["expected_outcome"]
        for run in report["conversion_reproducibility"]["runs"]:
            run["artifacts"][expected["path"]] = expected["sha256"]
        report_changed = True
    elif case == "nonmonotonic_time":
        rows[2]["ts"] = 0.5
        session_changed = True
    elif case == "duplicate_object_ids":
        rows[0]["objects"][1]["id"] = rows[0]["objects"][0]["id"]
        session_changed = True
    elif case == "nonfinite_state":
        rows[0]["objects"][0]["pos_world"][0] = float("nan")
        session_changed = True
    elif case == "ambiguous_omission":
        rows[1]["objects"] = [rows[1]["objects"][0]]
        session_changed = True
    elif case == "undeclared_derived_field":
        rows[0]["objects"][0]["vel_world"] = [0.0, 0.0, 0.0]
        session_changed = True
    elif case == "unknown_state_in_frame":
        rows[0]["objects"][0]["zone"] = None
        session_changed = True
    elif case == "prohibited_source_incident_label":
        rows[0]["incident_id"] = "SOURCE-INCIDENT-1"
        session_changed = True
    elif case == "nonempty_frame_events":
        rows[0]["events"] = [
            {
                "object_id": "reference_probe_pose",
                "ts": 0.0,
                "type": "zone_enter",
                "zone": "probe_storage",
            }
        ]
        session_changed = True
    elif case == "polygon_zone_contradiction":
        rows[0]["objects"][0]["zone"] = "measurement_zone"
        session_changed = True
    elif case == "unmapped_authoritative_object":
        for row in rows:
            row["objects"].append(
                {
                    "id": "unmapped_context_pose",
                    "pos_world": [0.6, 0.6, 0.0],
                    "zone": "input_buffer",
                }
            )
        session_changed = True
    elif case == "irregular_fixed_step":
        clock = manifest["normalization"]["clock"]
        clock.update(
            {
                "source_clock": "synthetic frame index",
                "source_field": "samples[*].sample_index",
                "source_unit": "index",
                "evaluation_field": "ts_sim_ns",
                "mapping_method": "fixed_step",
                "fixed_step_ns": 1_000_000_000,
                "fixed_step_origin_ns": 0,
                "description": "Map contiguous frame indices to one-second fixed steps.",
            }
        )
        manifest["normalization"]["field_provenance"].append(
            {
                "normalized_field": "ts_sim_ns",
                "layer": "adapter_derived_fact",
                "source_artifact_ids": ["trajectory"],
                "source_fields": ["samples[*].sample_index"],
                "derivation": "Multiply source index by the declared fixed step.",
            }
        )
        for row, value in zip(rows, [0, 1_000_000_000, 3_500_000_000, 4_000_000_000]):
            row["ts_sim_ns"] = value
        session_changed = True
    else:  # pragma: no cover - every checked-in descriptor must have a handler
        raise AssertionError(f"unhandled invalid fixture case: {case}")

    if session_changed:
        _write_session(session_path, rows)
        manifest["normalized_artifacts"]["session"]["sha256"] = _sha256(session_path)
    if report_changed:
        _write_json(report_path, report)
        manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(root)


@pytest.mark.parametrize(
    "case_path",
    INVALID_CASES,
    ids=lambda path: path.stem,
)
def test_negative_fixture_fails_with_actionable_error(
    tmp_path: Path,
    case_path: Path,
) -> None:
    descriptor = _read_json(case_path)
    root = tmp_path / descriptor["case"]
    shutil.copytree(VALID_BUNDLE, root)
    _mutate_invalid_case(root, descriptor["case"])

    with pytest.raises(ValueError) as error:
        validate_external_fixture_bundle(root)

    assert descriptor["expected_error"] in str(error.value)


def test_contract_and_profile_versions_are_independent() -> None:
    manifest = ExternalSourceManifestV1.model_validate(
        _read_json(VALID_BUNDLE / "source-manifest.json")
    )
    assert manifest.schema_version == CONTRACT_SCHEMA_VERSION
    assert manifest.contract_profile == CONTRACT_PROFILE
    assert manifest.normalization.frame_state_model_version == "1.0"
    assert manifest.evaluation.metriplane_version == "0.4.0.post1"
    assert (
        len(
            {
                manifest.schema_version,
                manifest.contract_profile,
                manifest.normalization.frame_state_model_version,
                manifest.evaluation.metriplane_version,
            }
        )
        == 4
    )

    for invalid_version in ("0.4.0.post", "0.4.0.post0", "0.4.0.post01", "0.4.0.post1.extra"):
        payload = _read_json(VALID_BUNDLE / "source-manifest.json")
        payload["evaluation"]["metriplane_version"] = invalid_version
        with pytest.raises(ValueError, match="exact supported package version"):
            ExternalSourceManifestV1.model_validate(payload)


def test_reference_only_source_can_use_immutable_identifier() -> None:
    artifact = SourceArtifact.model_validate(
        {
            "artifact_id": "private_trajectory",
            "role": "trajectory",
            "media_type": "application/x-hdf5",
            "rights_id": "private-source-rights",
            "presence": "withheld",
            "uri": "private://university-lab/fixture-17",
            "immutable_identifier": "lab-ledger:fixture-17:revision-4",
            "description": "Source retained inside the authorized environment.",
        }
    )
    assert artifact.sha256 is None
    assert artifact.immutable_identifier == "lab-ledger:fixture-17:revision-4"


def test_entity_mapping_supports_declared_multi_source_fusion() -> None:
    mapping = EntityMappingDocument.model_validate(
        {
            "schema_version": "metriplane.external_entity_mapping.v1",
            "mappings": [
                {
                    "source_entities": [
                        {
                            "source_artifact_id": "camera_a",
                            "source_entity_id": "carrier",
                        },
                        {
                            "source_artifact_id": "camera_b",
                            "source_entity_id": "carrier",
                        },
                    ],
                    "normalized_object_id": "carrier_pose",
                    "atlas_asset_id": "carrier_1",
                    "process_relevant": True,
                    "description": "Fuse two independently identified pose streams.",
                    "fusion": {
                        "method": "weighted",
                        "implementation": "Deterministic weighted pose fusion.",
                        "parameters": {
                            "path": "adapter/fusion-parameters.json",
                            "sha256": "0" * 64,
                            "media_type": "application/json",
                        },
                    },
                }
            ],
        }
    )
    assert len(mapping.mappings[0].source_entities) == 2


def test_referenced_source_rejects_blank_immutable_identifier() -> None:
    with pytest.raises(ValueError, match="immutable_identifier"):
        SourceArtifact.model_validate(
            {
                "artifact_id": "private_trajectory",
                "role": "trajectory",
                "media_type": "application/x-hdf5",
                "rights_id": "private-source-rights",
                "presence": "withheld",
                "uri": "private://university-lab/fixture-17",
                "immutable_identifier": "   ",
                "description": "Source retained inside the authorized environment.",
            }
        )


@pytest.mark.parametrize(
    "value",
    [
        "../session.jsonl",
        "/session.jsonl",
        "domain\\pack",
        "a//b",
        "a/./b",
        "C:/x",
        "a\nb",
        "a\tb",
        "a\x7fb",
    ],
)
def test_safe_relative_paths_reject_ambiguous_or_escaping_values(value: str) -> None:
    with pytest.raises(ValueError, match="unsafe bundle path"):
        validate_safe_relative_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "doi: 10.1000/example",
        "https://example.invalid/source?X-Amz-Signature=secret",
        "https://example.invalid/source?X-Amz-Security-Token=secret",
        "https://example.invalid/source#access-token=secret",
    ],
)
def test_absolute_uris_reject_whitespace_and_credential_material(value: str) -> None:
    manifest = _read_json(VALID_BUNDLE / "source-manifest.json")
    manifest["source_project"]["canonical_uri"] = value
    with pytest.raises(ValueError):
        ExternalSourceManifestV1.model_validate(manifest)


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "mkfifo"),
    reason="FIFO creation is available only on supported POSIX platforms",
)
def test_bundle_rejects_nonregular_fifo_entry(tmp_path: Path) -> None:
    root = tmp_path / "fixture-with-fifo"
    shutil.copytree(VALID_BUNDLE, root)
    fifo = root / "unexpected.pipe"
    os.mkfifo(fifo)

    with pytest.raises(
        ValueError,
        match=r"bundle entry is not a regular file or directory: unexpected\.pipe",
    ):
        validate_external_fixture_bundle(root)


def test_expected_outcome_type_inventory_matches_counts() -> None:
    with pytest.raises(ValueError, match="event_types length"):
        ExpectedOutcome.model_validate(
            {
                "schema_version": "metriplane.external_expected_outcome.v1",
                "role": "test_metadata_only",
                "atlas_input": False,
                "fixture_id": "fixture",
                "frame_count": 1,
                "event_count": 1,
                "deviation_count": 0,
                "incident_count": 0,
                "event_types": [],
                "incident_types": [],
                "evidence_bundle_verified": False,
                "regression_passed": False,
            }
        )


def test_conversion_and_evaluation_fingerprints_are_separate() -> None:
    manifest = ExternalSourceManifestV1.model_validate(
        _read_json(VALID_BUNDLE / "source-manifest.json")
    )
    conversion = conversion_inputs_sha256(manifest)
    evaluation = evaluation_inputs_sha256(manifest)
    assert conversion != evaluation

    updated = manifest.model_copy(
        update={
            "evaluation": manifest.evaluation.model_copy(
                update={"metriplane_version": "0.3.0+different-evaluation"}
            )
        }
    )
    assert conversion_inputs_sha256(updated) == conversion
    assert evaluation_inputs_sha256(updated) != evaluation


def test_checked_schema_exposes_safe_path_constraint() -> None:
    schema = _read_json(
        REPOSITORY_ROOT / "schemas" / "metriplane.external_source_contract.v1.schema.json"
    )
    pattern = schema["$defs"]["FileReference"]["properties"]["path"]["pattern"]
    assert re.fullmatch(pattern, "domain-pack/assets.yaml") is not None
    assert re.fullmatch(pattern, "../assets.yaml") is None


def test_private_fixture_can_include_explicitly_authorized_private_source(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-fixture"
    shutil.copytree(VALID_BUNDLE, root)
    manifest_path = root / "source-manifest.json"
    report_path = root / "normalization-report.json"
    manifest = _read_json(manifest_path)
    manifest["fixture"]["distribution"] = "private"
    manifest["rights"]["fixture"].update(
        {
            "access": "private",
            "redistribution": "private",
            "redistribution_permission": "verified",
            "permission_basis": "Authorized only inside this private test fixture.",
        }
    )
    for declaration in manifest["rights"]["source_artifacts"]:
        declaration.update(
            {
                "source_access": "private",
                "source_use_permission": "verified",
                "redistribution": "private",
                "redistribution_permission": "verified",
                "permission_basis": "Explicit private test-fixture authorization.",
            }
        )

    parsed = ExternalSourceManifestV1.model_validate(manifest)
    report = _read_json(report_path)
    report["conversion_reproducibility"]["input_fingerprint_sha256"] = conversion_inputs_sha256(
        parsed
    )
    _write_json(report_path, report)
    manifest["normalized_artifacts"]["normalization_report"]["sha256"] = _sha256(report_path)
    _write_json(manifest_path, manifest)
    _rewrite_checksums(root)

    fixture = validate_external_fixture_bundle(root)
    assert fixture.manifest.fixture.distribution == "private"
    assert len(fixture.manifest.rights.source_artifacts) == 2
