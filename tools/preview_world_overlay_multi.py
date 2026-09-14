# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from pathlib import Path

import cv2  # type: ignore
from metriplane.camera.v4l_resolve import resolve_v4l_to_index

from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb_multi import USBMultiCamera
from metriplane.mapping.planar_multi import load_multi_planar_mapper


def _parse_bounds(s: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bounds must be xmin,xmax,ymin,ymax")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def _world_to_px(x: float, y: float, *, xmin: float, ymax: float, scale: float) -> tuple[int, int]:
    px = int((x - xmin) * scale)
    py = int((ymax - y) * scale)
    return (px, py)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Preview: 2 cameras mapped into same world XY + topdown."
    )
    ap.add_argument("--cam0", type=str, default="0")
    ap.add_argument("--cam1", type=str, default="2")

    ap.add_argument("--mapping-cam0", type=Path, required=True)
    ap.add_argument("--mapping-cam1", type=Path, required=True)
    ap.add_argument("--intrinsics-cam0", type=Path, default=None)
    ap.add_argument("--intrinsics-cam1", type=Path, default=None)

    ap.add_argument(
        "--bounds", default="-0.05,0.60,-0.05,0.45", help="xmin,xmax,ymin,ymax (meters)"
    )
    ap.add_argument("--scale", type=float, default=700.0, help="pixels per meter")
    args = ap.parse_args()

    mp0 = Path(args.mapping_cam0)
    mp1 = Path(args.mapping_cam1)
    if not mp0.is_file():
        raise SystemExit(f"missing mapping-cam0: {mp0}")
    if not mp1.is_file():
        raise SystemExit(f"missing mapping-cam1: {mp1}")

    ip0 = Path(args.intrinsics_cam0) if args.intrinsics_cam0 else None
    ip1 = Path(args.intrinsics_cam1) if args.intrinsics_cam1 else None

    mm = load_multi_planar_mapper(
        mapping_by_camera={"cam0": mp0, "cam1": mp1},
        intrinsics_by_camera={"cam0": ip0, "cam1": ip1},
    )

    # show whether intrinsics are actually used (depends on mapping yaml)
    print("[multi] cam0 mapper uses intrinsics =", mm.cams["cam0"].mapper.intrinsics is not None)
    print("[multi] cam1 mapper uses intrinsics =", mm.cams["cam1"].mapper.intrinsics is not None)

    cam0_idx = resolve_v4l_to_index(args.cam0)
    cam1_idx = resolve_v4l_to_index(args.cam1)
    cam = USBMultiCamera(cameras={"cam0": cam0_idx, "cam1": cam1_idx}, require_all=True)
    print(f"[multi] cam0 src={args.cam0} -> index={cam0_idx}")
    print(f"[multi] cam1 src={args.cam1} -> index={cam1_idx}")
    backend = ArUcoBackend()

    xmin, xmax, ymin, ymax = _parse_bounds(args.bounds)
    scale = float(args.scale)

    cam.open()
    try:
        while True:
            frames = cam.read()
            if len(frames) < 2:
                continue

            # Topdown canvas
            w = int((xmax - xmin) * scale)
            h = int((ymax - ymin) * scale)
            top = (0 * (cv2.UMat(h, w, cv2.CV_8UC3).get())).astype("uint8")  # black
            top = cv2.cvtColor(top, cv2.COLOR_BGR2RGB)

            # grid
            step_m = 0.1
            x = xmin
            while x <= xmax:
                px, _ = _world_to_px(x, ymin, xmin=xmin, ymax=ymax, scale=scale)
                cv2.line(top, (px, 0), (px, h), (40, 40, 40), 1)
                x += step_m
            y = ymin
            while y <= ymax:
                _, py = _world_to_px(xmin, y, xmin=xmin, ymax=ymax, scale=scale)
                cv2.line(top, (0, py), (w, py), (40, 40, 40), 1)
                y += step_m

            for fr in frames:
                cid = str(fr.camera_id)
                dets = backend.detect(fr)

                vis = fr.image.copy()
                for mid, cx, cy in dets:
                    xy = mm.pixel_to_world_xy(cid, cx, cy)
                    cv2.circle(vis, (int(cx), int(cy)), 6, (0, 255, 0), -1)

                    if xy is not None:
                        xw, yw = xy
                        txt = f"id={mid} x={xw:.2f} y={yw:.2f}"
                        cv2.putText(
                            vis,
                            txt,
                            (int(cx) + 8, int(cy) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0, 255, 0),
                            2,
                        )

                        px, py = _world_to_px(xw, yw, xmin=xmin, ymax=ymax, scale=scale)

                        col = (0, 255, 255) if cid == "cam1" else (0, 255, 0)
                        cv2.circle(top, (px, py), 6, col, -1)
                        cv2.putText(
                            top, f"{mid}", (px + 6, py - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1
                        )

                cv2.imshow(f"cam_{cid}", vis)

            cv2.imshow("world_topdown", top)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                return 0

    finally:
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
