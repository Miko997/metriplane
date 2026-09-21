# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from pathlib import Path
import struct
from typing import IO
import zipfile

import pytest

import metriplane.archive_safety as archive_safety
from metriplane.archive_safety import ResourceLimits, copy_relative_regular_file, stage_path
from metriplane.runner.safe_reads import PinnedDirectory, PinnedFile, UnsafeReadPathError


def _zip(path: Path, rows: list[tuple[str, bytes]], *, method: int = zipfile.ZIP_STORED) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in rows:
            archive.writestr(name, data, compress_type=method)


def _tree(root: Path, rows: list[tuple[str, bytes]]) -> None:
    root.mkdir()
    for name, data in rows:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class _UnseekableZipSink:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> int:
        self.data.extend(data)
        return len(data)

    def tell(self) -> int:
        return len(self.data)

    def flush(self) -> None:
        pass


@pytest.mark.parametrize("kind", ["zip", "directory"])
@pytest.mark.parametrize(
    ("entry_count", "passes"),
    [(1, True), (2, True), (3, False)],
)
def test_identical_entry_budget_n_minus_one_n_n_plus_one(
    tmp_path: Path,
    kind: str,
    entry_count: int,
    passes: bool,
) -> None:
    rows = [(f"f{index}.txt", b"x") for index in range(entry_count)]
    source = tmp_path / ("source.zip" if kind == "zip" else "source")
    (_zip if kind == "zip" else _tree)(source, rows)
    destination = tmp_path / "staged"
    limits = ResourceLimits(max_entries=2, max_file_bytes=8, max_total_bytes=8)

    if passes:
        stage_path(source, destination, limits=limits)
        assert sorted(path.name for path in destination.iterdir()) == [name for name, _ in rows]
    else:
        with pytest.raises(ValueError, match="too many entries"):
            stage_path(source, destination, limits=limits)
        assert not destination.exists()


