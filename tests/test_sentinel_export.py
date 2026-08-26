# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

import pytest

from metriplane.schema import ObjectStateModel
from metriplane.sentinel.cli_runtime import main_sentinel
from metriplane.sentinel.config import SentinelConfig
from metriplane.sentinel.runtime import SentinelError, SentinelRuntime

CONTRACT = "configs/contracts/sentinel_demo.yaml"
OBJECTS = "configs/objects.example.yaml"
FIXTURE = "tests/fixtures/contracts/sentinel_minimal_session.jsonl"


def obj(marker, x, y, zone=None):
    return ObjectStateModel(id=str(marker), pos_world=(x, y, 0.0), zone=zone)


def _runtime(run_dir, run_id="t"):
    cfg = SentinelConfig(enabled=True, contracts_file=CONTRACT, objects_file=OBJECTS)
    return SentinelRuntime(cfg, run_dir=run_dir, run_id=run_id)


def test_close_writes_summary(tmp_path):
    rt = _runtime(tmp_path / "run")
    rt.update(0.0, 0, [obj(7, 1.0, 1.0, zone="exit_lane")])
    out = rt.close()
    assert out is not None and out.exists()
    data = json.loads(out.read_text())
    assert data["phase"] == 17
    assert data["control_enabled"] is False
    assert data["run_id"] == "t"
    assert data["contract_id"] == "sentinel_demo_warehouse"


def test_summary_handles_no_alerts(tmp_path):
    rt = _runtime(tmp_path / "run")
    rt.update(0.0, 0, [obj(7, 5.0, 5.0, zone="main")])  # no violation
    out = rt.close()
    data = json.loads(out.read_text())
    assert data["alerts_total"] == 0
    assert data["incidents_total"] == 0


def test_fail_fast_on_missing_contract():
    cfg = SentinelConfig(
        enabled=True, contracts_file="does/not/exist.yaml", fail_fast_on_contract_error=True
    )
    with pytest.raises(SentinelError):
        SentinelRuntime(cfg)


def test_no_fail_fast_marks_degraded():
    cfg = SentinelConfig(
        enabled=True, contracts_file="does/not/exist.yaml", fail_fast_on_contract_error=False
    )
    rt = SentinelRuntime(cfg)
    assert rt.health == "DEGRADED"


def test_cli_run_end_to_end(tmp_path, capsys):
    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "sentinel_runtime_001",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "mode=shadow_auditor" in out
    assert "control_enabled=False" in out

    summary = tmp_path / "sentinel_runtime_001" / "sentinel_summary.json"
    assert summary.exists()
    data = json.loads(summary.read_text())
    assert data["alerts_total"] >= 1
    assert data["incidents_total"] >= 1


def test_cli_status_prints_summary(tmp_path, capsys):
    main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "r1",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    rc = main_sentinel(["status", str(tmp_path / "r1")])
    assert rc == 0
    assert "shadow_auditor" in capsys.readouterr().out
