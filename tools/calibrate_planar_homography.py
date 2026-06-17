# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np  # type: ignore
import yaml

from metriplane.config import maybe_get_calib_paths
from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb import USBCamera
from metriplane.calibration.camera import load_intrinsics
from metriplane.mapping.planar import save_homography
from metriplane.models import Frame


def load_anchors(path: Path) -> list[tuple[int, float, float]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    anchors = data.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 4:
        raise ValueError("anchors.yaml must contain at least 4 anchors")

    out: list[tuple[int, float, float]] = []
    for a in anchors:
        if not isinstance(a, dict):
            continue
        mid = int(a["id"])
        xy = a["world_xy"]
        out.append((mid, float(xy[0]), float(xy[1])))
    if len(out) < 4:
        raise ValueError("anchors.yaml must contain at least 4 valid anchors")
    return out


def compute_rmse(dst: np.ndarray, pred: np.ndarray) -> float:
    dif = dst - pred
    err = np.sqrt((dif[:, 0] ** 2) + (dif[:, 1] ** 2))
    return float(np.sqrt(np.mean(err ** 2)))


def main() -> int:
    ap = argparse.ArgumentParser(description="M5: Planar homography calibration (pixel -> world XY).")

    ap.add_argument("--profile", default=None, help="Profile name (defaults to calib/active_profile.yaml)")
    ap.add_argument("--calib-root", type=Path, default=Path("calib"), help="Calibration root (default: ./calib)")
    ap.add_argument("--no-undistort", action="store_true", help="force raw pixel points (ignore intrinsics even if profile has camera.yaml)")

    ap.add_argument("--no-intrinsics", action="store_true", help="Force DISABLE intrinsics even if profile has camera.yaml")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--anchors", type=Path, default=None, help="anchors.yaml (overrides profile)")
    ap.add_argument("--out", type=Path, default=None, help="output mapping.yaml (overrides profile)")
    ap.add_argument("--units", default="meters")
    ap.add_argument("--intrinsics", type=Path, default=None, help="Optional: camera.yaml to undistort anchor points (overrides profile camera.yaml)")
    ap.add_argument("--no-preview", action="store_true", help="do not open OpenCV preview window")
    ap.add_argument("--max-frames", type=int, default=600, help="Max frames to capture in headless mode (default: 600)")
    ap.add_argument("--timeout-s", type=int, default=30, help="Timeout in seconds for headless mode (default: 30)")
    args = ap.parse_args()

    calib = maybe_get_calib_paths(args.profile, calib_root=args.calib_root)

    anchors_path = args.anchors or (calib.anchors if calib is not None else None)
    out_path = args.out or (calib.mapping if calib is not None else None)

    if anchors_path is None or out_path is None:
        ap.error("You must provide either (--profile or calib/active_profile.yaml) OR both --anchors and --out.")

    # Intrinsics: explicit flag wins; otherwise profile camera.yaml if present; otherwise None.
    intrinsics_path = None if args.no_undistort else args.intrinsics
    if args.no_intrinsics:
        intrinsics_path = None
    elif (intrinsics_path is None) and (not args.no_undistort) and (calib is not None) and (calib.intrinsics is not None):
        intrinsics_path = calib.intrinsics

    if calib is not None:
        print(f"[calib_plane] profile={calib.profile} dir={calib.profile_dir}")
        print(f"[calib_plane] anchors={anchors_path}")
        print(f"[calib_plane] out(mapping)={out_path}")

    anchors = load_anchors(anchors_path)
    anchor_ids = [a[0] for a in anchors]
    print("[calib_plane] anchors:", anchors)
    print("[calib_plane] show these marker IDs in view at the same time:", anchor_ids)

    intr = load_intrinsics(intrinsics_path) if intrinsics_path else None
    if intr is not None:
        print("[calib_plane] intrinsics: ENABLED (undistort points) ->", intrinsics_path)
    else:
        print("[calib_plane] intrinsics: DISABLED (raw pixels)")

    cam = USBCamera(index=args.camera)
    backend = ArUcoBackend()

    cam.open()
    
    # Headless mode tracking
    frame_count = 0
    start_time = time.time()
    frames_with_markers = 0
    frames_with_anchors = 0
    all_detected_ids: set[int] = set()
    
    if args.no_preview:
        print(f"[calib_plane] Headless mode: max_frames={args.max_frames}, timeout={args.timeout_s}s")
        print(f"[calib_plane] Waiting for anchors {anchor_ids}...")
    
    try:
        while True:
            fr = cam.read()
            frame_count += 1
            elapsed = time.time() - start_time
            
            # Timeout/max-frames checks for headless mode
            if args.no_preview:
                if elapsed > args.timeout_s:
                    print(f"\n[calib_plane] ERROR: Timeout after {elapsed:.1f}s")
                    print(f"[calib_plane] Frames captured: {frame_count}")
                    print(f"[calib_plane] Frames with markers: {frames_with_markers}")
                    print(f"[calib_plane] Frames with required anchors: {frames_with_anchors}")
                    print(f"[calib_plane] All detected IDs: {sorted(all_detected_ids)}")
                    print(f"[calib_plane] Required anchor IDs: {anchor_ids}")
                    return 1
                
                if frame_count > args.max_frames:
                    print(f"\n[calib_plane] ERROR: Max frames ({args.max_frames}) reached")
                    print(f"[calib_plane] Frames with markers: {frames_with_markers}")
                    print(f"[calib_plane] Frames with required anchors: {frames_with_anchors}")
                    print(f"[calib_plane] All detected IDs: {sorted(all_detected_ids)}")
                    print(f"[calib_plane] Required anchor IDs: {anchor_ids}")
                    return 1
            
            dets = backend.detect(Frame(ts_cam_read=fr.ts_cam_read, image=fr.image))
            det_map: dict[int, tuple[float, float]] = {int(d[0]): (float(d[1]), float(d[2])) for d in dets}
            
            if det_map:
                frames_with_markers += 1
                all_detected_ids.update(det_map.keys())

            src_pts: list[list[float]] = []
            dst_pts: list[list[float]] = []

            for mid, wx, wy in anchors:
                if mid not in det_map:
                    continue
                cx, cy = det_map[mid]
                if intr is not None:
                    (cx, cy) = intr.undistort_points_px([(cx, cy)])[0]
                src_pts.append([cx, cy])
                dst_pts.append([wx, wy])
            
            if len(src_pts) >= 4:
                frames_with_anchors += 1
            
            # Progress printing for headless mode (every 30 frames)
            if args.no_preview and frame_count % 30 == 0:
                detected_ids = sorted(det_map.keys())
                print(f"[calib_plane] frame={frame_count} elapsed={elapsed:.1f}s detected_ids={detected_ids} anchors_seen={len(src_pts)}/{len(anchors)}")

            if not args.no_preview:
                vis = fr.image.copy()
                for mid, (cx, cy) in det_map.items():
                    cv2.circle(vis, (int(cx), int(cy)), 6, (0, 255, 0), -1)
                    cv2.putText(
                        vis,
                        str(mid),
                        (int(cx) + 8, int(cy) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )
                cv2.putText(
                    vis,
                    f"anchors_seen={len(src_pts)}/{len(anchors)}  (press 'w' to write when >=4 seen, 'q' to quit)",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )
                cv2.imshow("calibrate_planar_homography", vis)

            key = cv2.waitKey(1) & 0xFF if not args.no_preview else 255
            if key == ord("q"):
                print("[calib_plane] quit")
                return 1

            if len(src_pts) < 4:
                continue

            # In headless mode, auto-write when all anchors seen
            # In GUI mode, wait for 'w' keypress
            if args.no_preview:
                # Auto-write in headless mode
                print(f"\n[calib_plane] All {len(src_pts)} anchors detected! Auto-writing calibration...")
            elif key != ord("w"):
                # GUI mode: wait for 'w' keypress
                continue

            src = np.array(src_pts, dtype=np.float64)
            dst = np.array(dst_pts, dtype=np.float64)

            method = 0 if src.shape[0] == 4 else cv2.RANSAC
            H, _ = cv2.findHomography(src, dst, method=method)
            if H is None:
                print("[calib_plane] ERROR: cv2.findHomography returned None")
                continue

            src_h = np.concatenate([src, np.ones((src.shape[0], 1), dtype=np.float64)], axis=1)
            pred_h = (H @ src_h.T).T
            pred = pred_h[:, :2] / pred_h[:, 2:3]
            rmse = compute_rmse(dst, pred)

            save_homography(
                out_path,
                H=H.tolist(),
                units=str(args.units),
                extra={
                    "type": "homography_v1",
                    "computed_at_unix": time.time(),
                    "anchors_file": str(anchors_path),
                    "anchors_used": [int(a[0]) for a in anchors],
                    "anchors_seen": int(src.shape[0]),
                    "anchor_rmse": rmse,
                    "intrinsics_file": str(intrinsics_path) if intrinsics_path else None,
                    "undistort_points": bool(intr is not None),
                    "profile": calib.profile if calib is not None else None,
                },
            )
            print(f"[calib_plane] wrote {out_path}  rmse={rmse:.6f} {args.units}")
            return 0

    finally:
        cam.close()
        if not args.no_preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
