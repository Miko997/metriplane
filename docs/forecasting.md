<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Risk Forecasting

Metriplane Sentinel can emit **short-horizon risk forecasts**: predictions that an object
is likely to violate a spatial contract in the next 1–3 seconds. This is advisory only. It
is **not robot control and not a certified safety system** — it forecasts and records risk.

## What it answers

Incident detection answers "what already happened". Forecasting answers:

> What is likely to violate a rule in the next 1–3 seconds?

Example: *"cart_01 projected to enter exit_lane in 1.2 s."*

## How it works

1. **Velocity estimation** — from the last two world positions (preferred), or
   `vel_world`, or zero if no history. Velocity is clamped to 10 m/s to suppress
   marker-jitter teleports.
2. **Constant-velocity projection** — each object's path is projected from `step_s` to
   `horizon_s`. No acceleration or turning is modeled.
3. **Rule check** — projected paths are tested against contract rules:
   - `future_forbidden_zone`: a projected point lands in a forbidden polygon zone.
   - `future_minimum_distance`: two projected paths cross a distance threshold.

### Confidence

Deterministic MVP tiers:

| Confidence | Condition |
|---|---|
| 0.8 | trace velocity from ≥3 points |
| 0.6 | trace velocity from 2 points |
| 0.4 | `vel_world` only, no trace |
| 0.0 | no position/velocity |

Forecasts below `min_confidence` are suppressed.

## Config

```yaml
forecasting:
  enabled: true
  horizon_s: 2.0
  step_s: 0.2
  min_confidence: 0.55
  max_projected_points: 12
  include_projected_path: true
```

Forecasting requires a `zones_file` (polygon zones) for `future_forbidden_zone`. Without
one, zone forecasts are skipped and distance forecasts still run.

## Demo

```bash
metriplane sentinel run \
  --config configs/sentinel_forecast_demo.yaml \
  --run-id risk_forecasting_001 \
  --runs-dir ~/metriplane-runs
```

The summary reports `forecasts_total` and `risk_forecasts_enabled`.

## Limitations

- Constant-velocity only; sharp turns or stops are not predicted.
- Pairwise distance forecasting is O(n² × steps); fine at demo scale.
- A forecast is a probabilistic projection, never a guarantee. Wording everywhere uses
  "forecast" and "confidence".
