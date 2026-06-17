# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from metriplane.runner.allowlist import ALLOWLIST, get_command, validate_command_id


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
