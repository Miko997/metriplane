# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from metriplane.runner import safe_reads
from metriplane.runner.safe_reads import UnsafeReadPathError, open_pinned_file

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")),
    reason="secure reads require POSIX O_NOFOLLOW descriptors",
)


def test_pinned_file_rejects_parent_replacement(tmp_path: Path) -> None:
    authority = tmp_path / "runs"
    run = authority / "authorized"
    parked = authority / "authorized-original"
    outside = tmp_path / "outside"
    run.mkdir(parents=True)
    outside.mkdir()
    requested = run / "session.jsonl"
    requested.write_text("authorized\n", encoding="utf-8")
    (outside / requested.name).write_text("outside\n", encoding="utf-8")

    with open_pinned_file([authority], requested) as pinned:
        run.rename(parked)
        run.symlink_to(outside, target_is_directory=True)

        with pytest.raises(UnsafeReadPathError, match="changed during read"):
            pinned.read_text()

    assert (parked / requested.name).read_text() == "authorized\n"
    assert (outside / requested.name).read_text() == "outside\n"


def test_pinned_file_allows_a_canonicalized_trusted_root(tmp_path: Path) -> None:
    authority = tmp_path / "real-runs"
    linked_authority = tmp_path / "linked-runs"
    artifact = authority / "run" / "session.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("authorized\n", encoding="utf-8")
    linked_authority.symlink_to(authority, target_is_directory=True)
    requested = linked_authority / "run" / "session.jsonl"

    with open_pinned_file([linked_authority], requested) as pinned:
        assert pinned.read_text() == "authorized\n"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", "/proc/self/fd/17"),
        ("darwin", "/dev/fd/17"),
    ],
)
def test_inherited_fd_path_uses_the_platform_descriptor_namespace(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected: str,
) -> None:
    monkeypatch.setattr(safe_reads, "sys", SimpleNamespace(platform=platform))

    assert safe_reads.inherited_fd_path(17) == expected


def test_inherited_fd_path_fails_closed_on_unknown_posix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(safe_reads, "sys", SimpleNamespace(platform="freebsd14"))

    with pytest.raises(OSError, match="unsupported"):
        safe_reads.inherited_fd_path(17)
