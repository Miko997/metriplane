# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ctypes
import errno
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CONFIG, DEFAULT_LOCK
from .fixture import FixtureError, write_conversion
from .parser import SourceValidationError, load_source
from .validation import ConfigValidationError, load_config


class AdapterError(RuntimeError):
    """Stable CLI-facing adapter error."""


_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    data: bytes
    stat: tuple[int, int, int, int, int, int]


def verify_adapter_commit(value: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise AdapterError("adapter commit must be one exact lowercase 40-hex identity")
    return value


def _reject_symlink_components(path: Path, *, label: str) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    cursor = absolute
    while True:
        if cursor.is_symlink():
            raise AdapterError(f"{label}: symlink components are prohibited")
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


def _snapshot(path: Path, *, label: str) -> _Snapshot:
    _reject_symlink_components(path, label=label)
    if path.is_symlink() or not path.is_file():
        raise AdapterError(f"{label}: regular non-symlink file is required")
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_mode,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    )
    if identity_before != identity_after or len(data) != after.st_size:
        raise AdapterError(f"{label}: file changed while read")
    return _Snapshot(path=path.resolve(), data=data, stat=identity_after)


def _verify_snapshot(snapshot: _Snapshot, *, label: str) -> None:
    current = _snapshot(snapshot.path, label=label)
    if current.stat != snapshot.stat or current.data != snapshot.data:
        raise AdapterError(f"{label}: file changed after authenticated read")


def _reject_overlap(source: Path, output: Path) -> None:
    source_absolute = Path(os.path.abspath(source))
    output_absolute = Path(os.path.abspath(output))
    if (
        source_absolute == output_absolute
        or output_absolute in source_absolute.parents
        or source_absolute in output_absolute.parents
    ):
        raise AdapterError("source/output path overlap is prohibited")


