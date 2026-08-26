# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from metriplane.runner.operator_api import OperatorAPI

REPO = Path(__file__).resolve().parents[1]
BUNDLE = str((REPO / "evidence/incidents/INC-DIST-001").resolve())
DEMO = str((REPO / "evidence/experiments/assistant_demo").resolve())


@pytest.fixture
def api():
    return OperatorAPI(executor=None, repo_root=REPO)


def test_incidents_endpoint(api):
    st, data = api.route("POST", "/operator/incidents", {"run_dir": BUNDLE})
    assert st == 200
    assert len(data["incidents"]) >= 1
    assert data["incidents"][0]["rule_id"] == "cart_person_distance"


def test_objects_endpoint(api):
    st, data = api.route("POST", "/operator/objects", {"run_dir": BUNDLE})
    assert st == 200
    ids = {o["object_id"] for o in data["objects"]}
    assert {"cart_01", "human_proxy_01"}.issubset(ids)


def test_traces_endpoint(api):
    st, data = api.route("POST", "/operator/traces", {"run_dir": BUNDLE})
    assert st == 200
    assert len(data["traces"]) == 2


def test_live_summary_endpoint(api):
    st, data = api.route("POST", "/operator/live-summary", {"run_dir": BUNDLE})
    assert st == 200
    assert data["objects_count"] == 2
    assert data["incidents_count"] >= 1


def test_camera_trust_endpoint(api):
    st, data = api.route("POST", "/operator/camera-trust", {"run_dir": DEMO})
    assert st == 200
    assert data["camera_trust"] is not None
    assert "cam1" in data["camera_trust"]["camera_scores"]


def test_ask_endpoint(api):
    st, data = api.route(
        "POST",
        "/operator/ask",
        {"run_dir": BUNDLE, "question": "which rule triggered this incident?"},
    )
    assert st == 200
    assert data["intent"] == "rule_explanation"
    assert "min_distance" in data["answer"]


def test_ask_missing_question(api):
    st, data = api.route("POST", "/operator/ask", {"run_dir": BUNDLE})
    assert st == 400


def test_path_traversal_rejected(api):
    # /etc is outside allowed roots -> resolves to no run -> empty, never reads it
    st, data = api.route("POST", "/operator/incidents", {"run_dir": "/etc"})
    assert st == 200
    assert data["incidents"] == []


def test_frames_endpoint(api):
    st, data = api.route("POST", "/operator/frames", {"run_dir": BUNDLE})
    assert st == 200
    assert len(data["frames"]) >= 2
    # frames carry per-object positions for the replay map
    objs = data["frames"][0]["objects"]
    assert any(o["object_id"] == "cart_01" for o in objs)
    assert "incidents" in data


def test_frames_endpoint_includes_workspace_zones(api, tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    run.joinpath("session.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_backend": "dummy",
                "run_id": "workspace_test",
                "ts": 0.0,
                "frame_id": 1,
                "objects": [{"id": "1", "pos_world": [0.2, 0.3, 0.0], "zone": "zone_a"}],
                "events": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    run.joinpath("zones.yaml").write_text(
        "zones:\n"
        "  - name: zone_a\n"
        "    label: Zone A\n"
        "    polygon: [[0, 0], [1, 0], [1, 1], [0, 1]]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_cc_allowed_roots", lambda: [tmp_path.resolve()])

    st, data = api.route("POST", "/operator/frames", {"run_dir": str(run)})

    assert st == 200
    assert data["workspace"]["zones"][0]["zone_id"] == "zone_a"
    assert data["workspace"]["zones"][0]["label"] == "Zone A"


def test_unknown_endpoint_still_404(api):
    st, data = api.route("GET", "/operator/does-not-exist", {})
    assert st == 404


def test_get_endpoints_no_data_safe(api, monkeypatch, tmp_path):
    # point HOME at an empty dir so there is no ~/metriplane-runs latest run
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    st, data = api.route("GET", "/operator/objects", {})
    assert st == 200
    assert data["objects"] == []


def test_latest_command_center_run_prefers_incident_artifacts(api, monkeypatch, tmp_path):
    runs_root = tmp_path / "metriplane-runs"
    generic = runs_root / "new_generic_runtime"
    command_center = runs_root / "older_command_center"
    generic.mkdir(parents=True)
    command_center.mkdir(parents=True)
    generic.joinpath("session.jsonl").write_text('{"type":"run_header"}\n', encoding="utf-8")
    command_center.joinpath("incident.json").write_text(
        json.dumps(
            {
                "incident_id": "INC-TEST",
                "run_id": "command_center_run",
                "status": "open",
                "severity": "warning",
                "title": "test incident",
                "summary": "test incident",
            }
        ),
        encoding="utf-8",
    )
    os.utime(command_center, (1000, 1000))
    os.utime(generic, (2000, 2000))

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    st, data = api.route("GET", "/operator/live-summary", {})

    assert st == 200
    assert data["run_id"] == "command_center_run"
    assert data["incidents_count"] == 1
