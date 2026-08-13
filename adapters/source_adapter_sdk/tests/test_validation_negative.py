# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metriplane_source_adapter_sdk import (
    CapabilityValidationError,
    validate_capability,
    verify_repository_evidence,
)
from metriplane_source_adapter_sdk.canonical import load_json
from metriplane_source_adapter_sdk.validation import schema_path


def _delete(record: dict, path: tuple[str, ...]) -> None:
    target = record
    for part in path[:-1]:
        target = target[part]
    del target[path[-1]]


@pytest.mark.parametrize(
    "path",
    [
        ("schema_version",),
        ("record",),
        ("contract",),
        ("adapter",),
        ("source",),
        ("capabilities",),
        ("evidence",),
        ("limitations",),
        ("record", "classification"),
        ("adapter", "implementation_commit"),
        ("source", "artifacts"),
        ("capabilities", "clock"),
        ("capabilities", "semantics"),
    ],
)
def test_missing_required_field_rejects(maniskill_record: dict, path: tuple[str, ...]) -> None:
    _delete(maniskill_record, path)
    with pytest.raises(CapabilityValidationError, match="missing required"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("record", "ros_topic"), "/tf"),
        (("adapter", "plugin_loader"), True),
        (("source", "mcap_channel"), 1),
        (("capabilities", "tf2"), {}),
        (("capabilities", "clock", "bag_time"), 1),
    ],
)
def test_unknown_or_source_specific_sdk_field_rejects(
    maniskill_record: dict, path: tuple[str, ...], value: object
) -> None:
    target = maniskill_record
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(CapabilityValidationError, match="unknown fields"):
        validate_capability(maniskill_record)


def test_unsupported_contract_rejects(maniskill_record: dict) -> None:
    maniskill_record["contract"]["version"] = "metriplane.external_source_contract.v2"
    with pytest.raises(CapabilityValidationError):
        validate_capability(maniskill_record)


def test_malformed_hash_rejects(maniskill_record: dict) -> None:
    maniskill_record["source"]["artifacts"][0]["sha256"] = "0" * 63
    with pytest.raises(CapabilityValidationError, match="does not match"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("adapter", "implementation_commit"), f"x{'0' * 40}x"),
        (("adapter", "implementation_commit"), f"{'0' * 40}\n"),
        (("source", "artifacts", 0, "sha256"), f"x{'0' * 64}x"),
        (("source", "artifacts", 0, "sha256"), f"{'0' * 64}\n"),
        (("source", "artifacts", 0, "artifact_id"), "valid_id/escape"),
        (("evidence", 0, "path"), "../docs/specs/external-source-contract-v1.md"),
        (("evidence", 0, "path"), "docs/specs/external-source-contract-v1.md\n"),
    ],
)
def test_official_json_schema_rejects_padded_or_unsafe_values(
    maniskill_record: dict, path: tuple[object, ...], value: str
) -> None:
    target: object = maniskill_record
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    validator = Draft202012Validator(load_json(schema_path()))
    assert list(validator.iter_errors(maniskill_record))


def test_duplicate_artifact_identity_rejects(maniskill_record: dict) -> None:
    duplicate = copy.deepcopy(maniskill_record["source"]["artifacts"][0])
    maniskill_record["source"]["artifacts"].append(duplicate)
    with pytest.raises(CapabilityValidationError, match="artifact_id values must be unique"):
        validate_capability(maniskill_record)


