#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import json
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: session_health_summary.py <run_dir/session.jsonl>")
        return 2

    path = sys.argv[1]

    cams = ["cam0", "cam1"]
    cam_stats = {
        cid: {
            "present": 0,
            "missing": 0,
            "age_max": 0.0,
            "dets0": 0,
            "stale": 0,
            "first_missing_at": None,
        }
        for cid in cams
    }

    t0 = None
    t_last = None
    frames = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)

            # Skip header line(s)
            if r.get("type") == "run_header":
                continue

            ts = r.get("ts")
            if ts is None:
                # If for some reason ts is absent, skip (or you could fall back to something else)
                continue

            if t0 is None:
                t0 = ts
            t_last = ts
            frames += 1

            per_cam = {c.get("camera_id"): c for c in (r.get("raw_per_camera") or [])}

            for cid in cams:
                if cid not in per_cam:
                    cam_stats[cid]["missing"] += 1
                    if cam_stats[cid]["first_missing_at"] is None and t0 is not None:
                        cam_stats[cid]["first_missing_at"] = ts - t0
                    continue

                cam_stats[cid]["present"] += 1
                metrics = per_cam[cid].get("metrics") or {}

                age_s = float(metrics.get("age_s") or 0.0)
                if age_s > cam_stats[cid]["age_max"]:
                    cam_stats[cid]["age_max"] = age_s

                dets = int(metrics.get("dets") or 0)
                if dets == 0:
                    cam_stats[cid]["dets0"] += 1

                if bool(metrics.get("stale_for_fusion")):
                    cam_stats[cid]["stale"] += 1

    if t0 is None or t_last is None:
        print("No frames found (no non-header records with ts).")
        return 1

    duration_s = (t_last - t0) if (t_last is not None and t0 is not None) else 0.0
    print(f"frames={frames} duration_s={duration_s:.2f}")

    for cid in cams:
        present = cam_stats[cid]["present"]
        missing = cam_stats[cid]["missing"]

        missing_pct = (missing / frames * 100.0) if frames else 0.0
        dets0_pct = (cam_stats[cid]["dets0"] / present * 100.0) if present else 0.0
        stale_pct = (cam_stats[cid]["stale"] / present * 100.0) if present else 0.0

        print(
            f"{cid}: present_frames={present} missing_frames={missing} missing_pct={missing_pct:.1f}%"
        )
        print(
            f"{cid}: age_s_max={cam_stats[cid]['age_max']:.3f} "
            f"dets0_frames={cam_stats[cid]['dets0']} dets0_pct={dets0_pct:.1f}% "
            f"stale_for_fusion_frames={cam_stats[cid]['stale']} stale_for_fusion_pct={stale_pct:.1f}%"
        )

        if cam_stats[cid]["first_missing_at"] is not None:
            print(f"{cid}: first_missing_at_s={cam_stats[cid]['first_missing_at']:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
