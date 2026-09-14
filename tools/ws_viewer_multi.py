# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any, Dict, Tuple

import cv2  # type: ignore
import numpy as np  # type: ignore
import websockets  # type: ignore


def _parse_bounds(s: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bounds must be xmin,xmax,ymin,ymax")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def _world_to_px(
    x: float, y: float, *, xmin: float, xmax: float, ymin: float, ymax: float, scale: float
) -> tuple[int, int]:
    px = int((x - xmin) * scale)
    py = int((ymax - y) * scale)  # invert y for topdown
    return (px, py)


def _blank(h: int, w: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _draw_grid(
    img: np.ndarray,
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    scale: float,
    step_m: float = 0.1,
) -> None:
    h, w = img.shape[:2]
    x = xmin
    while x <= xmax + 1e-9:
        px, _ = _world_to_px(x, ymin, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
        if 0 <= px < w:
            cv2.line(img, (px, 0), (px, h), (40, 40, 40), 1)
        x += step_m
    y = ymin
    while y <= ymax + 1e-9:
        _, py = _world_to_px(xmin, y, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
        if 0 <= py < h:
            cv2.line(img, (0, py), (w, py), (40, 40, 40), 1)
        y += step_m


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _extract_cam_frames(frame: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Returns {camera_id: {"ts_cam_read":..., "objects":[...]} }
    """
    out: Dict[str, Dict[str, Any]] = {}
    raw = frame.get("raw_per_camera") or []
    if isinstance(raw, list):
        for cf in raw:
            if not isinstance(cf, dict):
                continue
            cid = str(cf.get("camera_id") or "")
            if not cid:
                continue
            out[cid] = cf
    return out


def _draw_cam_overlay(img: np.ndarray, cam_payload: Dict[str, Any], label: str) -> np.ndarray:
    vis = img.copy()
    cv2.putText(vis, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

    objs = cam_payload.get("objects") or []
    if isinstance(objs, list):
        for o in objs[:50]:
            if not isinstance(o, dict):
                continue
            oid = str(o.get("id", "?"))
            extra = o.get("extra") or {}
            px = extra.get("px") if isinstance(extra, dict) else None
            if isinstance(px, (list, tuple)) and len(px) >= 2:
                cx, cy = int(float(px[0])), int(float(px[1]))
                cv2.circle(vis, (cx, cy), 6, (0, 255, 0), -1)
                cv2.putText(
                    vis, oid, (cx + 8, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
                )
    return vis


def _topdown_canvas(bounds: Tuple[float, float, float, float], scale: float) -> np.ndarray:
    xmin, xmax, ymin, ymax = bounds
    w = int(max(1.0, (xmax - xmin) * scale))
    h = int(max(1.0, (ymax - ymin) * scale))
    img = _blank(h, w)
    _draw_grid(img, xmin, xmax, ymin, ymax, scale)
    return img


def _draw_topdown(
    top: np.ndarray, frame: Dict[str, Any], bounds: Tuple[float, float, float, float], scale: float
) -> np.ndarray:
    xmin, xmax, ymin, ymax = bounds
    vis = top.copy()

    # Draw fused objects (frame["objects"])
    objs = frame.get("objects") or []
    if isinstance(objs, list):
        for o in objs[:200]:
            if not isinstance(o, dict):
                continue
            oid = str(o.get("id", "?"))
            pw = o.get("pos_world")
            if not (isinstance(pw, (list, tuple)) and len(pw) >= 2):
                continue
            x = _safe_float(pw[0])
            y = _safe_float(pw[1])

            px, py = _world_to_px(x, y, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
            if 0 <= px < vis.shape[1] and 0 <= py < vis.shape[0]:
                cv2.circle(vis, (px, py), 6, (0, 200, 255), -1)  # yellow-ish
                cv2.putText(
                    vis, oid, (px + 7, py - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2
                )

    # HUD (fps-ish)
    cv2.putText(vis, "TOPDOWN (fused)", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    return vis


async def main_async(url: str, bounds: Tuple[float, float, float, float], scale: float) -> int:
    top_base = _topdown_canvas(bounds, scale)

    last = time.time()
    frames = 0

    async with websockets.connect(url, ping_interval=None) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)

            cam_frames = _extract_cam_frames(data)

            # Build images
            # If cam images are not available in WS payload, we just show black.
            # (Optionally we could draw only topdown.)
            cam0 = cam_frames.get("cam0")
            cam1 = cam_frames.get("cam1")

            # NOTE: We do not receive raw camera pixels via WS in current schema.
            # So we render "camera windows" as overlays only. If you want real pixels in this viewer,
            # we must add frame.image JPEG encoding into WS (not recommended for now).
            # For now, the "both camera views" in this viewer are diagnostic overlays.
            cam0_img = _blank(480, 640)
            cam1_img = _blank(480, 640)

            cam0_vis = _draw_cam_overlay(cam0_img, cam0 or {"objects": []}, "cam0 (WS diagnostics)")
            cam1_vis = _draw_cam_overlay(cam1_img, cam1 or {"objects": []}, "cam1 (WS diagnostics)")

            top_vis = _draw_topdown(top_base, data, bounds, scale)

            # FPS text
            frames += 1
            now = time.time()
            if now - last >= 1.0:
                fps = frames / (now - last)
                frames = 0
                last = now
            else:
                fps = None

            if fps is not None:
                cv2.putText(
                    top_vis,
                    f"viewer_fps={fps:.1f}",
                    (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )

            cv2.imshow("cam0", cam0_vis)
            cv2.imshow("cam1", cam1_vis)
            cv2.imshow("topdown", top_vis)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

    cv2.destroyAllWindows()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="WS viewer: cam0/cam1 diagnostics + fused topdown (no camera access)."
    )
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--bounds", default="-0.05,1.15,-0.05,0.45")
    ap.add_argument("--scale", type=float, default=700.0)
    args = ap.parse_args()

    bounds = _parse_bounds(args.bounds)
    return asyncio.run(main_async(args.url, bounds, float(args.scale)))


if __name__ == "__main__":
    raise SystemExit(main())
