# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Bounded, race-resistant staging for ZIP archives and directory inputs."""

from __future__ import annotations

import hashlib
import os
import stat
import struct
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, TemporaryFile
from typing import IO

from metriplane.runner.safe_reads import (
    PinnedDirectory,
    PinnedFile,
    open_pinned_directory,
    open_pinned_file,
)
from metriplane.runner.safe_writes import open_secure_directory


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_entries: int = 1024
    max_file_bytes: int = 128 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_compression_ratio: int = 1000

    def __post_init__(self) -> None:
        if (
            min(
                self.max_entries,
                self.max_file_bytes,
                self.max_total_bytes,
                self.max_compression_ratio,
            )
            <= 0
        ):
            raise ValueError("archive resource limits must be positive")


DEFAULT_LIMITS = ResourceLimits()
_ALLOWED_ZIP_METHODS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_STRUCT = struct.Struct("<4s4H2LH")
_MAX_EOCD_BYTES = 22 + 65535
_LOCAL_FILE_HEADER_SIGNATURE = b"PK\x03\x04"
_LOCAL_FILE_HEADER_STRUCT = struct.Struct("<4s5H3L2H")
_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x01\x02"
_CENTRAL_DIRECTORY_HEADER_STRUCT = struct.Struct("<4s4B4HL2L5H2L")
_DATA_DESCRIPTOR_SIGNATURE = b"PK\x07\x08"
_MAX_ZIP_LOCAL_METADATA_BYTES = _LOCAL_FILE_HEADER_STRUCT.size + 2 * 65535
_MAX_ZIP_CENTRAL_METADATA_BYTES = _CENTRAL_DIRECTORY_HEADER_STRUCT.size + 3 * 65535
_MAX_ZIP_ENTRY_OVERHEAD_BYTES = _MAX_ZIP_LOCAL_METADATA_BYTES + _MAX_ZIP_CENTRAL_METADATA_BYTES + 24


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe staged path: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"unsafe staged path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"unsafe staged path: {value!r}")
    return path


class _Inventory:
    def __init__(self, limits: ResourceLimits) -> None:
        self.limits = limits
        self.entries = 0
        self.total_bytes = 0
        self._paths: dict[str, tuple[str, bool, bool]] = {}

    def _count_entry(self, path: PurePosixPath, *, is_dir: bool, size: int) -> None:
        self.entries += 1
        if self.entries > self.limits.max_entries:
            raise ValueError(
                f"input has too many entries: {self.entries} (maximum {self.limits.max_entries})"
            )
        if size < 0 or size > self.limits.max_file_bytes:
            raise ValueError(f"input file is too large: {path.as_posix()} ({size} bytes)")
        if not is_dir:
            self.total_bytes += size
            if self.total_bytes > self.limits.max_total_bytes:
                raise ValueError(f"input expands beyond {self.limits.max_total_bytes} bytes")

    def add(self, path: PurePosixPath, *, is_dir: bool, size: int) -> None:
        text = path.as_posix()
        folded = text.casefold()
        for index in range(1, len(path.parts)):
            parent_path = PurePosixPath(*path.parts[:index])
            parent_text = parent_path.as_posix()
            parent = parent_text.casefold()
            parent_entry = self._paths.get(parent)
            if parent_entry is not None and not parent_entry[1]:
                raise ValueError(
                    f"file/directory collision in input: {parent_entry[0]!r} and {text!r}"
                )
            if parent_entry is not None and parent_entry[0] != parent_text:
                raise ValueError(
                    "case-colliding input entries are not supported: "
                    f"{parent_entry[0]!r} and {parent_text!r}"
                )
            if parent_entry is None:
                self._count_entry(parent_path, is_dir=True, size=0)
                self._paths[parent] = (parent_text, True, False)

        previous = self._paths.get(folded)
        if previous is not None:
            previous_text, previous_is_dir, previous_declared = previous
            if previous_text != text:
                raise ValueError(
                    "case-colliding input entries are not supported: "
                    f"{previous_text!r} and {text!r}"
                )
            if previous_is_dir != is_dir:
                raise ValueError(
                    f"file/directory collision in input: {previous_text!r} and {text!r}"
                )
            if is_dir and not previous_declared:
                self._paths[folded] = (text, True, True)
                return
            raise ValueError(f"duplicate input entry: {text}")
        if not is_dir:
            prefix = folded + "/"
            child = next(
                (
                    raw
                    for key, (raw, _kind, _declared) in self._paths.items()
                    if key.startswith(prefix)
                ),
                None,
            )
            if child is not None:
                raise ValueError(f"file/directory collision in input: {text!r} and {child!r}")
        self._count_entry(path, is_dir=is_dir, size=size)
        self._paths[folded] = (text, is_dir, True)


