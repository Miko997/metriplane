# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""ROS-free unit tests for the bridge message adapters."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metriplane_ros.msg_adapters import (  # noqa: E402
    extract_alert_json_strings,
    extract_frame_json,
    extract_incident_json_strings,
    extract_object_summary,
)


def test_frame_json_roundtrips():
    frame = {"frame_id": 1, "objects": [{"id": "7"}]}
    assert json.loads(extract_frame_json(frame)) == frame


def test_alerts_top_level():
    frame = {"alerts": [{"rule_id": "r1"}, {"rule_id": "r2"}]}
    out = extract_alert_json_strings(frame)
    assert len(out) == 2
    assert json.loads(out[0])["rule_id"] == "r1"


def test_alerts_under_sentinel_metrics():
    frame = {"metrics": {"sentinel": {"alerts": [{"rule_id": "x"}]}}}
    out = extract_alert_json_strings(frame)
    assert len(out) == 1
    assert json.loads(out[0])["rule_id"] == "x"


def test_no_alerts_returns_empty():
    assert extract_alert_json_strings({"objects": []}) == []


def test_incidents():
    frame = {"incidents": [{"incident_id": "inc_0001"}]}
    out = extract_incident_json_strings(frame)
    assert json.loads(out[0])["incident_id"] == "inc_0001"


def test_object_summary_uses_fused_first():
    frame = {"fused": [{"id": "7", "pos_world": [1.0, 2.0, 0.0], "zone": "main"}],
             "objects": [{"id": "99", "pos_world": [9.0, 9.0, 0.0]}]}
    out = extract_object_summary(frame)
    assert out == [{"id": "7", "x": 1.0, "y": 2.0, "zone": "main"}]


def test_object_summary_handles_missing_pos():
    out = extract_object_summary({"objects": [{"id": "7"}]})
    assert out[0]["x"] is None and out[0]["y"] is None
