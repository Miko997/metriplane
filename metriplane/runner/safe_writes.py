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

_DARWIN_O_EVTONLY = 0x00008000


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
class _CleanupResult:
    removed: bool
    retained_path: Path | None = None


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


def _entry_identity(directory_fd: int, name: str, display_path: Path) -> _EntryIdentity | None:
    try:
        result = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _translate_component_error(display_path, exc)

    return _identity(result)


def _destination_identity(
    directory_fd: int, name: str, display_path: Path
) -> _EntryIdentity | None:
    identity = _entry_identity(directory_fd, name, display_path)
    if identity is None:
        return None
    if stat.S_ISLNK(identity.mode):
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': links are not allowed"
        )
    if not stat.S_ISREG(identity.mode):
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': expected a regular file"
        )
    return identity


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


def _open_pinned_entry(
    directory_fd: int,
    name: str,
    display_path: Path,
    expected: _EntryIdentity,
) -> int:
    if hasattr(os, "O_PATH"):
        access = os.O_PATH
    elif sys.platform == "darwin":
        # Darwin's metadata-only descriptor does not require file read permission.
        access = _DARWIN_O_EVTONLY
    else:
        access = os.O_RDONLY
    flags = access | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        file_fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        _translate_component_error(display_path, exc)
    try:
        if _identity(os.fstat(file_fd)) != expected:
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': destination changed while pinning"
            )
    except BaseException:
        os.close(file_fd)
        raise
    return file_fd


def _exchange_entries(directory_fd: int, left: str, right: str) -> None:
    """Atomically exchange two entries using the native POSIX platform API."""
    libc = ctypes.CDLL(None, use_errno=True)
    function_name = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    exchange = getattr(libc, function_name, None)
    if exchange is None:
        raise OSError(errno.ENOTSUP, "atomic exchange is unavailable")
    exchange.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    exchange.restype = ctypes.c_int
    result = exchange(
        directory_fd,
        os.fsencode(left),
        directory_fd,
        os.fsencode(right),
        2,  # Linux RENAME_EXCHANGE and Darwin RENAME_SWAP
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _use_portable_overwrite() -> bool:
    if sys.platform != "darwin":
        return False
    return getattr(ctypes.CDLL(None), "renameatx_np", None) is None


def _remove_quarantine_directory(
    directory_fd: int,
    quarantine_name: str,
    quarantine_fd: int,
    display_path: Path,
) -> None:
    opened_identity = _identity(os.fstat(quarantine_fd))
    if _entry_identity(directory_fd, quarantine_name, display_path) != opened_identity:
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': quarantine directory changed"
        )
    os.rmdir(quarantine_name, dir_fd=directory_fd)


def _quarantine_owned_entry(
    directory_fd: int,
    name: str,
    display_path: Path,
    expected: _EntryIdentity,
    pinned_fd: int,
) -> _CleanupResult:
    pinned_identity = _identity(os.fstat(pinned_fd))
    if pinned_identity != expected:
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': cleanup descriptor changed"
        )
    quarantine_name: str | None = None
    quarantine_fd: int | None = None
    for _attempt in range(10):
        candidate = f".{name}.quarantine-{secrets.token_hex(8)}"
        try:
            os.mkdir(candidate, mode=0o700, dir_fd=directory_fd)
        except FileExistsError:
            continue
        quarantine_name = candidate
        created_identity = _entry_identity(directory_fd, candidate, display_path)
        quarantine_fd = os.open(candidate, _directory_flags(), dir_fd=directory_fd)
        try:
            opened_identity = _identity(os.fstat(quarantine_fd))
        except BaseException:
            os.close(quarantine_fd)
            raise
        if created_identity is None or opened_identity != created_identity:
            os.close(quarantine_fd)
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': quarantine directory changed"
            )
        break
    if quarantine_name is None or quarantine_fd is None:
        raise OSError(errno.EEXIST, f"could not allocate cleanup quarantine for {display_path}")

    retained_path = display_path.parent / quarantine_name / "entry"
    remove_quarantine = False
    try:
        opened_identity = _identity(os.fstat(quarantine_fd))
        if _entry_identity(directory_fd, quarantine_name, display_path) != opened_identity:
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': quarantine directory changed"
            )
        try:
            os.rename(
                name,
                "entry",
                src_dir_fd=directory_fd,
                dst_dir_fd=quarantine_fd,
            )
        except FileNotFoundError:
            remove_quarantine = True
            return _CleanupResult(removed=False)

        os.fsync(directory_fd)
        moved_identity = _entry_identity(quarantine_fd, "entry", retained_path)
        if moved_identity != pinned_identity or _identity(os.fstat(pinned_fd)) != pinned_identity:
            return _CleanupResult(removed=False, retained_path=retained_path)
        try:
            os.unlink("entry", dir_fd=quarantine_fd)
            os.fsync(quarantine_fd)
        except OSError:
            return _CleanupResult(removed=False, retained_path=retained_path)
        remove_quarantine = True
        return _CleanupResult(removed=True)
    finally:
        try:
            if remove_quarantine:
                _remove_quarantine_directory(
                    directory_fd,
                    quarantine_name,
                    quarantine_fd,
                    display_path,
                )
                os.fsync(directory_fd)
        finally:
            os.close(quarantine_fd)