def _create_directory(destination: Path, relative: PurePosixPath) -> None:
    path = Path(destination.name, *relative.parts)
    with open_secure_directory(destination.parent, path, create=True) as directory:
        directory.verify()


def _atomic_write(destination: Path, relative: PurePosixPath, data: bytes) -> str:
    parent = Path(destination.name, *relative.parts[:-1])
    with open_secure_directory(destination.parent, parent, create=True) as directory:
        directory.atomic_write(relative.name, data, overwrite=False)
    expected = hashlib.sha256(data).hexdigest()
    staged_path = destination / Path(*relative.parts)
    with open_pinned_file([destination], staged_path) as staged:
        actual = hashlib.sha256()
        for chunk in staged.iter_bytes():
            actual.update(chunk)
        if actual.hexdigest() != expected:
            raise ValueError(f"staged copy hash mismatch: {relative.as_posix()}")
        staged.verify()
    return expected


def _read_bounded_file(artifact: PinnedFile, *, expected_size: int, label: str) -> bytes:
    data = bytearray()
    for chunk in artifact.iter_bytes():
        if len(data) + len(chunk) > expected_size:
            raise ValueError(f"input file grew during staged copy: {label}")
        data.extend(chunk)
    if len(data) != expected_size:
        raise ValueError(f"input file size changed during staged copy: {label}")
    return bytes(data)


def _hash_bounded_file(artifact: PinnedFile, *, expected_size: int, label: str) -> bytes:
    digest = hashlib.sha256()
    total = 0
    for chunk in artifact.iter_bytes():
        total += len(chunk)
        if total > expected_size:
            raise ValueError(f"input file grew during hash: {label}")
        digest.update(chunk)
    if total != expected_size:
        raise ValueError(f"input file size changed during hash: {label}")
    return digest.digest()


def _copy_bounded_snapshot(
    artifact: PinnedFile,
    destination: IO[bytes],
    *,
    expected_size: int,
    label: str,
) -> bytes:
    digest = hashlib.sha256()
    total = 0
    for chunk in artifact.iter_bytes():
        total += len(chunk)
        if total > expected_size:
            raise ValueError(f"input file grew during snapshot: {label}")
        destination.write(chunk)
        digest.update(chunk)
    if total != expected_size:
        raise ValueError(f"input file size changed during snapshot: {label}")
    destination.flush()
    destination.seek(0)
    return digest.digest()


def _bounded_directory_names(directory: PinnedDirectory, inventory: _Inventory) -> list[str]:
    remaining = inventory.limits.max_entries - inventory.entries
    names: list[str] = []
    directory.verify()
    with os.scandir(directory.fd) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > remaining:
                raise ValueError(
                    f"input has too many entries: more than {inventory.limits.max_entries}"
                )
    directory.verify()
    names.sort()
    return names


def _directory_entries(
    directory: PinnedDirectory,
    prefix: PurePosixPath | None,
    inventory: _Inventory,
) -> Iterator[tuple[PurePosixPath, bytes | None]]:
    for name in _bounded_directory_names(directory, inventory):
        if not name or "/" in name or "\\" in name or "\x00" in name or name in {".", ".."}:
            raise ValueError(f"unsafe directory entry: {name!r}")
        relative = PurePosixPath(name) if prefix is None else prefix / name
        visible = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if stat.S_ISLNK(visible.st_mode):
            raise ValueError(f"directory symlink is not allowed: {relative.as_posix()}")
        if stat.S_ISDIR(visible.st_mode):
            inventory.add(relative, is_dir=True, size=0)
            child = directory.open_directory(Path(name))
            try:
                opened = child.stat()
                if (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino):
                    raise ValueError(f"directory changed during inventory: {relative.as_posix()}")
                yield relative, None
                yield from _directory_entries(child, relative, inventory)
                child.verify()
            finally:
                child.close()
            continue
        if not stat.S_ISREG(visible.st_mode):
            raise ValueError(f"directory entry is not a regular file: {relative.as_posix()}")
        inventory.add(relative, is_dir=False, size=visible.st_size)
        artifact = directory.open_file(Path(name))
        before = artifact.stat()
        if (visible.st_dev, visible.st_ino, visible.st_mode) != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
        ):
            raise ValueError(f"directory file changed before staged copy: {relative.as_posix()}")
        data = _read_bounded_file(
            artifact,
            expected_size=before.st_size,
            label=relative.as_posix(),
        )
        after = artifact.stat()
        stable_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        stable_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if stable_before != stable_after or len(data) != before.st_size:
            raise ValueError(f"directory file changed during staged copy: {relative.as_posix()}")
        yield relative, data
    directory.verify()


