# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Strict MCAP inventory, CDR decoding, clock, and transform validation."""

from __future__ import annotations

import io
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcap.exceptions import McapError
from mcap.reader import make_reader

from .canonical import sha256_bytes
from .cdr import (
    CdrError,
    PoseStamped,
    SourceOutcome,
    TransformStamped,
    decode_pose_stamped,
    decode_source_outcome,
    decode_tf_message,
)
from .constants import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    EXPECTED_SCHEMA_SHA256,
    FIRST_TIMESTAMP_NS,
    FRAME_COUNT,
    FROZEN_CONFIG_SHA256,
    LOG_TIME_OFFSET_NS,
    MATERIAL_TOPIC,
    MESSAGE_ENCODING,
    OUTCOME_SCHEMA_NAME,
    OUTCOME_TOPIC,
    PERIOD_NS,
    POSE_SCHEMA_NAME,
    PROFILE_ID,
    PUBLISH_TIME_OFFSET_NS,
    SCHEMA_ENCODING,
    SOURCE_SHA256,
    SOURCE_SIZE,
    TF_SCHEMA_NAME,
    TF_TOPIC,
    TOOL_TOPIC,
)
from .path_safety import PathSafetyError, read_file_snapshot, verify_file_snapshot_current


class DecodeError(ValueError):
    """Raised when a source violates the exact recorded-state profile."""


_CONFIG_SNAPSHOT_TEST_HOOK: Callable[[Path], None] | None = None
_SOURCE_SNAPSHOT_TEST_HOOK: Callable[[Path], None] | None = None


@dataclass(frozen=True)
class DecodedFrame:
    timestamp_ns: int
    material_source: tuple[float, float, float]
    tool_source: tuple[float, float, float]
    material_world: tuple[float, float, float]
    tool_world: tuple[float, float, float]
    log_time_ns: int
    publish_time_ns: int


@dataclass(frozen=True)
class DecodedSource:
    frames: tuple[DecodedFrame, ...]
    transforms: tuple[TransformStamped, ...]
    schema_inventory: tuple[dict[str, object], ...]
    channel_inventory: tuple[dict[str, object], ...]
    source_sha256: str
    source_size: int
    outcome_stream_present: bool
    outcome_message_count: int


