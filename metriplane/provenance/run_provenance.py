# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import dataclasses
import datetime as dt
import getpass
import hashlib
import json

from metriplane.strict_parsing import load_json as strict_json_loads
import os
import platform
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import tomllib
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, TextIO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from metriplane.config import Config, resolve_profile
from metriplane.paths import PlatformPathError, normalize_runs_dir, resolve_runs_dir
from metriplane.run_ids import portable_run_id_for_collision, validate_portable_run_id

HEADER_TYPES = {"header", "run_header", "provenance"}
_REDACTED = "<redacted>"
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_BUILD_INFO_SCHEMA = "metriplane.build-info.v1"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SOURCE_CHECKOUT_PATH = Path("metriplane/provenance/run_provenance.py")
_SENSITIVE_CONFIG_KEYS = {
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
    "session_id",
    "session_key",
    "token",
    "user",
    "username",
}


def _set_descriptor_mode(file_fd: int, mode: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(file_fd, mode)


def is_header_record(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    t = obj.get("type") or obj.get("record_type")
    return t in HEADER_TYPES


def canonical_json_dumps(obj: Any) -> str:
    # Canonical JSON for stable hashing and more stable JSONL evidence bytes.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def in_docker() -> bool:
    return Path("/.dockerenv").exists()


def data_dir() -> Path:
    env = normalize_runs_dir(os.getenv("METRIPLANE_DATA_DIR"))
    if env is not None:
        return Path(env)
    return Path("/data") if in_docker() else Path(".")


def resolve_under_data_dir(p: str | Path) -> Path:
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return data_dir() / pp


def generate_run_id(prefix: str = "run") -> str:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    rnd = secrets.token_hex(3)
    return f"{prefix}_{ts}_{rnd}"


class BuildInfoError(ValueError):
    """Raised when an installed build-info authority is malformed or tampered."""


def _find_repo_root(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p
    return None


@dataclass(frozen=True, slots=True)
class GitInfo:
    commit: str | None
    dirty: bool | None
    describe: str | None
    repo_root: str | None
    tree: str | None = None
    authority: str = "unavailable"
    declared_commit: str | None = None
    declaration_matches: bool | None = None


def _ambient_git_declaration() -> str | None:
    for name in ("METRIPLANE_GIT_COMMIT", "GIT_COMMIT", "GITHUB_SHA"):
        value = os.getenv(name)
        if value is not None and value.strip():
            candidate = value.strip()
            return candidate if _GIT_SHA_RE.fullmatch(candidate) else "<invalid>"
    return None


def _git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return completed.stdout.strip()


def _checkout_git_info(source_path: Path, declared: str | None) -> GitInfo | None:
    root = _find_repo_root(source_path)
    if root is None:
        return None
    try:
        relative_source = source_path.resolve().relative_to(root)
        top_level = Path(_git_output(root, "rev-parse", "--show-toplevel")).resolve()
        if (
            top_level != root.resolve()
            or len(relative_source.parts) < 2
            or relative_source.parts[0] != "metriplane"
            or relative_source.suffix != ".py"
        ):
            return None
        for tracked_path in (
            relative_source.as_posix(),
            _SOURCE_CHECKOUT_PATH.as_posix(),
            "metriplane/build-info.json",
            "pyproject.toml",
        ):
            _git_output(root, "ls-files", "--error-unmatch", "--", tracked_path)
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        project_table = project.get("project")
        if not isinstance(project_table, dict) or project_table.get("name") != "metriplane":
            return None
        commit = _git_output(root, "rev-parse", "HEAD")
        tree = _git_output(root, "rev-parse", "HEAD^{tree}")
        if _GIT_SHA_RE.fullmatch(commit) is None or _GIT_SHA_RE.fullmatch(tree) is None:
            return None
        describe = _git_output(root, "describe", "--tags", "--always", "--dirty")
        dirty = bool(_git_output(root, "status", "--porcelain", "--untracked-files=all"))
    except (
        OSError,
        ValueError,
        tomllib.TOMLDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    return GitInfo(
        commit=commit,
        dirty=dirty,
        describe=describe,
        repo_root=str(root),
        tree=tree,
        authority="checkout",
        declared_commit=declared,
        declaration_matches=(declared == commit) if declared is not None else None,
    )


def _embedded_git_info(source_path: Path, declared: str | None) -> GitInfo | None:
    resource = source_path.parent.parent / "build-info.json"
    try:
        raw = resource.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BuildInfoError(f"cannot read embedded build info: {exc}") from exc
    try:
        value = strict_json_loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildInfoError("embedded build info is not valid JSON") from exc
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BuildInfoError("embedded build info is not canonical JSON data") from exc
    if (
        raw != canonical
        or not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "source_commit",
            "source_dirty",
            "source_tree",
            "status",
        }
    ):
        raise BuildInfoError("embedded build info is not exact canonical v1 data")
    if value["schema_version"] != _BUILD_INFO_SCHEMA:
        raise BuildInfoError("embedded build info schema is unsupported")
    if value["status"] == "unbound":
        if any(
            value[field] is not None for field in ("source_commit", "source_dirty", "source_tree")
        ):
            raise BuildInfoError("unbound build info contains a source identity")
        return None
    source_commit = value.get("source_commit")
    source_tree = value.get("source_tree")
    if (
        value["status"] != "bound"
        or not isinstance(source_commit, str)
        or _GIT_SHA_RE.fullmatch(source_commit) is None
        or not isinstance(source_tree, str)
        or _GIT_SHA_RE.fullmatch(source_tree) is None
        or value.get("source_dirty") is not False
    ):
        raise BuildInfoError("embedded build info does not bind one clean Git source")
    commit = source_commit
    return GitInfo(
        commit=commit,
        dirty=False,
        describe=None,
        repo_root=None,
        tree=source_tree,
        authority="embedded-build-info",
        declared_commit=declared,
        declaration_matches=(declared == commit) if declared is not None else None,
    )


def get_git_info(*, start: Path | None = None) -> GitInfo:
    """Resolve source identity without trusting ambient Git variables.

    A verified checkout containing the inspected source file wins. Outside a
    checkout, a strict embedded build-info record may supply the identity.
    Ambient variables are retained only as declarations and never become the
    authoritative ``commit`` value.
    """

    declared = _ambient_git_declaration()
    candidate = Path(start).resolve() if start is not None else Path(__file__).resolve()
    source_path = candidate if candidate.is_file() else Path(__file__).resolve()
    checkout = _checkout_git_info(source_path, declared)
    if checkout is not None:
        return checkout
    embedded = _embedded_git_info(source_path, declared)
    if embedded is not None:
        return embedded
    return GitInfo(
        commit=None,
        dirty=None,
        describe=None,
        repo_root=None,
        authority="unavailable",
        declared_commit=declared,
        declaration_matches=None,
    )


def _redact_url_secrets(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or parsed.hostname is None:
            return value
        hostname = parsed.hostname
        if ":" in hostname:
            hostname = f"[{hostname}]"
        netloc = hostname
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        query = urlencode(
            [
                (
                    key,
                    _REDACTED if _is_sensitive_config_key(key) else item,
                )
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        fragment = (
            urlencode(
                [
                    (
                        key,
                        _REDACTED if _is_sensitive_config_key(key) else item,
                    )
                    for key, item in parse_qsl(parsed.fragment, keep_blank_values=True)
                ]
            )
            if "=" in parsed.fragment
            else parsed.fragment
        )
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))
    except (TypeError, ValueError):
        # Invalid URL-like strings are validated elsewhere. Persisting the
        # malformed value is less useful than risking an embedded credential.
        return _REDACTED if "://" in value else value


def _is_sensitive_config_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    components = set(normalized.split("_"))
    return (
        normalized in _SENSITIVE_CONFIG_KEYS
        or bool(
            components
            & {
                "authorization",
                "bearer",
                "cookie",
                "credential",
                "credentials",
                "passwd",
                "password",
                "secret",
                "session",
                "signature",
                "sig",
                "token",
            }
        )
        or normalized.endswith(("_api_key", "_private_key", "_access_key", "_secret_key"))
    )


def redact_persisted_config(value: Any, *, key: str | None = None) -> Any:
    """Remove credentials from config data before it becomes an artifact."""
    if key is not None and _is_sensitive_config_key(key):
        return _REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): redact_persisted_config(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_persisted_config(item) for item in value]
    if isinstance(value, str):
        return _redact_url_secrets(value)
    return value


def config_to_primitive(cfg: Config) -> dict[str, Any]:
    # asdict recursively converts nested dataclasses; JSON roundtrip ensures only JSON primitives.
    d = dataclasses.asdict(cfg)
    result: dict[str, Any] = strict_json_loads(canonical_json_dumps(redact_persisted_config(d)))
    return result


def compute_config_hash(cfg: Config) -> tuple[str, str]:
    prim = config_to_primitive(cfg)
    canon = canonical_json_dumps(prim)
    return sha256_text(canon), canon


def dump_config_yaml(cfg: Config) -> str:
    prim = config_to_primitive(cfg)
    return yaml.safe_dump(prim, sort_keys=True, default_flow_style=False)


_RUN_RESERVATION_MARKER = ".metriplane-run-reservation"
_RUN_RESERVATION_CANCELLED_MARKER = ".metriplane-run-reservation-cancelled"
_RUN_RESERVATION_DIR_ENV = "METRIPLANE_RESERVED_RUN_DIR"
_RUN_RESERVATION_TOKEN_ENV = "METRIPLANE_RUN_RESERVATION_TOKEN"
_RUN_RESERVATION_DEVICE_ENV = "METRIPLANE_RUN_RESERVATION_DEVICE"
_RUN_RESERVATION_INODE_ENV = "METRIPLANE_RUN_RESERVATION_INODE"


def _reservation_directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW")
    if os.name != "posix" or any(not hasattr(os, name) for name in required):
        raise PlatformPathError(
            "secure run directory reservations require POSIX directory handles and O_NOFOLLOW"
        )
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def _assert_directory_identity(
    expected: os.stat_result,
    current: os.stat_result,
    path: Path,
) -> None:
    if not _same_directory_identity(expected, current):
        raise PlatformPathError(f"run directory identity changed during reservation: {path}")


def _write_run_reservation_marker(directory_fd: int, token: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    marker_fd = os.open(_RUN_RESERVATION_MARKER, flags, 0o600, dir_fd=directory_fd)
    try:
        _set_descriptor_mode(marker_fd, _PRIVATE_FILE_MODE)
        remaining = memoryview(token.encode("utf-8"))
        while remaining:
            written = os.write(marker_fd, remaining)
            if written <= 0:
                raise OSError("run directory reservation marker write made no progress")
            remaining = remaining[written:]
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)


@dataclass(frozen=True, slots=True)
class _ReservationAuthority:
    run_dir: Path
    token: str
    device: int
    inode: int


_IN_PROCESS_RUN_CONTEXTS: weakref.WeakValueDictionary[str, RunContext] = (
    weakref.WeakValueDictionary()
)
_IN_PROCESS_RUN_AUTHORITIES_LOCK = threading.RLock()


def _authority_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _remember_run_context(context: RunContext) -> None:
    with _IN_PROCESS_RUN_AUTHORITIES_LOCK:
        _IN_PROCESS_RUN_CONTEXTS[_authority_key(context.run_dir)] = context


def _in_process_run_authority(candidate: Path) -> _ReservationAuthority | None:
    with _IN_PROCESS_RUN_AUTHORITIES_LOCK:
        context = _IN_PROCESS_RUN_CONTEXTS.get(_authority_key(candidate))
        return None if context is None else context._authority


@dataclass(slots=True)
class _ClaimedRunDirectory:
    authority: _ReservationAuthority
    fd: int

    def verify_visible_path(self) -> None:
        try:
            current = self.authority.run_dir.lstat()
        except OSError as exc:
            raise PlatformPathError(
                f"reserved run directory is unavailable: {self.authority.run_dir}"
            ) from exc
        if (
            not stat.S_ISDIR(current.st_mode)
            or current.st_dev != self.authority.device
            or current.st_ino != self.authority.inode
        ):
            raise PlatformPathError(
                f"reserved run directory identity changed: {self.authority.run_dir}"
            )

    def write_text(self, name: str, content: str) -> None:
        self.verify_visible_path()
        _write_claimed_text(self.fd, name, content)
        self.verify_visible_path()

    def close(self) -> None:
        os.close(self.fd)


def _reservation_authority(candidate: Path) -> _ReservationAuthority | None:
    values = {
        _RUN_RESERVATION_DIR_ENV: os.getenv(_RUN_RESERVATION_DIR_ENV),
        _RUN_RESERVATION_TOKEN_ENV: os.getenv(_RUN_RESERVATION_TOKEN_ENV),
        _RUN_RESERVATION_DEVICE_ENV: os.getenv(_RUN_RESERVATION_DEVICE_ENV),
        _RUN_RESERVATION_INODE_ENV: os.getenv(_RUN_RESERVATION_INODE_ENV),
    }
    if all(value is None for value in values.values()):
        return None
    if any(value is None for value in values.values()):
        raise PlatformPathError("run directory reservation environment is incomplete")

    configured_dir_text = values[_RUN_RESERVATION_DIR_ENV]
    configured_token = values[_RUN_RESERVATION_TOKEN_ENV]
    configured_device = values[_RUN_RESERVATION_DEVICE_ENV]
    configured_inode = values[_RUN_RESERVATION_INODE_ENV]
    assert configured_dir_text is not None
    assert configured_token is not None
    assert configured_device is not None
    assert configured_inode is not None

    configured_dir = Path(configured_dir_text)
    if not configured_dir.is_absolute():
        raise PlatformPathError("reserved run directory must be an absolute path")
    if os.path.normcase(os.path.abspath(configured_dir)) != os.path.normcase(
        os.path.abspath(candidate)
    ):
        raise PlatformPathError(
            f"run directory reservation does not match requested run_id: {candidate}"
        )
    try:
        device = int(configured_device, 10)
        inode = int(configured_inode, 10)
    except ValueError as exc:
        raise PlatformPathError("run directory reservation identity is malformed") from exc
    if device < 0 or inode <= 0:
        raise PlatformPathError("run directory reservation identity is malformed")
    return _ReservationAuthority(
        run_dir=candidate,
        token=configured_token,
        device=device,
        inode=inode,
    )


def _open_authorized_run_directory(
    authority: _ReservationAuthority,
) -> _ClaimedRunDirectory:
    try:
        directory_fd = os.open(authority.run_dir, _reservation_directory_flags())
    except OSError as exc:
        raise PlatformPathError(
            f"reserved run directory cannot be opened safely: {authority.run_dir}"
        ) from exc
    claimed = _ClaimedRunDirectory(authority=authority, fd=directory_fd)
    try:
        opened = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_dev != authority.device
            or opened.st_ino != authority.inode
        ):
            raise PlatformPathError(f"reserved run directory identity changed: {authority.run_dir}")
        claimed.verify_visible_path()
    except BaseException:
        claimed.close()
        raise
    return claimed


def _read_reservation_marker(directory_fd: int, path: Path) -> str:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        marker_fd = os.open(_RUN_RESERVATION_MARKER, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise PlatformPathError(f"run directory reservation cannot be read: {path}") from exc
    try:
        marker_identity = os.fstat(marker_fd)
        if not stat.S_ISREG(marker_identity.st_mode):
            raise PlatformPathError(
                f"run directory reservation marker is not a regular file: {path}"
            )
        content = os.read(marker_fd, 4097)
        if len(content) > 4096 or os.read(marker_fd, 1):
            raise PlatformPathError(f"run directory reservation marker is too large: {path}")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlatformPathError(
                f"run directory reservation marker is not UTF-8: {path}"
            ) from exc
    finally:
        os.close(marker_fd)


def _write_claimed_text(
    directory_fd: int,
    name: str,
    content: str,
    *,
    mode: int = _PRIVATE_FILE_MODE,
) -> None:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError(f"invalid run artifact name: {name}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    file_fd = os.open(name, flags, mode, dir_fd=directory_fd)
    try:
        _set_descriptor_mode(file_fd, mode & 0o700)
        remaining = memoryview(content.encode("utf-8"))
        while remaining:
            written = os.write(file_fd, remaining)
            if written <= 0:
                raise OSError("run artifact write made no progress")
            remaining = remaining[written:]
        os.fsync(file_fd)
    finally:
        os.close(file_fd)


def _mkdir_private(path: Path, *, parents: bool, exist_ok: bool) -> None:
    """Create every missing directory component with a private mode."""
    try:
        os.mkdir(path, _PRIVATE_DIRECTORY_MODE)
    except FileNotFoundError:
        if not parents or path.parent == path:
            raise
        _mkdir_private(path.parent, parents=True, exist_ok=True)
        _mkdir_private(path, parents=False, exist_ok=exist_ok)
    except FileExistsError:
        if not exist_ok:
            raise
        opened = path.lstat()
        if stat.S_ISLNK(opened.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise


@dataclass(frozen=True, slots=True)
class RunDirectoryReservation:
    """An exact run directory reserved for one child runtime."""

    run_id: str
    run_dir: Path
    token: str
    device: int
    inode: int

    @property
    def marker_path(self) -> Path:
        return self.run_dir / _RUN_RESERVATION_MARKER

    def child_environment(self, environment: Mapping[str, str]) -> dict[str, str]:
        child = dict(environment)
        child[_RUN_RESERVATION_DIR_ENV] = str(self.run_dir)
        child[_RUN_RESERVATION_TOKEN_ENV] = self.token
        child[_RUN_RESERVATION_DEVICE_ENV] = str(self.device)
        child[_RUN_RESERVATION_INODE_ENV] = str(self.inode)
        return child

    def cancel_if_pending(self) -> bool:
        """Tombstone an unclaimed reservation without pathname-based deletion."""
        authority = _ReservationAuthority(
            run_dir=self.run_dir,
            token=self.token,
            device=self.device,
            inode=self.inode,
        )
        try:
            claimed = _open_authorized_run_directory(authority)
        except (OSError, PlatformPathError):
            return False

        try:
            if os.listdir(claimed.fd) != [_RUN_RESERVATION_MARKER]:
                return False
            marker_token = _read_reservation_marker(claimed.fd, self.run_dir)
            claimed.verify_visible_path()
            if not secrets.compare_digest(marker_token, self.token):
                return False

            _write_claimed_text(
                claimed.fd,
                _RUN_RESERVATION_CANCELLED_MARKER,
                self.token,
                mode=0o600,
            )
            claimed.verify_visible_path()
            os.unlink(_RUN_RESERVATION_MARKER, dir_fd=claimed.fd)
            os.fsync(claimed.fd)
            claimed.verify_visible_path()
        except (OSError, PlatformPathError):
            return False
        finally:
            claimed.close()
        return True

    def claimed_run_dir(self) -> Path:
        """Return the exact claimed directory or fail on stale/replaced identity."""
        authority = _ReservationAuthority(
            run_dir=self.run_dir,
            token=self.token,
            device=self.device,
            inode=self.inode,
        )
        claimed = _open_authorized_run_directory(authority)
        try:
            entries = set(os.listdir(claimed.fd))
            claimed.verify_visible_path()
            if _RUN_RESERVATION_MARKER in entries:
                raise PlatformPathError(
                    f"run directory reservation was not claimed: {self.run_dir}"
                )
            if _RUN_RESERVATION_CANCELLED_MARKER in entries:
                raise PlatformPathError(f"run directory reservation was cancelled: {self.run_dir}")
            return self.run_dir
        finally:
            claimed.close()


def reserve_run_directory(base: Path, run_id: str) -> RunDirectoryReservation:
    """Atomically reserve one canonical collision-safe run directory."""
    requested_run_id = validate_portable_run_id(run_id)
    _mkdir_private(base, parents=True, exist_ok=True)
    try:
        base_before_open = base.lstat()
        base_fd = os.open(base, _reservation_directory_flags())
    except OSError as exc:
        raise PlatformPathError(f"run directory base cannot be opened safely: {base}") from exc

    try:
        base_opened = os.fstat(base_fd)
        _assert_directory_identity(base_before_open, base_opened, base)

        for collision_index in range(1000):
            reserved_run_id = portable_run_id_for_collision(
                requested_run_id,
                collision_index,
            )
            run_dir = base / reserved_run_id
            try:
                os.mkdir(
                    reserved_run_id,
                    mode=_PRIVATE_DIRECTORY_MODE,
                    dir_fd=base_fd,
                )
            except FileExistsError:
                continue

            run_fd: int | None = None
            created_identity: os.stat_result | None = None
            opened_identity: os.stat_result | None = None
            try:
                try:
                    created_identity = os.stat(
                        reserved_run_id,
                        dir_fd=base_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise PlatformPathError(
                        f"run directory identity changed during reservation: {run_dir}"
                    ) from exc
                try:
                    run_fd = os.open(
                        reserved_run_id,
                        _reservation_directory_flags(),
                        dir_fd=base_fd,
                    )
                except OSError as exc:
                    raise PlatformPathError(
                        f"run directory identity changed during reservation: {run_dir}"
                    ) from exc
                opened_identity = os.fstat(run_fd)
                _assert_directory_identity(created_identity, opened_identity, run_dir)
                _set_descriptor_mode(run_fd, _PRIVATE_DIRECTORY_MODE)

                token = secrets.token_hex(32)
                _write_run_reservation_marker(run_fd, token)
                os.fsync(run_fd)

                try:
                    current_identity = os.stat(
                        reserved_run_id,
                        dir_fd=base_fd,
                        follow_symlinks=False,
                    )
                    current_base = base.lstat()
                except OSError as exc:
                    raise PlatformPathError(
                        f"run directory identity changed during reservation: {run_dir}"
                    ) from exc
                _assert_directory_identity(opened_identity, current_identity, run_dir)
                _assert_directory_identity(base_opened, current_base, base)
                return RunDirectoryReservation(
                    run_id=reserved_run_id,
                    run_dir=run_dir,
                    token=token,
                    device=opened_identity.st_dev,
                    inode=opened_identity.st_ino,
                )
            except BaseException:
                # A directory cannot be removed portably through its open
                # descriptor. Preserve failed reservations instead of risking
                # deletion of a replacement installed after an identity check.
                raise
            finally:
                if run_fd is not None:
                    os.close(run_fd)
    finally:
        os.close(base_fd)
    raise RuntimeError(f"could not reserve a unique run directory under {base}")


def _claim_authorized_run_directory(
    authority: _ReservationAuthority,
) -> _ClaimedRunDirectory:
    candidate = authority.run_dir
    claimed = _open_authorized_run_directory(authority)
    try:
        try:
            entries = os.listdir(claimed.fd)
        except OSError as exc:
            raise PlatformPathError(
                f"run directory reservation cannot be read: {candidate}"
            ) from exc
        claimed.verify_visible_path()
        if entries != [_RUN_RESERVATION_MARKER]:
            raise PlatformPathError(f"reserved run directory is not empty: {candidate}")

        marker_token = _read_reservation_marker(claimed.fd, candidate)
        claimed.verify_visible_path()
        if not secrets.compare_digest(marker_token, authority.token):
            raise PlatformPathError("run directory reservation token does not match")
        os.unlink(_RUN_RESERVATION_MARKER, dir_fd=claimed.fd)
        os.fsync(claimed.fd)
        claimed.verify_visible_path()
    except BaseException:
        claimed.close()
        raise
    return claimed


def _claim_run_directory_reservation(candidate: Path) -> _ClaimedRunDirectory | None:
    authority = _reservation_authority(candidate)
    if authority is None:
        return None
    return _claim_authorized_run_directory(authority)


def _create_unreserved_run_directory(base: Path, run_id: str) -> _ClaimedRunDirectory:
    reservation = reserve_run_directory(base, run_id)
    authority = _ReservationAuthority(
        run_dir=reservation.run_dir,
        token=reservation.token,
        device=reservation.device,
        inode=reservation.inode,
    )
    return _claim_authorized_run_directory(authority)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class RunContext:
    run_id: str
    run_dir: Path
    created_utc: str
    argv: list[str]

    resolved_profile: str | None

    config_hash: str
    git: GitInfo

    source_config_path: str | None

    meta_json: Path
    env_txt: Path
    config_yaml: Path
    config_canonical_json_path: Path
    session_jsonl: Path
    _authority: _ReservationAuthority = dataclasses.field(repr=False, compare=False)

    def header_record(self) -> dict[str, Any]:
        return {
            "type": "run_header",
            "schema_version": "1.0",
            "created_utc": self.created_utc,
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "git_commit": self.git.commit,
            "git_dirty": self.git.dirty,
            "git_describe": self.git.describe,
            "git_tree": self.git.tree,
            "git_authority": self.git.authority,
            "git_declared_commit": self.git.declared_commit,
            "git_declaration_matches": self.git.declaration_matches,
            "argv": list(self.argv),
            "source_config_path": self.source_config_path,
            "resolved_profile": self.resolved_profile,
        }


class JsonlWriter:
    def __init__(self, files: list[TextIO], paths: list[Path]) -> None:
        self._files = files
        self.paths = paths

    def write(self, obj: Any) -> None:
        # Accept pydantic models or plain dicts
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        if not isinstance(obj, dict):
            raise TypeError(f"JsonlWriter.write expects dict-like; got {type(obj)}")

        line = canonical_json_dumps(obj)
        for f in self._files:
            f.write(line + "\n")

    def close(self) -> None:
        for f in self._files:
            try:
                f.close()
            except Exception:
                pass
        self._files = []


def _capture_env_text() -> str:
    lines: list[str] = []
    lines.append(f"created_utc: {_utc_now_iso()}")
    lines.append(f"python: {sys.version.replace(os.linesep, ' ')}")
    lines.append(f"executable: {sys.executable}")
    lines.append(f"platform: {platform.platform()}")
    lines.append(f"machine: {platform.machine()}")
    lines.append(f"processor: {platform.processor()}")
    lines.append("")

    no_freeze = os.getenv("METRIPLANE_NO_PIP_FREEZE", "0").strip() == "1"
    lines.append("pip_freeze:")
    if no_freeze:
        lines.append("(skipped: METRIPLANE_NO_PIP_FREEZE=1)")
    else:
        try:
            p = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"], check=True, capture_output=True, text=True
            )
            lines.append(p.stdout.strip())
        except Exception as e:
            lines.append(f"(pip freeze failed: {type(e).__name__}: {e})")

    lines.append("")
    return "\n".join(lines) + "\n"


def _open_private_text(path: Path, *, exclusive: bool, buffering: int = -1) -> TextIO:
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    file_fd = os.open(path, flags, _PRIVATE_FILE_MODE)
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise PlatformPathError(f"run artifact is not a regular file: {path}")
        _set_descriptor_mode(file_fd, _PRIVATE_FILE_MODE)
        handle = os.fdopen(file_fd, "w", encoding="utf-8", buffering=buffering)
        file_fd = -1
        return handle
    finally:
        if file_fd >= 0:
            os.close(file_fd)


def _write_private_text(path: Path, content: str, *, exclusive: bool) -> None:
    with _open_private_text(path, exclusive=exclusive) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def capture_env_txt(path: Path) -> None:
    _write_private_text(path, _capture_env_text(), exclusive=False)


def create_run_context(
    cfg: Config,
    *,
    config_path: Path | None,
    argv: Sequence[str] | None,
    run_id: str | None,
    runs_dir: str | None,
) -> RunContext:
    created = _utc_now_iso()

    configured_run_id = run_id if run_id is not None else os.getenv("METRIPLANE_RUN_ID")
    if configured_run_id is None:
        rid = generate_run_id()
    else:
        rid = validate_portable_run_id(str(configured_run_id))

    # Where runs live
    unresolved_base: Path
    explicit_runs_dir = normalize_runs_dir(runs_dir)
    configured_runs_dir = normalize_runs_dir(cfg.runs_dir)
    if explicit_runs_dir is not None:
        unresolved_base = resolve_under_data_dir(explicit_runs_dir)
    elif configured_runs_dir is not None:
        unresolved_base = resolve_under_data_dir(configured_runs_dir)
    else:
        unresolved_base = data_dir() / "runs"

    base = resolve_runs_dir(unresolved_base)
    if base is None:  # The concrete Path above cannot normalize to an absent override.
        raise AssertionError("run-recording root unexpectedly resolved as absent")

    # Make run dir unique (avoid overwriting) and keep it beneath runs_dir.
    unresolved_candidate = base / rid
    if unresolved_candidate.is_symlink():
        raise PlatformPathError(
            f"cannot resolve run-recording path {unresolved_candidate}: "
            "symbolic links are not allowed"
        )
    try:
        candidate = unresolved_candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise PlatformPathError(
            f"cannot resolve run-recording path {unresolved_candidate}: {exc}"
        ) from exc
    try:
        candidate.relative_to(base)
    except ValueError as exc:  # defense in depth; the run-id syntax already rejects separators
        raise ValueError("run_id resolves outside runs_dir") from exc
    claimed_directory = _claim_run_directory_reservation(candidate)
    if claimed_directory is not None:
        run_dir = candidate
    else:
        claimed_directory = _create_unreserved_run_directory(base, rid)
        run_dir = claimed_directory.authority.run_dir
    try:
        # If collision suffixing changed the directory, keep the persisted ID in sync.
        rid = validate_portable_run_id(run_dir.name)

        # Git + config hash
        git = get_git_info(start=Path(__file__).resolve())
        cfg_hash, cfg_canon = compute_config_hash(cfg)

        # Resolved profile (captures calib/active_profile.yaml even if cfg.profile is None)
        resolved_prof = resolve_profile(
            cfg.profile,
            active_profile_path=Path("calib/active_profile.yaml"),
        )

        # Artifact paths
        meta_json = run_dir / "meta.json"
        env_txt = run_dir / "env.txt"
        config_yaml = run_dir / "config.yaml"
        cfg_canon_path = run_dir / "config.canonical.json"
        session_jsonl = run_dir / "session.jsonl"

        config_yaml_content = dump_config_yaml(cfg)
        env_content = _capture_env_text()
        claimed_directory.write_text("config.yaml", config_yaml_content)
        claimed_directory.write_text("config.canonical.json", cfg_canon)
        claimed_directory.write_text("env.txt", env_content)
        config_yaml_checksum = sha256_text(config_yaml_content)
        config_canonical_checksum = sha256_text(cfg_canon)
        env_checksum = sha256_text(env_content)
        assert config_canonical_checksum == cfg_hash

        meta: dict[str, Any] = {
            "schema_version": "1.0",
            "created_utc": created,
            "run_id": rid,
            "run_dir": str(run_dir),
            "user": getpass.getuser(),
            "hostname": socket.gethostname(),
            "cwd": str(Path.cwd()),
            "argv": list(argv) if argv is not None else [],
            "source_config_path": str(config_path) if config_path else None,
            "resolved_profile": resolved_prof,
            "git": {
                "commit": git.commit,
                "dirty": git.dirty,
                "describe": git.describe,
                "repo_root": git.repo_root,
                "tree": git.tree,
                "authority": git.authority,
                "declared_commit": git.declared_commit,
                "declaration_matches": git.declaration_matches,
            },
            "config": {
                "hash_algo": "sha256",
                "hash": cfg_hash,
                "canonical_json_path": str(cfg_canon_path),
                "snapshot_yaml_path": str(config_yaml),
                "source_config_path": str(config_path) if config_path else None,
            },
            "artifacts": {
                "session_jsonl": str(session_jsonl),
                "env_txt": str(env_txt),
            },
            "checksums": {
                "config_yaml_sha256": config_yaml_checksum,
                "config_canonical_json_sha256": config_canonical_checksum,
                "env_txt_sha256": env_checksum,
            },
        }
        meta_content = json.dumps(meta, indent=2, sort_keys=True)
        claimed_directory.write_text("meta.json", meta_content)
        os.fsync(claimed_directory.fd)
        claimed_directory.verify_visible_path()

        context = RunContext(
            run_id=rid,
            run_dir=run_dir,
            created_utc=created,
            argv=list(argv) if argv is not None else [],
            resolved_profile=resolved_prof,
            config_hash=cfg_hash,
            git=git,
            source_config_path=str(config_path) if config_path else None,
            meta_json=meta_json,
            env_txt=env_txt,
            config_yaml=config_yaml,
            config_canonical_json_path=cfg_canon_path,
            session_jsonl=session_jsonl,
            _authority=claimed_directory.authority,
        )
        _remember_run_context(context)
        return context
    finally:
        claimed_directory.close()


def _open_reserved_text_artifact(path: Path) -> TextIO | None:
    authority = _reservation_authority(path.parent)
    if authority is None:
        authority = _in_process_run_authority(path.parent)
    if authority is None:
        return None
    if Path(path.name).name != path.name or path.name in {"", ".", ".."}:
        raise PlatformPathError(f"invalid reserved run artifact path: {path}")

    claimed = _open_authorized_run_directory(authority)
    file_fd: int | None = None
    try:
        claimed.verify_visible_path()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(
                path.name,
                flags,
                _PRIVATE_FILE_MODE,
                dir_fd=claimed.fd,
            )
        except OSError as exc:
            raise PlatformPathError(
                f"reserved run artifact cannot be opened safely: {path}"
            ) from exc
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise PlatformPathError(f"reserved run artifact is not a regular file: {path}")
        _set_descriptor_mode(file_fd, _PRIVATE_FILE_MODE)
        os.fsync(claimed.fd)
        claimed.verify_visible_path()
        handle = os.fdopen(file_fd, "w", encoding="utf-8", buffering=1)
        file_fd = None
        return handle
    finally:
        if file_fd is not None:
            os.close(file_fd)
        claimed.close()


def open_jsonl_writer(*, primary_path: Path, mirror_path: str | None) -> JsonlWriter:
    paths: list[Path] = [primary_path]

    if mirror_path and str(mirror_path).strip():
        mp = resolve_under_data_dir(str(mirror_path).strip())
        try:
            if mp.resolve() != primary_path.resolve():
                paths.append(mp)
        except Exception:
            # If resolve() fails (permissions), still compare raw Paths.
            if mp != primary_path:
                paths.append(mp)

    opened_files: dict[int, TextIO] = {}
    open_order = [*range(1, len(paths)), 0] if len(paths) > 1 else [0]
    try:
        for index in open_order:
            p = paths[index]
            if index == 0:
                reserved_handle = _open_reserved_text_artifact(p)
                if reserved_handle is not None:
                    opened_files[index] = reserved_handle
                    continue
            _mkdir_private(p.parent, parents=True, exist_ok=True)
            opened_files[index] = _open_private_text(
                p,
                exclusive=False,
                buffering=1,
            )
    except Exception:
        for handle in opened_files.values():
            try:
                handle.close()
            except Exception:
                pass
        raise
    files = [opened_files[index] for index in range(len(paths))]
    return JsonlWriter(files, paths)