def stage_directory(
    source: str | Path,
    destination: str | Path,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
    _expected_source: os.stat_result | None = None,
) -> Path:
    source_path = Path(source).absolute()
    destination_path = Path(destination).absolute()
    visible_source = _expected_source if _expected_source is not None else os.lstat(source_path)
    if stat.S_ISLNK(visible_source.st_mode) or not stat.S_ISDIR(visible_source.st_mode):
        raise ValueError(f"source is not a real directory: {source_path}")
    destination_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        inventory = _Inventory(limits)
        with open_pinned_directory([source_path.parent], source_path) as pinned:
            opened_source = pinned.stat()
            if (visible_source.st_dev, visible_source.st_ino, visible_source.st_mode) != (
                opened_source.st_dev,
                opened_source.st_ino,
                opened_source.st_mode,
            ):
                raise ValueError(f"source directory changed before staged copy: {source_path}")
            for relative, data in _directory_entries(pinned, None, inventory):
                if data is None:
                    _create_directory(destination_path, relative)
                else:
                    _atomic_write(destination_path, relative, data)
            pinned.verify()
    except BaseException:
        import shutil

        shutil.rmtree(destination_path, ignore_errors=True)
        raise
    return destination_path


def _max_zip_source_bytes(limits: ResourceLimits) -> int:
    return (
        limits.max_total_bytes
        + limits.max_entries * _MAX_ZIP_ENTRY_OVERHEAD_BYTES
        + _MAX_EOCD_BYTES
    )


def _preflight_central_directory(
    stream: IO[bytes],
    *,
    start: int,
    end: int,
    expected_entries: int,
    limits: ResourceLimits,
) -> None:
    cursor = start
    entries = 0
    while cursor < end:
        if entries >= limits.max_entries:
            raise ValueError(f"input has too many entries: more than {limits.max_entries}")
        if end - cursor < _CENTRAL_DIRECTORY_HEADER_STRUCT.size:
            raise ValueError("ZIP central directory record is truncated")
        stream.seek(cursor)
        record = stream.read(_CENTRAL_DIRECTORY_HEADER_STRUCT.size)
        if len(record) != _CENTRAL_DIRECTORY_HEADER_STRUCT.size:
            raise ValueError("ZIP central directory ended during preflight")
        fields = _CENTRAL_DIRECTORY_HEADER_STRUCT.unpack(record)
        if fields[0] != _CENTRAL_DIRECTORY_SIGNATURE:
            raise ValueError("ZIP central directory has unreferenced or invalid bytes")
        filename_bytes, extra_bytes, comment_bytes = fields[12:15]
        record_size = (
            _CENTRAL_DIRECTORY_HEADER_STRUCT.size + filename_bytes + extra_bytes + comment_bytes
        )
        if cursor + record_size > end:
            raise ValueError("ZIP central directory record exceeds its declared boundary")
        cursor += record_size
        entries += 1
    if cursor != end or entries != expected_entries:
        raise ValueError("ZIP central-directory entry count differs from its end record")


