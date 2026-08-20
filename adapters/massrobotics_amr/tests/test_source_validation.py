# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import JsonObject, read_jsonl, write_jsonl

from massrobotics_amr_adapter.clock import ClockError, parse_timestamp_ns
from massrobotics_amr_adapter.constants import (
    AMR_1_UUID,
    AMR_2_UUID,
    DEFAULT_CONFIG,
    DEFAULT_SOURCE_ROOT,
    PLANAR_DATUM_UUID,
)
from massrobotics_amr_adapter.parser import SourceValidationError, load_source
from massrobotics_amr_adapter.validation import ConfigValidationError, load_config


def _load(root: Path, config_path: Path = DEFAULT_CONFIG):
    config = load_config(config_path)
    return load_source(
        root,
        expected_datum=config.expected_planar_datum_uuid,
        frame_interval_ns=config.frame_interval_ns,
        entity_order=config.entity_order,
    )


def test_frozen_synthetic_source_byte_identities() -> None:
    expected = {
        "incident/identity.jsonl": (
            498,
            "e721cc90fe6c7641d6ae1dfae37c2697ca60b1a633904cace1ec0dcc08e5cf2c",
        ),
        "incident/status.jsonl": (
            5_015,
            "c3edfb18ffed5821b65d3c4954c5ffb987fb5de2569e1dc2731f07a82effaea5",
        ),
        "control/identity.jsonl": (
            498,
            "e721cc90fe6c7641d6ae1dfae37c2697ca60b1a633904cace1ec0dcc08e5cf2c",
        ),
        "control/status.jsonl": (
            5_013,
            "2988e1555e55f19196433d0aef0913e272881f65d52fc049adf3c826edf87ed2",
        ),
    }
    for relative, (size, digest) in expected.items():
        data = (DEFAULT_SOURCE_ROOT / relative).read_bytes()
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == digest


@pytest.mark.parametrize(
    ("value", "fraction_ns"),
    [
        ("2026-08-20T10:00:00Z", 0),
        ("2026-08-20T10:00:00.1Z", 100_000_000),
        ("2026-08-20T10:00:00.12Z", 120_000_000),
        ("2026-08-20T10:00:00.123Z", 123_000_000),
        ("2026-08-20T10:00:00.1234Z", 123_400_000),
        ("2026-08-20T10:00:00.12345Z", 123_450_000),
        ("2026-08-20T10:00:00.123456Z", 123_456_000),
        ("2026-08-20T10:00:00.1234567Z", 123_456_700),
        ("2026-08-20T10:00:00.12345678Z", 123_456_780),
        ("2026-08-20T10:00:00.123456789Z", 123_456_789),
    ],
)
def test_clock_accepts_zero_to_nine_fractional_digits_and_preserves_ns(
    value: str, fraction_ns: int
) -> None:
    whole = parse_timestamp_ns("2026-08-20T10:00:00Z", field="status.timestamp")
    assert parse_timestamp_ns(value, field="status.timestamp") - whole == fraction_ns


def test_clock_requires_an_explicit_zone_and_normalizes_offsets_to_utc() -> None:
    expected = parse_timestamp_ns("2026-08-20T08:00:00.123456789Z", field="timestamp")
    assert parse_timestamp_ns("2026-08-20T10:00:00.123456789+02:00", field="timestamp") == expected
    assert parse_timestamp_ns("2026-08-20T03:00:00.123456789-05:00", field="timestamp") == expected
    with pytest.raises(ClockError, match="explicit Z or UTC offset"):
        parse_timestamp_ns("2026-08-20T10:00:00", field="timestamp")


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-20T10:00:00.1234567890Z",
        "2026-08-20T10:00:00.Z",
        "2026-08-20T10:00:00+24:00",
        "2026-08-20T10:00:00+00:60",
    ],
)
def test_clock_rejects_excess_precision_empty_fraction_and_bad_offsets(value: str) -> None:
    with pytest.raises(ClockError):
        parse_timestamp_ns(value, field="timestamp")


def test_valid_identity_and_status_sequence_parses(source_root: Path) -> None:
    trace = _load(source_root)
    assert len(trace.identities) == 2
    assert len(trace.status_records) == 18
    assert len(trace.frames) == 9
    assert [record.uuid for record in trace.identities] == [AMR_1_UUID, AMR_2_UUID]


def test_identity_uuid_is_stable_across_all_statuses(source_root: Path) -> None:
    trace = _load(source_root)
    known = {record.uuid for record in trace.identities}
    assert known == {AMR_1_UUID, AMR_2_UUID}
    assert {record.uuid for record in trace.status_records} == known
    for frame in trace.frames:
        assert [record.uuid for record in frame.statuses] == [AMR_1_UUID, AMR_2_UUID]


def test_status_timestamps_are_monotonic(source_root: Path) -> None:
    trace = _load(source_root)
    values = [record.timestamp_ns for record in trace.status_records]
    assert values == sorted(values)
    assert [frame.timestamp_ns - trace.frames[0].timestamp_ns for frame in trace.frames] == [
        index * 1_000_000_000 for index in range(9)
    ]


