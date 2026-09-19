# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

import tools.release_artifacts as release_tool
from tools.release_artifacts import (
    _REQUIRED_SDIST_PATHS,
    PUBLISH_BROKER_APP_ID,
    PUBLISH_BROKER_APP_SLUG,
    PUBLISH_LEASE_CHECK_NAME,
    ReleaseArtifactError,
    _publish_lease,
    acquire_publish_lease,
    assert_publish_lease,
    create_build_info,
    create_manifest,
    inspect_sdist,
    inspect_wheel,
    read_manifest,
    reconcile_publish_lease,
    verify_manifest,
    verify_registry_payload,
)

VERSION = "0.3.0"
REPOSITORY = "Miko997/metriplane"
RELEASE_SHA = "a" * 40
RELEASE_TREE = "b" * 40


def test_editable_build_does_not_claim_an_embedded_distribution_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    command = object.__new__(release_tool.BoundBuildPy)
    command.editable_mode = True
    monkeypatch.setattr(
        release_tool._SetuptoolsBuildPy,
        "run",
        lambda instance: calls.append(instance),
    )
    monkeypatch.setattr(
        release_tool,
        "_source_build_info",
        lambda _root: pytest.fail("editable builds must use their live checkout at runtime"),
    )

    command.run()

    assert calls == [command]


class _LeaseApi:
    def __init__(
        self,
        *,
        complete_after_active_checks: int | None = None,
        drift_after_first_main_read: bool = False,
        wrong_app: bool = False,
    ) -> None:
        self.complete_after_active_checks = complete_after_active_checks
        self.drift_after_first_main_read = drift_after_first_main_read
        self.wrong_app = wrong_app
        self.check_reads = 0
        self.main_reads = 0
        self.calls: list[str] = []

    @property
    def completed(self) -> bool:
        return (
            self.complete_after_active_checks is not None
            and self.check_reads > self.complete_after_active_checks
        )

    def __call__(
        self,
        repository: str,
        path: str,
        token: str,
    ) -> Any:
        assert repository == REPOSITORY
        assert token == "test-token"
        self.calls.append(path)
        lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
        if path == "git/ref/heads/main":
            self.main_reads += 1
            sha = (
                "f" * 40
                if self.drift_after_first_main_read and self.main_reads > 1
                else RELEASE_SHA
            )
            return {
                "object": {"sha": sha, "type": "commit"},
                "ref": "refs/heads/main",
            }
        if path == release_tool._lease_ref_api_path(lease):
            return {
                "object": {"sha": RELEASE_SHA, "type": "commit"},
                "ref": lease.ref,
            }
        if path == f"git/matching-refs/{lease.ref.removeprefix('refs/')}":
            return [] if self.completed else [{"ref": lease.ref}]
        if path.startswith(f"commits/{RELEASE_SHA}/check-runs?"):
            self.check_reads += 1
            return {
                "check_runs": [
                    {
                        "app": {
                            "id": 1 if self.wrong_app else PUBLISH_BROKER_APP_ID,
                            "slug": PUBLISH_BROKER_APP_SLUG,
                        },
                        "conclusion": "success" if self.completed else None,
                        "external_id": lease.external_id,
                        "head_sha": RELEASE_SHA,
                        "id": 456,
                        "name": PUBLISH_LEASE_CHECK_NAME,
                        "status": "completed" if self.completed else "in_progress",
                    }
                ],
                "total_count": 1,
            }
        raise AssertionError(f"unexpected API request: GET {path}")


