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
import shutil
from pathlib import Path

from metriplane import __version__


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
