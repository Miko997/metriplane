# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from datetime import UTC, datetime


class ClockError(ValueError):
    """Raised when a source timestamp is outside the strict profile."""


_RFC3339 = re.compile(
    r"(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?P<fraction>\.[0-9]{0,10})?(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


def parse_timestamp_ns(value: object, *, field: str) -> int:
    """Parse strict RFC 3339 time while preserving up to nanoseconds."""

    if not isinstance(value, str):
        raise ClockError(f"{field}: timestamp must be a string")
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ClockError(f"{field}: explicit Z or UTC offset is required")
    fraction = match.group("fraction")
    digits = "" if fraction is None else fraction[1:]
    if not digits and fraction is not None:
        raise ClockError(f"{field}: fractional seconds cannot be empty")
    if len(digits) > 9:
        raise ClockError(f"{field}: more than 9 fractional-second digits are prohibited")
    try:
        base = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
            tzinfo=UTC,
        )
    except ValueError as exc:
        raise ClockError(f"{field}: invalid calendar timestamp") from exc
    offset = match.group("offset")
    offset_seconds = 0
    if offset != "Z":
        hours = int(offset[1:3])
        minutes = int(offset[4:6])
        if hours > 23 or minutes > 59:
            raise ClockError(f"{field}: invalid UTC offset")
        offset_seconds = (hours * 60 + minutes) * 60
        if offset[0] == "+":
            offset_seconds = -offset_seconds
    epoch_seconds = int(base.timestamp()) + offset_seconds
    nanoseconds = int(digits.ljust(9, "0")) if digits else 0
    return epoch_seconds * 1_000_000_000 + nanoseconds