def _artifact_set(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"metriplane-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
    (dist / f"metriplane-{VERSION}.tar.gz").write_bytes(b"sdist")
    return dist, tmp_path / "SHA256SUMS"


def _clean_git_checkout(root: Path) -> tuple[str, str]:
    root.mkdir()
    (root / "tracked.txt").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Metriplane Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
    return commit, tree


def test_create_build_info_uses_clean_checkout_not_ambient_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    commit, tree = _clean_git_checkout(checkout)
    output = tmp_path / "stage" / "metriplane" / "build-info.json"
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)

    payload = create_build_info(checkout, output)

    assert payload == {
        "schema_version": "metriplane.build-info.v1",
        "source_commit": commit,
        "source_dirty": False,
        "source_tree": tree,
        "status": "bound",
    }
    assert output.read_bytes() == json.dumps(
        payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def test_create_build_info_rejects_dirty_or_reused_output(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    _clean_git_checkout(checkout)
    output = tmp_path / "stage" / "metriplane" / "build-info.json"
    create_build_info(checkout, output)
    with pytest.raises(FileExistsError):
        create_build_info(checkout, output)

    (checkout / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ReleaseArtifactError, match="must be clean"):
        create_build_info(checkout, tmp_path / "other" / "build-info.json")


def test_standard_build_embeds_exact_identity_in_installed_wheel_and_sdist(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    checkout = tmp_path / "checkout"
    shutil.copytree(
        repository_root / "metriplane",
        checkout / "metriplane",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (checkout / "tools").mkdir()
    shutil.copy2(repository_root / "tools" / "release_artifacts.py", checkout / "tools")
    (checkout / ".gitignore").write_text(
        "*.egg-info/\nbuild/\n__pycache__/\n*.pyc\ninjected-review.jsonl\n",
        encoding="utf-8",
    )
    (checkout / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools==82.0.1"]
build-backend = "setuptools.build_meta"

[project]
name = "metriplane"
version = "0.0.0"

[tool.setuptools]
include-package-data = true

[tool.setuptools.cmdclass]
build_py = "tools.release_artifacts.BoundBuildPy"
sdist = "tools.release_artifacts.BoundSdist"

[tool.setuptools.packages.find]
where = ["."]
include = ["metriplane*"]

[tool.setuptools.package-data]
metriplane = ["build-info.json"]
"metriplane.demo" = ["assets/*.jsonl"]
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "config", "user.name", "Metriplane Test"], cwd=checkout, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=checkout, check=True
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-qm", "build fixture"], cwd=checkout, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=checkout, text=True
    ).strip()

    injected = checkout / "metriplane" / "demo" / "assets" / "injected-review.jsonl"
    injected.write_text('{"ignored":"but packageable"}\n', encoding="utf-8")
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout, text=True
    ).strip()
    rejected = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--wheel"],
        cwd=checkout,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "Packaged source is not tracked by Git" in (rejected.stdout + rejected.stderr)
    injected.unlink()
    shutil.rmtree(checkout / "build")

    dist = tmp_path / "dist"
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--sdist",
            "--wheel",
            "--outdir",
            str(dist),
        ],
        cwd=checkout,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = json.dumps(
        {
            "schema_version": "metriplane.build-info.v1",
            "source_commit": commit,
            "source_dirty": False,
            "source_tree": tree,
            "status": "bound",
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("metriplane/build-info.json") == expected
        archive.extractall(tmp_path / "installed")
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = archive.getnames()
        build_info = next(name for name in names if name.endswith("/metriplane/build-info.json"))
        assert archive.extractfile(build_info).read() == expected
        assert any(name.endswith("/tools/release_artifacts.py") for name in names)
    inspect_wheel(wheel, "0.0.0", expected_commit=commit, expected_tree=tree)
    assert (checkout / "metriplane" / "build-info.json").read_bytes() == (
        b'{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        b'"source_dirty":null,"source_tree":null,"status":"unbound"}'
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from dataclasses import asdict; "
                "from metriplane.provenance.run_provenance import get_git_info; "
                "print(json.dumps(asdict(get_git_info()), sort_keys=True))"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path / "installed")},
        check=True,
        capture_output=True,
        text=True,
    )
    installed = json.loads(completed.stdout)
    assert installed["authority"] == "embedded-build-info"
    assert installed["commit"] == commit
    assert installed["tree"] == tree
    assert installed["dirty"] is False


def test_publish_lease_identity_is_exact() -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")

    assert lease.ref == "refs/heads/release-leases/pypi-123-2"
    assert lease.external_id == f"metriplane-publish-lease.v1:123:2:{RELEASE_SHA}"
    assert release_tool._lease_ref_api_path(lease).startswith("git/ref/heads/")
    with pytest.raises(ReleaseArtifactError, match="repository identity"):
        _publish_lease("not-a-repository", RELEASE_SHA, "123", "2")
    with pytest.raises(ReleaseArtifactError, match="positive integer"):
        _publish_lease(REPOSITORY, RELEASE_SHA, "0", "2")