def test_unhashed_required_artifacts_reject(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["artifact_identity"]["all_required_artifacts_hashed"] = False
    with pytest.raises(CapabilityValidationError, match="must be hashed"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize("field", ["order_only", "authoritative"])
def test_invalid_clock_authority_rejects(maniskill_record: dict, field: str) -> None:
    maniskill_record["capabilities"]["clock"][field] = field == "order_only"
    with pytest.raises(CapabilityValidationError, match="clock"):
        validate_capability(maniskill_record)


def test_nonidentity_projection_without_loss_rejects(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["information_loss"]["declared"] = False
    with pytest.raises(CapabilityValidationError, match=r"information loss|nonidentity projection"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize("field", ["stable", "explicit_mapping"])
def test_unstable_or_implicit_identity_rejects(maniskill_record: dict, field: str) -> None:
    maniskill_record["capabilities"]["entity_identity"][field] = False
    with pytest.raises(CapabilityValidationError, match="stable and explicit"):
        validate_capability(maniskill_record)


def test_required_entities_must_match_process_relevant_ids(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["entity_identity"]["required_entities"] = ["cube_1"]
    with pytest.raises(CapabilityValidationError, match="exactly match"):
        validate_capability(maniskill_record)


def test_duplicate_normalized_entity_rejects(maniskill_record: dict) -> None:
    identity = maniskill_record["capabilities"]["entity_identity"]
    identity["normalized_entities"].append(copy.deepcopy(identity["normalized_entities"][0]))
    with pytest.raises(CapabilityValidationError, match="normalized IDs must be unique"):
        validate_capability(maniskill_record)


def test_artifact_rights_id_must_bind_subject(maniskill_record: dict) -> None:
    maniskill_record["source"]["artifacts"][0]["rights_id"] = "unbound"
    with pytest.raises(CapabilityValidationError, match="does not bind"):
        validate_capability(maniskill_record)


def test_rights_subjects_must_cover_artifacts_exactly_once(maniskill_record: dict) -> None:
    subjects = maniskill_record["source"]["rights"]["source_records"][0]["subject_artifact_ids"]
    subjects.pop()
    with pytest.raises(CapabilityValidationError, match="exactly once"):
        validate_capability(maniskill_record)


def test_verified_rights_reject_unresolved_source_use(maniskill_record: dict) -> None:
    maniskill_record["source"]["rights"]["source_records"][0]["source_use"] = "unresolved"
    with pytest.raises(CapabilityValidationError, match="verified rights"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize("redistribution", ["unresolved", "prohibited", "derived_only"])
def test_included_source_requires_allowed_redistribution(
    maniskill_record: dict, redistribution: str
) -> None:
    artifact = maniskill_record["source"]["artifacts"][0]
    artifact["presence"] = "included"
    maniskill_record["source"]["rights"]["source_bytes_in_fixture"] = True
    rights_id = artifact["rights_id"]
    for rights in maniskill_record["source"]["rights"]["source_records"]:
        if rights["rights_id"] == rights_id:
            rights["source_redistribution"] = redistribution
    with pytest.raises(CapabilityValidationError, match="allowed source redistribution"):
        validate_capability(maniskill_record)


def test_derived_fixture_rights_id_is_separate(maniskill_record: dict) -> None:
    source_rights = maniskill_record["source"]["rights"]["source_records"][0]
    maniskill_record["source"]["rights"]["derived_fixture"]["rights_id"] = source_rights[
        "rights_id"
    ]
    with pytest.raises(CapabilityValidationError, match="separate rights subject"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize("field", ["complete", "trust_layers_separated"])
def test_incomplete_provenance_rejects(maniskill_record: dict, field: str) -> None:
    maniskill_record["capabilities"]["field_provenance"][field] = False
    with pytest.raises(CapabilityValidationError, match="provenance"):
        validate_capability(maniskill_record)


def test_none_carry_forward_with_fields_rejects(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["completeness"]["carry_forward"]["fields"] = [
        "objects[*].pos_world"
    ]
    with pytest.raises(CapabilityValidationError, match="none cannot carry"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("partial_updates_materialized", True),
        ("materialization_method", "exact_snapshot_join"),
        ("synchronization_tolerance_ns", 1),
    ],
)
def test_complete_source_snapshot_has_zero_materialization_policy(
    maniskill_record: dict, field: str, value: object
) -> None:
    maniskill_record["capabilities"]["completeness"][field] = value
    with pytest.raises(CapabilityValidationError, match="complete source snapshots"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize("missing", ["fields", "gap"])
def test_unbounded_carry_forward_rejects(maniskill_record: dict, missing: str) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "bounded_last_observation"
    carry = completeness["carry_forward"]
    carry["method"] = "bounded_last_observation"
    carry["fields"] = [] if missing == "fields" else ["objects[*].pos_world"]
    carry["max_gap_ns"] = None if missing == "gap" else 1
    with pytest.raises(CapabilityValidationError, match="bounded carry-forward"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("fields", "gap"),
    [
        (["objects[*].pos_world", "objects[*].pos_world"], 1),
        (["objects[*].pos_world"], 0),
    ],
)
def test_bounded_carry_forward_requires_unique_fields_and_positive_staleness(
    maniskill_record: dict, fields: list[str], gap: int
) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "bounded_last_observation"
    carry = completeness["carry_forward"]
    carry["method"] = "bounded_last_observation"
    carry["fields"] = fields
    carry["max_gap_ns"] = gap
    with pytest.raises(CapabilityValidationError):
        validate_capability(maniskill_record)


def test_partial_updates_without_materialization_reject(maniskill_record: dict) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    with pytest.raises(CapabilityValidationError, match="explicit materialization"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("synchronization_tolerance_ns", 1),
        ("source_stream_semantics", "complete_snapshot"),
    ],
)
def test_exact_snapshot_join_rejects_nonexact_policy(
    maniskill_record: dict, field: str, value: object
) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "exact_snapshot_join"
    completeness["synchronization"] = "exact_timestamp"
    completeness[field] = value
    with pytest.raises(CapabilityValidationError, match=r"exact snapshot join|complete source"):
        validate_capability(maniskill_record)


def test_exact_snapshot_join_rejects_carry_forward(maniskill_record: dict) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "exact_snapshot_join"
    completeness["synchronization"] = "exact_timestamp"
    carry = completeness["carry_forward"]
    carry["method"] = "bounded_last_observation"
    carry["fields"] = ["objects[*].pos_world"]
    carry["max_gap_ns"] = 1
    with pytest.raises(CapabilityValidationError, match="exact snapshot join"):
        validate_capability(maniskill_record)


def test_bounded_method_requires_matching_carry_policy(maniskill_record: dict) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "bounded_last_observation"
    with pytest.raises(CapabilityValidationError, match="bounded materialization"):
        validate_capability(maniskill_record)


def test_exact_snapshot_join_requires_exact_timestamp(maniskill_record: dict) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "exact_snapshot_join"
    completeness["synchronization"] = "not_applicable"
    with pytest.raises(CapabilityValidationError, match="exact timestamps"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interpolation", "linear"),
        ("interpolation", "nearest"),
        ("resampling", "fixed_rate"),
        ("resampling", "hold"),
        ("synchronization", "latest_available"),
        ("synchronization", "bounded_skew"),
    ],
)
def test_schema_rejects_unsupported_temporal_policy(
    maniskill_record: dict, field: str, value: str
) -> None:
    maniskill_record["capabilities"]["completeness"][field] = value
    validator = Draft202012Validator(load_json(schema_path()))
    assert list(validator.iter_errors(maniskill_record))


def test_complete_snapshot_requires_not_applicable_synchronization(
    maniskill_record: dict,
) -> None:
    maniskill_record["capabilities"]["completeness"]["synchronization"] = "exact_timestamp"
    with pytest.raises(CapabilityValidationError, match="complete source snapshots"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("status", "declared", "items"),
    [
        ("verified", False, []),
        ("verified", True, []),
        ("not_demonstrated", False, ["undeclared item"]),
        ("not_demonstrated", True, []),
    ],
)
def test_information_loss_consistency_rejects(
    maniskill_record: dict, status: str, declared: bool, items: list[str]
) -> None:
    loss = maniskill_record["capabilities"]["information_loss"]
    loss["status"] = status
    loss["declared"] = declared
    loss["items"] = items
    with pytest.raises(CapabilityValidationError, match="information loss"):
        validate_capability(maniskill_record)


def test_not_applicable_information_loss_can_be_undeclared_and_empty(
    maniskill_record: dict,
) -> None:
    loss = maniskill_record["capabilities"]["information_loss"]
    loss["status"] = "not_applicable"
    loss["declared"] = False
    loss["items"] = []
    maniskill_record["capabilities"]["coordinates"]["projection_method"] = "identity"
    assert validate_capability(maniskill_record) is maniskill_record


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inventory_complete", False),
        ("used_as_incident_truth", True),
        ("used_as_process_events", True),
    ],
)
def test_anti_taint_violation_rejects(maniskill_record: dict, field: str, value: bool) -> None:
    maniskill_record["capabilities"]["anti_taint"][field] = value
    with pytest.raises(CapabilityValidationError, match=r"anti_taint|annotation|outcomes"):
        validate_capability(maniskill_record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("clean_run_count", 2),
        ("compared_output_count", 0),
        ("comparison_policy", "not_demonstrated"),
        ("equivalent", False),
    ],
)
def test_false_determinism_claim_rejects(maniskill_record: dict, field: str, value: object) -> None:
    maniskill_record["capabilities"]["deterministic_conversion"][field] = value
    with pytest.raises(CapabilityValidationError, match="three equivalent clean runs"):
        validate_capability(maniskill_record)


def test_source_dependency_in_portable_evaluation_rejects(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["portable_evaluation"]["source_dependencies_required"] = True
    with pytest.raises(CapabilityValidationError, match="exclude source dependencies"):
        validate_capability(maniskill_record)


def test_post_hoc_portable_row_cannot_be_pending(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["portable_evaluation"]["environments"][0]["status"] = "pending"
    with pytest.raises(CapabilityValidationError, match="four passing"):
        validate_capability(maniskill_record)


def test_portable_matrix_must_be_exact_four_rows(maniskill_record: dict) -> None:
    environments = maniskill_record["capabilities"]["portable_evaluation"]["environments"]
    environments[-1]["operating_system"] = "Windows"
    with pytest.raises(CapabilityValidationError, match="exactly Ubuntu and macOS"):
        validate_capability(maniskill_record)


def test_native_synthetic_record_cannot_predeclare_pass(maniskill_record: dict) -> None:
    maniskill_record["record"]["classification"] = "native"
    maniskill_record["record"]["evidence_classification"] = "synthetic_format_engineering"
    maniskill_record["record"]["subject"] = "candidate_adapter"
    with pytest.raises(CapabilityValidationError, match="cannot predeclare"):
        validate_capability(maniskill_record)


def test_native_synthetic_required_rows_must_not_claim_verified_portability(
    maniskill_record: dict,
) -> None:
    maniskill_record["record"]["classification"] = "native"
    maniskill_record["record"]["evidence_classification"] = "synthetic_format_engineering"
    maniskill_record["record"]["subject"] = "candidate_adapter"
    for row in maniskill_record["capabilities"]["portable_evaluation"]["environments"]:
        row["status"] = "required"
    with pytest.raises(CapabilityValidationError, match="verified portability"):
        validate_capability(maniskill_record)


def test_duplicate_portable_row_rejects(maniskill_record: dict) -> None:
    environments = maniskill_record["capabilities"]["portable_evaluation"]["environments"]
    environments.append(copy.deepcopy(environments[0]))
    with pytest.raises(CapabilityValidationError, match="duplicate"):
        validate_capability(maniskill_record)


def test_supported_and_prohibited_overlap_rejects(maniskill_record: dict) -> None:
    semantics = maniskill_record["capabilities"]["semantics"]
    semantics["prohibited"].append(semantics["supported"][0].upper())
    with pytest.raises(CapabilityValidationError, match="overlap"):
        validate_capability(maniskill_record)


def test_unknown_evidence_reference_rejects(maniskill_record: dict) -> None:
    maniskill_record["capabilities"]["rights"]["evidence_ids"] = ["not_present"]
    with pytest.raises(CapabilityValidationError, match="unknown evidence"):
        validate_capability(maniskill_record)


def test_duplicate_evidence_id_rejects(maniskill_record: dict) -> None:
    duplicate = copy.deepcopy(maniskill_record["evidence"][0])
    duplicate["kind"] = "git_commit"
    duplicate.pop("path")
    duplicate.pop("sha256")
    duplicate["identity"] = "0" * 40
    duplicate["uri"] = "https://example.com/commit/0"
    maniskill_record["evidence"].append(duplicate)
    with pytest.raises(CapabilityValidationError, match="evidence_id values must be unique"):
        validate_capability(maniskill_record)


def test_repository_evidence_hash_mismatch_rejects(maniskill_record: dict, tmp_path: Path) -> None:
    source = tmp_path / "evidence.txt"
    source.write_text("actual", encoding="utf-8")
    evidence = maniskill_record["evidence"][0]
    evidence["path"] = "evidence.txt"
    evidence["sha256"] = hashlib.sha256(b"different").hexdigest()
    with pytest.raises(CapabilityValidationError, match="hash mismatch"):
        verify_repository_evidence(maniskill_record, tmp_path)


@pytest.mark.parametrize("unsafe", ["../outside", "/absolute", "dir\\file"])
def test_repository_evidence_unsafe_path_rejects(
    maniskill_record: dict, tmp_path: Path, unsafe: str
) -> None:
    maniskill_record["evidence"][0]["path"] = unsafe
    with pytest.raises(CapabilityValidationError):
        verify_repository_evidence(maniskill_record, tmp_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_repository_evidence_symlink_rejects(maniskill_record: dict, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"evidence")
    link = tmp_path / "evidence"
    link.symlink_to(target)
    evidence = maniskill_record["evidence"][0]
    evidence["path"] = "evidence"
    evidence["sha256"] = hashlib.sha256(b"evidence").hexdigest()
    with pytest.raises(ValueError, match="nonsymlink"):
        verify_repository_evidence(maniskill_record, tmp_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_repository_evidence_nested_symlink_rejects(maniskill_record: dict, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = outside / "evidence"
    payload.write_bytes(b"evidence")
    (tmp_path / "nested").symlink_to(outside, target_is_directory=True)
    evidence = maniskill_record["evidence"][0]
    evidence["path"] = "nested/evidence"
    evidence["sha256"] = hashlib.sha256(b"evidence").hexdigest()
    with pytest.raises(CapabilityValidationError, match="not a real directory"):
        verify_repository_evidence(maniskill_record, tmp_path)
