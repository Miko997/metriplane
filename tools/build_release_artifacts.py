# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build one immutable release artifact set from a validated source freeze."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from metriplane.release_control import (
    MILESTONES,
    RELEASE_BUILD_RECIPE,
    RELEASE_BUILD_RECIPE_DIGEST,
    ProviderAttestationVerifier,
    ReleaseInvocation,
    ReleaseControlError,
    _attestation_verifier_from_args,
    _release_version_pair,
    canonical_json,
    make_record,
    read_json,
    run_release_command,
    sha256_json,
    validate_record,
    validate_release_build_environment,
    validate_release_source_freeze_record,
    write_immutable_json,
)

if TYPE_CHECKING or __package__:
    from tools.release_artifacts import (
        create_manifest,
        inspect_sdist,
        release_artifacts,
        verify_manifest,
    )
else:
    from release_artifacts import (  # type: ignore[no-redef]
        create_manifest,
        inspect_sdist,
        release_artifacts,
        verify_manifest,
    )


ROOT: Final = Path(__file__).resolve().parents[1]
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_GIT_SHA: Final = re.compile(r"[0-9a-f]{40}")
_BUILD_RECIPE: Final = RELEASE_BUILD_RECIPE
BUILD_RECIPE_DIGEST: Final = RELEASE_BUILD_RECIPE_DIGEST


class ArtifactInputError(ValueError):
    """The invocation or an input record is malformed."""


class ArtifactBuildBlocked(RuntimeError):
    """The artifact build cannot produce authoritative immutable output."""


@dataclass(frozen=True)
class BuildInputs:
    repository: Path
    target_resolution: dict[str, Any]
    source_freeze: dict[str, Any]
    milestone: str
    package_version: str
    release_tag: str
    source_sha: str
    source_tree: str
    source_digest: str
    build_recipe_digest: str
    synthetic: bool


