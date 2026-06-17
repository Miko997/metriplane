# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np  # type: ignore

from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb_multi import USBMultiCamera
from metriplane.config import load_config, apply_profile_defaults, Config
from metriplane.mapping.planar_multi import MultiPlanarMapper, load_multi_planar_mapper
from metriplane.schema import CameraFrameModel, FrameStateModel, ObjectStateModel
from metriplane.streaming.ws_server import client_count
from metriplane.streaming.ws_thread import WsServerThread
from metriplane.metrics import MetricsRegistry, start_metrics_server
from metriplane.tracking import ObjectRegistry

from metriplane.fusion.fuse_xy import XYObs, fuse_average, fuse_weighted
from metriplane.fusion.kalman_cv import MultiObjectKalman

log = logging.getLogger("metriplane.run_fusion_preview")


def _as_int_list(v: Any) -> list[int] | None:
    if v is None:
        return None
    if isinstance(v, list):
        out: list[int] = []
        for x in v:
            try:
                out.append(int(x))
            except Exception:
                continue
        return out
    return None


def _filter_ids(cfg: Config, marker_id: int) -> bool:
    allow = _as_int_list(getattr(cfg, "allowed_marker_ids", None))
    deny = _as_int_list(getattr(cfg, "exclude_marker_ids", None))
    if allow is not None and marker_id not in allow:
        return False
    if deny is not None and marker_id in deny:
        return False
    return True


def _resolve_multi_mapper_from_cfg(cfg: Config) -> tuple[dict[str, int], MultiPlanarMapper]:
    if not cfg.cameras:
        raise ValueError("Fusion requires cfg.cameras list (cam0/cam1).")

    cameras: dict[str, int] = {}
    mapping_by_cam: dict[str, Path] = {}
    intr_by_cam: dict[str, Path | None] = {}

    for c in cfg.cameras:
        cid = str(c.name)
        if c.index is None:
            raise ValueError(f"CameraSpec {cid} missing index.")
        cameras[cid] = int(c.index)

        if not c.mapping_file:
            raise FileNotFoundError(f"{cid} missing mapping_file")
        mp = Path(str(c.mapping_file))
        if not mp.is_file():
            raise FileNotFoundError(f"{cid} mapping_file not found: {mp}")
        mapping_by_cam[cid] = mp

        ip: Path | None = Path(str(c.intrinsics_file)) if c.intrinsics_file else None
        intr_by_cam[cid] = ip if (ip is not None and ip.is_file()) else None

    mm = load_multi_planar_mapper(mapping_by_camera=mapping_by_cam, intrinsics_by_camera=intr_by_cam)
    return cameras, mm


