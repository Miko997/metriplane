# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import io
import math
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import rewrite_mcap
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory

import ros2_mcap_adapter.decoder as decoder
from ros2_mcap_adapter.canonical import sha256_bytes
from ros2_mcap_adapter.cdr import (
    Header,
    decode_pose_stamped,
    decode_tf_message,
    encode_pose_stamped,
    encode_tf_message,
)
from ros2_mcap_adapter.constants import (
    MATERIAL_TOPIC,
    OUTCOME_TOPIC,
    SOURCE_SHA256,
    SOURCE_SIZE,
    TF_TOPIC,
    TOOL_TOPIC,
)
from ros2_mcap_adapter.decoder import DecodeError, decode_source_bytes, decode_source_file
from ros2_mcap_adapter.generator import build_source_bytes


def _decode_structural_mutation(data: bytes):
    return decode_source_bytes(data, allow_outcome_test_mutation=True)


def test_frozen_source_identity_and_inventory(source_path: Path) -> None:
    data = source_path.read_bytes()
    assert len(data) == SOURCE_SIZE == 28_735
    assert sha256_bytes(data) == SOURCE_SHA256
    assert build_source_bytes() == data
    source = decode_source_file(source_path)
    assert len(source.frames) == 60
    assert [item["topic"] for item in source.channel_inventory] == [
        TF_TOPIC,
        MATERIAL_TOPIC,
        TOOL_TOPIC,
        OUTCOME_TOPIC,
    ]
    assert source.outcome_message_count == 60


def test_normal_wrong_identity_rejects_before_mcap_reader(monkeypatch) -> None:
    called = False

    def forbidden_reader(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("MCAP reader must not inspect unauthenticated bytes")

    monkeypatch.setattr(decoder, "make_reader", forbidden_reader)
    with pytest.raises(DecodeError, match="SHA-256 or byte count"):
        decode_source_bytes(b"not-the-frozen-source")
    assert called is False


def test_source_snapshot_rejects_same_byte_path_replacement(
    tmp_path: Path, source_path: Path, monkeypatch
) -> None:
    source_copy = tmp_path / "source.mcap"
    source_copy.write_bytes(source_path.read_bytes())

    def replace_after_snapshot(path: Path) -> None:
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(source_path.read_bytes())
        replacement.replace(path)

    monkeypatch.setattr(decoder, "_SOURCE_SNAPSHOT_TEST_HOOK", replace_after_snapshot)
    with pytest.raises(DecodeError, match="changed after its authenticated snapshot"):
        decode_source_file(source_copy)


def test_independent_mcap_ros2_decoder_reads_exact_values(source_path: Path) -> None:
    reader = make_reader(io.BytesIO(source_path.read_bytes()), decoder_factories=[DecoderFactory()])
    decoded = list(reader.iter_decoded_messages())
    assert len(decoded) == 181
    tf = decoded[0][3]
    pose = decoded[1][3]
    assert tf.transforms[0].header.frame_id == "world"
    assert tf.transforms[1].child_frame_id == "sensor_frame"
    assert pose.header.stamp.sec == 1
    assert pose.header.stamp.nanosec == 0
    assert pose.header.frame_id == "sensor_frame"
    assert pose.pose.position.x == -0.15


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data[:-1],
        lambda data: data[:100],
        lambda data: b"BADMAGIC" + data[8:],
        lambda data: data[:100] + bytes([data[100] ^ 0xFF]) + data[101:],
    ],
)
def test_container_corruption_rejected(source_path: Path, mutation) -> None:
    with pytest.raises(DecodeError):
        decode_source_bytes(mutation(source_path.read_bytes()))


def test_schema_hash_mismatch_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        schema_transform=lambda _id, name, encoding, data: (
            name,
            encoding,
            data + b"\n" if name == "geometry_msgs/msg/PoseStamped" else data,
        ),
    )
    with pytest.raises(DecodeError, match=r"schema .* hash mismatch"):
        _decode_structural_mutation(altered)


def test_schema_encoding_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        schema_transform=lambda _id, name, encoding, data: (
            name,
            "ros2idl" if name == "geometry_msgs/msg/PoseStamped" else encoding,
            data,
        ),
    )
    with pytest.raises(DecodeError, match="unsupported encoding"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize("replacement", ["/unexpected", "/tf", "/TF_STATIC"])
def test_unexpected_topic_rejected(source_path: Path, replacement: str) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        channel_transform=lambda _id, topic, encoding, schema, metadata: (
            replacement if topic == MATERIAL_TOPIC else topic,
            encoding,
            schema,
            metadata,
        ),
    )
    with pytest.raises(DecodeError, match="topic"):
        _decode_structural_mutation(altered)


def test_channel_encoding_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        channel_transform=lambda _id, topic, encoding, schema, metadata: (
            topic,
            "json" if topic == MATERIAL_TOPIC else encoding,
            schema,
            metadata,
        ),
    )
    with pytest.raises(DecodeError, match="message encoding"):
        _decode_structural_mutation(altered)


