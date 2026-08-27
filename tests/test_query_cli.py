# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

import pytest

from metriplane.sentinel.cli_incidents import main_incidents
from metriplane.sentinel.cli_query import main_query
from metriplane.sentinel.cli_rules import main_rules

CONFIG_OBJECTS = "configs/objects.example.yaml"
CONFIG_RULES = "configs/rules.example.yaml"


def make_frame(ts, frame_id, objects, run_id="query_test"):
    objs = [
        {
            "id": str(o["id"]),
            "pos_world": o.get("pos"),
            "vel_world": o.get("vel"),
            "zone": o.get("zone"),
        }
        for o in objects
    ]
    return json.dumps(
        {
            "schema_version": "1.0",
            "source_backend": "dummy",
            "run_id": run_id,
            "ts": ts,
            "frame_id": frame_id,
            "objects": objs,
            "events": [],
        }
    )


@pytest.fixture
def session(tmp_path):
    lines = [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(2.0, 2, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
    ]
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture
def incidents_json(tmp_path, session):
    out = tmp_path / "incidents.json"
    rc = main_incidents(
        [
            "run",
            "--session",
            str(session),
            "--rules",
            CONFIG_RULES,
            "--objects",
            CONFIG_OBJECTS,
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    return out


@pytest.fixture
def alerts_jsonl(tmp_path, session):
    out = tmp_path / "alerts.jsonl"
    rc = main_rules(
        [
            "run",
            "--session",
            str(session),
            "--rules",
            CONFIG_RULES,
            "--objects",
            CONFIG_OBJECTS,
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    return out


def test_rules_run_writes_alerts(alerts_jsonl):
    content = alerts_jsonl.read_text().strip()
    assert content  # at least one alert
    first = json.loads(content.splitlines()[0])
    assert first["rule_id"] == "no_cart_in_exit_lane"


def test_incidents_run_writes_incidents(incidents_json):
    data = json.loads(incidents_json.read_text())
    assert len(data) >= 1
    assert data[0]["rule_id"] == "no_cart_in_exit_lane"


def test_incidents_list(incidents_json, capsys):
    rc = main_incidents(["list", "--incidents", str(incidents_json)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no_cart_in_exit_lane" in out


def test_incidents_show(incidents_json, capsys):
    inc_id = json.loads(incidents_json.read_text())[0]["incident_id"]
    rc = main_incidents(["show", inc_id, "--incidents", str(incidents_json)])
    assert rc == 0
    out = capsys.readouterr().out
    assert inc_id in out
    assert "cart_01" in out


def test_incidents_show_not_found(incidents_json, capsys):
    rc = main_incidents(["show", "inc_9999", "--incidents", str(incidents_json)])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_query_incidents_filter_by_severity(incidents_json, capsys):
    rc = main_query(["incidents", "--incidents", str(incidents_json), "--severity", "warning"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no_cart_in_exit_lane" in out


def test_query_incidents_filter_excludes(incidents_json, capsys):
    rc = main_query(["incidents", "--incidents", str(incidents_json), "--severity", "critical"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "0 of" in out  # the warning incident is excluded


def test_query_incidents_filter_by_object(incidents_json, capsys):
    rc = main_query(["incidents", "--incidents", str(incidents_json), "--object", "cart_01"])
    assert rc == 0
    assert "no_cart_in_exit_lane" in capsys.readouterr().out


def test_query_alerts_filter_by_rule(alerts_jsonl, capsys):
    rc = main_query(["alerts", "--alerts", str(alerts_jsonl), "--rule", "no_cart_in_exit_lane"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no_cart_in_exit_lane" in out


def test_query_traces_filter_by_object(session, capsys):
    rc = main_query(
        ["traces", "--session", str(session), "--objects", CONFIG_OBJECTS, "--object", "cart_01"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "cart_01" in out


def test_query_traces_filter_by_zone(session, capsys):
    rc = main_query(
        ["traces", "--session", str(session), "--objects", CONFIG_OBJECTS, "--zone", "exit_lane"]
    )
    assert rc == 0
    assert "cart_01" in capsys.readouterr().out


def test_bundle_and_verify_end_to_end(tmp_path, session, capsys):
    inc_out = tmp_path / "incidents.json"
    main_incidents(
        [
            "run",
            "--session",
            str(session),
            "--rules",
            CONFIG_RULES,
            "--objects",
            CONFIG_OBJECTS,
            "--out",
            str(inc_out),
        ]
    )
    inc_id = json.loads(inc_out.read_text())[0]["incident_id"]

    bundle_dir = tmp_path / "bundle"
    rc = main_incidents(
        [
            "bundle",
            inc_id,
            "--session",
            str(session),
            "--rules",
            CONFIG_RULES,
            "--objects",
            CONFIG_OBJECTS,
            "--out",
            str(bundle_dir),
        ]
    )
    assert rc == 0
    assert (bundle_dir / "incident.json").exists()

    capsys.readouterr()  # clear
    rc = main_incidents(["verify-bundle", str(bundle_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "incident reproduced" in out
    assert "checksum verified" in out
