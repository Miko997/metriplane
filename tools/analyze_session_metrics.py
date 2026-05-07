from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median


def _get_ts(obj: dict) -> float | None:
    for k in ("ts", "t", "timestamp", "time", "ts_s", "unix_ts"):
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _iter_objects(obj: dict):
    """
    Best-effort extraction of (id, x, y) from unknown JSONL schemas.
    Looks for common keys: fused/objects/tracks, list or dict.
    """
    candidates = []
    for k in ("fused", "objects", "tracks", "markers", "detections"):
        v = obj.get(k)
        if v is not None:
            candidates.append(v)

    for v in candidates:
        # list of dicts
        if isinstance(v, list):
            for it in v:
                if not isinstance(it, dict):
                    continue
                oid = it.get("id", it.get("marker_id", it.get("tag_id", it.get("aruco_id"))))
                x = it.get("x", it.get("pos_x", it.get("world_x")))
                y = it.get("y", it.get("pos_y", it.get("world_y")))
                if isinstance(oid, (int, str)) and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    yield str(oid), float(x), float(y)

        # dict mapping id -> dict(x,y)
        if isinstance(v, dict):
            for k2, it in v.items():
                if isinstance(it, dict):
                    x = it.get("x", it.get("pos_x", it.get("world_x")))
                    y = it.get("y", it.get("pos_y", it.get("world_y")))
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        yield str(k2), float(x), float(y)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--anchors", type=str, default="", help="comma-separated anchor ids to ignore (e.g. 0,1,2,3)")
    args = ap.parse_args()

    anchors = set([s.strip() for s in args.anchors.split(",") if s.strip()])

    rows: list[tuple[float, dict[str, tuple[float, float]]]] = []
    per_id: dict[str, list[tuple[float, float]]] = defaultdict(list)

    with args.inp.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            ts = _get_ts(obj)
            if ts is None:
                # if no timestamp, just use row index as time
                ts = float(len(rows))

            frame_objs: dict[str, tuple[float, float]] = {}
            for oid, x, y in _iter_objects(obj):
                if oid in anchors:
                    continue
                frame_objs[oid] = (x, y)
                per_id[oid].append((x, y))

            rows.append((ts, frame_objs))

    if not rows:
        args.summary.write_text("ERROR: no rows parsed from session\n", encoding="utf-8")
        return 2

    # timing / fps
    ts_list = [t for t, _ in rows]
    ts_sorted = sorted(ts_list)
    dts = [ts_sorted[i + 1] - ts_sorted[i] for i in range(len(ts_sorted) - 1) if (ts_sorted[i + 1] - ts_sorted[i]) > 0]
    fps_est = (1.0 / median(dts)) if dts else 0.0

    # expected object count = max seen
    max_objs = max(len(o) for _, o in rows) if rows else 0
    max_objs = max(max_objs, 1)

    # per-id medians for jitter reference
    med: dict[str, tuple[float, float]] = {}
    for oid, pts in per_id.items():
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        med[oid] = (median(xs), median(ys))

    # write timeseries CSV: ts, n_objects, coverage, mean_jitter_m
    out_lines = ["ts,n_objects,coverage,mean_jitter_m\n"]
    jitter_samples = []
    covered = 0

    for ts, objs in rows:
        n = len(objs)
        cov = n / float(max_objs)
        if n > 0:
            covered += 1
        ds = []
        for oid, (x, y) in objs.items():
            mx, my = med.get(oid, (x, y))
            ds.append(math.hypot(x - mx, y - my))
        mean_j = (sum(ds) / len(ds)) if ds else 0.0
        jitter_samples.append(mean_j)
        out_lines.append(f"{ts:.6f},{n},{cov:.3f},{mean_j:.6f}\n")

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.csv.write_text("".join(out_lines), encoding="utf-8")

    coverage_frac = covered / float(len(rows))
    jitter_med = median(jitter_samples) if jitter_samples else 0.0

    summary = []
    summary.append(f"session={args.inp}\n")
    summary.append(f"frames={len(rows)}\n")
    summary.append(f"fps_est={fps_est:.2f}\n")
    summary.append(f"coverage_frac={coverage_frac:.3f}\n")
    summary.append(f"jitter_median_m={jitter_med:.6f}\n")
    summary.append(f"anchors_ignored={sorted(list(anchors))}\n")

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text("".join(summary), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
