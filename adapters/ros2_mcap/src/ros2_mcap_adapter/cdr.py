# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Small strict CDR codec for the three frozen ROS 2 schemas.

This is intentionally not a generic ROS deserializer. It supports only the
exact fields needed by ``metriplane.ros2_mcap_recorded_state.v1``.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass


class CdrError(ValueError):
    """Raised when bytes do not exactly match the frozen CDR profile."""


@dataclass(frozen=True)
class Header:
    stamp_ns: int
    frame_id: str


@dataclass(frozen=True)
class PoseStamped:
    header: Header
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]


@dataclass(frozen=True)
class TransformStamped:
    header: Header
    child_frame_id: str
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]


@dataclass(frozen=True)
class SourceOutcome:
    header: Header
    success: bool
    result: str
    alarm: str
    action: str
    annotation: str


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray(b"\x00\x01\x00\x00")

    def align(self, boundary: int) -> None:
        # DDS-XTypes CDR alignment begins at the serialized payload, after the
        # four-byte encapsulation header.
        padding = (-(len(self.data) - 4)) % boundary
        self.data.extend(b"\x00" * padding)

    def int32(self, value: int) -> None:
        if not -(2**31) <= value < 2**31:
            raise CdrError("int32 out of range")
        self.align(4)
        self.data.extend(struct.pack("<i", value))

    def uint32(self, value: int) -> None:
        if not 0 <= value < 2**32:
            raise CdrError("uint32 out of range")
        self.align(4)
        self.data.extend(struct.pack("<I", value))

    def float64(self, value: float) -> None:
        if not math.isfinite(value):
            raise CdrError("float64 must be finite")
        self.align(8)
        self.data.extend(struct.pack("<d", value))

    def boolean(self, value: bool) -> None:
        if type(value) is not bool:
            raise CdrError("bool field must be bool")
        self.data.append(int(value))

    def string(self, value: str) -> None:
        if not isinstance(value, str) or "\x00" in value:
            raise CdrError("string must be NUL-free text")
        encoded = value.encode("utf-8")
        self.uint32(len(encoded) + 1)
        self.data.extend(encoded)
        self.data.append(0)


class _Reader:
    def __init__(self, data: bytes) -> None:
        if not isinstance(data, bytes) or len(data) < 4:
            raise CdrError("truncated CDR encapsulation")
        if data[:4] != b"\x00\x01\x00\x00":
            raise CdrError("only little-endian CDR with zero options is supported")
        self.data = data
        self.offset = 4

    def align(self, boundary: int) -> None:
        aligned = self.offset + (-(self.offset - 4) % boundary)
        if aligned > len(self.data):
            raise CdrError("truncated CDR alignment")
        if any(self.data[self.offset : aligned]):
            raise CdrError("nonzero CDR padding")
        self.offset = aligned

    def take(self, count: int) -> bytes:
        end = self.offset + count
        if count < 0 or end > len(self.data):
            raise CdrError("truncated CDR field")
        value = self.data[self.offset : end]
        self.offset = end
        return value

    def int32(self) -> int:
        self.align(4)
        return struct.unpack("<i", self.take(4))[0]

    def uint32(self) -> int:
        self.align(4)
        return struct.unpack("<I", self.take(4))[0]

    def float64(self) -> float:
        self.align(8)
        value = struct.unpack("<d", self.take(8))[0]
        if not math.isfinite(value):
            raise CdrError("nonfinite CDR float64")
        return value

    def boolean(self) -> bool:
        value = self.take(1)[0]
        if value not in (0, 1):
            raise CdrError("noncanonical CDR bool")
        return bool(value)

    def string(self) -> str:
        count = self.uint32()
        if count == 0:
            raise CdrError("CDR string length must include a terminator")
        raw = self.take(count)
        if raw[-1:] != b"\x00" or b"\x00" in raw[:-1]:
            raise CdrError("malformed CDR string terminator")
        try:
            return raw[:-1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CdrError("CDR string is not UTF-8") from exc

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise CdrError("trailing bytes after supported CDR message")


def _write_header(writer: _Writer, header: Header) -> None:
    if not 0 <= header.stamp_ns < (2**31) * 1_000_000_000:
        raise CdrError("ROS timestamp outside supported nonnegative range")
    seconds, nanoseconds = divmod(header.stamp_ns, 1_000_000_000)
    writer.int32(seconds)
    writer.uint32(nanoseconds)
    writer.string(header.frame_id)


def _read_header(reader: _Reader) -> Header:
    seconds = reader.int32()
    nanoseconds = reader.uint32()
    if seconds < 0 or nanoseconds >= 1_000_000_000:
        raise CdrError("invalid ROS timestamp")
    return Header(seconds * 1_000_000_000 + nanoseconds, reader.string())


def _write_vector(writer: _Writer, values: tuple[float, float, float]) -> None:
    if len(values) != 3:
        raise CdrError("vector must have three components")
    for value in values:
        writer.float64(value)


def _read_vector(reader: _Reader) -> tuple[float, float, float]:
    return (reader.float64(), reader.float64(), reader.float64())


def _write_quaternion(writer: _Writer, values: tuple[float, float, float, float]) -> None:
    if len(values) != 4:
        raise CdrError("quaternion must have four components")
    for value in values:
        writer.float64(value)


def _read_quaternion(reader: _Reader) -> tuple[float, float, float, float]:
    return (reader.float64(), reader.float64(), reader.float64(), reader.float64())


def encode_pose_stamped(message: PoseStamped) -> bytes:
    writer = _Writer()
    _write_header(writer, message.header)
    _write_vector(writer, message.position)
    _write_quaternion(writer, message.orientation)
    return bytes(writer.data)


def decode_pose_stamped(data: bytes) -> PoseStamped:
    reader = _Reader(data)
    result = PoseStamped(_read_header(reader), _read_vector(reader), _read_quaternion(reader))
    reader.finish()
    return result


def encode_tf_message(messages: tuple[TransformStamped, ...]) -> bytes:
    writer = _Writer()
    writer.uint32(len(messages))
    for message in messages:
        _write_header(writer, message.header)
        writer.string(message.child_frame_id)
        _write_vector(writer, message.translation)
        _write_quaternion(writer, message.rotation)
    return bytes(writer.data)


def decode_tf_message(data: bytes) -> tuple[TransformStamped, ...]:
    reader = _Reader(data)
    count = reader.uint32()
    if count > 32:
        raise CdrError("TF message exceeds bounded transform count")
    messages = tuple(
        TransformStamped(
            _read_header(reader),
            reader.string(),
            _read_vector(reader),
            _read_quaternion(reader),
        )
        for _ in range(count)
    )
    reader.finish()
    return messages


def encode_source_outcome(message: SourceOutcome) -> bytes:
    writer = _Writer()
    _write_header(writer, message.header)
    writer.boolean(message.success)
    writer.string(message.result)
    writer.string(message.alarm)
    writer.string(message.action)
    writer.string(message.annotation)
    return bytes(writer.data)


def decode_source_outcome(data: bytes) -> SourceOutcome:
    reader = _Reader(data)
    result = SourceOutcome(
        _read_header(reader),
        reader.boolean(),
        reader.string(),
        reader.string(),
        reader.string(),
        reader.string(),
    )
    reader.finish()
    return result


__all__ = [
    "CdrError",
    "Header",
    "PoseStamped",
    "SourceOutcome",
    "TransformStamped",
    "decode_pose_stamped",
    "decode_source_outcome",
    "decode_tf_message",
    "encode_pose_stamped",
    "encode_source_outcome",
    "encode_tf_message",
]
