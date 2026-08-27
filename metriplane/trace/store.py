# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from metriplane.sentinel.registry import ObjectRegistryConfig


@dataclass
class TracePoint:
    ts: float
    object_id: str
    marker_id: str
    x_m: float | None
    y_m: float | None
    speed_mps: float | None
    zone: str | None
    run_id: str | None


@dataclass
class ObjectTraceSummary:
    object_id: str
    marker_id: str
    run_id: str | None
    first_ts: float
    last_ts: float
    duration_s: float
    total_distance_m: float
    max_speed_mps: float
    zones_visited: list[str]
    dwell_by_zone: dict[str, float]
    point_count: int
    gap_count: int


def _load_registry_map(registry_path: str | Path) -> dict[int, str]:
    try:
        import yaml

        data = yaml.safe_load(Path(registry_path).read_text())
        return {int(e["marker_id"]): e["object_id"] for e in data.get("objects", [])}
    except Exception:
        return {}


class TraceStore:
    def __init__(
        self,
        registry_path: str | Path | None = None,
        *,
        registry: ObjectRegistryConfig | None = None,
    ):
        self._registry: dict[int, str] = {}
        if registry is not None:
            self._registry = {entry.marker_id: entry.object_id for entry in registry.objects}
        elif registry_path:
            self._registry = _load_registry_map(registry_path)
        self._points: list[TracePoint] = []

    def _resolve(self, raw_id: str) -> str:
        try:
            mid = int(raw_id)
            return self._registry.get(mid, f"marker_{raw_id}")
        except (ValueError, TypeError):
            return f"marker_{raw_id}"

    def _load_session_lines(self, lines: list[str]) -> None:
        from metriplane.schema import FrameStateModel, frame_time_s

        self._points = []
        run_id: str | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                frame = FrameStateModel.model_validate(data)
            except Exception:
                continue
            if frame.run_id:
                run_id = frame.run_id
            objects = frame.fused if frame.fused is not None else frame.objects
            for obj in objects:
                x_m = obj.pos_world[0] if obj.pos_world else None
                y_m = obj.pos_world[1] if obj.pos_world else None
                speed: float | None = None
                if obj.vel_world:
                    vx, vy = obj.vel_world[0], obj.vel_world[1]
                    speed = math.sqrt(vx * vx + vy * vy)
                self._points.append(
                    TracePoint(
                        ts=frame_time_s(frame),
                        object_id=self._resolve(obj.id),
                        marker_id=obj.id,
                        x_m=x_m,
                        y_m=y_m,
                        speed_mps=speed,
                        zone=obj.zone,
                        run_id=run_id,
                    )
                )
        self._points.sort(key=lambda p: (p.object_id, p.ts))

    def load_session(self, session_path: str | Path) -> None:
        self._load_session_lines(Path(session_path).read_text().splitlines())

    def load_session_text(self, text: str) -> None:
        self._load_session_lines(text.splitlines())

    def points(self) -> list[TracePoint]:
        return list(self._points)

    def summarize(self) -> list[ObjectTraceSummary]:
        from itertools import groupby

        summaries = []
        for obj_id, group in groupby(self._points, key=lambda p: p.object_id):
            pts = list(group)
            if not pts:
                continue
            marker_id = pts[0].marker_id
            run_id = pts[0].run_id
            first_ts = pts[0].ts
            last_ts = pts[-1].ts
            duration_s = round(last_ts - first_ts, 4)

            total_dist = 0.0
            max_speed = 0.0
            gap_count = 0
            prev_x: float | None = None
            prev_y: float | None = None
            prev_ts: float | None = None

            zones_seen: list[str] = []
            zone_start: dict[str, float] = {}
            dwell_by_zone: dict[str, float] = {}
            current_zone: str | None = None

            for pt in pts:
                if (
                    prev_x is not None
                    and prev_y is not None
                    and pt.x_m is not None
                    and pt.y_m is not None
                ):
                    dx = pt.x_m - prev_x
                    dy = pt.y_m - prev_y
                    total_dist += math.sqrt(dx * dx + dy * dy)

                if pt.x_m is not None:
                    prev_x = pt.x_m
                if pt.y_m is not None:
                    prev_y = pt.y_m

                if pt.speed_mps is not None:
                    max_speed = max(max_speed, pt.speed_mps)

                if prev_ts is not None and (pt.ts - prev_ts) > 1.0:
                    gap_count += 1
                prev_ts = pt.ts

                z = pt.zone
                if z != current_zone:
                    if current_zone is not None:
                        elapsed = pt.ts - zone_start.get(current_zone, pt.ts)
                        dwell_by_zone[current_zone] = dwell_by_zone.get(current_zone, 0.0) + elapsed
                    current_zone = z
                    if z is not None:
                        if z not in zones_seen:
                            zones_seen.append(z)
                        zone_start[z] = pt.ts

            if current_zone is not None and pts:
                elapsed = pts[-1].ts - zone_start.get(current_zone, pts[-1].ts)
                dwell_by_zone[current_zone] = dwell_by_zone.get(current_zone, 0.0) + elapsed

            summaries.append(
                ObjectTraceSummary(
                    object_id=obj_id,
                    marker_id=marker_id,
                    run_id=run_id,
                    first_ts=first_ts,
                    last_ts=last_ts,
                    duration_s=duration_s,
                    total_distance_m=round(total_dist, 4),
                    max_speed_mps=round(max_speed, 4),
                    zones_visited=[z for z in zones_seen if z is not None],
                    dwell_by_zone={k: round(v, 3) for k, v in dwell_by_zone.items()},
                    point_count=len(pts),
                    gap_count=gap_count,
                )
            )
        return summaries

    def export_csv(self, out_path: str | Path) -> None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                ["ts", "object_id", "marker_id", "x_m", "y_m", "speed_mps", "zone", "run_id"]
            )
            for pt in self._points:
                w.writerow(
                    [
                        pt.ts,
                        pt.object_id,
                        pt.marker_id,
                        pt.x_m,
                        pt.y_m,
                        pt.speed_mps,
                        pt.zone,
                        pt.run_id,
                    ]
                )

    def summary_csv(self, out_path: str | Path) -> None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "object_id",
                    "marker_id",
                    "run_id",
                    "first_ts",
                    "last_ts",
                    "duration_s",
                    "total_distance_m",
                    "max_speed_mps",
                    "zones_visited",
                    "point_count",
                    "gap_count",
                ]
            )
            for s in self.summarize():
                w.writerow(
                    [
                        s.object_id,
                        s.marker_id,
                        s.run_id,
                        s.first_ts,
                        s.last_ts,
                        s.duration_s,
                        s.total_distance_m,
                        s.max_speed_mps,
                        "|".join(s.zones_visited),
                        s.point_count,
                        s.gap_count,
                    ]
                )