def _preflight_zip_stream(
    stream: IO[bytes],
    limits: ResourceLimits,
    *,
    expected_size: int | None = None,
) -> tuple[int, int, int]:
    if not stream.seekable():
        raise ValueError("ZIP source must be a seekable regular file")
    position = stream.tell()
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        if expected_size is not None and size != expected_size:
            raise ValueError("source archive changed before ZIP preflight")
        maximum = _max_zip_source_bytes(limits)
        if size > maximum:
            raise ValueError(f"ZIP source exceeds raw archive limit: {size} > {maximum}")
        tail_size = min(size, _MAX_EOCD_BYTES)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
        if len(tail) != tail_size:
            raise ValueError("ZIP source ended during end-record preflight")

        search_end = len(tail)
        while True:
            index = tail.rfind(_EOCD_SIGNATURE, 0, search_end)
            if index < 0:
                break
            search_end = index
            if index + _EOCD_STRUCT.size > len(tail):
                continue
            (
                _signature,
                disk_number,
                central_disk,
                disk_entries,
                total_entries,
                central_size,
                central_offset,
                comment_bytes,
            ) = _EOCD_STRUCT.unpack_from(tail, index)
            absolute_index = size - tail_size + index
            if not (
                disk_number == 0
                and central_disk == 0
                and disk_entries == total_entries
                and central_offset + central_size == absolute_index
                and absolute_index + _EOCD_STRUCT.size + comment_bytes == size
                and (
                    total_entries > 0
                    or (central_offset == 0 and central_size == 0 and absolute_index == 0)
                )
            ):
                continue
            if total_entries > limits.max_entries:
                raise ValueError(
                    f"input has too many entries: {total_entries} (maximum {limits.max_entries})"
                )
            minimum_central_size = total_entries * 46
            maximum_central_size = total_entries * _MAX_ZIP_CENTRAL_METADATA_BYTES
            if not minimum_central_size <= central_size <= maximum_central_size:
                raise ValueError("ZIP central directory has an invalid bounded size")
            _preflight_central_directory(
                stream,
                start=central_offset,
                end=absolute_index,
                expected_entries=total_entries,
                limits=limits,
            )
            return size, total_entries, central_offset
        raise ValueError("ZIP has trailing junk or an invalid end-of-central-directory record")
    finally:
        stream.seek(position)


def _require_no_trailing_zip_bytes(
    archive: zipfile.ZipFile,
    limits: ResourceLimits,
    *,
    expected_size: int | None = None,
) -> None:
    stream = archive.fp
    if stream is None:
        raise ValueError("ZIP source must be a seekable regular file")
    _size, total_entries, central_offset = _preflight_zip_stream(
        stream,
        limits,
        expected_size=expected_size,
    )
    if total_entries == len(archive.infolist()) and central_offset == archive.start_dir:
        return
    raise ValueError("ZIP has trailing junk or an invalid end-of-central-directory record")


def _data_descriptor_end(
    stream: IO[bytes],
    member: zipfile.ZipInfo,
    offset: int,
    *,
    zip64: bool,
) -> int:
    size_format = "Q" if zip64 else "L"
    values = struct.Struct(f"<L{size_format}{size_format}")
    stream.seek(offset)
    unsigned_payload = stream.read(values.size)
    expected = (member.CRC, member.compress_size, member.file_size)
    if len(unsigned_payload) == values.size and values.unpack(unsigned_payload) == expected:
        return offset + values.size
    if unsigned_payload[:4] != _DATA_DESCRIPTOR_SIGNATURE:
        raise ValueError(f"ZIP data descriptor differs from central directory: {member.filename}")
    stream.seek(offset + 4)
    signed_payload = stream.read(values.size)
    if len(signed_payload) != values.size:
        raise ValueError(f"ZIP data descriptor is truncated: {member.filename}")
    if values.unpack(signed_payload) != expected:
        raise ValueError(f"ZIP data descriptor differs from central directory: {member.filename}")
    return offset + 4 + values.size


