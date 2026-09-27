# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Fail-closed acquisition and adapter-normalization isolation."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import os
import platform
import resource
import secrets
import selectors
import signal
import stat
import struct
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Final, cast

from metriplane.strict_parsing import StrictJsonError, load_json_stream


class AdapterSandboxError(RuntimeError):
    """An adapter request failed a security boundary or isolated execution."""


@dataclass(frozen=True, order=True)
class AcquisitionIdentity:
    repository: str
    revision: str
    artifact: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 300.0
    max_output_bytes: int = 1_048_576
    max_open_files: int = 256
    max_processes: int = 1
    max_cpu_seconds: int = 300
    max_file_bytes: int = 1_073_741_824
    max_memory_bytes: int = 4_294_967_296
    max_output_files: int = 4096
    max_output_tree_bytes: int = 1_073_741_824
    max_output_depth: int = 32

    def __post_init__(self) -> None:
        values = (
            self.timeout_seconds,
            self.max_output_bytes,
            self.max_open_files - 2,
            self.max_processes,
            self.max_cpu_seconds,
            self.max_file_bytes,
            self.max_memory_bytes,
            self.max_output_files,
            self.max_output_tree_bytes,
            self.max_output_depth,
        )
        if any(value <= 0 for value in values) or self.max_processes != 1:
            raise ValueError("adapter sandbox limits must be positive and finite")


@dataclass(frozen=True)
class SandboxResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


@dataclass(frozen=True)
class _ArchiveMember:
    name: str
    parts: tuple[str, ...]
    kind: str
    size: int
    data_offset: int


class _VerifiedAcquisition:
    """Open identities retained from verification through sandbox mounting."""

    __slots__ = (
        "artifact_fd",
        "artifact_parts",
        "identity",
        "source_fd",
    )

    def __init__(
        self,
        *,
        identity: AcquisitionIdentity,
        source_fd: int,
        artifact_fd: int,
        artifact_parts: tuple[str, ...],
    ) -> None:
        self.identity = identity
        self.source_fd = source_fd
        self.artifact_fd = artifact_fd
        self.artifact_parts = artifact_parts

    def close(self) -> None:
        for name in ("artifact_fd", "source_fd"):
            fd = getattr(self, name)
            if fd >= 0:
                os.close(fd)
                setattr(self, name, -1)

    def __enter__(self) -> _VerifiedAcquisition:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_BWRAP: Final = Path("/usr/bin/bwrap")
_PYTHON_LAUNCHER: Final = Path("/usr/bin/python3")
_RENAME_NOREPLACE: Final = 1
_F_ADD_SEALS: Final = 1033
_F_GET_SEALS: Final = 1034
_REQUIRED_SEALS: Final = 1 | 2 | 4 | 8
_FIXED_ENVIRONMENT: Final = {
    "HOME": "/tmp/empty-home",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCODING": "utf-8",
    "TZ": "UTC",
}


def _fd_path(fd: int) -> str:
    return f"/proc/self/fd/{fd}"


def require_allowlisted_acquisition(
    requested: AcquisitionIdentity,
    allowlist: Sequence[AcquisitionIdentity],
) -> None:
    """Require one exact, unique source identity before any provider access."""
    if sum(entry == requested for entry in allowlist) != 1:
        raise AdapterSandboxError("acquisition source is not exactly allowlisted")


