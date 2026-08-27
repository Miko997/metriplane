# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from tools.audit_ui_functionality import (
    duplicate_html_ids,
    parse_allowed_commands,
    parse_dashboard_ui,
)


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_html_ids_are_unique_per_file():
    ui = parse_dashboard_ui(ROOT)
    duplicates = duplicate_html_ids(ui)
    assert duplicates == [], "Duplicate dashboard HTML ids: " + repr(duplicates)


def test_every_dashboard_data_command_id_exists_in_allowlist():
    ui = parse_dashboard_ui(ROOT)
    allowed = {action.action_id.removeprefix("runner.") for action in parse_allowed_commands(ROOT)}
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


def test_active_dashboard_wordmarks_use_metriplane_casing():
    dashboard = ROOT / "web" / "dashboard"
    wordmark = 'Metri<span class="brand-accent">plane</span>'
    old_wordmark = 'Metri<span class="brand-accent">Plane</span>'
    pages_with_wordmarks = []

    for page in sorted(dashboard.glob("*.html")):
        text = page.read_text(encoding="utf-8")
        if "brand-wordmark" not in text:
            continue
        pages_with_wordmarks.append(page.name)
        assert wordmark in text, f"Incorrect Metriplane wordmark in {page.name}"
        assert old_wordmark not in text, f"Legacy MetriPlane wordmark in {page.name}"

    assert pages_with_wordmarks == [
        "atlas.html",
        "benchmarks.html",
        "command_center.html",
        "command_center_live.html",
        "help.html",
        "index.html",
        "integrations.html",
        "operator.html",
        "report.html",
        "run.html",
        "runtime.html",
        "settings.html",
    ]


def test_incident_report_ui_leads_with_plain_language_sections():
    report = (ROOT / "web" / "dashboard" / "report.html").read_text(encoding="utf-8")
    headings = [
        "What happened",
        "Why it was flagged",
        "When it happened",
        "Evidence that was saved",
        "Repeatable check that was generated",
        "Limits of this result",
    ]

    positions = [report.index(f"<h2>{heading}</h2>") for heading in headings]
    assert positions == sorted(positions)
    assert report.index("<h1>Incident Report</h1>") < report.index(
        "Formal artifact: Cell Truth Report"
    )
    for explanation in (
        "A recorded run is a saved sequence",
        "An event is one observed change",
        "An incident groups related events",
        "Process rules describe expected steps",
        "An evidence bundle is a ZIP",
        "A regression check is a generated test",
        "Deterministic replay uses the same saved inputs",
    ):
        assert explanation in report


def test_humanized_ui_preserves_public_artifact_paths_and_headless_report_access():
    dashboard = ROOT / "web" / "dashboard"
    report = (dashboard / "report.html").read_text(encoding="utf-8")
    evidence = (dashboard / "atlas.html").read_text(encoding="utf-8")
    navigation = (dashboard / "mp_nav.js").read_text(encoding="utf-8")

    assert 'href="atlas_run/cell_truth_report.html"' in report
    assert 'href="atlas_run/evidence_bundles/INC-0001.zip"' in report
    assert 'href="atlas_run/regression_tests/INC-0001.yaml"' in report
    assert "cell_truth_report.html" in evidence
    assert "INC-0001.zip" in evidence
    assert "INC-0001.yaml" in evidence
    assert '["report.html", "Incident Report"]' in navigation
    assert "window.open" not in report