def test_zip_entry_budget_is_checked_before_zipfile_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.zip"
    _zip(source, [("a", b"a"), ("b", b"b"), ("c", b"c")])

    def unexpected_parser(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ZipFile parser ran before the entry-count preflight")

    monkeypatch.setattr(archive_safety.zipfile, "ZipFile", unexpected_parser)
    with pytest.raises(ValueError, match="too many entries"):
        stage_path(
            source,
            tmp_path / "staged",
            limits=ResourceLimits(max_entries=2, max_file_bytes=2, max_total_bytes=2),
        )

    forged_count = tmp_path / "forged-count.zip"
    raw = bytearray(source.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<H", raw, end + 8, 1)
    struct.pack_into("<H", raw, end + 10, 1)
    forged_count.write_bytes(raw)
    with pytest.raises(ValueError, match="entry count differs"):
        stage_path(
            forged_count,
            tmp_path / "forged-count-stage",
            limits=ResourceLimits(max_entries=4, max_file_bytes=4, max_total_bytes=4),
        )


@pytest.mark.parametrize("kind", ["zip", "directory"])
def test_implicit_and_explicit_directories_share_the_same_entry_budget(
    tmp_path: Path,
    kind: str,
) -> None:
    source = tmp_path / ("source.zip" if kind == "zip" else "source")
    rows = [("nested/payload", b"x")]
    (_zip if kind == "zip" else _tree)(source, rows)
    limits = ResourceLimits(max_entries=2, max_file_bytes=8, max_total_bytes=8)

    stage_path(source, tmp_path / "staged", limits=limits)

    assert (tmp_path / "staged" / "nested" / "payload").read_bytes() == b"x"


@pytest.mark.parametrize("kind", ["zip", "directory"])
@pytest.mark.parametrize(
    ("size", "passes"),
    [(3, True), (4, True), (5, False)],
)
def test_identical_file_budget_n_minus_one_n_n_plus_one(
    tmp_path: Path,
    kind: str,
    size: int,
    passes: bool,
) -> None:
    source = tmp_path / ("source.zip" if kind == "zip" else "source")
    (_zip if kind == "zip" else _tree)(source, [("payload", b"x" * size)])
    destination = tmp_path / "staged"
    limits = ResourceLimits(max_entries=4, max_file_bytes=4, max_total_bytes=4)

    if passes:
        stage_path(source, destination, limits=limits)
        assert (destination / "payload").read_bytes() == b"x" * size
    else:
        with pytest.raises(ValueError, match="too large"):
            stage_path(source, destination, limits=limits)
        assert not destination.exists()


@pytest.mark.parametrize("kind", ["zip", "directory"])
def test_case_collisions_fail_closed_without_partial_output(
    tmp_path: Path,
    kind: str,
) -> None:
    source = tmp_path / ("source.zip" if kind == "zip" else "source")
    (_zip if kind == "zip" else _tree)(source, [("A.txt", b"a"), ("a.txt", b"b")])
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="case-colliding"):
        stage_path(source, destination)

    assert not destination.exists()


def test_zip_file_directory_collision_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    _zip(source, [("node", b"file"), ("node/child", b"child")])

    with pytest.raises(ValueError, match="file/directory collision"):
        stage_path(source, tmp_path / "staged")


def test_zip_method_crc_and_trailing_junk_are_rejected(tmp_path: Path) -> None:
    unsupported = tmp_path / "unsupported.zip"
    _zip(unsupported, [("payload", b"data")], method=zipfile.ZIP_BZIP2)
    with pytest.raises(ValueError, match="unsupported ZIP compression method"):
        stage_path(unsupported, tmp_path / "unsupported-stage")

    corrupt = tmp_path / "corrupt.zip"
    _zip(corrupt, [("payload", b"data")])
    raw = bytearray(corrupt.read_bytes())
    offset = raw.index(b"data")
    raw[offset] ^= 1
    corrupt.write_bytes(raw)
    with pytest.raises(ValueError, match="CRC/content validation"):
        stage_path(corrupt, tmp_path / "corrupt-stage")

    trailing = tmp_path / "trailing.zip"
    _zip(trailing, [("payload", b"data")])
    trailing.write_bytes(trailing.read_bytes() + b"junk")
    with pytest.raises(ValueError, match="trailing junk"):
        stage_path(trailing, tmp_path / "trailing-stage")

    forged_end = tmp_path / "forged-end.zip"
    _zip(forged_end, [("payload", b"data")])
    forged_end.write_bytes(forged_end.read_bytes() + b"PK\x05\x06" + b"\x00" * 18)
    with pytest.raises(ValueError, match="trailing junk"):
        stage_path(forged_end, tmp_path / "forged-end-stage")

    self_consistent_end = tmp_path / "self-consistent-end.zip"
    _zip(self_consistent_end, [("payload", b"data")])
    valid_bytes = self_consistent_end.read_bytes()
    self_consistent_end.write_bytes(
        valid_bytes
        + struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            0,
            0,
            0,
            len(valid_bytes),
            0,
        )
    )
    with pytest.raises(ValueError, match="trailing junk"):
        stage_path(self_consistent_end, tmp_path / "self-consistent-end-stage")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _zip(first, [("original", b"first")])
    _zip(second, [("replacement", b"x" * (archive_safety._MAX_EOCD_BYTES + 4096))])
    prefix = first.read_bytes()
    replacement = bytearray(second.read_bytes())
    central = replacement.index(b"PK\x01\x02")
    local_offset = struct.unpack_from("<L", replacement, central + 42)[0]
    struct.pack_into("<L", replacement, central + 42, local_offset + len(prefix))
    end = replacement.rfind(b"PK\x05\x06")
    central_offset = struct.unpack_from("<L", replacement, end + 16)[0]
    struct.pack_into("<L", replacement, end + 16, central_offset + len(prefix))
    concatenated = tmp_path / "concatenated.zip"
    concatenated.write_bytes(prefix + replacement)
    with pytest.raises(
        ValueError,
        match="trailing junk|unreferenced prefix|concatenated archive",
    ):
        stage_path(concatenated, tmp_path / "concatenated-stage")

    retained_original = tmp_path / "retained-original.zip"
    appended_update = tmp_path / "appended-update.zip"
    _zip(retained_original, [("original", b"first")])
    _zip(
        appended_update,
        [("replacement", b"x" * (archive_safety._MAX_EOCD_BYTES + 4096))],
    )
    original = retained_original.read_bytes()
    update = appended_update.read_bytes()
    original_central = original.index(b"PK\x01\x02")
    original_end = original.rfind(b"PK\x05\x06")
    update_central = update.index(b"PK\x01\x02")
    update_end = update.rfind(b"PK\x05\x06")
    update_local = update[:update_central]
    update_central_record = bytearray(update[update_central:update_end])
    update_local_offset = struct.unpack_from("<L", update_central_record, 42)[0]
    struct.pack_into("<L", update_central_record, 42, update_local_offset + len(original))
    final_central = original[original_central:original_end] + update_central_record
    final_central_offset = len(original) + len(update_local)
    final_end = struct.pack(
        "<4s4H2LH",
        b"PK\x05\x06",
        0,
        0,
        2,
        2,
        len(final_central),
        final_central_offset,
        0,
    )
    retained_and_appended = tmp_path / "retained-and-appended.zip"
    retained_and_appended.write_bytes(original + update_local + final_central + final_end)
    assert len(retained_and_appended.read_bytes()) - original_end > archive_safety._MAX_EOCD_BYTES
    with pytest.raises(ValueError, match="trailing junk|unreferenced bytes"):
        stage_path(retained_and_appended, tmp_path / "retained-and-appended-stage")

    descriptor_payload = bytes.fromhex("ac0a7ad5")
    sink = _UnseekableZipSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("payload", descriptor_payload)
    signed_descriptor = tmp_path / "signed-descriptor.zip"
    signed_descriptor.write_bytes(sink.data)
    stage_path(signed_descriptor, tmp_path / "signed-descriptor-stage")
    assert (tmp_path / "signed-descriptor-stage" / "payload").read_bytes() == descriptor_payload

    unsigned_bytes = bytearray(sink.data)
    descriptor = unsigned_bytes.index(b"PK\x07\x08")
    del unsigned_bytes[descriptor : descriptor + 4]
    end = unsigned_bytes.rfind(b"PK\x05\x06")
    central_offset = struct.unpack_from("<L", unsigned_bytes, end + 16)[0]
    struct.pack_into("<L", unsigned_bytes, end + 16, central_offset - 4)
    unsigned_descriptor = tmp_path / "unsigned-descriptor.zip"
    unsigned_descriptor.write_bytes(unsigned_bytes)
    stage_path(unsigned_descriptor, tmp_path / "unsigned-descriptor-stage")
    assert (tmp_path / "unsigned-descriptor-stage" / "payload").read_bytes() == descriptor_payload

    embedded_end_payload = (
        b"A" * 10
        + struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            1,
            1,
            47,
            0,
            0,
        )
        + b"B" * 100
    )
    embedded_end = tmp_path / "embedded-end.zip"
    _zip(embedded_end, [("payload", embedded_end_payload)])
    stage_path(embedded_end, tmp_path / "embedded-end-stage")
    assert (tmp_path / "embedded-end-stage" / "payload").read_bytes() == embedded_end_payload