def _inventory(root: Path) -> dict[str, bytes]:
    if root.is_symlink() or not root.is_dir():
        raise AdapterError("generated output must be a regular non-symlink directory")
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise AdapterError("generated output contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise AdapterError("generated output contains a non-file entry")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def find_path_leaks(files: dict[str, bytes], *, extra_roots: tuple[Path, ...]) -> list[str]:
    candidates = {Path.cwd().resolve(), *[item.resolve() for item in extra_roots]}
    for name in ("HOME", "RUNNER_TEMP", "GITHUB_WORKSPACE", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            candidates.add(Path(value).resolve())
    leaks: list[str] = []
    for candidate in candidates:
        encoded = str(candidate).encode("utf-8")
        if len(encoded) >= 2 and any(encoded in data for data in files.values()):
            leaks.append(str(candidate))
    return sorted(leaks)


def _rename_noreplace(candidate: Path, output: Path) -> None:
    if os.name != "posix":
        raise AdapterError("atomic no-clobber publication requires a POSIX platform")
    parent_fd = os.open(candidate.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            function = ctypes.CDLL(None, use_errno=True).renameat2
        except AttributeError:
            function = None
        if function is not None:
            function.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            function.restype = ctypes.c_int
            result = function(
                parent_fd,
                os.fsencode(candidate.name),
                parent_fd,
                os.fsencode(output.name),
                1,
            )
            if result == 0:
                os.fsync(parent_fd)
                return
            error = ctypes.get_errno()
            if error in {errno.EEXIST, errno.ENOTEMPTY}:
                raise AdapterError("output directory collision; replacement is prohibited")
            if error not in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
                raise AdapterError(f"atomic publication failed: {os.strerror(error)}")
        try:
            renamex = ctypes.CDLL(None, use_errno=True).renamex_np
        except AttributeError as exc:
            raise AdapterError("atomic no-clobber directory publication is unavailable") from exc
        renamex.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex.restype = ctypes.c_int
        result = renamex(os.fsencode(candidate), os.fsencode(output), 0x00000004)
        if result != 0:
            error = ctypes.get_errno()
            if error in {errno.EEXIST, errno.ENOTEMPTY}:
                raise AdapterError("output directory collision; replacement is prohibited")
            raise AdapterError(f"atomic publication failed: {os.strerror(error)}")
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def publish_candidate(candidate: Path, output: Path, *, expected: dict[str, bytes]) -> None:
    output = Path(os.path.abspath(output))
    _reject_symlink_components(output, label="conversion output")
    if output.exists() or output.is_symlink():
        raise AdapterError("output directory collision; replacement is prohibited")
    if candidate.parent != output.parent:
        raise AdapterError("atomic candidate must share the output parent")
    if _inventory(candidate) != expected:
        raise AdapterError("generated output changed before publication")
    _rename_noreplace(candidate, output)
    if _inventory(output) != expected:
        raise AdapterError("published output differs from authenticated candidate")


def inspect_source(
    source_root: str | Path,
    *,
    config_path: str | Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    try:
        config = load_config(config_path)
        trace = load_source(
            source_root,
            expected_datum=config.expected_planar_datum_uuid,
            frame_interval_ns=config.frame_interval_ns,
            entity_order=config.entity_order,
        )
    except (ConfigValidationError, SourceValidationError, ValueError) as exc:
        raise AdapterError(str(exc)) from exc
    return {
        "complete_snapshot_policy": "exact timestamp join; both AMRs required",
        "datum_authority": "statusReport.location.planarDatum",
        "first_status_timestamp": trace.status_records[0].timestamp,
        "frame_count": len(trace.frames),
        "frame_interval_ns": config.frame_interval_ns,
        "identity_count": len(trace.identities),
        "identity_sha256": trace.identity_sha256,
        "path_prediction_count": sum(len(item.path) for item in trace.status_records),
        "prediction_derived_frame_count": 0,
        "profile_id": config.profile_id,
        "source_classification": "synthetic_format_engineering",
        "status_record_count": len(trace.status_records),
        "status_sha256": trace.status_sha256,
        "status_timestamp_count": len(trace.frames),
        "transport": "offline files only; no network access",
        "variant": trace.variant,
    }


def convert(
    source_root: str | Path,
    *,
    config_path: str | Path,
    output_root: str | Path,
    adapter_commit: str,
    overwrite: bool = False,
) -> dict[str, object]:
    candidate: Path | None = None
    try:
        verify_adapter_commit(adapter_commit)
        source = Path(source_root)
        output = Path(os.path.abspath(output_root))
        config_file = Path(config_path)
        lock_file = DEFAULT_LOCK
        _reject_symlink_components(source, label="source root")
        if source.is_symlink() or not source.is_dir():
            raise AdapterError("source root must be a regular non-symlink directory")
        _reject_overlap(source.resolve(), output)
        _reject_overlap(config_file.resolve(), output)
        _reject_overlap(lock_file.resolve(), output)
        if output.exists() or output.is_symlink():
            suffix = " even with --overwrite" if overwrite else ""
            raise AdapterError(f"output directory collision{suffix}; replacement is prohibited")
        identity_snapshot = _snapshot(source / "identity.jsonl", label="identity source")
        status_snapshot = _snapshot(source / "status.jsonl", label="status source")
        config_snapshot = _snapshot(config_file, label="frozen config")
        lock_snapshot = _snapshot(lock_file, label="adapter lock")
        config = load_config(config_file)
        trace = load_source(
            source,
            expected_datum=config.expected_planar_datum_uuid,
            frame_interval_ns=config.frame_interval_ns,
            entity_order=config.entity_order,
        )
        if (
            trace.identity_bytes != identity_snapshot.data
            or trace.status_bytes != status_snapshot.data
        ):
            raise AdapterError("source bytes differ from authenticated snapshots")
        output.parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{output.name}.candidate-", dir=output.parent))
        summary = write_conversion(
            trace=trace,
            config=config,
            adapter_commit=adapter_commit,
            output_root=candidate,
            config_bytes=config_snapshot.data,
            lock_bytes=lock_snapshot.data,
        )
        expected = _inventory(candidate)
        leaks = find_path_leaks(expected, extra_roots=(candidate, source.resolve()))
        if leaks:
            raise AdapterError(f"machine-local path leak in durable output: {leaks}")
        _verify_snapshot(identity_snapshot, label="identity source")
        _verify_snapshot(status_snapshot, label="status source")
        _verify_snapshot(config_snapshot, label="frozen config")
        _verify_snapshot(lock_snapshot, label="adapter lock")
        publish_candidate(candidate, output, expected=expected)
        candidate = None
        return summary
    except (
        AdapterError,
        ConfigValidationError,
        SourceValidationError,
        FixtureError,
        ValueError,
    ) as exc:
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError(str(exc)) from exc
    finally:
        if candidate is not None:
            shutil.rmtree(candidate, ignore_errors=True)


__all__ = [
    "AdapterError",
    "convert",
    "find_path_leaks",
    "inspect_source",
    "publish_candidate",
    "verify_adapter_commit",
]
