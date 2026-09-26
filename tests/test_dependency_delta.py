# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.check_dependency_delta import (
    DependencyDeltaError,
    validate_changed_paths,
    validate_dependency_delta,
)


def _policy() -> dict[str, object]:
    return {
        "python_projects": [
            {"directory": ".", "lock": "uv.lock"},
            {"directory": "adapter", "lock": "adapter/uv.lock"},
        ],
        "additional_locks": ["fixture/uv.lock"],
        "images": {
            "scanned": ["docker/Dockerfile"],
            "excluded": [{"path": "ci.Dockerfile", "reason": "test only"}],
        },
        "license_files": ["LICENSE", "NOTICE", "LICENSES/MIT.txt"],
    }


def test_declared_dependency_delta_is_canonical() -> None:
    result = validate_changed_paths(
        _policy(),
        ["uv.lock", "pyproject.toml", "metriplane/runtime.py", "docker/Dockerfile"],
    )
    assert result == {
        "dependency_path_count": 3,
        "dependency_paths": ["docker/Dockerfile", "pyproject.toml", "uv.lock"],
    }


@pytest.mark.parametrize(
    "path",
    ("unknown/pyproject.toml", "unknown/uv.lock", "unknown.Dockerfile", "LICENSES/GPL.txt"),
)
def test_undeclared_dependency_surface_fails_closed(path: str) -> None:
    with pytest.raises(DependencyDeltaError, match="undeclared dependency-bearing path"):
        validate_changed_paths(_policy(), [path])


def test_changed_manifest_requires_its_declared_lock() -> None:
    with pytest.raises(DependencyDeltaError, match="lacks its lock delta"):
        validate_changed_paths(_policy(), ["adapter/pyproject.toml"])


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_exact_git_delta_binds_base_head_and_changed_paths(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "supply-chain-policy.json").write_text(json.dumps(_policy()), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo-two'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\nrevision = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "head")
    head = _git(tmp_path, "rev-parse", "HEAD")
    result = validate_dependency_delta(tmp_path, event_name="pull_request", base=base, head=head)
    assert result["dependency_paths"] == ["pyproject.toml", "uv.lock"]
    assert result["verdict"] == "PASS"


def test_wrong_head_and_non_ancestor_fail_closed(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "supply-chain-policy.json").write_text(json.dumps(_policy()), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "only")
    head = _git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(DependencyDeltaError, match="differs from head SHA"):
        validate_dependency_delta(tmp_path, event_name="pull_request", base=head, head="f" * 40)
    with pytest.raises(DependencyDeltaError, match="git merge-base"):
        validate_dependency_delta(tmp_path, event_name="pull_request", base="e" * 40, head=head)
