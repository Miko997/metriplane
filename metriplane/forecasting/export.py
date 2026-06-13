from __future__ import annotations

from pathlib import Path

from metriplane.forecasting.models import RiskForecastModel


def write_forecasts_jsonl(forecasts: list[RiskForecastModel], path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for fc in forecasts:
            f.write(fc.model_dump_json() + "\n")


def read_forecasts_jsonl(path) -> list[RiskForecastModel]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            out.append(RiskForecastModel.model_validate_json(line))
    return out
