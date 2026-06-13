from __future__ import annotations

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
    st, data = api.route("POST", "/operator/ask",
                         {"run_dir": BUNDLE, "question": "which rule triggered this incident?"})
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
