# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Validate the immutable files used by the package publication workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

PROJECT_NAME = "metriplane"
GITHUB_API_VERSION = "2022-11-28"
PUBLISH_BROKER_APP_ID = 4722589
PUBLISH_BROKER_APP_SLUG = "metriplane-main-health-publisher"
PUBLISH_LEASE_CHECK_NAME = "Release serialization / required"
PUBLISH_LEASE_REF_PREFIX = "refs/heads/release-leases/pypi-"
_SHA256_LINE = re.compile(r"([0-9a-f]{64})  ([^/\\]+)")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.!+_-]*")
_GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_POSITIVE_INTEGER = re.compile(r"[1-9][0-9]*\Z")
_FORBIDDEN_ARCHIVE_PARTS = {
    ".DS_Store",
    ".env",
    ".git",
    ".github",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
}
_FORBIDDEN_ARCHIVE_SUFFIXES = {
    ".avi",
    ".7z",
    ".env",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".key",
    ".mov",
    ".mp4",
    ".p12",
    ".pem",
    ".png",
    ".pyc",
    ".pyo",
    ".tar",
    ".zip",
}
_ALLOWED_SDIST_TOP_LEVEL = {
    "LICENSE",
    "NOTICE",
    "PKG-INFO",
    "README.md",
    "integrations",
    "metriplane",
    "metriplane.egg-info",
    "pyproject.toml",
    "setup.cfg",
    "tests",
}
_REQUIRED_SDIST_PATHS = {
    "LICENSE",
    "NOTICE",
    "README.md",
    "pyproject.toml",
    "metriplane/__init__.py",
    "metriplane/cli.py",
    "metriplane/demo/__init__.py",
    "metriplane/demo/assets/assembly_cell_missing_tool.jsonl",
    "metriplane/demo/assets/assembly_cell/assets.yaml",
    "metriplane/demo/assets/assembly_cell/contracts.yaml",
    "metriplane/demo/assets/assembly_cell/process.yaml",
    "metriplane/demo/assets/assembly_cell/work_orders.csv",
    "metriplane/demo/assets/assembly_cell/workspace.yaml",
}


class ReleaseArtifactError(ValueError):
    """Raised when release files do not satisfy the publication contract."""


@dataclass(frozen=True)
class PublishLease:
    repository: str
    release_sha: str
    run_id: str
    run_attempt: str
    ref: str
    external_id: str


def _publish_lease(
    repository: str,
    release_sha: str,
    run_id: str,
    run_attempt: str,
) -> PublishLease:
    if _GITHUB_REPOSITORY.fullmatch(repository) is None:
        raise ReleaseArtifactError("Invalid GitHub repository identity")
    if _GIT_SHA.fullmatch(release_sha) is None:
        raise ReleaseArtifactError("Release commit must be a lowercase 40-character Git SHA")
    if _POSITIVE_INTEGER.fullmatch(run_id) is None:
        raise ReleaseArtifactError("GitHub run ID must be a positive integer")
    if _POSITIVE_INTEGER.fullmatch(run_attempt) is None:
        raise ReleaseArtifactError("GitHub run attempt must be a positive integer")
    return PublishLease(
        repository=repository,
        release_sha=release_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        ref=f"{PUBLISH_LEASE_REF_PREFIX}{run_id}-{run_attempt}",
        external_id=(f"metriplane-publish-lease.v1:{run_id}:{run_attempt}:{release_sha}"),
    )


def _github_request(
    repository: str,
    path: str,
    token: str,
) -> Any:
    if not token.strip():
        raise ReleaseArtifactError("GitHub token is required for publish-lease operations")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "metriplane-publish-lease",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except (OSError, TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise ReleaseArtifactError(
            f"GitHub publish-lease request failed for GET {path}: {exc}"
        ) from exc
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseArtifactError("GitHub publish-lease response is not JSON") from exc


def _lease_ref_api_path(lease: PublishLease) -> str:
    return "git/ref/heads/" + lease.ref.removeprefix("refs/heads/")


def _require_ref(
    lease: PublishLease,
    *,
    ref: str,
    path: str,
    token: str,
) -> None:
    value = _github_request(lease.repository, path, token)
    obj = value.get("object") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("ref") != ref
        or not isinstance(obj, Mapping)
        or obj.get("type") != "commit"
        or obj.get("sha") != lease.release_sha
    ):
        raise ReleaseArtifactError(
            f"GitHub ref {ref!r} does not resolve exactly to {lease.release_sha}"
        )