def _require_canonical_local_records(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
) -> None:
    stream = archive.fp
    if stream is None:
        raise ValueError("ZIP source must be a seekable regular file")
    position = stream.tell()
    cursor = 0
    try:
        for member in sorted(members, key=lambda item: item.header_offset):
            if member.header_offset != cursor:
                raise ValueError("ZIP has unreferenced bytes between local records")
            stream.seek(cursor)
            header = stream.read(_LOCAL_FILE_HEADER_STRUCT.size)
            if len(header) != _LOCAL_FILE_HEADER_STRUCT.size:
                raise ValueError(f"ZIP local header is truncated: {member.filename}")
            (
                signature,
                _extract_version,
                flag_bits,
                method,
                _modified_time,
                _modified_date,
                crc,
                compressed_size,
                file_size,
                filename_bytes,
                extra_bytes,
            ) = _LOCAL_FILE_HEADER_STRUCT.unpack(header)
            if signature != _LOCAL_FILE_HEADER_SIGNATURE:
                raise ValueError(f"ZIP local header is invalid: {member.filename}")
            if flag_bits != member.flag_bits or method != member.compress_type:
                raise ValueError(
                    f"ZIP local header differs from central directory: {member.filename}"
                )
            uses_descriptor = bool(flag_bits & 0x08)
            zip64 = compressed_size == 0xFFFFFFFF or file_size == 0xFFFFFFFF
            if not uses_descriptor and (
                crc != member.CRC
                or compressed_size not in {member.compress_size, 0xFFFFFFFF}
                or file_size not in {member.file_size, 0xFFFFFFFF}
            ):
                raise ValueError(
                    f"ZIP local sizes differ from central directory: {member.filename}"
                )
            data_offset = cursor + _LOCAL_FILE_HEADER_STRUCT.size + filename_bytes + extra_bytes
            cursor = data_offset + member.compress_size
            if uses_descriptor:
                cursor = _data_descriptor_end(stream, member, cursor, zip64=zip64)
        if cursor != archive.start_dir:
            raise ValueError("ZIP has unreferenced bytes before its central directory")
    finally:
        stream.seek(position)


def _zip_members(
    archive: zipfile.ZipFile,
    limits: ResourceLimits,
    *,
    expected_size: int | None = None,
) -> list[tuple[zipfile.ZipInfo, PurePosixPath, bool]]:
    _require_no_trailing_zip_bytes(archive, limits, expected_size=expected_size)
    members = archive.infolist()
    if members and min(member.header_offset for member in members) != 0:
        raise ValueError("ZIP has an unreferenced prefix or concatenated archive")
    _require_canonical_local_records(archive, members)
    inventory = _Inventory(limits)
    result: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
    for member in members:
        raw_name = member.filename
        is_dir = member.is_dir()
        normalized = raw_name[:-1] if is_dir and raw_name.endswith("/") else raw_name
        try:
            relative = _safe_relative_path(normalized)
        except ValueError as exc:
            raise ValueError(f"unsafe zip path: {raw_name}") from exc
        mode_type = (member.external_attr >> 16) & 0o170000
        if mode_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ValueError(f"ZIP special entry is not supported: {relative.as_posix()}")
        if (mode_type == stat.S_IFDIR) != is_dir and mode_type != 0:
            raise ValueError(f"ZIP entry type is inconsistent: {relative.as_posix()}")
        if member.flag_bits & 0x1:
            raise ValueError(f"encrypted ZIP member is not supported: {relative.as_posix()}")
        if not is_dir and member.compress_type not in _ALLOWED_ZIP_METHODS:
            raise ValueError(
                f"unsupported ZIP compression method {member.compress_type}: {relative.as_posix()}"
            )
        try:
            inventory.add(relative, is_dir=is_dir, size=0 if is_dir else member.file_size)
        except ValueError as exc:
            duplicate_prefix = "duplicate input entry: "
            if str(exc).startswith(duplicate_prefix):
                raise ValueError(
                    f"duplicate zip member: {str(exc)[len(duplicate_prefix) :]}"
                ) from exc
            raise
        if not is_dir:
            if member.file_size and member.compress_size == 0:
                raise ValueError(f"invalid compressed size for ZIP member: {relative.as_posix()}")
            if (
                member.compress_size
                and member.file_size / member.compress_size > limits.max_compression_ratio
            ):
                raise ValueError(f"ZIP compression ratio is too high: {relative.as_posix()}")
        result.append((member, relative, is_dir))
    return result


