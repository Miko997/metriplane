# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    # Existing (M1+)
    fps: float
    objects_tracked: int
    ws_clients_connected: int
    frames_total: int
    frames_dropped_total: int

    # NEW (M9.2): queue + stage instrumentation
    queue_depth: dict[str, int]
    queue_dropped_total: dict[tuple[str, str], int]  # (queue, policy) -> count
    stage_latency_ms_last: dict[str, float]
    stage_latency_ms_ema: dict[str, float]


class MetricsRegistry:
    """Thread-safe metrics registry.

    Notes
    -----
    - This registry is designed for very low overhead and minimal dependencies.
    - We keep per-queue and per-stage metrics in dictionaries so callers can
      introduce new queues/stages without changing the schema.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Existing (M1+)
        self._fps: float = 0.0
        self._objects_tracked: int = 0
        self._frames_total: int = 0
        self._frames_dropped_total: int = 0

        # NEW (M9.2)
        self._queue_depth: dict[str, int] = {}
        self._queue_dropped_total: dict[tuple[str, str], int] = {}
        self._stage_latency_ms_last: dict[str, float] = {}
        self._stage_latency_ms_ema: dict[str, float] = {}

    # -----------------------------
    # Existing scalar updates
    # -----------------------------

    def update(
        self,
        *,
        fps: Optional[float] = None,
        objects_tracked: Optional[int] = None,
        frames_total: Optional[int] = None,
        frames_dropped_total: Optional[int] = None,
    ) -> None:
        with self._lock:
            if fps is not None:
                self._fps = float(fps)
            if objects_tracked is not None:
                self._objects_tracked = int(objects_tracked)
            if frames_total is not None:
                self._frames_total = int(frames_total)
            if frames_dropped_total is not None:
                self._frames_dropped_total = int(frames_dropped_total)

    # -----------------------------
    # NEW (M9.2): queue + stage
    # -----------------------------

    def set_queue_depth(self, queue_name: str, depth: int) -> None:
        qn = str(queue_name)
        with self._lock:
            self._queue_depth[qn] = int(depth)

    def inc_queue_dropped(self, queue_name: str, *, policy: str, n: int = 1) -> None:
        qn = str(queue_name)
        pol = str(policy or "")
        with self._lock:
            k = (qn, pol)
            self._queue_dropped_total[k] = int(self._queue_dropped_total.get(k, 0)) + int(n)

    def observe_stage_latency_ms(
        self, stage: str, last: float, *, ema: float | None = None
    ) -> None:
        st = str(stage)
        with self._lock:
            self._stage_latency_ms_last[st] = float(last)
            if ema is not None:
                self._stage_latency_ms_ema[st] = float(ema)

    def snapshot(self, *, ws_clients_connected: int) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                fps=float(self._fps),
                objects_tracked=int(self._objects_tracked),
                ws_clients_connected=int(ws_clients_connected),
                frames_total=int(self._frames_total),
                frames_dropped_total=int(self._frames_dropped_total),
                queue_depth=dict(self._queue_depth),
                queue_dropped_total=dict(self._queue_dropped_total),
                stage_latency_ms_last=dict(self._stage_latency_ms_last),
                stage_latency_ms_ema=dict(self._stage_latency_ms_ema),
            )


def _prom_label(v: str) -> str:
    # Prometheus label value escaping for " and \\.
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def _render_prometheus(s: MetricsSnapshot) -> str:
    # Minimal Prometheus exposition format
    lines: list[str] = [
        "# HELP metriplane_fps Current FPS (smoothed).",
        "# TYPE metriplane_fps gauge",
        f"metriplane_fps {s.fps:.3f}",
        "",
        "# HELP metriplane_objects_tracked Number of objects currently tracked.",
        "# TYPE metriplane_objects_tracked gauge",
        f"metriplane_objects_tracked {s.objects_tracked}",
        "",
        "# HELP metriplane_ws_clients_connected Number of connected websocket clients.",
        "# TYPE metriplane_ws_clients_connected gauge",
        f"metriplane_ws_clients_connected {s.ws_clients_connected}",
        "",
        "# HELP metriplane_frames_total Total frames processed.",
        "# TYPE metriplane_frames_total counter",
        f"metriplane_frames_total {s.frames_total}",
        "",
        "# HELP metriplane_frames_dropped_total Total frames dropped due to read errors.",
        "# TYPE metriplane_frames_dropped_total counter",
        f"metriplane_frames_dropped_total {s.frames_dropped_total}",
        "",
        "# HELP metriplane_queue_depth Current depth of bounded queues.",
        "# TYPE metriplane_queue_depth gauge",
    ]

    # Queue depths
    for qname in sorted(s.queue_depth.keys()):
        depth = int(s.queue_depth[qname])
        lines.append(f'metriplane_queue_depth{{queue="{_prom_label(qname)}"}} {depth}')

    lines.extend(
        [
            "",
            "# HELP metriplane_queue_dropped_total Total items dropped by bounded queues.",
            "# TYPE metriplane_queue_dropped_total counter",
        ]
    )

    for qname, policy in sorted(s.queue_dropped_total.keys(), key=lambda k: (k[0], k[1])):
        c = int(s.queue_dropped_total[(qname, policy)])
        lines.append(
            "metriplane_queue_dropped_total"
            f'{{queue="{_prom_label(qname)}",policy="{_prom_label(policy)}"}} {c}'
        )

    lines.extend(
        [
            "",
            "# HELP metriplane_stage_latency_ms_last Last observed processing time per stage (ms).",
            "# TYPE metriplane_stage_latency_ms_last gauge",
        ]
    )
    for st in sorted(s.stage_latency_ms_last.keys()):
        v = float(s.stage_latency_ms_last[st])
        lines.append(f'metriplane_stage_latency_ms_last{{stage="{_prom_label(st)}"}} {v:.3f}')

    lines.extend(
        [
            "",
            "# HELP metriplane_stage_latency_ms_ema Exponentially smoothed processing time per stage (ms).",
            "# TYPE metriplane_stage_latency_ms_ema gauge",
        ]
    )
    for st in sorted(s.stage_latency_ms_ema.keys()):
        v = float(s.stage_latency_ms_ema[st])
        lines.append(f'metriplane_stage_latency_ms_ema{{stage="{_prom_label(st)}"}} {v:.3f}')

    lines.append("")
    return "\n".join(lines) + "\n"


def _health_status_to_prom_value(status: str) -> int:
    s = str(status).upper()
    if s == "OK":
        return 2
    if s == "DEGRADED":
        return 1
    if s == "FAILED":
        return 0
    return -1  # unknown


def _render_health_prometheus(health: dict[str, Any]) -> str:
    """
    Expects:
      {
        "overall": "OK|DEGRADED|FAILED",
        "components": {
            "camera.cam0": {"status": "OK", ...},
            ...
        }
      }
    """
    comps = health.get("components")
    if not isinstance(comps, dict):
        return ""

    lines: list[str] = [
        "",
        "# HELP metriplane_component_health Component health (OK=2, DEGRADED=1, FAILED=0).",
        "# TYPE metriplane_component_health gauge",
    ]

    # Stable ordering (deterministic output)
    for name in sorted(comps.keys()):
        item = comps.get(name)
        status = None
        if isinstance(item, dict):
            status = item.get("status")
        if status is None:
            status = str(item)
        v = _health_status_to_prom_value(str(status))
        lines.append(f'metriplane_component_health{{component="{_prom_label(str(name))}"}} {v}')

    lines.append("")
    return "\n".join(lines)


def start_metrics_server(
    *,
    host: str,
    port: int,
    registry: MetricsRegistry,
    get_ws_clients: Callable[[], int],
    get_health: Optional[Callable[[], dict[str, Any]]] = None,  # <-- NEW
) -> ThreadingHTTPServer:
    import json  # local import is fine; keeps module deps minimal

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/metrics", "/metrics/"):
                snap = registry.snapshot(ws_clients_connected=get_ws_clients())
                text = _render_prometheus(snap)

                # Optional: also export health as Prometheus gauges
                if get_health is not None:
                    try:
                        h = get_health()
                        if isinstance(h, dict):
                            text += _render_health_prometheus(h)
                    except Exception:
                        # Do NOT fail metrics endpoint because health is broken.
                        pass

                payload = text.encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if self.path in ("/health", "/health/") and get_health is not None:
                try:
                    body_obj = get_health()
                    if not isinstance(body_obj, dict):
                        body_obj = {
                            "overall": "FAILED",
                            "error": "get_health did not return a dict",
                        }
                except Exception as e:
                    body_obj = {"overall": "FAILED", "error": str(e)}

                body = json.dumps(body_obj, sort_keys=True).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()
            return

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

    server = ThreadingHTTPServer((host, port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server