def _require_main(lease: PublishLease, token: str) -> None:
    _require_ref(
        lease,
        ref="refs/heads/main",
        path="git/ref/heads/main",
        token=token,
    )


def _require_lease_ref(lease: PublishLease, token: str) -> None:
    _require_ref(
        lease,
        ref=lease.ref,
        path=_lease_ref_api_path(lease),
        token=token,
    )


def _require_lease_ref_absent(lease: PublishLease, token: str) -> None:
    prefix = lease.ref.removeprefix("refs/")
    value = _github_request(
        lease.repository,
        f"git/matching-refs/{prefix}",
        token,
    )
    if value != []:
        raise ReleaseArtifactError("GitHub publish-lease ref still exists after App reconciliation")


def _lease_check(lease: PublishLease, token: str) -> tuple[int, str, str | None] | None:
    query = urlencode(
        {
            "check_name": PUBLISH_LEASE_CHECK_NAME,
            "filter": "all",
            "per_page": 100,
        }
    )
    value = _github_request(
        lease.repository,
        f"commits/{lease.release_sha}/check-runs?{query}",
        token,
    )
    runs = value.get("check_runs") if isinstance(value, Mapping) else None
    total = value.get("total_count") if isinstance(value, Mapping) else None
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or not isinstance(runs, list)
        or total != len(runs)
        or total > 100
        or any(not isinstance(run, Mapping) for run in runs)
    ):
        raise ReleaseArtifactError(
            "GitHub publish-lease check inventory is incomplete or malformed"
        )
    matches = [run for run in runs if run.get("external_id") == lease.external_id]
    if not matches:
        return None
    if len(matches) != 1:
        raise ReleaseArtifactError("GitHub returned duplicate publish-lease acknowledgments")
    run = matches[0]
    app = run.get("app")
    check_id = run.get("id")
    status = run.get("status")
    conclusion = run.get("conclusion")
    if (
        isinstance(check_id, bool)
        or not isinstance(check_id, int)
        or check_id <= 0
        or run.get("name") != PUBLISH_LEASE_CHECK_NAME
        or run.get("head_sha") != lease.release_sha
        or not isinstance(app, Mapping)
        or app.get("id") != PUBLISH_BROKER_APP_ID
        or app.get("slug") != PUBLISH_BROKER_APP_SLUG
        or status not in {"in_progress", "completed"}
        or (status == "in_progress" and conclusion is not None)
        or (status == "completed" and not isinstance(conclusion, str))
    ):
        raise ReleaseArtifactError("GitHub publish-lease acknowledgment identity is malformed")
    return check_id, status, conclusion


def _wait_for_lease_check(
    lease: PublishLease,
    token: str,
    *,
    expected_status: str,
    expected_check_id: int | None,
    attempts: int,
    delay_seconds: float,
) -> int:
    if attempts < 1 or delay_seconds < 0:
        raise ReleaseArtifactError("Publish-lease retry settings must be non-negative")
    for attempt in range(1, attempts + 1):
        observed = _lease_check(lease, token)
        if observed is not None:
            check_id, status, conclusion = observed
            if expected_check_id is not None and check_id != expected_check_id:
                raise ReleaseArtifactError("GitHub publish-lease check identity changed")
            if expected_status == "in_progress":
                if status == "in_progress":
                    return check_id
                raise ReleaseArtifactError("GitHub publish lease ended before publication")
            if status == "completed":
                if conclusion != "success":
                    raise ReleaseArtifactError(
                        f"GitHub publish-lease reconciliation concluded {conclusion!r}"
                    )
                return check_id
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise ReleaseArtifactError(
        f"GitHub App did not acknowledge publish lease state {expected_status!r}"
    )


def assert_publish_lease(lease: PublishLease, token: str) -> int:
    """Prove that the App-acknowledged lease still fences exact current main."""

    _require_lease_ref(lease, token)
    first_check = _wait_for_lease_check(
        lease,
        token,
        expected_status="in_progress",
        expected_check_id=None,
        attempts=1,
        delay_seconds=0,
    )
    _require_main(lease, token)
    _require_lease_ref(lease, token)
    second_check = _wait_for_lease_check(
        lease,
        token,
        expected_status="in_progress",
        expected_check_id=first_check,
        attempts=1,
        delay_seconds=0,
    )
    return second_check


