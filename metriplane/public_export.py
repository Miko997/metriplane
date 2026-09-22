# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Deterministic, allowlisted public exports with protected diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from metriplane.publication import PublicationResult, PublicationTarget, publish_transaction


PUBLIC_EXPORT_SCHEMA_VERSION = "metriplane.public-export.v1"
PROTECTED_DIAGNOSTICS_SCHEMA_VERSION = "metriplane.public-export-diagnostics.v1"
PUBLIC_EXPORT_NAME = "public-export.json"
REDACTED_SECRET = "<redacted:secret>"
REDACTED_PATH = "<redacted:path>"
REDACTED_IDENTITY = "<redacted:identity>"

_SAFE_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/]")
_RELATIVE_PATH = re.compile(r"(?:[^/\\]+[/\\])+[^/\\]+\Z")
_OS_REPLACE = os.replace
_DARWIN_ROOT_ALIASES = {
    "etc": ("private", "etc"),
    "tmp": ("private", "tmp"),
    "var": ("private", "var"),
}
_SECRET_VALUE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|"
    r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{8,}|\bsk-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_SECRET_KEYS = {
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "password",
    "passwd",
    "private_key",
    "secret",
    "session_key",
    "token",
}
_IDENTITY_KEYS = {
    "actor_id",
    "email",
    "employee_id",
    "face_id",
    "full_name",
    "host",
    "hostname",
    "machine_id",
    "name",
    "operator_id",
    "person_id",
    "run_id",
    "session_id",
    "subject_id",
    "user",
    "user_id",
    "username",
    "worker_id",
}
_PATH_KEYS = {
    "checkout",
    "cwd",
    "directory",
    "file",
    "home",
    "out_dir",
    "path",
    "repo_root",
    "repository_root",
    "run_dir",
    "source_path",
}


class PublicExportError(ValueError):
    """The public projection or its destination is unsafe or ambiguous."""


@dataclass(frozen=True, slots=True)
class PublicExportPolicy:
    """A closed set of dotted leaf paths allowed in public records."""

    allowlist: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.allowlist or tuple(sorted(set(self.allowlist))) != self.allowlist:
            raise PublicExportError("public allowlist must be non-empty, unique, and sorted")
        for path in self.allowlist:
            parts = path.split(".")
            if not parts or any(_SAFE_FIELD.fullmatch(part) is None for part in parts):
                raise PublicExportError(f"invalid public allowlist path: {path!r}")


@dataclass(frozen=True, slots=True)
class PublicExportResult:
    """Path-neutral identity of one committed public export transaction."""

    destination_name: str
    diagnostics_name: str
    public_sha256: str
    diagnostics_sha256: str
    generation_id: str
    manifest_sha256: str
    namespace: str


@dataclass(slots=True)
class _Diagnostics:
    dropped: set[str]
    redactions: Counter[str]
    redacted_paths: set[str]


def canonical_public_bytes(value: object) -> bytes:
    """Return stable UTF-8 JSON bytes with one terminal newline."""
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise PublicExportError("public value is not canonical JSON data") from exc


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("zero-byte public export write")
        view = view[written:]


def write_private_file(path: str | Path, data: bytes) -> None:
    """Create exactly one no-follow ``0600`` file and fsync its bytes."""
    target = Path(path)
    if target.name in {"", ".", ".."}:
        raise PublicExportError("private output name is unsafe")
    parent, parent_descriptor = _open_parent(target.parent, create=False)
    try:
        _require_parent_identity(parent, parent_descriptor)
        descriptor = os.open(
            target.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent_descriptor)
        _require_parent_identity(parent, parent_descriptor)
        _require_mode_at(parent_descriptor, target.name, directory=False, mode=0o600)
    finally:
        os.close(parent_descriptor)


