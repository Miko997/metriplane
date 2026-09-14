# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Descriptor-relative reads beneath explicitly authorized directories."""

from __future__ import annotations

import errno
import os
import stat
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Never, Self


class UnsafeReadPathError(ValueError):
    """Raised when a read path escapes authority or changes during use."""


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


@dataclass(frozen=True, slots=True)
class _FileLink:
    parent_fd: int
    name: str
    file_fd: int
    display_path: Path


def _identity(result: os.stat_result) -> _EntryIdentity:
    return _EntryIdentity(result.st_dev, result.st_ino, result.st_mode)


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if os.name != "posix" or any(not hasattr(os, name) for name in required):
        raise OSError(
            errno.ENOTSUP,
            "secure Operator reads require POSIX directory handles and O_NOFOLLOW",
        )
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _component_name(name: str) -> str:
    if not name or "\x00" in name or Path(name).parts != (name,) or name in {".", ".."}:
        raise UnsafeReadPathError(f"unsafe read path component: {name!r}")
    return name


def _relative_parts(relative_path: Path) -> tuple[str, ...]:
    path = Path(relative_path)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise UnsafeReadPathError(f"unsafe relative read path: {path}")
    return tuple(_component_name(part) for part in path.parts)


def _absolute_path(path: str | Path) -> Path:
    expanded = os.path.expanduser(os.fspath(path))
    return Path(os.path.abspath(expanded))


def _translate_component_error(path: Path, exc: OSError) -> Never:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise UnsafeReadPathError(
            f"unsafe read path '{path}': symbolic links are not allowed"
        ) from exc
    raise exc


def _assert_directory_chain(links: Sequence[_DirectoryLink]) -> None:
    for link in links:
        try:
            visible = os.stat(link.name, dir_fd=link.parent_fd, follow_symlinks=False)
            opened = os.fstat(link.child_fd)
        except FileNotFoundError as exc:
            raise UnsafeReadPathError(
                f"unsafe read path '{link.display_path}': directory changed during read"
            ) from exc
        except OSError as exc:
            _translate_component_error(link.display_path, exc)
        if (
            stat.S_ISLNK(visible.st_mode)
            or not stat.S_ISDIR(visible.st_mode)
            or _identity(visible) != _identity(opened)
        ):
            raise UnsafeReadPathError(
                f"unsafe read path '{link.display_path}': directory changed during read"
            )