def test_channel_metadata_identity_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        channel_transform=lambda _id, topic, encoding, schema, metadata: (
            topic,
            encoding,
            schema,
            {**metadata, "entity_id": "alias"} if topic == MATERIAL_TOPIC else metadata,
        ),
    )
    with pytest.raises(DecodeError, match="metadata mismatch"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize("topic", [MATERIAL_TOPIC, TOOL_TOPIC])
def test_missing_required_state_rejected(source_path: Path, topic: str) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        message_transform=lambda current, log, publish, sequence, data: (
            None if current == topic and sequence == 10 else (log, publish, sequence, data)
        ),
    )
    with pytest.raises(DecodeError, match="complete observations"):
        _decode_structural_mutation(altered)


def test_duplicate_trigger_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(source_path.read_bytes(), duplicate_topic=MATERIAL_TOPIC)
    with pytest.raises(DecodeError, match="complete observations"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize("topic", [MATERIAL_TOPIC, TOOL_TOPIC, OUTCOME_TOPIC])
def test_sequence_drift_rejected(source_path: Path, topic: str) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        message_transform=lambda current, log, publish, sequence, data: (
            (log, publish, sequence + 1, data)
            if current == topic and sequence == 10
            else (log, publish, sequence, data)
        ),
    )
    with pytest.raises(DecodeError, match="sequence"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize("which", ["log", "publish"])
def test_mcap_transport_time_cannot_replace_header_clock(source_path: Path, which: str) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        message_transform=lambda topic, log, publish, sequence, data: (
            (
                log + (1 if which == "log" else 0),
                publish + (1 if which == "publish" else 0),
                sequence,
                data,
            )
            if topic == MATERIAL_TOPIC and sequence == 8
            else (log, publish, sequence, data)
        ),
    )
    with pytest.raises(DecodeError, match="clock relationship"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize(
    ("stamp", "frame"),
    [(0, "sensor_frame"), (1_800_000_001, "sensor_frame"), (1_800_000_000, "unknown")],
)
def test_authoritative_header_clock_and_frame_rejected_on_drift(
    source_path: Path, stamp: int, frame: str
) -> None:
    def mutate(topic, log, publish, sequence, data):
        if topic == MATERIAL_TOPIC and sequence == 8:
            pose = decode_pose_stamped(data)
            data = encode_pose_stamped(replace(pose, header=Header(stamp, frame)))
        return log, publish, sequence, data

    altered = rewrite_mcap(source_path.read_bytes(), message_transform=mutate)
    with pytest.raises(DecodeError, match=r"header stamp|source frame"):
        _decode_structural_mutation(altered)


@pytest.mark.parametrize(
    "pose_mutator",
    [
        lambda pose: replace(pose, position=(math.nan, 0.0, 0.0)),
        lambda pose: replace(pose, orientation=(0.0, 0.0, 0.0, 0.0)),
        lambda pose: replace(pose, orientation=(0.0, 0.0, 0.0, 2.0)),
    ],
)
def test_invalid_pose_rejected(source_path: Path, pose_mutator) -> None:
    def mutate(topic, log, publish, sequence, data):
        if topic == MATERIAL_TOPIC and sequence == 8:
            data = encode_pose_stamped(pose_mutator(decode_pose_stamped(data)))
        return log, publish, sequence, data

    with pytest.raises((DecodeError, ValueError)):
        _decode_structural_mutation(
            rewrite_mcap(source_path.read_bytes(), message_transform=mutate)
        )


@pytest.mark.parametrize(
    "tf_mutator",
    [
        lambda values: (replace(values[0], child_frame_id="sensor_frame"), values[1]),
        lambda values: (replace(values[0], header=Header(0, "cell_frame")), values[1]),
        lambda values: (replace(values[0], rotation=(0.0, 0.0, 0.0, 0.0)), values[1]),
        lambda values: (replace(values[0], header=Header(1, "world")), values[1]),
        lambda values: values[:1],
    ],
)
def test_tf_path_conflicts_cycles_and_invalid_values_rejected(
    source_path: Path, tf_mutator
) -> None:
    def mutate(topic, log, publish, sequence, data):
        if topic == TF_TOPIC:
            data = encode_tf_message(tuple(tf_mutator(decode_tf_message(data))))
        return log, publish, sequence, data

    with pytest.raises((DecodeError, ValueError), match=r"TF|quaternion"):
        _decode_structural_mutation(
            rewrite_mcap(source_path.read_bytes(), message_transform=mutate)
        )


def test_partial_outcome_stream_rejected(source_path: Path) -> None:
    altered = rewrite_mcap(
        source_path.read_bytes(),
        message_transform=lambda topic, log, publish, sequence, data: (
            None if topic == OUTCOME_TOPIC and sequence == 4 else (log, publish, sequence, data)
        ),
    )
    with pytest.raises(DecodeError, match="partial stream"):
        _decode_structural_mutation(altered)