def _canonical_parent(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    if sys.platform != "darwin" or len(absolute.parts) < 2:
        return absolute
    replacement = _DARWIN_ROOT_ALIASES.get(absolute.parts[1])
    if replacement is None:
        return absolute
    alias = Path("/") / absolute.parts[1]
    before = alias.lstat()
    if not stat.S_ISLNK(before.st_mode):
        if not stat.S_ISDIR(before.st_mode) or before.st_uid != 0:
            raise PublicExportError("Darwin private-output root alias differs")
        return absolute
    target = os.readlink(alias)
    after = alias.lstat()
    if (
        before.st_uid != 0
        or target != "/".join(replacement)
        or (before.st_dev, before.st_ino, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_ctime_ns)
    ):
        raise PublicExportError("Darwin private-output root alias differs")
    return Path("/", *replacement, *absolute.parts[2:])


def _open_parent(path: Path, *, create: bool) -> tuple[Path, int]:
    canonical = _canonical_parent(path)
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in canonical.parts[1:]:
            try:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            os.close(descriptor)
            descriptor = next_descriptor
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise PublicExportError("private output parent is not a real directory")
        return canonical, descriptor
    except OSError as exc:
        os.close(descriptor)
        raise PublicExportError("private output path contains an unsafe directory") from exc
    except BaseException:
        os.close(descriptor)
        raise


def _require_parent_identity(path: Path, descriptor: int) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
        pinned = os.fstat(descriptor)
    except OSError as exc:
        raise PublicExportError("private output parent identity is unavailable") from exc
    if (
        not stat.S_ISDIR(current.st_mode)
        or stat.S_ISLNK(current.st_mode)
        or (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino)
    ):
        raise PublicExportError("private output parent identity changed")


def _require_mode_at(descriptor: int, name: str, *, directory: bool, mode: int) -> None:
    info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    kind_matches = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not kind_matches
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != mode
        or (hasattr(os, "getuid") and info.st_uid != os.getuid())
    ):
        raise PublicExportError(f"public export protection differs: {name}")


