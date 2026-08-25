# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import inspect
import json
import logging
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from metriplane.observability.timing import StageTiming

import cv2  # type: ignore


from metriplane.config import Config, apply_profile_defaults, maybe_get_calib_paths
from metriplane.provenance.run_provenance import (
    JsonlWriter,
    RunContext,
    create_run_context,
    is_header_record,
    open_jsonl_writer,
)
from metriplane.paths import PlatformPaths, resolve_platform_paths


from metriplane.video_overlay import OverlayConfig, draw_overlay_bgr
from metriplane.backends.aruco_backend import ArUcoBackend
from metriplane.camera.rtsp import RTSPCamera
from metriplane.camera.usb import USBCamera
from metriplane.metrics import MetricsRegistry, start_metrics_server
from metriplane.mapping.planar import PlanarMapper, load_planar_mapper
from metriplane.schema import FrameStateModel, ObjectStateModel
from metriplane.streaming.ws_server import client_count
from metriplane.streaming.ws_thread import WsServerThread
from metriplane.tracking import ObjectRegistry
from metriplane.zone_analytics import ZoneAnalytics
from metriplane.zones import ZoneMap, load_zones

log = logging.getLogger("metriplane.run")


# =============================================================================
# M9.3: Health + graceful degradation (self-contained; no other files needed)
# =============================================================================

class HealthStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


_HEALTH_TO_SCORE: dict[HealthStatus, int] = {
    HealthStatus.OK: 2,
    HealthStatus.DEGRADED: 1,
    HealthStatus.FAILED: 0,
}


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus = HealthStatus.OK
    last_ok_ts_ns: int | None = None
    last_error_ts_ns: int | None = None
    last_error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "last_ok_ts_ns": self.last_ok_ts_ns,
            "last_error_ts_ns": self.last_error_ts_ns,
            "last_error": self.last_error,
            "details": dict(self.details or {}),
        }