def acquire_publish_lease(
    lease: PublishLease,
    token: str,
    *,
    attempts: int,
    delay_seconds: float,
) -> int:
    """Wait for the main-update broker to create and acknowledge its exact lease."""

    _require_main(lease, token)
    check_id = _wait_for_lease_check(
        lease,
        token,
        expected_status="in_progress",
        expected_check_id=None,
        attempts=attempts,
        delay_seconds=delay_seconds,
    )
    confirmed = assert_publish_lease(lease, token)
    if confirmed != check_id:
        raise ReleaseArtifactError(
            "GitHub publish-lease check identity changed after acknowledgment"
        )
    return check_id


def reconcile_publish_lease(
    lease: PublishLease,
    token: str,
    *,
    attempts: int,
    delay_seconds: float,
) -> int:
    """Require exact post-publication main and the App's terminal lease proof."""

    observed = _lease_check(lease, token)
    if observed is None:
        raise ReleaseArtifactError("GitHub App publish-lease acknowledgment is missing")
    check_id, status, _conclusion = observed
    if status == "in_progress":
        try:
            check_id = assert_publish_lease(lease, token)
        except ReleaseArtifactError:
            raced = _lease_check(lease, token)
            if raced is None or raced[0] != check_id or raced[1] != "completed":
                raise
            completed = _wait_for_lease_check(
                lease,
                token,
                expected_status="completed",
                expected_check_id=check_id,
                attempts=1,
                delay_seconds=0,
            )
        else:
            completed = _wait_for_lease_check(
                lease,
                token,
                expected_status="completed",
                expected_check_id=check_id,
                attempts=attempts,
                delay_seconds=delay_seconds,
            )
    else:
        completed = _wait_for_lease_check(
            lease,
            token,
            expected_status="completed",
            expected_check_id=check_id,
            attempts=1,
            delay_seconds=0,
        )
    _require_lease_ref_absent(lease, token)
    return _wait_for_lease_check(
        lease,
        token,
        expected_status="completed",
        expected_check_id=completed,
        attempts=1,
        delay_seconds=0,
    )


def _validate_version(version: str) -> None:
    if not _VERSION.fullmatch(version):
        raise ReleaseArtifactError(f"Invalid release version: {version!r}")


def _validate_artifact_names(names: Iterable[str], version: str) -> tuple[str, str]:
    _validate_version(version)
    names_tuple = tuple(sorted(names))
    wheel_names = [name for name in names_tuple if name.endswith(".whl")]
    sdist_names = [name for name in names_tuple if name.endswith((".tar.gz", ".zip"))]
    if len(names_tuple) != 2 or len(wheel_names) != 1 or len(sdist_names) != 1:
        raise ReleaseArtifactError(
            "Expected exactly one wheel and one source distribution; found: "
            + ", ".join(names_tuple)
        )

    prefix = f"{PROJECT_NAME}-{version}"
    wheel_name = wheel_names[0]
    sdist_name = sdist_names[0]
    if not wheel_name.startswith(f"{prefix}-"):
        raise ReleaseArtifactError(
            f"Wheel {wheel_name!r} does not contain release version {version!r}"
        )
    if sdist_name not in {f"{prefix}.tar.gz", f"{prefix}.zip"}:
        raise ReleaseArtifactError(
            f"Source distribution {sdist_name!r} does not match release version {version!r}"
        )
    return wheel_name, sdist_name


def release_artifacts(dist_dir: Path, version: str) -> tuple[Path, Path]:
    """Return the one wheel and one sdist after validating the directory."""

    if not dist_dir.is_dir():
        raise ReleaseArtifactError(f"Distribution directory does not exist: {dist_dir}")
    entries = sorted(dist_dir.iterdir(), key=lambda path: path.name)
    invalid = [path.name for path in entries if not path.is_file() or path.is_symlink()]
    if invalid:
        raise ReleaseArtifactError(
            "Distribution directory contains non-regular entries: " + ", ".join(invalid)
        )
    wheel_name, sdist_name = _validate_artifact_names((path.name for path in entries), version)
    return dist_dir / wheel_name, dist_dir / sdist_name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(dist_dir: Path, manifest_path: Path, version: str) -> dict[str, str]:
    """Write a canonical SHA-256 manifest for the two release files."""

    wheel, sdist = release_artifacts(dist_dir, version)
    digests = {
        path.name: sha256_file(path) for path in sorted((wheel, sdist), key=lambda p: p.name)
    }
    try:
        with manifest_path.open("x", encoding="utf-8") as manifest:
            manifest.write("".join(f"{digest}  {name}\n" for name, digest in digests.items()))
    except OSError as exc:
        raise ReleaseArtifactError(f"Cannot create release manifest: {exc}") from exc
    return digests