def _path_argument(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("path cannot be empty")
    return Path(value)


def _keyring_argument(value: str) -> str:
    _path_argument(value)
    return value


def _digest_argument(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("digest must be a lowercase SHA-256 value")
    return value


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        description="Build the exact section-9B release artifacts and immutable manifest.",
        epilog=(
            "The superseded --dist, --version, --output, --invocation-id, and "
            "--sequence flags are intentionally unsupported."
        ),
    )
    parser.add_argument("--target-resolution", type=_path_argument, required=True)
    parser.add_argument("--source-freeze", type=_path_argument, required=True)
    parser.add_argument("--out-dir", type=_path_argument, required=True)
    parser.add_argument("--manifest", type=_path_argument, required=True)
    parser.add_argument("--invocation-dir", type=_path_argument, required=True)
    parser.add_argument("--provider-attestation-keyring", type=_keyring_argument)
    parser.add_argument("--provider-attestation-keyring-digest", type=_digest_argument)
    parser.add_argument("--authority-policy-digest", type=_digest_argument)
    arguments = list(argv) if argv is not None else sys.argv[1:]
    accepted = {
        "--help",
        "--manifest",
        "--out-dir",
        "--source-freeze",
        "--target-resolution",
        "--invocation-dir",
        "--provider-attestation-keyring",
        "--provider-attestation-keyring-digest",
        "--authority-policy-digest",
    }
    unknown = [
        value
        for value in arguments
        if value.startswith("--") and value.partition("=")[0] not in accepted
    ]
    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    return parser.parse_args(arguments)


def _required_string(data: Mapping[str, Any], field: str, pattern: re.Pattern[str]) -> str:
    value = data.get(field)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ArtifactBuildBlocked(f"{field} is missing or invalid")
    return value


def _read_record(path: Path, expected_type: str) -> dict[str, Any]:
    try:
        record = read_json(path)
        validate_record(record, expected_type)
    except ReleaseControlError as exc:
        raise ArtifactInputError(str(exc)) from exc
    if record["status"] != "PASS":
        raise ArtifactBuildBlocked(f"{expected_type} is not PASS")
    return record


def _load_inputs(
    target_resolution_path: Path,
    source_freeze_path: Path,
    *,
    fixture_mode: bool,
    repository: Path | None = None,
    attestation_verifier: ProviderAttestationVerifier | None = None,
    expected_authority_policy_digest: str | None = None,
) -> BuildInputs:
    if expected_authority_policy_digest is not None:
        _required_string(
            {"authority_policy_digest": expected_authority_policy_digest},
            "authority_policy_digest",
            _DIGEST,
        )
        raise ArtifactBuildBlocked("source-freeze authority-policy replay hook is not implemented")
    target_resolution = _read_record(target_resolution_path, "release-target-resolution")
    source_freeze = _read_record(source_freeze_path, "release-source-freeze")
    target_data = target_resolution["data"]
    source_data = source_freeze["data"]
    if not isinstance(target_data, dict) or not isinstance(source_data, dict):
        raise ArtifactInputError("release input data must be an object")

    target_synthetic = target_resolution["synthetic"]
    source_synthetic = source_freeze["synthetic"]
    if target_synthetic is not source_synthetic:
        raise ArtifactBuildBlocked("target resolution and source freeze authority modes differ")
    if target_synthetic is True and not fixture_mode:
        raise ArtifactBuildBlocked("synthetic release inputs require fixture mode")

    milestone = target_data.get("milestone")
    if not isinstance(milestone, str) or milestone not in MILESTONES:
        raise ArtifactBuildBlocked("target resolution milestone is missing or unknown")
    if source_data.get("milestone") != milestone:
        raise ArtifactBuildBlocked("source freeze and target resolution milestones differ")
    if source_data.get("dirty") is not False:
        raise ArtifactBuildBlocked("source freeze does not prove a clean tree")

    selected_version = target_data.get("selected_package_version")
    release_tag = target_data.get("selected_release_tag")
    if not isinstance(selected_version, str) or not isinstance(release_tag, str):
        raise ArtifactBuildBlocked(
            "selected_package_version and selected_release_tag must be strings"
        )
    if not selected_version.startswith("v"):
        raise ArtifactBuildBlocked("selected_package_version must retain its legacy v prefix")
    # The target record retains its established v-prefixed wire value. Project
    # exactly one prefix for the shared current-version grammar and build backend.
    package_version = selected_version[1:]
    try:
        version_identity = _release_version_pair(package_version, release_tag)
    except ReleaseControlError as exc:
        raise ArtifactBuildBlocked(
            "selected_package_version or selected_release_tag is invalid: " + str(exc)
        ) from exc
    if f"v{version_identity[0]}.{version_identity[1]}" != milestone:
        raise ArtifactBuildBlocked("selected package version is outside the resolved milestone")
    source_sha = _required_string(source_data, "source_sha", _GIT_SHA)
    source_tree = _required_string(source_data, "source_tree", _GIT_SHA)
    source_digest = _required_string(source_data, "freeze_digest", _DIGEST)
    recipe_digest = _required_string(source_data, "build_recipe_digest", _DIGEST)
    if recipe_digest != BUILD_RECIPE_DIGEST:
        raise ArtifactBuildBlocked("source freeze names an unsupported artifact build recipe")

    repository = (
        Path(_git_output("rev-parse", "--show-toplevel")) if repository is None else repository
    )
    validate_release_source_freeze_record(
        source_freeze,
        source_freeze_path.absolute(),
        repository=repository,
        live=not fixture_mode,
        attestation_verifier=attestation_verifier,
    )

    return BuildInputs(
        repository=repository,
        target_resolution=target_resolution,
        source_freeze=source_freeze,
        milestone=milestone,
        package_version=package_version,
        release_tag=release_tag,
        source_sha=source_sha,
        source_tree=source_tree,
        source_digest=source_digest,
        build_recipe_digest=recipe_digest,
        synthetic=bool(target_synthetic),
    )


def _git_output(*arguments: str, repository: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=Path.cwd() if repository is None else repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArtifactBuildBlocked("cannot inspect the frozen Git source") from exc
    return completed.stdout.strip()


def _verify_frozen_source(inputs: BuildInputs) -> int:
    if _git_output("rev-parse", "HEAD", repository=inputs.repository) != inputs.source_sha:
        raise ArtifactBuildBlocked("checked-out HEAD differs from the source freeze")
    if _git_output("rev-parse", "HEAD^{tree}", repository=inputs.repository) != inputs.source_tree:
        raise ArtifactBuildBlocked("checked-out tree differs from the source freeze")
    if _git_output("status", "--porcelain", "--untracked-files=no", repository=inputs.repository):
        raise ArtifactBuildBlocked("tracked working tree differs from the source freeze")
    timestamp = _git_output(
        "show", "-s", "--format=%ct", inputs.source_sha, repository=inputs.repository
    )
    try:
        epoch = int(timestamp)
    except ValueError as exc:
        raise ArtifactBuildBlocked("source commit has no deterministic build epoch") from exc
    if epoch < 0:
        raise ArtifactBuildBlocked("source commit has an invalid build epoch")
    return epoch


def _archive_source(
    source_sha: str, temporary_root: Path, *, repository: Path | None = None
) -> Path:
    archive = temporary_root / "source.tar"
    source_dir = temporary_root / "source"
    try:
        subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                "--prefix=source/",
                f"--output={archive}",
                source_sha,
            ],
            cwd=Path.cwd() if repository is None else repository,
            check=True,
            capture_output=True,
            text=True,
        )
        with tarfile.open(archive, mode="r:") as source_archive:
            source_archive.extractall(temporary_root, filter="data")
    except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        raise ArtifactBuildBlocked("cannot materialize the frozen Git source") from exc
    if not source_dir.is_dir():
        raise ArtifactBuildBlocked("frozen Git source archive is incomplete")
    return source_dir


