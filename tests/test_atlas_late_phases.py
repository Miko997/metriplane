# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from metriplane.atlas.dashboard import dashboard_payload
from metriplane.atlas.edge import edge_doctor, retention_plan, write_edge_bundle
from metriplane.atlas.evidence_lake import build_lake, lake_query, trend_summary
from metriplane.atlas.freeze import build_freeze, claim_audit
from metriplane.atlas.improvement import compare_runs
from metriplane.atlas.multicell import compare_cells
from metriplane.atlas.pilot import create_pilot_kit
from metriplane.atlas.privacy import anonymize_run, privacy_report
from metriplane.atlas.protocol import compat_check, export_protocol
from metriplane.atlas.query import explain_query, run_saved_query
from metriplane.atlas.runtime import run_atlas
from metriplane.cli import main as metriplane_main


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY_PACK = ROOT / "configs" / "domain_packs" / "assembly_cell"
ASSEMBLY_SESSION = ROOT / "datasets" / "demo" / "atlas" / "assembly_cell_missing_tool.jsonl"
SAVED_QUERIES = ROOT / "configs" / "atlas" / "saved_queries.yaml"


def _run(tmp_path: Path, name: str = "run", run_id: str = "atlas_late") -> Path:
    run_dir = tmp_path / name
    run_atlas(ASSEMBLY_SESSION, ASSEMBLY_PACK, run_dir, run_id=run_id)
    return run_dir


def _after_session_with_tool_ready(path: Path) -> Path:
    out = path / "assembly_cell_tool_ready.jsonl"
    rows = []
    for line in ASSEMBLY_SESSION.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        if data.get("type") == "run_header":
            rows.append(data)
            continue
        if data["frame_id"] in {3, 4}:
            tool = {"id": "12", "pos_world": [2.6, 0.7, 0.0], "zone": "station_a_work", "confidence": 0.97}
            data["objects"].append(tool)
            data["fused"].append(tool)
        rows.append(data)
    out.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return out


def test_late_phase_default_run_artifacts(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)

    dashboard = (run_dir / "atlas_dashboard.html").read_text(encoding="utf-8")
    assert "Atlas Cell Black Box" in dashboard
    assert "Verify bundle" in dashboard
    payload = dashboard_payload(run_dir)
    assert payload["schema_version"] == "metriplane.atlas.dashboard_payload.v1"
    assert len(payload["events"]) == 6

    usda = (run_dir / "twinverify_replay.usda").read_text(encoding="utf-8")
    assert "#usda 1.0" in usda
    assert "station_a_work" in usda
    assert "torque_driver_1" in usda
    assert "INC-0001" in usda

    privacy = json.loads((run_dir / "privacy_report.json").read_text(encoding="utf-8"))
    assert privacy["video_free"] is True
    assert privacy["biometric_free"] is True

    assert (run_dir / "connectors" / "events.csv").read_text(encoding="utf-8").startswith("run_id,event_id")
    rest = json.loads((run_dir / "connectors" / "rest_snapshot.json").read_text(encoding="utf-8"))
    assert "/events" in rest["endpoints"]


