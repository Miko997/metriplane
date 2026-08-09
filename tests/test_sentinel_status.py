# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from metriplane.schema import FrameStateModel, ObjectStateModel
from metriplane.sentinel.config import SentinelConfig
from metriplane.sentinel.runtime import SentinelRuntime
from metriplane.sentinel.engine import RuleEngine
from metriplane.sentinel.registry import load_registry
from metriplane.sentinel.rules import load_rules

CONTRACT = "configs/contracts/sentinel_demo.yaml"
OBJECTS = "configs/objects.example.yaml"


def obj(marker, x, y, zone=None):
    return ObjectStateModel(id=str(marker), pos_world=(x, y, 0.0), zone=zone)


def _runtime(run_dir=None, run_id="t"):
    cfg = SentinelConfig(enabled=True, contracts_file=CONTRACT, objects_file=OBJECTS)
    return SentinelRuntime(cfg, run_dir=run_dir, run_id=run_id)


def test_status_starts_zero():
    rt = _runtime()
    st = rt.status()
    assert st.mode == "shadow_auditor"
    assert st.control_enabled is False
    assert st.objects_tracked == 0
    assert st.active_alerts == 0
    assert st.open_incidents == 0


def test_status_reflects_object_count():
    rt = _runtime()
    rt.update(0.0, 0, [obj(7, 5.0, 5.0, zone="main"), obj(12, 0.0, 0.0, zone="storage")])
    assert rt.status().objects_tracked == 2


def test_status_reflects_alerts_and_incidents():
    rt = _runtime()
    # cart in exit_lane → forbidden_zone alert
    rt.update(0.0, 0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    st = rt.status()
    assert st.active_alerts >= 1
    assert st.open_incidents >= 1


def test_status_serializes_to_json():
    rt = _runtime()
    rt.update(0.0, 0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    payload = rt.status().model_dump_json()
    data = json.loads(payload)
    assert data["mode"] == "shadow_auditor"
    assert data["control_enabled"] is False


def test_disabled_runtime_reports_disabled():
    rt = SentinelRuntime(SentinelConfig(enabled=False))
    assert rt.status().mode == "disabled"


def test_explicit_empty_fusion_does_not_fall_back_to_raw_objects() -> None:
    engine = RuleEngine(load_rules("configs/rules.example.yaml"), load_registry(OBJECTS))
    frame = FrameStateModel(
        source_backend="fusion",
        ts=0.0,
        frame_id=1,
        objects=[obj(7, 1.0, 1.0, zone="exit_lane")],
        fused=[],
    )

    assert engine.process_frame(frame) == []