def _assert_file_link(link: _FileLink) -> None:
    try:
        visible = os.stat(link.name, dir_fd=link.parent_fd, follow_symlinks=False)
        opened = os.fstat(link.file_fd)
    except FileNotFoundError as exc:
        raise UnsafeReadPathError(
            f"unsafe read path '{link.display_path}': file changed during read"
        ) from exc
    except OSError as exc:
        _translate_component_error(link.display_path, exc)
    if (
        stat.S_ISLNK(visible.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or _identity(visible) != _identity(opened)
    ):
        raise UnsafeReadPathError(
            f"unsafe read path '{link.display_path}': file changed during read"
        )


def _open_child_directory(parent_fd: int, name: str, display_path: Path) -> int:
    component = _component_name(name)
    try:
        child_fd = os.open(component, _directory_flags(), dir_fd=parent_fd)
    except OSError as exc:
        _translate_component_error(display_path, exc)
    opened = os.fstat(child_fd)
    if not stat.S_ISDIR(opened.st_mode):
        os.close(child_fd)
        raise UnsafeReadPathError(f"unsafe read path '{display_path}': expected a directory")
    return child_fd


def _open_absolute_directory(path: Path) -> PinnedDirectory:
    absolute = _absolute_path(path)
    if not absolute.is_absolute():
        raise UnsafeReadPathError(f"read authority must be absolute: {path}")

    root_fd = os.open(os.sep, _directory_flags())
    fds = [root_fd]
    links: list[_DirectoryLink] = []
    current_fd = root_fd
    display_path = Path(os.sep)
    try:
        for part in absolute.parts[1:]:
            display_path /= part
            child_fd = _open_child_directory(current_fd, part, display_path)
            fds.append(child_fd)
            links.append(_DirectoryLink(current_fd, part, child_fd, display_path))
            current_fd = child_fd
        directory = PinnedDirectory(
            display_path=absolute,
            _fds=fds,
            _links=tuple(links),
        )
        directory.verify()
        return directory
    except BaseException:
        while fds:
            os.close(fds.pop())
        raise


def _select_authority(
    allowed_roots: Iterable[Path], requested: str | Path
) -> tuple[Path, Path, Path]:
    requested_path = _absolute_path(requested)
    matches: list[tuple[int, Path, Path]] = []
    for root in allowed_roots:
        root_path = _absolute_path(root)
        try:
            relative = requested_path.relative_to(root_path)
        except ValueError:
            continue
        try:
            authority_path = root_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise UnsafeReadPathError(
                f"read authority '{root_path}' cannot be resolved safely"
            ) from exc
        matches.append((len(root_path.parts), authority_path, relative))
    if not matches:
        raise UnsafeReadPathError(
            f"read path '{requested_path}' is outside the authorized directories"
        )
    _specificity, root_path, relative = max(matches, key=lambda item: item[0])
    return root_path, relative, requested_path


@dataclass(slots=True)
class PinnedFile:
    """A regular file pinned to a retained descriptor-relative inode chain."""

    display_path: Path
    relative_path: Path
    _parent: PinnedDirectory
    _directory_fds: list[int]
    _links: tuple[_DirectoryLink, ...]
    _file_link: _FileLink
    _owns_parent: bool = False
    _closed: bool = False

    @property
    def name(self) -> str:
        return self.display_path.name

    def __str__(self) -> str:
        return str(self.display_path)

    @property
    def owns_authority(self) -> bool:
        """Whether closing this file also closes its pinned directory authority."""
        return self._owns_parent

    def __enter__(self) -> Self:
        self.verify()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def verify(self) -> None:
        if self._closed:
            raise OSError(errno.EBADF, f"pinned file is closed: {self.display_path}")
        self._parent.verify()
        _assert_directory_chain(self._links)
        _assert_file_link(self._file_link)

    def stat(self) -> os.stat_result:
        self.verify()
        result = os.fstat(self._file_link.file_fd)
        self.verify()
        return result

    def iter_bytes(self, chunk_size: int = 65536) -> Iterator[bytes]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.verify()
        offset = 0
        try:
            while True:
                chunk = os.pread(self._file_link.file_fd, chunk_size, offset)
                if not chunk:
                    break
                offset += len(chunk)
                yield chunk
        finally:
            self.verify()

    def read_bytes(self) -> bytes:
        return b"".join(self.iter_bytes())

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self.read_bytes().decode(encoding, errors)

    def duplicate_fd(self) -> int:
        """Return a pinned duplicate suitable for explicit ownership transfer."""
        self.verify()
        duplicate = os.dup(self._file_link.file_fd)
        try:
            os.set_inheritable(duplicate, False)
            if _identity(os.fstat(duplicate)) != _identity(os.fstat(self._file_link.file_fd)):
                raise UnsafeReadPathError(
                    f"unsafe read path '{self.display_path}': duplicate identity changed"
                )
            self.verify()
            return duplicate
        except BaseException:
            os.close(duplicate)
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._file_link.file_fd)
        except OSError:
            pass
        while self._directory_fds:
            try:
                os.close(self._directory_fds.pop())
            except OSError:
                pass
        if self._owns_parent:
            self._parent.close()


