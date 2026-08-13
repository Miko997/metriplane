# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Bind conversion to an exact, clean adapter Git tree."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from .constants import PACKAGE_ROOT, SOURCE_FILENAME


class AdapterIdentityError(RuntimeError):
    """Raised when exact adapter identity cannot be proven."""


def _git_bytes(root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith(("GIT_", "LD_", "DYLD_")):
            environment.pop(name, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    executable = shutil.which("git", path=os.defpath)
    if executable is None:
        raise AdapterIdentityError("adapter identity: system git executable is required")
    try:
        result = subprocess.run(
            [
                executable,
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=True,
            capture_output=True,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"") or getattr(exc, "stdout", b"")
        raise AdapterIdentityError(
            f"adapter identity: Git verification failed: {detail.decode(errors='replace').strip()}"
        ) from exc
    return result.stdout


def _git(root: Path, *arguments: str) -> str:
    try:
        return _git_bytes(root, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AdapterIdentityError("adapter identity: Git returned non-UTF-8 text") from exc


def verify_adapter_commit(adapter_commit: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", adapter_commit) is None:
        raise AdapterIdentityError("adapter identity: expected one lowercase 40-hex commit")
    adapter_root = PACKAGE_ROOT.resolve()
    repository_root = adapter_root.parent.parent.resolve()
    if adapter_root != repository_root / "adapters" / "ros2_mcap":
        raise AdapterIdentityError(
            "adapter identity: conversion requires tracked adapters/ros2_mcap checkout"
        )
    top = Path(_git(repository_root, "rev-parse", "--show-toplevel")).resolve()
    if top != repository_root:
        raise AdapterIdentityError("adapter identity: running source is outside repository root")
    head = _git(repository_root, "rev-parse", "--verify", "HEAD^{commit}")
    if head != adapter_commit:
        raise AdapterIdentityError(
            f"adapter identity: supplied commit {adapter_commit} does not equal HEAD {head}"
        )
    relative_root = "adapters/ros2_mcap"
    status = _git(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        relative_root,
    )
    if status:
        raise AdapterIdentityError("adapter identity: adapter checkout is not clean at HEAD")
    records = _git_bytes(
        repository_root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        "HEAD",
        "--",
        relative_root,
    )
    tracked: set[str] = set()
    for record in records.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdapterIdentityError("adapter identity: malformed Git tree record") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise AdapterIdentityError("adapter identity: symlinks and non-files are prohibited")
        if relative in tracked or not relative.startswith(f"{relative_root}/"):
            raise AdapterIdentityError("adapter identity: duplicate or escaped tracked path")
        tracked.add(relative)
        path = repository_root / relative
        if path.is_symlink() or not path.is_file():
            raise AdapterIdentityError(f"adapter identity: tracked file is missing: {relative}")
        if bool(path.stat().st_mode & stat.S_IXUSR) != (mode == "100755"):
            raise AdapterIdentityError(f"adapter identity: tracked mode differs: {relative}")
        if path.read_bytes() != _git_bytes(repository_root, "cat-file", "blob", object_id):
            raise AdapterIdentityError(f"adapter identity: working bytes differ: {relative}")
    required = {
        f"{relative_root}/config/frozen-config.json",
        f"{relative_root}/pyproject.toml",
        f"{relative_root}/source/{SOURCE_FILENAME}",
        f"{relative_root}/src/ros2_mcap_adapter/cli.py",
        f"{relative_root}/src/ros2_mcap_adapter/core.py",
        f"{relative_root}/src/ros2_mcap_adapter/decoder.py",
        f"{relative_root}/src/ros2_mcap_adapter/fixture.py",
        f"{relative_root}/src/ros2_mcap_adapter/identity.py",
        f"{relative_root}/uv.lock",
    }
    missing = sorted(required - tracked)
    if missing:
        raise AdapterIdentityError(f"adapter identity: required tracked files absent: {missing}")


__all__ = ["AdapterIdentityError", "verify_adapter_commit"]