def read_manifest(manifest_path: Path, version: str) -> dict[str, str]:
    """Read a canonical two-file SHA-256 manifest."""

    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ReleaseArtifactError(f"Manifest is missing or not a regular file: {manifest_path}")
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    digests: dict[str, str] = {}
    for line in lines:
        match = _SHA256_LINE.fullmatch(line)
        if match is None:
            raise ReleaseArtifactError(f"Invalid SHA-256 manifest line: {line!r}")
        digest, name = match.groups()
        if name in digests:
            raise ReleaseArtifactError(f"Duplicate manifest entry: {name}")
        digests[name] = digest
    _validate_artifact_names(digests, version)
    return digests


def verify_manifest(dist_dir: Path, manifest_path: Path, version: str) -> dict[str, str]:
    """Verify the local release files against their canonical manifest."""

    wheel, sdist = release_artifacts(dist_dir, version)
    expected = read_manifest(manifest_path, version)
    actual = {path.name: sha256_file(path) for path in sorted((wheel, sdist), key=lambda p: p.name)}
    if actual != expected:
        raise ReleaseArtifactError(
            f"Release artifact SHA-256 mismatch\nexpected: {expected}\nactual:   {actual}"
        )
    return actual


def inspect_sdist(sdist_path: Path, version: str) -> None:
    """Reject unsafe or incomplete tar source distributions."""

    _validate_version(version)
    expected_root = f"{PROJECT_NAME}-{version}"
    if sdist_path.name != f"{expected_root}.tar.gz":
        raise ReleaseArtifactError(
            f"Only the canonical tar.gz source distribution is accepted: {sdist_path.name}"
        )

    relative_files: set[str] = set()
    try:
        with tarfile.open(sdist_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ReleaseArtifactError(f"Unsafe source-distribution path: {member.name!r}")
                if not member_path.parts or member_path.parts[0] != expected_root:
                    raise ReleaseArtifactError(
                        f"Unexpected source-distribution root: {member.name!r}"
                    )
                if member.issym() or member.islnk() or member.isdev():
                    raise ReleaseArtifactError(
                        f"Unsupported source-distribution member: {member.name!r}"
                    )
                relative = PurePosixPath(*member_path.parts[1:])
                if _FORBIDDEN_ARCHIVE_PARTS.intersection(relative.parts):
                    raise ReleaseArtifactError(
                        f"Unintended source-distribution member: {member.name!r}"
                    )
                if relative.parts and relative.parts[0] not in _ALLOWED_SDIST_TOP_LEVEL:
                    raise ReleaseArtifactError(
                        f"Unexpected source-distribution top-level path: {member.name!r}"
                    )
                if member.isfile():
                    if relative.suffix.lower() in _FORBIDDEN_ARCHIVE_SUFFIXES:
                        raise ReleaseArtifactError(
                            f"Unintended source-distribution member: {member.name!r}"
                        )
                    relative_files.add(relative.as_posix())
    except (tarfile.TarError, OSError) as exc:
        raise ReleaseArtifactError(f"Cannot inspect source distribution: {exc}") from exc

    missing = sorted(_REQUIRED_SDIST_PATHS - relative_files)
    if missing:
        raise ReleaseArtifactError(
            "Source distribution is missing required files: " + ", ".join(missing)
        )


def registry_digests(payload: Mapping[str, Any], version: str) -> dict[str, str]:
    """Extract and validate the release-file hashes from a PyPI JSON response."""

    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise ReleaseArtifactError("Registry response has no release-file list")

    digests: dict[str, str] = {}
    for entry in urls:
        if not isinstance(entry, Mapping):
            raise ReleaseArtifactError("Registry response contains an invalid file entry")
        name = entry.get("filename")
        entry_digests = entry.get("digests")
        digest = entry_digests.get("sha256") if isinstance(entry_digests, Mapping) else None
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ReleaseArtifactError("Registry response contains incomplete file metadata")
        if name in digests:
            raise ReleaseArtifactError(f"Registry response repeats file {name!r}")
        digests[name] = digest

    _validate_artifact_names(digests, version)
    if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests.values()):
        raise ReleaseArtifactError("Registry response contains an invalid SHA-256 digest")
    return dict(sorted(digests.items()))


