#!/usr/bin/env python3
import argparse
import asyncio
import json
import time

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK


async def run(url: str, every: int, show_keys: bool, max_keys: int) -> None:
    n = 0
    t0 = time.time()
    print(f"[ws_drain] connecting: {url}", flush=True)

    try:
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as ws:
            while True:
                msg = await ws.recv()
                n += 1

                if every > 0 and (n % every == 0):
                    dt = time.time() - t0
                    rate = n / dt if dt > 0 else 0.0
                    line = f"[ws_drain] received={n} rate={rate:.1f}/s"

                    if show_keys:
                        try:
                            obj = json.loads(msg)
                            keys = sorted(list(obj.keys()))[:max_keys]
                            line += f" keys={keys}"
                        except Exception:
                            try:
                                line += f" bytes={len(msg)}"
                            except Exception:
                                line += " (non-json)"
                    print(line, flush=True)

    except (ConnectionClosedOK, ConnectionClosedError, ConnectionClosed) as e:
        # Clean end-of-demo shutdown should not look like a crash.
        print(f"[ws_drain] connection closed: {type(e).__name__}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="e.g. ws://127.0.0.1:8765")
    ap.add_argument("--every", type=int, default=50, help="print every N messages")
    ap.add_argument("--no-keys", action="store_true", help="don’t attempt JSON key printing")
    ap.add_argument("--max-keys", type=int, default=16)
    args = ap.parse_args()

    try:
        asyncio.run(run(args.url, args.every, (not args.no_keys), args.max_keys))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
