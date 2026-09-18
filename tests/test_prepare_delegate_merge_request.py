# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""The rootless request builder never invents missing provider evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import prepare_delegate_merge_request as request_builder


def test_bounded_provider_read_rejects_errors_and_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, "", "unavailable")

    monkeypatch.setattr(request_builder.subprocess, "run", failed)
    with pytest.raises(request_builder.RequestPreparationError, match="provider read failed"):
        request_builder._gh("repos/Miko997/metriplane")

    def malformed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, "not JSON", "")

    monkeypatch.setattr(request_builder.subprocess, "run", malformed)
    with pytest.raises(request_builder.RequestPreparationError, match="malformed JSON"):
        request_builder._gh("repos/Miko997/metriplane")


def test_request_builder_rejects_delegate_key_inside_repository(tmp_path: Path) -> None:
    key = tmp_path / "delegate.pem"
    key.write_text("fixture", encoding="ascii")
    with pytest.raises(request_builder.RequestPreparationError, match="outside the repository"):
        request_builder.prepare(
            repository_root=tmp_path,
            pull_number=135,
            work_order_path=tmp_path / "absent.json",
            delegation_path=tmp_path / "absent.json",
            snapshot_path=tmp_path / "absent.json",
            dependencies_path=tmp_path / "absent.json",
            commands_path=tmp_path / "absent.json",
            resolution_path=tmp_path / "absent.json",
            delegate_key_path=key,
        )
