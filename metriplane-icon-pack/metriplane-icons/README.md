# Metriplane Icon Pack

Transparent one-color SVG and PNG icons for the Metriplane website/UI.

- Default icon color: `#64DED6`
- Style: thin rounded-line telemetry/grid icon set
- SVG viewBox: `0 0 64 64`
- PNG exports: transparent `512x512`

## Included icons

- `camera-video`
- `detect-markers`
- `homography-calibration`
- `metric-xy`
- `multi-camera-fusion`
- `zones-events`
- `state-stream`
- `replay-logs`
- `observability-health`
- `schema-first`
- `integration-ready`
- `object-tracking`
- `coordinate-grid`
- `calibration-target`
- `websocket-json`
- `health-monitor`
- `dashboard-metrics`
- `api-bridge`
- `floor-state`

## Simple HTML usage

```html
<img src="/icons/svg/metriplane-metric-xy.svg" alt="Metric XY" width="32" height="32" />
```

## PNG usage

```html
<img src="/icons/png-512/metriplane-metric-xy.png" alt="Metric XY" width="32" height="32" />
```

## Inline SVG color control

The SVG files default to `#64DED6`, but they use `currentColor`, so they can be recolored when inlined or used through the sprite.

```html
<svg class="mp-icon" style="color:#40CCC4"><use href="#mp-icon-metric-xy" /></svg>
```

For this sprite approach, include `metriplane-icons-sprite.svg` inline in your page or import it with your bundler.
