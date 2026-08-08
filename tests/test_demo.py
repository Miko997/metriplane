# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.cli import main as metriplane_main
from metriplane.demo import main as demo_main


def test_demo_help_exposes_open_option(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        demo_main(["--help"])

    output = capsys.readouterr().out
    assert "metriplane demo" in output
    assert "--open" in output


def test_demo_runs_complete_verified_workflow(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "metriplane.demo.webbrowser.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser opened")),
    )
    out_dir = tmp_path / "demo"

    assert metriplane_main(["demo", "--out", str(out_dir)]) == 0

    output = capsys.readouterr().out
    assert "PASS  Incident analysis: 6 events, 1 incident" in output
    assert "PASS  Evidence bundle: verified" in output
    assert "PASS  Regression check: passed" in output
    assert "Demo complete." in output

    manifest = json.loads((out_dir / "atlas_manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_count"] == 6
    assert manifest["incident_count"] == 1

    bundle_path = out_dir / "evidence_bundles" / "INC-0001.zip"
    regression_path = out_dir / "regression_tests" / "INC-0001.yaml"
    report_path = out_dir / "cell_truth_report.html"
    assert verify_bundle(bundle_path)["pass"] is True
    assert run_regression(regression_path)["pass"] is True
    assert report_path.is_file()

    spec = yaml.safe_load(regression_path.read_text(encoding="utf-8"))
    source_bundle = Path(spec["source_bundle"])
    assert source_bundle.is_absolute()
    assert source_bundle == bundle_path.resolve()


def test_demo_refuses_existing_output_without_deleting_it(
    tmp_path: Path, capsys
) -> None:
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    sentinel = out_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    assert demo_main(["--out", str(out_dir)]) == 2

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert "Refusing to replace an existing output directory" in capsys.readouterr().err


def test_demo_default_output_uses_a_fresh_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert demo_main([]) == 0
    assert demo_main([]) == 0

    first = tmp_path / "metriplane-demo"
    second = tmp_path / "metriplane-demo-2"
    assert (first / "cell_truth_report.html").is_file()
    assert (second / "cell_truth_report.html").is_file()

    deterministic_artifacts = [
        "physical_event_log.jsonl",
        "incidents.jsonl",
        "deviations.jsonl",
        "flow_metrics.csv",
        "process_trace.json",
    ]
    for relative_path in deterministic_artifacts:
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_demo_open_is_best_effort(tmp_path: Path, capsys, monkeypatch) -> None:
    opened: list[str] = []

    def open_browser(uri: str, new: int = 0) -> bool:
        opened.append(uri)
        assert new == 2
        return True

    monkeypatch.setattr("metriplane.demo.webbrowser.open", open_browser)
    out_dir = tmp_path / "opened"

    assert demo_main(["--out", str(out_dir), "--open"]) == 0

    assert opened == [(out_dir / "cell_truth_report.html").resolve().as_uri()]
    assert "Browser: opened report" in capsys.readouterr().out


def test_demo_browser_failure_keeps_success(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("metriplane.demo.webbrowser.open", lambda *_args, **_kwargs: False)

    assert demo_main(["--out", str(tmp_path / "headless"), "--open"]) == 0

    captured = capsys.readouterr()
    assert "Demo complete." in captured.out
    assert "Could not open a browser" in captured.err
