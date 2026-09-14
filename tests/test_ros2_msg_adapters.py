# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Run the ROS 2 bridge adapter tests as part of the core suite (no ROS required).

The adapters live in the standalone integrations/ros2 package; we load the module by
path so the core suite covers them without putting ROS on the import path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ADAPTERS = (
    Path(__file__).resolve().parents[1]
    / "integrations/ros2/metriplane_ros/metriplane_ros/msg_adapters.py"
)


@pytest.fixture(scope="module")
def adapters():
    spec = importlib.util.spec_from_file_location("mp_ros_msg_adapters", _ADAPTERS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_frame_json_roundtrips(adapters):
    frame = {"frame_id": 1, "objects": [{"id": "7"}]}
    assert json.loads(adapters.extract_frame_json(frame)) == frame


def test_alerts_top_level(adapters):
    out = adapters.extract_alert_json_strings({"alerts": [{"rule_id": "r1"}]})
    assert len(out) == 1 and json.loads(out[0])["rule_id"] == "r1"


def test_alerts_under_sentinel_metrics(adapters):
    frame = {"metrics": {"sentinel": {"alerts": [{"rule_id": "x"}]}}}
    assert json.loads(adapters.extract_alert_json_strings(frame)[0])["rule_id"] == "x"


def test_no_alerts_returns_empty(adapters):
    assert adapters.extract_alert_json_strings({"objects": []}) == []


def test_incidents(adapters):
    out = adapters.extract_incident_json_strings({"incidents": [{"incident_id": "inc_1"}]})
    assert json.loads(out[0])["incident_id"] == "inc_1"


def test_object_summary_prefers_fused(adapters):
    frame = {"fused": [{"id": "7", "pos_world": [1.0, 2.0, 0.0], "zone": "main"}]}
    assert adapters.extract_object_summary(frame) == [
        {"id": "7", "x": 1.0, "y": 2.0, "zone": "main"}
    ]
