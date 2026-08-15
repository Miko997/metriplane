# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.demo import main as demo_main


def test_demo_labels_the_generated_html_as_incident_report(
    tmp_path: Path, capsys
) -> None:
    out_dir = tmp_path / "demo"

    assert demo_main(["--out", str(out_dir)]) == 0

    output = capsys.readouterr().out
    report_path = out_dir / "cell_truth_report.html"
    assert f"Incident Report:\n{report_path}" in output
    assert report_path.is_file()
