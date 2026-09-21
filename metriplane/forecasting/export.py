# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from metriplane.forecasting.models import RiskForecastModel
from metriplane.strict_parsing import iter_jsonl_path


def write_forecasts_jsonl(forecasts: list[RiskForecastModel], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for fc in forecasts:
            f.write(fc.model_dump_json() + "\n")


def read_forecasts_jsonl(path: str | Path) -> list[RiskForecastModel]:
    return [RiskForecastModel.model_validate(value) for value in iter_jsonl_path(path)]
