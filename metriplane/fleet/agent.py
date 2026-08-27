# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from metriplane.fleet.exporters import JsonlHeartbeatExporter
from metriplane.fleet.heartbeat import FleetHeartbeat

log = logging.getLogger("metriplane.fleet")


@dataclass
class FleetAgentConfig:
    node_id: str = "node_01"
    heartbeat_interval_s: float = 5.0
    output_path: str | None = None
    run_id: str | None = None
    git_commit: str | None = None
    config_hash: str | None = None


class FleetAgent:
    """
    Emits periodic node heartbeats for multi-node (fleet) deployments.

    The agent pulls live values through a single callback returning a metrics dict, so it
    stays decoupled from runtime internals. Heartbeat emission never raises into the
    runtime (exceptions are caught and logged).
    """

    def __init__(
        self,
        config: FleetAgentConfig,
        metrics_provider: Callable[[], dict[str, Any]] | None = None,
        exporter: JsonlHeartbeatExporter | None = None,
    ):
        self.config = config
        self._metrics_provider = metrics_provider or (lambda: {})
        self._exporter = exporter
        if self._exporter is None and config.output_path:
            self._exporter = JsonlHeartbeatExporter(config.output_path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def build_heartbeat(self) -> FleetHeartbeat:
        try:
            m = self._metrics_provider() or {}
        except Exception as e:
            log.warning("fleet metrics provider failed: %s", e)
            m = {}
        return FleetHeartbeat(
            node_id=self.config.node_id,
            ts=time.time(),
            run_id=self.config.run_id,
            git_commit=self.config.git_commit,
            config_hash=self.config.config_hash,
            health_overall=str(m.get("health_overall", "OK")),
            fps=m.get("fps"),
            objects_tracked=m.get("objects_tracked"),
            active_incidents=m.get("active_incidents"),
            frames_total=m.get("frames_total"),
            frames_dropped_total=m.get("frames_dropped_total"),
        )

    def emit_once(self) -> FleetHeartbeat:
        hb = self.build_heartbeat()
        if self._exporter is not None:
            self._exporter.publish(hb)
        return hb

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.emit_once()
            except Exception as e:  # pragma: no cover - defensive
                log.warning("fleet heartbeat emit failed: %s", e)
            self._stop.wait(self.config.heartbeat_interval_s)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fleet-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._exporter is not None:
            self._exporter.close()

    @classmethod
    def from_config_dict(
        cls,
        data: dict[str, Any] | None,
        metrics_provider: Callable[[], dict[str, Any]] | None = None,
        run_dir: str | Path | None = None,
        run_id: str | None = None,
        git_commit: str | None = None,
        config_hash: str | None = None,
    ) -> "FleetAgent | None":
        if not data or not data.get("enabled"):
            return None
        out = data.get("output_file", "fleet_heartbeat.jsonl")
        if run_dir is not None:
            out = str(Path(run_dir) / out)
        cfg = FleetAgentConfig(
            node_id=str(data.get("node_id", "node_01")),
            heartbeat_interval_s=float(data.get("heartbeat_interval_s", 5.0)),
            output_path=out,
            run_id=run_id,
            git_commit=git_commit,
            config_hash=config_hash,
        )
        return cls(cfg, metrics_provider=metrics_provider)
