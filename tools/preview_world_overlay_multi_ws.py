# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np  # type: ignore

from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb_multi import USBMultiCamera
from metriplane.mapping.planar_multi import load_multi_planar_mapper
from metriplane.schema import CameraFrameModel, FrameStateModel, ObjectStateModel
from metriplane.streaming.ws_server import client_count
from metriplane.streaming.ws_thread import WsServerThread
from metriplane.tracking import ObjectRegistry


def _parse_bounds(s: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bounds must be xmin,xmax,ymin,ymax")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def _world_to_px(
    x: float, y: float, *, xmin: float, xmax: float, ymin: float, ymax: float, scale: float
) -> tuple[int, int]:
    px = int((x - xmin) * scale)
    py = int((ymax - y) * scale)
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


def _fuse_nearest(obs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not obs:
        return None
    # pick smallest mapping rmse (fallback huge if missing)
    return min(obs, key=lambda o: float(o.get("rmse", 1e9)))


def _fuse_avg(obs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not obs:
        return None
    xs = [float(o["x"]) for o in obs]
    ys = [float(o["y"]) for o in obs]
    return {
        "x": float(np.mean(xs)),
        "y": float(np.mean(ys)),
        "camera_id": "avg",
        "rmse": None,
        "px": None,
    }


def _fuse_weighted(obs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not obs:
        return None
    eps = 1e-9
    ws = []
    xs = []
    ys = []
    for o in obs:
        r = float(o.get("rmse", 0.05) or 0.05)
        w = 1.0 / (r * r + eps)
        ws.append(w)
        xs.append(float(o["x"]))
        ys.append(float(o["y"]))
    ws = np.array(ws, dtype=np.float64)
    xs = np.array(xs, dtype=np.float64)
    ys = np.array(ys, dtype=np.float64)
    wsum = float(np.sum(ws)) if float(np.sum(ws)) > 0 else 1.0
    return {
        "x": float(np.sum(ws * xs) / wsum),
        "y": float(np.sum(ws * ys) / wsum),
        "camera_id": "weighted",
        "rmse": None,
        "px": None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Like preview_world_overlay_multi, but ALSO publishes WS frames for Omniverse/ROS2."
    )
    ap.add_argument("--cam0", type=int, default=0)
    ap.add_argument("--cam1", type=int, default=2)

    ap.add_argument("--mapping-cam0", type=Path, required=True)
    ap.add_argument("--mapping-cam1", type=Path, required=True)

    # IMPORTANT: keep intrinsics optional (and default NONE) to match mapping_raw behavior
    ap.add_argument("--intrinsics-cam0", type=Path, default=None)
    ap.add_argument("--intrinsics-cam1", type=Path, default=None)

    ap.add_argument("--bounds", default="-0.05,1.15,-0.05,0.45")
    ap.add_argument("--scale", type=float, default=700.0)

    ap.add_argument("--ws-host", default="127.0.0.1")
    ap.add_argument("--ws-port", type=int, default=8765)

    ap.add_argument("--fusion", choices=["nearest", "avg", "weighted"], default="nearest")
    ap.add_argument("--object-timeout-s", type=float, default=2.0)

    ap.add_argument("--record-jsonl", type=Path, default=None)
    ap.add_argument("--record-mosaic", type=Path, default=None)
    ap.add_argument("--record-fps", type=float, default=20.0)

    args = ap.parse_args()

    # Mapper (THIS is the whole point: use mapping_raw and NO intrinsics unless explicitly provided)
    mm = load_multi_planar_mapper(
        mapping_by_camera={"cam0": args.mapping_cam0, "cam1": args.mapping_cam1},
        intrinsics_by_camera={"cam0": args.intrinsics_cam0, "cam1": args.intrinsics_cam1},
    )

    ws = WsServerThread(host=args.ws_host, port=args.ws_port)
    ws.start()

    record_f = None
    if args.record_jsonl is not None:
        args.record_jsonl.parent.mkdir(parents=True, exist_ok=True)
        record_f = args.record_jsonl.open("w", encoding="utf-8", buffering=1)
        print("[ws_preview] recording jsonl ->", args.record_jsonl)

    writer = None

    cam = USBMultiCamera(cameras={"cam0": args.cam0, "cam1": args.cam1}, require_all=True)
    backend = ArUcoBackend()
    registry = ObjectRegistry(timeout_s=float(args.object_timeout_s))

    xmin, xmax, ymin, ymax = _parse_bounds(args.bounds)
    scale = float(args.scale)

    frame_times: deque[float] = deque(maxlen=60)
    frame_id = 0
    frames_total = 0

    cam.open()
    try:
        while True:
            frames = cam.read()
            if len(frames) < 2:
                continue

            frames_total += 1
            frame_id += 1

            ts_frame = max(float(fr.ts_cam_read) for fr in frames)
            now_mono = time.monotonic()
            frame_times.append(now_mono)

            fps = 0.0
            if len(frame_times) >= 2:
                dt = frame_times[-1] - frame_times[0]
                if dt > 1e-6:
                    fps = float(len(frame_times) - 1) / dt

            # Prepare topdown
            w = int(max(1.0, (xmax - xmin) * scale))
            h = int(max(1.0, (ymax - ymin) * scale))
            top = _blank(h, w)
            _draw_grid(top, xmin, xmax, ymin, ymax, scale)

            # Collect per-cam visuals + raw objects + fusion observations
            cam_vis: dict[str, np.ndarray] = {}
            raw_models: list[CameraFrameModel] = []
            obs_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)

            for fr in frames:
                cid = str(fr.camera_id)
                dets = backend.detect(fr)
                vis = fr.image.copy()

                raw_objs: list[ObjectStateModel] = []
                rmse = mm.rmse_for(cid)

                for mid, cx, cy in dets:
                    xy = mm.pixel_to_world_xy(cid, float(cx), float(cy))

                    cv2.circle(vis, (int(cx), int(cy)), 6, (0, 255, 0), -1)

                    if xy is None:
                        continue

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

                    raw_objs.append(
                        ObjectStateModel(
                            id=str(mid),
                            pos_world=(float(xw), float(yw), 0.0),
                            confidence=1.0,
                            extra={
                                "px": (float(cx), float(cy)),
                                "camera_id": cid,
                                "cam_anchor_rmse": rmse,
                            },
                        )
                    )

                    obs_by_id[str(mid)].append(
                        {
                            "camera_id": cid,
                            "x": float(xw),
                            "y": float(yw),
                            "rmse": rmse,
                            "px": (float(cx), float(cy)),
                        }
                    )

                    # topdown draw (cam0 green, cam1 yellow like your working tool)
                    px, py = _world_to_px(
                        xw, yw, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale
                    )
                    col = (0, 255, 255) if cid == "cam1" else (0, 255, 0)
                    if 0 <= px < w and 0 <= py < h:
                        cv2.circle(top, (px, py), 6, col, -1)
                        cv2.putText(
                            top, f"{mid}", (px + 6, py - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1
                        )

                cv2.putText(
                    vis, f"{cid}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2
                )
                cam_vis[cid] = vis
                raw_models.append(
                    CameraFrameModel(
                        camera_id=cid, ts_cam_read=float(fr.ts_cam_read), objects=raw_objs
                    )
                )

                cv2.imshow(f"cam_{cid}", vis)

            cv2.putText(
                top,
                f"world_topdown  fusion={args.fusion}  fps={fps:.1f}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
            cv2.imshow("world_topdown", top)

            # Fuse -> tracked
            fused_now: list[ObjectStateModel] = []
            for oid, obs in obs_by_id.items():
                if args.fusion == "avg":
                    best = _fuse_avg(obs)
                elif args.fusion == "weighted":
                    best = _fuse_weighted(obs)
                else:
                    best = _fuse_nearest(obs)

                if best is None:
                    continue

                fused_now.append(
                    ObjectStateModel(
                        id=str(oid),
                        pos_world=(float(best["x"]), float(best["y"]), 0.0),
                        confidence=1.0,
                        extra={
                            "fusion": {
                                "method": args.fusion,
                                "sources": [o["camera_id"] for o in obs],
                            }
                        },
                    )
                )

            registry.update(fused_now, now_s=time.monotonic())
            tracked = registry.snapshot()

            # WS publish
            ws_clients = client_count()
            msg = FrameStateModel(
                source_backend="aruco_fusion_preview_raw",
                ts=float(ts_frame),
                frame_id=int(frame_id),
                objects=tracked,
                fused=tracked,
                raw_per_camera=raw_models,
                events=[],
                metrics={
                    "fps": fps,
                    "frames_total": frames_total,
                    "ws_clients_connected": ws_clients,
                    "fusion_method": args.fusion,
                    "mapping_units": mm.units,
                    "cams": ["cam0", "cam1"],
                },
            )

            if record_f is not None:
                record_f.write(json.dumps(msg.model_dump(), ensure_ascii=False) + "\n")

            ws.send_frame(msg)

            # Optional: record one single mp4 that contains cam0+cam1+topdown
            if args.record_mosaic is not None:
                c0 = cam_vis.get("cam0", _blank(480, 640))
                c1 = cam_vis.get("cam1", _blank(480, 640))
                if c1.shape[:2] != c0.shape[:2]:
                    c1 = cv2.resize(c1, (c0.shape[1], c0.shape[0]))

                cams_row = np.hstack([c0, c1])
                top_r = cv2.resize(top, (cams_row.shape[1], c0.shape[0]))
                mosaic = np.vstack([cams_row, top_r])

                if writer is None:
                    args.record_mosaic.parent.mkdir(parents=True, exist_ok=True)
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(
                        str(args.record_mosaic),
                        fourcc,
                        float(args.record_fps),
                        (mosaic.shape[1], mosaic.shape[0]),
                    )
                    print("[ws_preview] recording mosaic ->", args.record_mosaic)

                writer.write(mosaic)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                return 0

    finally:
        cam.close()
        if record_f is not None:
            record_f.close()
        if writer is not None:
            writer.release()
        ws.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