def test_zip_raw_envelope_and_unreferenced_gap_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    _zip(source, [("payload", b"x")])
    original = source.read_bytes()
    central_offset = original.index(b"PK\x01\x02")

    def with_gap(size: int) -> bytes:
        result = bytearray(original[:central_offset] + b"\x00" * size + original[central_offset:])
        end = result.rfind(b"PK\x05\x06")
        struct.pack_into("<L", result, end + 16, central_offset + size)
        return bytes(result)

    small_gap = tmp_path / "small-gap.zip"
    small_gap.write_bytes(with_gap(4096))
    with pytest.raises(ValueError, match="unreferenced bytes"):
        stage_path(small_gap, tmp_path / "small-gap-stage")

    large_gap = tmp_path / "large-gap.zip"
    large_gap.write_bytes(with_gap(8 * 1024 * 1024))
    with pytest.raises(ValueError, match="raw archive limit"):
        stage_path(
            large_gap,
            tmp_path / "large-gap-stage",
            limits=ResourceLimits(max_entries=2, max_file_bytes=2, max_total_bytes=2),
        )


@pytest.mark.parametrize("name", ["./dot", "a/./b", "a//b"])
def test_zip_lexically_ambiguous_paths_are_rejected(tmp_path: Path, name: str) -> None:
    source = tmp_path / "source.zip"
    _zip(source, [(name, b"data")])

    with pytest.raises(ValueError, match="unsafe zip path"):
        stage_path(source, tmp_path / "staged")


def test_directory_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "target"
    target.write_text("secret", encoding="utf-8")
    (source / "payload").symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        stage_path(source, tmp_path / "staged")


def test_source_replacement_during_copy_is_rejected_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _tree(source, [("payload", b"original")])
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    original = PinnedFile.iter_bytes

    def replace_after_read(self: PinnedFile, chunk_size: int = 65536):
        yield from original(self, chunk_size)
        os.replace(replacement, source / "payload")

    monkeypatch.setattr(PinnedFile, "iter_bytes", replace_after_read)
    destination = tmp_path / "staged"

    with pytest.raises(UnsafeReadPathError, match="changed during read"):
        stage_path(source, destination)

    assert not destination.exists()


@pytest.mark.parametrize("operation", ["stage", "copy"])
def test_same_inode_growth_is_bounded_and_rejected_before_another_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    source = tmp_path / "source"
    _tree(source, [("payload", b"data")])
    original = PinnedFile.iter_bytes

    def grow_during_read(self: PinnedFile, chunk_size: int = 65536):
        iterator = original(self, chunk_size)
        first = next(iterator)
        yield first
        with (source / "payload").open("ab") as handle:
            handle.write(b"growth")
        yield b"g"
        raise AssertionError("bounded reader requested bytes after detecting growth")

    monkeypatch.setattr(PinnedFile, "iter_bytes", grow_during_read)
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="grew during staged copy"):
        if operation == "stage":
            stage_path(source, destination)
        else:
            destination.mkdir()
            copy_relative_regular_file(source, "payload", destination, "payload")

    assert not (destination / "payload").exists()