def load_acquisition_allowlist(path: str | Path) -> tuple[AcquisitionIdentity, ...]:
    """Load the strict reviewed allowlist used by the normalization command."""
    source = Path(path)
    try:
        fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise AdapterSandboxError("acquisition allowlist must be a regular file")
            value = load_json_stream(handle, label="acquisition allowlist")
    except (OSError, UnicodeError, StrictJsonError) as exc:
        raise AdapterSandboxError(f"acquisition allowlist is unreadable: {exc}") from exc
    if not isinstance(value, list) or not value:
        raise AdapterSandboxError("acquisition allowlist must be a non-empty array")
    expected = {"repository", "revision", "artifact", "size", "sha256"}
    entries: list[AcquisitionIdentity] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != expected:
            raise AdapterSandboxError("acquisition allowlist entry has unknown or missing fields")
        if (
            not all(isinstance(item[key], str) and item[key] for key in expected - {"size"})
            or not isinstance(item["size"], int)
            or isinstance(item["size"], bool)
            or item["size"] < 0
            or len(item["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["sha256"])
        ):
            raise AdapterSandboxError("acquisition allowlist entry is malformed")
        entries.append(AcquisitionIdentity(**item))
    if len(set(entries)) != len(entries):
        raise AdapterSandboxError("acquisition allowlist contains a duplicate identity")
    return tuple(entries)


def verify_allowlisted_acquisition(
    requested: AcquisitionIdentity,
    allowlist: Sequence[AcquisitionIdentity],
    source_root: str | Path,
) -> None:
    """Match the declaration and verify the exact local artifact bytes."""
    with _open_verified_acquisition(requested, allowlist, source_root):
        pass


def _open_verified_acquisition(
    requested: AcquisitionIdentity,
    allowlist: Sequence[AcquisitionIdentity],
    source_root: str | Path,
) -> _VerifiedAcquisition:
    """Verify exact bytes while retaining source and artifact descriptors."""
    require_allowlisted_acquisition(requested, allowlist)
    parts = PurePosixPath(requested.artifact).parts
    if not parts or parts[0] in {"/", ".", ".."} or any(part in {"", ".", ".."} for part in parts):
        raise AdapterSandboxError("acquisition artifact path is not a safe relative path")
    root_fd = _open_directory(Path(source_root), label="acquisition source root")
    directory_fd = root_fd
    opened_directories: list[int] = []
    artifact_fd = -1
    snapshot_fd = -1
    try:
        for component in parts[:-1]:
            directory_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            opened_directories.append(directory_fd)
        artifact_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        metadata = os.fstat(artifact_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != requested.size:
            raise AdapterSandboxError("acquisition artifact type or size differs from allowlist")
        snapshot_fd = _create_memfd("metriplane-verified-artifact", allow_sealing=True)
        digest = hashlib.sha256()
        while chunk := os.read(artifact_fd, 1024 * 1024):
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(snapshot_fd, view)
                view = view[written:]
        if digest.hexdigest() != requested.sha256:
            raise AdapterSandboxError("acquisition artifact digest differs from allowlist")
        fcntl.fcntl(snapshot_fd, _F_ADD_SEALS, _REQUIRED_SEALS)
        if fcntl.fcntl(snapshot_fd, _F_GET_SEALS) != _REQUIRED_SEALS:
            raise AdapterSandboxError("verified artifact snapshot seals are incomplete")
        os.lseek(snapshot_fd, 0, os.SEEK_SET)
        os.close(artifact_fd)
        artifact_fd = snapshot_fd
        snapshot_fd = -1
        retained = _VerifiedAcquisition(
            identity=requested,
            source_fd=root_fd,
            artifact_fd=artifact_fd,
            artifact_parts=tuple(parts),
        )
        root_fd = artifact_fd = -1
        return retained
    except OSError as exc:
        raise AdapterSandboxError(f"acquisition artifact cannot be verified: {exc}") from exc
    finally:
        if artifact_fd >= 0:
            os.close(artifact_fd)
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
        for fd in reversed(opened_directories):
            os.close(fd)
        if root_fd >= 0:
            os.close(root_fd)


def credential_empty_environment() -> dict[str, str]:
    """Return the entire immutable environment admitted to normalization."""
    return dict(_FIXED_ENVIRONMENT)


def _archive_byte_limit(limits: SandboxLimits) -> int:
    """Bound one untrusted tar stream including finite per-member overhead."""
    return limits.max_output_tree_bytes + (limits.max_output_files + 1) * 1024 + 10240


def _limit_child(limits: SandboxLimits) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))
    resource.setrlimit(resource.RLIMIT_CPU, (limits.max_cpu_seconds, limits.max_cpu_seconds))
    archive_limit = _archive_byte_limit(limits)
    resource.setrlimit(resource.RLIMIT_FSIZE, (archive_limit, archive_limit))
    resource.setrlimit(resource.RLIMIT_AS, (limits.max_memory_bytes, limits.max_memory_bytes))


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _bounded_communicate(
    process: subprocess.Popen[bytes], limits: SandboxLimits, archive_fd: int
) -> tuple[bytes, bytes]:
    selector = selectors.DefaultSelector()
    if process.stdout is None or process.stderr is None:
        raise AdapterSandboxError("sandbox output pipe was not created")
    streams = (process.stdout, process.stderr)
    stderr = bytearray()
    archive_size = 0
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + limits.timeout_seconds
        failure: AdapterSandboxError | None = None
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = AdapterSandboxError("adapter sandbox timed out")
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                stream = cast(IO[bytes], key.fileobj)
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream)
                    continue
                if stream is process.stdout:
                    if archive_size + len(chunk) > _archive_byte_limit(limits):
                        failure = AdapterSandboxError("adapter output archive quota exceeded")
                        break
                    archive_size += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(archive_fd, view)
                        view = view[written:]
                else:
                    if len(stderr) + len(chunk) > limits.max_output_bytes:
                        failure = AdapterSandboxError("adapter sandbox output quota exceeded")
                        break
                    stderr.extend(chunk)
            if failure is not None:
                break
        if failure is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                failure = AdapterSandboxError("adapter sandbox timed out")
        if failure is not None:
            _kill_and_reap(process)
            raise failure
    except BaseException:
        _kill_and_reap(process)
        raise
    finally:
        selector.close()
        for stream in streams:
            stream.close()
    return b"", bytes(stderr)


