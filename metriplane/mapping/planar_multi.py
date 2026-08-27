# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from metriplane.mapping.planar import PlanarMapper, load_planar_mapper


def _read_anchor_rmse(mapping_path: Path) -> float | None:
    try:
        data: Any = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            v = data.get("anchor_rmse")
            if v is not None:
                return float(v)
    except Exception:
        return None
    return None


@dataclass(frozen=True, slots=True)
class CameraPlanar:
    camera_id: str
    mapper: PlanarMapper
    mapping_path: Path
    intrinsics_path: Path | None
    anchor_rmse: float | None


@dataclass(frozen=True, slots=True)
class MultiPlanarMapper:
    cams: dict[str, CameraPlanar]

    @property
    def units(self) -> str:
        first = next(iter(self.cams.values()))
        return str(first.mapper.mapping.units)

    def pixel_to_world_xy(self, camera_id: str, u: float, v: float) -> tuple[float, float] | None:
        cam = self.cams.get(str(camera_id))
        if cam is None:
            return None
        return cam.mapper.pixel_to_world_xy(float(u), float(v))

    def rmse_for(self, camera_id: str) -> float | None:
        cam = self.cams.get(str(camera_id))
        if cam is None:
            return None
        return cam.anchor_rmse


def load_multi_planar_mapper(
    *,
    mapping_by_camera: dict[str, Path],
    intrinsics_by_camera: dict[str, Path | None],
) -> MultiPlanarMapper:
    cams: dict[str, CameraPlanar] = {}

    for cid, mp in mapping_by_camera.items():
        ip = intrinsics_by_camera.get(cid)
        mapper = load_planar_mapper(mp, ip)
        cams[str(cid)] = CameraPlanar(
            camera_id=str(cid),
            mapper=mapper,
            mapping_path=mp,
            intrinsics_path=ip,
            anchor_rmse=_read_anchor_rmse(mp),
        )

    if not cams:
        raise ValueError("no camera mappers loaded")

    units_by_camera = {
        camera_id: str(camera.mapper.mapping.units).strip().lower()
        for camera_id, camera in cams.items()
    }
    unique_units = set(units_by_camera.values())
    if len(unique_units) != 1:
        detail = ", ".join(
            f"{camera_id}={units_by_camera[camera_id]}" for camera_id in sorted(units_by_camera)
        )
        raise ValueError(f"camera mapping units must match ({detail})")

    return MultiPlanarMapper(cams=cams)
