# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from metriplane.sentinel.cli_runtime import main_sentinel
from metriplane.sentinel.config import SentinelConfig


def test_forecasting_config_parsed():
    cfg = SentinelConfig.from_dict(
        {
            "enabled": True,
            "contracts_file": "c.yaml",
            "zones_file": "z.yaml",
            "forecasting": {"enabled": True, "horizon_s": 2.0},
        }
    )
    assert cfg.forecasting == {"enabled": True, "horizon_s": 2.0}
    assert cfg.zones_file == "z.yaml"


def test_sentinel_run_reports_forecasts(tmp_path, capsys):
    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_forecast_demo.yaml",
            "--run-id",
            "fc",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    data = json.loads((tmp_path / "fc" / "sentinel_summary.json").read_text())
    assert data["risk_forecasts_enabled"] is True
    assert data["forecasts_total"] >= 1
    assert data["incidents_total"] >= 1


def test_forecasting_disabled_by_default(tmp_path):
    # the non-forecast demo config has no forecasting block
    rc = main_sentinel(
        [
            "run",
            "--config",
            "configs/sentinel_demo.yaml",
            "--run-id",
            "nofc",
            "--runs-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    data = json.loads((tmp_path / "nofc" / "sentinel_summary.json").read_text())
    assert data["risk_forecasts_enabled"] is False
    assert data["forecasts_total"] == 0