def _open_trusted_regular(path: Path, *, allow_launcher_symlink: bool = False) -> int:
    """Open a root-controlled executable and retain its identity through exec."""
    try:
        lexical = os.lstat(path)
        if stat.S_ISLNK(lexical.st_mode):
            if not allow_launcher_symlink:
                raise AdapterSandboxError(f"trusted executable must not be a symlink: {path}")
            target = path.resolve(strict=True)
            if target.parent != Path("/usr/bin") or not target.name.startswith("python3."):
                raise AdapterSandboxError("Python launcher resolves outside the trusted allowlist")
        else:
            target = path
        fd = os.open(target, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise AdapterSandboxError(f"cannot open trusted executable {path}: {exc}") from exc
    metadata = os.fstat(fd)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        os.close(fd)
        raise AdapterSandboxError(f"trusted executable ownership or mode is unsafe: {path}")
    return int(fd)


def _open_directory(path: Path, *, label: str) -> int:
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError as exc:
        raise AdapterSandboxError(f"{label} must be a real accessible directory: {exc}") from exc


def _require_current_directory_identity(path: Path, fd: int, *, label: str) -> None:
    """Require the requested pathname to still identify the retained directory."""
    try:
        retained = os.fstat(fd)
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise AdapterSandboxError(f"{label} identity cannot be verified: {exc}") from exc
    if not stat.S_ISDIR(current.st_mode) or (retained.st_dev, retained.st_ino) != (
        current.st_dev,
        current.st_ino,
    ):
        raise AdapterSandboxError(f"{label} identity changed")


def _directory_is_within(ancestor_fd: int, descendant_fd: int) -> bool:
    """Compare directory ancestry using only retained descriptors."""
    ancestor = os.fstat(ancestor_fd)
    current_fd = os.dup(descendant_fd)
    try:
        for _ in range(4096):
            current = os.fstat(current_fd)
            if (current.st_dev, current.st_ino) == (ancestor.st_dev, ancestor.st_ino):
                return True
            parent_fd = os.open(
                "..",
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            parent = os.fstat(parent_fd)
            if (parent.st_dev, parent.st_ino) == (current.st_dev, current.st_ino):
                os.close(parent_fd)
                return False
            os.close(current_fd)
            current_fd = parent_fd
    except OSError as exc:
        raise AdapterSandboxError(f"adapter directory ancestry cannot be verified: {exc}") from exc
    finally:
        os.close(current_fd)
    raise AdapterSandboxError("adapter directory ancestry exceeds the finite verification bound")


def _create_seccomp_fd() -> int:
    """Create a classic-BPF filter that denies processes and sockets."""
    architecture = {
        "x86_64": (0xC000003E, (41, 56, 57, 58, 272, 308, 435)),
        "aarch64": (0xC00000B7, (97, 198, 220, 268, 435)),
    }.get(platform.machine())
    if architecture is None or not hasattr(os, "O_TMPFILE"):
        raise AdapterSandboxError("supported seccomp architecture is unavailable")
    audit_arch, syscall_numbers = architecture
    instructions = [
        struct.pack("<HBBI", 0x20, 0, 0, 4),
        struct.pack("<HBBI", 0x15, 1, 0, audit_arch),
        struct.pack("<HBBI", 0x06, 0, 0, 0x80000000),
        struct.pack("<HBBI", 0x20, 0, 0, 0),
    ]
    if platform.machine() == "x86_64":
        instructions.extend(
            (
                struct.pack("<HBBI", 0x45, 0, 1, 0x40000000),
                struct.pack("<HBBI", 0x06, 0, 0, 0x00050000 | errno.ENOSYS),
            )
        )
    for number in syscall_numbers:
        instructions.extend(
            (
                struct.pack("<HBBI", 0x15, 0, 1, number),
                struct.pack("<HBBI", 0x06, 0, 0, 0x00050000 | errno.EPERM),
            )
        )
    instructions.append(struct.pack("<HBBI", 0x06, 0, 0, 0x7FFF0000))
    try:
        fd = os.open("/tmp", os.O_RDWR | os.O_TMPFILE | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise AdapterSandboxError(f"anonymous seccomp storage is unavailable: {exc}") from exc
    try:
        os.write(fd, b"".join(instructions))
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except OSError:
        os.close(fd)
        raise


def _make_stage(parent_fd: int, output_name: str) -> tuple[str, int]:
    for _ in range(16):
        name = f".{output_name}.stage-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            try:
                return name, os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except OSError:
                os.rmdir(name, dir_fd=parent_fd)
                raise
        except FileExistsError:
            continue
    raise AdapterSandboxError("could not allocate a unique adapter staging directory")


def _remove_tree_at(
    parent_fd: int,
    name: str,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    """Remove only the retained staging directory without following links."""
    try:
        directory_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return
    try:
        opened = os.fstat(directory_fd)
        opened_identity = (opened.st_dev, opened.st_ino)
        if expected_identity is not None and opened_identity != expected_identity:
            return
        for entry in os.scandir(directory_fd):
            if entry.is_dir(follow_symlinks=False):
                _remove_tree_at(directory_fd, entry.name)
            else:
                os.unlink(entry.name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (current.st_dev, current.st_ino) == opened_identity:
        os.rmdir(name, dir_fd=parent_fd)


def _validate_output_inventory(stage_fd: int, limits: SandboxLimits) -> None:
    file_count = 0
    total_size = 0
    stack: list[tuple[int, int]] = [(os.dup(stage_fd), 0)]
    try:
        while stack:
            directory_fd, depth = stack.pop()
            try:
                if depth > limits.max_output_depth:
                    raise AdapterSandboxError("adapter output depth quota exceeded")
                for entry in os.scandir(directory_fd):
                    metadata = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode):
                        stack.append(
                            (
                                os.open(
                                    entry.name,
                                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                                    dir_fd=directory_fd,
                                ),
                                depth + 1,
                            )
                        )
                        continue
                    if not stat.S_ISREG(metadata.st_mode):
                        raise AdapterSandboxError("adapter output contains a link or special file")
                    file_count += 1
                    total_size += metadata.st_size
                    if file_count > limits.max_output_files:
                        raise AdapterSandboxError("adapter output file-count quota exceeded")
                    if total_size > limits.max_output_tree_bytes:
                        raise AdapterSandboxError("adapter output tree-size quota exceeded")
            finally:
                os.close(directory_fd)
    finally:
        for directory_fd, _ in stack:
            os.close(directory_fd)


def _create_memfd(name: str, *, allow_sealing: bool = False) -> int:
    """Create a Linux anonymous file and fail closed on unsupported hosts."""
    libc = ctypes.CDLL(None, use_errno=True)
    memfd_create = getattr(libc, "memfd_create", None)
    if memfd_create is None:
        raise AdapterSandboxError("anonymous in-memory storage is unavailable")
    memfd_create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    memfd_create.restype = ctypes.c_int
    flags = 1 | (2 if allow_sealing else 0)
    fd = memfd_create(name.encode("ascii"), flags)
    if fd < 0:
        error = ctypes.get_errno()
        raise AdapterSandboxError(
            f"anonymous in-memory storage is unavailable: {os.strerror(error)}"
        )
    return int(fd)


def _create_output_archive() -> int:
    """Create one anonymous parent-owned spool for the adapter output stream."""
    return _create_memfd("metriplane-adapter-output")


def _safe_archive_parts(name: str) -> tuple[str, ...]:
    if not name or "\\" in name or name.startswith("/"):
        raise AdapterSandboxError("adapter output archive contains an unsafe path")
    normalized = name[:-1] if name.endswith("/") else name
    parts = PurePosixPath(normalized).parts
    if not parts or normalized != "/".join(parts) or any(part in {"", ".", ".."} for part in parts):
        raise AdapterSandboxError("adapter output archive contains an unsafe path")
    return tuple(parts)


def _ustar_octal(field: bytes, *, label: str) -> int:
    stripped = field.rstrip(b"\0 ").lstrip(b" ")
    if not stripped or any(byte < ord("0") or byte > ord("7") for byte in stripped):
        raise AdapterSandboxError(f"adapter output USTAR {label} is malformed")
    return int(stripped, 8)


def _ustar_text(field: bytes, *, label: str) -> str:
    raw = field.split(b"\0", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterSandboxError(f"adapter output USTAR {label} is not UTF-8") from exc


def _scan_plain_ustar(archive_fd: int, limits: SandboxLimits) -> list[_ArchiveMember]:
    """Parse only fixed-width USTAR headers without trusting extension records."""
    archive_size = os.fstat(archive_fd).st_size
    if archive_size > _archive_byte_limit(limits) or archive_size % 512:
        raise AdapterSandboxError("adapter output archive size is invalid")
    offset = 0
    zero_blocks = 0
    members: list[_ArchiveMember] = []
    while offset < archive_size:
        header = os.pread(archive_fd, 512, offset)
        if len(header) != 512:
            raise AdapterSandboxError("adapter output USTAR header is truncated")
        if header == bytes(512):
            zero_blocks += 1
            offset += 512
            continue
        if zero_blocks:
            raise AdapterSandboxError("adapter output USTAR has data after its terminator")
        if header[257:263] != b"ustar\0" or header[263:265] != b"00":
            raise AdapterSandboxError("adapter output must be plain USTAR")
        expected_checksum = _ustar_octal(header[148:156], label="checksum")
        observed_checksum = sum(header[:148]) + 8 * ord(" ") + sum(header[156:])
        if expected_checksum != observed_checksum:
            raise AdapterSandboxError("adapter output USTAR checksum differs")
        typeflag = header[156:157]
        if typeflag not in {b"\0", b"0", b"5"}:
            raise AdapterSandboxError(
                "adapter output USTAR extension, link or special file rejected"
            )
        name = _ustar_text(header[:100], label="name")
        prefix = _ustar_text(header[345:500], label="prefix")
        full_name = f"{prefix}/{name}" if prefix else name
        parts = _safe_archive_parts(full_name)
        if len(parts) > limits.max_output_depth:
            raise AdapterSandboxError("adapter output depth quota exceeded")
        if len(members) >= limits.max_output_files:
            raise AdapterSandboxError("adapter output node-count quota exceeded")
        size = _ustar_octal(header[124:136], label="size")
        kind = "directory" if typeflag == b"5" else "file"
        if kind == "directory" and size:
            raise AdapterSandboxError("adapter output USTAR directory has data")
        data_offset = offset + 512
        padded_size = (size + 511) // 512 * 512
        next_offset = data_offset + padded_size
        if next_offset > archive_size:
            raise AdapterSandboxError("adapter output USTAR member is truncated")
        members.append(_ArchiveMember(full_name, parts, kind, size, data_offset))
        offset = next_offset
    if zero_blocks < 2:
        raise AdapterSandboxError("adapter output USTAR terminator is missing")
    return members


def _open_relative_directory(root_fd: int, parts: Sequence[str]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _extract_bounded_output_archive(
    archive_fd: int,
    destination_fd: int,
    limits: SandboxLimits,
) -> None:
    """Validate the stopped archive completely, then extract regular bytes only."""
    try:
        members = _scan_plain_ustar(archive_fd, limits)
        explicit: set[tuple[str, ...]] = set()
        nodes: dict[tuple[str, ...], str] = {}
        total_size = 0
        for member in members:
            parts = member.parts
            if parts in explicit:
                raise AdapterSandboxError("adapter output archive contains a duplicate path")
            explicit.add(parts)
            if member.kind == "file":
                if member.size > limits.max_file_bytes:
                    raise AdapterSandboxError("adapter output individual-file quota exceeded")
                total_size += member.size
                if total_size > limits.max_output_tree_bytes:
                    raise AdapterSandboxError("adapter output tree-size quota exceeded")
            if len(parts) > limits.max_output_depth:
                raise AdapterSandboxError("adapter output depth quota exceeded")
            for index in range(1, len(parts)):
                parent = parts[:index]
                if nodes.get(parent) == "file":
                    raise AdapterSandboxError("adapter output archive path crosses a file")
                nodes.setdefault(parent, "directory")
            prior = nodes.get(parts)
            if prior is not None and prior != member.kind:
                raise AdapterSandboxError("adapter output archive path type conflicts")
            if member.kind == "file" and any(
                len(path) > len(parts) and path[: len(parts)] == parts for path in nodes
            ):
                raise AdapterSandboxError("adapter output archive path crosses a file")
            nodes[parts] = member.kind
            if len(nodes) > limits.max_output_files:
                raise AdapterSandboxError("adapter output node-count quota exceeded")
        if not members:
            raise AdapterSandboxError("adapter output archive is empty")

        for parts, kind in sorted(nodes.items(), key=lambda item: (len(item[0]), item[0])):
            if kind == "directory":
                parent_fd = _open_relative_directory(destination_fd, parts[:-1])
                try:
                    os.mkdir(parts[-1], 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                finally:
                    os.close(parent_fd)
        for member in members:
            if member.kind != "file":
                continue
            parent_fd = _open_relative_directory(destination_fd, member.parts[:-1])
            output_fd = -1
            try:
                output_fd = os.open(
                    member.parts[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                remaining = member.size
                read_offset = member.data_offset
                while remaining:
                    chunk = os.pread(archive_fd, min(remaining, 1024 * 1024), read_offset)
                    if not chunk:
                        raise AdapterSandboxError("adapter output archive member is truncated")
                    remaining -= len(chunk)
                    read_offset += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(output_fd, view)
                        view = view[written:]
            finally:
                if output_fd >= 0:
                    os.close(output_fd)
                os.close(parent_fd)
    except OSError as exc:
        raise AdapterSandboxError(f"adapter output archive is invalid: {exc}") from exc


def _rename_noreplace(parent_fd: int, source: str, destination: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise AdapterSandboxError("atomic no-replace publication is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            parent_fd,
            os.fsencode(source),
            parent_fd,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
        != 0
    ):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise AdapterSandboxError("adapter output appeared before atomic publication")
        raise AdapterSandboxError(f"atomic adapter publication failed: {os.strerror(error)}")


def _validate_command(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv or tuple(argv[:1]) != (str(_PYTHON_LAUNCHER),):
        raise AdapterSandboxError("adapter command must use the exact trusted Python launcher")
    if any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise AdapterSandboxError("adapter command contains an invalid argument")
    if len(argv) < 2 or not argv[1].startswith("/input/"):
        raise AdapterSandboxError("adapter script must be an absolute path below /input")
    if ".." in Path(argv[1]).parts or "." in Path(argv[1]).parts:
        raise AdapterSandboxError("adapter script path traversal is prohibited")
    if "/output" in argv or argv.count("/dev/stdout") != 1:
        raise AdapterSandboxError("adapter command must declare the exact /dev/stdout target")
    return tuple(argv)


def run_normalization_sandbox(
    argv: Sequence[str],
    *,
    fixture_root: str | Path,
    output_root: str | Path,
    validate_output: Callable[[Path], None],
    limits: SandboxLimits = SandboxLimits(),
    verified_acquisition: _VerifiedAcquisition | None = None,
) -> SandboxResult:
    """Run one adapter and atomically publish only validated canonical output."""
    if os.name != "posix" or os.geteuid() == 0:
        raise AdapterSandboxError("adapter normalization requires an unprivileged POSIX process")
    command_argv = _validate_command(argv)
    fixture = Path(fixture_root).absolute()
    output = Path(output_root).absolute()
    if output.name in {"", ".", ".."}:
        raise AdapterSandboxError("adapter output requires a safe final name")
    output_parent = output.parent

    bwrap_fd = python_fd = fixture_fd = artifact_fd = -1
    parent_fd = stage_fd = seccomp_fd = -1
    archive_fd = -1
    stage_name: str | None = None
    stage_identity: tuple[int, int] | None = None
    renamed = False
    published = False
    started = time.monotonic()
    try:
        if verified_acquisition is None:
            fixture_fd = _open_directory(fixture, label="adapter fixture root")
        else:
            if verified_acquisition.source_fd < 0 or verified_acquisition.artifact_fd < 0:
                raise AdapterSandboxError("verified acquisition descriptors are closed")
            fixture_fd = os.dup(verified_acquisition.source_fd)
            artifact_fd = os.dup(verified_acquisition.artifact_fd)
            os.lseek(artifact_fd, 0, os.SEEK_SET)
        parent_fd = _open_directory(output_parent, label="adapter output parent")
        _require_current_directory_identity(fixture, fixture_fd, label="adapter fixture root")
        _require_current_directory_identity(output_parent, parent_fd, label="adapter output parent")
        if _directory_is_within(fixture_fd, parent_fd):
            raise AdapterSandboxError("adapter input and output must be disjoint")
        bwrap_fd = _open_trusted_regular(_BWRAP)
        python_fd = _open_trusted_regular(_PYTHON_LAUNCHER, allow_launcher_symlink=True)
        seccomp_fd = _create_seccomp_fd()
        try:
            os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AdapterSandboxError("adapter output must not already exist")
        stage_name, stage_fd = _make_stage(parent_fd, output.name)
        stage_metadata = os.fstat(stage_fd)
        stage_identity = (stage_metadata.st_dev, stage_metadata.st_ino)
        archive_fd = _create_output_archive()
        command = [
            _fd_path(bwrap_fd),
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup",
            "--unshare-net",
            "--disable-userns",
            "--seccomp",
            str(seccomp_fd),
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind-try",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/tmp/empty-home",
            "--dir",
            "/runtime",
            "--ro-bind-fd",
            str(fixture_fd),
            "/input",
            "--ro-bind-fd",
            str(python_fd),
            "/runtime/python",
            "--chdir",
            "/input",
        ]
        if verified_acquisition is not None:
            command.extend(
                (
                    "--ro-bind-data",
                    str(artifact_fd),
                    f"/input/{'/'.join(verified_acquisition.artifact_parts)}",
                )
            )
        for name, value in sorted(credential_empty_environment().items()):
            command.extend(("--setenv", name, value))
        command.extend(("--", "/runtime/python", *command_argv[1:]))
        process = subprocess.Popen(
            command,
            executable=_fd_path(bwrap_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={},
            start_new_session=True,
            pass_fds=tuple(
                fd
                for fd in (
                    bwrap_fd,
                    python_fd,
                    fixture_fd,
                    artifact_fd,
                    seccomp_fd,
                )
                if fd >= 0
            ),
            preexec_fn=lambda: _limit_child(limits),
        )
        try:
            stdout, stderr = _bounded_communicate(process, limits, archive_fd)
        except BaseException:
            _kill_and_reap(process)
            raise
        if process.returncode != 0:
            decoded = stderr.decode("utf-8", errors="replace")[-1024:].strip()
            detail = decoded.encode("unicode_escape").decode("ascii")
            suffix = f": {detail}" if detail else ""
            raise AdapterSandboxError(f"adapter sandbox exited {process.returncode}{suffix}")
        _extract_bounded_output_archive(archive_fd, stage_fd, limits)
        _validate_output_inventory(stage_fd, limits)
        validate_output(Path(_fd_path(stage_fd)))
        observed_stage = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
        if stage_identity != (
            observed_stage.st_dev,
            observed_stage.st_ino,
        ):
            raise AdapterSandboxError("adapter staging directory identity changed")
        _require_current_directory_identity(output_parent, parent_fd, label="adapter output parent")
        _rename_noreplace(parent_fd, stage_name, output.name)
        renamed = True
        observed_output = os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
        if stage_identity != (observed_output.st_dev, observed_output.st_ino):
            raise AdapterSandboxError("published adapter staging identity changed")
        _require_current_directory_identity(output_parent, parent_fd, label="adapter output parent")
        published = True
        return SandboxResult(
            argv=command_argv,
            returncode=0,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            elapsed_seconds=time.monotonic() - started,
        )
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if renamed and parent_fd >= 0 and not published:
            _remove_tree_at(parent_fd, output.name, expected_identity=stage_identity)
        elif stage_name is not None and parent_fd >= 0 and not published:
            _remove_tree_at(parent_fd, stage_name, expected_identity=stage_identity)
        for fd in (
            archive_fd,
            seccomp_fd,
            parent_fd,
            artifact_fd,
            fixture_fd,
            python_fd,
            bwrap_fd,
        ):
            if fd >= 0:
                os.close(fd)
