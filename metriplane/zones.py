# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


@dataclass(frozen=True, slots=True)
class Zone:
    """A named polygon zone in world XY units (usually meters)."""
    name: str
    polygon: tuple[tuple[float, float], ...]  # (x,y) vertices, len>=3


@dataclass(frozen=True, slots=True)
class ZoneMap:
    """Collection of zones + convenience lookup."""
    units: str
    zones: tuple[Zone, ...]

    def zone_for_xy(self, x: float, y: float) -> str | None:
        for z in self.zones:
            if point_in_polygon(x, y, z.polygon):
                return z.name
        return None


def _as_float_xy(p: Any) -> tuple[float, float]:
    if not isinstance(p, (list, tuple)) or len(p) < 2:
        raise ValueError(f"invalid polygon point: {p!r}")
    return (float(p[0]), float(p[1]))


def _point_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float, eps: float = 1e-9) -> bool:
    # collinearity check via cross product
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > eps:
        return False
    # within bounding box
    if (min(ax, bx) - eps) <= px <= (max(ax, bx) + eps) and (min(ay, by) - eps) <= py <= (max(ay, by) + eps):
        return True
    return False


def point_in_polygon(x: float, y: float, poly: Sequence[tuple[float, float]]) -> bool:
    """
    Ray casting point-in-polygon.
    - Returns True if inside OR on edge.
    - poly: sequence of (x,y) vertices (len>=3)
    """
    n = len(poly)
    if n < 3:
        return False

    # If on edge -> inside
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        if _point_on_segment(x, y, ax, ay, bx, by):
            return True

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]

        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) + 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i

    return inside


def load_zones(path: Path) -> ZoneMap:
    """
    Load zones from YAML or JSON.

    Supported formats:

    YAML/JSON dict:
      schema_version: "1.0"   (optional)
      units: "meters"         (optional, default meters)
      zones:
        - name: "zone_a"
          polygon: [[x,y], [x,y], ...]
        - name: "zone_b"
          polygon: [[x,y], [x,y], ...]

    Or top-level list:
      - name: ...
        polygon: ...
    """
    if not path.is_file():
        raise FileNotFoundError(f"zones file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
    else:
        data = yaml.safe_load(raw)

    units = "meters"
    zones_raw: Any = None

    if isinstance(data, dict):
        units = str(data.get("units") or "meters")
        zones_raw = data.get("zones")
    elif isinstance(data, list):
        zones_raw = data
    else:
        raise ValueError("zones file must be a dict or list")

    if not isinstance(zones_raw, list) or not zones_raw:
        raise ValueError("zones file must contain a non-empty 'zones' list")

    zones: list[Zone] = []
    for z in zones_raw:
        if not isinstance(z, dict):
            continue
        name = str(z.get("name") or z.get("id") or "").strip()
        if not name:
            raise ValueError(f"zone missing name: {z!r}")

        poly_raw = z.get("polygon") or z.get("points")
        if not isinstance(poly_raw, list) or len(poly_raw) < 3:
            raise ValueError(f"zone '{name}' polygon must have >=3 points")

        poly = tuple(_as_float_xy(p) for p in poly_raw)
        zones.append(Zone(name=name, polygon=poly))

    if not zones:
        raise ValueError("no valid zones found")

    return ZoneMap(units=units, zones=tuple(zones))
