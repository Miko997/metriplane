# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Race-resistant, atomic writes beneath a trusted repository directory."""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class UnsafeWritePathError(ValueError):
    """Raised when a write path contains a link or changes during use."""


class WriteConflictError(FileExistsError):
    """Raised when a destination exists and overwrite was not requested."""


@dataclass(frozen=True, slots=True)
class _EntryIdentity:
    device: int
    inode: int
    mode: int


@dataclass(frozen=True, slots=True)
class _DirectoryLink:
    parent_fd: int
    name: str
    child_fd: int
    display_path: Path


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if os.name != "posix" or any(not hasattr(os, name) for name in required):
        raise OSError(
            errno.ENOTSUP,
            "secure Operator writes require POSIX directory handles and O_NOFOLLOW",
        )
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _safe_parts(relative_path: Path) -> tuple[str, ...]:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{path}': expected a repository-relative path"
        )
    return path.parts


def _component_name(name: str) -> str:
    if not name or Path(name).parts != (name,) or name in {".", ".."}:
        raise UnsafeWritePathError(f"Unsafe operator output component: {name!r}")
    return name


def _translate_component_error(path: Path, exc: OSError) -> None:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{path}': links are not allowed"
        ) from exc
    raise exc


def _identity(result: os.stat_result) -> _EntryIdentity:
    return _EntryIdentity(result.st_dev, result.st_ino, result.st_mode)


def _assert_directory_chain(links: tuple[_DirectoryLink, ...]) -> None:
    for link in links:
        try:
            current = os.stat(link.name, dir_fd=link.parent_fd, follow_symlinks=False)
            opened = os.fstat(link.child_fd)
        except FileNotFoundError as exc:
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{link.display_path}': path changed during write"
            ) from exc
        except OSError as exc:
            _translate_component_error(link.display_path, exc)

        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or _identity(current) != _identity(opened)
        ):
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{link.display_path}': path changed during write"
            )


def _open_child_directory(
    parent_fd: int,
    name: str,
    *,
    create: bool,
    display_path: Path,
) -> tuple[int, bool]:
    flags = _directory_flags()
    created = False
    for _attempt in range(3):
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(name, mode=0o777, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
            except OSError as exc:
                _translate_component_error(display_path, exc)
            continue
        except OSError as exc:
            _translate_component_error(display_path, exc)

        opened = os.fstat(child_fd)
        if not stat.S_ISDIR(opened.st_mode):
            os.close(child_fd)
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': expected a directory"
            )
        return child_fd, created

    raise UnsafeWritePathError(
        f"Unsafe operator output path '{display_path}': path changed during traversal"
    )


def _destination_identity(
    directory_fd: int, name: str, display_path: Path
) -> _EntryIdentity | None:
    try:
        result = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _translate_component_error(display_path, exc)

    if stat.S_ISLNK(result.st_mode):
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': links are not allowed"
        )
    if not stat.S_ISREG(result.st_mode):
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': expected a regular file"
        )
    return _identity(result)


def _assert_destination_unchanged(
    directory_fd: int,
    name: str,
    display_path: Path,
    expected: _EntryIdentity | None,
) -> None:
    if _destination_identity(directory_fd, name, display_path) != expected:
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': destination changed during write"
        )


