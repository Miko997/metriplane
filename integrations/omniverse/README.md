# Metriplane → Omniverse USD Replay

Generate a Metriplane USD replay scene for NVIDIA Omniverse. The `.usda` produced here is
standard USD and opens in Omniverse USD Composer / Create.

```bash
python integrations/omniverse/metriplane_usd_replay.py \
  --run-dir evidence/incidents/INC-0001 \
  --out /tmp/metriplane_replay.usda
```

This delegates to the [Isaac exporter](../isaac/README.md); see that README for scene
contents and coordinate mapping. No NVIDIA software is needed to produce the file.
