# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import pytest

from ros2_mcap_adapter.cdr import (
    CdrError,
    Header,
    PoseStamped,
    SourceOutcome,
    decode_pose_stamped,
    decode_source_outcome,
    decode_tf_message,
    encode_pose_stamped,
    encode_source_outcome,
    encode_tf_message,
)
from ros2_mcap_adapter.generator import _static_transforms

# Independently serialized with rosbags 0.11.0 Jazzy typestore. These fixed
# vectors test ROS 2 XCDR1 payload-origin alignment, not a self-roundtrip.
POSE_REFERENCE = bytes.fromhex(
    "0001000001000000000000000d00000073656e736f725f6672616d650000000000000000333333333333c3bf9a9999999999b93f7b14ae47e17a943f000000000000000000000000000000000000000000000000000000000000f03f"
)
TF_REFERENCE = bytes.fromhex(
    "0001000002000000000000000000000006000000776f726c640000000b00000063656c6c"
    "5f6672616d6500009a9999999999d93f9a9999999999c9bf9a9999999999b93f00000000"
    "000000000000000000000000cc3b7f669ea0e63fcd3b7f669ea0e63f0000000000000000"
    "0b00000063656c6c5f6672616d6500000d00000073656e736f725f6672616d6500000000"
    "000000009a9999999999b93f9a9999999999a93f9a9999999999b9bf0000000000000000"
    "0000000000000000cc3b7f669ea0e6bfcd3b7f669ea0e63f"
)


def test_pose_bytes_match_independent_rosbags_vector() -> None:
    message = PoseStamped(
        Header(1_000_000_000, "sensor_frame"),
        (-0.15, 0.1, 0.02),
        (0.0, 0.0, 0.0, 1.0),
    )
    assert encode_pose_stamped(message) == POSE_REFERENCE
    assert decode_pose_stamped(POSE_REFERENCE) == message


def test_tf_bytes_match_independent_rosbags_vector() -> None:
    assert encode_tf_message(_static_transforms()) == TF_REFERENCE
    assert decode_tf_message(TF_REFERENCE) == _static_transforms()


def test_outcome_roundtrip() -> None:
    message = SourceOutcome(Header(123, "annotations"), True, "ok", "none", "place", "x")
    assert decode_source_outcome(encode_source_outcome(message)) == message


@pytest.mark.parametrize(
    "mutation",
    [
        b"",
        b"\x00\x01\x00",
        b"\x00\x00\x00\x00" + POSE_REFERENCE[4:],
        POSE_REFERENCE + b"x",
        POSE_REFERENCE[:16],
    ],
)
def test_pose_rejects_malformed_cdr(mutation: bytes) -> None:
    with pytest.raises(CdrError):
        decode_pose_stamped(mutation)


def test_invalid_bool_rejected() -> None:
    encoded = bytearray(
        encode_source_outcome(SourceOutcome(Header(1, "a"), False, "r", "a", "x", "n"))
    )
    # Header is 4+8+4+2 bytes then padding to next bool position is unnecessary.
    encoded[18] = 2
    with pytest.raises(CdrError):
        decode_source_outcome(bytes(encoded))
