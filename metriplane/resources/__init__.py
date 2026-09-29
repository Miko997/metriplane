# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Installed, immutable runtime resources for Metriplane."""

from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Iterator, cast

DASHBOARD_RESOURCES = (
    "app.js",
    "atlas.html",
    "benchmarks.html",
    "command_center.css",
    "command_center.html",
    "command_center.js",
    "command_center_data.json",
    "command_center_live.html",
    "command_center_live.js",
    "help.html",
    "icons/metriplane-api-bridge.svg",
    "icons/metriplane-calibration-target.svg",
    "icons/metriplane-camera-video.svg",
    "icons/metriplane-coordinate-grid.svg",
    "icons/metriplane-dashboard-metrics.svg",
    "icons/metriplane-detect-markers.svg",
    "icons/metriplane-floor-state.svg",
    "icons/metriplane-health-monitor.svg",
    "icons/metriplane-homography-calibration.svg",
    "icons/metriplane-integration-ready.svg",
    "icons/metriplane-metric-xy.svg",
    "icons/metriplane-multi-camera-fusion.svg",
    "icons/metriplane-object-tracking.svg",
    "icons/metriplane-observability-health.svg",
    "icons/metriplane-replay-logs.svg",
    "icons/metriplane-schema-first.svg",
    "icons/metriplane-state-stream.svg",
    "icons/metriplane-websocket-json.svg",
    "icons/metriplane-zones-events.svg",
    "index.html",
    "integrations.html",
    "mp_nav.js",
    "operator.html",
    "operator.js",
    "product_actions.js",
    "report.html",
    "run.html",
    "runtime.html",
    "settings.html",
    "style.css",
)

BUNDLED_CONFIG_RESOURCES = (
    "configs/atlas/saved_queries.yaml",
    "configs/fusion_health_300fps.yaml",
)

RUNTIME_RESOURCES = tuple(f"dashboard/{path}" for path in DASHBOARD_RESOURCES) + (
    BUNDLED_CONFIG_RESOURCES
)


def resource(relative_path: str):  # type: ignore[no-untyped-def]
    """Return one declared installed resource as an importlib Traversable."""
    pure = PurePosixPath(relative_path)
    if pure.as_posix() != relative_path or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("runtime resource path must be canonical and relative")
    if relative_path not in RUNTIME_RESOURCES:
        raise KeyError(relative_path)
    return resources.files(__package__).joinpath(*pure.parts)


def read_bytes(relative_path: str) -> bytes:
    """Read one declared immutable resource without assuming a filesystem install."""
    return cast(bytes, resource(relative_path).read_bytes())


@contextmanager
def dashboard_directory() -> Iterator[Path]:
    """Materialize the dashboard resource tree for the bounded local server lifetime."""
    dashboard = resources.files(__package__).joinpath("dashboard")
    with resources.as_file(dashboard) as path:
        yield path
