# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_first_screen_uses_exact_v030_package_quickstart() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    first_screen, separator, _ = readme.partition("## Published versions")
    normalized = " ".join(
        first_screen.replace("`", "").replace("**", "").replace("\n> ", " ").split()
    )
    release_quickstart = """```bash
python -m pip install \"metriplane==0.3.0\"
metriplane demo --open
```"""

    assert separator
    assert first_screen.startswith("<!--")
    assert "# Metriplane" in first_screen
    assert "MetriPlane" not in first_screen
    assert "Understand what went wrong in a recorded workcell run" in normalized
    assert "timestamped object positions and process rules" in normalized
    assert "does not control machinery" in normalized
    assert release_quickstart in first_screen
    assert first_screen.index("## Quickstart") < first_screen.index(release_quickstart)
    assert "Current installable software release: `v0.3.0`" in readme
    assert 'python -m pip install "metriplane==0.2.1"' not in readme
    assert "current `main`" not in readme
    assert "preview" not in first_screen.lower()
    assert "planned" not in first_screen.lower()
    assert "not published" not in first_screen.lower()
    assert "agent/bundled-demo" not in readme
    assert "PASS  Incident timeline: 6 events" in first_screen
    assert "PASS  Incident report: 1 incident" in first_screen
    assert "PASS  Evidence bundle: verified" in first_screen
    assert "PASS  Repeatable regression check: passed" in first_screen
    assert "Browser: opened report" in first_screen


def test_readme_explains_the_beginner_input_output_and_terms() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    for phrase in (
        "Timestamped object positions + process rules",
        "Replays the recorded run and checks what happened",
        "Incident timeline",
        "Incident report",
        "Verified evidence bundle",
        "Repeatable regression check",
        "**Recorded run:**",
        "**Event:**",
        "**Incident:**",
        "**Evidence bundle:**",
        "**Regression check:**",
        "**Process rules:**",
        "**Deterministic replay:**",
    ):
        assert phrase in readme

    assert "does not prove that the original physical measurements were accurate" in normalized


def test_active_readme_uses_current_product_wordmark() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "# Metriplane" in readme
    assert "MetriPlane" not in readme


def test_release_gate_runs_the_exact_installed_wheel_quickstart() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-gates.yml").read_text(
        encoding="utf-8"
    )

    assert 'os: [ubuntu-latest, macos-latest]' in workflow
    assert 'python-version: ["3.12", "3.13"]' in workflow
    assert '"demo",\n              "--open",' in workflow
    assert 'BROWSER="$browser_stub"' in workflow
    assert '"Browser: opened report" not in completed.stdout' in workflow
    assert 'test "$(<"$browser_uri_file")" = "$expected_report_uri"' in workflow