def replace_private_file(path: str | Path, data: bytes) -> None:
    """Atomically create or replace one regular ``0600`` file.

    The destination parent and any existing destination are checked without
    following symlinks.  Bytes are fsynced before the atomic projection and the
    parent directory is fsynced afterwards.
    """
    target = Path(path)
    if target.name in {"", ".", ".."}:
        raise PublicExportError("private output name is unsafe")
    parent, directory_descriptor = _open_parent(target.parent, create=True)
    temporary = f".{target.name}.{secrets.token_hex(16)}.tmp"
    try:
        _require_parent_identity(parent, directory_descriptor)
        try:
            target_info = os.stat(
                target.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target_info = None
        if target_info is not None and (
            not stat.S_ISREG(target_info.st_mode) or stat.S_ISLNK(target_info.st_mode)
        ):
            raise PublicExportError("private output destination is not a regular file")
        staged_descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_descriptor,
        )
        try:
            os.fchmod(staged_descriptor, 0o600)
            _write_all(staged_descriptor, data)
            os.fsync(staged_descriptor)
        finally:
            os.close(staged_descriptor)
        _OS_REPLACE(
            temporary,
            target.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
        _require_parent_identity(parent, directory_descriptor)
        _require_mode_at(directory_descriptor, target.name, directory=False, mode=0o600)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        os.close(directory_descriptor)


def _normalized_key(key: object) -> str:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    return re.sub(r"[^a-z0-9]+", "_", split.casefold()).strip("_")


def _path_like(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith(("/", "~/", "./", "../", "\\\\"))
        or _WINDOWS_PATH.match(stripped) is not None
        or _RELATIVE_PATH.fullmatch(stripped) is not None
        or "/home/" in stripped
        or "\\Users\\" in stripped
    )


def _sensitive_kind(key: str, value: object) -> str | None:
    normalized = _normalized_key(key)
    if normalized in _SECRET_KEYS or normalized.endswith(("_secret", "_token", "_password")):
        return "secret"
    if normalized in _PATH_KEYS or normalized.endswith(("_path", "_dir", "_file")):
        return "path"
    if normalized in _IDENTITY_KEYS or normalized.endswith(("_user", "_username", "_hostname")):
        return "identity"
    if isinstance(value, str):
        if _SECRET_VALUE.search(value) is not None:
            return "secret"
        if _path_like(value):
            return "path"
    return None


def _marker(kind: str) -> str:
    return {
        "identity": REDACTED_IDENTITY,
        "path": REDACTED_PATH,
        "secret": REDACTED_SECRET,
    }[kind]


def _allowed_or_parent(path: str, allowlist: frozenset[str]) -> bool:
    return path in allowlist or any(candidate.startswith(f"{path}.") for candidate in allowlist)


def _project(
    value: object,
    *,
    allowlist: frozenset[str],
    diagnostics: _Diagnostics,
    path: tuple[str, ...] = (),
) -> object:
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for raw_key in sorted(value, key=lambda item: str(item)):
            if not isinstance(raw_key, str) or _SAFE_FIELD.fullmatch(raw_key) is None:
                raise PublicExportError("public record keys must be safe strings")
            child_path = (*path, raw_key)
            dotted = ".".join(child_path)
            if not _allowed_or_parent(dotted, allowlist):
                diagnostics.dropped.add(dotted)
                continue
            item = value[raw_key]
            kind = _sensitive_kind(raw_key, item)
            if kind is not None:
                projected[raw_key] = _marker(kind)
                diagnostics.redactions[kind] += 1
                diagnostics.redacted_paths.add(dotted)
                continue
            if dotted in allowlist and isinstance(item, Mapping):
                raise PublicExportError(
                    f"mapping allowlist entry must enumerate public leaves: {dotted}"
                )
            projected[raw_key] = _project(
                item,
                allowlist=allowlist,
                diagnostics=diagnostics,
                path=child_path,
            )
        return projected
    if isinstance(value, (list, tuple)):
        return [
            _project(item, allowlist=allowlist, diagnostics=diagnostics, path=path)
            for item in value
        ]
    dotted = ".".join(path)
    if dotted not in allowlist:
        raise PublicExportError(
            f"public scalar occupies an allowlist parent instead of a named leaf: {dotted}"
        )
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PublicExportError("public record contains a non-finite number")
        return value
    raise PublicExportError(f"unsupported public value at {'.'.join(path) or '<record>'}")


def build_public_export(
    records: Sequence[Mapping[str, object]],
    *,
    policy: PublicExportPolicy,
    canaries: Sequence[str] = (),
) -> tuple[dict[str, object], dict[str, object]]:
    """Project records and produce a value-free protected diagnostic summary."""
    if isinstance(records, (str, bytes, bytearray)):
        raise PublicExportError("public records must be a sequence of mappings")
    diagnostics = _Diagnostics(set(), Counter(), set())
    allowlist = frozenset(policy.allowlist)
    projected: list[object] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise PublicExportError("each public record must be a mapping")
        projected.append(_project(record, allowlist=allowlist, diagnostics=diagnostics))
    public: dict[str, object] = {
        "records": projected,
        "schema_version": PUBLIC_EXPORT_SCHEMA_VERSION,
    }
    protected: dict[str, object] = {
        "allowlist": list(policy.allowlist),
        "dropped_fields": sorted(diagnostics.dropped),
        "input_record_count": len(projected),
        "redacted_fields": sorted(diagnostics.redacted_paths),
        "redaction_counts": {
            kind: diagnostics.redactions.get(kind, 0) for kind in ("identity", "path", "secret")
        },
        "schema_version": PROTECTED_DIAGNOSTICS_SCHEMA_VERSION,
    }
    public_bytes = canonical_public_bytes(public)
    protected_bytes = canonical_public_bytes(protected)
    for canary in canaries:
        if not isinstance(canary, str) or len(canary.encode("utf-8")) < 4:
            raise PublicExportError("public export canaries must be strings of at least four bytes")
        encoded = canary.encode("utf-8")
        if encoded in public_bytes or encoded in protected_bytes:
            raise PublicExportError("sensitive canary survived public export redaction")
    return public, protected


def _sha256(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _sha256_at(directory_descriptor: int, name: str) -> str:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )
    digest = hashlib.sha256()
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _require_mode(path: Path, *, directory: bool, mode: int) -> None:
    info = path.lstat()
    kind_matches = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not kind_matches
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != mode
        or (hasattr(os, "getuid") and info.st_uid != os.getuid())
    ):
        raise PublicExportError(f"public export protection differs: {path.name}")


