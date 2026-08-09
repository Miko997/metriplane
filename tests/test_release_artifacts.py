# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from tools.release_artifacts import (
    ReleaseArtifactError,
    _REQUIRED_SDIST_PATHS,
    create_manifest,
    inspect_sdist,
    read_manifest,
    verify_manifest,
    verify_registry_payload,
)


VERSION = "0.3.0"


def _artifact_set(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"metriplane-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
    (dist / f"metriplane-{VERSION}.tar.gz").write_bytes(b"sdist")
    return dist, tmp_path / "SHA256SUMS"


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
