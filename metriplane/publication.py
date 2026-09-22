# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Durable, recoverable publication of immutable artifact generations.

The public destination remains a compatibility projection.  The authoritative
bytes live in an adjacent content-addressed generation selected by an atomic
pointer.  A durable journal makes every interrupted projection update either
recoverable to the previous destination or completable to the new generation.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


SCHEMA_VERSION = "metriplane.publication.v1"
MANIFEST_NAME = "publication-manifest.json"
_OWNER_ID = str(os.getuid()) if hasattr(os, "getuid") else "unsupported"
_STORE_NAME = f".metriplane-publication-{_OWNER_ID}"
_SAFE_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_ID = re.compile(r"[0-9a-f]{32}")


class PublicationError(ValueError):
    """Publication state is unsafe, ambiguous, or inconsistent."""


class PublicationCrash(RuntimeError):
    """Test-only interruption that deliberately leaves the journal for recovery."""


@dataclass(frozen=True, slots=True)
class PublicationTarget:
    staged: Path
    destination: Path


@dataclass(frozen=True, slots=True)
class PublicationResult:
    namespace: str
    generation_id: str
    manifest_sha256: str
    pointer_path: Path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _safe_namespace(value: str) -> str:
    if _SAFE_NAMESPACE.fullmatch(value) is None:
        raise PublicationError(f"unsafe publication namespace: {value!r}")
    return value


def publication_namespace(destinations: Sequence[Path]) -> str:
    if not destinations:
        raise PublicationError("publication namespace requires at least one destination")
    names = sorted(path.name for path in destinations)
    digest = hashlib.sha256(_canonical(names)).hexdigest()[:20]
    stem = re.sub(r"[^a-z0-9._-]+", "-", names[0].lower()).strip("-._") or "artifact"
    return _safe_namespace(f"{stem[:64]}-{digest}")


def _raise_rename_error(error_number: int, destination: Path) -> None:
    raise OSError(error_number, os.strerror(error_number), str(destination))


def rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically rename without replacing any existing path."""
    if os.name == "nt":
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform.startswith("linux"):
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            _raise_rename_error(errno.ENOTSUP, destination)
        assert renameat2 is not None
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, source_bytes, -100, destination_bytes, 1) != 0:
            _raise_rename_error(ctypes.get_errno(), destination)
        return
    if sys.platform == "darwin":
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            _raise_rename_error(errno.ENOTSUP, destination)
        assert renamex_np is not None
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        if renamex_np(source_bytes, destination_bytes, 0x00000004) != 0:
            _raise_rename_error(ctypes.get_errno(), destination)
        return
    _raise_rename_error(errno.ENOTSUP, destination)


def _require_real_directory(
    path: Path,
    *,
    mode: int | None = None,
    owner: bool = False,
) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PublicationError(f"publication path is not a real directory: {path}")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        raise PublicationError(f"publication directory mode differs: {path}")
    if owner and hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise PublicationError(f"publication directory owner differs: {path}")
    return info


def _mkdir_private(path: Path) -> None:
    if _lexists(path):
        _require_real_directory(path, mode=0o700, owner=True)
        return
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        # A concurrent initializer may have created the same protocol
        # directory.  It is accepted only after the same strict validation.
        pass
    _require_real_directory(path, mode=0o700, owner=True)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("zero-byte publication write")
        offset += written


def _open_regular_no_symlinks(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    directory_descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in absolute.parts[1:-1]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        return os.open(
            absolute.name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise PublicationError(f"publication source path is unsafe: {path}") from exc
    finally:
        os.close(directory_descriptor)


def _write_new(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        mode,
    )
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    _write_new(temporary, _canonical(value) + b"\n")
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _inventory(path: Path) -> tuple[str, list[dict[str, Any]]]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise PublicationError(f"publication artifact is a symlink: {path}")
    if stat.S_ISREG(info.st_mode):
        return "file", [
            {
                "kind": "file",
                "mode": stat.S_IMODE(info.st_mode),
                "path": "",
                "sha256": _sha256_file(path),
                "size": info.st_size,
            }
        ]
    if not stat.S_ISDIR(info.st_mode):
        raise PublicationError(f"publication artifact is not a regular file or directory: {path}")
    entries: list[dict[str, Any]] = []
    for member in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
        relative = member.relative_to(path).as_posix()
        current = member.lstat()
        if stat.S_ISLNK(current.st_mode):
            raise PublicationError(f"publication artifact contains a symlink: {relative}")
        if stat.S_ISDIR(current.st_mode):
            entries.append(
                {"kind": "directory", "mode": stat.S_IMODE(current.st_mode), "path": relative}
            )
        elif stat.S_ISREG(current.st_mode):
            entries.append(
                {
                    "kind": "file",
                    "mode": stat.S_IMODE(current.st_mode),
                    "path": relative,
                    "sha256": _sha256_file(member),
                    "size": current.st_size,
                }
            )
        else:
            raise PublicationError(f"publication artifact contains a special file: {relative}")
    return "directory", entries


def _artifact_record(path: Path) -> dict[str, Any]:
    kind, entries = _inventory(path)
    return {
        "entries": entries,
        "kind": kind,
        "mode": stat.S_IMODE(path.lstat().st_mode),
    }


def _previous_artifact_record(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return {"kind": "symlink", "target": os.readlink(path)}
    return _artifact_record(path)


def _valid_mode(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0o7777


def _validate_artifact_record(
    record: object,
    *,
    destination: bool = False,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PublicationError("publication artifact record is invalid")
    required = {"entries", "kind", "mode"}
    if destination:
        required |= {"destination", "index"}
    if set(record) != required:
        raise PublicationError("publication artifact record fields differ")
    kind = record.get("kind")
    mode = record.get("mode")
    entries = record.get("entries")
    if kind not in {"file", "directory"} or not _valid_mode(mode) or not isinstance(entries, list):
        raise PublicationError("publication artifact record is invalid")
    if destination:
        name = record.get("destination")
        index = record.get("index")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in {"", ".", "..", _STORE_NAME}
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
        ):
            raise PublicationError("publication target binding is invalid")

    seen: set[str] = set()
    directories: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PublicationError("publication artifact entry is invalid")
        entry_kind = entry.get("kind")
        expected_keys = {"kind", "mode", "path"}
        if entry_kind == "file":
            expected_keys |= {"sha256", "size"}
        if set(entry) != expected_keys or entry_kind not in {"file", "directory"}:
            raise PublicationError("publication artifact entry fields differ")
        relative = entry.get("path")
        if not isinstance(relative, str) or not _valid_mode(entry.get("mode")):
            raise PublicationError("publication artifact entry metadata is invalid")
        logical = PurePosixPath(relative)
        if relative != "":
            if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
                raise PublicationError("publication artifact entry path is unsafe")
            parent = logical.parent.as_posix()
            if parent != "." and parent not in directories:
                raise PublicationError("publication artifact entry parent is absent")
        if relative in seen:
            raise PublicationError("publication artifact entry path is duplicated")
        seen.add(relative)
        if entry_kind == "directory":
            if relative == "":
                raise PublicationError("publication directory entry path is empty")
            directories.add(relative)
        else:
            size = entry.get("size")
            digest = entry.get("sha256")
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
                or not isinstance(digest, str)
                or _HEX_64.fullmatch(digest) is None
            ):
                raise PublicationError("publication file entry identity is invalid")
    if kind == "file":
        if len(entries) != 1 or entries[0].get("kind") != "file" or entries[0].get("path") != "":
            raise PublicationError("publication file target inventory is invalid")
    elif "" in seen:
        raise PublicationError("publication directory target inventory is invalid")
    return record


def _validate_previous_artifact_record(record: object) -> dict[str, Any]:
    if isinstance(record, dict) and record.get("kind") == "symlink":
        if set(record) != {"kind", "target"} or not isinstance(record.get("target"), str):
            raise PublicationError("publication previous symlink record is invalid")
        return record
    return _validate_artifact_record(record)


def _previous_artifact_matches(path: Path, record: Mapping[str, Any]) -> bool:
    if record.get("kind") == "symlink":
        try:
            return path.is_symlink() and os.readlink(path) == record.get("target")
        except OSError:
            return False
    return _artifact_matches(path, record)


def _fsync_tree(path: Path) -> None:
    if path.is_file():
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    directories = [path, *(member for member in path.rglob("*") if member.is_dir())]
    for member in path.rglob("*"):
        if member.is_file():
            descriptor = os.open(member, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _fsync_directory(directory)


def _generation_blob_name(index: int) -> str:
    return f"{index:08d}.blob"


def _copy_verified_regular(
    source: Path,
    destination: Path,
    expected: Mapping[str, Any],
    *,
    destination_mode: int,
) -> None:
    source_descriptor = _open_regular_no_symlinks(source)
    destination_descriptor: int | None = None
    try:
        before = os.fstat(source_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PublicationError(f"publication source is not regular: {source}")
        if stat.S_IMODE(before.st_mode) != expected.get("mode") or before.st_size != expected.get(
            "size"
        ):
            raise PublicationError(f"publication source metadata changed: {source}")
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            _write_all(destination_descriptor, chunk)
        after = os.fstat(source_descriptor)
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
        ) or digest.hexdigest() != expected.get("sha256"):
            raise PublicationError(f"publication source content changed: {source}")
        os.fchmod(destination_descriptor, destination_mode)
        os.fsync(destination_descriptor)
    except Exception:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
            destination_descriptor = None
        if _lexists(destination):
            destination.unlink()
        raise
    finally:
        os.close(source_descriptor)
        if destination_descriptor is not None:
            os.close(destination_descriptor)


def _copy_generation_payload(
    source: Path,
    destination: Path,
    entries: Sequence[Mapping[str, Any]],
) -> None:
    """Store bytes without reproducing discoverable product file names.

    Discovery tools intentionally recurse above published artifacts.  Generation
    storage therefore uses opaque blob names and keeps the logical path/mode map
    in the manifest instead of creating a second discoverable product tree.
    """
    destination.mkdir(mode=0o700)
    file_entries = [entry for entry in entries if entry.get("kind") == "file"]
    for index, entry in enumerate(file_entries):
        relative = entry.get("path")
        if not isinstance(relative, str):
            raise PublicationError("publication file entry path is invalid")
        member = source if relative == "" else source / relative
        blob = destination / _generation_blob_name(index)
        _copy_verified_regular(member, blob, entry, destination_mode=0o400)
    _fsync_directory(destination)


def _materialize_generation_target(
    generation: Path,
    index: int,
    target: Mapping[str, Any],
    destination: Path,
) -> None:
    _validate_artifact_record(target, destination=True)
    entries = target["entries"]
    file_entries = [entry for entry in entries if entry.get("kind") == "file"]
    payload = generation / "payload" / str(index)
    _validate_generation_payload(payload, entries)
    try:
        if target["kind"] == "file":
            if len(file_entries) != 1 or file_entries[0].get("path") != "":
                raise PublicationError("publication file target inventory is invalid")
            _copy_verified_regular(
                payload / _generation_blob_name(0),
                destination,
                {**file_entries[0], "mode": 0o400},
                destination_mode=int(file_entries[0]["mode"]),
            )
            _fsync_directory(destination.parent)
        else:
            destination.mkdir(mode=0o700)
            file_index = 0
            for entry in entries:
                relative = entry.get("path")
                if not isinstance(relative, str) or relative in {"", ".", ".."}:
                    raise PublicationError("publication directory entry path is invalid")
                logical = PurePosixPath(relative)
                if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
                    raise PublicationError("publication directory entry escapes destination")
                member = destination.joinpath(*logical.parts)
                if entry.get("kind") == "directory":
                    member.mkdir(mode=0o700)
                elif entry.get("kind") == "file":
                    _copy_verified_regular(
                        payload / _generation_blob_name(file_index),
                        member,
                        {**entry, "mode": 0o400},
                        destination_mode=int(entry["mode"]),
                    )
                    file_index += 1
                else:
                    raise PublicationError("publication directory entry kind is invalid")
            _fsync_tree(destination)
            for entry in reversed(entries):
                if entry.get("kind") == "directory":
                    logical = PurePosixPath(str(entry["path"]))
                    descriptor = os.open(
                        destination.joinpath(*logical.parts),
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    )
                    try:
                        os.fchmod(descriptor, int(entry["mode"]))
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            descriptor = os.open(
                destination,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fchmod(descriptor, int(target["mode"]))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _fsync_directory(destination.parent)
        if not _artifact_matches(destination, target):
            raise PublicationError("materialized publication differs from generation")
    except Exception:
        if _lexists(destination):
            _remove_artifact(destination)
        raise


def _validate_generation_payload(
    payload: Path,
    entries: Sequence[Mapping[str, Any]],
) -> None:
    _require_real_directory(payload, mode=0o700, owner=True)
    file_entries = [entry for entry in entries if entry.get("kind") == "file"]
    expected = {_generation_blob_name(index) for index in range(len(file_entries))}
    actual = {member.name for member in payload.iterdir()}
    if actual != expected:
        raise PublicationError("immutable publication generation blob inventory differs")
    for index, entry in enumerate(file_entries):
        blob = payload / _generation_blob_name(index)
        info = blob.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PublicationError("immutable publication generation blob is not regular")
        if stat.S_IMODE(info.st_mode) != 0o400:
            raise PublicationError("immutable publication generation blob mode differs")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise PublicationError("immutable publication generation blob owner differs")
        if info.st_size != entry.get("size") or _sha256_file(blob) != entry.get("sha256"):
            raise PublicationError("immutable publication generation content differs")


def _remove_artifact(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise PublicationError(f"publication record is not a regular file: {path}")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        value = json.loads(b"".join(chunks))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"invalid publication record {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicationError(f"publication record is not an object: {path}")
    return value


def _generation_manifest(generation: Path) -> dict[str, Any]:
    _require_real_directory(generation, mode=0o700, owner=True)
    members = {member.name for member in generation.iterdir()}
    if members != {"payload", MANIFEST_NAME}:
        raise PublicationError("publication generation member inventory differs")
    payload_root = generation / "payload"
    _require_real_directory(payload_root, mode=0o700, owner=True)
    manifest_path = generation / MANIFEST_NAME
    manifest_info = manifest_path.lstat()
    if (
        not stat.S_ISREG(manifest_info.st_mode)
        or stat.S_ISLNK(manifest_info.st_mode)
        or stat.S_IMODE(manifest_info.st_mode) != 0o400
        or (hasattr(os, "getuid") and manifest_info.st_uid != os.getuid())
    ):
        raise PublicationError("publication generation manifest metadata differs")
    manifest = _read_json(manifest_path)
    if set(manifest) != {"generation_id", "publication_id", "schema_version", "targets"}:
        raise PublicationError("publication manifest fields differ")
    publication_id = manifest.get("publication_id")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or not isinstance(publication_id, str)
        or _safe_namespace(publication_id) != publication_id
    ):
        raise PublicationError("publication manifest schema differs")
    subject = {key: value for key, value in manifest.items() if key != "generation_id"}
    generation_id = hashlib.sha256(_canonical(subject)).hexdigest()
    if manifest.get("generation_id") != generation_id or generation.name != generation_id:
        raise PublicationError("publication generation identity differs")
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise PublicationError("publication manifest targets are absent")
    expected_payloads = {str(index) for index in range(len(targets))}
    if {member.name for member in payload_root.iterdir()} != expected_payloads:
        raise PublicationError("publication generation target inventory differs")
    destination_names: set[str] = set()
    for index, target in enumerate(targets):
        validated = _validate_artifact_record(target, destination=True)
        if validated.get("index") != index:
            raise PublicationError("publication manifest target ordering differs")
        destination_name = validated["destination"]
        if destination_name in destination_names:
            raise PublicationError("publication manifest destination is duplicated")
        destination_names.add(destination_name)
        _validate_generation_payload(payload_root / str(index), validated["entries"])
    return manifest


def _artifact_matches(path: Path, target: Mapping[str, Any]) -> bool:
    if not _lexists(path):
        return False
    try:
        kind, entries = _inventory(path)
    except PublicationError:
        return False
    return (
        kind == target.get("kind")
        and entries == target.get("entries")
        and stat.S_IMODE(path.lstat().st_mode) == target.get("mode")
    )


def _prepare_generation(
    namespace_root: Path,
    namespace: str,
    targets: Sequence[PublicationTarget],
) -> tuple[Path, dict[str, Any], str]:
    inventories: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        kind, entries = _inventory(target.staged)
        inventories.append(
            {
                "destination": target.destination.name,
                "entries": entries,
                "index": index,
                "kind": kind,
                "mode": stat.S_IMODE(target.staged.lstat().st_mode),
            }
        )
    subject: dict[str, Any] = {
        "publication_id": namespace,
        "schema_version": SCHEMA_VERSION,
        "targets": inventories,
    }
    generation_id = hashlib.sha256(_canonical(subject)).hexdigest()
    manifest = {**subject, "generation_id": generation_id}
    manifest_bytes = _canonical(manifest) + b"\n"
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    generations = namespace_root / "generations"
    _mkdir_private(generations)
    final = generations / generation_id
    if _lexists(final):
        _require_real_directory(final, mode=0o700, owner=True)
        existing = _generation_manifest(final)
        if existing != manifest:
            raise PublicationError("existing generation differs from its content identity")
        return final, manifest, manifest_sha256

    stage = generations / f".generation-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        payload = stage / "payload"
        payload.mkdir(mode=0o700)
        for index, target in enumerate(targets):
            _copy_generation_payload(
                target.staged,
                payload / str(index),
                inventories[index]["entries"],
            )
        _fsync_tree(payload)
        # The manifest is intentionally the final generation member written.
        _write_new(stage / MANIFEST_NAME, manifest_bytes, mode=0o400)
        _fsync_directory(stage)
        rename_no_replace(stage, final)
        _fsync_directory(generations)
    except Exception:
        if _lexists(stage):
            _remove_artifact(stage)
        raise
    _generation_manifest(final)
    return final, manifest, manifest_sha256


def _paths(parent: Path, namespace: str) -> tuple[Path, Path, Path]:
    store = parent / _STORE_NAME
    _mkdir_private(store)
    namespaces = store / "namespaces"
    _mkdir_private(namespaces)
    namespace_root = namespaces / namespace
    _mkdir_private(namespace_root)
    transactions = namespace_root / "transactions"
    _mkdir_private(transactions)
    return namespace_root, transactions / "active.json", namespace_root / "current.json"


@contextmanager
def _publication_lock(store_root: Path) -> Iterator[None]:
    """Serialize all publications below one destination parent."""
    if os.name != "posix":
        raise PublicationError("durable publication locking is unsupported on this platform")
    import fcntl

    lock_path = store_root / "publication.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise PublicationError(f"cannot open publication lock: {lock_path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise PublicationError("publication lock is not a regular file")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise PublicationError("publication lock mode differs")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise PublicationError("publication lock owner differs")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _journal_write(path: Path, journal: Mapping[str, Any]) -> None:
    _atomic_json(path, journal)


def _journal_destinations(journal: Mapping[str, Any], parent: Path) -> list[Path]:
    raw = journal.get("destinations")
    if not isinstance(raw, list) or not raw or not all(isinstance(value, str) for value in raw):
        raise PublicationError("publication journal destinations are invalid")
    paths = [parent / value for value in raw]
    if len({path.name for path in paths}) != len(paths) or any(
        path.name != raw[index] for index, path in enumerate(paths)
    ):
        raise PublicationError("publication journal destination is unsafe")
    return paths


def _store_root(namespace_root: Path) -> Path:
    store_root = namespace_root.parent.parent
    if store_root.name != _STORE_NAME:
        raise PublicationError("publication store identity differs")
    _require_real_directory(store_root, mode=0o700, owner=True)
    return store_root


def _record_destination_names(record: Mapping[str, Any]) -> set[str]:
    raw = record.get("destinations")
    if not isinstance(raw, list) or not raw or not all(isinstance(value, str) for value in raw):
        raise PublicationError("publication record destinations are invalid")
    names = set(raw)
    if len(names) != len(raw) or any(
        Path(value).name != value or value in {"", ".", "..", _STORE_NAME} for value in raw
    ):
        raise PublicationError("publication record destination is unsafe")
    return names


def _validate_destination_ownership(
    namespace_root: Path,
    namespace: str,
    destination_names: set[str],
) -> None:
    namespaces_root = namespace_root.parent
    _require_real_directory(namespaces_root, mode=0o700, owner=True)
    selected_pointer = namespace_root / "current.json"
    if _lexists(selected_pointer):
        _validate_pointer(namespace_root, selected_pointer, namespace)
        if _record_destination_names(_read_json(selected_pointer)) != destination_names:
            raise PublicationError("publication namespace destination binding differs")
    for candidate in namespaces_root.iterdir():
        _require_real_directory(candidate, mode=0o700, owner=True)
        candidate_namespace = _safe_namespace(candidate.name)
        if candidate_namespace == namespace:
            continue
        journal_path = candidate / "transactions" / "active.json"
        if _lexists(journal_path):
            journal = _read_json(journal_path)
            if destination_names & _record_destination_names(journal):
                raise PublicationError("publication destination belongs to another transaction")
        pointer_path = candidate / "current.json"
        if _lexists(pointer_path):
            pointer = _read_json(pointer_path)
            if destination_names & _record_destination_names(pointer):
                _validate_pointer(candidate, pointer_path, candidate_namespace)
                raise PublicationError("publication destination belongs to another publication")


def _pointer_value(manifest: Mapping[str, Any], manifest_sha256: str) -> dict[str, Any]:
    return {
        "destinations": [target["destination"] for target in manifest["targets"]],
        "generation_id": manifest["generation_id"],
        "manifest_sha256": manifest_sha256,
        "publication_id": manifest["publication_id"],
        "schema_version": SCHEMA_VERSION,
    }


def _transaction_root(namespace_root: Path, journal: Mapping[str, Any]) -> Path:
    transaction_id = journal.get("transaction_id")
    if not isinstance(transaction_id, str) or _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise PublicationError("publication transaction identity is invalid")
    return namespace_root / "transactions" / transaction_id


def _journal_progress(
    journal: Mapping[str, Any],
    target_count: int,
) -> tuple[bool, set[int], set[int], set[int], tuple[str, int] | None]:
    overwrite = journal.get("overwrite")
    backed_up = journal.get("backed_up")
    previous = journal.get("previous")
    published = journal.get("published")
    operation = journal.get("operation")
    if (
        not isinstance(overwrite, bool)
        or not isinstance(backed_up, list)
        or not isinstance(previous, list)
        or not isinstance(published, list)
    ):
        raise PublicationError("publication journal progress is invalid")
    for name, values in (
        ("backed-up", backed_up),
        ("previous", previous),
        ("published", published),
    ):
        if (
            any(not isinstance(value, int) or isinstance(value, bool) for value in values)
            or len(set(values)) != len(values)
            or values != sorted(values)
            or any(value < 0 or value >= target_count for value in values)
        ):
            raise PublicationError(f"publication journal {name} indexes are invalid")
    if backed_up != list(range(len(backed_up))) or published != list(range(len(published))):
        raise PublicationError("publication journal progress is not a contiguous prefix")
    backed_up_set = set(backed_up)
    previous_set = set(previous)
    published_set = set(published)
    if not previous_set <= backed_up_set:
        raise PublicationError("publication journal previous indexes are invalid")
    if overwrite:
        if published and backed_up != list(range(target_count)):
            raise PublicationError("publication began before backup completion")
    elif backed_up or previous:
        raise PublicationError("no-overwrite publication records backup progress")
    active: tuple[str, int] | None = None
    if operation is not None:
        if not isinstance(operation, dict) or set(operation) != {"index", "kind"}:
            raise PublicationError("publication journal operation is invalid")
        kind = operation.get("kind")
        index = operation.get("index")
        if (
            kind not in {"backup", "publish"}
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= target_count
        ):
            raise PublicationError("publication journal operation is invalid")
        if kind == "backup":
            if not overwrite or index != len(backed_up):
                raise PublicationError("publication backup operation is inconsistent")
        elif index != len(published) or (overwrite and len(backed_up) != target_count):
            raise PublicationError("publication publish operation is inconsistent")
        active = (kind, index)
    return overwrite, backed_up_set, previous_set, published_set, active


def _journal_rollback_state(
    journal: Mapping[str, Any],
    target_count: int,
) -> tuple[list[dict[str, Any] | None], list[int], tuple[str, int] | None]:
    previous_targets = journal.get("previous_targets")
    rolled_back = journal.get("rolled_back")
    rollback = journal.get("rollback")
    if (
        not isinstance(previous_targets, list)
        or len(previous_targets) != target_count
        or not isinstance(rolled_back, list)
    ):
        raise PublicationError("publication rollback state is invalid")
    validated_previous: list[dict[str, Any] | None] = []
    for record in previous_targets:
        validated_previous.append(
            None if record is None else _validate_previous_artifact_record(record)
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) for value in rolled_back
    ) or rolled_back != list(range(target_count - 1, target_count - len(rolled_back) - 1, -1)):
        raise PublicationError("publication rolled-back indexes are invalid")
    active: tuple[str, int] | None = None
    if rollback is not None:
        if not isinstance(rollback, dict) or set(rollback) != {"index", "kind"}:
            raise PublicationError("publication rollback operation is invalid")
        kind = rollback.get("kind")
        index = rollback.get("index")
        expected_index = target_count - len(rolled_back) - 1
        if (
            kind not in {"remove", "restore"}
            or not isinstance(index, int)
            or isinstance(index, bool)
            or index != expected_index
        ):
            raise PublicationError("publication rollback operation is inconsistent")
        if kind == "restore" and validated_previous[index] is None:
            raise PublicationError("publication restore has no previous target")
        active = (kind, index)
    return validated_previous, rolled_back, active


def _complete_rollback_index(
    journal_path: Path,
    journal: dict[str, Any],
    index: int,
) -> None:
    journal["rolled_back"] = [*journal["rolled_back"], index]
    journal["rollback"] = None
    _journal_write(journal_path, journal)


def _validate_pointer(
    namespace_root: Path,
    pointer_path: Path,
    namespace: str,
) -> PublicationResult:
    pointer = _read_json(pointer_path)
    generation_id = pointer.get("generation_id")
    manifest_sha256 = pointer.get("manifest_sha256")
    if (
        pointer.get("schema_version") != SCHEMA_VERSION
        or pointer.get("publication_id") != namespace
        or not isinstance(generation_id, str)
        or _HEX_64.fullmatch(generation_id) is None
        or not isinstance(manifest_sha256, str)
        or _HEX_64.fullmatch(manifest_sha256) is None
    ):
        raise PublicationError("publication pointer binding is invalid")
    generation = namespace_root / "generations" / generation_id
    manifest = _generation_manifest(generation)
    actual_manifest_sha256 = _sha256_file(generation / MANIFEST_NAME)
    if manifest_sha256 != actual_manifest_sha256:
        raise PublicationError("publication pointer manifest digest differs")
    if pointer != _pointer_value(manifest, manifest_sha256):
        raise PublicationError("publication pointer content differs")
    return PublicationResult(namespace, generation_id, manifest_sha256, pointer_path)


def _cleanup_committed(
    namespace_root: Path,
    journal_path: Path,
    journal: Mapping[str, Any],
) -> None:
    backup_root = _transaction_root(namespace_root, journal)
    if _lexists(backup_root):
        _require_real_directory(backup_root, mode=0o700, owner=True)
        shutil.rmtree(backup_root)
        _fsync_directory(backup_root.parent)
    if _lexists(journal_path):
        journal_path.unlink()
        _fsync_directory(journal_path.parent)


def _rollback(
    *,
    namespace_root: Path,
    journal_path: Path,
    journal: dict[str, Any],
    manifest: Mapping[str, Any],
    replace_fn: Callable[[Path, Path], None],
) -> None:
    parent = Path(str(journal["parent"]))
    destinations = _journal_destinations(journal, parent)
    backup_root = _transaction_root(namespace_root, journal)
    overwrite, backed_up, previous, published, operation = _journal_progress(
        journal, len(destinations)
    )
    previous_targets, rolled_back, rollback = _journal_rollback_state(journal, len(destinations))
    prior_indexes = {
        index for index, prior_target in enumerate(previous_targets) if prior_target is not None
    }
    if (
        not previous <= prior_indexes
        or any(index in backed_up and index not in previous for index in prior_indexes)
        or (not overwrite and prior_indexes)
    ):
        raise PublicationError("publication previous-target evidence is inconsistent")
    completed = set(rolled_back)
    for index in reversed(range(len(destinations))):
        if index in completed:
            continue
        destination = destinations[index]
        backup = backup_root / f"previous-{index}"
        quarantine = backup_root / f"discard-{index}"
        expected = manifest["targets"][index]
        prior = previous_targets[index]
        publish_touched = index in published or operation == ("publish", index)
        backup_touched = index in backed_up or operation == ("backup", index)

        if rollback is None and not publish_touched and not backup_touched:
            _complete_rollback_index(journal_path, journal, index)
            continue

        active_kind = rollback[0] if rollback is not None else None
        if active_kind is None and publish_touched and _lexists(destination):
            if _artifact_matches(destination, expected):
                journal["rollback"] = {"index": index, "kind": "remove"}
                _journal_write(journal_path, journal)
                active_kind = "remove"
            else:
                raise PublicationError(
                    f"cannot roll back modified publication destination: {destination}"
                )

        if active_kind == "remove":
            if _lexists(destination):
                if not _artifact_matches(destination, expected):
                    raise PublicationError(
                        f"cannot roll back modified publication destination: {destination}"
                    )
                if _lexists(quarantine):
                    raise PublicationError("publication rollback quarantine already exists")
                rename_no_replace(destination, quarantine)
                _fsync_directory(parent)
                _fsync_directory(backup_root)
            if not _lexists(quarantine) or not _artifact_matches(quarantine, expected):
                raise PublicationError("publication rollback quarantine differs")
            if prior is None:
                _complete_rollback_index(journal_path, journal, index)
                rollback = None
                continue
            journal["rollback"] = {"index": index, "kind": "restore"}
            _journal_write(journal_path, journal)
            active_kind = "restore"

        if active_kind is None and not _lexists(destination):
            if prior is None:
                if index in published:
                    raise PublicationError(
                        f"cannot roll back missing published destination: {destination}"
                    )
                _complete_rollback_index(journal_path, journal, index)
                continue
            if not _lexists(backup):
                raise PublicationError(f"publication backup is missing: {destination}")
            journal["rollback"] = {"index": index, "kind": "restore"}
            _journal_write(journal_path, journal)
            active_kind = "restore"

        if (
            active_kind is None
            and prior is not None
            and _previous_artifact_matches(destination, prior)
        ):
            if _lexists(backup):
                raise PublicationError("publication backup and restored destination both exist")
            _complete_rollback_index(journal_path, journal, index)
            continue

        if active_kind == "restore":
            assert prior is not None
            if _lexists(backup):
                if not _previous_artifact_matches(backup, prior):
                    raise PublicationError(
                        f"publication backup differs from recorded prior state: {destination}"
                    )
                if _lexists(destination):
                    raise PublicationError(
                        f"cannot restore publication backup over existing path: {destination}"
                    )
                replace_fn(backup, destination)
                _fsync_directory(parent)
            elif not _previous_artifact_matches(destination, prior):
                raise PublicationError(f"publication backup is missing: {destination}")
            if not _previous_artifact_matches(destination, prior):
                raise PublicationError(f"restored publication destination differs: {destination}")
            _complete_rollback_index(journal_path, journal, index)
            rollback = None
            continue

        if _lexists(destination):
            raise PublicationError(
                f"cannot roll back modified publication destination: {destination}"
            )
        if _lexists(backup):
            if not overwrite or not backup_touched:
                raise PublicationError("unexpected publication backup exists")
        elif index in previous:
            raise PublicationError(f"publication backup is missing: {destination}")
        _complete_rollback_index(journal_path, journal, index)
    _cleanup_committed(namespace_root, journal_path, journal)


def _recover_publication_locked(
    parent: str | Path,
    namespace: str,
    *,
    replace_fn: Callable[[Path, Path], None] = os.replace,
) -> PublicationResult | None:
    """Recover one journaled transaction without inventing missing state."""
    publication_parent = Path(parent).resolve()
    namespace = _safe_namespace(namespace)
    namespace_root, journal_path, pointer_path = _paths(publication_parent, namespace)
    if not _lexists(journal_path):
        if _lexists(pointer_path):
            return _validate_pointer(namespace_root, pointer_path, namespace)
        return None
    journal = _read_json(journal_path)
    if (
        journal.get("schema_version") != SCHEMA_VERSION
        or journal.get("publication_id") != namespace
        or journal.get("parent") != str(publication_parent)
    ):
        raise PublicationError("publication journal binding differs")
    generation_id = journal.get("generation_id")
    manifest_sha256 = journal.get("manifest_sha256")
    if (
        not isinstance(generation_id, str)
        or _HEX_64.fullmatch(generation_id) is None
        or not isinstance(manifest_sha256, str)
        or _HEX_64.fullmatch(manifest_sha256) is None
    ):
        raise PublicationError("publication journal generation identity is invalid")
    destinations = _journal_destinations(journal, publication_parent)
    generation = namespace_root / "generations" / generation_id
    manifest = _generation_manifest(generation)
    if _sha256_file(generation / MANIFEST_NAME) != manifest_sha256:
        raise PublicationError("publication journal manifest digest differs")
    if [path.name for path in destinations] != [
        target["destination"] for target in manifest["targets"]
    ]:
        raise PublicationError("publication journal target binding differs")
    _transaction_root(namespace_root, journal)
    _, _, _, published, operation = _journal_progress(journal, len(destinations))
    _, rolled_back, rollback = _journal_rollback_state(journal, len(destinations))
    phase = journal.get("phase")
    if phase in {"published", "pointer_committed"}:
        if (
            published != set(range(len(destinations)))
            or operation is not None
            or rolled_back
            or rollback is not None
        ):
            raise PublicationError("committed publication journal progress differs")
        if not all(
            _artifact_matches(destination, manifest["targets"][index])
            for index, destination in enumerate(destinations)
        ):
            raise PublicationError("published destinations differ during recovery")
        _atomic_json(pointer_path, _pointer_value(manifest, manifest_sha256))
        _validate_pointer(namespace_root, pointer_path, namespace)
        _cleanup_committed(namespace_root, journal_path, journal)
        return PublicationResult(namespace, generation_id, manifest_sha256, pointer_path)
    if phase not in {"prepared", "backed_up", "publishing"}:
        raise PublicationError("publication journal phase is invalid")
    _rollback(
        namespace_root=namespace_root,
        journal_path=journal_path,
        journal=journal,
        manifest=manifest,
        replace_fn=replace_fn,
    )
    return None


def recover_publication(
    parent: str | Path,
    namespace: str,
    *,
    replace_fn: Callable[[Path, Path], None] = os.replace,
) -> PublicationResult | None:
    """Recover one journaled transaction while excluding live publishers."""
    publication_parent = Path(parent).resolve()
    selected_namespace = _safe_namespace(namespace)
    namespace_root, _, _ = _paths(publication_parent, selected_namespace)
    with _publication_lock(_store_root(namespace_root)):
        return _recover_publication_locked(
            publication_parent,
            selected_namespace,
            replace_fn=replace_fn,
        )


def _publish_transaction_locked(
    targets: Sequence[PublicationTarget],
    *,
    overwrite: bool,
    namespace: str | None = None,
    replace_fn: Callable[[Path, Path], None] = os.replace,
    rename_no_replace_fn: Callable[[Path, Path], None] = rename_no_replace,
    failpoint: Callable[[str], None] | None = None,
) -> PublicationResult:
    """Publish staged sibling artifacts through a durable generation transaction."""
    if not targets:
        raise PublicationError("publication requires at least one target")
    raw = [PublicationTarget(Path(target.staged), Path(target.destination)) for target in targets]
    raw_parent = raw[0].destination.parent
    if any(target.destination.parent != raw_parent for target in raw):
        raise PublicationError("publication destinations must share one parent")
    raw_parent.mkdir(parents=True, exist_ok=True)
    parent = raw_parent.resolve()
    normalized = [
        PublicationTarget(target.staged, parent / target.destination.name) for target in raw
    ]
    if len({target.destination.name for target in normalized}) != len(normalized):
        raise PublicationError("publication destinations must be unique")
    _require_real_directory(parent)
    for target in normalized:
        if target.destination.name in {"", ".", "..", _STORE_NAME}:
            raise PublicationError("publication destination name is unsafe")
        _inventory(target.staged)
    canonical_namespace = publication_namespace([target.destination for target in normalized])
    if namespace is not None and _safe_namespace(namespace) != canonical_namespace:
        raise PublicationError("publication namespace does not bind destination set")
    selected_namespace = canonical_namespace
    namespace_root, journal_path, pointer_path = _paths(parent, selected_namespace)
    _recover_publication_locked(parent, selected_namespace, replace_fn=replace_fn)
    _validate_destination_ownership(
        namespace_root,
        selected_namespace,
        {target.destination.name for target in normalized},
    )
    if not overwrite and any(_lexists(target.destination) for target in normalized):
        raise PublicationError("refusing to replace existing publication without overwrite")

    generation, manifest, manifest_sha256 = _prepare_generation(
        namespace_root, selected_namespace, normalized
    )
    if failpoint is not None:
        failpoint("generation_committed")
    transaction_id = uuid.uuid4().hex
    backup_root = namespace_root / "transactions" / transaction_id
    if not overwrite and any(_lexists(target.destination) for target in normalized):
        raise PublicationError("refusing to replace existing publication without overwrite")
    previous_targets = [
        _previous_artifact_record(target.destination) if _lexists(target.destination) else None
        for target in normalized
    ]
    journal: dict[str, Any] = {
        "backed_up": [],
        "destinations": [target.destination.name for target in normalized],
        "generation_id": manifest["generation_id"],
        "manifest_sha256": manifest_sha256,
        "operation": None,
        "overwrite": overwrite,
        "previous": [],
        "previous_targets": previous_targets,
        "publication_id": selected_namespace,
        "parent": str(parent),
        "phase": "prepared",
        "published": [],
        "rollback": None,
        "rolled_back": [],
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
    }
    _journal_write(journal_path, journal)
    if failpoint is not None:
        failpoint("journal_committed")
    try:
        backup_root.mkdir(mode=0o700)
        _require_real_directory(backup_root, mode=0o700, owner=True)
        _fsync_directory(backup_root.parent)
        candidates: list[Path] = []
        for index, target_manifest in enumerate(manifest["targets"]):
            candidate_parent = backup_root / f"candidate-{index}"
            candidate_parent.mkdir(mode=0o700)
            candidate = candidate_parent / (normalized[index].staged.name or "artifact")
            _materialize_generation_target(generation, index, target_manifest, candidate)
            candidates.append(candidate)
        _fsync_directory(backup_root)
        if overwrite:
            for index, target in enumerate(normalized):
                prior = previous_targets[index]
                journal["operation"] = {"index": index, "kind": "backup"}
                _journal_write(journal_path, journal)
                if prior is None:
                    if _lexists(target.destination):
                        raise PublicationError(
                            "publication destination appeared after journal commit"
                        )
                else:
                    if not _previous_artifact_matches(target.destination, prior):
                        raise PublicationError(
                            "publication destination changed after journal commit"
                        )
                    replace_fn(target.destination, backup_root / f"previous-{index}")
                    _fsync_directory(parent)
                    _fsync_directory(backup_root)
                    if not _previous_artifact_matches(backup_root / f"previous-{index}", prior):
                        raise PublicationError(
                            "publication backup differs from recorded prior state"
                        )
                    journal["previous"] = [*journal["previous"], index]
                journal["backed_up"] = [*journal["backed_up"], index]
                journal["operation"] = None
                journal["phase"] = "backed_up"
                _journal_write(journal_path, journal)
                if failpoint is not None:
                    failpoint(f"backup_{index}")
        for index, target in enumerate(normalized):
            candidate = candidates[index]
            if not _artifact_matches(candidate, manifest["targets"][index]):
                raise PublicationError("materialized publication differs before commit")
            journal["operation"] = {"index": index, "kind": "publish"}
            _journal_write(journal_path, journal)
            if not overwrite:
                try:
                    rename_no_replace_fn(candidate, target.destination)
                except FileExistsError as exc:
                    journal["operation"] = None
                    _journal_write(journal_path, journal)
                    raise PublicationError(
                        "refusing to replace publication created while staging without overwrite"
                    ) from exc
            else:
                if _lexists(target.destination):
                    raise PublicationError("publication destination appeared after backup")
                replace_fn(candidate, target.destination)
            _fsync_directory(parent)
            journal["phase"] = "publishing"
            journal["published"] = [*journal["published"], index]
            journal["operation"] = None
            _journal_write(journal_path, journal)
            if failpoint is not None:
                failpoint(f"publish_{index}")
        if not all(
            _artifact_matches(target.destination, manifest["targets"][index])
            for index, target in enumerate(normalized)
        ):
            raise PublicationError("published destinations differ from committed generation")
        if (
            _generation_manifest(generation) != manifest
            or _sha256_file(generation / MANIFEST_NAME) != manifest_sha256
        ):
            raise PublicationError("committed publication generation changed")
        journal["phase"] = "published"
        _journal_write(journal_path, journal)
        _atomic_json(pointer_path, _pointer_value(manifest, manifest_sha256))
        _validate_pointer(namespace_root, pointer_path, selected_namespace)
        journal["phase"] = "pointer_committed"
        _journal_write(journal_path, journal)
        if failpoint is not None:
            failpoint("pointer_committed")
        if not all(
            _artifact_matches(target.destination, manifest["targets"][index])
            for index, target in enumerate(normalized)
        ):
            raise PublicationError("published destinations changed after pointer commit")
        if (
            _generation_manifest(generation) != manifest
            or _sha256_file(generation / MANIFEST_NAME) != manifest_sha256
        ):
            raise PublicationError("committed publication generation changed after pointer commit")
        _cleanup_committed(namespace_root, journal_path, journal)
    except PublicationCrash:
        raise
    except Exception:
        _recover_publication_locked(parent, selected_namespace, replace_fn=replace_fn)
        raise
    return PublicationResult(
        selected_namespace,
        manifest["generation_id"],
        manifest_sha256,
        pointer_path,
    )


def publish_transaction(
    targets: Sequence[PublicationTarget],
    *,
    overwrite: bool,
    namespace: str | None = None,
    replace_fn: Callable[[Path, Path], None] = os.replace,
    rename_no_replace_fn: Callable[[Path, Path], None] = rename_no_replace,
    failpoint: Callable[[str], None] | None = None,
) -> PublicationResult:
    """Publish staged sibling artifacts through a serialized transaction."""
    if not targets:
        raise PublicationError("publication requires at least one target")
    destinations = [Path(target.destination) for target in targets]
    raw_parent = destinations[0].parent
    if any(destination.parent != raw_parent for destination in destinations):
        raise PublicationError("publication destinations must share one parent")
    raw_parent.mkdir(parents=True, exist_ok=True)
    parent = raw_parent.resolve()
    normalized_destinations = [parent / destination.name for destination in destinations]
    canonical_namespace = publication_namespace(normalized_destinations)
    if namespace is not None and _safe_namespace(namespace) != canonical_namespace:
        raise PublicationError("publication namespace does not bind destination set")
    selected_namespace = canonical_namespace
    namespace_root, _, _ = _paths(parent, selected_namespace)
    with _publication_lock(_store_root(namespace_root)):
        return _publish_transaction_locked(
            targets,
            overwrite=overwrite,
            namespace=selected_namespace,
            replace_fn=replace_fn,
            rename_no_replace_fn=rename_no_replace_fn,
            failpoint=failpoint,
        )


__all__ = [
    "MANIFEST_NAME",
    "PublicationCrash",
    "PublicationError",
    "PublicationResult",
    "PublicationTarget",
    "publication_namespace",
    "publish_transaction",
    "recover_publication",
    "rename_no_replace",
]