def publish_public_export(
    records: Sequence[Mapping[str, object]],
    destination: str | Path,
    *,
    policy: PublicExportPolicy,
    diagnostics_path: str | Path | None = None,
    overwrite: bool = False,
    canaries: Sequence[str] = (),
) -> PublicExportResult:
    """Commit public bytes and their protected sidecar as one publication."""
    output = Path(destination)
    if output.name in {"", ".", ".."}:
        raise PublicExportError("public export destination name is unsafe")
    diagnostic = (
        Path(diagnostics_path)
        if diagnostics_path is not None
        else output.with_name(f".{output.name}.diagnostics.json")
    )
    output_parent = _canonical_parent(output.parent)
    diagnostic_parent = _canonical_parent(diagnostic.parent)
    if output_parent != diagnostic_parent or output.name == diagnostic.name:
        raise PublicExportError("public export and diagnostics must be distinct siblings")
    output = output_parent / output.name
    diagnostic = diagnostic_parent / diagnostic.name
    public, protected = build_public_export(records, policy=policy, canaries=canaries)
    public_bytes = canonical_public_bytes(public)
    protected_bytes = canonical_public_bytes(protected)
    parent, parent_descriptor = _open_parent(output.parent, create=True)
    try:
        _require_parent_identity(parent, parent_descriptor)
        with TemporaryDirectory(prefix="metriplane-public-export-") as temporary:
            temporary_root = Path(temporary)
            temporary_root.chmod(0o700)
            _require_mode(temporary_root, directory=True, mode=0o700)
            public_stage = temporary_root / "public"
            public_stage.mkdir(mode=0o700)
            write_private_file(public_stage / PUBLIC_EXPORT_NAME, public_bytes)
            diagnostic_stage = temporary_root / "diagnostics.json"
            write_private_file(diagnostic_stage, protected_bytes)
            publication: PublicationResult = publish_transaction(
                [
                    PublicationTarget(public_stage, output),
                    PublicationTarget(diagnostic_stage, diagnostic),
                ],
                overwrite=overwrite,
                destination_parent_fd=parent_descriptor,
            )
        _require_parent_identity(parent, parent_descriptor)
        _require_mode_at(parent_descriptor, output.name, directory=True, mode=0o700)
        _require_mode_at(parent_descriptor, diagnostic.name, directory=False, mode=0o600)
        output_descriptor = os.open(
            output.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_descriptor,
        )
        try:
            _require_mode_at(
                output_descriptor,
                PUBLIC_EXPORT_NAME,
                directory=False,
                mode=0o600,
            )
            public_sha256 = _sha256_at(output_descriptor, PUBLIC_EXPORT_NAME)
        finally:
            os.close(output_descriptor)
        diagnostics_sha256 = _sha256_at(parent_descriptor, diagnostic.name)
        return PublicExportResult(
            destination_name=output.name,
            diagnostics_name=diagnostic.name,
            public_sha256=public_sha256,
            diagnostics_sha256=diagnostics_sha256,
            generation_id=publication.generation_id,
            manifest_sha256=publication.manifest_sha256,
            namespace=publication.namespace,
        )
    finally:
        os.close(parent_descriptor)


__all__ = [
    "PROTECTED_DIAGNOSTICS_SCHEMA_VERSION",
    "PUBLIC_EXPORT_NAME",
    "PUBLIC_EXPORT_SCHEMA_VERSION",
    "PublicExportError",
    "PublicExportPolicy",
    "PublicExportResult",
    "build_public_export",
    "canonical_public_bytes",
    "publish_public_export",
    "replace_private_file",
    "write_private_file",
]
