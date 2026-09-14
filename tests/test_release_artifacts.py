# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import io
import tarfile
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
    create_manifest,
    inspect_sdist,
    read_manifest,
    reconcile_publish_lease,
    verify_manifest,
    verify_registry_payload,
)

VERSION = "0.3.0"
REPOSITORY = "Miko997/metriplane"
RELEASE_SHA = "a" * 40


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


def _write_tar(path: Path, names: set[str], *, root: str) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name in sorted(names):
            payload = name.encode("utf-8") or b"x"
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_sdist_inspection_requires_resources_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    sdist = tmp_path / f"metriplane-{VERSION}.tar.gz"
    root = f"metriplane-{VERSION}"
    _write_tar(sdist, set(_REQUIRED_SDIST_PATHS), root=root)
    inspect_sdist(sdist, VERSION)

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
