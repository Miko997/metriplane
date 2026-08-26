# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import inspect
import logging
import os
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import cv2  # type: ignore

from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.usb_multi import USBMultiCamera
from metriplane.compute.select import select_fusion_backend
from metriplane.config import Config, apply_profile_defaults, load_config
from metriplane.fusion.fuse_xy import XYObs, fuse_average, fuse_weighted
from metriplane.fusion.kalman_cv import MultiObjectKalman
from metriplane.mapping.planar_multi import MultiPlanarMapper, load_multi_planar_mapper
from metriplane.metrics import MetricsRegistry, start_metrics_server
from metriplane.observability.timing import StageTiming
from metriplane.paths import (
    PlatformPaths,
    normalize_runs_dir,
)
from metriplane.provenance.run_provenance import (
    JsonlWriter,
    RunContext,
    create_run_context,
    open_jsonl_writer,
)
from metriplane.run_ids import validate_portable_run_id
from metriplane.schema import CameraFrameModel, FrameStateModel, ObjectStateModel
from metriplane.streaming.ws_server import client_count
from metriplane.streaming.ws_thread import WsServerThread
from metriplane.time.clock import Clock, RealTimeClock
from metriplane.tracking import ObjectRegistry
from metriplane.zone_analytics import ZoneAnalytics
from metriplane.zones import load_zones

try:
    from metriplane.preview.live_preview import LivePreview
except Exception:  # pragma: no cover
    LivePreview = None  # type: ignore

log = logging.getLogger("metriplane.run_fusion")


# -----------------------------
# M9.3: Health model (self-contained)
# -----------------------------
class HealthStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


_STATUS_RANK: dict[HealthStatus, int] = {
    HealthStatus.OK: 2,
    HealthStatus.DEGRADED: 1,
    HealthStatus.FAILED: 0,
}


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    last_ok_ts_ns: int | None
    last_error_ts_ns: int | None
    last_error: str | None


class HealthRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._components: dict[str, ComponentHealth] = {}
        self._started_ns = time.time_ns()

    def _now_ns(self) -> int:
        return time.time_ns()

    def _upsert(self, name: str, *, status: HealthStatus, err: str | None = None) -> None:
        now = self._now_ns()
        with self._lock:
            prev = self._components.get(name)
            last_ok = prev.last_ok_ts_ns if prev else None
            last_err = prev.last_error_ts_ns if prev else None
            last_err_msg = prev.last_error if prev else None

            if status == HealthStatus.OK:
                last_ok = now
            else:
                last_err = now
                last_err_msg = err or last_err_msg

            self._components[name] = ComponentHealth(
                name=name,
                status=status,
                last_ok_ts_ns=last_ok,
                last_error_ts_ns=last_err,
                last_error=last_err_msg,
            )

    def set_ok(self, name: str) -> None:
        self._upsert(str(name), status=HealthStatus.OK)

    def set_degraded(self, name: str, err: str) -> None:
        self._upsert(str(name), status=HealthStatus.DEGRADED, err=str(err))

    def set_failed(self, name: str, err: str) -> None:
        self._upsert(str(name), status=HealthStatus.FAILED, err=str(err))

    def snapshot(self) -> dict[str, Any]:
        now = self._now_ns()
        with self._lock:
            comps = dict(self._components)

        if comps:
            worst_rank = min(_STATUS_RANK[c.status] for c in comps.values())
            overall = {2: HealthStatus.OK, 1: HealthStatus.DEGRADED, 0: HealthStatus.FAILED}[worst_rank]
        else:
            overall = HealthStatus.OK

        comp_out: dict[str, Any] = {}
        for name in sorted(comps.keys()):
            c = comps[name]
            comp_out[name] = {
                "status": c.status.value,
                "last_ok_ts_ns": c.last_ok_ts_ns,
                "last_error_ts_ns": c.last_error_ts_ns,
                "last_error": c.last_error,
            }

        return {
            "overall": overall.value,
            "ts_ns": now,
            "uptime_s": float(max(0, now - self._started_ns)) / 1e9,
            "components": comp_out,
        }


