# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Bind a claimed adapter commit to the exact running checkout."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from .constants import PACKAGE_ROOT


class AdapterIdentityError(RuntimeError):
    """Raised when the running adapter cannot prove its Git identity."""


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    environment = os.environ.copy()
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    for name in tuple(environment):
        if name.startswith(("GIT_CONFIG_", "GIT_TRACE", "LD_", "DYLD_")):
            environment.pop(name, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    git_executable = shutil.which("git", path=os.defpath)
    if git_executable is None:
        raise AdapterIdentityError("adapter identity: system git executable is required")
    try:
        result = subprocess.run(
            [
                git_executable,
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(repo_root),
                *arguments,
            ],
            check=True,
            capture_output=True,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise AdapterIdentityError("adapter identity: git executable is required") from exc
    except subprocess.CalledProcessError as exc:
        raw_detail = exc.stderr.strip() or exc.stdout.strip()
        detail = raw_detail.decode("utf-8", errors="replace") if raw_detail else arguments[0]
        raise AdapterIdentityError(f"adapter identity: Git verification failed: {detail}") from exc
    return result.stdout


def _git(repo_root: Path, *arguments: str) -> str:
    try:
        return _git_bytes(repo_root, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise AdapterIdentityError("adapter identity: Git returned non-UTF-8 text") from exc


def _verify_head_tree_bytes(repository_root: Path, relative_root: str) -> set[str]:
    raw = _git_bytes(
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
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdapterIdentityError("adapter identity: malformed Git tree record") from exc
        path = Path(relative)
        if (
            object_type != "blob"
            or mode not in {"100644", "100755"}
            or path.is_absolute()
            or ".." in path.parts
            or relative == relative_root
            or not relative.startswith(f"{relative_root}/")
            or relative in tracked
        ):
            raise AdapterIdentityError("adapter identity: unexpected Git tree entry")
        tracked.add(relative)
        source = repository_root / path
        if source.is_symlink() or not source.is_file():
            raise AdapterIdentityError(
                f"adapter identity: tracked file is missing or unsafe: {relative}"
            )
        actual_executable = bool(source.stat().st_mode & stat.S_IXUSR)
        if actual_executable != (mode == "100755"):
            raise AdapterIdentityError(f"adapter identity: tracked mode differs: {relative}")
        expected_bytes = _git_bytes(repository_root, "cat-file", "blob", object_id)
        if source.read_bytes() != expected_bytes:
            raise AdapterIdentityError(
                f"adapter identity: working bytes differ from HEAD: {relative}"
            )
    if not tracked:
        raise AdapterIdentityError("adapter identity: adapter subtree is absent from HEAD")
    return tracked


def verify_adapter_commit(adapter_commit: str) -> None:
    """Require a clean tracked adapter at the exact supplied repository HEAD.

    Conversion intentionally requires a Git checkout. The portable fixture does
    not: ordinary Metriplane evaluation never imports this adapter package.
    """
    if re.fullmatch(r"[0-9a-f]{40}", adapter_commit) is None:
        raise AdapterIdentityError("adapter identity: expected one lowercase 40-hex commit")
    adapter_root = PACKAGE_ROOT.resolve()
    repository_root = adapter_root.parent.parent.resolve()
    if adapter_root != repository_root / "adapters" / "robomimic_lowdim":
        raise AdapterIdentityError(
            "adapter identity: conversion requires the tracked adapters/robomimic_lowdim checkout"
        )
    top_level = Path(_git(repository_root, "rev-parse", "--show-toplevel")).resolve()
    if top_level != repository_root:
        raise AdapterIdentityError("adapter identity: running source is outside the Git root")
    actual_commit = _git(repository_root, "rev-parse", "--verify", "HEAD^{commit}")
    if actual_commit != adapter_commit:
        raise AdapterIdentityError(
            f"adapter identity: supplied commit {adapter_commit} does not equal HEAD {actual_commit}"
        )
    _git(repository_root, "cat-file", "-e", f"{adapter_commit}^{{commit}}")
    relative_root = "adapters/robomimic_lowdim"
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
    tracked = _verify_head_tree_bytes(repository_root, relative_root)
    required = {
        f"{relative_root}/config/frozen-config.json",
        f"{relative_root}/pyproject.toml",
        f"{relative_root}/src/robomimic_lowdim/cli.py",
        f"{relative_root}/src/robomimic_lowdim/constants.py",
        f"{relative_root}/src/robomimic_lowdim/core.py",
        f"{relative_root}/src/robomimic_lowdim/fixture.py",
        f"{relative_root}/src/robomimic_lowdim/hdf5_audit.py",
        f"{relative_root}/src/robomimic_lowdim/identity.py",
        f"{relative_root}/uv.lock",
    }
    missing = sorted(required - tracked)
    if missing:
        raise AdapterIdentityError(
            f"adapter identity: required tracked files absent from HEAD: {missing}"
        )
