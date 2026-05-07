from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2  # type: ignore

from metriplane.config import maybe_get_calib_paths
from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb import USBCamera
from metriplane.mapping.planar import load_planar_mapper


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview planar mapping: show world XY overlay for ArUco markers.")
    ap.add_argument("--profile", default=None, help="Profile name (defaults to calib/active_profile.yaml)")
    ap.add_argument("--calib-root", type=Path, default=Path("calib"), help="Calibration root (default: ./calib)")

    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--mapping", type=Path, default=None, help="mapping.yaml (overrides profile)")
    ap.add_argument("--intrinsics", type=Path, default=None, help="Optional camera.yaml override")
    ap.add_argument("--record", type=Path, help="Optional output .mp4")
    ap.add_argument("--fps", type=float, default=30.0)
    args = ap.parse_args()

    calib = maybe_get_calib_paths(args.profile, calib_root=args.calib_root)

    mapping_path = args.mapping or (calib.mapping if calib is not None else None)
    if mapping_path is None:
        ap.error("Need --mapping OR (--profile / calib/active_profile.yaml).")

    # Only used if mapping requires undistortion; load_planar_mapper decides.
    intr_path = args.intrinsics
    if intr_path is None and calib is not None and calib.intrinsics is not None:
        intr_path = calib.intrinsics

    if calib is not None:
        print(f"[preview] profile={calib.profile} dir={calib.profile_dir}")
    print(f"[preview] mapping={mapping_path}")
    print(f"[preview] intrinsics(candidate)={intr_path if intr_path else '(none)'}")

    mapper = load_planar_mapper(mapping_path, intr_path)
    print(f"[preview] mapping.undistort_points={mapper.mapping.undistort_points} -> runtime_uses_intrinsics={mapper.intrinsics is not None}")

    cam = USBCamera(index=args.camera)
    backend = ArUcoBackend()

    cam.open()
    writer = None
    last_print = time.time()

    try:
        while True:
            fr = cam.read()
            dets = backend.detect(fr)
            vis = fr.image.copy()

            if args.record and writer is None:
                h, w = vis.shape[:2]
                args.record.parent.mkdir(parents=True, exist_ok=True)
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(args.record), fourcc, float(args.fps), (w, h))
                print("[preview] recording ->", args.record)

            lines = []
            for (mid, cx, cy) in dets:
                xy = mapper.pixel_to_world_xy(cx, cy)

                cv2.circle(vis, (int(cx), int(cy)), 6, (0, 255, 0), -1)
                if xy is None:
                    txt = f"id={mid} (no map)"
                else:
                    x, y = xy
                    txt = f"id={mid} x={x:.3f} y={y:.3f} {mapper.mapping.units}"
                    lines.append(txt)

                cv2.putText(
                    vis,
                    txt,
                    (int(cx) + 10, int(cy) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

            cv2.putText(
                vis,
                "Preview: ESC/q=quit",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )

            cv2.imshow("metriplane_preview_world_overlay", vis)
            if writer is not None:
                writer.write(vis)

            if (time.time() - last_print) >= 1.0 and lines:
                print("[preview]", " | ".join(lines[:8]))
                last_print = time.time()

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                return 0

    finally:
        cam.close()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
