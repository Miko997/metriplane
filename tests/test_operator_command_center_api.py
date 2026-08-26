# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json


from metriplane.runner.cli_command_center import main_command_center
from metriplane.runner.command_center_api import (
    export_command_center,
    get_events,
    get_frames,
    get_incidents,
    get_live_summary,
    get_objects,
    get_traces,
)

BUNDLE = "evidence/incidents/INC-DIST-001"


def test_get_objects_returns_list():
    objs = get_objects(BUNDLE)
    assert isinstance(objs, list)
    ids = {o["object_id"] for o in objs}
    assert {"cart_01", "human_proxy_01"}.issubset(ids)
    for o in objs:
        assert "type" in o and "zone" in o and "x_m" in o


def test_get_incidents_returns_list():
    incidents = get_incidents(BUNDLE)
    assert len(incidents) >= 1
    assert incidents[0]["rule_id"] == "cart_person_distance"


def test_get_traces_all():
    traces = get_traces(BUNDLE)
    assert len(traces) == 2
    assert all("duration_s" in t for t in traces)


def test_get_traces_filtered():
    traces = get_traces(BUNDLE, object_id="cart_01")
    assert len(traces) == 1
    assert traces[0]["object_id"] == "cart_01"


def test_get_events_returns_list():
    events = get_events(BUNDLE)
    assert isinstance(events, list)
    assert len(events) >= 1


def test_get_frames_for_replay():
    data = get_frames(BUNDLE)
    assert len(data["frames"]) >= 2
    f0 = data["frames"][0]
    assert "ts" in f0 and "objects" in f0
    assert any(o["object_id"] == "cart_01" for o in f0["objects"])
    # incident windows included for map highlighting
    assert isinstance(data["incidents"], list)


def test_get_frames_missing_session(tmp_path):
    assert get_frames(tmp_path) == {
        "frames": [],
        "incidents": [],
        "workspace": {"zones": [], "stations": []},
    }


def test_live_summary():
    s = get_live_summary(BUNDLE)
    assert s["objects_count"] == 2
    assert s["incidents_count"] >= 1
    assert s["health"]["overall"] == "OK"


def test_missing_artifacts_return_empty_not_error(tmp_path):
    # empty dir: every reader returns empty, no exception
    assert get_objects(tmp_path) == []
    assert get_incidents(tmp_path) == []
    assert get_traces(tmp_path) == []
    assert get_events(tmp_path) == []
    summary = get_live_summary(tmp_path)
    assert summary["objects_count"] == 0
    assert summary["incidents_count"] == 0


def test_export_writes_bundle_json(tmp_path):
    out = tmp_path / "cc.json"
    payload = export_command_center(BUNDLE, out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert set(data) == {"summary", "objects", "incidents", "events", "traces", "workspace"}
    assert payload["summary"]["objects_count"] == 2
    assert "zones" in payload["workspace"]


def test_cli_export(tmp_path):
    out = tmp_path / "cc.json"
    rc = main_command_center(["export", BUNDLE, "--out", str(out)])
    assert rc == 0
    assert out.exists()


def test_cli_summary(capsys):
    rc = main_command_center(["summary", BUNDLE])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == "INC-DIST-001"
