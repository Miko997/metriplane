# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Generate the exact deterministic synthetic MCAP source."""

from __future__ import annotations

import io
import math
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from mcap.writer import CompressionType, IndexType, Writer

from .canonical import sha256_bytes
from .cdr import (
    Header,
    PoseStamped,
    SourceOutcome,
    TransformStamped,
    encode_pose_stamped,
    encode_source_outcome,
    encode_tf_message,
)
from .constants import (
    FIRST_TIMESTAMP_NS,
    FRAME_COUNT,
    LOG_TIME_OFFSET_NS,
    MATERIAL_TOPIC,
    MESSAGE_ENCODING,
    OUTCOME_SCHEMA_NAME,
    OUTCOME_TOPIC,
    PERIOD_NS,
    POSE_SCHEMA_NAME,
    PUBLISH_TIME_OFFSET_NS,
    SCHEMA_ENCODING,
    SOURCE_SHA256,
    SOURCE_SIZE,
    TF_SCHEMA_NAME,
    TF_TOPIC,
    TOOL_TOPIC,
)
from .path_safety import PathSafetyError, publish_file, reject_symlink_components
from .schemas import OUTCOME_SCHEMA, POSE_STAMPED_SCHEMA, TF_MESSAGE_SCHEMA


class SourceGenerationError(RuntimeError):
    """Raised when the frozen synthetic source cannot be published safely."""


OutcomeTransform = Callable[[int, SourceOutcome], SourceOutcome]


def _yaw_quaternion(radians: float) -> tuple[float, float, float, float]:
    return (0.0, 0.0, math.sin(radians / 2.0), math.cos(radians / 2.0))


def _static_transforms() -> tuple[TransformStamped, ...]:
    timeless = Header(0, "world")
    return (
        TransformStamped(
            timeless,
            "cell_frame",
            (0.4, -0.2, 0.1),
            _yaw_quaternion(math.pi / 2.0),
        ),
        TransformStamped(
            Header(0, "cell_frame"),
            "sensor_frame",
            (0.1, 0.05, -0.1),
            _yaw_quaternion(-math.pi / 2.0),
        ),
    )


def _material_position(index: int) -> tuple[float, float, float]:
    # The composed static transform maps p_sensor to p_world + (0.35, -0.10, 0).
    if index < 5:
        return (-0.15, 0.1, 0.02)
    if index <= 39:
        return (0.15, 0.1, 0.02)
    return (0.45, 0.1, 0.02)


def _tool_position(index: int) -> tuple[float, float, float]:
    if index < 15:
        return (-0.25, -0.2, 0.12)
    if index <= 40:
        return (0.15, 0.1, 0.12)
    return (-0.25, -0.2, 0.12)


def _outcome(index: int, stamp_ns: int) -> SourceOutcome:
    return SourceOutcome(
        Header(stamp_ns, "operator_annotations"),
        index >= 15,
        "complete" if index >= 15 else "running",
        "none" if index >= 15 else "waiting",
        "place" if index >= 10 else "approach",
        f"synthetic-label-{index:02d}",
    )