def _require_owned_cleanup(result: _CleanupResult, display_path: Path) -> None:
    if result.removed:
        return
    if result.retained_path is not None:
        raise UnsafeWritePathError(
            f"Unsafe operator output path '{display_path}': "
            f"cleanup identity was ambiguous; entry retained as {result.retained_path}"
        )
    raise UnsafeWritePathError(
        f"Unsafe operator output path '{display_path}': entry disappeared before cleanup"
    )


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

    def _recover_trusted_destination(
        self,
        staged_name: str,
        destination: str,
        display_path: Path,
        expected: _EntryIdentity,
        staged_identity: _EntryIdentity,
    ) -> None:
        trusted = {expected, staged_identity}
        current_destination = _entry_identity(self.fd, destination, display_path)
        if current_destination in trusted:
            return
        current_staged = _entry_identity(self.fd, staged_name, display_path)
        if current_staged not in trusted:
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': "
                "neither exchange entry retains a trusted inode"
            )
        _exchange_entries(self.fd, staged_name, destination)
        if _entry_identity(self.fd, destination, display_path) != current_staged:
            raise UnsafeWritePathError(
                f"Unsafe operator output path '{display_path}': "
                "trusted destination recovery was interfered with"
            )

    def atomic_write(self, name: str, content: bytes, *, overwrite: bool) -> None:
        destination = _component_name(name)
        display_path = self.relative_path / destination
        self.verify()
        expected = _destination_identity(self.fd, destination, display_path)
        if expected is not None and not overwrite:
            raise WriteConflictError(f"destination already exists: {display_path}")
        expected_fd = (
            _open_pinned_entry(self.fd, destination, display_path, expected)
            if expected is not None
            else None
        )

        mode = stat.S_IMODE(expected.mode) if expected is not None else 0o666
        staged_name: str | None = None
        staged_fd: int | None = None
        staged_identity: _EntryIdentity | None = None
        try:
            staged_name, staged_fd = _create_staged_file(self.fd, destination, mode)
            staged_identity = _identity(os.fstat(staged_fd))
            _write_all(staged_fd, content)
            os.fsync(staged_fd)

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
                    if _destination_identity(self.fd, destination, display_path) != staged_identity:
                        raise UnsafeWritePathError(
                            f"Unsafe operator output path '{display_path}': "
                            "staged value was not installed atomically"
                        )
                    self.verify()
                except FileExistsError as exc:
                    raise WriteConflictError(
                        f"destination appeared during write: {display_path}"
                    ) from exc
                except BaseException as primary_error:
                    if installed:
                        try:
                            cleanup = _quarantine_owned_entry(
                                self.fd,
                                destination,
                                display_path,
                                staged_identity,
                                staged_fd,
                            )
                            _require_owned_cleanup(cleanup, display_path)
                        except (OSError, UnsafeWritePathError) as cleanup_error:
                            primary_error.add_note(f"installed cleanup failed: {cleanup_error}")
                    raise
                cleanup = _quarantine_owned_entry(
                    self.fd,
                    staged_name,
                    display_path,
                    staged_identity,
                    staged_fd,
                )
                staged_name = None
                _require_owned_cleanup(cleanup, display_path)
            else:
                if expected_fd is None:
                    raise OSError(errno.EBADF, "destination cleanup descriptor is missing")
                if _use_portable_overwrite():
                    raise OSError(
                        errno.ENOTSUP,
                        f"race-resistant atomic overwrite is unavailable for {display_path}",
                    )
                else:
                    exchanged = False
                    installed_identity: _EntryIdentity | None = None
                    displaced_identity: _EntryIdentity | None = None
                    try:
                        _exchange_entries(self.fd, staged_name, destination)
                        exchanged = True
                        installed_identity = _entry_identity(self.fd, destination, display_path)
                        displaced_identity = _entry_identity(self.fd, staged_name, display_path)
                        if installed_identity != staged_identity or displaced_identity != expected:
                            raise UnsafeWritePathError(
                                f"Unsafe operator output path '{display_path}': "
                                "exchange entries changed during atomic replacement"
                            )
                        self.verify()
                    except BaseException:
                        if exchanged:
                            try:
                                if (
                                    installed_identity is None
                                    or displaced_identity is None
                                    or _entry_identity(self.fd, destination, display_path)
                                    != installed_identity
                                    or _entry_identity(self.fd, staged_name, display_path)
                                    != displaced_identity
                                ):
                                    raise UnsafeWritePathError(
                                        f"Unsafe operator output path '{display_path}': "
                                        "exchange entries changed before rollback"
                                    )
                                _exchange_entries(self.fd, staged_name, destination)
                                if (
                                    _entry_identity(self.fd, destination, display_path)
                                    != displaced_identity
                                    or _entry_identity(self.fd, staged_name, display_path)
                                    != installed_identity
                                ):
                                    raise UnsafeWritePathError(
                                        f"Unsafe operator output path '{display_path}': "
                                        "rollback identities are not exact"
                                    )
                            except BaseException as rollback_error:
                                try:
                                    self._recover_trusted_destination(
                                        staged_name,
                                        destination,
                                        display_path,
                                        expected,
                                        staged_identity,
                                    )
                                except BaseException as recovery_error:
                                    raise OSError(
                                        errno.EIO,
                                        f"could not recover a trusted destination for {display_path}",
                                    ) from recovery_error
                                raise OSError(
                                    errno.EIO,
                                    f"could not roll back atomic write for {display_path}",
                                ) from rollback_error
                        raise
                    cleanup = _quarantine_owned_entry(
                        self.fd,
                        staged_name,
                        display_path,
                        expected,
                        expected_fd,
                    )
                    staged_name = None
                    _require_owned_cleanup(cleanup, display_path)
            staged_name = None
            os.fsync(self.fd)
        finally:
            active_error = sys.exception()
            deferred_errors: list[BaseException] = []
            if staged_name is not None and staged_identity is not None:
                try:
                    if staged_fd is None:
                        raise OSError(errno.EBADF, "staged cleanup descriptor is missing")
                    cleanup = _quarantine_owned_entry(
                        self.fd,
                        staged_name,
                        display_path,
                        staged_identity,
                        staged_fd,
                    )
                    staged_name = None
                    _require_owned_cleanup(cleanup, display_path)
                except (OSError, UnsafeWritePathError) as cleanup_error:
                    deferred_errors.append(cleanup_error)
            for label, file_fd in (("staged", staged_fd), ("destination", expected_fd)):
                if file_fd is None:
                    continue
                try:
                    os.close(file_fd)
                except OSError as close_error:
                    deferred_errors.append(
                        OSError(
                            close_error.errno, f"{label} descriptor close failed: {close_error}"
                        )
                    )
            if deferred_errors:
                if active_error is not None:
                    for deferred_error in deferred_errors:
                        active_error.add_note(f"cleanup failed: {deferred_error}")
                else:
                    raise deferred_errors[0]

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