def _parse_bounds(s: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bounds must be xmin,xmax,ymin,ymax")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def _world_to_px(x: float, y: float, *, xmin: float, xmax: float, ymin: float, ymax: float, scale: float) -> tuple[int, int]:
    px = int((x - xmin) * scale)
    py = int((ymax - y) * scale)  # invert y for topdown
    return (px, py)


def _blank(h: int, w: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _draw_grid(img: np.ndarray, xmin: float, xmax: float, ymin: float, ymax: float, scale: float, step_m: float = 0.1) -> None:
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


def run(cfg_path: Path, *, bounds: tuple[float, float, float, float], scale: float, record_mosaic: str | None) -> None:
    cfg = load_config(cfg_path)
    cfg = apply_profile_defaults(cfg)

    ws = WsServerThread(host=cfg.ws_host, port=cfg.ws_port)
    ws.start()

    metrics = MetricsRegistry()
    start_metrics_server(
        host=cfg.metrics_host,
        port=cfg.metrics_port,
        registry=metrics,
        get_ws_clients=client_count,
    )

    cameras, mm = _resolve_multi_mapper_from_cfg(cfg)

    backend = ArUcoBackend()
    cam = USBMultiCamera(cameras=cameras, require_all=True)

    # Fusion config (keep your working behavior)
    method = str(getattr(cfg, "fusion_method", "kalman")).lower().strip()
    if isinstance(getattr(cfg, "fusion", None), dict) and cfg.fusion.get("method"):
        method = str(cfg.fusion["method"]).lower().strip()

    if method in ("mean", "average"):
        method = "avg"

    base_meas_sigma = float(getattr(cfg, "fusion_meas_sigma", 0.03))
    process_sigma = float(getattr(cfg, "fusion_process_sigma", 0.8))
    timeout_s = float(getattr(cfg, "fusion_timeout_s", 2.0))

    if isinstance(getattr(cfg, "fusion", None), dict):
        f = cfg.fusion
        if "meas_sigma" in f:
            base_meas_sigma = float(f["meas_sigma"])
        if "process_sigma" in f:
            process_sigma = float(f["process_sigma"])
        if "timeout_s" in f:
            timeout_s = float(f["timeout_s"])

    kalman: MultiObjectKalman | None = None
    if method == "kalman":
        kalman = MultiObjectKalman(process_sigma=process_sigma, base_meas_sigma=base_meas_sigma, timeout_s=timeout_s)

    # Recording JSONL (same as before)
    record_f = None
    if cfg.record_jsonl:
        rp = Path(str(cfg.record_jsonl))
        rp.parent.mkdir(parents=True, exist_ok=True)
        record_f = rp.open("w", encoding="utf-8", buffering=1)
        log.info("recording jsonl -> %s", rp)

    # Mosaic recording (optional)
    writer = None
    if record_mosaic:
        outp = Path(record_mosaic)
        outp.parent.mkdir(parents=True, exist_ok=True)
        # We’ll init once we have the first mosaic frame

    registry = ObjectRegistry(timeout_s=float(cfg.object_timeout_s))
    frame_times: deque[float] = deque(maxlen=max(int(cfg.target_fps) * 2, 20))
    frame_id = 0
    frames_total = 0
    last_log = time.monotonic()

    xmin, xmax, ymin, ymax = bounds
    cam.open()
    try:
        while True:
            loop_start = time.monotonic()
            frames = cam.read()
            if len(frames) < len(cameras):
                time.sleep(0.002)
                continue

            frames_total += 1
            frame_id += 1

            ts_frame = max(float(fr.ts_cam_read) for fr in frames)

            raw_models: list[CameraFrameModel] = []
            meas_by_oid: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
            obs_for_fuse: dict[str, list[XYObs]] = defaultdict(list)
            raw_unique_ids: set[str] = set()

            # ---- Per-camera detect + map ----
            cam_vis: dict[str, np.ndarray] = {}
            for fr in frames:
                cid = str(fr.camera_id or "cam?")
                dets = backend.detect(fr)

                img = fr.image.copy()
                raw_objs: list[ObjectStateModel] = []

                for (mid, cx, cy) in dets:
                    if not _filter_ids(cfg, int(mid)):
                        continue

                    # draw marker center + id on the real camera frame
                    cv2.circle(img, (int(cx), int(cy)), 6, (0, 255, 0), -1)
                    cv2.putText(img, str(mid), (int(cx) + 8, int(cy) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                    xy = mm.pixel_to_world_xy(cid, float(cx), float(cy))
                    if xy is None:
                        continue
                    xw, yw = xy

                    rmse = mm.rmse_for(cid)
                    raw_unique_ids.add(str(mid))

                    raw_objs.append(
                        ObjectStateModel(
                            id=str(mid),
                            pos_world=(float(xw), float(yw), 0.0),
                            confidence=1.0,
                            extra={"px": (float(cx), float(cy)), "camera_id": cid, "cam_anchor_rmse": rmse},
                        )
                    )

                    obs_for_fuse[str(mid)].append(XYObs(camera_id=cid, x=float(xw), y=float(yw), confidence=1.0, rmse=rmse))
                    sigma = max(float(base_meas_sigma), float(rmse)) if (rmse is not None) else float(base_meas_sigma)
                    meas_by_oid[str(mid)].append((float(xw), float(yw), float(sigma)))

                cv2.putText(img, f"{cid}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255,255,255), 2)
                cam_vis[cid] = img
                raw_models.append(CameraFrameModel(camera_id=cid, ts_cam_read=float(fr.ts_cam_read), objects=raw_objs))

            # ---- Fuse ----
            fused_now: list[ObjectStateModel] = []
            if method == "avg":
                for oid, obs in obs_for_fuse.items():
                    xy = fuse_average(obs)
                    if xy is None:
                        continue
                    fused_now.append(ObjectStateModel(id=str(oid), pos_world=(float(xy[0]), float(xy[1]), 0.0), confidence=1.0))
            elif method == "weighted":
                for oid, obs in obs_for_fuse.items():
                    xy = fuse_weighted(obs)
                    if xy is None:
                        continue
                    fused_now.append(ObjectStateModel(id=str(oid), pos_world=(float(xy[0]), float(xy[1]), 0.0), confidence=1.0))
            else:
                if kalman is None:
                    raise RuntimeError("kalman selected but not initialized")
                states = kalman.update(ts=ts_frame, measurements=meas_by_oid)
                for oid, (x, y, vx, vy) in states.items():
                    fused_now.append(ObjectStateModel(id=str(oid), pos_world=(float(x), float(y), 0.0), vel_world=(float(vx), float(vy), 0.0), confidence=1.0))

            now_s = time.monotonic()
            registry.update(fused_now, now_s=now_s)
            tracked = registry.snapshot()

            # FPS estimate
            frame_times.append(time.monotonic())
            fps = 0.0
            if len(frame_times) >= 2:
                dt = frame_times[-1] - frame_times[0]
                if dt > 1e-6:
                    fps = float(len(frame_times) - 1) / dt

            metrics.update(fps=fps, objects_tracked=len(tracked), frames_total=frames_total)

            # Build topdown
            w = int(max(1.0, (xmax - xmin) * scale))
            h = int(max(1.0, (ymax - ymin) * scale))
            top = _blank(h, w)
            _draw_grid(top, xmin, xmax, ymin, ymax, scale)

            # draw board rectangle (your coordinate system!)
            bx0, by0 = _world_to_px(0.0, 0.0, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
            bx1, by1 = _world_to_px(1.10, 0.40, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
            cv2.rectangle(top, (min(bx0,bx1), min(by0,by1)), (max(bx0,bx1), max(by0,by1)), (255,255,255), 2)
            cv2.putText(top, "WORLD XY (meters)", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,255,255), 2)

            for o in tracked:
                pw = o.pos_world
                if not pw:
                    continue
                x, y = float(pw[0]), float(pw[1])
                px, py = _world_to_px(x, y, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, scale=scale)
                if 0 <= px < w and 0 <= py < h:
                    cv2.circle(top, (px, py), 6, (0, 200, 255), -1)
                    cv2.putText(top, str(o.id), (px + 7, py - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

            cv2.putText(top, f"fusion={method} fps={fps:.1f}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

            # Emit WS frame (for Omniverse + ROS2)
            ws_clients = client_count()
            msg = FrameStateModel(
                source_backend="aruco_fusion",
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
                    "fusion_method": method,
                    "raw_unique_ids": len(raw_unique_ids),
                    "fused_total": len(tracked),
                    "mapping_units": mm.units,
                    "cams": list(cameras.keys()),
                },
            )
            if record_f is not None:
                record_f.write(json.dumps(msg.model_dump(), ensure_ascii=False) + "\n")
            ws.send_frame(msg)

            # Show windows (REAL camera pixels + REAL topdown)
            if "cam0" in cam_vis:
                cv2.imshow("cam0", cam_vis["cam0"])
            if "cam1" in cam_vis:
                cv2.imshow("cam1", cam_vis["cam1"])
            cv2.imshow("topdown", top)

            # Optional mosaic video
            if record_mosaic:
                # stack into one big frame (cam0 | cam1) over topdown
                c0 = cam_vis.get("cam0", _blank(480, 640))
                c1 = cam_vis.get("cam1", _blank(480, 640))
                # resize topdown to width of two cams
                top_r = cv2.resize(top, (c0.shape[1] + c1.shape[1], c0.shape[0]))
                cams_row = np.hstack([c0, c1])
                mosaic = np.vstack([cams_row, top_r])

                if writer is None:
                    outp = Path(record_mosaic)
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(str(outp), fourcc, float(max(10.0, cfg.target_fps)), (mosaic.shape[1], mosaic.shape[0]))
                    log.info("recording mosaic -> %s", outp)

                writer.write(mosaic)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

            if (time.monotonic() - last_log) >= 1.0:
                log.info("fps=%.1f fused=%d ws=%d", fps, len(tracked), ws_clients)
                last_log = time.monotonic()

            # FPS cap
            if cfg.target_fps > 0:
                budget = 1.0 / float(cfg.target_fps)
                elapsed = time.monotonic() - loop_start
                sleep_s = budget - elapsed
                if sleep_s > 0:
                    time.sleep(min(sleep_s, 0.05))

    except KeyboardInterrupt:
        log.info("shutdown requested")
    finally:
        cam.close()
        ws.stop()
        if record_f is not None:
            record_f.close()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    ap = argparse.ArgumentParser(description="Fusion + preview (cam0/cam1/topdown) in ONE process.")
    ap.add_argument("config", type=Path)
    ap.add_argument("--bounds", default="-0.05,1.15,-0.05,0.45")
    ap.add_argument("--scale", type=float, default=700.0)
    ap.add_argument("--record-mosaic", default=None, help="Optional output mp4 containing cam0+cam1+topdown")
    args = ap.parse_args()

    bounds = _parse_bounds(args.bounds)
    run(args.config, bounds=bounds, scale=float(args.scale), record_mosaic=args.record_mosaic)


if __name__ == "__main__":
    main()
