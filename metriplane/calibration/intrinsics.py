# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import datetime as _dt
import logging
from pathlib import Path
from typing import Any, Tuple

import cv2  # type: ignore
import numpy as np  # type: ignore
import yaml

log = logging.getLogger("metriplane.calibration.intrinsics")


def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _build_object_points(cols: int, rows: int, square_size_m: float) -> np.ndarray:
    """
    Chessboard object points in the board coordinate system (Z=0 plane).
    cols/rows = number of *inner* corners (OpenCV convention).
    """
    objp = np.zeros((rows * cols, 3), dtype=np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_size_m)
    return objp


def _find_chessboard(gray: np.ndarray, pattern_size: Tuple[int, int]) -> tuple[bool, Any]:
    """
    Returns (found, corners).
    Tries findChessboardCornersSB when available for better robustness.
    """
    cols, rows = pattern_size
    try:
        if hasattr(cv2, "findChessboardCornersSB"):
            found, corners = cv2.findChessboardCornersSB(
                gray,
                (cols, rows),
                flags=cv2.CALIB_CB_NORMALIZE_IMAGE,
            )
            return bool(found), corners
    except Exception:
        pass

    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_NORMALIZE_IMAGE
    found, corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
    return bool(found), corners


def _save_intrinsics(
    out_path: Path,
    *,
    image_size: tuple[int, int],
    cols: int,
    rows: int,
    square_size_m: float,
    rms: float,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    per_view_errors: list[float],
    extra: dict[str, Any] | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "type": "camera_intrinsics_v1",
        "computed_at": _now_iso(),
        "image_width": int(image_size[0]),
        "image_height": int(image_size[1]),
        "pattern": {
            "type": "chessboard",
            "cols": int(cols),
            "rows": int(rows),
            "square_size_m": float(square_size_m),
        },
        "rms_reprojection_error": float(rms),
        "camera_matrix": camera_matrix.astype(float).tolist(),
        "dist_coeffs": dist_coeffs.astype(float).reshape(-1).tolist(),
        "per_view_errors": [float(e) for e in per_view_errors],
        "samples": int(len(per_view_errors)),
    }
    if extra:
        payload.update(extra)

    out_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _compute_reprojection_errors(
    objpoints: list[np.ndarray],
    imgpoints: list[np.ndarray],
    rvecs: list[np.ndarray],
    tvecs: list[np.ndarray],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
) -> list[float]:
    errs: list[float] = []
    for i in range(len(objpoints)):
        imgpoints2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], camera_matrix, dist_coeffs)
        imgpoints2 = imgpoints2.reshape(-1, 2)
        imgp = imgpoints[i].reshape(-1, 2)
        err = cv2.norm(imgp, imgpoints2, cv2.NORM_L2) / max(len(imgpoints2), 1)
        errs.append(float(err))
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="M5: Camera intrinsics calibration (chessboard).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--camera", type=int, default=0, help="USB camera index (default: 0)")
    src.add_argument("--video", type=Path, help="Optional: calibrate from a video file instead of live camera")
    ap.add_argument("--cols", type=int, default=9, help="Chessboard inner corners (columns)")
    ap.add_argument("--rows", type=int, default=6, help="Chessboard inner corners (rows)")
    ap.add_argument("--square-size-m", type=float, default=0.024, help="Chessboard square size in meters")
    ap.add_argument("--min-samples", type=int, default=15, help="Minimum captures before allowing save")
    ap.add_argument("--out", type=Path, default=Path("calib/camera.yaml"), help="Output YAML path")
    ap.add_argument("--no-preview", action="store_true", help="Do not open OpenCV window (headless)")
    ap.add_argument("--print-every", type=int, default=5, help="Print status every N captures")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    pattern_size = (int(args.cols), int(args.rows))
    square_size_m = float(args.square_size_m)
    objp = _build_object_points(args.cols, args.rows, square_size_m)

    cap: cv2.VideoCapture
    if args.video:
        cap = cv2.VideoCapture(str(args.video))
        if not cap.isOpened():
            log.error("failed to open video: %s", args.video)
            return 2
    else:
        cap = cv2.VideoCapture(int(args.camera))
        if not cap.isOpened():
            log.error("failed to open camera index=%s", args.camera)
            return 2

    objpoints: list[np.ndarray] = []
    imgpoints: list[np.ndarray] = []

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-4)

    log.info("Controls: SPACE=capture sample, r=reset, q=calibrate+write, ESC=quit")
    log.info(
        "Chessboard: cols=%d rows=%d square=%.4fm min_samples=%d",
        args.cols, args.rows, square_size_m, args.min_samples
    )

    image_size: tuple[int, int] | None = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                log.warning("frame read failed")
                break

            h, w = frame.shape[:2]
            image_size = (w, h)

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = _find_chessboard(gray, pattern_size)

            vis = frame.copy()
            if found:
                try:
                    corners2 = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
                except Exception:
                    corners2 = corners

                cv2.drawChessboardCorners(vis, pattern_size, corners2, found)
                status = "FOUND"
            else:
                corners2 = None
                status = "not found"

            cv2.putText(
                vis,
                f"captures={len(imgpoints)}  status={status}  (SPACE=capture, q=save, ESC=quit)",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            if not args.no_preview:
                cv2.imshow("metriplane_calibrate_intrinsics", vis)
                key = cv2.waitKey(1) & 0xFF
            else:
                key = 255

            if key == 27:  # ESC
                log.info("quit (ESC)")
                return 1

            if key == ord("r"):
                objpoints.clear()
                imgpoints.clear()
                log.info("reset captures")
                continue

            if key == ord(" "):
                if not found or corners2 is None:
                    log.warning("cannot capture: chessboard not found")
                    continue
                objpoints.append(objp.copy())
                imgpoints.append(corners2.astype(np.float32))
                if (len(imgpoints) % max(int(args.print_every), 1)) == 0:
                    log.info("captured %d samples", len(imgpoints))
                continue

            if key == ord("q"):
                if image_size is None:
                    log.error("no image size detected; cannot calibrate")
                    return 2
                if len(imgpoints) < int(args.min_samples):
                    log.warning("need at least %d samples (have %d)", args.min_samples, len(imgpoints))
                    continue

                log.info("calibrating... samples=%d image_size=%s", len(imgpoints), image_size)
                ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
                    objpoints,
                    imgpoints,
                    image_size,
                    None,
                    None,
                )
                rms = float(ret)
                per_view = _compute_reprojection_errors(objpoints, imgpoints, rvecs, tvecs, camera_matrix, dist_coeffs)

                log.info("done. RMS reprojection error: %.4f px", rms)
                log.info("saving -> %s", args.out)
                _save_intrinsics(
                    args.out,
                    image_size=image_size,
                    cols=args.cols,
                    rows=args.rows,
                    square_size_m=square_size_m,
                    rms=rms,
                    camera_matrix=camera_matrix,
                    dist_coeffs=dist_coeffs,
                    per_view_errors=per_view,
                )
                log.info("WROTE %s", args.out)
                return 0

    finally:
        cap.release()
        if not args.no_preview:
            cv2.destroyAllWindows()

    log.warning("ended without saving")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