@dataclass(slots=True)
class PinnedDirectory:
    """An authorized directory with every traversed inode retained."""

    display_path: Path
    _fds: list[int]
    _links: tuple[_DirectoryLink, ...]
    _parent: PinnedDirectory | None = None
    _owns_parent: bool = False
    _artifacts: dict[Path, PinnedFile] = field(default_factory=dict)
    _closed: bool = False

    @property
    def fd(self) -> int:
        if self._closed or not self._fds:
            raise OSError(errno.EBADF, f"pinned directory is closed: {self.display_path}")
        return self._fds[-1]

    def __str__(self) -> str:
        return str(self.display_path)

    def __enter__(self) -> Self:
        self.verify()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def verify(self) -> None:
        if self._closed:
            raise OSError(errno.EBADF, f"pinned directory is closed: {self.display_path}")
        if self._parent is not None:
            self._parent.verify()
        _assert_directory_chain(self._links)

    def stat(self) -> os.stat_result:
        self.verify()
        result = os.fstat(self.fd)
        self.verify()
        return result

    def listdir(self) -> list[str]:
        self.verify()
        names = os.listdir(self.fd)
        self.verify()
        return names

    def open_directory(self, relative_path: Path) -> PinnedDirectory:
        parts = _relative_parts(relative_path)
        self.verify()
        fds: list[int] = []
        links: list[_DirectoryLink] = []
        current_fd = self.fd
        display_path = self.display_path
        try:
            for part in parts:
                display_path /= part
                child_fd = _open_child_directory(current_fd, part, display_path)
                fds.append(child_fd)
                links.append(_DirectoryLink(current_fd, part, child_fd, display_path))
                current_fd = child_fd
            child = PinnedDirectory(
                display_path=display_path,
                _fds=fds,
                _links=tuple(links),
                _parent=self,
            )
            child.verify()
            return child
        except BaseException:
            while fds:
                os.close(fds.pop())
            raise

    def open_file(self, relative_path: Path) -> PinnedFile:
        relative = Path(relative_path)
        cached = self._artifacts.get(relative)
        if cached is not None:
            cached.verify()
            return cached

        parts = _relative_parts(relative)
        self.verify()
        directory_fds: list[int] = []
        links: list[_DirectoryLink] = []
        current_fd = self.fd
        display_path = self.display_path
        file_fd: int | None = None
        try:
            for part in parts[:-1]:
                display_path /= part
                child_fd = _open_child_directory(current_fd, part, display_path)
                directory_fds.append(child_fd)
                links.append(_DirectoryLink(current_fd, part, child_fd, display_path))
                current_fd = child_fd

            name = _component_name(parts[-1])
            display_path /= name
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            try:
                file_fd = os.open(name, flags, dir_fd=current_fd)
            except OSError as exc:
                _translate_component_error(display_path, exc)
            assert file_fd is not None
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise UnsafeReadPathError(
                    f"unsafe read path '{display_path}': expected a regular file"
                )
            artifact = PinnedFile(
                display_path=display_path,
                relative_path=relative,
                _parent=self,
                _directory_fds=directory_fds,
                _links=tuple(links),
                _file_link=_FileLink(current_fd, name, file_fd, display_path),
            )
            artifact.verify()
            self._artifacts[relative] = artifact
            return artifact
        except BaseException:
            if file_fd is not None:
                os.close(file_fd)
            while directory_fds:
                os.close(directory_fds.pop())
            raise

    def find_file(self, names: Sequence[str]) -> PinnedFile | None:
        for name in names:
            try:
                return self.open_file(Path(name))
            except (FileNotFoundError, UnsafeReadPathError):
                continue
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for artifact in self._artifacts.values():
            artifact.close()
        self._artifacts.clear()
        while self._fds:
            try:
                os.close(self._fds.pop())
            except OSError:
                pass
        if self._owns_parent and self._parent is not None:
            self._parent.close()


def pin_directory(allowed_roots: Iterable[Path], requested: str | Path) -> PinnedDirectory:
    """Acquire a pinned directory; the caller owns and must close the result."""
    root_path, relative, requested_path = _select_authority(allowed_roots, requested)
    root = _open_absolute_directory(root_path)
    if not relative.parts:
        return root

    child: PinnedDirectory | None = None
    try:
        child = root.open_directory(relative)
        child.display_path = requested_path
        child._owns_parent = True
        return child
    except BaseException:
        root.close()
        raise


@contextmanager
def open_pinned_directory(
    allowed_roots: Iterable[Path], requested: str | Path
) -> Iterator[PinnedDirectory]:
    """Open a requested directory beneath one allowed root without following links."""
    directory = pin_directory(allowed_roots, requested)
    try:
        yield directory
    finally:
        directory.close()


def pin_file(allowed_roots: Iterable[Path], requested: str | Path) -> PinnedFile:
    """Acquire a pinned regular file; the caller owns and must close the result."""
    root_path, relative, requested_path = _select_authority(allowed_roots, requested)
    root = _open_absolute_directory(root_path)
    try:
        artifact = root.open_file(relative)
        artifact.display_path = requested_path
        artifact._owns_parent = True
        return artifact
    except BaseException:
        root.close()
        raise


@contextmanager
def open_pinned_file(allowed_roots: Iterable[Path], requested: str | Path) -> Iterator[PinnedFile]:
    """Open a requested regular file beneath one allowed root and retain its chain."""
    artifact = pin_file(allowed_roots, requested)
    try:
        yield artifact
    finally:
        artifact.close()


def inherited_fd_path(file_fd: int) -> str:
    """Return a child-process path for a descriptor or fail closed."""
    if os.name != "posix":
        raise OSError(errno.ENOTSUP, "descriptor inheritance is unsupported on this platform")
    if sys.platform.startswith("linux"):
        return f"/proc/self/fd/{file_fd}"
    if sys.platform == "darwin":
        return f"/dev/fd/{file_fd}"
    raise OSError(errno.ENOTSUP, "descriptor-backed report input is unsupported")