def _run_build(source_dir: Path, dist_dir: Path, *, source_date_epoch: int) -> None:
    validate_release_build_environment(source_dir)
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    commands = (
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--sdist",
            "--wheel",
            "--outdir",
            str(dist_dir),
            str(source_dir),
        ],
        [sys.executable, "-m", "twine", "check", "--strict"],
    )
    try:
        subprocess.run(
            commands[0],
            cwd=source_dir,
            env=environment,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
        )
        artifacts = sorted(dist_dir.iterdir(), key=lambda path: path.name)
        subprocess.run(
            [*commands[1], *(str(path) for path in artifacts)],
            cwd=source_dir,
            env=environment,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArtifactBuildBlocked("canonical artifact build or metadata check failed") from exc


def _artifact_media_type(path: Path) -> str:
    if path.name.endswith(".whl"):
        return "application/vnd.pypa.wheel+zip"
    if path.name.endswith(".tar.gz"):
        return "application/gzip"
    raise ArtifactBuildBlocked(f"unsupported release artifact type: {path.name}")


def _fingerprint_artifacts(
    dist_dir: Path,
    checksum_path: Path,
    package_version: str,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    digests = create_manifest(dist_dir, checksum_path, package_version)
    if verify_manifest(dist_dir, checksum_path, package_version) != digests:
        raise ArtifactBuildBlocked("artifact fingerprint read-back changed")
    wheel, sdist = release_artifacts(dist_dir, package_version)
    inspect_sdist(sdist, package_version)
    artifacts = [
        {
            "media_type": _artifact_media_type(path),
            "path": path.name,
            "sha256": digests[path.name],
            "size": path.stat().st_size,
        }
        for path in sorted((wheel, sdist), key=lambda item: item.name)
    ]
    return artifacts, digests


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _validate_destinations(out_dir: Path, manifest: Path) -> None:
    resolved_out = out_dir.resolve(strict=False)
    resolved_manifest = manifest.resolve(strict=False)
    try:
        resolved_manifest.relative_to(resolved_out)
    except ValueError:
        pass
    else:
        raise ArtifactInputError("manifest must be outside the artifact directory")
    if _path_exists(out_dir):
        raise ArtifactBuildBlocked(f"refusing to overwrite artifact directory: {out_dir}")
    if _path_exists(manifest):
        raise ArtifactBuildBlocked(f"refusing to overwrite artifact manifest: {manifest}")


def _rollback_artifacts(installed: Sequence[tuple[Path, Path]], out_dir: Path) -> None:
    for source, destination in reversed(installed):
        try:
            source_stat = source.stat()
            destination_stat = destination.stat(follow_symlinks=False)
            if (source_stat.st_dev, source_stat.st_ino) == (
                destination_stat.st_dev,
                destination_stat.st_ino,
            ):
                destination.unlink()
        except OSError:
            continue
    try:
        out_dir.rmdir()
    except OSError:
        pass


def _install_artifacts(staged_dir: Path, out_dir: Path) -> list[tuple[Path, Path]]:
    installed: list[tuple[Path, Path]] = []
    try:
        out_dir.mkdir(mode=0o755)
        for source in sorted(staged_dir.iterdir(), key=lambda path: path.name):
            source.chmod(0o444)
            destination = out_dir / source.name
            os.link(source, destination, follow_symlinks=False)
            installed.append((source, destination))
    except OSError as exc:
        _rollback_artifacts(installed, out_dir)
        raise ArtifactBuildBlocked("cannot atomically install immutable artifacts") from exc
    return installed


def _build_manifest(
    inputs: BuildInputs, artifacts: list[dict[str, object]], context: ReleaseInvocation
) -> dict[str, Any]:
    target_digest = sha256_json(inputs.target_resolution)
    source_freeze_digest = sha256_json(inputs.source_freeze)
    artifact_set_digest = sha256_json(artifacts)
    invocation_id = context.intent["invocation_id"]
    return make_record(
        "release-artifact-manifest",
        {
            "artifact_set_digest": artifact_set_digest,
            "artifacts": artifacts,
            "build_invocation_id": invocation_id,
            "build_recipe_digest": inputs.build_recipe_digest,
            "milestone": inputs.milestone,
            "source_digest": inputs.source_digest,
            "source_freeze_digest": source_freeze_digest,
            "target_resolution_digest": target_digest,
            "invocation_root_locator": "invocations",
            "producer_intent_digest": sha256_json(context.intent),
        },
        invocation_id=invocation_id,
        sequence=context.intent["sequence"],
        synthetic=inputs.synthetic,
    )


def _execute(args: argparse.Namespace, *, context: ReleaseInvocation) -> None:
    fixture_mode = os.environ.get("METRIPLANE_RELEASE_FIXTURE_MODE") == "1"
    if Path(args.invocation_dir).absolute() != context.directory or context.intent["sequence"] != 1:
        raise ArtifactBuildBlocked(
            "artifact build requires its first reserved invocation in a new staging run"
        )
    if (
        args.target_resolution.absolute() != context.root / "target-resolution.json"
        or args.source_freeze.absolute() != context.root / "source-freeze.json"
    ):
        raise ArtifactInputError(
            "artifact inputs must be the canonical records in the invocation run root"
        )
    attestation_verifier = _attestation_verifier_from_args(
        args, live=not fixture_mode, context=context
    )
    inputs = _load_inputs(
        args.target_resolution,
        args.source_freeze,
        fixture_mode=fixture_mode,
        attestation_verifier=attestation_verifier,
        expected_authority_policy_digest=args.authority_policy_digest,
    )
    _validate_destinations(args.out_dir, args.manifest)
    source_date_epoch = _verify_frozen_source(inputs)
    validate_release_build_environment(inputs.repository)
    temporary_root = context.directory / "workspace"
    temporary_root.mkdir()
    source_dir = _archive_source(inputs.source_sha, temporary_root, repository=inputs.repository)
    staged_dist = context.directory / "staged" / "artifacts"
    staged_dist.mkdir()
    _run_build(source_dir, staged_dist, source_date_epoch=source_date_epoch)
    artifacts, _ = _fingerprint_artifacts(
        staged_dist, temporary_root / "SHA256SUMS", inputs.package_version
    )
    _verify_frozen_source(inputs)
    manifest_record = _build_manifest(inputs, artifacts, context)
    write_immutable_json(context.directory / "staged" / args.manifest.name, manifest_record)


def _emit_result(status: str, reason: str) -> None:
    print(
        canonical_json(
            {"reason": reason, "status": status, "tool": "build_release_artifacts.py"}
        ).decode("utf-8")
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if "--help" in arguments or "-h" in arguments:
        _parse_args(arguments)
        return 0
    return run_release_command(
        "build_release_artifacts.py", arguments, artifact_installer=_install_artifacts
    )


if __name__ == "__main__":
    raise SystemExit(main())
