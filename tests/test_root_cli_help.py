# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane import cli


def test_root_help_lists_the_bundled_demo_and_primary_actions(capsys) -> None:
    assert cli.main(["--help"]) == 0

    output = capsys.readouterr().out
    assert "Metriplane helps explain what went wrong" in output
    assert "report of what happened" in output
    assert "repeatable check that can catch the same problem after a change" in output
    assert "Start here:" in output
    assert "demo       Run a complete recorded-incident example" in output
    assert "doctor     Check whether this installation is ready" in output
    assert (
        "test       Rerun a bundle and compare its incidents and events with expectations"
        in output
    )
    assert "physical-observability comparisons" not in output
    for command in ("demo", "doctor", "atlas", "replay", "test", "incidents", "run"):
        assert f"  {command}" in output


def test_explicit_run_command_preserves_runtime_dispatch(monkeypatch) -> None:
    received: list[str] = []
    logging_initialized: list[bool] = []

    def fake_run(argv: list[str]) -> int:
        received.extend(argv)
        return 7

    monkeypatch.setattr(cli, "_main_run", fake_run)
    import metriplane.logging as metriplane_logging

    monkeypatch.setattr(
        metriplane_logging,
        "setup_logging",
        lambda: logging_initialized.append(True),
    )

    assert cli.main(["run", "--config", "cell.yaml"]) == 7
    assert received == ["--config", "cell.yaml"]
    assert logging_initialized == [True]
