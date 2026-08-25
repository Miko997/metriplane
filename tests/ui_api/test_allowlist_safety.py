# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.paths import PlatformPaths
from metriplane.runner.allowlist import ALLOWLIST, get_command, get_commands, validate_command_id


def test_allowlist_command_ids_validate():
    ids = [cmd.id for cmd in ALLOWLIST]
    assert ids
    assert len(ids) == len(set(ids))
    for command_id in ids:
        assert validate_command_id(command_id)
        assert get_command(command_id) is not None


def test_invalid_command_ids_reject_traversal_and_special_chars():
    bad_ids = [
        "../doctor",
        "doctor;rm-rf",
        "doctor && whoami",
        "doctor/../../x",
        "",
        "not a command",
    ]
    for command_id in bad_ids:
        assert not validate_command_id(command_id)


def test_enabled_commands_have_nonempty_command_lists():
    for cmd in ALLOWLIST:
        if cmd.enabled:
            assert cmd.command, cmd.id
            assert all(isinstance(part, str) and part for part in cmd.command), cmd.id
            assert cmd.timeout_s > 0


def test_disabled_commands_explain_why():
    disabled = [cmd for cmd in ALLOWLIST if not cmd.enabled]
    assert disabled
    for cmd in disabled:
        assert cmd.disabled_reason


def test_platform_run_path_is_resolved_only_for_returned_commands(tmp_path: Path):
    paths = PlatformPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
    )

    resolved_commands = get_commands(paths=paths)

    for command_id in ("run-demo-replay", "sentinel-demo"):
        static = next(command for command in ALLOWLIST if command.id == command_id)
        resolved = next(command for command in resolved_commands if command.id == command_id)
        assert str(paths.runs_dir) not in static.command
        assert str(paths.runs_dir) in resolved.command
        assert resolved.command[resolved.command.index("--runs-dir") + 1] == str(paths.runs_dir)
        assert get_command(command_id, paths=paths) == resolved


def test_only_path_dependent_command_is_disabled_without_home(monkeypatch):
    for name in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)

    commands = get_commands()
    replay = next(command for command in commands if command.id == "run-demo-replay")
    sentinel = next(command for command in commands if command.id == "sentinel-demo")
    doctor = next(command for command in commands if command.id == "doctor")

    for command in (replay, sentinel):
        assert command.enabled is False
        assert command.disabled_reason is not None
        assert "Platform paths unavailable" in command.disabled_reason
    assert doctor.enabled is True
