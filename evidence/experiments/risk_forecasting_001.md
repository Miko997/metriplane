# Short-Horizon Risk Forecasting — Phase 18 Evidence

- phase: 18
- feature: risk_forecasting
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/forecasting/
- config_path: configs/sentinel_forecast_demo.yaml
- contract_path: configs/contracts/sentinel_demo.yaml
- zones_path: configs/zones.demo.yaml
- replay_input: tests/fixtures/contracts/forecast_session.jsonl
- horizon_s: 2.0
- step_s: 0.2

## Commands run

```bash
python -m pytest tests/test_forecasting_velocity.py \
  tests/test_forecasting_projector.py tests/test_forecasting_engine.py -q

metriplane sentinel run \
  --config configs/sentinel_forecast_demo.yaml \
  --run-id risk_forecasting_001 \
  --runs-dir <runs-dir>
```

## Result

A cart approaching `exit_lane` produced 4 `future_forbidden_zone` forecasts (ts 1.0–2.5)
before physically entering the zone at ts 3.0, which then raised 1 incident.

```json
{
  "forecasts_total": 4,
  "future_zone_forecasts": 4,
  "future_distance_forecasts": 0,
  "incidents_total": 1,
  "pass": true
}
```

## Forecast types implemented

- future_forbidden_zone (constant-velocity projection into a polygon zone)
- future_minimum_distance (pairwise projected distance crossing threshold)

## Confidence model (deterministic MVP)

- 0.8: trace velocity from ≥3 points
- 0.6: trace velocity from 2 points
- 0.4: vel_world only, no trace
- 0.0: no position/velocity

## Tests

- tests/test_forecasting_velocity.py (8)
- tests/test_forecasting_projector.py (6)
- tests/test_forecasting_engine.py (9)
- tests/test_forecasting_runtime.py (3)

## Limitations

- Constant-velocity assumption; no acceleration or turning model.
- Velocity clamped to 10 m/s to suppress marker-jitter / ID-swap teleports.
- Advisory only: forecasts are not robot control and not a guaranteed future.
- future_forbidden_zone needs a polygon zone map; without one, zone forecasts are skipped
  (distance forecasts still work).