def test_complete_snapshot_contains_two_amrs_per_frame(source_root: Path) -> None:
    trace = _load(source_root)
    assert all(len(frame.statuses) == 2 for frame in trace.frames)
    assert all(
        tuple(record.uuid for record in frame.statuses) == (AMR_1_UUID, AMR_2_UUID)
        for frame in trace.frames
    )


def test_location_planar_datum_is_authoritative(source_root: Path) -> None:
    trace = _load(source_root)
    assert {record.location.planar_datum for record in trace.status_records} == {PLANAR_DATUM_UUID}


def test_path_point_without_datum_inherits_current_for_validation(source_root: Path) -> None:
    trace = _load(source_root)
    first = trace.frames[0].statuses[0]
    assert first.path[0].declared_planar_datum is None
    assert first.path[0].effective_planar_datum == PLANAR_DATUM_UUID


def test_path_point_with_matching_explicit_datum_is_accepted(source_root: Path) -> None:
    trace = _load(source_root)
    first = trace.frames[0].statuses[0]
    assert first.path[1].declared_planar_datum == PLANAR_DATUM_UUID
    assert first.path[1].effective_planar_datum == PLANAR_DATUM_UUID


def test_path_predictions_do_not_create_source_frames(source_root: Path) -> None:
    trace = _load(source_root)
    assert sum(len(record.path) for record in trace.status_records) == 2
    assert len(trace.frames) == 9
    assert [frame.timestamp_ns for frame in trace.frames] == sorted(
        {record.timestamp_ns for record in trace.status_records}
    )


def test_missing_location_planar_datum_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident", "status.jsonl", lambda rows: rows[0]["location"].pop("planarDatum")
    )
    with pytest.raises(ValueError, match="planarDatum"):
        _load(root)


def test_malformed_datum_uuid_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[0]["location"].__setitem__("planarDatum", "not-a-uuid"),
    )
    with pytest.raises(ValueError, match="UUID"):
        _load(root)


def test_invalid_amr_uuid_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident", "identity.jsonl", lambda rows: rows[0].__setitem__("uuid", "not-a-uuid")
    )
    with pytest.raises(ValueError, match="UUID"):
        _load(root)


def test_status_uuid_without_matching_identity_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[0].__setitem__("uuid", "33333333-3333-4333-8333-333333333333"),
    )
    with pytest.raises(ValueError, match="without matching identity"):
        _load(root)


def test_missing_identity_report_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    (root / "identity.jsonl").unlink()
    with pytest.raises(SourceValidationError, match="identity report"):
        _load(root)


def test_nonmonotonic_status_timestamps_are_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    rows = read_jsonl(path)
    rows[:] = rows[2:4] + rows[0:2] + rows[4:]
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError, match="nonmonotonic"):
        _load(root)


def test_duplicate_robot_timestamp_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    rows = read_jsonl(path)
    rows.insert(1, copy.deepcopy(rows[0]))
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError, match="duplicate"):
        _load(root)


def test_conflicting_duplicate_state_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    rows = read_jsonl(path)
    conflicting = copy.deepcopy(rows[0])
    conflicting["location"]["x"] = 123.0
    rows.insert(1, conflicting)
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError, match="conflicting duplicate"):
        _load(root)


def test_missing_amr_2_status_at_one_frame_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    rows = read_jsonl(path)
    del rows[7]
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError):
        _load(root)


def test_nonexact_frame_gap_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    rows = read_jsonl(path)
    for row in rows[4:6]:
        row["timestamp"] = "2026-08-20T10:00:02.000000001Z"
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError, match="exactly 1,000,000,000 ns"):
        _load(root)


def test_path_point_with_conflicting_datum_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[0]["path"][0].__setitem__("planarDatumUUID", other),
    )
    with pytest.raises(ValueError, match="path datum differs"):
        _load(root)


def test_current_location_datum_change_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[6]["location"].__setitem__("planarDatum", other),
    )
    with pytest.raises(SourceValidationError, match="datum"):
        _load(root)


def test_two_amrs_with_different_datums_are_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[1]["location"].__setitem__("planarDatum", other),
    )
    with pytest.raises(SourceValidationError, match="different datums"):
        _load(root)


def test_nonfinite_coordinate_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "status.jsonl"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"x":2.0', '"x":NaN', 1), encoding="utf-8")
    with pytest.raises(SourceValidationError, match="nonfinite"):
        _load(root)


def test_incomplete_current_location_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source("incident", "status.jsonl", lambda rows: rows[0]["location"].pop("z"))
    with pytest.raises(SourceValidationError, match=r"missing=.*z"):
        _load(root)


