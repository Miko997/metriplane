# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from tools.audit_ui_functionality import duplicate_html_ids, parse_allowed_commands, parse_dashboard_ui


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_html_ids_are_unique_per_file():
    ui = parse_dashboard_ui(ROOT)
    duplicates = duplicate_html_ids(ui)
    assert duplicates == [], "Duplicate dashboard HTML ids: " + repr(duplicates)


def test_every_dashboard_data_command_id_exists_in_allowlist():
    ui = parse_dashboard_ui(ROOT)
    allowed = {
        action.action_id.removeprefix("runner.")
        for action in parse_allowed_commands(ROOT)
    }
    missing = sorted(
        {
            button["command_id"]
            for button in ui["command_buttons"]
            if button["command_id"] not in allowed
        }
    )
    assert missing == []


def test_command_center_live_js_has_no_merge_artifact_duplicates():
    text = (ROOT / "web" / "dashboard" / "command_center_live.js").read_text(encoding="utf-8")
    assert text.count("await Promise.all([") == 1
    assert text.count("const start =") == 1
