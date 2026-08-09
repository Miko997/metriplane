# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# benchmarks/run_replay_determinism.py
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HEADER_TYPES = {"header", "run_header", "provenance"}


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            record_type = None
            if isinstance(rec, dict):
                record_type = rec.get("type") or rec.get("record_type")
            if not isinstance(rec, dict):
                raise ValueError(  # noqa: TRY004 - invalid serialized data, not an API type error
                    f"Invalid JSONL record at {path}:{line_number}: expected an object"
                )
            if record_type not in HEADER_TYPES:
                yield rec


def frame_key(rec: dict[str, Any], fallback_index: int) -> tuple[str, int, int | None]:
    """Keep both the deterministic tick and recorded frame id in the identity."""
    raw_frame_id = rec.get("frame_id")
    frame_id = (
        raw_frame_id
        if isinstance(raw_frame_id, int) and not isinstance(raw_frame_id, bool)
        else None
    )
    raw_ts_sim_ns = rec.get("ts_sim_ns")
    if isinstance(raw_ts_sim_ns, int) and not isinstance(raw_ts_sim_ns, bool):
        return ("ts_sim_ns", int(rec["ts_sim_ns"]), frame_id)
    if frame_id is not None:
        return ("frame_id", int(frame_id), frame_id)
    return ("index", int(fallback_index), None)


def frame_field_summary(
    frames: list[dict[str, Any]],
    field: str,
    *,
    only_without_sim_tick: bool = False,
) -> tuple[list[int], int]:
    """Return duplicate integer values and the count of malformed supplied values."""
    seen: set[int] = set()
    duplicates: list[int] = []
    invalid_count = 0
    for frame in frames:
        if field not in frame or frame[field] is None:
            continue
        value = frame[field]
        if not isinstance(value, int) or isinstance(value, bool):
            invalid_count += 1
            continue
        tick = frame.get("ts_sim_ns")
        has_sim_tick = isinstance(tick, int) and not isinstance(tick, bool)
        if only_without_sim_tick and has_sim_tick:
            # Fixed-step replay can legitimately repeat a source frame across
            # distinct simulation ticks. In that case the tick is the identity.
            continue
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return duplicates, invalid_count


def objects_by_id(
    frame: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str], bool]:
    out: dict[str, dict[str, Any]] = {}
    objs = frame.get("objects")
    if not isinstance(objs, list):
        return out, [], True
    duplicates: list[str] = []
    invalid = False
    for o in objs:
        if not isinstance(o, dict):
            invalid = True
            continue
        raw_id = o.get("id")
        if not isinstance(raw_id, (str, int)) or isinstance(raw_id, bool) or not str(raw_id):
            invalid = True
            continue
        oid = str(raw_id)
        if oid in out:
            duplicates.append(oid)
        out[oid] = o
    return out, duplicates, invalid


def pos_xy_cm(o: dict[str, Any]) -> tuple[float, float] | None:
    p = o.get("pos_world")
    if not isinstance(p, list) or len(p) < 2:
        return None
    if isinstance(p[0], bool) or isinstance(p[1], bool):
        return None
    try:
        x = float(p[0]) * 100.0
        y = float(p[1]) * 100.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return (x, y)