def test_publish_lease_requires_app_ack_and_stable_main(monkeypatch: pytest.MonkeyPatch) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    api = _LeaseApi()
    monkeypatch.setattr(release_tool, "_github_request", api)

    check_id = acquire_publish_lease(
        lease,
        "test-token",
        attempts=1,
        delay_seconds=0,
    )

    assert check_id == 456
    assert assert_publish_lease(lease, "test-token") == 456
    assert "git/refs" not in api.calls


def test_publish_lease_rejects_wrong_app_and_post_ack_main_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    wrong_app = _LeaseApi(wrong_app=True)
    monkeypatch.setattr(release_tool, "_github_request", wrong_app)
    with pytest.raises(ReleaseArtifactError, match="acknowledgment identity"):
        acquire_publish_lease(
            lease,
            "test-token",
            attempts=1,
            delay_seconds=0,
        )

    drift = _LeaseApi(drift_after_first_main_read=True)
    monkeypatch.setattr(release_tool, "_github_request", drift)
    with pytest.raises(ReleaseArtifactError, match="refs/heads/main"):
        acquire_publish_lease(
            lease,
            "test-token",
            attempts=1,
            delay_seconds=0,
        )
    assert all(not path.startswith("git/matching-refs/") for path in drift.calls)


def test_publish_lease_is_released_only_after_exact_main_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    api = _LeaseApi(complete_after_active_checks=3)
    monkeypatch.setattr(release_tool, "_github_request", api)

    check_id = reconcile_publish_lease(
        lease,
        "test-token",
        attempts=1,
        delay_seconds=0,
    )

    assert check_id == 456
    absent_index = next(
        index for index, path in enumerate(api.calls) if path.startswith("git/matching-refs/")
    )
    main_index = max(index for index, path in enumerate(api.calls) if path == "git/ref/heads/main")
    assert main_index < absent_index

    drift = _LeaseApi(drift_after_first_main_read=True)
    drift.main_reads = 1
    monkeypatch.setattr(release_tool, "_github_request", drift)
    with pytest.raises(ReleaseArtifactError, match="refs/heads/main"):
        reconcile_publish_lease(
            lease,
            "test-token",
            attempts=1,
            delay_seconds=0,
        )
    assert all(not path.startswith("git/matching-refs/") for path in drift.calls)


def test_publish_lease_requires_the_app_terminal_before_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    api = _LeaseApi()
    monkeypatch.setattr(release_tool, "_github_request", api)

    with pytest.raises(ReleaseArtifactError, match="state 'completed'"):
        reconcile_publish_lease(
            lease,
            "test-token",
            attempts=1,
            delay_seconds=0,
        )
    assert all(not path.startswith("git/matching-refs/") for path in api.calls)


def test_publish_lease_accepts_an_already_published_exact_app_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    api = _LeaseApi(complete_after_active_checks=0)
    monkeypatch.setattr(release_tool, "_github_request", api)

    check_id = reconcile_publish_lease(
        lease,
        "test-token",
        attempts=1,
        delay_seconds=0,
    )

    assert check_id == 456
    assert any(path.startswith("git/matching-refs/") for path in api.calls)


def test_publish_lease_accepts_the_same_app_terminal_during_observer_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = _publish_lease(REPOSITORY, RELEASE_SHA, "123", "2")
    api = _LeaseApi(complete_after_active_checks=1)
    monkeypatch.setattr(release_tool, "_github_request", api)

    check_id = reconcile_publish_lease(
        lease,
        "test-token",
        attempts=1,
        delay_seconds=0,
    )

    assert check_id == 456
    assert any(path.startswith("git/matching-refs/") for path in api.calls)


def test_manifest_fingerprints_exactly_one_wheel_and_sdist(tmp_path: Path) -> None:
    dist, manifest = _artifact_set(tmp_path)

    created = create_manifest(dist, manifest, VERSION)

    assert read_manifest(manifest, VERSION) == created
    assert verify_manifest(dist, manifest, VERSION) == created
    assert set(created) == {
        f"metriplane-{VERSION}-py3-none-any.whl",
        f"metriplane-{VERSION}.tar.gz",
    }
    with pytest.raises(ReleaseArtifactError, match="Cannot create release manifest"):
        create_manifest(dist, manifest, VERSION)


