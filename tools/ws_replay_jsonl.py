# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""
Replay a Metriplane JSONL session over the Metriplane websocket server.

This is the M3 broadcaster (fake-live): JSONL -> WS -> Omniverse.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from metriplane.recording.jsonl import read_jsonl
from metriplane.streaming.ws_server import start_server, broadcast, client_count


async def replay(jsonl_path: Path, speed: float) -> None:
    frames = read_jsonl(jsonl_path)
    if not frames:
        print("[ws_replay] no frames found")
        return

    # --- NEW: wait for at least one websocket client before starting replay ---
    print("[ws_replay] waiting for ws client...")
    while client_count() == 0:
        await asyncio.sleep(0.05)
    print("[ws_replay] client connected; starting replay")
    # -------------------------------------------------------------------------

    loop = asyncio.get_running_loop()
    t0 = float(frames[0].ts)
    start = loop.time()

    print(f"[ws_replay] frames={len(frames)} speed={speed}")
    for fr in frames:
        target = (float(fr.ts) - t0) / max(speed, 1e-6)
        while (loop.time() - start) < target:
            await asyncio.sleep(0.001)

        await broadcast(fr)
        # Useful debug so you know the server is actually pushing frames:
        print(f"[ws_replay] sent frame_id={fr.frame_id} clients={client_count()}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "jsonl",
        type=Path,
        help="Path to Metriplane JSONL session",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--speed", type=float, default=1.0, help="2.0 = twice as fast")
    args = ap.parse_args()

    await start_server(host=args.host, port=args.port)
    print(f"[ws_replay] ws server: ws://{args.host}:{args.port}")

    await replay(args.jsonl, args.speed)

    print("[ws_replay] done replaying; keeping server alive (Ctrl+C to stop)")
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
