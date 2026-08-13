# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from mcap.reader import make_reader
from mcap.writer import CompressionType, IndexType, Writer

from ros2_mcap_adapter.constants import DEFAULT_CONFIG, PACKAGE_ROOT, SOURCE_FILENAME


@pytest.fixture
def source_path() -> Path:
    return PACKAGE_ROOT / "source" / SOURCE_FILENAME


@pytest.fixture
def config_path() -> Path:
    return DEFAULT_CONFIG


def rewrite_mcap(
    data: bytes,
    *,
    schema_transform: Callable[[int, str, str, bytes], tuple[str, str, bytes]] | None = None,
    channel_transform: Callable[
        [int, str, str, int, dict[str, str]], tuple[str, str, int, dict[str, str]]
    ]
    | None = None,
    message_transform: Callable[
        [str, int, int, int, int, bytes], tuple[int, int, int, bytes] | None
    ]
    | None = None,
    duplicate_topic: str | None = None,
) -> bytes:
    reader = make_reader(io.BytesIO(data), validate_crcs=True)
    summary = reader.get_summary()
    assert summary is not None
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
    header = reader.get_header()
    writer.start(profile=header.profile, library=header.library)
    schema_ids: dict[int, int] = {}
    for old_id, schema in sorted(summary.schemas.items()):
        name, encoding, schema_data = schema.name, schema.encoding, schema.data
        if schema_transform is not None:
            name, encoding, schema_data = schema_transform(old_id, name, encoding, schema_data)
        schema_ids[old_id] = writer.register_schema(name=name, encoding=encoding, data=schema_data)
    channel_ids: dict[int, int] = {}
    topics: dict[int, str] = {}
    for old_id, channel in sorted(summary.channels.items()):
        topic, encoding, schema_id, metadata = (
            channel.topic,
            channel.message_encoding,
            schema_ids[channel.schema_id],
            dict(channel.metadata),
        )
        if channel_transform is not None:
            topic, encoding, schema_id, metadata = channel_transform(
                old_id, topic, encoding, schema_id, metadata
            )
        channel_ids[old_id] = writer.register_channel(
            topic=topic, message_encoding=encoding, schema_id=schema_id, metadata=metadata
        )
        topics[old_id] = topic
    for _schema, channel, message in reader.iter_messages(log_time_order=True):
        transformed = (message.log_time, message.publish_time, message.sequence, message.data)
        if message_transform is not None:
            transformed = message_transform(
                channel.topic,
                message.log_time,
                message.publish_time,
                message.sequence,
                message.data,
            )
        if transformed is None:
            continue
        log_time, publish_time, sequence, message_data = transformed
        writer.add_message(
            channel_id=channel_ids[channel.id],
            log_time=log_time,
            publish_time=publish_time,
            sequence=sequence,
            data=message_data,
        )
        if duplicate_topic == channel.topic:
            writer.add_message(
                channel_id=channel_ids[channel.id],
                log_time=log_time,
                publish_time=publish_time,
                sequence=sequence,
                data=message_data,
            )
    writer.finish()
    return output.getvalue()
