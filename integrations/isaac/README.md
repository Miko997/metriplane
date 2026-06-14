<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane → Isaac / USD Replay

Export Metriplane traces and incidents into a USD (`.usda`) replay scene that opens in
NVIDIA Isaac Sim or Omniverse. The exporter is **pure Python and needs no NVIDIA
software** — Isaac is only required to *view* the result.

## Export

```bash
python integrations/isaac/metriplane_to_usd.py \
  --run-dir evidence/incidents/INC-0001 \
  --out /tmp/metriplane_replay.usda
```

`--run-dir` may be an incident evidence bundle (with `session_excerpt.jsonl`,
`incident.json`, `objects.yaml`) or any run dir containing a `session.jsonl`.

Outputs:

- `metriplane_replay.usda` — the scene
- `metriplane_replay_manifest.json` — run id, object/incident ids, coordinate mapping

## Scene contents

- a floor plane;
- one sphere per named object, colored by type (cart/pallet/human_proxy/robot);
- time-sampled `xformOp:translate` per object (frame index = USD timecode);
- one red cube per incident, annotated with its id and summary;
- layer metadata: run id, source path, coordinate mapping.

## Coordinate mapping

```
USD X = Metriplane X
USD Y = Metriplane Y
USD Z = 0   (flat 2D floor replay)
```

## View in Isaac Sim

Inside an Isaac Sim Python environment:

```bash
python integrations/isaac/metriplane_isaac_replay.py --run-dir runs/<id>
```

Or open the exported `.usda` manually in Omniverse USD Composer / Isaac Sim.

## Status

This is a **replay/export path**, not a full Isaac integration. It is verified by exporting
valid USD text with time samples and incident markers; viewing inside Isaac/Omniverse is a
manual step on hardware with that software installed.
