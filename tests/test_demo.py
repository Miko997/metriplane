# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import webbrowser
from importlib import resources
from pathlib import Path

import pytest
import yaml

from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.regression import run_regression
from metriplane.cli import main as metriplane_main
from metriplane.demo import main as demo_main


def test_demo_help_exposes_open_and_export_options(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        demo_main(["--help"])

    output = capsys.readouterr().out
    normalized = " ".join(output.split())
    assert "metriplane demo" in normalized
    assert (
        "from a recorded incident to a verified report and a repeatable check"
        in normalized
    )
    assert "No camera is needed" in normalized
    assert "Save the report, evidence, and repeatable check in DIR" in normalized
    assert "--open" in normalized
    assert "--export-inputs" in normalized
    assert "Copy the example recorded run and process rules into a new DIR" in normalized


def test_demo_exports_exact_inspectable_inputs(tmp_path: Path, capsys) -> None:
    export_dir = tmp_path / "example inputs"

    assert demo_main(["--export-inputs", str(export_dir)]) == 0

    expected_layout = {
        "session.jsonl": "assets/assembly_cell_missing_tool.jsonl",
        "domain-pack/assets.yaml": "assets/assembly_cell/assets.yaml",
        "domain-pack/workspace.yaml": "assets/assembly_cell/workspace.yaml",
        "domain-pack/process.yaml": "assets/assembly_cell/process.yaml",
        "domain-pack/contracts.yaml": "assets/assembly_cell/contracts.yaml",
        "domain-pack/work_orders.csv": "assets/assembly_cell/work_orders.csv",
    }
    exported_files = {
        path.relative_to(export_dir).as_posix()
        for path in export_dir.rglob("*")
        if path.is_file()
    }
    assert exported_files == set(expected_layout)

    package_root = resources.files("metriplane.demo")
    for exported_relative, packaged_relative in expected_layout.items():
        assert (export_dir / exported_relative).read_bytes() == package_root.joinpath(
            packaged_relative
        ).read_bytes()

    output = capsys.readouterr().out
    assert "Metriplane example inputs exported." in output
    assert f"Recorded run: {export_dir / 'session.jsonl'}" in output
    assert f"Process rules: {export_dir / 'domain-pack'}" in output
    assert "metriplane atlas validate-pack" in output
    assert "metriplane atlas run" in output
    assert "metriplane atlas bundle verify" in output
    assert "metriplane atlas test" in output


@pytest.mark.parametrize("existing_kind", ["file", "directory", "symlink"])
def test_demo_export_refuses_every_existing_path_kind(
    tmp_path: Path, capsys, existing_kind: str
) -> None:
    destination = tmp_path / "existing"
    if existing_kind == "file":
        destination.write_text("keep", encoding="utf-8")
    elif existing_kind == "directory":
        destination.mkdir()
        (destination / "keep.txt").write_text("keep", encoding="utf-8")
    else:
        destination.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    assert demo_main(["--export-inputs", str(destination)]) == 2

    assert "Refusing to replace an existing export path" in capsys.readouterr().err
    if existing_kind == "file":
        assert destination.read_text(encoding="utf-8") == "keep"
    elif existing_kind == "directory":
        assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    else:
        assert destination.is_symlink()
        assert not destination.exists()


def test_demo_export_failure_leaves_no_partial_destination(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    import metriplane.demo as demo

    monkeypatch.setattr(
        demo,
        "_DEMO_EXPORT_LAYOUT",
        (
            ("assets/assembly_cell_missing_tool.jsonl", "session.jsonl"),
            ("assets/does-not-exist.yaml", "domain-pack/process.yaml"),
        ),
    )
    destination = tmp_path / "export"

    assert demo_main(["--export-inputs", str(destination)]) == 1

    assert not os.path.lexists(destination)
    assert list(tmp_path.iterdir()) == []
    assert "Bundled demo resource is missing" in capsys.readouterr().err


def test_demo_export_does_not_replace_destination_created_during_staging(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    destination = tmp_path / "raced-export"
    original_mkdir = Path.mkdir

    def race_destination_mkdir(path: Path, *args, **kwargs) -> None:
        if path == destination and not os.path.lexists(path):
            original_mkdir(path, mode=0o711)
            (path / "keep.txt").write_text("keep", encoding="utf-8")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", race_destination_mkdir)

    assert demo_main(["--export-inputs", str(destination)]) == 2

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert "appeared while exporting" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--out", "run"],
        ["--open"],
    ],
)
def test_demo_export_rejects_run_and_browser_options(
    tmp_path: Path, extra_args: list[str]
) -> None:
    with pytest.raises(SystemExit, match="2"):
        demo_main(["--export-inputs", str(tmp_path / "export"), *extra_args])

    assert not (tmp_path / "export").exists()


def test_demo_runs_complete_verified_workflow(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "metriplane.demo.webbrowser.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser opened")),
    )
    out_dir = tmp_path / "demo"

    assert metriplane_main(["demo", "--out", str(out_dir)]) == 0

    output = capsys.readouterr().out
    assert "Metriplane bundled demo" in output
    assert (
        "Scenario:\n"
        "A required torque driver is missing during an assembly step.\n"
        "The fastening step is delayed by 35.0 seconds."
        in output
    )
    assert "Input:\nTimestamped object positions and process rules." in output
    assert "Result:\nPASS  Incident timeline: 6 events" in output
    assert "PASS  Incident report: 1 incident" in output
    assert "PASS  Evidence bundle: verified" in output
    assert "PASS  Repeatable regression check: passed" in output
    assert f"Report:\n{out_dir / 'cell_truth_report.html'}" in output
    assert (
        "The generated check can be run again after the software or process rules change."
        in output
    )
    assert "Demo complete." in output

    manifest = json.loads((out_dir / "atlas_manifest.json").read_text(encoding="utf-8"))
    assert manifest["event_count"] == 6
    assert manifest["incident_count"] == 1
    assert manifest["source_session_jsonl"] == "state_segment.jsonl"
    assert manifest["domain_pack"] == "configs"

    bundle_path = out_dir / "evidence_bundles" / "INC-0001.zip"
    regression_path = out_dir / "regression_tests" / "INC-0001.yaml"
    report_path = out_dir / "cell_truth_report.html"
    assert verify_bundle(bundle_path)["pass"] is True
    assert run_regression(regression_path)["pass"] is True
    assert report_path.is_file()

    spec = yaml.safe_load(regression_path.read_text(encoding="utf-8"))
    source_bundle = Path(spec["source_bundle"])
    assert not source_bundle.is_absolute()
    assert (regression_path.parent / source_bundle).resolve() == bundle_path.resolve()


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
    output = capsys.readouterr().out
    assert "Browser: open request sent" in output
    assert "If no browser opens, use the Report path above." in output
    assert "Browser: opened report" not in output


def test_demo_browser_failure_keeps_success(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("metriplane.demo.webbrowser.open", lambda *_args, **_kwargs: False)

    assert demo_main(["--out", str(tmp_path / "headless"), "--open"]) == 0

    captured = capsys.readouterr()
    assert "Demo complete." in captured.out
    assert "Could not open a browser" in captured.err
    assert (tmp_path / "headless" / "cell_truth_report.html").resolve().as_uri() in captured.err


@pytest.mark.parametrize("error", [OSError("no opener"), webbrowser.Error("no browser")])
def test_demo_browser_error_keeps_success(
    tmp_path: Path, capsys, monkeypatch, error: Exception
) -> None:
    def raise_error(*_args, **_kwargs) -> bool:
        raise error

    monkeypatch.setattr("metriplane.demo.webbrowser.open", raise_error)

    assert demo_main(["--out", str(tmp_path / "browser-error"), "--open"]) == 0

    captured = capsys.readouterr()
    assert "Demo complete." in captured.out
    assert "Could not open a browser" in captured.err
