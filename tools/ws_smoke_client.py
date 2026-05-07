import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List

import websockets


def validate_frame(obj: Dict[str, Any]) -> None:
    # Minimal contract checks (kept intentionally strict on the top-level shape)
    required = ["ts", "frame_id", "objects", "events", "metrics"]
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(f"missing keys: {missing}")

    if not isinstance(obj["frame_id"], int):
        raise ValueError("frame_id is not int")

    if not isinstance(obj["objects"], list):
        raise ValueError("objects is not list")

    if not isinstance(obj["events"], list):
        raise ValueError("events is not list")

    # Optional-but-expected (based on docs/schema.md)
    if "schema_version" in obj and obj["schema_version"] != "1.0":
        raise ValueError(f"schema_version != 1.0 (got {obj['schema_version']})")

    # Object shape sanity
    for i, o in enumerate(obj["objects"][:10]):
        if not isinstance(o, dict):
            raise ValueError(f"objects[{i}] is not dict")
        if "id" not in o:
            raise ValueError(f"objects[{i}] missing 'id'")


async def main_async(url: str, n: int, timeout_s: float) -> int:
    got: List[Dict[str, Any]] = []
    async with websockets.connect(url, open_timeout=timeout_s) as ws:
        for _ in range(n):
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            obj = json.loads(raw)
            validate_frame(obj)
            got.append(obj)

    first = got[0]
    print(f"[ws_smoke] OK messages={len(got)} first_frame_id={first.get('frame_id')} keys={sorted(list(first.keys()))}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--n", type=int, default=3, help="how many messages to read")
    ap.add_argument("--timeout", type=float, default=3.0)
    args = ap.parse_args()

    try:
        rc = asyncio.run(main_async(args.url, args.n, args.timeout))
    except Exception as e:
        print(f"[ws_smoke] FAIL: {e}", file=sys.stderr)
        raise SystemExit(2)

    raise SystemExit(rc)


if __name__ == "__main__":
    main()
