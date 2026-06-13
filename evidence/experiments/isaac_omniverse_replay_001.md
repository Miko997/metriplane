# Isaac / Omniverse Replay — Phase 09 Evidence

- phase: 09
- feature: isaac_omniverse_replay
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- exporter: integrations/isaac/metriplane_to_usd.py
- source: evidence/incidents/INC-0001 (incident bundle)

## Export command

```bash
python integrations/isaac/metriplane_to_usd.py \
  --run-dir evidence/incidents/INC-0001 \
  --out evidence/experiments/isaac_replay/metriplane_replay.usda
```

## Output

- `evidence/experiments/isaac_replay/metriplane_replay.usda`
- `evidence/experiments/isaac_replay/metriplane_replay_manifest.json`

```json
{
  "run_id": "INC-0001",
  "frames": 5,
  "coordinate_mapping": "USD_X=X, USD_Y=Y, USD_Z=0 (2D floor)",
  "object_ids": ["cart_01"],
  "incident_ids": ["inc_0001"]
}
```

The `.usda` contains a floor plane, a `Sphere "cart_01"` with time-sampled
`xformOp:translate` across 5 frames (cart entering then leaving `exit_lane`), and a red
incident marker cube annotated with the incident id and summary.

## Verification

- Pure-Python export, no NVIDIA software required (verified on this host).
- tests/test_usd_export_adapter.py (9 tests): trace/incident loading, file creation,
  object names, time samples, incident marker, coordinate-mapping metadata, manifest.

## Coordinate mapping

USD X = Metriplane X, USD Y = Metriplane Y, USD Z = 0 (flat 2D floor replay), upAxis = Z.

## Limitations

- 2D floor replay; no 3D geometry or physics.
- Zones not yet exported as polygons.
- Viewing in Isaac Sim / Omniverse is a manual step on hardware with that software; the
  export itself is what this evidence covers.
