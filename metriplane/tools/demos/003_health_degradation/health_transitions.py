#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("health_jsonl", help="path to health.jsonl")
    ap.add_argument(
        "components",
        nargs="*",
        default=["camera.cam1", "ws.send"],
        help="components to track (default: camera.cam1 ws.send)",
    )
    args = ap.parse_args()

    p = Path(args.health_jsonl)
    last: dict[str, str | None] = {}

    def show(ts: str, msg: str) -> None:
        print(f"{ts} {msg}")

    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)

        ts = obj.get("ts") or str(obj.get("ts_ns") or "")
        overall = obj.get("overall")
        if overall is not None and overall != last.get("overall"):
            show(ts, f"overall: {last.get('overall')} -> {overall}")
            last["overall"] = overall

        comps = obj.get("components") or {}
        for name in args.components:
            ch = comps.get(name) or {}
            st = ch.get("status")
            key = f"comp:{name}"
            if st is not None and st != last.get(key):
                err = ch.get("last_error")
                extra = f" | err={err}" if err else ""
                show(ts, f"{name}: {last.get(key)} -> {st}{extra}")
                last[key] = st


if __name__ == "__main__":
    main()
