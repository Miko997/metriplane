#!/usr/bin/env python3
"""
Analyze ID continuity / tracking stability from a Metriplane session JSONL.

Computes per-object continuity metrics from the fused objects list.
NOTE: This tool reports *ID continuity* (was the same ID present across frames?).
It does NOT claim true ID-switch rate because that requires ground truth labeling.

Usage:
    python tools/analyze_id_stability_jsonl.py <session.jsonl> --out <output.csv>
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def analyze(session_jsonl: str, out_csv: str) -> None:
    session = Path(session_jsonl)
    if not session.exists():
        print(f"[id_stability] ERROR: session not found: {session_jsonl}", file=sys.stderr)
        sys.exit(1)

    # Per-object tracking: frame index → whether object was seen
    obj_seen: dict[str, list[bool]] = {}   # id → per-frame presence
    frame_idx = 0
    first_ts = None
    last_ts = None

    with open(session) as f:
        for line in f:
            d = json.loads(line.strip())
            if not d or d.get("type") == "run_header":
                continue

            ts = d.get("ts")
            if ts is not None:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

            # Use fused list if available, fall back to objects
            obj_list = d.get("fused") or d.get("objects") or []
            seen_ids = {str(obj["id"]) for obj in obj_list}

            # Register any new IDs we haven't seen before
            for oid in seen_ids:
                if oid not in obj_seen:
                    # Pad with False for all previous frames
                    obj_seen[oid] = [False] * frame_idx

            # Mark presence for all known IDs in this frame
            for oid in obj_seen:
                obj_seen[oid].append(oid in seen_ids)

            frame_idx += 1

    total_frames = frame_idx
    duration_s = (last_ts - first_ts) if (first_ts and last_ts) else 0.0

    print(f"[id_stability] total_frames={total_frames}, duration={duration_s:.2f}s, unique_ids={len(obj_seen)}")

    rows = []
    for oid, presence in sorted(obj_seen.items()):
        frames_seen = sum(presence)
        coverage_pct = 100.0 * frames_seen / total_frames if total_frames > 0 else 0.0
        full_session = all(presence)

        # Count gaps (sequences of False)
        gaps = []
        in_gap = False
        gap_len = 0
        for p in presence:
            if not p:
                in_gap = True
                gap_len += 1
            else:
                if in_gap:
                    gaps.append(gap_len)
                    in_gap = False
                    gap_len = 0
        if in_gap:
            gaps.append(gap_len)

        n_gaps = len(gaps)
        max_gap = max(gaps) if gaps else 0
        mean_gap = sum(gaps) / len(gaps) if gaps else 0.0

        rows.append({
            "object_id": oid,
            "total_frames": total_frames,
            "frames_seen": frames_seen,
            "coverage_pct": round(coverage_pct, 2),
            "continuous_full_session": full_session,
            "n_missing_gaps": n_gaps,
            "max_missing_gap_frames": max_gap,
            "mean_missing_gap_frames": round(mean_gap, 2),
            "session_duration_s": round(duration_s, 3),
        })

        print(
            f"  id={oid}: seen={frames_seen}/{total_frames} "
            f"({coverage_pct:.1f}%) gaps={n_gaps} max_gap={max_gap} "
            f"continuous={full_session}"
        )

    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "object_id", "total_frames", "frames_seen", "coverage_pct",
        "continuous_full_session", "n_missing_gaps", "max_missing_gap_frames",
        "mean_missing_gap_frames", "session_duration_s",
    ]
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[id_stability] wrote -> {out_csv}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze ID continuity from Metriplane session JSONL. "
                    "Reports presence/absence per object, not true ID switch rate."
    )
    parser.add_argument("session_jsonl", help="Input session.jsonl file")
    parser.add_argument("--out", required=True, help="Output CSV path")
    args = parser.parse_args()
    analyze(args.session_jsonl, args.out)


if __name__ == "__main__":
    main()
