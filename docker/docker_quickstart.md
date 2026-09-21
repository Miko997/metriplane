<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Docker Quickstart (M9)

## Goal
Run Metriplane without installing Python locally.

## Prereqs
- Docker Engine + Docker Compose v2

Set separate bearer tokens before using a container profile. Compose refuses to start
when either token is absent:

```bash
export METRIPLANE_WS_AUTH_TOKEN='<locally-generated-secret>'
export METRIPLANE_METRICS_AUTH_TOKEN='<different-locally-generated-secret>'
```

Do not put production token values in Git, shell tracing, command history, logs, or this
document.

## Ports
- Metrics: http://localhost:8000/metrics
- WebSocket: ws://localhost:8765

## 1) Demo replay (no camera, uses dataset JSONL)

```bash
cd metriplane
./tools/docker_demo_up.sh
curl -fsS -H "Authorization: Bearer $METRIPLANE_METRICS_AUTH_TOKEN" \
  http://localhost:8000/metrics | head
```

WebSocket proof:

```bash
python3 - <<'PY'
import asyncio, os, websockets
async def main():
    headers = {"Authorization": f"Bearer {os.environ['METRIPLANE_WS_AUTH_TOKEN']}"}
    async with websockets.connect("ws://localhost:8765", additional_headers=headers) as ws:
        print((await ws.recv())[:250])
asyncio.run(main())
PY
```

Stop:

```bash
./tools/docker_stop.sh
```

## 2) Dummy mode (no camera, no dataset)

```bash
./tools/docker_dummy_up.sh
curl -fsS -H "Authorization: Bearer $METRIPLANE_METRICS_AUTH_TOKEN" \
  http://localhost:8000/metrics | head
./tools/docker_stop.sh
```

## 3) Live camera mode (Omniverse / real hardware)

```bash
./tools/docker_live_up.sh
curl -fsS -H "Authorization: Bearer $METRIPLANE_METRICS_AUTH_TOKEN" \
  http://localhost:8000/metrics | head
```

### IMPORTANT: Stopping live mode (so MP4 is valid)
If you record MP4 (`record_video: ...mp4`), you **must stop gracefully** so the MP4 header ("moov" atom) is written.

Use:

```bash
./tools/docker_stop.sh
```

As a fallback if you ever see an invalid MP4:

```bash
docker compose --profile live kill -s SIGINT metriplane_live
sleep 2
docker compose --profile live down --remove-orphans
```

## Hard reset
If you want to remove containers + the named volume (`vt_data`):

```bash
./tools/docker_clean.sh
```

All profiles use a read-only root filesystem, run as UID/GID `10001:10001`, drop all
capabilities, and set `no-new-privileges`. For a live camera, set
`METRIPLANE_VIDEO_GID` to the host video-device group ID if it isn't `44`. The replay
path is the automated runtime proof; physical-camera confinement remains a documented
hardware validation step rather than a claimed automated result.