def _exchange_entries(directory_fd: int, left: str, right: str) -> None:
    """Atomically exchange two entries using Linux renameat2."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOTSUP, "atomic exchange is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd,
        os.fsencode(left),
        directory_fd,
        os.fsencode(right),
        2,  # RENAME_EXCHANGE
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _use_portable_overwrite() -> bool:
    return sys.platform == "darwin"


def _create_backup_link(
    directory_fd: int,
    destination: str,
    display_path: Path,
    expected: _EntryIdentity,
) -> str:
    for _attempt in range(10):
        backup_name = f".{destination}.backup-{secrets.token_hex(8)}"
        try:
            os.link(
                destination,
                backup_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            continue

        try:
            backup_identity = _destination_identity(directory_fd, backup_name, display_path)
            if backup_identity != expected:
                raise UnsafeWritePathError(
                    f"Unsafe operator output path '{display_path}': "
                    "destination changed while preserving the previous value"
                )
            _assert_destination_unchanged(
                directory_fd,
                destination,
                display_path,
                expected,
            )
        except BaseException:
            try:
                os.unlink(backup_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise
        return backup_name
    raise OSError(errno.EEXIST, f"could not preserve existing destination {display_path}")


def _write_all(file_fd: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(file_fd, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "staged Operator write made no progress")
        remaining = remaining[written:]


def _create_staged_file(directory_fd: int, name: str, mode: int) -> tuple[str, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    for _attempt in range(10):
        staged_name = f".{name}.tmp-{secrets.token_hex(8)}"
        try:
            return staged_name, os.open(staged_name, flags, mode, dir_fd=directory_fd)
        except FileExistsError:
            continue
    raise OSError(errno.EEXIST, f"could not allocate staged file for {name}")


@dataclass(slots=True)
class SecureDirectory:
    """An opened repository-relative directory whose complete inode chain is retained."""

    relative_path: Path
    created: bool
    _fds: list[int]
    _links: tuple[_DirectoryLink, ...]

    @property
    def fd(self) -> int:
        return self._fds[-1]

    def verify(self) -> None:
        _assert_directory_chain(self._links)

    def ensure_child_directory(self, name: str) -> bool:
        child_name = _component_name(name)
        self.verify()
        display_path = self.relative_path / child_name
        child_fd, created = _open_child_directory(
            self.fd,
            child_name,
            create=True,
            display_path=display_path,
        )
        try:
            link = _DirectoryLink(self.fd, child_name, child_fd, display_path)
            _assert_directory_chain((*self._links, link))
        finally:
            os.close(child_fd)
        return created

    def _portable_atomic_overwrite(
        self,
        staged_name: str,
        destination: str,
        display_path: Path,
        expected: _EntryIdentity,
        staged_identity: _EntryIdentity,
    ) -> None:
        backup_name: str | None = _create_backup_link(
            self.fd,
            destination,
            display_path,
            expected,
        )
        installed = False
        try:
            self.verify()
            _assert_destination_unchanged(self.fd, destination, display_path, expected)
            os.replace(
                staged_name,
                destination,
                src_dir_fd=self.fd,
                dst_dir_fd=self.fd,
            )
            installed = True
            if _destination_identity(self.fd, destination, display_path) != staged_identity:
                raise UnsafeWritePathError(
                    f"Unsafe operator output path '{display_path}': "
                    "staged value was not installed atomically"
                )
            self.verify()
            if backup_name is None:
                raise OSError(errno.EIO, "portable overwrite lost its rollback entry")
            os.unlink(backup_name, dir_fd=self.fd)
            backup_name = None
        except BaseException:
            if installed and backup_name is not None:
                try:
                    if _destination_identity(self.fd, backup_name, display_path) != expected:
                        raise UnsafeWritePathError(
                            f"Unsafe operator output path '{display_path}': "
                            "rollback value changed during atomic replacement"
                        )
                    os.replace(
                        backup_name,
                        destination,
                        src_dir_fd=self.fd,
                        dst_dir_fd=self.fd,
                    )
                    backup_name = None
                    if _destination_identity(self.fd, destination, display_path) != expected:
                        raise UnsafeWritePathError(
                            f"Unsafe operator output path '{display_path}': "
                            "rollback did not restore the previous value"
                        )
                    os.fsync(self.fd)
                except BaseException as rollback_error:
                    retained_backup = backup_name
                    backup_name = None
                    raise OSError(
                        errno.EIO,
                        f"could not roll back atomic write for {display_path}; "
                        f"previous value retained as {retained_backup}",
                    ) from rollback_error
            raise
        finally:
            if backup_name is not None:
                try:
                    os.unlink(backup_name, dir_fd=self.fd)
                except FileNotFoundError:
                    pass

    def atomic_write(self, name: str, content: bytes, *, overwrite: bool) -> None:
        destination = _component_name(name)
        display_path = self.relative_path / destination
        self.verify()
        expected = _destination_identity(self.fd, destination, display_path)
        if expected is not None and not overwrite:
            raise WriteConflictError(f"destination already exists: {display_path}")

        mode = stat.S_IMODE(expected.mode) if expected is not None else 0o666
        staged_name: str | None = None
        staged_fd: int | None = None
        try:
            staged_name, staged_fd = _create_staged_file(self.fd, destination, mode)
            _write_all(staged_fd, content)
            os.fsync(staged_fd)
            staged_identity = _identity(os.fstat(staged_fd))
            os.close(staged_fd)
            staged_fd = None

            self.verify()
            _assert_destination_unchanged(self.fd, destination, display_path, expected)

            if expected is None:
                installed = False
                try:
                    os.link(
                        staged_name,
                        destination,
                        src_dir_fd=self.fd,
                        dst_dir_fd=self.fd,
                        follow_symlinks=False,
                    )
                    installed = True
                    self.verify()
                except FileExistsError as exc:
                    raise WriteConflictError(
                        f"destination appeared during write: {display_path}"
                    ) from exc
                except BaseException:
                    if installed:
                        os.unlink(destination, dir_fd=self.fd)
                    raise
                os.unlink(staged_name, dir_fd=self.fd)
            else:
                if _use_portable_overwrite():
                    self._portable_atomic_overwrite(
                        staged_name,
                        destination,
                        display_path,
                        expected,
                        staged_identity,
                    )
                else:
                    exchanged = False
                    try:
                        _exchange_entries(self.fd, staged_name, destination)
                        exchanged = True
                        displaced = os.stat(
                            staged_name,
                            dir_fd=self.fd,
                            follow_symlinks=False,
                        )
                        if _identity(displaced) != expected:
                            raise UnsafeWritePathError(
                                f"Unsafe operator output path '{display_path}': "
                                "destination changed during atomic replacement"
                            )
                        self.verify()
                    except BaseException:
                        if exchanged:
                            try:
                                _exchange_entries(self.fd, staged_name, destination)
                            except OSError as rollback_error:
                                raise OSError(
                                    errno.EIO,
                                    f"could not roll back atomic write for {display_path}",
                                ) from rollback_error
                        raise
                    os.unlink(staged_name, dir_fd=self.fd)
            staged_name = None
            os.fsync(self.fd)
        finally:
            if staged_fd is not None:
                os.close(staged_fd)
            if staged_name is not None:
                try:
                    os.unlink(staged_name, dir_fd=self.fd)
                except FileNotFoundError:
                    pass

    def close(self) -> None:
        while self._fds:
            try:
                os.close(self._fds.pop())
            except OSError:
                pass


@contextmanager
def open_secure_directory(
    repo_root: Path,
    relative_path: Path,
    *,
    create: bool,
) -> Iterator[SecureDirectory]:
    """Open and retain every component of a repository-relative directory."""
    parts = _safe_parts(relative_path)
    flags = _directory_flags()
    try:
        root_fd = os.open(repo_root, flags)
    except OSError as exc:
        _translate_component_error(Path(repo_root), exc)

    fds = [root_fd]
    links: list[_DirectoryLink] = []
    current_fd = root_fd
    created_final = False
    display_path = Path()
    try:
        for index, part in enumerate(parts):
            display_path /= part
            child_fd, created = _open_child_directory(
                current_fd,
                part,
                create=create,
                display_path=display_path,
            )
            fds.append(child_fd)
            links.append(_DirectoryLink(current_fd, part, child_fd, display_path))
            current_fd = child_fd
            if index == len(parts) - 1:
                created_final = created

        directory = SecureDirectory(
            relative_path=Path(relative_path),
            created=created_final,
            _fds=fds,
            _links=tuple(links),
        )
        directory.verify()
        try:
            yield directory
        finally:
            directory.close()
    except BaseException:
        while fds:
            try:
                os.close(fds.pop())
            except OSError:
                pass
        raise
