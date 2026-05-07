from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Dict, Tuple, List

import cv2  # type: ignore
import numpy as np  # type: ignore
import yaml

from metriplane.mapping.planar import load_planar_mapper


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


def load_anchors(path: Path) -> Dict[int, Tuple[float, float]]:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: Dict[int, Tuple[float, float]] = {}
    for a in d.get("anchors", []):
        out[int(a["id"])] = (float(a["world_xy"][0]), float(a["world_xy"][1]))
    return out


def median_dets(samples: List[Dict[int, Tuple[float, float]]]) -> Dict[int, Tuple[float, float]]:
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Report per-ID cross-camera world XY deltas.")
    ap.add_argument("--cam0", type=int, default=0)
    ap.add_argument("--cam1", type=int, default=2)
    ap.add_argument("--mapping-cam0", type=Path, required=True)
    ap.add_argument("--mapping-cam1", type=Path, required=True)
    ap.add_argument("--intrinsics-cam0", type=Path, default=None)
    ap.add_argument("--intrinsics-cam1", type=Path, default=None)
    ap.add_argument("--anchors", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--fps", type=float, default=15.0)
    args = ap.parse_args()

    mapper0 = load_planar_mapper(args.mapping_cam0, args.intrinsics_cam0)
    mapper1 = load_planar_mapper(args.mapping_cam1, args.intrinsics_cam1)
    anchors = load_anchors(args.anchors)

    cap0 = cv2.VideoCapture(int(args.cam0))
    cap1 = cv2.VideoCapture(int(args.cam1))
    if not cap0.isOpened():
        raise SystemExit(f"failed to open cam0 index={args.cam0}")
    if not cap1.isOpened():
        raise SystemExit(f"failed to open cam1 index={args.cam1}")

    t_end = time.time() + float(args.seconds)
    interval = 1.0 / max(float(args.fps), 1e-6)

    s0: List[Dict[int, Tuple[float, float]]] = []
    s1: List[Dict[int, Tuple[float, float]]] = []

    print("[report] collecting...")
    while time.time() < t_end:
        ok0, f0 = cap0.read()
        ok1, f1 = cap1.read()
        if ok0 and f0 is not None:
            s0.append(detect_aruco_centers(f0))
        if ok1 and f1 is not None:
            s1.append(detect_aruco_centers(f1))
        time.sleep(interval)

    cap0.release()
    cap1.release()

    d0 = median_dets(s0)
    d1 = median_dets(s1)

    ids = sorted(set(d0.keys()) & set(d1.keys()))
    if not ids:
        print("[report] no overlapping IDs seen")
        return 2

    print("\nID  cam0(x,y)              cam1(x,y)              dist(m)   anchor?")
    print("--  --------------------   --------------------   -------   ------")
    for mid in ids:
        xy0 = mapper0.pixel_to_world_xy(*d0[mid])
        xy1 = mapper1.pixel_to_world_xy(*d1[mid])
        if xy0 is None or xy1 is None:
            continue
        dx = float(xy0[0] - xy1[0])
        dy = float(xy0[1] - xy1[1])
        dist = float(np.hypot(dx, dy))
        is_anchor = "YES" if mid in anchors else ""
        print(f"{mid:>2d}  ({xy0[0]:>7.3f},{xy0[1]:>7.3f})   ({xy1[0]:>7.3f},{xy1[1]:>7.3f})   {dist:>7.3f}   {is_anchor}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