def test_source_replacement_between_inventory_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _tree(source, [("payload", b"original")])
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    original = PinnedDirectory.open_file

    def replace_before_open(self: PinnedDirectory, relative_path: Path) -> PinnedFile:
        os.replace(replacement, source / "payload")
        return original(self, relative_path)

    monkeypatch.setattr(PinnedDirectory, "open_file", replace_before_open)
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="changed before staged copy"):
        stage_path(source, destination)

    assert not destination.exists()


def test_archive_replacement_before_pin_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.zip"
    replacement = tmp_path / "replacement.zip"
    _zip(source, [("payload", b"original")])
    _zip(replacement, [("payload", b"replacement")])
    original = os.lstat

    def replace_after_lstat(path: os.PathLike[str] | str) -> os.stat_result:
        result = original(path)
        if Path(path) == source:
            os.replace(replacement, source)
        return result

    monkeypatch.setattr(os, "lstat", replace_after_lstat)
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="archive changed before staged copy"):
        stage_path(source, destination)

    assert not destination.exists()


def test_same_inode_archive_mutation_during_staging_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.zip"
    _zip(source, [("payload", b"data")])
    original = archive_safety._zip_members

    def mutate_after_inventory(
        archive: zipfile.ZipFile,
        limits: ResourceLimits,
        *,
        expected_size: int | None = None,
    ) -> list[tuple[zipfile.ZipInfo, object, bool]]:
        members = original(archive, limits, expected_size=expected_size)
        with source.open("ab") as handle:
            handle.write(b"junk")
        return members

    monkeypatch.setattr(archive_safety, "_zip_members", mutate_after_inventory)
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="archive changed during staged copy"):
        stage_path(source, destination)

    assert not destination.exists()

    monkeypatch.setattr(archive_safety, "_zip_members", original)
    source_after_snapshot = tmp_path / "source-after-snapshot.zip"
    _zip(source_after_snapshot, [("payload", b"data")])
    mutated = bytearray(source_after_snapshot.read_bytes())
    mutated[mutated.index(b"data")] ^= 1
    original_snapshot = archive_safety._copy_bounded_snapshot

    def mutate_after_snapshot(
        artifact: PinnedFile,
        snapshot: IO[bytes],
        *,
        expected_size: int,
        label: str,
    ) -> bytes:
        digest = original_snapshot(
            artifact,
            snapshot,
            expected_size=expected_size,
            label=label,
        )
        source_after_snapshot.write_bytes(mutated)
        return digest

    monkeypatch.setattr(archive_safety, "_copy_bounded_snapshot", mutate_after_snapshot)
    snapshot_destination = tmp_path / "snapshot-staged"
    with pytest.raises(ValueError, match="archive changed during staged copy"):
        stage_path(source_after_snapshot, snapshot_destination)
    assert not snapshot_destination.exists()


def test_directory_replacement_before_pin_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    replacement = tmp_path / "replacement"
    displaced = tmp_path / "displaced"
    _tree(source, [("payload", b"original")])
    _tree(replacement, [("payload", b"replacement")])
    original = os.lstat
    replaced = False

    def replace_after_lstat(
        path: os.PathLike[str] | str,
        *,
        dir_fd: int | None = None,
    ) -> os.stat_result:
        nonlocal replaced
        result = original(path, dir_fd=dir_fd)
        if dir_fd is None and Path(path) == source and not replaced:
            source.rename(displaced)
            replacement.rename(source)
            replaced = True
        return result

    monkeypatch.setattr(os, "lstat", replace_after_lstat)
    destination = tmp_path / "staged"

    with pytest.raises(ValueError, match="directory changed before staged copy"):
        stage_path(source, destination)

    assert not destination.exists()


def test_archive_and_directory_stage_to_identical_bytes(tmp_path: Path) -> None:
    rows = [("a.txt", b"a"), ("nested/b.txt", b"b")]
    archive = tmp_path / "source.zip"
    directory = tmp_path / "source"
    _zip(archive, rows, method=zipfile.ZIP_DEFLATED)
    _tree(directory, rows)
    archive_stage = stage_path(archive, tmp_path / "archive-stage")
    directory_stage = stage_path(directory, tmp_path / "directory-stage")

    for name, data in rows:
        assert (archive_stage / name).read_bytes() == data
        assert (directory_stage / name).read_bytes() == data


def test_existing_destination_is_never_reused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _tree(source, [("payload", b"data")])
    destination = tmp_path / "staged"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        stage_path(source, destination)

    assert sentinel.read_text(encoding="utf-8") == "keep"
