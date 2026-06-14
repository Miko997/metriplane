#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Regenerate release manifest and aggregate checksums from the staged tree."""

from __future__ import annotations

import csv
import hashlib
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "v0.2.0"
MANIFEST = ROOT / "evidence" / "manifest.csv"
CHECKSUMS = ROOT / "evidence" / "CHECKSUMS.sha256"
HEADER = [
    "claim_id",
    "artifact_path",
    "metric_name",
    "metric_value",
    "units",
    "source_command",
    "sha256",
    "release_tag",
    "notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(os.readlink(path).encode("utf-8"))
        return digest.hexdigest()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "."],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = [p.decode("utf-8") for p in result.stdout.split(b"\0") if p]
    return sorted(
        path
        for path in paths
        if not path.endswith("/CHECKSUMS.sha256") and not (ROOT / path).is_symlink()
    )


def read_existing_manifest() -> list[dict[str, str]]:
    if not MANIFEST.exists():
        return []
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def claim_id_for(path: str) -> str:
    safe = path.replace("/", ".").replace("_", "-")
    for char in " ()[]{}:":
        safe = safe.replace(char, "-")
    return f"artifact.{safe}"


def artifact_row(path: str, digest: str) -> dict[str, str]:
    return {
        "claim_id": claim_id_for(path),
        "artifact_path": path,
        "metric_name": "artifact_sha256",
        "metric_value": digest,
        "units": "sha256",
        "source_command": "git-index release-tree file inventory",
        "sha256": digest,
        "release_tag": RELEASE_TAG,
        "notes": "Release-tree artifact retained for v0.2.0 provenance.",
    }


def main() -> int:
    paths = staged_paths()
    path_set = set(paths)
    checksummed_paths = [path for path in paths if path != "evidence/CHECKSUMS.sha256"]
    hashes = {path: sha256_file(ROOT / path) for path in checksummed_paths}

    existing = read_existing_manifest()
    rows: list[dict[str, str]] = []
    covered: set[str] = set()

    for row in existing:
        path = row.get("artifact_path", "")
        if not path or path == "evidence/manifest.csv" or path not in path_set:
            continue
        digest = hashes[path]
        updated = {key: row.get(key, "") for key in HEADER}
        updated["sha256"] = digest
        updated["release_tag"] = RELEASE_TAG
        if updated["metric_name"] == "artifact_sha256":
            updated["metric_value"] = digest
            updated["units"] = "sha256"
            if not updated["source_command"]:
                updated["source_command"] = "git-index release-tree file inventory"
            if not updated["notes"]:
                updated["notes"] = "Release-tree artifact retained for v0.2.0 provenance."
        rows.append(updated)
        covered.add(path)

    for path in checksummed_paths:
        if path == "evidence/manifest.csv" or path in covered:
            continue
        rows.append(artifact_row(path, hashes[path]))

    rows.sort(key=lambda row: (row["artifact_path"], row["claim_id"]))

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    hashes["evidence/manifest.csv"] = sha256_file(MANIFEST)
    with CHECKSUMS.open("w", encoding="utf-8") as handle:
        for path in sorted(hashes):
            handle.write(f"{hashes[path]}  {path}\n")

    print(f"wrote {MANIFEST.relative_to(ROOT)} ({len(rows)} rows)")
    print(f"wrote {CHECKSUMS.relative_to(ROOT)} ({len(hashes)} checksums)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
