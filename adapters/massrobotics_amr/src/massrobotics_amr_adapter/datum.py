# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping

from .models import Quaternion


class DatumError(ValueError):
    """Raised when datum or coordinate validation fails closed."""


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
QUATERNION_NORM_TOLERANCE = 1e-6


def require_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        raise DatumError(f"{field}: canonical lowercase UUID is required")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise DatumError(f"{field}: malformed UUID") from exc
    if str(parsed) != value:
        raise DatumError(f"{field}: canonical lowercase UUID is required")
    return value


def finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatumError(f"{field}: finite number is required")
    result = float(value)
    if not math.isfinite(result):
        raise DatumError(f"{field}: nonfinite coordinate is prohibited")
    return result


def parse_quaternion(value: object, *, field: str) -> Quaternion:
    if not isinstance(value, Mapping):
        raise DatumError(f"{field}: quaternion object is required")
    required = {"x", "y", "z", "w"}
    if set(value) != required:
        missing = sorted(required - set(value))
        unknown = sorted(set(value) - required)
        raise DatumError(
            f"{field}: incomplete or unknown quaternion fields; missing={missing}; unknown={unknown}"
        )
    quaternion = Quaternion(
        x=finite_number(value["x"], field=f"{field}.x"),
        y=finite_number(value["y"], field=f"{field}.y"),
        z=finite_number(value["z"], field=f"{field}.z"),
        w=finite_number(value["w"], field=f"{field}.w"),
    )
    norm = math.sqrt(quaternion.x**2 + quaternion.y**2 + quaternion.z**2 + quaternion.w**2)
    if norm == 0:
        raise DatumError(f"{field}: zero-norm quaternion is prohibited")
    if abs(norm - 1.0) > QUATERNION_NORM_TOLERANCE:
        raise DatumError(f"{field}: quaternion norm outside tolerance {QUATERNION_NORM_TOLERANCE}")
    return quaternion


def effective_path_datum(
    declared: object | None,
    *,
    current: str,
    field: str,
) -> tuple[str | None, str]:
    if declared is None:
        return None, current
    parsed = require_uuid(declared, field=field)
    if parsed != current:
        raise DatumError(f"{field}: path datum differs from authoritative current datum")
    return parsed, parsed
