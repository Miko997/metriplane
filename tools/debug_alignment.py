# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2  # type: ignore
import numpy as np  # type: ignore
import yaml


# ----------------------------
# Basic loaders
# ----------------------------
def load_intrinsics(path: Path):
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    K = np.array(d["camera_matrix"], dtype=np.float64)
    D = np.array(d["dist_coeffs"], dtype=np.float64).reshape(-1)
    iw = int(d.get("image_width", 0) or 0)
    ih = int(d.get("image_height", 0) or 0)
    return K, D, iw, ih


def load_homography(path: Path):
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    H = np.array(d["homography"], dtype=np.float64)
    return H


def load_anchors(path: Path) -> Dict[int, Tuple[float, float]]:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: Dict[int, Tuple[float, float]] = {}
    for a in d.get("anchors", []):
        out[int(a["id"])] = (float(a["world_xy"][0]), float(a["world_xy"][1]))
    return out


# ----------------------------
# Mapping pipelines
# ----------------------------
def undistort_points_px(pts: np.ndarray, K: np.ndarray, D: np.ndarray) -> np.ndarray:
    # pts: (N,2) -> (N,2)
    if pts.size == 0:
        return pts
    p = pts.reshape(-1, 1, 2).astype(np.float64)
    u = cv2.undistortPoints(p, K, D, P=K).reshape(-1, 2)
    return u


