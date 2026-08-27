# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import threading

from metriplane.fleet.agent import FleetAgent, FleetAgentConfig
from metriplane.fleet.heartbeat import FleetHeartbeat


def test_heartbeat_serializes():
    hb = FleetHeartbeat(
        node_id="cam_node_01",
        ts=1.0,
        run_id="r",
        git_commit="abc",
        config_hash="def",
        health_overall="OK",
        fps=30.0,
        objects_tracked=3,
        active_incidents=1,
        frames_total=100,
        frames_dropped_total=0,
    )
    data = json.loads(hb.to_json())
    assert data["node_id"] == "cam_node_01"
    assert data["fps"] == 30.0


def test_emit_once_writes_jsonl(tmp_path):
    out = tmp_path / "hb.jsonl"
    agent = FleetAgent(
        FleetAgentConfig(
            node_id="cam_node_01", output_path=str(out), run_id="fleet_test", git_commit="abc123"
        ),
        metrics_provider=lambda: {
            "health_overall": "OK",
            "fps": 30.0,
            "objects_tracked": 3,
            "active_incidents": 1,
        },
    )
    hb = agent.emit_once()
    assert hb.node_id == "cam_node_01"
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["run_id"] == "fleet_test"
    assert rec["git_commit"] == "abc123"
    assert rec["health_overall"] == "OK"
    assert rec["fps"] == 30.0


def test_heartbeat_includes_provenance():
    agent = FleetAgent(
        FleetAgentConfig(node_id="n", run_id="r1", git_commit="c1", config_hash="h1")
    )
    hb = agent.build_heartbeat()
    assert hb.run_id == "r1"
    assert hb.git_commit == "c1"
    assert hb.config_hash == "h1"


def test_metrics_provider_failure_is_safe():
    def boom():
        raise RuntimeError("nope")

    agent = FleetAgent(FleetAgentConfig(node_id="n"), metrics_provider=boom)
    hb = agent.build_heartbeat()
    assert hb.health_overall == "OK"  # falls back, no crash


def test_start_stop_emits(tmp_path):
    out = tmp_path / "hb.jsonl"
    emitted_twice = threading.Event()
    emissions = 0

    def metrics():
        nonlocal emissions
        emissions += 1
        if emissions >= 2:
            emitted_twice.set()
        return {"fps": 10.0}

    agent = FleetAgent(
        FleetAgentConfig(node_id="n", heartbeat_interval_s=0.05, output_path=str(out)),
        metrics_provider=metrics,
    )
    agent.start()
    try:
        assert emitted_twice.wait(timeout=2.0)
    finally:
        agent.stop()
    lines = out.read_text().strip().splitlines()
    assert len(lines) >= 2  # several heartbeats emitted


def test_from_config_dict_disabled():
    assert FleetAgent.from_config_dict({"enabled": False}) is None
    assert FleetAgent.from_config_dict(None) is None


def test_from_config_dict_enabled(tmp_path):
    agent = FleetAgent.from_config_dict(
        {"enabled": True, "node_id": "cam_node_02", "output_file": "hb.jsonl"},
        run_dir=tmp_path,
        run_id="r9",
    )
    assert agent is not None
    hb = agent.emit_once()
    assert hb.node_id == "cam_node_02"
    assert hb.run_id == "r9"
    assert (tmp_path / "hb.jsonl").exists()