def build_source_bytes(
    *,
    include_outcome_stream: bool = True,
    outcome_transform: OutcomeTransform | None = None,
) -> bytes:
    """Build the exact source or an anti-taint outcome-only mutation.

    The mutation and deletion options exist only for internal anti-taint tests.
    Normal conversion accepts only the exact frozen complete stream.
    """
    output = io.BytesIO()
    writer = Writer(
        output,
        compression=CompressionType.NONE,
        index_types=IndexType.NONE,
        repeat_channels=True,
        repeat_schemas=True,
        use_chunking=False,
        use_statistics=True,
        use_summary_offsets=True,
        enable_crcs=True,
        enable_data_crcs=True,
    )
    writer.start(
        profile="ros2",
        library="metriplane-ros2-mcap-adapter 1.0.0",
    )
    pose_schema = writer.register_schema(
        name=POSE_SCHEMA_NAME,
        encoding=SCHEMA_ENCODING,
        data=POSE_STAMPED_SCHEMA,
    )
    tf_schema = writer.register_schema(
        name=TF_SCHEMA_NAME,
        encoding=SCHEMA_ENCODING,
        data=TF_MESSAGE_SCHEMA,
    )
    outcome_schema = None
    if include_outcome_stream:
        outcome_schema = writer.register_schema(
            name=OUTCOME_SCHEMA_NAME,
            encoding=SCHEMA_ENCODING,
            data=OUTCOME_SCHEMA,
        )
    tf_channel = writer.register_channel(
        topic=TF_TOPIC,
        message_encoding=MESSAGE_ENCODING,
        schema_id=tf_schema,
        metadata={"durability": "transient_local", "source": "metriplane_synthetic"},
    )
    material_channel = writer.register_channel(
        topic=MATERIAL_TOPIC,
        message_encoding=MESSAGE_ENCODING,
        schema_id=pose_schema,
        metadata={"entity_id": "synthetic_material_1", "unit": "m"},
    )
    tool_channel = writer.register_channel(
        topic=TOOL_TOPIC,
        message_encoding=MESSAGE_ENCODING,
        schema_id=pose_schema,
        metadata={"entity_id": "synthetic_tool_1", "unit": "m"},
    )
    outcome_channel = None
    if include_outcome_stream:
        assert outcome_schema is not None
        outcome_channel = writer.register_channel(
            topic=OUTCOME_TOPIC,
            message_encoding=MESSAGE_ENCODING,
            schema_id=outcome_schema,
            metadata={"evaluation_use": "excluded"},
        )

    writer.add_message(
        channel_id=tf_channel,
        log_time=FIRST_TIMESTAMP_NS - 100_000_000,
        publish_time=FIRST_TIMESTAMP_NS - 101_000_000,
        sequence=0,
        data=encode_tf_message(_static_transforms()),
    )
    for index in range(FRAME_COUNT):
        stamp_ns = FIRST_TIMESTAMP_NS + index * PERIOD_NS
        publish_time = stamp_ns + PUBLISH_TIME_OFFSET_NS
        log_time = stamp_ns + LOG_TIME_OFFSET_NS
        header = Header(stamp_ns, "sensor_frame")
        orientation = (0.0, 0.0, 0.0, 1.0)
        writer.add_message(
            channel_id=material_channel,
            log_time=log_time,
            publish_time=publish_time,
            sequence=index,
            data=encode_pose_stamped(PoseStamped(header, _material_position(index), orientation)),
        )
        writer.add_message(
            channel_id=tool_channel,
            log_time=log_time,
            publish_time=publish_time,
            sequence=index,
            data=encode_pose_stamped(PoseStamped(header, _tool_position(index), orientation)),
        )
        if include_outcome_stream:
            assert outcome_channel is not None
            message = _outcome(index, stamp_ns)
            if outcome_transform is not None:
                message = outcome_transform(index, message)
            writer.add_message(
                channel_id=outcome_channel,
                log_time=log_time,
                publish_time=publish_time,
                sequence=index,
                data=encode_source_outcome(message),
            )
    writer.finish()
    return output.getvalue()


def generate_source(output_path: str | Path, *, overwrite: bool = False) -> dict[str, object]:
    """Atomically publish and verify the exact frozen synthetic source."""
    try:
        output = reject_symlink_components(output_path, label="source generation output")
    except PathSafetyError as exc:
        raise SourceGenerationError(str(exc)) from exc
    data = build_source_bytes()
    actual_size = len(data)
    actual_sha256 = sha256_bytes(data)
    if actual_size != SOURCE_SIZE or actual_sha256 != SOURCE_SHA256:
        raise SourceGenerationError(
            "source generation: construction differs from frozen identity; "
            f"size={actual_size} sha256={actual_sha256}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
        os.fsync(descriptor)
        identity = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = -1
        publish_file(
            temporary,
            output,
            overwrite=overwrite,
            expected_data=data,
            expected_identity=identity,
        )
    except (OSError, PathSafetyError) as exc:
        raise SourceGenerationError(str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return {
        "classification": "FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE",
        "path": output.name,
        "schema_version": "org.metriplane.ros2_mcap.synthetic_source.v1",
        "sha256": actual_sha256,
        "size": actual_size,
    }


__all__ = ["SourceGenerationError", "build_source_bytes", "generate_source"]
