# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed path checks used before source bytes are opened or output is written."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised for symlinks, missing files, overlaps, or unsafe destinations."""


@dataclass(frozen=True)
class FileSnapshot:
    """Bytes and filesystem identity read from one authenticated descriptor."""

    path: Path
    data: bytes
    sha256: str
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def reject_symlink_components(path: str | Path, *, label: str) -> Path:
    supplied = Path(path)
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    cursor = supplied
    while True:
        if cursor.is_symlink():
            raise PathSafetyError(f"{label}: symlink components are prohibited: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return supplied


def require_regular_file(path: str | Path, *, label: str) -> Path:
    supplied = reject_symlink_components(path, label=label)
    if supplied.is_symlink() or not supplied.is_file():
        raise PathSafetyError(f"{label}: expected a regular non-symlink file: {supplied}")
    return supplied.resolve()


def read_file_snapshot(path: str | Path, *, label: str) -> FileSnapshot:
    """Read one regular file once and bind the bytes to its descriptor identity."""

    supplied = reject_symlink_components(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(supplied, flags)
    except OSError as exc:
        raise PathSafetyError(
            f"{label}: expected a regular non-symlink file; cannot safely open {supplied}: {exc}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PathSafetyError(f"{label}: expected a regular non-symlink file: {supplied}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise PathSafetyError(f"{label}: cannot read authenticated file descriptor: {exc}") from exc
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after):
        raise PathSafetyError(f"{label}: file changed while its authenticated snapshot was read")
    data = b"".join(chunks)
    if len(data) != before.st_size:
        raise PathSafetyError(f"{label}: descriptor byte count differs from file size")
    try:
        current = os.stat(supplied, follow_symlinks=False)
    except OSError as exc:
        raise PathSafetyError(f"{label}: path disappeared after authenticated read: {exc}") from exc
    if not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(after):
        raise PathSafetyError(f"{label}: path identity changed during authenticated read")
    return FileSnapshot(
        path=Path(os.path.abspath(supplied)),
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        device=after.st_dev,
        inode=after.st_ino,
        mode=after.st_mode,
        link_count=after.st_nlink,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        ctime_ns=after.st_ctime_ns,
    )


def verify_file_snapshot_current(snapshot: FileSnapshot, *, label: str) -> None:
    """Reject replacement, mutation, or restoration after an authenticated read."""

    current = read_file_snapshot(snapshot.path, label=label)
    expected = (
        snapshot.sha256,
        snapshot.device,
        snapshot.inode,
        snapshot.mode,
        snapshot.link_count,
        snapshot.size,
        snapshot.mtime_ns,
        snapshot.ctime_ns,
    )
    actual = (
        current.sha256,
        current.device,
        current.inode,
        current.mode,
        current.link_count,
        current.size,
        current.mtime_ns,
        current.ctime_ns,
    )
    if actual != expected or current.data != snapshot.data:
        raise PathSafetyError(f"{label}: file changed after its authenticated snapshot")


def require_safe_output(path: str | Path, *, label: str) -> Path:
    supplied = reject_symlink_components(path, label=label)
    if supplied.is_symlink():
        raise PathSafetyError(f"{label}: output symlinks are prohibited")
    return supplied.resolve()


def reject_overlap(source: Path, output: Path) -> None:
    if output == source or output in source.parents or source in output.parents:
        raise PathSafetyError("output/source overlap: source and output must be disjoint")


def durable_path_leaks(data: bytes, *, extra_roots: tuple[Path, ...] = ()) -> list[str]:
    candidates = {
        Path.cwd().resolve(),
        Path(os.environ.get("TMPDIR", "/tmp")).resolve(),
        *[root.resolve() for root in extra_roots],
    }
    for name in ("HOME", "RUNNER_TEMP", "GITHUB_WORKSPACE"):
        value = os.environ.get(name)
        if value:
            candidates.add(Path(value).resolve())
    leaks = []
    for candidate in sorted(candidates, key=lambda item: str(item)):
        encoded = str(candidate).encode()
        if len(encoded) >= 2 and encoded in data:
            leaks.append(str(candidate))
    return leaks


def publish_directory(candidate: Path, output: Path, *, overwrite: bool) -> None:
    """Publish a same-parent candidate while preserving an overwritten tree on failure."""
    if candidate.parent != output.parent or candidate.is_symlink() or not candidate.is_dir():
        raise PathSafetyError("publish: candidate must be a regular same-parent directory")
    if output.exists() and not overwrite:
        raise PathSafetyError(f"publish: output exists: {output}; pass --overwrite explicitly")
    backup: Path | None = None
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise PathSafetyError("publish: refusing non-directory output replacement")
        backup = Path(tempfile.mkdtemp(prefix=f".{output.name}.backup-", dir=output.parent))
        backup.rmdir()
        output.replace(backup)
    try:
        candidate.replace(output)
    except Exception:
        if backup is not None and backup.exists() and not output.exists():
            backup.replace(output)
        raise
    if backup is not None:
        shutil.rmtree(backup)


__all__ = [
    "FileSnapshot",
    "PathSafetyError",
    "durable_path_leaks",
    "publish_directory",
    "read_file_snapshot",
    "reject_overlap",
    "reject_symlink_components",
    "require_regular_file",
    "require_safe_output",
    "verify_file_snapshot_current",
]
