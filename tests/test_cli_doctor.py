# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane import cli


def test_doctor_source_checkout_helpers_are_warnings_outside_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli._check_vt_sh_exists() == (
        "WARN",
        "tools/mp.sh not found outside a source checkout",
    )
    assert cli._check_config_exists() == (
        "WARN",
        "configs/fusion_health_300fps.yaml not found outside a source checkout",
    )


def test_doctor_source_checkout_helpers_fail_inside_incomplete_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'metriplane'\n", encoding="utf-8")

    assert cli._check_vt_sh_exists() == ("FAIL", "tools/mp.sh not found")
    assert cli._check_config_exists() == ("FAIL", "configs/fusion_health_300fps.yaml not found")


def test_doctor_git_commit_is_warning_outside_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    status, message = cli._check_git_commit()

    assert status == "WARN"
    assert message == "Git commit not available outside a source checkout"