def verify_registry_payload(
    payload: Mapping[str, Any], expected: Mapping[str, str], version: str
) -> None:
    actual = registry_digests(payload, version)
    if actual != dict(expected):
        raise ReleaseArtifactError(
            "Registry artifact identity does not match the build manifest\n"
            f"expected: {dict(expected)}\n"
            f"actual:   {actual}"
        )


def verify_registry(
    repository: str,
    project: str,
    version: str,
    manifest_path: Path,
    *,
    attempts: int,
    delay_seconds: float,
) -> None:
    """Wait for a registry release and compare every file hash with the build."""

    if attempts < 1 or delay_seconds < 0:
        raise ReleaseArtifactError("Retry settings must be non-negative")
    expected = read_manifest(manifest_path, version)
    url = f"{repository.rstrip('/')}/pypi/{project}/{version}/json"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "metriplane-release-gate"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, Mapping):
                raise ReleaseArtifactError("Registry returned a non-object JSON response")
            verify_registry_payload(payload, expected, version)
            return
        except (
            json.JSONDecodeError,
            OSError,
            ReleaseArtifactError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise ReleaseArtifactError(
        f"Registry did not expose the exact release artifacts after {attempts} attempts: "
        f"{last_error}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("create-manifest", "verify-manifest"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dist", type=Path, required=True)
        subparser.add_argument("--manifest", type=Path, required=True)
        subparser.add_argument("--version", required=True)

    inspect = subparsers.add_parser("inspect-sdist")
    inspect.add_argument("--sdist", type=Path, required=True)
    inspect.add_argument("--version", required=True)

    registry = subparsers.add_parser("verify-registry")
    registry.add_argument("--repository", required=True)
    registry.add_argument("--project", default=PROJECT_NAME)
    registry.add_argument("--version", required=True)
    registry.add_argument("--manifest", type=Path, required=True)
    registry.add_argument("--attempts", type=int, default=12)
    registry.add_argument("--delay-seconds", type=float, default=10)

    for command in (
        "acquire-publish-lease",
        "assert-publish-lease",
        "reconcile-publish-lease",
    ):
        lease = subparsers.add_parser(command)
        lease.add_argument("--repository", required=True)
        lease.add_argument("--release-sha", required=True)
        lease.add_argument("--run-id", required=True)
        lease.add_argument("--run-attempt", required=True)
        lease.add_argument("--github-token-env", default="GITHUB_TOKEN")
        if command != "assert-publish-lease":
            lease.add_argument("--attempts", type=int, default=60)
            lease.add_argument("--delay-seconds", type=float, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create-manifest":
            create_manifest(args.dist, args.manifest, args.version)
        elif args.command == "verify-manifest":
            verify_manifest(args.dist, args.manifest, args.version)
        elif args.command == "inspect-sdist":
            inspect_sdist(args.sdist, args.version)
        elif args.command == "verify-registry":
            verify_registry(
                args.repository,
                args.project,
                args.version,
                args.manifest,
                attempts=args.attempts,
                delay_seconds=args.delay_seconds,
            )
        else:
            lease = _publish_lease(
                args.repository,
                args.release_sha,
                args.run_id,
                args.run_attempt,
            )
            token = os.environ.get(args.github_token_env, "")
            if args.command == "acquire-publish-lease":
                check_id = acquire_publish_lease(
                    lease,
                    token,
                    attempts=args.attempts,
                    delay_seconds=args.delay_seconds,
                )
                state = "in_progress"
            elif args.command == "assert-publish-lease":
                check_id = assert_publish_lease(lease, token)
                state = "in_progress"
            else:
                check_id = reconcile_publish_lease(
                    lease,
                    token,
                    attempts=args.attempts,
                    delay_seconds=args.delay_seconds,
                )
                state = "completed"
            print(
                json.dumps(
                    {
                        "check_id": check_id,
                        "external_id": lease.external_id,
                        "ref": lease.ref,
                        "release_sha": lease.release_sha,
                        "state": state,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
    except ReleaseArtifactError as exc:
        print(f"release artifact check failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
