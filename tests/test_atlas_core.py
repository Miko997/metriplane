# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from metriplane.atlas.bench import bench_core
from metriplane.atlas.bundles import verify_bundle
from metriplane.atlas.domain_packs import validate_domain_pack
from metriplane.atlas.event_ledger import read_events
from metriplane.atlas.query import index_runs, query_run_events
from metriplane.atlas.regression import create_regression_from_bundle, run_regression
from metriplane.atlas.runtime import run_atlas
from metriplane.cli import main as metriplane_main


ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "configs" / "domain_packs"
ASSEMBLY_PACK = PACK_ROOT / "assembly_cell"
ASSEMBLY_SESSION = ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_atlas_domain_packs_validate() -> None:
    for pack_name in ("assembly_cell", "robot_cell", "warehouse_lane", "line_clearance", "training_lab"):
        assert validate_domain_pack(PACK_ROOT / pack_name) == []


def test_atlas_domain_pack_validation_reports_bad_references(tmp_path: Path) -> None:
    broken = tmp_path / "broken_pack"
    shutil.copytree(ASSEMBLY_PACK, broken)
    process_path = broken / "process.yaml"
    data = yaml.safe_load(process_path.read_text(encoding="utf-8"))
    data["steps"][-1]["required_assets"] = ["missing_fixture_99"]
    process_path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")

    errors = validate_domain_pack(broken)

    assert any("missing_fixture_99" in error for error in errors)


def test_atlas_runtime_generates_replayable_cell_black_box_artifacts(tmp_path: Path) -> None:
    before_hash = _sha256(ASSEMBLY_SESSION)
    run_dir = tmp_path / "run"

    manifest = run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_dir, run_id="atlas_pytest")

    assert _sha256(ASSEMBLY_SESSION) == before_hash
    assert manifest.frame_count == 5
    assert manifest.event_count == 6
    assert manifest.incident_count == 1
    events = read_events(run_dir / "physical_event_log.jsonl")
    assert [event.event_type for event in events] == [
        "step_completed",
        "step_completed",
        "required_asset_missing",
        "step_delayed",
        "required_asset_present",
        "step_completed",
    ]
    assert events[3].value == 35.0

    report = (run_dir / "cell_truth_report.md").read_text(encoding="utf-8")
    assert "Cell Truth Report" in report
    assert "not a certified safety or quality decision system" in report
    assert "Add a required-tool staging check" in report
    report_html = (run_dir / "cell_truth_report.html").read_text(encoding="utf-8")
    assert '<table class="report-table">' in report_html
    assert "<pre>| issue" not in report_html

    bundle_zip = run_dir / "evidence_bundles" / "INC-0001.zip"
    assert verify_bundle(bundle_zip)["pass"] is True

    extracted_bundle = bundle_zip.with_suffix("")
    shutil.rmtree(extracted_bundle)
    regression_result = run_regression(run_dir / "regression_tests" / "INC-0001.yaml")
    assert regression_result["pass"] is True

    generated_spec = tmp_path / "zip_only_regression.yaml"
    spec = create_regression_from_bundle(bundle_zip, generated_spec)
    assert spec.expected_incidents[0]["incident_type"] == "missing_tool_caused_delay"
    assert run_regression(generated_spec)["pass"] is True

    assert (run_dir / "training_cases" / "INC-0001.md").exists()
    assert (run_dir / "improvement_actions.json").exists()


def test_atlas_outputs_are_deterministic_for_same_run_id(tmp_path: Path) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"

    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_a, run_id="atlas_deterministic")
    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_b, run_id="atlas_deterministic")

    for artifact in ("physical_event_log.jsonl", "deviations.jsonl", "incidents.jsonl", "reality_graph.json", "process_trace.json"):
        assert (run_a / artifact).read_text(encoding="utf-8") == (run_b / artifact).read_text(encoding="utf-8")


def test_atlas_bundle_verifier_detects_corruption(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_dir, run_id="atlas_corruption")
    bundle_dir = run_dir / "evidence_bundles" / "INC-0001"
    incident_path = bundle_dir / "incident.json"
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    incident["title"] = "tampered"
    incident_path.write_text(json.dumps(incident, indent=2, sort_keys=True), encoding="utf-8")

    result = verify_bundle(bundle_dir)

    assert result["pass"] is False
    assert any("checksum mismatch: incident.json" in error for error in result["errors"])


def test_atlas_query_index_bench_and_cli(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    run_dir = tmp_path / "run"
    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_dir, run_id="atlas_query")

    tool_events = query_run_events(run_dir, asset_id="torque_driver_1")
    assert [event["event_type"] for event in tool_events] == [
        "required_asset_missing",
        "step_delayed",
        "required_asset_present",
        "step_completed",
    ]
    station_events = query_run_events(run_dir, station_id="station_a")
    assert station_events

    indexed = index_runs(tmp_path)
    assert indexed["runs"][0]["run_id"] == "atlas_query"

    bench = bench_core(ASSEMBLY_SESSION, ASSEMBLY_PACK, tmp_path / "bench")
    assert bench["bundles_pass"] is True
    assert bench["regressions_pass"] is True
    assert bench["event_count"] == 6

    assert metriplane_main(["atlas", "validate-pack", str(ASSEMBLY_PACK)]) == 0
    validate_output = capsys.readouterr().out
    assert "PASS" in validate_output

    cli_out = tmp_path / "cli_run"
    assert metriplane_main([
        "atlas",
        "run",
        "--session-jsonl",
        str(ASSEMBLY_SESSION),
        "--pack",
        str(ASSEMBLY_PACK),
        "--out",
        str(cli_out),
        "--run-id",
        "atlas_cli",
    ]) == 0
    run_output = capsys.readouterr().out
    assert "events=6" in run_output
    assert (cli_out / "cell_truth_report.html").exists()
