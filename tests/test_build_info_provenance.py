# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from metriplane.provenance.run_provenance import BuildInfoError, get_git_info


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_checkout(root: Path) -> tuple[Path, str, str]:
    source = root / "metriplane" / "provenance" / "run_provenance.py"
    source.parent.mkdir(parents=True)
    source.write_text("SOURCE = 'clean'\n", encoding="utf-8")
    (root / "metriplane" / "build-info.json").write_text(
        '{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        '"source_dirty":null,"source_tree":null,"status":"unbound"}',
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "metriplane"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    _git("init", "-q", cwd=root)
    _git("config", "user.name", "Metriplane Test", cwd=root)
    _git("config", "user.email", "test@example.invalid", cwd=root)
    _git("add", ".", cwd=root)
    _git("commit", "-qm", "fixture", cwd=root)
    return source, _git("rev-parse", "HEAD", cwd=root), _git("rev-parse", "HEAD^{tree}", cwd=root)


def _write_build_info(package: Path, *, commit: str, tree: str) -> None:
    package.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "metriplane.build-info.v1",
        "source_commit": commit,
        "source_dirty": False,
        "source_tree": tree,
        "status": "bound",
    }
    (package / "build-info.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_checkout_identity_wins_and_ambient_commit_is_only_a_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, commit, tree = _source_checkout(tmp_path / "source")
    declared = "f" * 40
    monkeypatch.setenv("METRIPLANE_GIT_COMMIT", declared)

    clean = get_git_info(start=source)

    assert clean.commit == commit
    assert clean.tree == tree
    assert clean.dirty is False
    assert clean.authority == "checkout"
    assert clean.declared_commit == declared
    assert clean.declaration_matches is False

    source.write_text("SOURCE = 'dirty'\n", encoding="utf-8")
    dirty = get_git_info(start=source)
    assert dirty.commit == commit
    assert dirty.tree == tree
    assert dirty.dirty is True
    assert dirty.declared_commit == declared


def test_embedded_build_info_wins_outside_a_checkout_and_rejects_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "installed" / "metriplane" / "provenance" / "run_provenance.py"
    source.parent.mkdir(parents=True)
    source.write_text("# installed\n", encoding="utf-8")
    commit = "a" * 40
    tree = "b" * 40
    _write_build_info(source.parent.parent, commit=commit, tree=tree)
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)

    info = get_git_info(start=source)

    assert info.commit == commit
    assert info.tree == tree
    assert info.dirty is False
    assert info.repo_root is None
    assert info.authority == "embedded-build-info"
    assert info.declared_commit == "c" * 40
    assert info.declaration_matches is False


def test_unrelated_checkout_cannot_replace_embedded_package_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = tmp_path / "unrelated"
    source = unrelated / "venv" / "metriplane" / "provenance" / "run_provenance.py"
    source.parent.mkdir(parents=True)
    source.write_text("# installed\n", encoding="utf-8")
    _git("init", "-q", cwd=unrelated)
    _git("config", "user.name", "Metriplane Test", cwd=unrelated)
    _git("config", "user.email", "test@example.invalid", cwd=unrelated)
    marker = unrelated / "README.md"
    marker.write_text("unrelated\n", encoding="utf-8")
    embedded_commit = "d" * 40
    _write_build_info(source.parent.parent, commit=embedded_commit, tree="e" * 40)
    _git("add", ".", cwd=unrelated)
    _git("commit", "-qm", "tracked vendor package", cwd=unrelated)
    monkeypatch.chdir(unrelated)

    info = get_git_info(start=source)

    assert info.commit == embedded_commit
    assert info.authority == "embedded-build-info"
    assert info.repo_root is None

    lookalike = tmp_path / "lookalike"
    exact_source = lookalike / "metriplane" / "provenance" / "run_provenance.py"
    exact_source.parent.mkdir(parents=True)
    exact_source.write_text("# tracked lookalike\n", encoding="utf-8")
    _write_build_info(exact_source.parent.parent, commit=embedded_commit, tree="e" * 40)
    (lookalike / "pyproject.toml").write_text(
        '[project]\nname = "not-metriplane"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    _git("init", "-q", cwd=lookalike)
    _git("config", "user.name", "Metriplane Test", cwd=lookalike)
    _git("config", "user.email", "test@example.invalid", cwd=lookalike)
    _git("add", ".", cwd=lookalike)
    _git("commit", "-qm", "tracked lookalike package", cwd=lookalike)

    marker_rejected = get_git_info(start=exact_source)
    assert marker_rejected.commit == embedded_commit
    assert marker_rejected.authority == "embedded-build-info"
    assert marker_rejected.repo_root is None


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"metriplane.build-info.v1"}\n',
        b'{"schema_version":"metriplane.build-info.v1","source_commit":"bad",'
        b'"source_dirty":false,"source_tree":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        b'"status":"bound"}',
        b'{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        b'"source_dirty":false,"source_tree":null,"status":"unbound"}',
    ],
)
def test_tampered_or_malformed_embedded_build_info_fails_closed(
    tmp_path: Path, payload: bytes
) -> None:
    source = tmp_path / "installed" / "metriplane" / "provenance" / "run_provenance.py"
    source.parent.mkdir(parents=True)
    source.write_text("# installed\n", encoding="utf-8")
    (source.parent.parent / "build-info.json").write_bytes(payload)

    with pytest.raises(BuildInfoError):
        get_git_info(start=source)


def test_unbound_build_info_and_ambient_value_do_not_claim_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "installed" / "metriplane" / "provenance" / "run_provenance.py"
    source.parent.mkdir(parents=True)
    source.write_text("# installed\n", encoding="utf-8")
    (source.parent.parent / "build-info.json").write_text(
        '{"schema_version":"metriplane.build-info.v1","source_commit":null,'
        '"source_dirty":null,"source_tree":null,"status":"unbound"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_COMMIT", "a" * 40)

    info = get_git_info(start=source)

    assert info.commit is None
    assert info.tree is None
    assert info.authority == "unavailable"
    assert info.declared_commit == "a" * 40
    assert info.declaration_matches is None

    monkeypatch.setenv("GIT_COMMIT", "not-a-commit-or-safe-metadata")
    invalid = get_git_info(start=source)
    assert invalid.commit is None
    assert invalid.declared_commit == "<invalid>"

    (source.parent.parent / "build-info.json").write_text(
        '{"schema_version":"metriplane.build-info.v1","source_commit":1,'
        '"source_dirty":false,"source_tree":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        '"status":"bound"}',
        encoding="utf-8",
    )
    with pytest.raises(BuildInfoError):
        get_git_info(start=source)
