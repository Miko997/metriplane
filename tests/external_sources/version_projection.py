# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Materialize a disposable fixture evaluation for the running release.

Source-specific fixture trees remain immutable evidence for the version named in
their manifests. Release compatibility tests copy that evidence and change only
the declared evaluation version plus its checksum inventory before execution.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path

from metriplane import __version__


_PRIVATE_PATH = re.compile(
    rb"(?:/(?:home|Users)/[^/\s\"'<>]+(?:/|(?=[\s\"'<>]|$))|"
    rb"(?<![A-Za-z0-9_+.-])[A-Za-z]:[\\/])"
)


def _assert_path_free(raw: bytes, *, forbidden: tuple[bytes, ...], where: object) -> None:
    assert not any(value in raw for value in forbidden), where
    assert _PRIVATE_PATH.search(raw) is None, where


def assert_portable_output_tree(root: Path, *, forbidden: Iterable[bytes]) -> None:
    """Require user-visible output bytes to contain no machine-private paths.

    Publication generations retain exact public bytes under opaque blob names.
    Detect ZIP content independently of its suffix and inspect member names and
    decompressed bodies, so random compressed bytes are never treated as text.
    Every non-ZIP file remains subject to the raw-byte checks.
    """
    root = Path(root)
    assert root.is_dir() and not root.is_symlink(), root
    forbidden_values = tuple(forbidden)
    assert forbidden_values and all(
        isinstance(value, bytes) and value for value in forbidden_values
    )

    for path in sorted(root.rglob("*")):
        assert not path.is_symlink(), path
        if path.is_dir():
            continue
        assert path.is_file(), path
        if path.suffix == ".zip" or zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None, path
                for member in archive.infolist():
                    _assert_path_free(
                        member.filename.encode(),
                        forbidden=forbidden_values,
                        where=(path, member.filename),
                    )
                    if not member.is_dir():
                        _assert_path_free(
                            archive.read(member),
                            forbidden=forbidden_values,
                            where=(path, member.filename),
                        )
            continue
        _assert_path_free(path.read_bytes(), forbidden=forbidden_values, where=path)


def materialize_current_version_fixture(source: Path, destination: Path) -> Path:
    """Copy *source* into a disposable exact-version evaluation fixture."""
    shutil.copytree(source, destination)
    manifest_path = destination / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evaluation"]["metriplane_version"] = __version__
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    checksums_path = destination / "CHECKSUMS.sha256"
    lines = checksums_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        digest, separator, relative = line.partition("  ")
        if separator and relative == "source-manifest.json":
            if len(digest) != 64:
                raise ValueError("source-manifest checksum is malformed")
            lines[index] = f"{manifest_sha256}  source-manifest.json"
            replaced = True
    if not replaced:
        raise ValueError("source-manifest checksum entry is missing")
    checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