class HealthRegistry:
    def __init__(self, *, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._lock = threading.Lock()
        self._start_ts_ns = time.monotonic_ns()
        self._components: dict[str, ComponentHealth] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def ensure(self, name: str, *, details: dict[str, Any] | None = None) -> None:
        n = str(name)
        with self._lock:
            if n not in self._components:
                self._components[n] = ComponentHealth(name=n)
            if details:
                self._components[n].details.update(details)

    def mark_ok(self, name: str, *, details: dict[str, Any] | None = None) -> None:
        if not self._enabled:
            return
        now = time.monotonic_ns()
        n = str(name)
        with self._lock:
            ch = self._components.get(n) or ComponentHealth(name=n)
            ch.status = HealthStatus.OK
            ch.last_ok_ts_ns = now
            if details:
                ch.details.update(details)
            self._components[n] = ch

    def mark_degraded(self, name: str, err: str, *, details: dict[str, Any] | None = None) -> None:
        if not self._enabled:
            return
        now = time.monotonic_ns()
        n = str(name)
        with self._lock:
            ch = self._components.get(n) or ComponentHealth(name=n)
            ch.status = HealthStatus.DEGRADED
            ch.last_error_ts_ns = now
            ch.last_error = str(err)
            if details:
                ch.details.update(details)
            self._components[n] = ch

    def mark_failed(self, name: str, err: str, *, details: dict[str, Any] | None = None) -> None:
        if not self._enabled:
            return
        now = time.monotonic_ns()
        n = str(name)
        with self._lock:
            ch = self._components.get(n) or ComponentHealth(name=n)
            ch.status = HealthStatus.FAILED
            ch.last_error_ts_ns = now
            ch.last_error = str(err)
            if details:
                ch.details.update(details)
            self._components[n] = ch

    def overall(self) -> HealthStatus:
        if not self._enabled:
            return HealthStatus.OK
        with self._lock:
            statuses = [c.status for c in self._components.values()]
        if any(s == HealthStatus.FAILED for s in statuses):
            return HealthStatus.FAILED
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        return HealthStatus.OK

    def snapshot_json(self) -> dict[str, Any]:
        now = time.monotonic_ns()
        with self._lock:
            comps = {k: v.to_json() for k, v in sorted(self._components.items(), key=lambda kv: kv[0])}
        return {
            "enabled": self._enabled,
            "ts_ns": now,
            "uptime_s": (now - self._start_ts_ns) / 1e9,
            "overall": self.overall().value,
            "components": comps,
        }

    def prometheus_samples(self) -> list[tuple[str, int]]:
        if not self._enabled:
            return []
        with self._lock:
            items = list(self._components.items())
        out: list[tuple[str, int]] = []
        for name, ch in items:
            out.append((name, _HEALTH_TO_SCORE.get(ch.status, 0)))
        out.sort(key=lambda x: x[0])
        return out


def _cfg_section(cfg: Config, key: str) -> dict[str, Any]:
    v = getattr(cfg, key, None)
    return dict(v) if isinstance(v, dict) else {}


def _parse_faults(*, cfg: Config, cli_faults: list[str] | None) -> dict[str, Any]:
    faults: dict[str, Any] = {}

    # from config: faults: { ... }
    faults.update(_cfg_section(cfg, "faults"))

    # from CLI: --fault k=v
    for item in (cli_faults or []):
        s = str(item).strip()
        if not s:
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip()
        else:
            k, v = s, "true"

        # type coercion
        vl: Any = v
        if v.lower() in ("true", "false"):
            vl = (v.lower() == "true")
        else:
            try:
                if "." in v:
                    vl = float(v)
                else:
                    vl = int(v)
            except Exception:
                vl = v
        faults[str(k)] = vl

    # from env: METRIPLANE_FAULT_*
    # (env takes highest priority)
    env_cam1 = os.getenv("METRIPLANE_FAULT_CAM1_DISCONNECT_AFTER_S")
    if env_cam1 is not None:
        try:
            faults["cam1_disconnect_after_s"] = float(env_cam1)
        except Exception:
            pass

    env_ws = os.getenv("METRIPLANE_FAULT_WS_SEND_FAIL_AFTER_S") or os.getenv("METRIPLANE_FAULT_WS_FAIL_AFTER_S")
    if env_ws is not None:
        try:
            faults["ws_send_fail_after_s"] = float(env_ws)
        except Exception:
            pass

    return faults


def _start_observability_server(
    *,
    host: str,
    port: int,
    registry: MetricsRegistry,
    get_ws_clients: Callable[[], int],
    get_health_json: Callable[[], dict[str, Any]],
    health: HealthRegistry,
) -> ThreadingHTTPServer:
    """
    Prefer metriplane.metrics.start_metrics_server if it already supports get_health.
    Otherwise, start a local server that serves BOTH /metrics and /health on the same port.
    """
    # Try the "native" server if it supports get_health (future-proof).
    try:
        sig = inspect.signature(start_metrics_server)
        if "get_health" in sig.parameters:
            return start_metrics_server(  # type: ignore[call-arg]
                host=host,
                port=port,
                registry=registry,
                get_ws_clients=get_ws_clients,
                get_health=get_health_json,
            )
    except Exception:
        pass

    # Fallback: combined server implemented here.
    from metriplane.metrics import CONTENT_TYPE as _METRICS_CT  # type: ignore
    from metriplane.metrics import _render_prometheus as _render  # type: ignore

    def _prom_label(v: str) -> str:
        return str(v).replace("\\", "\\\\").replace('"', '\\"')

    def _render_health_prometheus() -> str:
        lines: list[str] = [
            "# HELP metriplane_component_health Component health status (OK=2, DEGRADED=1, FAILED=0).",
            "# TYPE metriplane_component_health gauge",
        ]
        for name, score in health.prometheus_samples():
            lines.append(f'metriplane_component_health{{component="{_prom_label(name)}"}} {int(score)}')
        lines.append("")
        return "\n".join(lines) + "\n"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/metrics", "/metrics/"):
                snap = registry.snapshot(ws_clients_connected=get_ws_clients())
                base = _render(snap)
                payload = (base + _render_health_prometheus()).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", _METRICS_CT)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if self.path in ("/health", "/health/"):
                body = json.dumps(get_health_json(), sort_keys=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

        def end_headers(self) -> None:  # noqa: N802
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer((host, int(port)), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# -----------------------------
# Existing helpers (unchanged)
# -----------------------------

def _looks_like_default_calib_file(p: Path, filename: str) -> bool:
    """
    True for:
      calib/mapping.yaml
      ./calib/mapping.yaml
      /abs/.../calib/mapping.yaml
    """
    try:
        parts = p.parts
        if len(parts) >= 2 and parts[-1] == filename and parts[-2] == "calib":
            return True
    except Exception:
        pass

    try:
        norm = p.as_posix().lstrip("./")
        if norm == f"calib/{filename}":
            return True
    except Exception:
        pass

    return False


def _frame_to_bgr(frame: Any) -> Any:
    """
    USBCamera may return a wrapper (Frame) that contains the actual image as an attribute.
    This extracts a BGR ndarray-like image suitable for OpenCV + video writing.

    Tries common attribute names; otherwise assumes `frame` is already an ndarray.
    """
    if frame is None:
        return None

    for attr in ("bgr", "image", "img", "frame", "data"):
        try:
            if hasattr(frame, attr):
                v = getattr(frame, attr)
                if v is not None and hasattr(v, "shape"):
                    return v
        except Exception:
            pass

    return frame


def _in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _data_dir() -> Path:
    env = os.getenv("METRIPLANE_DATA_DIR")
    if env:
        return Path(env)
    return Path("/data") if _in_docker() else Path(".")


def _resolve_output_path(p: str | None) -> Path | None:
    if not p:
        return None
    pp = Path(p)
    if pp.is_absolute():
        return pp
    if _in_docker() or os.getenv("METRIPLANE_DATA_DIR"):
        return _data_dir() / pp
    return pp


@dataclass(frozen=True)
class ResolvedSingleCamera:
    camera: Any
    camera_backend: str
    camera_source: int | str
    vision_backend: str

    @property
    def source_backend(self) -> str:
        return f"{self.vision_backend}_{self.camera_backend}"


def _resolve_single_camera(cfg: Config) -> ResolvedSingleCamera:
    """Resolve and validate the camera settings used by the single-camera runner."""
    vision_backend = str(cfg.vision_backend or "").strip().lower()
    if vision_backend != "aruco":
        raise ValueError(
            f"Unsupported vision_backend={cfg.vision_backend!r}; single-camera runtime supports 'aruco'"
        )

    camera_backend = str(cfg.camera_backend or "").strip().lower()
    camera_device = str(cfg.camera_device).strip() if cfg.camera_device is not None else None
    camera_index = cfg.camera_index

    if cfg.cameras:
        if len(cfg.cameras) != 1:
            raise ValueError(
                "Single-camera runtime accepts at most one cameras entry; use metriplane.run_fusion "
                "for multiple cameras"
            )
        spec = cfg.cameras[0]
        camera_device = str(spec.device).strip() if spec.device is not None else camera_device
        camera_index = spec.index if spec.index is not None else camera_index

    if camera_backend == "usb":
        source: int | str
        if camera_device:
            source = camera_device
        else:
            source = 0 if camera_index is None else camera_index
            if not isinstance(source, int) or isinstance(source, bool) or source < 0:
                raise ValueError(f"Invalid USB camera_index={source!r}; expected a non-negative integer")
        return ResolvedSingleCamera(
            camera=USBCamera(index=source),
            camera_backend="usb",
            camera_source=source,
            vision_backend=vision_backend,
        )

    if camera_backend == "rtsp":
        if not camera_device or not camera_device.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError(
                "camera_backend='rtsp' requires camera_device with an rtsp:// or rtsps:// URL"
            )
        return ResolvedSingleCamera(
            camera=RTSPCamera(url=camera_device),
            camera_backend="rtsp",
            camera_source=camera_device,
            vision_backend=vision_backend,
        )

    raise ValueError(
        f"Unsupported camera_backend={cfg.camera_backend!r}; single-camera runtime supports 'usb' and 'rtsp'"
    )


def _maybe_load_mapper(cfg: Config, *, required: bool | None = None) -> PlanarMapper | None:
    if required is None:
        required = bool(cfg.mapping_file or cfg.intrinsics_file)
    calib = maybe_get_calib_paths(getattr(cfg, "profile", None), calib_root=Path("calib"))
    if calib is not None:
        log.info("profile: ENABLED profile=%s dir=%s", calib.profile, calib.profile_dir)
    else:
        log.info("profile: DISABLED (no --profile and no calib/active_profile.yaml)")

    mapping_path: Path | None = Path(str(cfg.mapping_file)) if cfg.mapping_file else None
    intr_path: Path | None = Path(str(cfg.intrinsics_file)) if getattr(cfg, "intrinsics_file", None) else None

    if calib is not None:
        if mapping_path is None or _looks_like_default_calib_file(mapping_path, "mapping.yaml"):
            mapping_path = calib.mapping
        if intr_path is None and calib.intrinsics is not None:
            intr_path = calib.intrinsics

    if mapping_path is None:
        return None

    try:
        mapper = load_planar_mapper(mapping_path, intr_path)
        log.info("planar mapping: ENABLED mapping=%s intrinsics=%s", mapping_path, intr_path or "(none)")
        return mapper
    except Exception as e:
        if required:
            raise ValueError(f"Failed to load configured planar mapping {mapping_path}: {e}") from e
        log.warning("planar mapping: DISABLED (profile default unavailable): %s", e)
        return None


def _maybe_load_zones(cfg: Config, *, required: bool | None = None) -> ZoneMap | None:
    if required is None:
        required = bool(cfg.zones_file)
    calib = maybe_get_calib_paths(getattr(cfg, "profile", None), calib_root=Path("calib"))

    zones_path: Path | None = Path(str(cfg.zones_file)) if cfg.zones_file else None
    if calib is not None:
        if zones_path is None or _looks_like_default_calib_file(zones_path, "zones.yaml"):
            zones_path = calib.zones

    if zones_path is None:
        return None

    try:
        z = load_zones(zones_path)
        log.info("zones: ENABLED file=%s zones=%d units=%s", zones_path, len(z.zones), z.units)
        return z
    except Exception as e:
        if required:
            raise ValueError(f"Failed to load configured zones {zones_path}: {e}") from e
        log.warning("zones: DISABLED (profile default unavailable): %s", e)
        return None


def _apply_runtime_profile_defaults(
    cfg: Config, *, calib_root: Path = Path("calib")
) -> Config:
    """Resolve profile defaults, failing only for an explicitly selected profile."""
    explicit_profile = str(cfg.profile or "").strip()
    if explicit_profile:
        calib = maybe_get_calib_paths(explicit_profile, calib_root=calib_root)
        if calib is None:
            raise ValueError(
                f"Configured profile not found: "
                f"{calib_root / 'profiles' / explicit_profile}"
            )
        if cfg.mapping_file is None and not calib.mapping.is_file():
            raise ValueError(
                f"Configured profile {explicit_profile!r} has no planar mapping: "
                f"{calib.mapping}"
            )
        if cfg.zones_file is None and not calib.zones.is_file():
            raise ValueError(
                f"Configured profile {explicit_profile!r} has no zones file: "
                f"{calib.zones}"
            )
    return apply_profile_defaults(cfg, calib_root=calib_root)


def _sleep_until_replay_deadline(target: float, *, max_sleep_s: float = 0.25) -> int:
    """Sleep in bounded chunks until a replay deadline is actually reached."""
    slept_ns = 0
    while True:
        remaining = target - time.monotonic()
        if remaining <= 0:
            return slept_ns
        started_ns = time.perf_counter_ns()
        time.sleep(min(remaining, max_sleep_s))
        slept_ns += time.perf_counter_ns() - started_ns


_MAX_REPLAY_PACING_DELAY_S = 24 * 60 * 60


def _detection_to_object(
    det: Any,
    *,
    mapper: Optional[PlanarMapper],
    z_world: float = 0.0,
) -> ObjectStateModel | None:
    if isinstance(det, (tuple, list)) and len(det) >= 3:
        oid = str(det[0])
        try:
            cx = float(det[1])
            cy = float(det[2])
        except Exception:
            return ObjectStateModel(id=oid)

        extra = {"px": (cx, cy)}
        pos_world = None
        if mapper is not None:
            xy = mapper.pixel_to_world_xy(cx, cy)
            if xy is not None:
                wx, wy = xy
                pos_world = (float(wx), float(wy), float(z_world))

        return ObjectStateModel(
            id=oid,
            pos_world=pos_world,
            confidence=1.0,
            extra=extra,
        )

    if isinstance(det, dict):
        mid = det.get("id") or det.get("marker_id")
        if mid is None:
            return None

        extra = det.get("extra")
        pos_world = None

        cx = det.get("cx")
        cy = det.get("cy")
        if cx is not None and cy is not None:
            try:
                cx_f = float(cx)
                cy_f = float(cy)
                extra = dict(extra or {})
                extra["px"] = (cx_f, cy_f)
                if mapper is not None:
                    xy = mapper.pixel_to_world_xy(cx_f, cy_f)
                    if xy is not None:
                        wx, wy = xy
                        pos_world = (float(wx), float(wy), float(z_world))
            except Exception:
                pass

        return ObjectStateModel(
            id=str(mid),
            pos_world=pos_world,
            extra=extra,
        )

    mid = getattr(det, "id", None) or getattr(det, "marker_id", None)
    if mid is None:
        return None
    return ObjectStateModel(id=str(mid))


@dataclass
class _RunResources:
    camera: Any = None
    websocket: Any = None
    observability: Any = None
    recorder: Any = None
    timing: Any = None
    video_writer: Any = None


def _close_run_resources(resources: _RunResources) -> None:
    """Close every acquired runtime resource, even when another close fails."""
    for resource, method in (
        (resources.camera, "close"),
        (resources.websocket, "stop"),
        (resources.observability, "shutdown"),
        (resources.observability, "server_close"),
        (resources.recorder, "close"),
        (resources.video_writer, "release"),
        (resources.timing, "close"),
    ):
        if resource is None:
            continue
        try:
            getattr(resource, method)()
        except Exception:
            log.debug(
                "cleanup failed for %s.%s",
                type(resource).__name__,
                method,
                exc_info=True,
            )


def run_loop(
    cfg: Config,
    *,
    cli_faults: list[str] | None = None,
    config_path: Path | None = None,
    argv: list[str] | None = None,
    run_id: str | None = None,
    runs_dir: str | None = None,
    paths: PlatformPaths | None = None,
) -> int:
    effective_runs_dir = runs_dir
    if not effective_runs_dir and not cfg.runs_dir:
        effective_runs_dir = str((paths or resolve_platform_paths()).runs_dir)
    resources = _RunResources()
    try:
        return _run_loop_impl(
            cfg,
            cli_faults=cli_faults,
            config_path=config_path,
            argv=argv,
            run_id=run_id,
            runs_dir=effective_runs_dir,
            _resources=resources,
        )
    finally:
        _close_run_resources(resources)


def _run_loop_impl(
    cfg: Config,
    *,
    cli_faults: list[str] | None = None,
    config_path: Path | None = None,
    argv: list[str] | None = None,
    run_id: str | None = None,
    runs_dir: str | None = None,
    _resources: _RunResources,
) -> int:
    log.info("run loop started")

    mode = str(getattr(cfg, "source_mode", "camera") or "camera").strip().lower()
    if mode not in {"camera", "replay", "dummy"}:
        log.error("unsupported source_mode=%r", cfg.source_mode)
        return 1

    try:
        # Explicit file/profile selections fail closed. An omitted profile (including
        # a best-effort active profile) remains optional for backwards compatibility.
        explicit_profile = bool(str(cfg.profile or "").strip())
        mapping_required = bool(
            cfg.mapping_file or cfg.intrinsics_file or explicit_profile
        )
        zones_required = bool(cfg.zones_file or explicit_profile)
        cfg = _apply_runtime_profile_defaults(cfg)

        # Validate configured optional resources before starting services or writing
        # a header-only run that appears successful.
        mapper = _maybe_load_mapper(cfg, required=mapping_required)
        zone_map = _maybe_load_zones(cfg, required=zones_required)
        resolved_camera = _resolve_single_camera(cfg) if mode == "camera" else None
    except (OSError, ValueError) as e:
        log.error("invalid runtime configuration: %s", e)
        return 1

    # M9.4: run provenance (FAIL FAST if we cannot create it)
    mirror_path: str | None = None
    if cfg.record_jsonl:
        rp = _resolve_output_path(str(cfg.record_jsonl))
        mirror_path = str(rp) if rp is not None else str(cfg.record_jsonl)

        # preserve prior overwrite warning behavior for record_jsonl mirror
        if rp is not None:
            try:
                if rp.exists():
                    size = rp.stat().st_size
                    if size > 0:
                        log.warning(
                            "recording: JSONL exists and WILL BE OVERWRITTEN: %s (size=%d bytes)",
                            rp,
                            size,
                        )
            except Exception as e:
                log.warning("recording: could not stat JSONL path %s: %s", rp, e)

        try:
            Path(mirror_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    ctx: RunContext = create_run_context(
        cfg,
        config_path=config_path,
        argv=argv,
        run_id=run_id,
        runs_dir=runs_dir,
    )

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

    # M9.5: per-stage timing (CSV artifacts in run_dir)
    tcfg = _cfg_section(cfg, "timing")
    env_timing = os.getenv("METRIPLANE_TIMING") or os.getenv("METRIPLANE_TIMING")
    timing_enabled = bool(tcfg.get("enabled", tcfg.get("enable", False))) or (str(env_timing).strip() in ("1", "true", "True", "yes", "on"))
    timing = StageTiming(
        enabled=timing_enabled,
        stages=[
            "camera.read",
            "detect",
            "to_objects",
            "tracking",
            "zones",
            "record.jsonl",
            "ws.send",
            "overlay",
            "replay.parse",
            "replay.sleep",
            "dummy.sim",
            "sleep",
        ],
        frames_csv_path=ctx.run_dir / "latency_frames.csv",
        summary_csv_path=ctx.run_dir / "latency_summary.csv",
        flush_every=1,
    )
    _resources.timing = timing
    if timing_enabled:
        log.info("M9.5 timing: ENABLED frames_csv=%s summary_csv=%s", ctx.run_dir / "latency_frames.csv", ctx.run_dir / "latency_summary.csv")
    else:
        log.info("M9.5 timing: DISABLED (set METRIPLANE_TIMING=1 or timing.enabled=true)")

    # M9.3: health enable
    hcfg = _cfg_section(cfg, "health")
    health_enabled = bool(hcfg.get("enabled", hcfg.get("enable", True)))
    health = HealthRegistry(enabled=health_enabled)
    health.ensure("ws")
    health.ensure("camera")
    health.ensure("recording.jsonl")
    health.ensure("mapping")
    health.ensure("zones")
    health.ensure("timing")
    health.ensure("observability")

    health.mark_ok(
        "recording.jsonl",
        details={"enabled": True, "paths": [str(p) for p in recorder.paths], "mirror_enabled": bool(mirror_enabled)},
    )
    if (not mirror_enabled) and mirror_path:
        health.mark_degraded("recording.jsonl", f"mirror_disabled: {mirror_path}")

    health.mark_ok(
        "timing",
        details={
            "enabled": bool(timing_enabled),
            "frames_csv": str(ctx.run_dir / "latency_frames.csv"),
            "summary_csv": str(ctx.run_dir / "latency_summary.csv"),
        },
    )

    # Faults (mainly used for WS send fail in single-cam runner)
    faults = _parse_faults(cfg=cfg, cli_faults=cli_faults)
    ws_fail_after_s = float(faults.get("ws_send_fail_after_s") or faults.get("ws_fail_after_s") or 0.0)
    t0 = time.monotonic()

    ws = WsServerThread(host=cfg.ws_host, port=cfg.ws_port)
    _resources.websocket = ws
    try:
        ws.start()
        log.info("ws server running at ws://%s:%d", cfg.ws_host, cfg.ws_port)
        health.mark_ok("ws", details={"ws_url": f"ws://{cfg.ws_host}:{cfg.ws_port}"})
    except Exception as e:
        log.error("failed to start ws server on ws://%s:%d: %s", cfg.ws_host, cfg.ws_port, e)
        health.mark_failed("ws", f"start_failed: {e}")
        return 1

    metrics = MetricsRegistry()
    try:
        obs_server = _start_observability_server(
            host=cfg.metrics_host,
            port=cfg.metrics_port,
            registry=metrics,
            get_ws_clients=client_count,
            get_health_json=health.snapshot_json,
            health=health,
        )
        _resources.observability = obs_server
        health.mark_ok(
            "observability",
            details={"host": cfg.metrics_host, "port": int(cfg.metrics_port)},
        )
    except Exception as e:
        log.error(
            "failed to start observability server on http://%s:%d: %s",
            cfg.metrics_host,
            cfg.metrics_port,
            e,
        )
        health.mark_failed("observability", f"start_failed: {e}")
        return 1
    log.info("metrics at http://%s:%d/metrics", cfg.metrics_host, cfg.metrics_port)
    log.info("health  at http://%s:%d/health", cfg.metrics_host, cfg.metrics_port)

    if mapper is None:
        health.mark_ok("mapping", details={"enabled": False})
    else:
        health.mark_ok("mapping", details={"enabled": True, "units": mapper.mapping.units})

    zone_analytics = ZoneAnalytics(zone_map) if zone_map is not None else None
    if zone_analytics is not None:
        log.info("zone analytics: ENABLED")
        health.mark_ok("zones", details={"enabled": True, "units": zone_map.units})
    else:
        log.info("zone analytics: DISABLED (zones unavailable)")
        health.mark_ok("zones", details={"enabled": False})

    # -----------------------------
    # M9: Docker/offline source modes (NO CAMERA)
    # -----------------------------
    if mode in ("replay", "dummy"):
        status = 0
        try:
            if mode == "replay":
                status = _run_replay_mode(
                    cfg=cfg,
                    ctx=ctx,
                    ws=ws,
                    metrics=metrics,
                    recorder=recorder,
                    health=health,
                    timing=timing,
                    ws_fail_after_s=ws_fail_after_s,
                    t0=t0,
                )
            else:
                status = _run_dummy_mode(
                    cfg=cfg,
                    ctx=ctx,
                    ws=ws,
                    metrics=metrics,
                    zone_analytics=zone_analytics,
                    recorder=recorder,
                    health=health,
                    timing=timing,
                    ws_fail_after_s=ws_fail_after_s,
                    t0=t0,
                )
        finally:
            log.info("run loop exited cleanly")
        return status

    # -----------------------------
    # CAMERA MODE (existing behavior)
    # -----------------------------

    # Optional MP4 recording
    record_video_path: Path | None = None
    video_writer: Any | None = None
    video_fps = float(getattr(cfg, "record_video_fps", 15.0))

    rv = getattr(cfg, "record_video", None)
    if rv:
        record_video_path = _resolve_output_path(str(rv)) or Path(str(rv))
        record_video_path.parent.mkdir(parents=True, exist_ok=True)
        log.info("video recording: REQUESTED -> %s (fps=%.1f)", record_video_path, video_fps)
    else:
        log.info("video recording: DISABLED")

    assert resolved_camera is not None
    cam = resolved_camera.camera
    _resources.camera = cam
    backend = ArUcoBackend()
    registry = ObjectRegistry(timeout_s=float(cfg.object_timeout_s))

    frame_times: deque[float] = deque(maxlen=max(int(cfg.target_fps) * 2, 20))

    frame_id = 0
    frames_total = 0
    frames_dropped = 0
    last_log = time.monotonic()

    try:
        cam.open()
        health.mark_ok(
            "camera",
            details={
                "mode": resolved_camera.camera_backend,
                "source": (
                    str(resolved_camera.camera_source)
                    if resolved_camera.camera_backend == "usb"
                    else "configured_rtsp_url"
                ),
                "vision_backend": resolved_camera.vision_backend,
            },
        )
    except Exception as e:
        log.error("camera open error: %s", e)
        health.mark_failed(
            "camera",
            f"open_failed: {e}",
            details={"mode": resolved_camera.camera_backend},
        )
        return 1

    last_ts_frame = time.time()
    ws_disabled = False

    try:
        while True:
            loop_start = time.monotonic()
            ts_now_epoch = time.time()

            # ---- camera.read timing measured outside begin_frame ----
            t_cam0 = time.perf_counter_ns()
            try:
                frame_raw = cam.read()
                cam_read_ns = time.perf_counter_ns() - t_cam0
                health.mark_ok("camera")
            except RuntimeError as e:
                frames_dropped += 1
                metrics.update(frames_dropped_total=frames_dropped)
                log.warning("camera read error (dropped=%d): %s", frames_dropped, e)
                health.mark_degraded("camera", f"read_error: {e}")
                time.sleep(0.01)
                continue

            frame_bgr = _frame_to_bgr(frame_raw)

            # Init writer once we have a real ndarray frame
            if (
                video_writer is None
                and record_video_path is not None
                and frame_bgr is not None
                and hasattr(frame_bgr, "shape")
            ):
                try:
                    h, w = frame_bgr.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    video_writer = cv2.VideoWriter(
                        str(record_video_path), fourcc, float(video_fps), (int(w), int(h))
                    )
                    _resources.video_writer = video_writer
                    if not video_writer.isOpened():
                        log.error("video recording: FAILED to open writer -> %s", record_video_path)
                        try:
                            video_writer.release()
                        except Exception:
                            pass
                        video_writer = None
                        _resources.video_writer = None
                        record_video_path = None
                    else:
                        log.info(
                            "video recording: ENABLED -> %s (size=%dx%d fps=%.1f)",
                            record_video_path,
                            w,
                            h,
                            video_fps,
                        )
                except Exception as e:
                    log.exception("video recording: FAILED to init writer: %s", e)
                    if video_writer is not None:
                        try:
                            video_writer.release()
                        except Exception:
                            pass
                    video_writer = None
                    _resources.video_writer = None
                    record_video_path = None

            frames_total += 1
            frame_id += 1
            metrics.update(frames_total=frames_total)

            ts_frame = float(getattr(frame_raw, "ts_cam_read", ts_now_epoch))
            last_ts_frame = ts_frame

            # ---- begin per-frame timing (M9.5) ----
            timing.begin_frame(ts=ts_frame, frame_id=frame_id)
            timing.add_stage_ns("camera.read", int(cam_read_ns))

            # ---- detect ----
            with timing.stage("detect"):
                try:
                    detections = backend.detect(frame_bgr) or []
                except Exception:
                    detections = backend.detect(frame_raw) or []

            # ---- to_objects + mapping ----
            now_s = time.monotonic()
            with timing.stage("to_objects"):
                objs_now: list[ObjectStateModel] = []
                for det in detections:
                    obj = _detection_to_object(det, mapper=mapper)
                    if obj is not None:
                        objs_now.append(obj)

            # ---- tracking + fps ----
            with timing.stage("tracking"):
                expired = registry.update(objs_now, now_s=now_s)

                frame_times.append(time.monotonic())
                fps = 0.0
                if len(frame_times) >= 2:
                    dt = frame_times[-1] - frame_times[0]
                    if dt > 1e-6:
                        fps = float(len(frame_times) - 1) / dt

                tracked = registry.snapshot()
                ws_clients = client_count()
                metrics.update(fps=fps, objects_tracked=len(tracked))

            # ---- zones ----
            with timing.stage("zones"):
                if zone_analytics is not None:
                    tracked_out, events = zone_analytics.update(ts_frame, tracked)
                    if events:
                        for ev in events:
                            log.info("zone_event type=%s object=%s zone=%s", ev.type, ev.object_id, ev.zone)
                else:
                    tracked_out = tracked
                    events = []

            msg = FrameStateModel(
                # M9.4 provenance
                run_id=ctx.run_id,
                config_hash=ctx.config_hash,
                git_commit=ctx.git.commit,
                source_backend=resolved_camera.source_backend,
                ts=ts_frame,
                frame_id=frame_id,
                objects=tracked_out,
                events=events,
                metrics={
                    "fps": fps,
                    "objects_tracked": len(tracked_out),
                    "frames_total": frames_total,
                    "frames_dropped_total": frames_dropped,
                    "ws_clients_connected": ws_clients,
                    "camera_backend": resolved_camera.camera_backend,
                    "mapping_enabled": bool(mapper is not None),
                    "mapping_units": mapper.mapping.units if mapper is not None else None,
                    "zones_enabled": bool(zone_analytics is not None),
                    "zones_units": zone_map.units if zone_map is not None else None,
                },
            )

            # ---- record.jsonl ----
            with timing.stage("record.jsonl"):
                try:
                    recorder.write(msg.model_dump())
                except Exception as e:
                    health.mark_failed("recording.jsonl", f"write_failed: {e}")
                    return 1

            # ---- ws.send ----
            with timing.stage("ws.send"):
                try:
                    if not ws_disabled and ws_fail_after_s > 0 and (time.monotonic() - t0) >= ws_fail_after_s:
                        raise RuntimeError(f"FAULT: ws_send_fail_after_s={ws_fail_after_s}")

                    if not ws_disabled:
                        ws.send_frame(msg)
                        health.mark_ok("ws")
                except Exception as e:
                    ws_disabled = True
                    health.mark_degraded("ws", f"send_failed: {e}")
                    log.warning("ws send failed -> entering degraded mode (publishing disabled): %s", e)

            # ---- overlay ----
            if video_writer is not None and frame_bgr is not None and hasattr(frame_bgr, "shape"):
                with timing.stage("overlay"):
                    story_ids = {"1", "2", "3", "4", "7"}
                    present_ids = {str(o.id) for o in tracked_out}
                    include = story_ids & present_ids
                    include_ids = include if include else None

                    overlay_cfg = OverlayConfig(
                        include_ids=include_ids,
                        show_xy_ids={"7"},
                        font_scale=0.50,
                        thickness=1,
                        bg_alpha=0.70,
                        max_labels=10,
                        require_px=True,
                    )

                    vis = draw_overlay_bgr(frame_bgr, tracked_out, overlay_cfg, units="m")
                    video_writer.write(vis)

            # Logs
            if (time.monotonic() - last_log) >= 1.0:
                ids = registry.tracked_ids()
                log.info(
                    "fps=%.1f objects_tracked=%d seen_now=%d expired=%d ids=%s ws_clients=%d mapping=%s zones=%s",
                    fps,
                    len(ids),
                    len(objs_now),
                    len(expired),
                    ",".join(ids) if ids else "-",
                    ws_clients,
                    "on" if mapper is not None else "off",
                    "on" if zone_analytics is not None else "off",
                )
                last_log = time.monotonic()

            # FPS limit (sleep stage measured)
            if cfg.target_fps > 0:
                budget = 1.0 / float(cfg.target_fps)
                elapsed = time.monotonic() - loop_start
                sleep_s = budget - elapsed
                if sleep_s > 0:
                    with timing.stage("sleep"):
                        time.sleep(min(sleep_s, 0.05))

            # ---- end per-frame timing ----
            timing.end_frame()

    except KeyboardInterrupt:
        log.info("shutdown requested")
    finally:
        # Export analytics
        if zone_analytics is not None and cfg.analytics_out_dir:
            out_dir = _resolve_output_path(str(cfg.analytics_out_dir)) or Path(str(cfg.analytics_out_dir))
            try:
                zone_analytics.finalize(last_ts_frame)
                paths = zone_analytics.export_csv(out_dir, prefix="m6")
                log.info("zone analytics exported -> %s", out_dir)
                for k, p in paths.items():
                    log.info("  %s: %s", k, p)
            except Exception as e:
                log.exception("failed to export zone analytics: %s", e)

        if video_writer is not None:
            if record_video_path is not None:
                log.info("video recording: WROTE %s", record_video_path)

        log.info("run loop exited cleanly")

    return 0


def _run_replay_mode(
    cfg: Config,
    ctx: RunContext,
    ws: WsServerThread,
    metrics: MetricsRegistry,
    recorder: JsonlWriter,
    health: HealthRegistry,
    timing: StageTiming,
    *,
    ws_fail_after_s: float,
    t0: float,
) -> int:
    inp = getattr(cfg, "replay_input", None)
    if not inp:
        log.error("replay mode requires replay_input (set replay.input in docker_demo_replay.yaml)")
        health.mark_failed("camera", "replay_input_missing", details={"mode": "replay"})
        return 1

    p = Path(str(inp))
    if not p.is_file():
        log.error("replay input not found: %s", p)
        health.mark_failed("camera", "replay_input_not_found", details={"mode": "replay", "path": str(p)})
        return 1

    health.mark_ok("camera", details={"mode": "replay", "path": str(p)})

    try:
        speed = float(getattr(cfg, "replay_speed", 1.0))
    except (TypeError, ValueError) as exc:
        health.mark_failed("camera", f"invalid_replay_speed: {exc}")
        return 1
    if not math.isfinite(speed) or speed < 0:
        health.mark_failed(
            "camera",
            "invalid_replay_speed: expected a finite value greater than or equal to zero",
        )
        return 1
    loop_forever = bool(getattr(cfg, "replay_loop", True))

    frames_total = 0
    frame_times: deque[float] = deque(maxlen=max(int(cfg.target_fps) * 2, 60))
    ws_disabled = False

    log.info("replay: ENABLED input=%s speed=%.2f loop=%s", p, speed, loop_forever)

    try:
        while True:
            first_ts: float | None = None
            previous_ts: float | None = None
            wall0 = time.monotonic()
            pass_frames = 0

            with p.open("r", encoding="utf-8") as f:
                for line_number, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue

                    # measure parse/validate cost
                    t_parse0 = time.perf_counter_ns()

                    try:
                        data = json.loads(line)

                        if is_header_record(data):
                            continue

                        msg = FrameStateModel.model_validate(data)

                        upd = {}
                        if getattr(msg, "run_id", None) in (None, ""):
                            upd["run_id"] = ctx.run_id
                        if getattr(msg, "config_hash", None) in (None, ""):
                            upd["config_hash"] = ctx.config_hash
                        if getattr(msg, "git_commit", None) in (None, ""):
                            upd["git_commit"] = ctx.git.commit

                        if upd:
                            msg = msg.model_copy(update=upd)

                    except Exception as exc:
                        err = (
                            f"invalid_jsonl_line:{line_number}:"
                            f"{type(exc).__name__}: {exc}"
                        )
                        log.error("replay: %s", err)
                        health.mark_failed(
                            "camera",
                            err,
                            details={"mode": "replay", "path": str(p)},
                        )
                        return 1

                    parse_ns = time.perf_counter_ns() - t_parse0

                    source_ts = float(msg.ts)
                    if not math.isfinite(source_ts):
                        err = f"invalid_timestamp: line {line_number} ts must be finite"
                        log.error("replay: %s", err)
                        health.mark_failed("camera", err)
                        return 1
                    if msg.ts_sim_ns is not None and msg.ts_sim_ns < 0:
                        err = (
                            f"invalid_timestamp: line {line_number} "
                            "ts_sim_ns must be non-negative"
                        )
                        log.error("replay: %s", err)
                        health.mark_failed("camera", err)
                        return 1
                    try:
                        replay_ts = (
                            float(msg.ts_sim_ns) / 1_000_000_000.0
                            if msg.ts_sim_ns is not None
                            else source_ts
                        )
                    except OverflowError:
                        replay_ts = float("inf")
                    if not math.isfinite(replay_ts):
                        err = (
                            f"invalid_timestamp: line {line_number} "
                            "timestamp is outside the supported range"
                        )
                        log.error("replay: %s", err)
                        health.mark_failed("camera", err)
                        return 1
                    if previous_ts is not None and replay_ts < previous_ts:
                        err = f"non_monotonic_timestamp: {replay_ts} follows {previous_ts}"
                        log.error("replay: %s", err)
                        health.mark_failed(
                            "camera",
                            err,
                            details={"mode": "replay", "path": str(p)},
                        )
                        return 1
                    previous_ts = replay_ts

                    if first_ts is None:
                        first_ts = replay_ts
                        wall0 = time.monotonic()

                    # begin timing for this emitted frame (use monotonic counter as frame_id)
                    timing.begin_frame(ts=float(msg.ts), frame_id=int(frames_total + 1))
                    timing.add_stage_ns("replay.parse", int(parse_ns))

                    # replay pacing
                    if speed > 0 and first_ts is not None:
                        try:
                            dt = (replay_ts - first_ts) / speed
                            target = wall0 + dt
                        except OverflowError:
                            dt = float("inf")
                            target = float("inf")
                        if (
                            not math.isfinite(target)
                            or dt < 0
                            or dt > _MAX_REPLAY_PACING_DELAY_S
                        ):
                            err = (
                                f"invalid_replay_deadline: line {line_number} "
                                "produced a non-finite, negative, or longer than "
                                "24-hour pacing delay"
                            )
                            log.error("replay: %s", err)
                            health.mark_failed("camera", err)
                            return 1
                        slept_ns = _sleep_until_replay_deadline(target)
                        if slept_ns:
                            timing.add_stage_ns("replay.sleep", slept_ns)

                    frames_total += 1
                    pass_frames += 1
                    frame_times.append(time.monotonic())

                    fps = 0.0
                    if len(frame_times) >= 2:
                        dtw = frame_times[-1] - frame_times[0]
                        if dtw > 1e-6:
                            fps = float(len(frame_times) - 1) / dtw

                    metrics.update(frames_total=frames_total, fps=fps, objects_tracked=len(msg.objects))

                    with timing.stage("record.jsonl"):
                        try:
                            recorder.write(msg.model_dump())
                        except Exception as e:
                            health.mark_failed("recording.jsonl", f"write_failed: {e}")
                            return 1

                    with timing.stage("ws.send"):
                        try:
                            if not ws_disabled and ws_fail_after_s > 0 and (time.monotonic() - t0) >= ws_fail_after_s:
                                raise RuntimeError(f"FAULT: ws_send_fail_after_s={ws_fail_after_s}")
                            if not ws_disabled:
                                ws.send_frame(msg)
                                health.mark_ok("ws")
                        except Exception as e:
                            ws_disabled = True
                            health.mark_degraded("ws", f"send_failed: {e}")
                            log.warning("ws send failed -> degraded mode (publishing disabled): %s", e)

                    timing.end_frame()

            if pass_frames == 0:
                err = "replay_input_has_no_valid_frames"
                log.error("replay: %s: %s", err, p)
                health.mark_failed(
                    "camera",
                    err,
                    details={"mode": "replay", "path": str(p)},
                )
                return 1

            if not loop_forever:
                log.info("replay: EOF reached; exiting replay mode")
                break

            log.info("replay: EOF reached; restarting in 1.0s")
            time.sleep(1.0)

    except KeyboardInterrupt:
        log.info("replay: shutdown requested")
        return 0
    except OSError as e:
        log.error("replay: failed to read %s: %s", p, e)
        health.mark_failed(
            "camera",
            f"replay_input_unreadable: {e}",
            details={"mode": "replay", "path": str(p)},
        )
        return 1

    return 0


def _run_dummy_mode(
    cfg: Config,
    ctx: RunContext,
    ws: WsServerThread,
    metrics: MetricsRegistry,
    zone_analytics: Any | None,
    recorder: JsonlWriter,
    health: HealthRegistry,
    timing: StageTiming,
    *,
    ws_fail_after_s: float,
    t0: float,
) -> int:
    import math

    log.info("dummy: ENABLED (no camera)")
    health.mark_ok("camera", details={"mode": "dummy"})

    frames_total = 0
    frame_id = 0
    frame_times: deque[float] = deque(maxlen=max(int(cfg.target_fps) * 2, 60))
    ws_disabled = False

    t0_wall = time.time()

    try:
        while True:
            loop_start = time.monotonic()
            ts = time.time()
            t = ts - t0_wall

            frames_total += 1
            frame_id += 1

            timing.begin_frame(ts=float(ts), frame_id=int(frame_id))

            with timing.stage("dummy.sim"):
                x = 0.25 + 0.10 * math.sin(t * 0.8)
                y = 0.15 + 0.06 * math.cos(t * 0.6)

                objs = [
                    ObjectStateModel(
                        id="7",
                        pos_world=(float(x), float(y), 0.0),
                        confidence=1.0,
                        extra={"dummy": True},
                    )
                ]

            with timing.stage("zones"):
                if zone_analytics is not None:
                    objs_out, events = zone_analytics.update(ts, objs)
                else:
                    objs_out, events = objs, []

            frame_times.append(time.monotonic())
            fps = 0.0
            if len(frame_times) >= 2:
                dtw = frame_times[-1] - frame_times[0]
                if dtw > 1e-6:
                    fps = float(len(frame_times) - 1) / dtw

            msg = FrameStateModel(
                # M9.4 provenance
                run_id=ctx.run_id,
                config_hash=ctx.config_hash,
                git_commit=ctx.git.commit,
                source_backend="dummy",
                ts=float(ts),
                frame_id=int(frame_id),
                objects=list(objs_out),
                events=list(events),
                metrics={
                    "fps": fps,
                    "frames_total": frames_total,
                    "ws_clients_connected": client_count(),
                },
            )

            metrics.update(frames_total=frames_total, fps=fps, objects_tracked=len(msg.objects))

            with timing.stage("record.jsonl"):
                try:
                    recorder.write(msg.model_dump())
                except Exception as e:
                    health.mark_failed("recording.jsonl", f"write_failed: {e}")
                    return 1

            with timing.stage("ws.send"):
                try:
                    if not ws_disabled and ws_fail_after_s > 0 and (time.monotonic() - t0) >= ws_fail_after_s:
                        raise RuntimeError(f"FAULT: ws_send_fail_after_s={ws_fail_after_s}")

                    if not ws_disabled:
                        ws.send_frame(msg)
                        health.mark_ok("ws")
                except Exception as e:
                    ws_disabled = True
                    health.mark_degraded("ws", f"send_failed: {e}")
                    log.warning("ws send failed -> degraded mode (publishing disabled): %s", e)

            if cfg.target_fps > 0:
                budget = 1.0 / float(cfg.target_fps)
                elapsed = time.monotonic() - loop_start
                sleep_s = budget - elapsed
                if sleep_s > 0:
                    with timing.stage("sleep"):
                        time.sleep(min(sleep_s, 0.05))

            timing.end_frame()

    except KeyboardInterrupt:
        log.info("dummy: shutdown requested")
        return 0




def main(argv=None, *, paths: PlatformPaths | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path

    from metriplane.config import load_config

    ap = argparse.ArgumentParser(description="Metriplane runner")
    ap.add_argument("--config", "-c", default="config.example.yaml", help="Path to YAML config")

    ap.add_argument("--run-id", default=None, help="Optional run id override (otherwise auto).")
    ap.add_argument(
        "--runs-dir",
        default=None,
        help="Override runs base directory (default: platform data directory).",
    )

    # M9.3: reproducible fault injection
    ap.add_argument(
        "--fault",
        action="append",
        default=[],
        help="Fault injection (repeatable). Example: --fault ws_send_fail_after_s=12",
    )

    argv_in = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(argv_in)

    cfg = load_config(Path(args.config))

    return run_loop(
        cfg,
        cli_faults=list(args.fault or []),
        config_path=Path(args.config),
        argv=["metriplane", *argv_in],
        run_id=args.run_id,
        runs_dir=args.runs_dir,
        paths=paths,
    )


if __name__ == "__main__":
    raise SystemExit(main())