def load_config_bytes(data: bytes) -> dict[str, Any]:
    """Validate and parse exactly the authenticated frozen config bytes."""

    actual = sha256_bytes(data)
    if actual != FROZEN_CONFIG_SHA256:
        raise DecodeError(
            f"frozen config: SHA-256 mismatch; expected {FROZEN_CONFIG_SHA256}, got {actual}"
        )
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DecodeError(f"frozen config: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise DecodeError("frozen config: root must be an object")
    if value.get("profile") != PROFILE_ID:
        raise DecodeError("frozen config: unsupported profile")
    if value.get("adapter") != {"adapter_id": ADAPTER_ID, "version": ADAPTER_VERSION}:
        raise DecodeError("frozen config: adapter declaration differs")
    clock = value.get("clock")
    expected_clock = {
        "authority": "message_header",
        "domain": "ROS_TIME",
        "epoch": "synthetic_declared_source_domain",
        "evaluation_field": "header.stamp",
        "first_timestamp_ns": FIRST_TIMESTAMP_NS,
        "frame_count": FRAME_COUNT,
        "log_time_offset_ns": LOG_TIME_OFFSET_NS,
        "monotonic": True,
        "period_ns": PERIOD_NS,
        "publish_time_offset_ns": PUBLISH_TIME_OFFSET_NS,
        "unit": "ns",
    }
    if clock != expected_clock:
        raise DecodeError("frozen config: clock differs from exact profile")
    materialization = value.get("materialization")
    if materialization != {
        "allow_duplicate_trigger": False,
        "carry_forward": "none",
        "dynamic_state": "exact_timestamp",
        "missing_state": "reject_recording",
        "required_topics": [MATERIAL_TOPIC, TOOL_TOPIC],
        "sampling_trigger": MATERIAL_TOPIC,
        "synchronization_tolerance_ns": 0,
    }:
        raise DecodeError("frozen config: materialization differs from exact profile")
    entities = value.get("entities")
    if not isinstance(entities, list) or len(entities) != 2:
        raise DecodeError("frozen config: exactly two entity mappings are required")
    if len({item.get("topic") for item in entities if isinstance(item, dict)}) != 2:
        raise DecodeError("frozen config: duplicate entity topic mapping")
    if len({item.get("normalized_id") for item in entities if isinstance(item, dict)}) != 2:
        raise DecodeError("frozen config: duplicate normalized entity ID")
    tf = value.get("tf")
    if tf != {
        "allow_dynamic": False,
        "allow_extrapolation": False,
        "allow_interpolation": False,
        "allow_latest": False,
        "source_frame": "sensor_frame",
        "static_zero_stamp_meaning": "timeless_static_transform",
        "target_frame": "world",
        "topic": TF_TOPIC,
        "transform_path": ["world->cell_frame", "cell_frame->sensor_frame"],
    }:
        raise DecodeError("frozen config: TF policy differs from exact profile")
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    try:
        snapshot = read_file_snapshot(path, label="frozen config")
        if _CONFIG_SNAPSHOT_TEST_HOOK is not None:
            _CONFIG_SNAPSHOT_TEST_HOOK(snapshot.path)
        value = load_config_bytes(snapshot.data)
        verify_file_snapshot_current(snapshot, label="frozen config")
        return value
    except PathSafetyError as exc:
        raise DecodeError(str(exc)) from exc


def _require_unit_quaternion(values: tuple[float, float, float, float], *, label: str) -> None:
    if any(not math.isfinite(value) for value in values):
        raise DecodeError(f"{label}: nonfinite quaternion")
    norm_squared = sum(value * value for value in values)
    if abs(norm_squared - 1.0) > 1e-12:
        raise DecodeError(f"{label}: invalid quaternion norm")


def _rotate(
    quaternion: tuple[float, float, float, float], vector: tuple[float, float, float]
) -> tuple[float, float, float]:
    x, y, z, w = quaternion
    vx, vy, vz = vector
    # q * [v,0] * conjugate(q), expanded to avoid external numeric dependencies.
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _transform(
    position: tuple[float, float, float], transforms: tuple[TransformStamped, ...]
) -> tuple[float, float, float]:
    current = position
    # Stored path is parent -> child; converting child coordinates to parent
    # applies the chain in reverse order.
    for item in reversed(transforms):
        rotated = _rotate(item.rotation, current)
        current = tuple(rotated[index] + item.translation[index] for index in range(3))
    if any(not math.isfinite(value) for value in current):
        raise DecodeError("transform: nonfinite composed position")
    return current


def _validate_transforms(messages: tuple[TransformStamped, ...]) -> None:
    if len(messages) != 2:
        raise DecodeError("TF: exactly two static transforms are required")
    expected_edges = (("world", "cell_frame"), ("cell_frame", "sensor_frame"))
    actual_edges = tuple((item.header.frame_id, item.child_frame_id) for item in messages)
    if actual_edges != expected_edges:
        raise DecodeError("TF: transform path is missing, reordered, cyclic, or ambiguous")
    if len({child for _, child in actual_edges}) != len(actual_edges):
        raise DecodeError("TF: duplicate or conflicting child frame")
    if any(item.header.stamp_ns != 0 for item in messages):
        raise DecodeError("TF: /tf_static transforms must use the declared zero timestamp")
    for index, item in enumerate(messages):
        if any(not math.isfinite(value) for value in item.translation):
            raise DecodeError(f"TF[{index}]: nonfinite translation")
        _require_unit_quaternion(item.rotation, label=f"TF[{index}]")


def _validate_pose(
    pose: PoseStamped, *, timestamp_ns: int, topic: str
) -> tuple[float, float, float]:
    if pose.header.stamp_ns != timestamp_ns:
        raise DecodeError(f"{topic}: header stamp differs from exact evaluation timestamp")
    if pose.header.frame_id != "sensor_frame":
        raise DecodeError(f"{topic}: unexpected or missing source frame")
    if any(not math.isfinite(value) for value in pose.position):
        raise DecodeError(f"{topic}: nonfinite position")
    _require_unit_quaternion(pose.orientation, label=f"{topic} orientation")
    return pose.position


def decode_source_bytes(
    data: bytes,
    *,
    allow_outcome_test_mutation: bool = False,
) -> DecodedSource:
    size = len(data)
    digest = sha256_bytes(data)
    if not allow_outcome_test_mutation and (digest != SOURCE_SHA256 or size != SOURCE_SIZE):
        raise DecodeError("source: SHA-256 or byte count differs from frozen source")
    if size < 16 or data[:8] != b"\x89MCAP0\r\n" or data[-8:] != b"\x89MCAP0\r\n":
        raise DecodeError("source: truncated or invalid MCAP magic")
    # Test-only excluded-stream deletion and value mutations are authenticated
    # structurally below. Every normal decode still requires the exact frozen
    # SHA-256 and byte count before it can return successfully.
    try:
        reader = make_reader(io.BytesIO(data), validate_crcs=True)
        header = reader.get_header()
        summary = reader.get_summary()
        if summary is None or summary.statistics is None:
            raise DecodeError("source: MCAP summary and statistics are required")
        if header.profile != "ros2" or header.library != "metriplane-ros2-mcap-adapter 1.0.0":
            raise DecodeError("source: unexpected MCAP profile or writer identity")
        schemas = summary.schemas
        channels = summary.channels
        topics = {channel.topic for channel in channels.values()}
        required_topics = {TF_TOPIC, MATERIAL_TOPIC, TOOL_TOPIC}
        allowed_topics = required_topics | {OUTCOME_TOPIC}
        if not required_topics <= topics or not topics <= allowed_topics:
            raise DecodeError("source: missing required topic or unexpected topic")
        if len(topics) != len(channels):
            raise DecodeError("source: duplicate channel semantic mapping")
        outcome_present = OUTCOME_TOPIC in topics
        expected_schema_names = {POSE_SCHEMA_NAME, TF_SCHEMA_NAME}
        if outcome_present:
            expected_schema_names.add(OUTCOME_SCHEMA_NAME)
        if {schema.name for schema in schemas.values()} != expected_schema_names:
            raise DecodeError("source: missing, duplicate, or unexpected message schema")
        if len(schemas) != len(expected_schema_names):
            raise DecodeError("source: duplicate schema identity")
        schemas_by_name = {schema.name: schema for schema in schemas.values()}
        for name, schema in schemas_by_name.items():
            if schema.encoding != SCHEMA_ENCODING:
                raise DecodeError(f"schema {name}: unsupported encoding")
            if sha256_bytes(schema.data) != EXPECTED_SCHEMA_SHA256[name]:
                raise DecodeError(f"schema {name}: hash mismatch")
        expected_channels = {
            TF_TOPIC: (
                TF_SCHEMA_NAME,
                {"durability": "transient_local", "source": "metriplane_synthetic"},
            ),
            MATERIAL_TOPIC: (POSE_SCHEMA_NAME, {"entity_id": "synthetic_material_1", "unit": "m"}),
            TOOL_TOPIC: (POSE_SCHEMA_NAME, {"entity_id": "synthetic_tool_1", "unit": "m"}),
        }
        if outcome_present:
            expected_channels[OUTCOME_TOPIC] = (OUTCOME_SCHEMA_NAME, {"evaluation_use": "excluded"})
        for channel in channels.values():
            if channel.message_encoding != MESSAGE_ENCODING:
                raise DecodeError(f"channel {channel.topic}: unsupported message encoding")
            expected_schema, expected_metadata = expected_channels[channel.topic]
            schema = schemas.get(channel.schema_id)
            if (
                schema is None
                or schema.name != expected_schema
                or channel.metadata != expected_metadata
            ):
                raise DecodeError(f"channel {channel.topic}: schema or metadata mismatch")

        by_topic: dict[str, list[tuple[object, object]]] = {topic: [] for topic in topics}
        for schema, channel, message in reader.iter_messages(log_time_order=True):
            if schema is None or schema.id != channel.schema_id:
                raise DecodeError("source: message channel/schema mismatch")
            by_topic[channel.topic].append((schema, message))
    except DecodeError:
        raise
    except (McapError, CdrError, ValueError, OSError) as exc:
        raise DecodeError(f"source: malformed or corrupt MCAP: {exc}") from exc

    if len(by_topic[TF_TOPIC]) != 1:
        raise DecodeError("TF: exactly one /tf_static message is required")
    _, tf_record = by_topic[TF_TOPIC][0]
    if tf_record.sequence != 0:
        raise DecodeError("TF: unexpected sequence")
    if (
        tf_record.publish_time != FIRST_TIMESTAMP_NS - 101_000_000
        or tf_record.log_time != FIRST_TIMESTAMP_NS - 100_000_000
    ):
        raise DecodeError("TF: unexpected MCAP publish/log time")
    try:
        transforms = decode_tf_message(tf_record.data)
    except CdrError as exc:
        raise DecodeError(f"TF: malformed CDR: {exc}") from exc
    _validate_transforms(transforms)

    for topic in (MATERIAL_TOPIC, TOOL_TOPIC):
        if len(by_topic[topic]) != FRAME_COUNT:
            raise DecodeError(f"{topic}: expected {FRAME_COUNT} complete observations")
    outcome_count = len(by_topic.get(OUTCOME_TOPIC, []))
    if outcome_present and outcome_count != FRAME_COUNT:
        raise DecodeError("excluded outcome stream: partial stream is prohibited")

    frames: list[DecodedFrame] = []
    for index in range(FRAME_COUNT):
        stamp_ns = FIRST_TIMESTAMP_NS + index * PERIOD_NS
        decoded_positions: dict[str, tuple[float, float, float]] = {}
        reference_times: tuple[int, int] | None = None
        for topic in (MATERIAL_TOPIC, TOOL_TOPIC):
            _, record = by_topic[topic][index]
            if record.sequence != index:
                raise DecodeError(f"{topic}: sequence is missing, duplicated, or reordered")
            expected_publish = stamp_ns + PUBLISH_TIME_OFFSET_NS
            expected_log = stamp_ns + LOG_TIME_OFFSET_NS
            if record.publish_time != expected_publish or record.log_time != expected_log:
                raise DecodeError(f"{topic}: publish/header/log clock relationship differs")
            try:
                pose = decode_pose_stamped(record.data)
            except CdrError as exc:
                raise DecodeError(f"{topic}: malformed CDR: {exc}") from exc
            decoded_positions[topic] = _validate_pose(pose, timestamp_ns=stamp_ns, topic=topic)
            times = (record.publish_time, record.log_time)
            if reference_times is not None and reference_times != times:
                raise DecodeError(
                    "materialization: required messages are not exactly co-timestamped"
                )
            reference_times = times
        if outcome_present:
            _, record = by_topic[OUTCOME_TOPIC][index]
            if record.sequence != index:
                raise DecodeError(
                    "excluded outcome stream: missing, duplicated, or reordered sequence"
                )
            if (
                record.publish_time != stamp_ns + PUBLISH_TIME_OFFSET_NS
                or record.log_time != stamp_ns + LOG_TIME_OFFSET_NS
            ):
                raise DecodeError("excluded outcome stream: clock relationship differs")
            try:
                outcome: SourceOutcome = decode_source_outcome(record.data)
            except CdrError as exc:
                raise DecodeError(f"excluded outcome stream: malformed CDR: {exc}") from exc
            if (
                outcome.header.stamp_ns != stamp_ns
                or outcome.header.frame_id != "operator_annotations"
            ):
                raise DecodeError("excluded outcome stream: header identity differs")
        frames.append(
            DecodedFrame(
                timestamp_ns=stamp_ns,
                material_source=decoded_positions[MATERIAL_TOPIC],
                tool_source=decoded_positions[TOOL_TOPIC],
                material_world=_transform(decoded_positions[MATERIAL_TOPIC], transforms),
                tool_world=_transform(decoded_positions[TOOL_TOPIC], transforms),
                publish_time_ns=stamp_ns + PUBLISH_TIME_OFFSET_NS,
                log_time_ns=stamp_ns + LOG_TIME_OFFSET_NS,
            )
        )

    if digest != SOURCE_SHA256 or size != SOURCE_SIZE:
        from .generator import build_source_bytes

        if not outcome_present:
            expected = build_source_bytes(include_outcome_stream=False)
            if data != expected:
                raise DecodeError("source: non-outcome bytes differ from exact deletion variant")
        else:
            # Reconstruct the decoded outcomes. If replacing only those values in
            # the canonical generator yields these exact bytes, every structural
            # and non-outcome byte is proven unchanged.
            outcomes = [decode_source_outcome(record.data) for _, record in by_topic[OUTCOME_TOPIC]]
            expected = build_source_bytes(outcome_transform=lambda index, _: outcomes[index])
            if data != expected:
                raise DecodeError("source: test mutation changes non-outcome bytes or structure")
    return DecodedSource(
        frames=tuple(frames),
        transforms=transforms,
        schema_inventory=tuple(
            {
                "encoding": schema.encoding,
                "name": schema.name,
                "schema_id": schema.id,
                "sha256": sha256_bytes(schema.data),
            }
            for schema in sorted(schemas.values(), key=lambda item: item.id)
        ),
        channel_inventory=tuple(
            {
                "channel_id": channel.id,
                "message_encoding": channel.message_encoding,
                "schema_id": channel.schema_id,
                "topic": channel.topic,
            }
            for channel in sorted(channels.values(), key=lambda item: item.id)
        ),
        source_sha256=digest,
        source_size=size,
        outcome_stream_present=outcome_present,
        outcome_message_count=outcome_count,
    )


def decode_source_file(
    path: str | Path,
    *,
    allow_outcome_test_mutation: bool = False,
) -> DecodedSource:
    try:
        snapshot = read_file_snapshot(path, label="MCAP source")
        if _SOURCE_SNAPSHOT_TEST_HOOK is not None:
            _SOURCE_SNAPSHOT_TEST_HOOK(snapshot.path)
        decoded = decode_source_bytes(
            snapshot.data,
            allow_outcome_test_mutation=allow_outcome_test_mutation,
        )
        verify_file_snapshot_current(snapshot, label="MCAP source")
        return decoded
    except PathSafetyError as exc:
        raise DecodeError(str(exc)) from exc


__all__ = [
    "DecodeError",
    "DecodedFrame",
    "DecodedSource",
    "decode_source_bytes",
    "decode_source_file",
    "load_config",
    "load_config_bytes",
]