def stage_zip_archive(
    archive: zipfile.ZipFile,
    destination: str | Path,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
    _expected_size: int | None = None,
) -> Path:
    destination_path = Path(destination).absolute()
    destination_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        members = _zip_members(archive, limits, expected_size=_expected_size)
        for member, relative, is_dir in members:
            if is_dir:
                _create_directory(destination_path, relative)
                continue
            try:
                with archive.open(member, "r") as source:
                    data = source.read(limits.max_file_bytes + 1)
                    if source.read(1):
                        raise ValueError(f"ZIP member exceeds declared size: {relative.as_posix()}")
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile, OSError) as exc:
                raise ValueError(
                    f"ZIP member failed CRC/content validation: {relative.as_posix()}"
                ) from exc
            if len(data) != member.file_size or len(data) > limits.max_file_bytes:
                raise ValueError(f"ZIP member size differs: {relative.as_posix()}")
            _atomic_write(destination_path, relative, data)
    except BaseException:
        import shutil

        shutil.rmtree(destination_path, ignore_errors=True)
        raise
    return destination_path


def stage_path(
    source: str | Path,
    destination: str | Path,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Path:
    source_path = Path(source).absolute()
    visible = os.lstat(source_path)
    if stat.S_ISLNK(visible.st_mode):
        raise ValueError(f"source must not be a symlink: {source_path}")
    if stat.S_ISDIR(visible.st_mode):
        return stage_directory(
            source_path,
            destination,
            limits=limits,
            _expected_source=visible,
        )
    if not stat.S_ISREG(visible.st_mode):
        raise ValueError(f"source is not a ZIP file or directory: {source_path}")
    with open_pinned_file([source_path.parent], source_path) as pinned:
        opened = pinned.stat()
        if (visible.st_dev, visible.st_ino, visible.st_mode) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_mode,
        ):
            raise ValueError(f"source archive changed before staged copy: {source_path}")
        maximum = _max_zip_source_bytes(limits)
        if opened.st_size > maximum:
            raise ValueError(f"ZIP source exceeds raw archive limit: {opened.st_size} > {maximum}")
        with TemporaryFile(mode="w+b") as snapshot:
            digest_before = _copy_bounded_snapshot(
                pinned,
                snapshot,
                expected_size=opened.st_size,
                label=os.fspath(source_path),
            )
            _preflight_zip_stream(snapshot, limits, expected_size=opened.st_size)
            with zipfile.ZipFile(snapshot) as archive:
                staged = stage_zip_archive(
                    archive,
                    destination,
                    limits=limits,
                    _expected_size=opened.st_size,
                )
        try:
            closed = pinned.stat()
            try:
                digest_after = _hash_bounded_file(
                    pinned,
                    expected_size=opened.st_size,
                    label=os.fspath(source_path),
                )
            except ValueError as exc:
                raise ValueError(
                    f"source archive changed during staged copy: {source_path}"
                ) from exc
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
                digest_before,
            ) != (
                closed.st_dev,
                closed.st_ino,
                closed.st_size,
                closed.st_mtime_ns,
                closed.st_ctime_ns,
                digest_after,
            ):
                raise ValueError(f"source archive changed during staged copy: {source_path}")
            pinned.verify()
        except BaseException:
            import shutil

            shutil.rmtree(staged, ignore_errors=True)
            raise
        return staged


@contextmanager
def staged_path(
    source: str | Path,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Iterator[Path]:
    with TemporaryDirectory(prefix="metriplane-staged-") as temporary:
        root = Path(temporary) / "payload"
        stage_path(source, root, limits=limits)
        yield root


def copy_relative_regular_file(
    source_root: str | Path,
    source_relative: str | PurePosixPath,
    destination_root: str | Path,
    destination_relative: str | PurePosixPath,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> str:
    source = _safe_relative_path(str(source_relative))
    destination = _safe_relative_path(str(destination_relative))
    source_root_path = Path(source_root).absolute()
    with open_pinned_directory([source_root_path.parent], source_root_path) as directory:
        artifact = directory.open_file(Path(*source.parts))
        before = artifact.stat()
        if before.st_size > limits.max_file_bytes:
            raise ValueError(
                f"input file is too large: {source.as_posix()} ({before.st_size} bytes)"
            )
        data = _read_bounded_file(
            artifact,
            expected_size=before.st_size,
            label=source.as_posix(),
        )
        after = artifact.stat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(data) != before.st_size:
            raise ValueError(f"source file changed during staged copy: {source.as_posix()}")
        _atomic_write(Path(destination_root).absolute(), destination, data)
        directory.verify()
    return hashlib.sha256(data).hexdigest()