def _parse_faults(fault_args: list[str] | None, env_fallback: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    items: list[str] = []

    if fault_args:
        items.extend([str(x).strip() for x in fault_args if str(x).strip()])
    if env_fallback:
        for part in str(env_fallback).split(","):
            p = part.strip()
            if p:
                items.append(p)

    for it in items:
        if "=" in it:
            k, v = it.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                out[k] = v
        else:
            out[it.strip()] = "1"
    return out


def _coerce_float(v: str | None, default: float) -> float:
    if v is None:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


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


def _resolve_multi_mapper_from_cfg(
    cfg: Config,
    *,
    health: HealthRegistry | None = None,
) -> tuple[dict[str, int | str], MultiPlanarMapper, list[str]]:
    """
    Uses cfg.cameras (tuple[CameraSpec]) and expects each CameraSpec has mapping_file filled.
    apply_profile_defaults(cfg) is responsible for filling those from profile cam0/cam1 folders.

    M9.3 change: If a camera mapping is missing, we DO NOT crash.
    We skip that camera, mark health mapping.<cam> as FAILED, and continue with remaining.
    """
    if not cfg.cameras:
        raise ValueError("Fusion requires cfg.cameras list (cam0/cam1).")

    cameras: dict[str, int | str] = {}
    mapping_by_cam: dict[str, Path] = {}
    intr_by_cam: dict[str, Path | None] = {}
    skipped: list[str] = []

    # stable order
    cams_sorted = sorted(list(cfg.cameras), key=lambda c: str(getattr(c, "name", "")))

    for c in cams_sorted:
        cid = str(c.name)

        # Prefer stable device path if provided; fallback to index.
        dev: int | str | None
        if getattr(c, "device", None):
            dev = str(c.device)
        elif getattr(c, "index", None) is not None:
            dev = int(c.index)
        else:
            skipped.append(cid)
            if health is not None:
                health.set_failed(f"camera.{cid}", "missing both device and index")
            log.warning("cam=%s skipped: missing both device and index", cid)
            continue

        # mapping file
        mp_raw = getattr(c, "mapping_file", None)
        if not mp_raw:
            skipped.append(cid)
            if health is not None:
                health.set_failed(f"mapping.{cid}", "missing mapping_file")
            log.warning("cam=%s skipped: missing mapping_file", cid)
            continue

        mp = Path(str(mp_raw))
        if not mp.is_file():
            skipped.append(cid)
            if health is not None:
                health.set_failed(f"mapping.{cid}", f"mapping_file not found: {mp}")
            log.warning("cam=%s skipped: mapping_file not found: %s", cid, mp)
            continue

        cameras[cid] = dev
        mapping_by_cam[cid] = mp

        ip: Path | None = Path(str(c.intrinsics_file)) if getattr(c, "intrinsics_file", None) else None
        intr_by_cam[cid] = ip if (ip is not None and ip.is_file()) else None

        if health is not None:
            health.set_ok(f"camera.{cid}")
            health.set_ok(f"mapping.{cid}")

    if not mapping_by_cam:
        raise FileNotFoundError("No usable cameras: all mapping files missing/invalid.")

    mm: MultiPlanarMapper = load_multi_planar_mapper(
        mapping_by_camera=mapping_by_cam,
        intrinsics_by_camera=intr_by_cam,
    )
    return cameras, mm, skipped


def _fusion_cfg(cfg: Config) -> dict[str, Any]:
    f = getattr(cfg, "fusion", None)
    return dict(f) if isinstance(f, dict) else {}


def _update_camera_capture_health(
    *,
    capture_status: dict[str, dict[str, float | int | bool]],
    expected_camera_ids: list[str],
    health: HealthRegistry,
    fail_after_s: float,
    target_fps: float,
) -> dict[str, HealthStatus]:
    """Update camera health from capture age, not runner polling frequency."""
    fail_after = max(0.01, float(fail_after_s))
    nominal_period = 1.0 / max(1.0, float(target_fps))
    degraded_after = min(fail_after * 0.5, max(0.25, nominal_period * 3.0))
    result: dict[str, HealthStatus] = {}

    for camera_id in expected_camera_ids:
        item = capture_status.get(camera_id) or {}
        age_s = max(0.0, float(item.get("capture_age_s", fail_after)))
        has_frame = bool(item.get("has_frame", False))
        component = f"camera.{camera_id}"
        if age_s >= fail_after:
            status = HealthStatus.FAILED
            health.set_failed(component, f"capture stalled for {age_s:.2f}s")
        elif not has_frame:
            status = HealthStatus.DEGRADED
            health.set_degraded(component, f"waiting for first capture ({age_s:.2f}s)")
        elif age_s >= degraded_after:
            status = HealthStatus.DEGRADED
            health.set_degraded(component, f"last capture {age_s:.2f}s ago")
        else:
            status = HealthStatus.OK
            health.set_ok(component)
        result[camera_id] = status

    return result


def _close_fusion_resources(
    *,
    preview: Any = None,
    camera: Any = None,
    websocket: Any = None,
    metrics_server: Any = None,
    recorder: Any = None,
    timing: Any = None,
) -> None:
    """Best-effort, idempotent cleanup for setup and runtime failures."""
    for resource, method in (
        (preview, "close"),
        (camera, "close"),
        (websocket, "stop"),
        (metrics_server, "shutdown"),
        (metrics_server, "server_close"),
        (recorder, "close"),
        (timing, "close"),
    ):
        if resource is None:
            continue
        try:
            getattr(resource, method)()
        except Exception:
            log.debug("cleanup failed for %s.%s", type(resource).__name__, method, exc_info=True)


@dataclass
class _FusionResources:
    preview: Any = None
    camera: Any = None
    websocket: Any = None
    metrics_server: Any = None
    recorder: Any = None
    timing: Any = None


def run_loop_fusion(
    cfg: Config,
    *,
    clock: Clock | None = None,
    fault_args: list[str] | None = None,
    config_path: Path | None = None,
    argv: list[str] | None = None,
    run_id: str | None = None,
    runs_dir: str | None = None,
    duration_s: float = 0.0,
    paths: PlatformPaths | None = None,
) -> int:
    candidate_run_id = str(run_id or os.getenv("METRIPLANE_RUN_ID") or "")
    if candidate_run_id.strip():
        try:
            validate_portable_run_id(candidate_run_id)
        except ValueError as exc:
            log.error("run storage unavailable: %s", exc)
            return 2

    effective_runs_dir = normalize_runs_dir(runs_dir)
    configured_runs_dir = normalize_runs_dir(cfg.runs_dir)
    if effective_runs_dir is None:
        effective_runs_dir = configured_runs_dir
    if effective_runs_dir is None:
        if paths is not None:
            effective_runs_dir = str(paths.runs_dir)
    resources = _FusionResources()
    try:
        return _run_loop_fusion_impl(
            cfg,
            clock=clock,
            fault_args=fault_args,
            config_path=config_path,
            argv=argv,
            run_id=run_id,
            runs_dir=effective_runs_dir,
            duration_s=duration_s,
            _resources=resources,
        )
    finally:
        _close_fusion_resources(
            preview=resources.preview,
            camera=resources.camera,
            websocket=resources.websocket,
            metrics_server=resources.metrics_server,
            recorder=resources.recorder,
            timing=resources.timing,
        )


def _run_loop_fusion_impl(
    cfg: Config,
    *,
    clock: Clock | None = None,
    fault_args: list[str] | None = None,
    config_path: Path | None = None,
    argv: list[str] | None = None,
    run_id: str | None = None,
    runs_dir: str | None = None,
    duration_s: float = 0.0,
    _resources: _FusionResources,
) -> int:
    if clock is None:
        clock = RealTimeClock()
    # Fill per-camera mapping/intrinsics from profile/cam0 + cam1 if missing.
    preview = None
    if os.getenv("METRIPLANE_SHOW_PREVIEW", "0") == "1" and LivePreview is not None:
        preview = LivePreview(scale=float(os.getenv("METRIPLANE_PREVIEW_SCALE", "1.0")))
        _resources.preview = preview

    cfg = apply_profile_defaults(cfg)

    # M9.4: run provenance (FAIL FAST if we cannot create it)
    try:
        ctx: RunContext = create_run_context(
            cfg,
            config_path=config_path,
            argv=argv,
            run_id=run_id,
            runs_dir=runs_dir,
        )
    except (OSError, ValueError) as exc:
        log.error("run storage unavailable: %s", exc)
        return 2

    mirror_path = str(cfg.record_jsonl) if cfg.record_jsonl else None
    mirror_enabled = bool(mirror_path)
    try:
        recorder: JsonlWriter = open_jsonl_writer(
            primary_path=ctx.session_jsonl,
            mirror_path=mirror_path,
        )
    except Exception as e:
        if mirror_path:
            log.warning(
                "M9.4 recorder: failed to open mirror_path=%s (%s); continuing without mirror",
                mirror_path,
                e,
            )
            mirror_enabled = False
            recorder = open_jsonl_writer(primary_path=ctx.session_jsonl, mirror_path=None)
        else:
            raise
    _resources.recorder = recorder

    recorder.write(ctx.header_record())
    log.info("M9.4 provenance: run_id=%s dir=%s config_hash=%s", ctx.run_id, ctx.run_dir, ctx.config_hash)
    log.info("M9.4 recorder paths: %s", ", ".join(str(p) for p in recorder.paths))

    # M9.5 timing
    # ---- M9.5 timing (UPDATED: per-camera detect/map stages) ----
    tcfg = getattr(cfg, "timing", None)
    if not isinstance(tcfg, dict):
        tcfg = {}

    env_timing = os.getenv("METRIPLANE_TIMING") or os.getenv("METRIPLANE_TIMING")
    timing_enabled = bool(tcfg.get("enabled", tcfg.get("enable", False))) or (
        str(env_timing).strip().lower() in ("1", "true", "yes", "on")
    )

    cam_names = sorted({str(c.name) for c in (cfg.cameras or ())})
    cam_stages: list[str] = []
    for cid in cam_names:
        cam_stages.append(f"detect.{cid}")
        cam_stages.append(f"map.{cid}")

    timing = StageTiming(
        enabled=timing_enabled,
        stages=[
            "camera.read",
            "preview",
            *cam_stages,
            "fuse",
            "tracking",
            "zones",
            "build.msg",
            "record.jsonl",
            "ws.send",
            "sleep",
        ],
        frames_csv_path=ctx.run_dir / "latency_frames.csv",
        summary_csv_path=ctx.run_dir / "latency_summary.csv",
        flush_every=int(os.getenv("METRIPLANE_TIMING_FLUSH_EVERY", "250")),
        run_id=ctx.run_id,
        config_hash=ctx.config_hash,
        git_commit=ctx.git.commit,
    )
    _resources.timing = timing

    if timing_enabled:
        log.info("M9.5 timing: ENABLED frames_csv=%s summary_csv=%s", ctx.run_dir / "latency_frames.csv", ctx.run_dir / "latency_summary.csv")
    else:
        log.info("M9.5 timing: DISABLED (set METRIPLANE_TIMING=1 or timing.enabled=true)")

    hcfg = getattr(cfg, "health", None) or {}
    health_enabled = bool(hcfg.get("enabled", hcfg.get("enable", True)))  # default True to match metriplane.run
    health = HealthRegistry()

    # M9.6: compute backend selection (CPU NumPy by default; optional GPU via CuPy)
    compute_backend = select_fusion_backend(
        getattr(cfg, "compute", None), logger=log, health=health
    )
    log.info("M9.6 compute backend: %s", compute_backend.name)

    health.set_ok("process")
    health.set_ok("recorder.jsonl")
    if (not mirror_enabled) and mirror_path:
        health.set_degraded("recorder.jsonl", f"mirror disabled (failed to open): {mirror_path}")

    faults = _parse_faults(fault_args, os.getenv("METRIPLANE_FAULT") or os.getenv("METRIPLANE_FAULT"))
    cam1_disconnect_after_s = _coerce_float(faults.get("cam1_disconnect_after_s"), -1.0)
    ws_fail_after_s = _coerce_float(faults.get("ws_fail_after_s"), -1.0)

    # thresholds for marking camera missing as FAILED
    cam_missing_fail_after_s = _coerce_float(
        str(getattr(cfg, "health_cam_missing_fail_after_s", ""))
        if getattr(cfg, "health_cam_missing_fail_after_s", None) is not None
        else None,
        2.0,
    )

    t0_mon = time.monotonic()
    cam1_fault_triggered = False
    ws_fault_triggered = False

    log.info("fusion run loop started")
    log.info("profile=%s cameras=%s", cfg.profile, [c.name for c in (cfg.cameras or ())])
    for c in (cfg.cameras or ()):
        log.info(
            "cam=%s index=%s mapping=%s intrinsics=%s",
            c.name,
            c.index,
            c.mapping_file,
            c.intrinsics_file,
        )

    ws = WsServerThread(host=cfg.ws_host, port=cfg.ws_port)
    _resources.websocket = ws
    try:
        ws.start()
        health.set_ok("ws")
    except Exception as e:
        health.set_failed("ws", f"{type(e).__name__}: {e}")
        raise

    metrics = MetricsRegistry()

    start_kwargs: dict[str, Any] = dict(
        host=cfg.metrics_host,
        port=cfg.metrics_port,
        registry=metrics,
        get_ws_clients=client_count,
    )

    # Only expose /health if enabled
    if health_enabled and "get_health" in inspect.signature(start_metrics_server).parameters:
        start_kwargs["get_health"] = health.snapshot

    metrics_server = start_metrics_server(**start_kwargs)
    _resources.metrics_server = metrics_server

    health.set_ok("http.metrics")
    log.info("metrics at http://%s:%d/metrics", cfg.metrics_host, cfg.metrics_port)
    if health_enabled:
        log.info("health  at http://%s:%d/health", cfg.metrics_host, cfg.metrics_port)
    else:
        log.info("health  DISABLED (set health.enabled=true to enable)")

    cameras, mm, skipped = _resolve_multi_mapper_from_cfg(cfg, health=health)
    if skipped:
        health.set_degraded("fusion", f"skipped cameras: {','.join(sorted(skipped))}")
        log.warning("fusion: skipped cameras due to missing mapping/device: %s", ",".join(sorted(skipped)))
    else:
        health.set_ok("fusion")

    expected_cam_ids = sorted(list(cameras.keys()))

    # Zones (shared)
    zone_analytics: ZoneAnalytics | None = None
    if cfg.zones_file:
        zp = Path(str(cfg.zones_file))
        if zp.is_file():
            zone_analytics = ZoneAnalytics(load_zones(zp))
            health.set_ok("zones")
        else:
            health.set_degraded("zones", f"zones_file not found: {zp}")

    backend = ArUcoBackend()

    # Critical for M9.3: allow partial camera availability; do NOT deadlock on require_all=True
    cam = USBMultiCamera(
        cameras=cameras,
        width=640,
        height=480,
        fps=int(cfg.target_fps or 30),
        fourcc="MJPG",
        require_all=False,
    )
    _resources.camera = cam

    # -----------------------------
    # Fusion config (authoritative: cfg.fusion dict)
    # -----------------------------
    fcfg = _fusion_cfg(cfg)

    method_raw = fcfg.get("method") or getattr(cfg, "fusion_method", None) or "kalman"
    method = str(method_raw).lower().strip()

    if method in ("mean", "average"):
        method = "avg"
    if method in ("best", "best_conf", "best_rmse"):
        method = "nearest"
    if method not in ("avg", "weighted", "nearest", "kalman"):
        raise ValueError(f"Unsupported fusion method '{method}'. Use avg|weighted|nearest|kalman.")

    z_world = _coerce_float(str(fcfg.get("z_world")) if fcfg.get("z_world") is not None else None, 0.0)

    base_meas_sigma = _coerce_float(
        str(fcfg.get("meas_sigma") if fcfg.get("meas_sigma") is not None else fcfg.get("base_meas_sigma"))
        if (fcfg.get("meas_sigma") is not None or fcfg.get("base_meas_sigma") is not None)
        else None,
        0.03,
    )
    process_sigma = _coerce_float(str(fcfg.get("process_sigma")) if fcfg.get("process_sigma") is not None else None, 0.8)
    timeout_s = _coerce_float(str(fcfg.get("timeout_s")) if fcfg.get("timeout_s") is not None else None, 2.0)

    if not fcfg:
        base_meas_sigma = _coerce_float(
            str(getattr(cfg, "fusion_meas_sigma", None)) if getattr(cfg, "fusion_meas_sigma", None) is not None else None,
            base_meas_sigma,
        )
        process_sigma = _coerce_float(
            str(getattr(cfg, "fusion_process_sigma", None)) if getattr(cfg, "fusion_process_sigma", None) is not None else None,
            process_sigma,
        )
        timeout_s = _coerce_float(
            str(getattr(cfg, "fusion_timeout_s", None)) if getattr(cfg, "fusion_timeout_s", None) is not None else None,
            timeout_s,
        )

    if fcfg.get("sync_window_s") is not None:
        sync_window_s = _coerce_float(str(fcfg.get("sync_window_s")), 0.05)
    else:
        if cfg.target_fps and cfg.target_fps > 0:
            sync_window_s = float(1.5 / float(cfg.target_fps))
        else:
            sync_window_s = 0.05

    kalman: MultiObjectKalman | None = None
    if method == "kalman":
        kalman = MultiObjectKalman(
            process_sigma=float(process_sigma),
            base_meas_sigma=float(base_meas_sigma),
            timeout_s=float(timeout_s),
        )

    registry = ObjectRegistry(timeout_s=float(cfg.object_timeout_s))
    frame_times: deque[float] = deque(maxlen=max(int(cfg.target_fps) * 2, 20))
    frame_id = 0
    frames_total = 0
    last_log = time.monotonic()

    det = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100),
        cv2.aruco.DetectorParameters(),
    )

    try:
        cam.open()
        health.set_ok("camera.open")
        t_start = time.monotonic()
        while True:
            if duration_s and (time.monotonic() - t_start) >= duration_s:
                break

            loop_start = time.monotonic()

            # ---- camera.read timing measured outside begin_frame ----
            t_read0 = time.perf_counter_ns()
            try:
                frames = cam.read() or []
                read_ns = time.perf_counter_ns() - t_read0
            except Exception as e:
                health.set_degraded("camera.read", f"{type(e).__name__}: {e}")
                time.sleep(0.01)
                continue

            capture_health = _update_camera_capture_health(
                capture_status=cam.capture_status(now_monotonic=time.monotonic()),
                expected_camera_ids=expected_cam_ids,
                health=health,
                fail_after_s=cam_missing_fail_after_s,
                target_fps=float(cfg.target_fps or 30),
            )

            frames_by_cam: dict[str, Any] = {}
            for fr in frames:
                cid = str(getattr(fr, "camera_id", "") or "")
                if not cid:
                    continue
                frames_by_cam[cid] = fr

            if cam1_disconnect_after_s > 0 and (time.monotonic() - t0_mon) >= cam1_disconnect_after_s:
                if "cam1" in frames_by_cam:
                    frames_by_cam.pop("cam1", None)
                if not cam1_fault_triggered:
                    cam1_fault_triggered = True
                health.set_failed(
                    "camera.cam1",
                    f"fault injected: cam1_disconnect_after_s={cam1_disconnect_after_s}",
                )

            preview_ns = 0
            if preview is not None:
                t_prev0 = time.perf_counter_ns()
                img_by_cam = {}
                for cid, fr in frames_by_cam.items():
                    if getattr(fr, "image", None) is None:
                        continue
                    vis = fr.image.copy()
                    try:
                        gray = cv2.cvtColor(vis, cv2.COLOR_BGR2GRAY)
                        corners, ids, _ = det.detectMarkers(gray)
                        if ids is not None and len(ids) > 0:
                            cv2.aruco.drawDetectedMarkers(vis, corners, ids)
                    except Exception:
                        pass
                    img_by_cam[cid] = vis

                preview.render_cam("Metriplane cam0", img_by_cam.get("cam0"))
                preview.render_cam("Metriplane cam1", img_by_cam.get("cam1"))
                if not preview.tick():
                    break
                preview_ns = time.perf_counter_ns() - t_prev0

            if not frames_by_cam:
                if capture_health and all(s == HealthStatus.FAILED for s in capture_health.values()):
                    health.set_failed("camera.read", "all camera captures stalled")
                elif any(s != HealthStatus.OK for s in capture_health.values()):
                    health.set_degraded("camera.read", "waiting for fresh camera capture")
                time.sleep(0.005)
                continue

            health.set_ok("camera.read")

            frames_total += 1
            frame_id += 1

            try:
                ts_frame = max(float(getattr(fr, "ts_cam_read", 0.0)) for fr in frames_by_cam.values())
            except Exception:
                ts_frame = time.time()

            ts_sim_ns = int(clock.now_ns())

            # ---- begin per-frame timing (M9.5) ----
            timing.begin_frame(ts=float(ts_frame), frame_id=int(frame_id))
            timing.add_stage_ns("camera.read", int(read_ns))
            if preview_ns > 0:
                timing.add_stage_ns("preview", int(preview_ns))

            raw_models: list[CameraFrameModel] = []
            meas_by_oid: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
            obs_for_fuse: dict[str, list[XYObs]] = defaultdict(list)
            raw_unique_ids: set[str] = set()
            stale_cams: list[str] = []

            # UPDATED: split detect+map into detect.<cid> + map.<cid>
            for cid in sorted(frames_by_cam.keys()):
                fr = frames_by_cam[cid]

                age_s = float(ts_frame - float(getattr(fr, "ts_cam_read", ts_frame)))
                is_stale = age_s > float(sync_window_s)
                if is_stale:
                    stale_cams.append(cid)

                skip_stale = bool(fcfg.get("skip_stale_cams", True))
                if is_stale and skip_stale:
                    # record that we skipped, but don't do detect/map
                    raw_models.append(
                        CameraFrameModel(
                            camera_id=cid,
                            ts_cam_read=float(getattr(fr, "ts_cam_read", ts_frame)),
                            objects=[],
                            metrics={
                                "age_s": age_s,
                                "stale_for_fusion": True,
                                "dets": 0,
                                "dets_kept": 0,
                                "dets_mapped": 0,
                                "dets_used_for_fusion": 0,
                                "cam_anchor_rmse": mm.rmse_for(cid),
                                "skipped_reason": "stale",
                            },
                        )
                    )
                    continue

                # ---- detect.<cid> ----
                with timing.stage(f"detect.{cid}"):
                    dets = backend.detect(fr) or []

                try:
                    dets = sorted(list(dets), key=lambda d: int(d[0]))
                except Exception:
                    dets = list(dets)

                # Compute once per camera (avoid repeated call inside loop)
                rmse = mm.rmse_for(cid)

                raw_objs: list[ObjectStateModel] = []

                dets_raw = int(len(dets))
                dets_kept = 0
                dets_mapped = 0
                dets_used_for_fusion = 0

                # ---- map.<cid> ----
                with timing.stage(f"map.{cid}"):
                    for (mid, cx, cy) in dets:
                        if not _filter_ids(cfg, int(mid)):
                            continue
                        dets_kept += 1

                        xy = mm.pixel_to_world_xy(cid, float(cx), float(cy))
                        if xy is None:
                            continue
                        dets_mapped += 1

                        xw, yw = xy
                        raw_unique_ids.add(str(mid))

                        raw_objs.append(
                            ObjectStateModel(
                                id=str(mid),
                                pos_world=(float(xw), float(yw), float(z_world)),
                                confidence=1.0,
                                extra={
                                    "px": (float(cx), float(cy)),
                                    "camera_id": cid,
                                    "cam_anchor_rmse": rmse,
                                    "cam_age_s": age_s,
                                    "cam_stale_for_fusion": bool(is_stale),
                                },
                            )
                        )

                        if not is_stale:
                            dets_used_for_fusion += 1
                            obs_for_fuse[str(mid)].append(
                                XYObs(camera_id=cid, x=float(xw), y=float(yw), confidence=1.0, rmse=rmse)
                            )
                            sigma = (
                                max(float(base_meas_sigma), float(rmse))
                                if (rmse is not None)
                                else float(base_meas_sigma)
                            )
                            meas_by_oid[str(mid)].append((float(xw), float(yw), float(sigma)))

                raw_models.append(
                    CameraFrameModel(
                        camera_id=cid,
                        ts_cam_read=float(getattr(fr, "ts_cam_read", ts_frame)),
                        objects=raw_objs,
                        metrics={
                            "age_s": age_s,
                            "stale_for_fusion": bool(is_stale),

                            # Keep old field for compatibility
                            "dets": dets_raw,

                            # NEW: more actionable breakdown
                            "dets_kept": int(dets_kept),
                            "dets_mapped": int(dets_mapped),
                            "dets_used_for_fusion": int(dets_used_for_fusion),

                            # Helpful for correlating with mapping quality
                            "cam_anchor_rmse": rmse,
                        },
                    )
                )


            fused_now: list[ObjectStateModel] = []
            with timing.stage("fuse"):
                if method in ("avg", "weighted"):
                    xy_by_oid = compute_backend.fuse_xy(obs_for_fuse, method=method)
                    for oid in sorted(xy_by_oid.keys()):
                        x, y = xy_by_oid[str(oid)]
                        obs = obs_for_fuse.get(str(oid), [])
                        fused_now.append(
                            ObjectStateModel(
                                id=str(oid),
                                pos_world=(float(x), float(y), float(z_world)),
                                confidence=1.0,
                                extra={"fusion": {"method": method, "sources": [o.camera_id for o in obs]}},
                            )
                        )
                         

                elif method == "nearest":
                    def _score(o: XYObs, eps: float = 1e-9) -> float:
                        w = float(o.confidence) if o.confidence is not None else 1.0
                        if o.rmse is not None and o.rmse > 0:
                            w *= 1.0 / ((float(o.rmse) ** 2) + eps)
                        return float(w)

                    for oid in sorted(obs_for_fuse.keys()):
                        obs = obs_for_fuse[oid]
                        if not obs:
                            continue
                        best = max(obs, key=_score)
                        fused_now.append(
                            ObjectStateModel(
                                id=str(oid),
                                pos_world=(float(best.x), float(best.y), float(z_world)),
                                confidence=float(best.confidence) if best.confidence is not None else 1.0,
                                extra={"fusion": {"method": "nearest", "source": best.camera_id}},
                            )
                        )

                elif method == "kalman":
                    if kalman is None:
                        raise RuntimeError("fusion method 'kalman' selected but filter not initialized")

                    meas_sorted: dict[str, list[tuple[float, float, float]]] = {
                        k: meas_by_oid[k] for k in sorted(meas_by_oid.keys())
                    }
                    states = kalman.update(ts=ts_frame, measurements=meas_sorted)
                    for oid in sorted(states.keys()):
                        x, y, vx, vy = states[oid]
                        fused_now.append(
                            ObjectStateModel(
                                id=str(oid),
                                pos_world=(float(x), float(y), float(z_world)),
                                vel_world=(float(vx), float(vy), 0.0),
                                confidence=1.0,
                                extra={"fusion": {"method": "kalman", "sensors": len(meas_by_oid.get(oid, []))}},
                            )
                        )

            with timing.stage("tracking"):
                now_s = time.monotonic()
                registry.update(fused_now, now_s=now_s)
                tracked = registry.snapshot()

            with timing.stage("zones"):
                if zone_analytics is not None:
                    tracked_out, events = zone_analytics.update(ts_frame, tracked)
                else:
                    tracked_out, events = tracked, []

            # Stable ordering (demo + audit requirement)
            try:
                tracked_out = sorted(list(tracked_out), key=lambda o: str(getattr(o, "id", "")))
            except Exception:
                pass

            frame_times.append(time.monotonic())
            fps = 0.0
            if len(frame_times) >= 2:
                dt = frame_times[-1] - frame_times[0]
                if dt > 1e-6:
                    fps = float(len(frame_times) - 1) / dt

            ws_clients = client_count()
            metrics.update(fps=fps, objects_tracked=len(tracked_out), frames_total=frames_total)

            raw_total = sum(len(r.objects) for r in raw_models)
            fused_total = len(fused_now)
            denom = max(len(raw_unique_ids), 1)
            coverage_frame = float(fused_total) / float(denom)

            with timing.stage("build.msg"):
                msg = FrameStateModel(
                    run_id=ctx.run_id,
                    config_hash=ctx.config_hash,
                    git_commit=ctx.git.commit,
                    source_backend="aruco_fusion",
                    ts=float(ts_frame),
                    ts_sim_ns=int(ts_sim_ns),
                    frame_id=int(frame_id),
                    objects=tracked_out,
                    fused=tracked_out,
                    raw_per_camera=raw_models,
                    events=events,
                    metrics={
                        "fps": fps,
                        "frames_total": frames_total,
                        "ws_clients_connected": ws_clients,
                        "fusion_method": method,
                        "compute_backend": compute_backend.name,
                        "fusion_base_meas_sigma": float(base_meas_sigma),
                        "fusion_process_sigma": float(process_sigma),
                        "fusion_timeout_s": float(timeout_s),
                        "fusion_sync_window_s": float(sync_window_s),
                        "stale_cams": sorted(list(set(stale_cams))),
                        "raw_total": raw_total,
                        "raw_unique_ids": len(raw_unique_ids),
                        "fused_total": fused_total,
                        "coverage_frame": coverage_frame,
                        "mapping_units": mm.units,
                        "cams": expected_cam_ids,
                    },
                )

                with timing.stage("record.jsonl"):
                    try:
                        recorder.write(msg.model_dump())
                        health.set_ok("recorder.jsonl")
                    except Exception as e:
                        health.set_failed(
                            "recorder.jsonl",
                            f"write failed: {type(e).__name__}: {e}",
                        )
                        return 1

                with timing.stage("ws.send"):
                    try:
                        if (not ws_fault_triggered) and ws_fail_after_s > 0 and (time.monotonic() - t0_mon) >= ws_fail_after_s:
                            ws_fault_triggered = True
                            raise RuntimeError(f"fault injected: ws_fail_after_s={ws_fail_after_s}")
                        ws.send_frame(msg)
                        health.set_ok("ws.send")
                    except Exception as e:
                        health.set_degraded("ws.send", f"{type(e).__name__}: {e}")

            if (time.monotonic() - last_log) >= 1.0:
                log.info(
                    "fps=%.1f raw=%d unique=%d fused=%d coverage=%.2f method=%s stale=%s ws=%d cams=%s",
                    fps,
                    raw_total,
                    len(raw_unique_ids),
                    fused_total,
                    coverage_frame,
                    method,
                    ",".join(sorted(set(stale_cams))) if stale_cams else "-",
                    ws_clients,
                    ",".join(expected_cam_ids) if expected_cam_ids else "-",
                )
                last_log = time.monotonic()

            if cfg.target_fps > 0:
                budget = 1.0 / float(cfg.target_fps)
                elapsed = time.monotonic() - loop_start
                sleep_s = budget - elapsed
                if sleep_s > 0:
                    with timing.stage("sleep"):
                        time.sleep(min(sleep_s, 0.05))

            timing.end_frame()

    except KeyboardInterrupt:
        log.info("shutdown requested")
    return 0



def main(argv=None, *, paths: PlatformPaths | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Metriplane fusion runner")
    ap.add_argument("--config", "-c", default="config.example.yaml", help="Path to YAML config")
    ap.add_argument("--run-id", default=None, help="Optional run id override (otherwise auto).")
    ap.add_argument(
        "--runs-dir",
        default=None,
        help="Override runs base dir (default: platform runs directory).",
    )
    ap.add_argument(
        "--fault",
        action="append",
        default=[],
        help="Fault injection (repeatable), e.g. --fault cam1_disconnect_after_s=8 --fault ws_fail_after_s=12. "
        "Also supports env METRIPLANE_FAULT='k=v,k2=v2'.",
    )
    ap.add_argument("--duration-s", type=float, default=0.0, help="Stop after N seconds (0=forever).")

    argv_in = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(argv_in)

    cfg = load_config(Path(args.config))
    return run_loop_fusion(
        cfg,
        fault_args=list(args.fault or []),
        config_path=Path(args.config),
        argv=["metriplane-fusion", *argv_in],
        run_id=args.run_id,
        runs_dir=normalize_runs_dir(args.runs_dir),
        duration_s=args.duration_s,
        paths=paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