@pytest.mark.parametrize(
    ("quaternion", "message"),
    [
        ({"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}, "zero-norm"),
        ({"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.001}, "outside tolerance"),
    ],
)
def test_invalid_quaternion_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
    quaternion: dict[str, float],
    message: str,
) -> None:
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[0]["location"].__setitem__("angle", quaternion),
    )
    with pytest.raises(ValueError, match=message):
        _load(root)


def test_unknown_process_relevant_entity_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "identity.jsonl"
    rows = read_jsonl(path)
    extra = copy.deepcopy(rows[0])
    extra["uuid"] = "33333333-3333-4333-8333-333333333333"
    extra["robotSerialNumber"] = "MP-SYN-AMR-003"
    rows.append(extra)
    write_jsonl(path, rows)
    with pytest.raises(SourceValidationError, match="exactly two"):
        _load(root)


def test_malformed_source_json_is_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    (root / "status.jsonl").write_text("{\n", encoding="utf-8")
    with pytest.raises(SourceValidationError, match="malformed source JSON"):
        _load(root)


def test_unexpected_source_fields_are_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident", "status.jsonl", lambda rows: rows[0].__setitem__("sourceIncident", True)
    )
    with pytest.raises(SourceValidationError, match="unexpected source fields"):
        _load(root)


def test_optional_identity_fields_outside_bounded_profile_are_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident", "identity.jsonl", lambda rows: rows[0].__setitem__("maxSpeed", "fast")
    )
    with pytest.raises(SourceValidationError, match="unexpected source fields"):
        _load(root)


def test_angular_velocity_outside_bounded_profile_is_rejected(
    mutate_source: Callable[[str, str, Callable[[list[JsonObject]], None]], Path],
) -> None:
    root = mutate_source(
        "incident",
        "status.jsonl",
        lambda rows: rows[0].__setitem__(
            "velocity",
            {"linear": 0.0, "angular": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 0.0}},
        ),
    )
    with pytest.raises(SourceValidationError, match="unexpected source fields"):
        _load(root)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.__setitem__("carry_forward", "latest"), "carry-forward"),
        (lambda value: value.__setitem__("interpolation", "linear"), "interpolation"),
        (lambda value: value.__setitem__("resampling", "1_hz"), "resampling"),
        (
            lambda value: value.__setitem__("promote_predictions_to_observations", True),
            "prediction promoted",
        ),
        (
            lambda value: value.__setitem__("expected_outcome_is_input", True),
            "expected outcome",
        ),
        (
            lambda value: value.__setitem__("upstream_artifacts_included", True),
            "upstream official artifact",
        ),
        (
            lambda value: value["operator_coordinate_binding"].pop("unit_authority"),
            "missing=.*unit_authority",
        ),
        (
            lambda value: value["operator_coordinate_binding"].__setitem__(
                "source_linear_unit", "unknown"
            ),
            "coordinate-unit binding",
        ),
        (
            lambda value: value["operator_coordinate_binding"].__setitem__(
                "transform", "translate"
            ),
            "non-identity transform",
        ),
        (
            lambda value: value.__setitem__("coordinate_transforms", []),
            "unknown=.*coordinate_transforms",
        ),
    ],
    ids=[
        "requested-carry-forward",
        "requested-interpolation",
        "requested-resampling",
        "prediction-promoted",
        "expected-outcome-input",
        "upstream-artifact-included",
        "missing-coordinate-binding-authority",
        "unknown-unit-binding",
        "nonidentity-transform",
        "explicit-transform-registry",
    ],
)
def test_unsupported_profile_configurations_are_rejected(
    copy_config: Callable[[Callable[[JsonObject], None]], Path],
    mutation: Callable[[JsonObject], None],
    message: str,
) -> None:
    path = copy_config(mutation)
    with pytest.raises(ConfigValidationError, match=message):
        load_config(path)


def test_missing_operator_coordinate_binding_is_rejected(
    copy_config: Callable[[Callable[[JsonObject], None]], Path],
) -> None:
    path = copy_config(lambda value: value.pop("operator_coordinate_binding"))
    with pytest.raises(ConfigValidationError, match="operator_coordinate_binding"):
        load_config(path)


def test_expected_outcome_declaration_is_rejected_even_under_an_alias(
    copy_config: Callable[[Callable[[JsonObject], None]], Path],
) -> None:
    path = copy_config(
        lambda value: value.__setitem__("expected_outcome_path", "expected-outcome.json")
    )
    with pytest.raises(ConfigValidationError, match="expected outcome declared"):
        load_config(path)


def test_duplicate_json_keys_are_rejected(copy_source: Callable[[str], Path]) -> None:
    root = copy_source("incident")
    path = root / "identity.jsonl"
    first, second = path.read_text(encoding="utf-8").splitlines()
    first = first[:-1] + ',"uuid":"11111111-1111-4111-8111-111111111111"}'
    path.write_text(first + "\n" + second + "\n", encoding="utf-8")
    with pytest.raises(SourceValidationError, match="duplicate JSON key"):
        _load(root)
