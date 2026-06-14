<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Docker Quickstart (M9)

## Goal
Run Metriplane without installing Python locally.

## Prereqs
- Docker Engine + Docker Compose v2

## Ports
- Metrics: http://localhost:8000/metrics
- WebSocket: ws://localhost:8765

## 1) Demo replay (no camera, uses dataset JSONL)

```bash
cd metriplane/metriplane-core
./tools/docker_demo_up.sh
curl -fsS http://localhost:8000/metrics | head
```

WebSocket proof:

```bash
python3 - <<'PY'
import asyncio, websockets
async def main():
    async with websockets.connect("ws://localhost:8765") as ws:
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
curl -fsS http://localhost:8000/metrics | head
./tools/docker_stop.sh
```

## 3) Live camera mode (Omniverse / real hardware)

```bash
./tools/docker_live_up.sh
curl -fsS http://localhost:8000/metrics | head
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
