# benchmarks/run_replay_determinism.py
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict):
                yield rec


def frame_key(rec: Dict[str, Any], fallback_index: int) -> int:
    # Prefer ts_sim_ns because it is the deterministic "clock tick" identity.
    if isinstance(rec.get("ts_sim_ns"), int):
        return int(rec["ts_sim_ns"])
    if isinstance(rec.get("frame_id"), int):
        return int(rec["frame_id"])
    return fallback_index


def objects_by_id(frame: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    objs = frame.get("objects")
    if not isinstance(objs, list):
        return out
    for o in objs:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id", ""))
        if not oid:
            continue
        out[oid] = o
    return out


def pos_xy_cm(o: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    p = o.get("pos_world")
    if not isinstance(p, list) or len(p) < 2:
        return None
    try:
        x = float(p[0]) * 100.0
        y = float(p[1]) * 100.0
        return (x, y)
    except (TypeError, ValueError):
        return None


def compare(a_path: Path, b_path: Path) -> Dict[str, Any]:
    a_frames = list(iter_jsonl(a_path))
    b_frames = list(iter_jsonl(b_path))

    a_map: Dict[int, Dict[str, Any]] = {}
    b_map: Dict[int, Dict[str, Any]] = {}

    for i, fr in enumerate(a_frames):
        if isinstance(fr, dict):
            a_map[frame_key(fr, i)] = fr
    for i, fr in enumerate(b_frames):
        if isinstance(fr, dict):
            b_map[frame_key(fr, i)] = fr

    keys = sorted(set(a_map.keys()) & set(b_map.keys()))
    if not keys:
        raise SystemExit("No overlapping frames between A and B (by ts_sim_ns/frame_id).")

    diffs_cm: List[float] = []
    event_mismatch_count = 0
    compared_pairs = 0

    for k in keys:
        fa = a_map[k]
        fb = b_map[k]
        oa = objects_by_id(fa)
        ob = objects_by_id(fb)

        all_ids = sorted(set(oa.keys()) & set(ob.keys()))
        for oid in all_ids:
            pa = pos_xy_cm(oa[oid])
            pb = pos_xy_cm(ob[oid])
            if pa is not None and pb is not None:
                dx = pa[0] - pb[0]
                dy = pa[1] - pb[1]
                diffs_cm.append(math.sqrt(dx * dx + dy * dy))
                compared_pairs += 1

            # "event_mismatch_count" proxy:
            # count per-frame mismatches in zone membership (if present).
            za = oa[oid].get("zone")
            zb = ob[oid].get("zone")
            if za != zb:
                event_mismatch_count += 1

    mean_pos_diff_cm = (sum(diffs_cm) / len(diffs_cm)) if diffs_cm else 0.0
    max_pos_diff_cm = max(diffs_cm) if diffs_cm else 0.0

    return {
        "frames_compared": len(keys),
        "object_pairs_compared": compared_pairs,
        "mean_pos_diff_cm": mean_pos_diff_cm,
        "max_pos_diff_cm": max_pos_diff_cm,
        "event_mismatch_count": event_mismatch_count,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True, help="First output JSONL")
    ap.add_argument("--b", type=Path, required=True, help="Second output JSONL")
    ap.add_argument("--out", type=Path, required=True, help="CSV output path")
    ap.add_argument("--max-pos-diff-cm", type=float, default=0.0, help="Threshold for pass")
    ap.add_argument("--allow-zone-mismatch", action="store_true", help="Ignore zone mismatches for pass")
    args = ap.parse_args()

    res = compare(args.a, args.b)

    pass_ok = True
    if res["max_pos_diff_cm"] > args.max_pos_diff_cm:
        pass_ok = False
    if (not args.allow_zone_mismatch) and res["event_mismatch_count"] != 0:
        pass_ok = False

    out_row = dict(res)
    out_row["pass"] = str(pass_ok).lower()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_row.keys()))
        w.writeheader()
        w.writerow(out_row)

    print(f"[determinism] wrote: {args.out}")
    print(out_row)


if __name__ == "__main__":
    main()
