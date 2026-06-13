#!/usr/bin/env python3
"""Parquet exporter: convert run-dir JSONL artifacts into Parquet for batch analytics.

Requires an optional engine (pyarrow or fastparquet via pandas). If neither is available,
prints an install instruction and exits nonzero — it never crashes the runtime path.

Usage:
    python -m metriplane.exporters.parquet --run-dir runs/<run_id>
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

log = logging.getLogger("metriplane.exporters")

# (source filename in run dir, output parquet name)
_SOURCES = [
    ("session_excerpt.jsonl", "frames.parquet"),
    ("session.jsonl", "frames.parquet"),
    ("alerts.jsonl", "alerts.parquet"),
    ("events.jsonl", "alerts.parquet"),
]


def parquet_available() -> tuple[bool, str]:
    try:
        import pyarrow  # noqa: F401
        return True, "pyarrow"
    except Exception:
        pass
    try:
        import fastparquet  # noqa: F401
        return True, "fastparquet"
    except Exception:
        pass
    return False, ""


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def export_run_dir(run_dir: str | Path, out_dir: str | Path | None = None) -> dict:
    ok, engine = parquet_available()
    if not ok:
        raise RuntimeError(
            "Parquet export needs an engine. Install one of:\n"
            "  pip install pyarrow\n  pip install fastparquet")
    import pandas as pd

    run = Path(run_dir)
    out = Path(out_dir) if out_dir else run / "exports" / "parquet"
    out.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    for src_name, out_name in _SOURCES:
        src = run / src_name
        if not src.exists():
            continue
        rows = _read_jsonl(src)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df.to_parquet(out / out_name, engine=engine, index=False)
        written[out_name] = len(rows)

    # incidents.json (array)
    inc = run / "incident.json"
    if inc.exists():
        try:
            data = json.loads(inc.read_text())
            if isinstance(data, list) and data:
                pd.DataFrame(data).to_parquet(out / "incidents.parquet",
                                              engine=engine, index=False)
                written["incidents.parquet"] = len(data)
        except Exception:
            pass
    return {"engine": engine, "out_dir": str(out), "written": written}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("metriplane.exporters.parquet")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out-dir", default=None)
    args = p.parse_args(argv)
    try:
        result = export_run_dir(args.run_dir, args.out_dir)
    except RuntimeError as e:
        print(str(e))
        return 1
    print(f"engine={result['engine']} out={result['out_dir']}")
    for name, n in result["written"].items():
        print(f"  {name}: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
