# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane import cli


def test_root_help_lists_the_bundled_demo_and_primary_actions(capsys) -> None:
    assert cli.main(["--help"]) == 0

    output = capsys.readouterr().out
    assert "Metriplane turns recorded workcell state" in output
    for command in ("demo", "doctor", "atlas", "replay", "test", "incidents", "run"):
        assert f"  {command}" in output


def test_explicit_run_command_preserves_runtime_dispatch(monkeypatch) -> None:
    received: list[str] = []

    def fake_run(argv: list[str]) -> int:
        received.extend(argv)
        return 7

    monkeypatch.setattr(cli, "_main_run", fake_run)

    assert cli.main(["run", "--config", "cell.yaml"]) == 7
    assert received == ["--config", "cell.yaml"]