def test_manifest_rejects_tampering_and_extra_files(tmp_path: Path) -> None:
    dist, manifest = _artifact_set(tmp_path)
    create_manifest(dist, manifest, VERSION)
    (dist / f"metriplane-{VERSION}.tar.gz").write_bytes(b"changed")

    with pytest.raises(ReleaseArtifactError, match="SHA-256 mismatch"):
        verify_manifest(dist, manifest, VERSION)

    (dist / "unexpected.txt").write_text("not a distribution", encoding="utf-8")
    with pytest.raises(ReleaseArtifactError, match="exactly one wheel"):
        create_manifest(dist, manifest, VERSION)


def test_registry_payload_must_match_both_build_hashes(tmp_path: Path) -> None:
    dist, manifest = _artifact_set(tmp_path)
    expected = create_manifest(dist, manifest, VERSION)
    payload = {
        "urls": [
            {"filename": name, "digests": {"sha256": digest}}
            for name, digest in reversed(tuple(expected.items()))
        ]
    }

    verify_registry_payload(payload, expected, VERSION)

    payload["urls"][0]["digests"]["sha256"] = "0" * 64
    with pytest.raises(ReleaseArtifactError, match="does not match"):
        verify_registry_payload(payload, expected, VERSION)


def _write_tar(
    path: Path,
    names: set[str],
    *,
    root: str,
    build_info: bytes | None = None,
) -> None:
    canonical_build_info = json.dumps(
        {
            "schema_version": "metriplane.build-info.v1",
            "source_commit": RELEASE_SHA,
            "source_dirty": False,
            "source_tree": RELEASE_TREE,
            "status": "bound",
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    with tarfile.open(path, mode="w:gz") as archive:
        for name in sorted(names):
            payload = (
                (build_info if build_info is not None else canonical_build_info)
                if name == "metriplane/build-info.json"
                else (name.encode("utf-8") or b"x")
            )
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_sdist_inspection_requires_resources_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    sdist = tmp_path / f"metriplane-{VERSION}.tar.gz"
    root = f"metriplane-{VERSION}"
    _write_tar(sdist, set(_REQUIRED_SDIST_PATHS), root=root)
    inspect_sdist(
        sdist,
        VERSION,
        expected_commit=RELEASE_SHA,
        expected_tree=RELEASE_TREE,
    )

    for invalid_build_info in (
        b"not-json",
        b'{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        b'"source_dirty":null,"source_tree":null,"status":"unbound"}',
        json.dumps(
            {
                "schema_version": "metriplane.build-info.v1",
                "source_commit": "c" * 40,
                "source_dirty": False,
                "source_tree": RELEASE_TREE,
                "status": "bound",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        json.dumps(
            {
                "schema_version": "metriplane.build-info.v1",
                "source_commit": RELEASE_SHA,
                "source_dirty": False,
                "source_tree": "d" * 40,
                "status": "bound",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    ):
        _write_tar(
            sdist,
            set(_REQUIRED_SDIST_PATHS),
            root=root,
            build_info=invalid_build_info,
        )
        with pytest.raises(ReleaseArtifactError):
            inspect_sdist(
                sdist,
                VERSION,
                expected_commit=RELEASE_SHA,
                expected_tree=RELEASE_TREE,
            )

    missing = set(_REQUIRED_SDIST_PATHS) - {"NOTICE"}
    _write_tar(sdist, missing, root=root)
    with pytest.raises(ReleaseArtifactError, match="missing required files: NOTICE"):
        inspect_sdist(sdist, VERSION)

    _write_tar(sdist, set(_REQUIRED_SDIST_PATHS) | {".DS_Store"}, root=root)
    with pytest.raises(ReleaseArtifactError, match="Unintended"):
        inspect_sdist(sdist, VERSION)

    _write_tar(
        sdist,
        set(_REQUIRED_SDIST_PATHS) | {"evidence/private-recording.zip"},
        root=root,
    )
    with pytest.raises(ReleaseArtifactError, match="top-level path"):
        inspect_sdist(sdist, VERSION)

    _write_tar(
        sdist,
        set(_REQUIRED_SDIST_PATHS) | {"tools/unreviewed.py"},
        root=root,
    )
    with pytest.raises(ReleaseArtifactError, match="build-tool path"):
        inspect_sdist(sdist, VERSION)
