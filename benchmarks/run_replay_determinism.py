# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# benchmarks/run_replay_determinism.py
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


HEADER_TYPES = {"header", "run_header", "provenance"}


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            record_type = None
            if isinstance(rec, dict):
                record_type = rec.get("type") or rec.get("record_type")
            if isinstance(rec, dict) and record_type not in HEADER_TYPES:
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

    duplicate_a: list[int] = []
    duplicate_b: list[int] = []
    for i, fr in enumerate(a_frames):
        key = frame_key(fr, i)
        if key in a_map:
            duplicate_a.append(key)
        a_map[key] = fr
    for i, fr in enumerate(b_frames):
        key = frame_key(fr, i)
        if key in b_map:
            duplicate_b.append(key)
        b_map[key] = fr

    a_keys = set(a_map)
    b_keys = set(b_map)
    keys = sorted(a_keys & b_keys)
    missing_in_a = sorted(b_keys - a_keys)
    missing_in_b = sorted(a_keys - b_keys)

    diffs_cm: List[float] = []
    event_mismatch_count = 0
    compared_pairs = 0
    object_id_mismatch_count = 0
    object_id_mismatches: list[str] = []

    for k in keys:
        fa = a_map[k]
        fb = b_map[k]
        oa = objects_by_id(fa)
        ob = objects_by_id(fb)

        ids_a = set(oa)
        ids_b = set(ob)
        missing_objects_in_a = sorted(ids_b - ids_a)
        missing_objects_in_b = sorted(ids_a - ids_b)
        if missing_objects_in_a or missing_objects_in_b:
            object_id_mismatch_count += 1
            if len(object_id_mismatches) < 10:
                object_id_mismatches.append(
                    f"frame={k}:missing_in_a={missing_objects_in_a}:missing_in_b={missing_objects_in_b}"
                )

        all_ids = sorted(ids_a & ids_b)
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

    result: Dict[str, Any] = {
        "frames_compared": len(keys),
        "object_pairs_compared": compared_pairs,
        "mean_pos_diff_cm": mean_pos_diff_cm,
        "max_pos_diff_cm": max_pos_diff_cm,
        "event_mismatch_count": event_mismatch_count,
    }

    structure_ok = (
        bool(a_frames)
        and bool(b_frames)
        and len(a_frames) == len(b_frames)
        and not duplicate_a
        and not duplicate_b
        and not missing_in_a
        and not missing_in_b
        and object_id_mismatch_count == 0
    )
    if not structure_ok:
        # Preserve the historical six-column CSV for successful canonical runs;
        # append diagnostics only when a comparison is structurally invalid.
        result.update(
            {
                "comparison_valid": False,
                "frames_a": len(a_frames),
                "frames_b": len(b_frames),
                "missing_frame_count_in_a": len(missing_in_a),
                "missing_frame_count_in_b": len(missing_in_b),
                "missing_frame_keys_in_a": missing_in_a[:10],
                "missing_frame_keys_in_b": missing_in_b[:10],
                "duplicate_frame_keys_in_a": sorted(set(duplicate_a))[:10],
                "duplicate_frame_keys_in_b": sorted(set(duplicate_b))[:10],
                "object_id_mismatch_count": object_id_mismatch_count,
                "object_id_mismatches": object_id_mismatches,
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True, help="First output JSONL")
    ap.add_argument("--b", type=Path, required=True, help="Second output JSONL")
    ap.add_argument("--out", type=Path, required=True, help="CSV output path")
    ap.add_argument("--max-pos-diff-cm", type=float, default=0.0, help="Threshold for pass")
    ap.add_argument("--allow-zone-mismatch", action="store_true", help="Ignore zone mismatches for pass")
    args = ap.parse_args(argv)

    res = compare(args.a, args.b)

    pass_ok = bool(res.get("comparison_valid", True))
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
    if not pass_ok:
        print("[determinism] comparison failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
