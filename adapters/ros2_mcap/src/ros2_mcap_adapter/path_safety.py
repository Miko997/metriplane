# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed path checks used before source bytes are opened or output is written."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import stat
from collections.abc import Callable
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
    parent_device: int
    parent_inode: int
    parent_mode: int


@dataclass(frozen=True)
class DirectoryEntrySnapshot:
    """One descriptor-authenticated entry in a generated directory tree."""

    relative_path: str
    entry_type: str
    data: bytes | None
    sha256: str | None
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class DirectorySnapshot:
    """A complete generated tree bound to its root inode and entry identities."""

    path: Path
    device: int
    inode: int
    mode: int
    link_count: int
    size: int
    mtime_ns: int
    parent_device: int
    parent_inode: int
    parent_mode: int
    entries: tuple[DirectoryEntrySnapshot, ...]


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


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Identity fields stable across a same-filesystem directory rename."""

    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )


def _namespace_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode)


def _rename_stable_file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """File identity fields not changed by a same-filesystem rename."""

    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
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
    absolute = Path(os.path.abspath(supplied))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent, parent_identity = _open_parent(absolute.parent, label=label)
    try:
        descriptor = os.open(absolute.name, flags, dir_fd=parent)
    except OSError as exc:
        os.close(parent)
        raise PathSafetyError(
            f"{label}: expected a regular non-symlink file; cannot safely open {absolute}: {exc}"
        ) from exc
    try:
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PathSafetyError(f"{label}: expected a regular non-symlink file: {absolute}")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        except OSError as exc:
            raise PathSafetyError(
                f"{label}: cannot read authenticated file descriptor: {exc}"
            ) from exc
        if _identity(before) != _identity(after):
            raise PathSafetyError(
                f"{label}: file changed while its authenticated snapshot was read"
            )
        data = b"".join(chunks)
        if len(data) != before.st_size:
            raise PathSafetyError(f"{label}: descriptor byte count differs from file size")
        try:
            current = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise PathSafetyError(
                f"{label}: path disappeared after authenticated read: {exc}"
            ) from exc
        if not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(after):
            raise PathSafetyError(f"{label}: path identity changed during authenticated read")
        _verify_directory_namespace(absolute.parent, parent_identity, label=label)
    finally:
        os.close(descriptor)
        os.close(parent)
    return FileSnapshot(
        path=absolute,
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        device=after.st_dev,
        inode=after.st_ino,
        mode=after.st_mode,
        link_count=after.st_nlink,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        ctime_ns=after.st_ctime_ns,
        parent_device=parent_identity.st_dev,
        parent_inode=parent_identity.st_ino,
        parent_mode=parent_identity.st_mode,
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
        snapshot.parent_device,
        snapshot.parent_inode,
        snapshot.parent_mode,
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
        current.parent_device,
        current.parent_inode,
        current.parent_mode,
    )
    if actual != expected or current.data != snapshot.data:
        raise PathSafetyError(f"{label}: file changed after its authenticated snapshot")


def require_safe_output(path: str | Path, *, label: str) -> Path:
    supplied = reject_symlink_components(path, label=label)
    if supplied.is_symlink():
        raise PathSafetyError(f"{label}: output symlinks are prohibited")
    return Path(os.path.abspath(supplied))


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


def _read_file_entry(
    parent_descriptor: int,
    name: str,
    relative_path: str,
    *,
    label: str,
) -> DirectoryEntrySnapshot:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise PathSafetyError(f"{label}: cannot safely open {relative_path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PathSafetyError(f"{label}: non-regular file prohibited: {relative_path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _identity(before) != _identity(after):
            raise PathSafetyError(f"{label}: file changed while read: {relative_path}")
        os.fsync(descriptor)
    except OSError as exc:
        raise PathSafetyError(f"{label}: cannot read {relative_path}: {exc}") from exc
    finally:
        os.close(descriptor)
    try:
        current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise PathSafetyError(f"{label}: entry disappeared after read: {relative_path}") from exc
    if not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(after):
        raise PathSafetyError(f"{label}: entry identity changed during read: {relative_path}")
    data = b"".join(chunks)
    if len(data) != after.st_size:
        raise PathSafetyError(f"{label}: descriptor byte count differs: {relative_path}")
    return DirectoryEntrySnapshot(
        relative_path=relative_path,
        entry_type="file",
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


def _read_directory_entries(
    descriptor: int,
    prefix: str,
    *,
    label: str,
) -> tuple[DirectoryEntrySnapshot, ...]:
    try:
        names = sorted(os.listdir(descriptor))
    except OSError as exc:
        raise PathSafetyError(f"{label}: cannot enumerate authenticated directory: {exc}") from exc
    entries: list[DirectoryEntrySnapshot] = []
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    for name in names:
        if name in {"", ".", ".."} or "/" in name or "\x00" in name:
            raise PathSafetyError(f"{label}: unsafe directory entry name")
        relative_path = f"{prefix}/{name}" if prefix else name
        try:
            current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as exc:
            raise PathSafetyError(f"{label}: cannot inspect {relative_path}: {exc}") from exc
        if stat.S_ISLNK(current.st_mode):
            raise PathSafetyError(f"{label}: generated symlink prohibited: {relative_path}")
        if stat.S_ISREG(current.st_mode):
            entries.append(_read_file_entry(descriptor, name, relative_path, label=label))
            continue
        if not stat.S_ISDIR(current.st_mode):
            raise PathSafetyError(f"{label}: non-file entry prohibited: {relative_path}")
        try:
            child = os.open(name, directory_flags, dir_fd=descriptor)
        except OSError as exc:
            raise PathSafetyError(f"{label}: cannot safely open {relative_path}: {exc}") from exc
        try:
            before = os.fstat(child)
            if not stat.S_ISDIR(before.st_mode):
                raise PathSafetyError(f"{label}: expected directory: {relative_path}")
            nested = _read_directory_entries(child, relative_path, label=label)
            os.fsync(child)
            after = os.fstat(child)
        except OSError as exc:
            raise PathSafetyError(f"{label}: cannot read {relative_path}: {exc}") from exc
        finally:
            os.close(child)
        try:
            path_current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as exc:
            raise PathSafetyError(
                f"{label}: directory disappeared after read: {relative_path}"
            ) from exc
        if _identity(before) != _identity(after) or _identity(after) != _identity(path_current):
            raise PathSafetyError(f"{label}: directory changed while read: {relative_path}")
        entries.append(
            DirectoryEntrySnapshot(
                relative_path=relative_path,
                entry_type="directory",
                data=None,
                sha256=None,
                device=after.st_dev,
                inode=after.st_ino,
                mode=after.st_mode,
                link_count=after.st_nlink,
                size=after.st_size,
                mtime_ns=after.st_mtime_ns,
                ctime_ns=after.st_ctime_ns,
            )
        )
        entries.extend(nested)
    return tuple(entries)


def _snapshot_open_directory(
    descriptor: int,
    *,
    path: Path,
    label: str,
    parent_identity: os.stat_result,
) -> DirectorySnapshot:
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise PathSafetyError(f"{label}: expected a regular directory: {path}")
    entries = _read_directory_entries(descriptor, "", label=label)
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if _identity(before) != _identity(after):
        raise PathSafetyError(f"{label}: directory changed while its snapshot was read")
    return DirectorySnapshot(
        path=Path(os.path.abspath(path)),
        device=after.st_dev,
        inode=after.st_ino,
        mode=after.st_mode,
        link_count=after.st_nlink,
        size=after.st_size,
        mtime_ns=after.st_mtime_ns,
        parent_device=parent_identity.st_dev,
        parent_inode=parent_identity.st_ino,
        parent_mode=parent_identity.st_mode,
        entries=entries,
    )


def _open_parent(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    """Open an absolute directory one component at a time without following links."""

    absolute = Path(os.path.abspath(path))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise PathSafetyError(f"{label}: cannot safely open parent directory: {exc}") from exc
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(descriptor)
        raise PathSafetyError(f"{label}: expected a directory: {absolute}")
    return descriptor, opened


def _verify_directory_namespace(
    path: Path,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    current_descriptor, current = _open_parent(path, label=label)
    os.close(current_descriptor)
    if _namespace_identity(current) != _namespace_identity(expected):
        raise PathSafetyError(f"{label}: directory namespace identity changed")


def _open_named_directory(parent_descriptor: int, name: str, *, label: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        return os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise PathSafetyError(f"{label}: cannot safely open directory: {exc}") from exc


def read_directory_snapshot(path: str | Path, *, label: str) -> DirectorySnapshot:
    """Read and fsync a complete directory tree through authenticated descriptors."""

    supplied = reject_symlink_components(path, label=label)
    absolute = Path(os.path.abspath(supplied))
    parent, parent_identity = _open_parent(absolute.parent, label=label)
    try:
        descriptor = _open_named_directory(parent, absolute.name, label=label)
        try:
            snapshot = _snapshot_open_directory(
                descriptor,
                path=absolute,
                label=label,
                parent_identity=parent_identity,
            )
            current = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
            if _directory_identity(current) != (
                snapshot.device,
                snapshot.inode,
                snapshot.mode,
                snapshot.link_count,
                snapshot.size,
                snapshot.mtime_ns,
            ):
                raise PathSafetyError(f"{label}: root directory identity changed during read")
            _verify_directory_namespace(absolute.parent, parent_identity, label=label)
            return snapshot
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _same_tree(left: DirectorySnapshot, right: DirectorySnapshot) -> bool:
    return (
        left.device,
        left.inode,
        left.mode,
        left.link_count,
        left.size,
        left.mtime_ns,
        left.parent_device,
        left.parent_inode,
        left.parent_mode,
    ) == (
        right.device,
        right.inode,
        right.mode,
        right.link_count,
        right.size,
        right.mtime_ns,
        right.parent_device,
        right.parent_inode,
        right.parent_mode,
    ) and left.entries == right.entries


def _renameat2(
    parent_descriptor: int,
    source_name: str,
    target_name: str,
    *,
    flags: int,
) -> None:
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise PathSafetyError("publish: atomic renameat2 is unavailable on this platform") from exc
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    result = function(
        parent_descriptor,
        os.fsencode(source_name),
        parent_descriptor,
        os.fsencode(target_name),
        flags,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise PathSafetyError(f"publish: output exists: {target_name}; replacement is prohibited")
    if error in {errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL}:
        raise PathSafetyError("publish: required atomic rename operation is unavailable")
    raise PathSafetyError(f"publish: atomic rename failed: {os.strerror(error)}")


def _rename_noreplace(parent_descriptor: int, source_name: str, target_name: str) -> None:
    _renameat2(parent_descriptor, source_name, target_name, flags=1)


def publish_file(
    candidate: Path,
    output: Path,
    *,
    overwrite: bool,
    expected_data: bytes,
    expected_identity: os.stat_result,
) -> None:
    """Publish one open-and-authenticated regular file to a fresh destination."""

    candidate = Path(os.path.abspath(candidate))
    output = Path(os.path.abspath(output))
    if candidate.parent != output.parent or candidate.name == output.name:
        raise PathSafetyError("publish: file candidate must be a distinct same-parent path")
    parent, parent_identity = _open_parent(candidate.parent, label="file publish")
    published = False
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            descriptor = os.open(candidate.name, flags, dir_fd=parent)
        except OSError as exc:
            raise PathSafetyError(f"file publish: cannot safely open candidate: {exc}") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(
                expected_identity
            ):
                raise PathSafetyError("file publish: candidate identity changed")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if _identity(before) != _identity(after) or b"".join(chunks) != expected_data:
            raise PathSafetyError("file publish: candidate bytes or identity changed")
        current = os.stat(candidate.name, dir_fd=parent, follow_symlinks=False)
        if _identity(current) != _identity(after):
            raise PathSafetyError("file publish: candidate namespace identity changed")
        try:
            os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            flag = " even with --overwrite" if overwrite else ""
            raise PathSafetyError(
                f"file publish: output exists and replacement is prohibited{flag}: {output}"
            )
        _rename_noreplace(parent, candidate.name, output.name)
        published = True
        try:
            descriptor = os.open(output.name, flags, dir_fd=parent)
        except OSError as exc:
            raise PathSafetyError(f"file publish: cannot verify published output: {exc}") from exc
        try:
            output_before = os.fstat(descriptor)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            output_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        output_current = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        if (
            _identity(output_before) != _identity(output_after)
            or _identity(output_after) != _identity(output_current)
            or _rename_stable_file_identity(output_after)
            != _rename_stable_file_identity(expected_identity)
            or b"".join(chunks) != expected_data
        ):
            raise PathSafetyError("file publish: published output differs from authenticated bytes")
        _verify_directory_namespace(candidate.parent, parent_identity, label="file publish")
        os.fsync(parent)
    except Exception as original:
        if published:
            try:
                _renameat2(parent, output.name, candidate.name, flags=1)
                os.fsync(parent)
            except (OSError, PathSafetyError) as rollback_error:
                raise PathSafetyError(
                    f"file publish: verification failed and atomic rollback failed: {original}"
                ) from rollback_error
        raise
    finally:
        os.close(parent)


def publish_directory(
    candidate: Path,
    output: Path,
    *,
    overwrite: bool,
    snapshot: DirectorySnapshot,
    commit_check: Callable[[], None] | None = None,
) -> None:
    """Publish an authenticated tree atomically to a fresh Linux destination."""

    candidate = Path(os.path.abspath(candidate))
    output = Path(os.path.abspath(output))
    if candidate.parent != output.parent or candidate.name == output.name:
        raise PathSafetyError("publish: candidate must be a distinct same-parent directory")
    if snapshot.path != candidate:
        raise PathSafetyError("publish: authenticated snapshot does not name the candidate")
    parent, parent_identity = _open_parent(candidate.parent, label="publish")
    published = False
    try:
        if (
            snapshot.parent_device,
            snapshot.parent_inode,
            snapshot.parent_mode,
        ) != _namespace_identity(parent_identity):
            raise PathSafetyError("publish: candidate parent changed after authentication")
        descriptor = _open_named_directory(parent, candidate.name, label="publish candidate")
        try:
            current = _snapshot_open_directory(
                descriptor,
                path=candidate,
                label="publish candidate",
                parent_identity=parent_identity,
            )
        finally:
            os.close(descriptor)
        if not _same_tree(snapshot, current):
            raise PathSafetyError("publish: candidate changed after its authenticated snapshot")
        try:
            destination = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            destination = None
        except OSError as exc:
            raise PathSafetyError(f"publish: cannot inspect output: {exc}") from exc
        if destination is not None:
            flag = " even with --overwrite" if overwrite else ""
            raise PathSafetyError(
                f"publish: output exists and directory replacement is prohibited{flag}: {output}"
            )
        _rename_noreplace(parent, candidate.name, output.name)
        published = True
        output_descriptor = _open_named_directory(parent, output.name, label="published output")
        try:
            published_snapshot = _snapshot_open_directory(
                output_descriptor,
                path=output,
                label="published output",
                parent_identity=parent_identity,
            )
        finally:
            os.close(output_descriptor)
        output_current = os.stat(output.name, dir_fd=parent, follow_symlinks=False)
        if _directory_identity(output_current) != (
            published_snapshot.device,
            published_snapshot.inode,
            published_snapshot.mode,
            published_snapshot.link_count,
            published_snapshot.size,
            published_snapshot.mtime_ns,
        ):
            raise PathSafetyError("publish: output path identity changed during verification")
        if not _same_tree(snapshot, published_snapshot):
            raise PathSafetyError("publish: published tree differs from authenticated candidate")
        if commit_check is not None:
            commit_check()
        _verify_directory_namespace(candidate.parent, parent_identity, label="publish")
        os.fsync(parent)
    except Exception as original:
        if published:
            try:
                _renameat2(parent, output.name, candidate.name, flags=1)
                os.fsync(parent)
            except (OSError, PathSafetyError) as rollback_error:
                raise PathSafetyError(
                    f"publish: verification failed and atomic rollback failed: {original}"
                ) from rollback_error
        raise
    finally:
        os.close(parent)


__all__ = [
    "DirectoryEntrySnapshot",
    "DirectorySnapshot",
    "FileSnapshot",
    "PathSafetyError",
    "durable_path_leaks",
    "publish_directory",
    "publish_file",
    "read_directory_snapshot",
    "read_file_snapshot",
    "reject_overlap",
    "reject_symlink_components",
    "require_regular_file",
    "require_safe_output",
    "verify_file_snapshot_current",
]
