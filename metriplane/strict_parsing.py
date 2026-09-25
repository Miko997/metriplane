# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Strict, resource-bounded JSON, JSONL, and YAML parsing.

The defaults are calibrated above the largest tracked repository document while
remaining finite. Callers handling a narrower protocol should pass a smaller
``ParseLimits`` instance; tests use that facility for exact N-1/N/N+1 proofs.
"""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol, TextIO

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised in an isolated subprocess
    yaml = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """Finite lexical and constructed-resource limits for one document."""

    max_bytes: int
    max_depth: int
    max_nodes: int
    max_scalar_bytes: int
    max_jsonl_lines: int

    def __post_init__(self) -> None:
        for name in (
            "max_bytes",
            "max_depth",
            "max_nodes",
            "max_scalar_bytes",
            "max_jsonl_lines",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


# requirements.json is currently the largest tracked structured document. The
# 64 MiB ceiling leaves deterministic headroom without allowing unbounded input.
REPOSITORY_DOCUMENT_LIMITS = ParseLimits(
    max_bytes=64 * 1024 * 1024,
    max_depth=128,
    max_nodes=2_000_000,
    max_scalar_bytes=16 * 1024 * 1024,
    max_jsonl_lines=2_000_000,
)
DEFAULT_LIMITS = REPOSITORY_DOCUMENT_LIMITS


class StrictParseError(ValueError):
    """Base class for deterministic lexical or resource-limit rejection."""


class StrictJsonError(StrictParseError, json.JSONDecodeError):
    """JSON rejection compatible with existing JSONDecodeError handlers."""

    def __init__(self, message: str) -> None:
        json.JSONDecodeError.__init__(self, message, "", 0)


class _UnavailableYamlError(Exception):
    """Stand-in exception base used only when PyYAML is absent."""


_YamlErrorBase = _UnavailableYamlError if yaml is None else yaml.YAMLError


class StrictYamlError(StrictParseError, _YamlErrorBase):  # type: ignore[misc, valid-type]
    """YAML rejection compatible with PyYAML when that dependency is present."""


_DEFAULT_YAML_LOADER: Any = yaml.SafeLoader if yaml is not None else None


class PinnedReadable(Protocol):
    """Minimal pinned-file authority required by the strict parser helpers."""

    def duplicate_fd(self) -> int: ...

    def verify(self) -> None: ...

    def __str__(self) -> str: ...


def _bounded_text(
    data: str | bytes | bytearray | memoryview,
    *,
    label: str,
    limits: ParseLimits,
    error: type[StrictParseError],
) -> str:
    if isinstance(data, str):
        try:
            encoded = data.encode("utf-8", "strict")
        except UnicodeError as exc:
            raise error(f"{label} is not valid UTF-8") from exc
        text = data
    elif isinstance(data, (bytes, bytearray, memoryview)):
        encoded = bytes(data)
        try:
            text = encoded.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise error(f"{label} is not valid UTF-8") from exc
    else:
        raise TypeError(f"{label} must be str or bytes-like")
    if len(encoded) > limits.max_bytes:
        raise error(f"{label} exceeds the {limits.max_bytes}-byte limit")
    return text


def _read_bounded_stream(
    stream: BinaryIO | TextIO,
    *,
    label: str,
    limits: ParseLimits,
    error: type[StrictParseError],
) -> str | bytes:
    try:
        value = stream.read(limits.max_bytes + 1)
    except TypeError as exc:
        raise error(f"{label} does not support bounded reads") from exc
    if not isinstance(value, (str, bytes, bytearray, memoryview)):
        raise error(f"{label} stream returned an unsupported value")
    return value


def _read_bounded_path(
    path: str | os.PathLike[str],
    *,
    label: str,
    limits: ParseLimits,
    error: type[StrictParseError],
) -> bytes:
    candidate = Path(path)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise error(f"cannot safely open {label}: required open flags are unavailable")
    try:
        descriptor = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise error(f"cannot open {label}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise error(f"{label} is not a regular file")
        if metadata.st_size > limits.max_bytes:
            raise error(f"{label} exceeds the {limits.max_bytes}-byte limit")
        chunks: list[bytes] = []
        remaining = limits.max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limits.max_bytes:
            raise error(f"{label} exceeds the {limits.max_bytes}-byte limit")
        return data
    finally:
        os.close(descriptor)


def _read_bounded_pinned(
    source: PinnedReadable,
    *,
    label: str,
    limits: ParseLimits,
    error: type[StrictParseError],
) -> bytes:
    """Read a pinned regular file and revalidate its path authority afterwards."""

    descriptor = source.duplicate_fd()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise error(f"{label} is not a regular file")
        if metadata.st_size > limits.max_bytes:
            raise error(f"{label} exceeds the {limits.max_bytes}-byte limit")
        chunks: list[bytes] = []
        remaining = limits.max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limits.max_bytes:
            raise error(f"{label} exceeds the {limits.max_bytes}-byte limit")
        return data
    except OSError as exc:
        raise error(f"cannot read {label}") from exc
    finally:
        os.close(descriptor)
        source.verify()


def _scan_json_depth(text: str, *, label: str, limits: ParseLimits) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limits.max_depth:
                raise StrictJsonError(f"{label} exceeds the depth limit {limits.max_depth}")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                break


def _check_tree(
    value: Any, *, label: str, limits: ParseLimits, error: type[StrictParseError]
) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise error(f"{label} exceeds the node limit {limits.max_nodes}")
        if isinstance(current, str):
            try:
                scalar_bytes = current.encode("utf-8", "strict")
            except UnicodeError as exc:
                raise error(f"{label} contains an invalid Unicode scalar") from exc
            if len(scalar_bytes) > limits.max_scalar_bytes:
                raise error(
                    f"{label} contains a scalar above the {limits.max_scalar_bytes}-byte limit"
                )
        elif isinstance(current, float) and not math.isfinite(current):
            raise error(f"{label} contains a non-finite number")
        elif isinstance(current, Mapping):
            child_depth = depth + 1
            if child_depth > limits.max_depth:
                raise error(f"{label} exceeds the depth limit {limits.max_depth}")
            for key, item in current.items():
                stack.append((key, child_depth))
                stack.append((item, child_depth))
        elif isinstance(current, Sequence) and not isinstance(
            current, (bytes, bytearray, memoryview)
        ):
            child_depth = depth + 1
            if child_depth > limits.max_depth:
                raise error(f"{label} exceeds the depth limit {limits.max_depth}")
            stack.extend((item, child_depth) for item in current)


def _json_pairs_hook(
    user_hook: Callable[[list[tuple[str, Any]]], Any] | None,
    *,
    label: str,
) -> Callable[[list[tuple[str, Any]]], Any]:
    def strict_pairs(pairs: list[tuple[str, Any]]) -> Any:
        seen: set[str] = set()
        for key, _value in pairs:
            if key in seen:
                raise StrictJsonError(f"{label} has duplicate JSON key {key!r} (repeats key)")
            seen.add(key)
        return user_hook(pairs) if user_hook is not None else dict(pairs)

    return strict_pairs


def _reject_json_constant(value: str) -> None:
    raise StrictJsonError(f"nonfinite JSON number is prohibited (non-finite constant): {value}")


def _json_constant_hook(
    user_hook: Callable[[str], Any] | None,
) -> Callable[[str], Any]:
    def strict_constant(value: str) -> Any:
        if user_hook is not None:
            user_hook(value)
        _reject_json_constant(value)

    return strict_constant


def load_json(
    data: str | bytes | bytearray | memoryview,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "JSON input",
    **kwargs: Any,
) -> Any:
    """Parse one UTF-8 JSON value with duplicate, finite, and resource checks."""

    text = _bounded_text(data, label=label, limits=limits, error=StrictJsonError)
    _scan_json_depth(text, label=label, limits=limits)
    user_pairs = kwargs.pop("object_pairs_hook", None)
    user_constant = kwargs.pop("parse_constant", None)
    try:
        value = json.loads(
            text,
            object_pairs_hook=_json_pairs_hook(user_pairs, label=label),
            parse_constant=_json_constant_hook(user_constant),
            **kwargs,
        )
    except StrictJsonError:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise StrictJsonError(f"{label} is invalid: {exc}") from exc
    _check_tree(value, label=label, limits=limits, error=StrictJsonError)
    return value


def load_json_stream(
    stream: BinaryIO | TextIO,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "JSON stream",
    **kwargs: Any,
) -> Any:
    """Read and parse one bounded JSON stream."""

    return load_json(
        _read_bounded_stream(stream, label=label, limits=limits, error=StrictJsonError),
        limits=limits,
        label=label,
        **kwargs,
    )


def load_json_path(
    path: str | os.PathLike[str],
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    **kwargs: Any,
) -> Any:
    """Descriptor-read and parse one bounded regular JSON file."""

    effective_label = label or f"JSON file {Path(path)}"
    return load_json(
        _read_bounded_path(path, label=effective_label, limits=limits, error=StrictJsonError),
        limits=limits,
        label=effective_label,
        **kwargs,
    )


def load_json_pinned(
    source: PinnedReadable,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    **kwargs: Any,
) -> Any:
    """Read a pinned JSON file with bounded allocation and post-read verification."""

    effective_label = label or str(source)
    return load_json(
        _read_bounded_pinned(
            source,
            label=effective_label,
            limits=limits,
            error=StrictJsonError,
        ),
        limits=limits,
        label=effective_label,
        **kwargs,
    )


def iter_jsonl(
    data: str | bytes | bytearray | memoryview,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "JSONL input",
    skip_blank: bool = True,
) -> Iterator[Any]:
    """Yield bounded strict JSONL records with a finite line inventory."""

    text = _bounded_text(data, label=label, limits=limits, error=StrictJsonError)
    for index, line in enumerate(text.splitlines(), start=1):
        if index > limits.max_jsonl_lines:
            raise StrictJsonError(f"{label} exceeds the line limit {limits.max_jsonl_lines}")
        if skip_blank and not line.strip():
            continue
        yield load_json(line, limits=limits, label=f"{label} line {index}")


def iter_jsonl_stream(
    stream: BinaryIO | TextIO,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "JSONL stream",
    skip_blank: bool = True,
) -> Iterator[Any]:
    """Read one bounded JSONL stream and yield strict records."""

    yield from iter_jsonl(
        _read_bounded_stream(stream, label=label, limits=limits, error=StrictJsonError),
        limits=limits,
        label=label,
        skip_blank=skip_blank,
    )


def iter_jsonl_path(
    path: str | os.PathLike[str],
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    skip_blank: bool = True,
) -> Iterator[Any]:
    """Descriptor-read one bounded regular JSONL file and yield strict records."""

    effective_label = label or f"JSONL file {Path(path)}"
    data = _read_bounded_path(
        path,
        label=effective_label,
        limits=limits,
        error=StrictJsonError,
    )
    yield from iter_jsonl(
        data,
        limits=limits,
        label=effective_label,
        skip_blank=skip_blank,
    )


def iter_jsonl_pinned(
    source: PinnedReadable,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    skip_blank: bool = True,
) -> Iterator[Any]:
    """Read pinned JSONL with whole-file bounds and post-read verification."""

    effective_label = label or str(source)
    data = _read_bounded_pinned(
        source,
        label=effective_label,
        limits=limits,
        error=StrictJsonError,
    )
    yield from iter_jsonl(
        data,
        limits=limits,
        label=effective_label,
        skip_blank=skip_blank,
    )


def _bounded_yaml_loader(
    base_loader: type[yaml.SafeLoader], *, label: str, limits: ParseLimits
) -> type[yaml.SafeLoader]:
    if yaml is None:
        raise StrictYamlError("PyYAML is required to parse YAML")
    if not issubclass(base_loader, yaml.SafeLoader):
        raise StrictYamlError("only yaml.SafeLoader subclasses are permitted")

    class BoundedLoader(base_loader):  # type: ignore[misc, valid-type]
        _strict_container_depth = 0
        _strict_nodes = 0

        def compose_node(self, parent: Any, index: Any) -> Any:
            if self.check_event(yaml.AliasEvent):
                raise StrictYamlError(f"{label} aliases are forbidden")
            event = self.peek_event()
            is_container = isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent))
            next_depth = self._strict_container_depth + int(is_container)
            previous_depth = self._strict_container_depth
            self._strict_nodes += 1
            try:
                if next_depth > limits.max_depth:
                    raise StrictYamlError(f"{label} exceeds the depth limit {limits.max_depth}")
                if self._strict_nodes > limits.max_nodes:
                    raise StrictYamlError(f"{label} exceeds the node limit {limits.max_nodes}")
                self._strict_container_depth = next_depth
                return super().compose_node(parent, index)
            finally:
                self._strict_container_depth = previous_depth

        def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
            self.flatten_mapping(node)
            result: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in result
                except TypeError as exc:
                    raise StrictYamlError(f"{label} has an unhashable mapping key") from exc
                if duplicate:
                    raise StrictYamlError(f"{label} repeats key {key!r}")
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    return BoundedLoader


def load_yaml(
    data: str | bytes | bytearray | memoryview,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "YAML input",
    Loader: type[yaml.SafeLoader] = _DEFAULT_YAML_LOADER,
) -> Any:
    """Parse one safe YAML document with duplicate, alias, and resource checks."""

    if yaml is None:
        raise StrictYamlError("PyYAML is required to parse YAML")
    text = _bounded_text(data, label=label, limits=limits, error=StrictYamlError)
    loader = _bounded_yaml_loader(Loader, label=label, limits=limits)
    try:
        value = yaml.load(text, Loader=loader)
    except StrictYamlError:
        raise
    except (yaml.YAMLError, ValueError, RecursionError) as exc:
        raise StrictYamlError(f"{label} is invalid: {exc}") from exc
    _check_tree(value, label=label, limits=limits, error=StrictYamlError)
    return value


def load_yaml_stream(
    stream: BinaryIO | TextIO,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str = "YAML stream",
    Loader: type[yaml.SafeLoader] = _DEFAULT_YAML_LOADER,
) -> Any:
    """Read and parse one bounded safe YAML stream."""

    return load_yaml(
        _read_bounded_stream(stream, label=label, limits=limits, error=StrictYamlError),
        limits=limits,
        label=label,
        Loader=Loader,
    )


def load_yaml_path(
    path: str | os.PathLike[str],
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    Loader: type[yaml.SafeLoader] = _DEFAULT_YAML_LOADER,
) -> Any:
    """Descriptor-read and parse one bounded regular YAML file."""

    effective_label = label or f"YAML file {Path(path)}"
    return load_yaml(
        _read_bounded_path(path, label=effective_label, limits=limits, error=StrictYamlError),
        limits=limits,
        label=effective_label,
        Loader=Loader,
    )


def load_yaml_pinned(
    source: PinnedReadable,
    *,
    limits: ParseLimits = DEFAULT_LIMITS,
    label: str | None = None,
    Loader: type[yaml.SafeLoader] = _DEFAULT_YAML_LOADER,
) -> Any:
    """Read pinned YAML with bounded allocation and post-read verification."""

    effective_label = label or str(source)
    return load_yaml(
        _read_bounded_pinned(
            source,
            label=effective_label,
            limits=limits,
            error=StrictYamlError,
        ),
        limits=limits,
        label=effective_label,
        Loader=Loader,
    )