def compare(a_path: Path, b_path: Path) -> dict[str, Any]:
    a_frames = list(iter_jsonl(a_path))
    b_frames = list(iter_jsonl(b_path))

    a_map: dict[tuple[str, int, int | None], dict[str, Any]] = {}
    b_map: dict[tuple[str, int, int | None], dict[str, Any]] = {}

    duplicate_frame_ids_a, invalid_frame_ids_a = frame_field_summary(
        a_frames, "frame_id", only_without_sim_tick=True
    )
    duplicate_frame_ids_b, invalid_frame_ids_b = frame_field_summary(
        b_frames, "frame_id", only_without_sim_tick=True
    )
    duplicate_ticks_a, invalid_ticks_a = frame_field_summary(a_frames, "ts_sim_ns")
    duplicate_ticks_b, invalid_ticks_b = frame_field_summary(b_frames, "ts_sim_ns")

    duplicate_a: list[tuple[str, int, int | None]] = []
    duplicate_b: list[tuple[str, int, int | None]] = []
    ordered_a: list[tuple[str, int, int | None]] = []
    ordered_b: list[tuple[str, int, int | None]] = []
    for i, fr in enumerate(a_frames):
        key = frame_key(fr, i)
        ordered_a.append(key)
        if key in a_map:
            duplicate_a.append(key)
        a_map[key] = fr
    for i, fr in enumerate(b_frames):
        key = frame_key(fr, i)
        ordered_b.append(key)
        if key in b_map:
            duplicate_b.append(key)
        b_map[key] = fr

    a_keys = set(a_map)
    b_keys = set(b_map)
    keys = [key for key in ordered_a if key in b_map]
    missing_in_a = sorted(b_keys - a_keys, key=repr)
    missing_in_b = sorted(a_keys - b_keys, key=repr)

    diffs_cm: list[float] = []
    event_mismatch_count = 0
    compared_pairs = 0
    object_id_mismatch_count = 0
    object_id_mismatches: list[str] = []
    invalid_object_count = 0
    duplicate_object_ids: list[str] = []
    invalid_position_count = 0
    invalid_positions: list[str] = []

    for k in keys:
        fa = a_map[k]
        fb = b_map[k]
        oa, duplicates_a, invalid_a = objects_by_id(fa)
        ob, duplicates_b, invalid_b = objects_by_id(fb)
        if invalid_a or invalid_b:
            invalid_object_count += 1
        if duplicates_a or duplicates_b:
            duplicate_object_ids.append(
                f"frame={k}:a={sorted(set(duplicates_a))}:b={sorted(set(duplicates_b))}"
            )

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
            if pa is None or pb is None:
                invalid_position_count += 1
                if len(invalid_positions) < 10:
                    invalid_positions.append(
                        f"frame={k}:object={oid}:valid_a={pa is not None}:valid_b={pb is not None}"
                    )
                continue
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

    result: dict[str, Any] = {
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
        and ordered_a == ordered_b
        and not duplicate_frame_ids_a
        and not duplicate_frame_ids_b
        and not duplicate_ticks_a
        and not duplicate_ticks_b
        and invalid_frame_ids_a == 0
        and invalid_frame_ids_b == 0
        and invalid_ticks_a == 0
        and invalid_ticks_b == 0
        and object_id_mismatch_count == 0
        and invalid_object_count == 0
        and not duplicate_object_ids
        and invalid_position_count == 0
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
                "duplicate_frame_keys_in_a": sorted(set(duplicate_a), key=repr)[:10],
                "duplicate_frame_keys_in_b": sorted(set(duplicate_b), key=repr)[:10],
                "duplicate_frame_ids_in_a": sorted(set(duplicate_frame_ids_a))[:10],
                "duplicate_frame_ids_in_b": sorted(set(duplicate_frame_ids_b))[:10],
                "duplicate_ticks_in_a": sorted(set(duplicate_ticks_a))[:10],
                "duplicate_ticks_in_b": sorted(set(duplicate_ticks_b))[:10],
                "invalid_frame_ids_in_a": invalid_frame_ids_a,
                "invalid_frame_ids_in_b": invalid_frame_ids_b,
                "invalid_ticks_in_a": invalid_ticks_a,
                "invalid_ticks_in_b": invalid_ticks_b,
                "frame_order_matches": ordered_a == ordered_b,
                "object_id_mismatch_count": object_id_mismatch_count,
                "object_id_mismatches": object_id_mismatches,
                "invalid_object_count": invalid_object_count,
                "duplicate_object_ids": duplicate_object_ids[:10],
                "invalid_position_count": invalid_position_count,
                "invalid_positions": invalid_positions,
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True, help="First output JSONL")
    ap.add_argument("--b", type=Path, required=True, help="Second output JSONL")
    ap.add_argument("--out", type=Path, required=True, help="CSV output path")
    ap.add_argument("--max-pos-diff-cm", type=float, default=0.0, help="Threshold for pass")
    ap.add_argument(
        "--allow-zone-mismatch", action="store_true", help="Ignore zone mismatches for pass"
    )
    args = ap.parse_args(argv)

    if not math.isfinite(args.max_pos_diff_cm) or args.max_pos_diff_cm < 0:
        print("--max-pos-diff-cm must be a finite non-negative number", file=sys.stderr)
        return 2

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
