# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metriplane_source_adapter_sdk import (
    CapabilityValidationError,
    assess_capability,
    capability_fingerprint,
    load_capability,
    record_path,
    schema_path,
    validate_capability,
    verify_repository_evidence,
)


@pytest.mark.parametrize("name", ["maniskill-pickcube", "robomimic-lowdim"])
def test_bundled_records_validate(name: str) -> None:
    assert load_capability(record_path(name))["record"]["classification"] == "post_hoc"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("maniskill-pickcube", "ccc7fc3972b19aa373101ef60bc0598cca83e41d8c1243821003c3a0eaef4487"),
        ("robomimic-lowdim", "053b7994edd1f1043ee1b3423ee7de45e83c111c2dcf921482bce8ffb4afa610"),
    ],
)
def test_bundled_record_fingerprints(name: str, expected: str) -> None:
    assert capability_fingerprint(load_capability(record_path(name))) == expected


@pytest.mark.parametrize("name", ["maniskill-pickcube", "robomimic-lowdim"])
def test_bundled_external_records_are_permitted(name: str) -> None:
    result = assess_capability(load_capability(record_path(name)))
    assert result.technically_permitted
    assert result.external_source_permitted
    assert result.reasons == ()


@pytest.mark.parametrize("name", ["maniskill-pickcube", "robomimic-lowdim"])
def test_repository_evidence_hashes_match(name: str, repository_root: Path) -> None:
    verified = verify_repository_evidence(load_capability(record_path(name)), repository_root)
    assert "external_contract" in verified
    assert len(verified) == 7


def test_schema_is_strict_draft_2020_12_json() -> None:
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"].endswith(".v1")


def test_jsonschema_format_and_meta_schema_validate_all_records() -> None:
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    for name in ("maniskill-pickcube", "robomimic-lowdim"):
        validator.validate(load_capability(record_path(name)))


def test_shared_schema_has_no_source_specific_fields() -> None:
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    forbidden = {
        "ros",
        "ros_topic",
        "topic",
        "mcap",
        "mcap_channel",
        "channel",
        "cdr",
        "tf",
        "tf2",
        "message_schema",
        "hdf5_group",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            result = set(value)
            for child in value.values():
                result.update(keys(child))
            return result
        if isinstance(value, list):
            result: set[str] = set()
            for child in value:
                result.update(keys(child))
            return result
        return set()

    assert forbidden.isdisjoint(keys(schema))


@pytest.mark.parametrize(
    "name",
    ["", "../record", "/record", "Record", "record.json", "ros/topic", "two words"],
)
def test_record_path_rejects_unsafe_name(name: str) -> None:
    with pytest.raises(ValueError, match="record name"):
        record_path(name)


def test_synthetic_record_is_technical_but_not_external(maniskill_record: dict) -> None:
    maniskill_record["record"]["classification"] = "native"
    maniskill_record["record"]["evidence_classification"] = "synthetic_format_engineering"
    maniskill_record["record"]["subject"] = "candidate_adapter"
    maniskill_record["capabilities"]["portable_evaluation"]["status"] = "not_demonstrated"
    for row in maniskill_record["capabilities"]["portable_evaluation"]["environments"]:
        row["status"] = "required"
    result = assess_capability(maniskill_record)
    assert not result.technically_permitted
    assert not result.external_source_permitted
    assert result.reasons == ("portable_evaluation is not verified",)


def test_unverified_gate_blocks_technical_permission(maniskill_record: dict) -> None:
    maniskill_record["record"]["classification"] = "native"
    maniskill_record["record"]["subject"] = "candidate_adapter"
    maniskill_record["capabilities"]["portable_evaluation"]["status"] = "not_demonstrated"
    for row in maniskill_record["capabilities"]["portable_evaluation"]["environments"]:
        row["status"] = "pending"
    result = assess_capability(maniskill_record)
    assert not result.technically_permitted
    assert not result.external_source_permitted
    assert result.reasons == ("portable_evaluation is not verified",)


def test_exact_snapshot_join_is_a_valid_source_neutral_materialization(
    maniskill_record: dict,
) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "exact_snapshot_join"
    completeness["synchronization_tolerance_ns"] = 0
    completeness["synchronization"] = "exact_timestamp"
    completeness["carry_forward"] = {
        "method": "none",
        "fields": [],
        "max_gap_ns": None,
    }
    assert validate_capability(maniskill_record) is maniskill_record


def test_native_synthetic_exact_join_validates_without_external_permission(
    maniskill_record: dict,
) -> None:
    maniskill_record["record"]["classification"] = "native"
    maniskill_record["record"]["evidence_classification"] = "synthetic_format_engineering"
    maniskill_record["record"]["subject"] = "candidate_adapter"
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "exact_snapshot_join"
    completeness["synchronization_tolerance_ns"] = 0
    completeness["synchronization"] = "exact_timestamp"
    completeness["carry_forward"] = {
        "method": "none",
        "fields": [],
        "max_gap_ns": None,
    }
    portable = maniskill_record["capabilities"]["portable_evaluation"]
    portable["status"] = "not_demonstrated"
    for row in portable["environments"]:
        row["status"] = "required"
    validated = validate_capability(maniskill_record)
    result = assess_capability(validated)
    assert not result.technically_permitted
    assert not result.external_source_permitted
    assert result.reasons == ("portable_evaluation is not verified",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interpolation", "linear"),
        ("resampling", "fixed_rate"),
        ("synchronization", "latest_available"),
    ],
)
def test_assessment_rejects_hidden_temporal_policy(
    maniskill_record: dict, field: str, value: str
) -> None:
    maniskill_record["capabilities"]["completeness"][field] = value
    with pytest.raises(CapabilityValidationError):
        assess_capability(maniskill_record)


@pytest.mark.parametrize(
    ("status", "declared", "items"),
    [
        ("verified", False, []),
        ("verified", True, []),
        ("not_demonstrated", False, ["hidden loss"]),
        ("not_demonstrated", True, []),
    ],
)
def test_assessment_rejects_inconsistent_information_loss(
    maniskill_record: dict, status: str, declared: bool, items: list[str]
) -> None:
    loss = maniskill_record["capabilities"]["information_loss"]
    loss["status"] = status
    loss["declared"] = declared
    loss["items"] = items
    with pytest.raises(CapabilityValidationError, match="information loss"):
        assess_capability(maniskill_record)


def test_bounded_last_observation_is_valid_when_explicit_and_bounded(
    maniskill_record: dict,
) -> None:
    completeness = maniskill_record["capabilities"]["completeness"]
    completeness["source_stream_semantics"] = "partial_updates"
    completeness["partial_updates_materialized"] = True
    completeness["materialization_method"] = "bounded_last_observation"
    completeness["carry_forward"] = {
        "method": "bounded_last_observation",
        "fields": ["objects[*].pos_world"],
        "max_gap_ns": 1,
    }
    assert validate_capability(maniskill_record) is maniskill_record
