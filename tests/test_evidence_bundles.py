# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metriplane.sentinel.bundles import (
    create_bundle,
    verify_bundle,
    verify_checksums,
)
from metriplane.sentinel.engine import evaluate_session
from metriplane.sentinel.incidents import build_incidents
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import load_rules

CONFIG_OBJECTS = "configs/objects.example.yaml"
CONFIG_RULES = "configs/rules.example.yaml"


def make_frame(ts, frame_id, objects, run_id="bundle_test"):
    objs = [
        {"id": str(o["id"]), "pos_world": o.get("pos"),
         "vel_world": o.get("vel"), "zone": o.get("zone")}
        for o in objects
    ]
    return json.dumps({
        "schema_version": "1.0", "source_backend": "dummy", "run_id": run_id,
        "ts": ts, "frame_id": frame_id, "objects": objs, "events": [],
    })


@pytest.fixture
def scenario(tmp_path):
    """Cart_01 sits in exit_lane → one forbidden_zone incident."""
    lines = [
        make_frame(0.0, 0, [{"id": 7, "pos": [0.0, 0.0, 0.0], "zone": "main"}]),
        make_frame(1.0, 1, [{"id": 7, "pos": [1.0, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(2.0, 2, [{"id": 7, "pos": [1.1, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(3.0, 3, [{"id": 7, "pos": [1.2, 0.0, 0.0], "zone": "exit_lane"}]),
        make_frame(4.0, 4, [{"id": 7, "pos": [2.0, 0.0, 0.0], "zone": "main"}]),
    ]
    session = tmp_path / "session.jsonl"
    session.write_text("\n".join(lines) + "\n")

    ruleset = load_rules(CONFIG_RULES)
    registry = load_registry(CONFIG_OBJECTS)
    alerts, _ = evaluate_session(session, ruleset, registry)
    incidents = build_incidents(alerts)
    assert incidents, "scenario must produce at least one incident"
    return {
        "session": session,
        "alerts": alerts,
        "incidents": incidents,
        "incident": incidents[0],
    }


def test_bundle_files_present(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    for name in ["incident.json", "alerts.jsonl", "session_excerpt.jsonl",
                 "trace.csv", "report.md", "report.html", "replay.sh",
                 "CHECKSUMS.sha256", "objects.yaml", "rules.yaml"]:
        assert (out / name).exists(), f"missing {name}"


def test_bundle_replay_sh_executable(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    import os
    assert os.access(out / "replay.sh", os.X_OK)


def test_bundle_verifies_ok(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    ok, messages = verify_bundle(out)
    assert ok, messages
    assert any("incident reproduced" in m for m in messages)
    assert any("checksum verified" in m for m in messages)


def test_checksums_detect_tampering(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    # tamper with the report
    (out / "report.md").write_text("tampered")
    errors = verify_checksums(out)
    assert any("report.md" in e for e in errors)


def test_bundle_verify_fails_on_tamper(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    (out / "trace.csv").write_text("garbage")
    ok, _ = verify_bundle(out)
    assert ok is False


def test_excerpt_only_contains_window(tmp_path, scenario):
    out = tmp_path / "bundle"
    create_bundle(
        incident=scenario["incident"], alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    excerpt = (out / "session_excerpt.jsonl").read_text().strip().splitlines()
    assert len(excerpt) >= 1
    for line in excerpt:
        rec = json.loads(line)
        assert isinstance(rec["ts"], (int, float))


def test_bundle_only_includes_incident_alerts(tmp_path, scenario):
    from metriplane.sentinel.events import read_alerts_jsonl
    out = tmp_path / "bundle"
    inc = scenario["incident"]
    create_bundle(
        incident=inc, alerts=scenario["alerts"],
        out_dir=out, session_path=scenario["session"],
        objects_path=CONFIG_OBJECTS, rules_path=CONFIG_RULES,
    )
    bundled = read_alerts_jsonl(out / "alerts.jsonl")
    assert {a.alert_id for a in bundled} == set(inc.alert_ids)
