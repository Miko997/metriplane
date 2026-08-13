# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Dependency-free canonical JSON and regular-file hashing helpers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class CanonicalJsonError(ValueError):
    """Raised when a value cannot enter the SDK's canonical JSON domain."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJsonError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise CanonicalJsonError(f"non-finite JSON number: {value}")


def load_json(path: str | Path) -> Any:
    """Load strict UTF-8 JSON, rejecting duplicate keys and non-finite values."""

    source = Path(path)
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise CanonicalJsonError(f"cannot read JSON file: {source}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalJsonError(f"JSON file is not UTF-8: {source}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except CanonicalJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise CanonicalJsonError(f"invalid JSON at line {exc.lineno}, column {exc.colno}") from exc


def _check_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError(f"non-finite number at {path}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalJsonError(f"non-string object key at {path}")
            _check_json_value(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _check_json_value(child, f"{path}[{index}]")
        return
    raise CanonicalJsonError(f"unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize finite JSON deterministically with sorted keys and one final LF.

    This is the explicitly bounded Metriplane capability-record serialization,
    not a claim of RFC 8785 conformance.
    """

    _check_json_value(value)
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalJsonError("value cannot be serialized as canonical JSON") from exc
    return (rendered + "\n").encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of :func:`canonical_json_bytes`."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return the file identity and mutation-sensitive metadata we authenticate."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def artifact_sha256(path: str | Path) -> str:
    """Hash one stable regular nonsymlink file through one authenticated descriptor."""

    source = Path(path)
    try:
        initial = source.lstat()
    except OSError as exc:
        raise ValueError(f"artifact is unavailable: {source}") from exc
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        raise ValueError(f"artifact is not a regular nonsymlink file: {source}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise ValueError(f"artifact is unavailable: {source}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(initial) != _file_identity(opened):
            raise ValueError(f"artifact path changed before hashing: {source}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        finished = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(finished):
            raise ValueError(f"artifact changed while hashing: {source}")
        try:
            named_after = source.lstat()
        except OSError as exc:
            raise ValueError(f"artifact path changed while hashing: {source}") from exc
        if (
            stat.S_ISLNK(named_after.st_mode)
            or not stat.S_ISREG(named_after.st_mode)
            or _file_identity(finished) != _file_identity(named_after)
        ):
            raise ValueError(f"artifact path changed while hashing: {source}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)