def test_lake_saved_queries_protocol_edge_and_freeze(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, "run_a", "atlas_lake_a")
    db = tmp_path / "lake.sqlite"

    build = build_lake(tmp_path, db)
    assert build["run_count"] == 1
    assert build["event_count"] == 6
    delayed = lake_query(db, event_type="step_delayed")
    assert delayed[0]["asset_id"] == "torque_driver_1"
    trends = trend_summary(db, tmp_path / "trends.json")
    assert trends["by_cell"][0]["cell_id"] == "cell_assembly_a"

    saved = run_saved_query(run_dir, SAVED_QUERIES, "delayed_steps")
    assert saved[0]["event_type"] == "step_delayed"
    listed = explain_query(SAVED_QUERIES)
    assert any(query["query_id"] == "torque_driver_history" for query in listed["queries"])

    protocol = export_protocol(tmp_path / "protocol")
    assert len(protocol["schema_files"]) >= 10
    compat = compat_check(ASSEMBLY_PACK, run_dir / "evidence_bundles" / "INC-0001.zip")
    assert compat["pass"] is True

    edge = edge_doctor(tmp_path, min_free_mb=1)
    assert edge["pass"] is True
    retention = retention_plan(tmp_path, keep_last=1)
    assert retention["keep_run_dirs"]
    assert write_edge_bundle(tmp_path, tmp_path / "edge.json").exists()

    freeze = build_freeze(ROOT, tmp_path / "freeze")
    assert Path(freeze["claim_audit"]).exists()
    audit = claim_audit(ROOT)
    assert any(row["status"] == "EXTERNAL_REQUIRED" for row in audit["claims"])


def test_multicell_privacy_pilot_and_improvement(tmp_path: Path) -> None:
    before = _run(tmp_path, "before", "atlas_before")
    pack_b = tmp_path / "pack_b"
    shutil.copytree(ASSEMBLY_PACK, pack_b)
    workspace_path = pack_b / "workspace.yaml"
    workspace = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    workspace["cell_id"] = "cell_assembly_b"
    workspace_path.write_text(yaml.safe_dump(workspace, sort_keys=True), encoding="utf-8")
    run_atlas(ASSEMBLY_SESSION, pack_b, tmp_path / "cell_b", run_id="atlas_cell_b")

    comparison = compare_cells(tmp_path, tmp_path / "multicell.json", tmp_path / "multicell.md")
    assert {cell["cell_id"] for cell in comparison["cells"]} == {"cell_assembly_a", "cell_assembly_b"}

    report = privacy_report(before, tmp_path / "privacy.json")
    assert report["video_free"] is True
    anon = anonymize_run(before, tmp_path / "anon")
    assert anon["mapped_values"] > 0
    assert anon["mapping_exported"] is False
    assert not (tmp_path / "anon" / "asset_proxy_map.json").exists()
    assert (tmp_path / "anon" / "privacy_metadata.json").exists()

    pilot = create_pilot_kit(tmp_path / "pilot")
    assert len(pilot["files"]) == 4
    assert (tmp_path / "pilot" / "reviewer_questionnaire.md").exists()

    after_session = _after_session_with_tool_ready(tmp_path)
    after = tmp_path / "after"
    run_atlas(after_session, ASSEMBLY_PACK, after, run_id="atlas_after")
    result = compare_runs(before, after, tmp_path / "before_after.json")
    assert result["after_incidents"] < result["before_incidents"]
    assert result["wait_time_delta_s"] < 0


def test_late_phase_cli_commands(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    run_dir = _run(tmp_path, "cli_run", "atlas_cli_late")

    assert metriplane_main(["atlas", "dashboard", "build", "--run-dir", str(run_dir)]) == 0
    assert "atlas_dashboard.html" in capsys.readouterr().out
    assert metriplane_main(["atlas", "twinverify", "export-usd", "--run-dir", str(run_dir)]) == 0
    assert "twinverify_replay.usda" in capsys.readouterr().out
    assert metriplane_main(["atlas", "connectors", "export", "--run-dir", str(run_dir)]) == 0
    assert "events.csv" in capsys.readouterr().out
    assert metriplane_main(["atlas", "query", "saved", "--run-dir", str(run_dir), "--query-id", "delayed_steps", "--json"]) == 0
    assert "step_delayed" in capsys.readouterr().out
    assert metriplane_main(["atlas", "privacy", "report", "--run-dir", str(run_dir), "--out", str(tmp_path / "privacy_cli.json")]) == 0
    assert "video_free" in capsys.readouterr().out
    assert metriplane_main(["atlas", "pilot", "kit", "--out", str(tmp_path / "pilot_cli")]) == 0
    assert "pilot_checklist" in capsys.readouterr().out