def apply_H(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    # pts: (N,2) -> (N,2)
    if pts.size == 0:
        return pts
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    ph = np.concatenate([pts, ones], axis=1)  # (N,3)
    qh = (H @ ph.T).T  # (N,3)
    q = qh[:, :2] / qh[:, 2:3]
    return q


@dataclass
class PipelineResult:
    name: str
    anchor_rmse_m: float
    anchor_max_m: float
    in_bounds_pct: float
    explode_pct: float
    notes: str


def eval_pipeline(
    *,
    name: str,
    H: np.ndarray,
    K: Optional[np.ndarray],
    D: Optional[np.ndarray],
    pts_px_by_id: Dict[int, Tuple[float, float]],
    anchors_gt: Dict[int, Tuple[float, float]],
    undistort_mode: str,  # "none" | "once" | "twice"
    bounds: Tuple[float, float, float, float],
) -> PipelineResult:
    # build arrays of points
    ids = sorted(pts_px_by_id.keys())
    pts = np.array([pts_px_by_id[i] for i in ids], dtype=np.float64)

    # undistort if requested
    if undistort_mode in ("once", "twice"):
        if K is None or D is None:
            return PipelineResult(name, float("inf"), float("inf"), 0.0, 100.0, "NO_INTRINSICS")
        pts = undistort_points_px(pts, K, D)
        if undistort_mode == "twice":
            pts = undistort_points_px(pts, K, D)

    # map to world
    w = apply_H(H, pts)

    # anchor errors
    errs = []
    for i, mid in enumerate(ids):
        if mid in anchors_gt:
            gx, gy = anchors_gt[mid]
            ex = float(w[i, 0] - gx)
            ey = float(w[i, 1] - gy)
            errs.append((ex * ex + ey * ey) ** 0.5)
    if errs:
        anchor_rmse = float(np.sqrt(np.mean(np.square(errs))))
        anchor_max = float(np.max(errs))
    else:
        anchor_rmse = float("nan")
        anchor_max = float("nan")

    # bounds sanity
    xmin, xmax, ymin, ymax = bounds
    inb = 0
    explode = 0
    for i in range(w.shape[0]):
        x, y = float(w[i, 0]), float(w[i, 1])
        if xmin <= x <= xmax and ymin <= y <= ymax:
            inb += 1
        # "explode" heuristic: far outside any reasonable area
        if abs(x) > 10.0 or abs(y) > 10.0:
            explode += 1

    n = max(w.shape[0], 1)
    in_bounds_pct = 100.0 * (inb / n)
    explode_pct = 100.0 * (explode / n)

    notes = ""
    if np.isfinite(anchor_rmse) and anchor_rmse > 0.02:
        notes += f"ANCHOR_RMSE_HIGH({anchor_rmse:.3f}m) "
    if explode_pct > 5.0:
        notes += f"EXPLODING({explode_pct:.1f}%) "
    if in_bounds_pct < 50.0:
        notes += f"LOW_IN_BOUNDS({in_bounds_pct:.1f}%) "
    notes = notes.strip() or "OK"

    return PipelineResult(name, anchor_rmse, anchor_max, in_bounds_pct, explode_pct, notes)


# ----------------------------
# ArUco detection
# ----------------------------
def detect_aruco_centers(bgr: np.ndarray) -> Dict[int, Tuple[float, float]]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    detector = cv2.aruco.ArucoDetector(dictionary)
    corners, ids, _ = detector.detectMarkers(gray)
    out: Dict[int, Tuple[float, float]] = {}
    if ids is None:
        return out
    for mid, cset in zip(ids.flatten(), corners):
        pts = cset.reshape(4, 2)
        cx = float(np.mean(pts[:, 0]))
        cy = float(np.mean(pts[:, 1]))
        out[int(mid)] = (cx, cy)
    return out


# ----------------------------
# Main diagnostic
# ----------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diagnose multi-cam alignment: mapping/intrinsics/double-undistort."
    )
    ap.add_argument("--cam0", type=int, default=0)
    ap.add_argument("--cam1", type=int, default=2)

    ap.add_argument("--mapping-cam0", type=Path, required=True)
    ap.add_argument("--mapping-cam1", type=Path, required=True)
    ap.add_argument("--intrinsics-cam0", type=Path, required=True)
    ap.add_argument("--intrinsics-cam1", type=Path, required=True)

    ap.add_argument("--anchors", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--fps", type=float, default=15.0)

    # sanity bounds (board-ish). For "explode detection", we also look at >10m.
    ap.add_argument("--bounds", default="-0.2,1.3,-0.2,0.6", help="xmin,xmax,ymin,ymax")
    args = ap.parse_args()

    bounds_parts = [float(x.strip()) for x in str(args.bounds).split(",")]
    if len(bounds_parts) != 4:
        raise SystemExit("bounds must be xmin,xmax,ymin,ymax")
    bounds = (bounds_parts[0], bounds_parts[1], bounds_parts[2], bounds_parts[3])

    anchors_gt = load_anchors(args.anchors)

    H0 = load_homography(args.mapping_cam0)
    H1 = load_homography(args.mapping_cam1)

    K0, D0, iw0, ih0 = load_intrinsics(args.intrinsics_cam0)
    K1, D1, iw1, ih1 = load_intrinsics(args.intrinsics_cam1)

    cap0 = cv2.VideoCapture(int(args.cam0))
    cap1 = cv2.VideoCapture(int(args.cam1))
    if not cap0.isOpened():
        raise SystemExit(f"failed to open cam0 index={args.cam0}")
    if not cap1.isOpened():
        raise SystemExit(f"failed to open cam1 index={args.cam1}")

    # Collect samples
    t_end = time.time() + float(args.seconds)
    interval = 1.0 / max(float(args.fps), 1e-6)

    samples0: List[Dict[int, Tuple[float, float]]] = []
    samples1: List[Dict[int, Tuple[float, float]]] = []
    sizes0: List[Tuple[int, int]] = []
    sizes1: List[Tuple[int, int]] = []

    print("\n[debug] collecting frames...")
    while time.time() < t_end:
        ok0, f0 = cap0.read()
        ok1, f1 = cap1.read()
        if ok0 and f0 is not None:
            sizes0.append((int(f0.shape[1]), int(f0.shape[0])))
            samples0.append(detect_aruco_centers(f0))
        if ok1 and f1 is not None:
            sizes1.append((int(f1.shape[1]), int(f1.shape[0])))
            samples1.append(detect_aruco_centers(f1))
        time.sleep(interval)

    cap0.release()
    cap1.release()

    def _mode_size(sizes: List[Tuple[int, int]]) -> Tuple[int, int]:
        if not sizes:
            return (0, 0)
        from collections import Counter

        c = Counter(sizes)
        return c.most_common(1)[0][0]

    sz0 = _mode_size(sizes0)
    sz1 = _mode_size(sizes1)

    print("\n[debug] camera sizes observed:")
    print(f"  cam0 stream size = {sz0}, intrinsics size = ({iw0},{ih0})")
    print(f"  cam1 stream size = {sz1}, intrinsics size = ({iw1},{ih1})")
    if (iw0 and ih0) and (sz0 != (iw0, ih0)):
        print(
            "  !! cam0 intrinsics size DOES NOT match stream size -> HIGH suspicion (wrong intrinsics or different resolution)"
        )
    if (iw1 and ih1) and (sz1 != (iw1, ih1)):
        print("  !! cam1 intrinsics size DOES NOT match stream size -> HIGH suspicion")

    # Merge detections across samples (take median pixel per id for stability)
    def _median_dets(
        samples: List[Dict[int, Tuple[float, float]]],
    ) -> Dict[int, Tuple[float, float]]:
        acc: Dict[int, List[Tuple[float, float]]] = {}
        for s in samples:
            for mid, (cx, cy) in s.items():
                acc.setdefault(mid, []).append((cx, cy))
        out: Dict[int, Tuple[float, float]] = {}
        for mid, pts in acc.items():
            xs = np.array([p[0] for p in pts], dtype=np.float64)
            ys = np.array([p[1] for p in pts], dtype=np.float64)
            out[mid] = (float(np.median(xs)), float(np.median(ys)))
        return out

    det0 = _median_dets(samples0)
    det1 = _median_dets(samples1)

    print("\n[debug] detections (median) count:")
    print(
        f"  cam0 ids={len(det0)} sample={sorted(list(det0.keys()))[:12]}{'...' if len(det0) > 12 else ''}"
    )
    print(
        f"  cam1 ids={len(det1)} sample={sorted(list(det1.keys()))[:12]}{'...' if len(det1) > 12 else ''}"
    )

    # Evaluate pipelines for each cam
    pipelines = []

    # Normal
    pipelines.append(("cam0/raw->H0", H0, None, None, det0, "none"))
    pipelines.append(("cam0/undistort->H0", H0, K0, D0, det0, "once"))
    pipelines.append(("cam0/undistort2->H0", H0, K0, D0, det0, "twice"))

    pipelines.append(("cam1/raw->H1", H1, None, None, det1, "none"))
    pipelines.append(("cam1/undistort->H1", H1, K1, D1, det1, "once"))
    pipelines.append(("cam1/undistort2->H1", H1, K1, D1, det1, "twice"))

    # Swap intrinsics test
    pipelines.append(("cam0/undistort(cam1K)->H0", H0, K1, D1, det0, "once"))
    pipelines.append(("cam1/undistort(cam0K)->H1", H1, K0, D0, det1, "once"))

    results: List[PipelineResult] = []
    for name, H, K, D, det, mode in pipelines:
        r = eval_pipeline(
            name=name,
            H=H,
            K=K,
            D=D,
            pts_px_by_id=det,
            anchors_gt=anchors_gt,
            undistort_mode=mode,
            bounds=bounds,
        )
        results.append(r)

    # Print report
    print("\n=== PIPELINE RESULTS (lower anchor RMSE is better; higher in-bounds is better) ===")
    for r in results:
        print(
            f"{r.name:28s}  "
            f"anchor_rmse={r.anchor_rmse_m:8.4f}  "
            f"anchor_max={r.anchor_max_m:8.4f}  "
            f"in_bounds={r.in_bounds_pct:6.1f}%  "
            f"explode={r.explode_pct:6.1f}%  "
            f"{r.notes}"
        )

    # Cross-camera consistency: compare world coords for IDs visible in both cameras under "best" pipeline guesses
    # We'll choose for each cam the best among raw/undistort/undistort2 based on in_bounds then anchor_rmse.
    def _pick_best(prefix: str) -> PipelineResult:
        cand = [r for r in results if r.name.startswith(prefix)]
        # sort: explode low, in_bounds high, anchor rmse low
        cand.sort(key=lambda x: (x.explode_pct, -x.in_bounds_pct, x.anchor_rmse_m))
        return cand[0]

    best0 = _pick_best("cam0/")
    best1 = _pick_best("cam1/")
    print("\n[debug] best pipelines chosen:")
    print(f"  best cam0 = {best0.name}")
    print(f"  best cam1 = {best1.name}")

    # Recompute world coords for bests
    def _world_map(
        det: Dict[int, Tuple[float, float]],
        H: np.ndarray,
        K: Optional[np.ndarray],
        D: Optional[np.ndarray],
        mode: str,
    ) -> Dict[int, Tuple[float, float]]:
        ids = sorted(det.keys())
        pts = np.array([det[i] for i in ids], dtype=np.float64)
        if mode in ("once", "twice"):
            pts = undistort_points_px(pts, K, D)  # type: ignore[arg-type]
            if mode == "twice":
                pts = undistort_points_px(pts, K, D)  # type: ignore[arg-type]
        w = apply_H(H, pts)
        out: Dict[int, Tuple[float, float]] = {}
        for idx, mid in enumerate(ids):
            out[mid] = (float(w[idx, 0]), float(w[idx, 1]))
        return out

    # Decode best pipeline params
    def _decode_best(r: PipelineResult):
        # name looks like: cam0/undistort->H0
        if "cam0" in r.name:
            H = H0
        else:
            H = H1
        if "undistort2" in r.name:
            mode = "twice"
        elif "undistort" in r.name:
            mode = "once"
        else:
            mode = "none"
        if "cam0" in r.name:
            K, D = K0, D0
        else:
            K, D = K1, D1
        return H, K, D, mode

    H_best0, K_best0, D_best0, mode0 = _decode_best(best0)
    H_best1, K_best1, D_best1, mode1 = _decode_best(best1)

    w0 = _world_map(det0, H_best0, K_best0, D_best0, mode0)
    w1 = _world_map(det1, H_best1, K_best1, D_best1, mode1)

    overlap = sorted(set(w0.keys()) & set(w1.keys()))
    overlap_nonanchors = [i for i in overlap if i not in anchors_gt]

    def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    if overlap:
        dists = [_dist(w0[i], w1[i]) for i in overlap]
        print("\n=== CROSS-CAMERA CONSISTENCY (using best per-cam pipeline) ===")
        print(f"overlap ids={overlap}")
        print(f"mean_dist={float(np.mean(dists)):.4f}m  max_dist={float(np.max(dists)):.4f}m")

        # Per-marker table
        print("\n=== PER-MARKER CROSS-CAMERA COMPARISON ===")
        print(
            f"{'ID':<6} {'Cam0_X':>8} {'Cam0_Y':>8} {'Cam1_X':>8} {'Cam1_Y':>8} {'Dist_m':>8} {'Type':<10}"
        )
        print("-" * 68)

        # Anchors first
        anchor_ids = [i for i in overlap if i in anchors_gt]
        for mid in anchor_ids:
            x0, y0 = w0[mid]
            x1, y1 = w1[mid]
            dist = _dist(w0[mid], w1[mid])
            print(f"{mid:<6} {x0:8.4f} {y0:8.4f} {x1:8.4f} {y1:8.4f} {dist:8.4f} {'ANCHOR':<10}")

        # Non-anchors
        bad_markers = []
        for mid in overlap_nonanchors:
            x0, y0 = w0[mid]
            x1, y1 = w1[mid]
            dist = _dist(w0[mid], w1[mid])
            marker_type = "NON-ANCHOR"
            if dist > 0.02:
                marker_type += " ⚠"
                bad_markers.append((mid, dist))
            print(f"{mid:<6} {x0:8.4f} {y0:8.4f} {x1:8.4f} {y1:8.4f} {dist:8.4f} {marker_type:<10}")

        # Warnings
        if bad_markers:
            print("\n⚠ WARNING: Large disagreement on non-anchor markers:")
            for mid, dist in bad_markers:
                print(f"  Marker ID {mid}: {dist:.4f}m (>0.02m threshold)")

        if overlap_nonanchors:
            d2 = [_dist(w0[i], w1[i]) for i in overlap_nonanchors]
            print(
                f"\nnon-anchor summary: mean_dist={float(np.mean(d2)):.4f}m  max_dist={float(np.max(d2)):.4f}m"
            )
    else:
        print("\n[debug] No overlapping IDs between cams in the capture window.")

    # Verdict heuristics
    print("\n=== VERDICT (heuristics) ===")
    # 1) Intrinsics mismatch
    if (iw0 and ih0) and (sz0 != (iw0, ih0)):
        print(
            "cam0: INTRINSICS SIZE MISMATCH -> calibrate intrinsics at the exact runtime resolution, or force camera to that resolution."
        )
    if (iw1 and ih1) and (sz1 != (iw1, ih1)):
        print(
            "cam1: INTRINSICS SIZE MISMATCH -> calibrate intrinsics at the exact runtime resolution, or force camera to that resolution."
        )

    # 2) Double-undistort suspicion: undistort2 beats undistort by a lot
    def _find(name: str) -> Optional[PipelineResult]:
        for r in results:
            if r.name == name:
                return r
        return None

    r0_u = _find("cam0/undistort->H0")
    r0_u2 = _find("cam0/undistort2->H0")
    if (
        r0_u
        and r0_u2
        and (r0_u2.in_bounds_pct > (r0_u.in_bounds_pct + 15.0))
        and (r0_u2.explode_pct < r0_u.explode_pct)
    ):
        print(
            "cam0: looks like DOUBLE-UNDISTORT in your normal pipeline (undistort twice performs much better)."
        )
    r1_u = _find("cam1/undistort->H1")
    r1_u2 = _find("cam1/undistort2->H1")
    if (
        r1_u
        and r1_u2
        and (r1_u2.in_bounds_pct > (r1_u.in_bounds_pct + 15.0))
        and (r1_u2.explode_pct < r1_u.explode_pct)
    ):
        print("cam1: looks like DOUBLE-UNDISTORT in your normal pipeline.")

    # 3) Intrinsics swapped suspicion
    r0_swap = _find("cam0/undistort(cam1K)->H0")
    r1_swap = _find("cam1/undistort(cam0K)->H1")
    if r0_u and r0_swap and (r0_swap.in_bounds_pct > (r0_u.in_bounds_pct + 20.0)):
        print(
            "cam0: using cam1 intrinsics improves a lot -> your intrinsics files are likely swapped/mislabeled."
        )
    if r1_u and r1_swap and (r1_swap.in_bounds_pct > (r1_u.in_bounds_pct + 20.0)):
        print(
            "cam1: using cam0 intrinsics improves a lot -> your intrinsics files are likely swapped/mislabeled."
        )

    # 4) Ill-conditioned homography suspicion: anchors OK but non-anchor exploding
    # If anchors RMSE ~0 but explode% high or in-bounds low.
    for cam in ("cam0", "cam1"):
        rr = _find(f"{cam}/undistort->{'H0' if cam == 'cam0' else 'H1'}")
        if (
            rr
            and np.isfinite(rr.anchor_rmse_m)
            and rr.anchor_rmse_m < 1e-3
            and (rr.explode_pct > 5.0 or rr.in_bounds_pct < 60.0)
        ):
            print(
                f"{cam}: anchors fit perfectly but other points blow up -> homography is ill-conditioned OR undistortion is wrong for most of the image."
            )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
