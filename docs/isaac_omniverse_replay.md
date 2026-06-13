# Isaac / Omniverse Replay

Metriplane can export camera-tracked object traces and incidents into a USD (`.usda`)
replay scene for NVIDIA Isaac Sim and Omniverse. This bridges real-world physical telemetry
with simulation / digital-twin tooling.

This is a **replay/export path**, not a full Isaac integration. The exporter is pure
Python; NVIDIA software is only needed to view the result.

## Export

```bash
python integrations/isaac/metriplane_to_usd.py \
  --run-dir evidence/incidents/INC-0001 \
  --out evidence/experiments/isaac_replay/metriplane_replay.usda
```

For Omniverse specifically:

```bash
python integrations/omniverse/metriplane_usd_replay.py --run-dir <run-or-bundle> --out scene.usda
```

## What gets exported

| Element | USD representation |
|---|---|
| floor | flat `Cube` plane |
| object | `Sphere` per named object, colored by type |
| object motion | `xformOp:translate.timeSamples` (frame index = timecode) |
| incident | red `Cube` marker annotated with id + summary |
| provenance | layer `customLayerData`: run id, source path, coordinate mapping |

## Coordinate mapping

```
USD X = Metriplane X
USD Y = Metriplane Y
USD Z = 0       (flat 2D floor replay)
upAxis = Z
```

## View it

- **Omniverse:** open the `.usda` in USD Composer / Create.
- **Isaac Sim:** `python integrations/isaac/metriplane_isaac_replay.py --run-dir <dir>`
  inside an Isaac Python environment, or open the `.usda` manually.

## Limitations

- 2D floor replay (z = 0); no 3D object geometry or physics.
- Zones are documented but not yet exported as polygons (objects + incidents are).
- Viewing in Isaac/Omniverse is a manual step on hardware with that software.
