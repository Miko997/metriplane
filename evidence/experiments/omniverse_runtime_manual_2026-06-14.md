<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Evidence: Omniverse manual runtime smoke - 2026-06-14

## Result

PARTIAL

## Test type

Manual runtime smoke evidence reconciliation.

## Environment

- OS: Linux miko-21796-2252-20700 6.17.0-35-generic x86_64 GNU/Linux
- Python: Python 3.12.3
- MetriPlane commit: 1ca27a1
- Omniverse launcher: /home/miko/bin/omniverse
- GPU: NVIDIA GeForce RTX 5070 Ti
- Driver: 580.159.03
- CUDA, if relevant: not measured in this smoke
- Shell: /bin/bash
- Working directory: /home/miko/projects/metriplane-public

## Commands run

```bash
sha256sum web/dashboard/atlas_run/omniverse/metriplane_replay.usda \
  web/dashboard/atlas_run/twinverify_replay.usda \
  evidence/experiments/isaac_replay/metriplane_replay.usda
cp web/dashboard/atlas_run/omniverse/metriplane_replay.usda \
  evidence/experiments/manual_omniverse_2026-06-14/metriplane_replay.usda
head -60 web/dashboard/atlas_run/omniverse/metriplane_replay.usda
sha256sum evidence/experiments/manual_omniverse_2026-06-14/*
```

The Omniverse open action was reported manually by the maintainer, but no raw
open log or screenshot was captured into the repository for this evidence pass.

## Artifacts

- `evidence/experiments/manual_omniverse_2026-06-14/environment.txt`
- `evidence/experiments/manual_omniverse_2026-06-14/usd_sha256.txt`
- `evidence/experiments/manual_omniverse_2026-06-14/usd_head.txt`
- `evidence/experiments/manual_omniverse_2026-06-14/artifact_notes.txt`
- `evidence/experiments/manual_omniverse_2026-06-14/metriplane_replay.usda`
- `evidence/experiments/manual_omniverse_2026-06-14/checksums.sha256`

No screenshot captured. No raw Omniverse open log captured.

## Expected behavior

The generated USDA replay artifact should exist, be readable as OpenUSD text,
and open in Omniverse with visible replay objects and zones.

## Observed behavior

The generated USDA replay artifact exists, was copied into the evidence folder,
and has SHA256/content evidence. The repository does not contain a current
Omniverse screenshot or launcher/open log proving that the file opened in
Omniverse on 2026-06-14.

## Pass criteria

- USDA replay file exists: PASS
- USDA replay checksum captured: PASS
- USDA replay content header captured: PASS
- Omniverse opens file without error: NOT VERIFIED
- Replay objects visible in Omniverse: REPORTED MANUALLY, ARTIFACT MISSING

## Limitations

- Manual test only.
- One maintainer environment.
- No raw Omniverse open log.
- No screenshot evidence.
- No latency measurement.
- No production runtime guarantee.
- No robot-control claim.
- No safety certification.
- No collision-avoidance claim.
- No simulator physics-correctness claim.
- No full 3D reconstruction claim.
