# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import csv
import math
import time
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import yaml

from metriplane.config import maybe_get_calib_paths
from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb import USBCamera
from metriplane.mapping.planar import load_planar_mapper
from metriplane.models import Frame


def load_test_points(path: Path) -> tuple[int, list[tuple[str, float, float]]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    test_marker_id = int(data.get("test_marker_id", 0))
    pts_raw = data.get("points")
    if not isinstance(pts_raw, list) or not pts_raw:
        raise ValueError("test_points.yaml must have a non-empty 'points' list")

    pts: list[tuple[str, float, float]] = []
    for p in pts_raw:
        name = str(p["name"])
        xy = p["world_xy"]
        pts.append((name, float(xy[0]), float(xy[1])))
    return test_marker_id, pts


def main() -> int:
    ap = argparse.ArgumentParser(description="M5: mapping error benchmark (live, interactive).")

    ap.add_argument(
        "--profile", default=None, help="Profile name (defaults to calib/active_profile.yaml)"
    )
    ap.add_argument(
        "--calib-root", type=Path, default=Path("calib"), help="Calibration root (default: ./calib)"
    )

    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--mapping", type=Path, default=None, help="mapping.yaml (overrides profile)")
    ap.add_argument(
        "--intrinsics",
        type=Path,
        default=None,
        help="Optional camera.yaml (overrides profile camera.yaml)",
    )
    ap.add_argument(
        "--test-points", type=Path, default=None, help="test_points.yaml (overrides profile)"
    )
    ap.add_argument("--out", type=Path, default=Path("benchmarks/out/mapping_error_001.csv"))
    args = ap.parse_args()

    calib = maybe_get_calib_paths(args.profile, calib_root=args.calib_root)

    mapping_path = args.mapping or (calib.mapping if calib is not None else None)
    test_points_path = args.test_points or (calib.test_points if calib is not None else None)
    if mapping_path is None:
        ap.error("Need --mapping OR (--profile / calib/active_profile.yaml).")
    if test_points_path is None:
        ap.error("Need --test-points OR (--profile / calib/active_profile.yaml).")

    intr_path = args.intrinsics
    if intr_path is None and calib is not None and calib.intrinsics is not None:
        intr_path = calib.intrinsics

    mapper = load_planar_mapper(mapping_path, intr_path)
    test_marker_id, points = load_test_points(test_points_path)

    print("[mapping_error] mapping units:", mapper.mapping.units)
    print("[mapping_error] mapping:", mapping_path)
    print("[mapping_error] intrinsics:", str(intr_path) if intr_path else "(none)")
    print("[mapping_error] test_points:", test_points_path)
    print("[mapping_error] test_marker_id:", test_marker_id)
    print("[mapping_error] points:", len(points))
    print("[mapping_error] Controls: SPACE=capture  q=quit")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    cam = USBCamera(index=args.camera)
    backend = ArUcoBackend()
    cam.open()

    rows: list[dict[str, Any]] = []
    try:
        for name, gx, gy in points:
            print(f"\n[mapping_error] Point '{name}' GT=({gx:.3f},{gy:.3f}) m")
            print("[mapping_error] Place marker and press SPACE...")

            while True:
                fr = cam.read()
                dets = backend.detect(Frame(ts_cam_read=fr.ts_cam_read, image=fr.image))
                det_map = {int(d[0]): (float(d[1]), float(d[2])) for d in dets}

                vis = fr.image.copy()
                if test_marker_id in det_map:
                    cx, cy = det_map[test_marker_id]
                    cv2.circle(vis, (int(cx), int(cy)), 8, (0, 255, 0), -1)
                    cv2.putText(
                        vis,
                        f"id={test_marker_id}",
                        (int(cx) + 10, int(cy)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 255, 0),
                        2,
                    )
                cv2.putText(
                    vis,
                    f"point={name} GT=({gx:.2f},{gy:.2f})m",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 255),
                    2,
                )

                cv2.imshow("run_mapping_error", vis)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("[mapping_error] quit")
                    return 1
                if key != ord(" "):
                    continue

                if test_marker_id not in det_map:
                    print("[mapping_error] Marker not visible on capture; try again.")
                    continue

                cx, cy = det_map[test_marker_id]
                xy = mapper.pixel_to_world_xy(cx, cy)
                if xy is None:
                    print("[mapping_error] mapping produced invalid result; try again.")
                    continue

                mx, my = xy
                err = math.sqrt((mx - gx) ** 2 + (my - gy) ** 2)

                row = {
                    "ts_unix": time.time(),
                    "point": name,
                    "gt_x_m": gx,
                    "gt_y_m": gy,
                    "meas_x_m": mx,
                    "meas_y_m": my,
                    "err_m": err,
                    "err_cm": err * 100.0,
                    "marker_id": test_marker_id,
                    "px_u": cx,
                    "px_v": cy,
                }
                rows.append(row)
                print(f"[mapping_error] measured=({mx:.3f},{my:.3f}) err={err * 100:.2f} cm")
                break

    finally:
        cam.close()
        cv2.destroyAllWindows()

    fieldnames = (
        list(rows[0].keys())
        if rows
        else [
            "ts_unix",
            "point",
            "gt_x_m",
            "gt_y_m",
            "meas_x_m",
            "meas_y_m",
            "err_m",
            "err_cm",
            "marker_id",
            "px_u",
            "px_v",
        ]
    )
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    errs = [float(r["err_cm"]) for r in rows]
    if errs:
        mean = sum(errs) / len(errs)
        mx = max(errs)
        print(f"\n[mapping_error] wrote {args.out}")
        print(f"[mapping_error] mean_err_cm={mean:.2f} max_err_cm={mx:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
