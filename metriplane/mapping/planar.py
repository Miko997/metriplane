# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from metriplane.calibration.camera import CameraIntrinsics, load_intrinsics


@dataclass(frozen=True, slots=True)
class HomographyMapping:
    H: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    units: str = "meters"

    # Meaning:
    # True  -> the homography was fit in UNDISTORTED pixel space,
    #          so runtime MUST undistort detections before applying H.
    # False -> the homography was fit in RAW pixel space,
    #          so runtime MUST NOT undistort.
    undistort_points: bool = False

    # Optional hint written by the calibrator
    intrinsics_file: str | None = None

    def pixel_to_world_xy(self, u: float, v: float) -> tuple[float, float] | None:
        (h11, h12, h13), (h21, h22, h23), (h31, h32, h33) = self.H
        w = (h31 * u) + (h32 * v) + h33
        if abs(w) < 1e-12:
            return None
        x = ((h11 * u) + (h12 * v) + h13) / w
        y = ((h21 * u) + (h22 * v) + h23) / w
        return (float(x), float(y))


@dataclass(frozen=True, slots=True)
class PlanarMapper:
    mapping: HomographyMapping
    intrinsics: CameraIntrinsics | None = None

    def pixel_to_world_xy(self, u: float, v: float) -> tuple[float, float] | None:
        uu, vv = float(u), float(v)

        # IMPORTANT:
        # Only undistort when mapping was fit in UNDISTORTED space.
        if self.intrinsics is not None and self.mapping.undistort_points:
            (uu, vv) = self.intrinsics.undistort_points_px([(uu, vv)])[0]

        return self.mapping.pixel_to_world_xy(uu, vv)


def load_homography(path: Path) -> HomographyMapping:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid homography file (must parse to dict). Path={path}")

    H_raw = data.get("homography") or data.get("H") or data.get("matrix")
    if H_raw is None:
        raise ValueError(
            "Invalid homography file (missing 3x3 matrix). "
            "Expected one of keys: homography/H/matrix. "
            f"Got keys={list(data.keys())}. Path={path}"
        )
    if not isinstance(H_raw, list) or len(H_raw) != 3:
        raise ValueError(
            f"Invalid homography: expected 3 rows, got {type(H_raw)} len={len(H_raw) if hasattr(H_raw, '__len__') else '?'} Path={path}"
        )

    rows: list[tuple[float, float, float]] = []
    for r in H_raw:
        if not isinstance(r, list) or len(r) != 3:
            raise ValueError(f"Invalid homography row (expected len=3 list): {r} Path={path}")
        rows.append((float(r[0]), float(r[1]), float(r[2])))

    units = str(data.get("units") or "meters")
    und = bool(data.get("undistort_points", False))
    intr_file = data.get("intrinsics_file", None)
    intr_file = str(intr_file) if intr_file not in (None, "null") else None

    return HomographyMapping(
        H=(rows[0], rows[1], rows[2]),
        units=units,
        undistort_points=und,
        intrinsics_file=intr_file,
    )


def save_homography(
    path: Path,
    *,
    H: Iterable[Iterable[float]],
    units: str = "meters",
    extra: dict[str, Any] | None = None,
) -> None:
    h_list = [[float(v) for v in row] for row in H]
    payload: dict[str, Any] = {"units": units, "homography": h_list}
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_planar_mapper(mapping_path: Path, intrinsics_path: Optional[Path] = None) -> PlanarMapper:
    # Load mapping matrix + flags
    mapping = load_homography(mapping_path)

    # Respect mapping YAML's "intrinsics_file" directive, but distinguish:
    # - key absent: do NOT override the caller-provided intrinsics_path
    # - key present with null/empty: explicitly disable intrinsics loading
    # - key present with string: use it if caller didn't provide a path
    data: Any = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict) and ("intrinsics_file" in data):
        intr_file = data.get("intrinsics_file")
        # explicit disable
        if intr_file is None or str(intr_file).strip().lower() in ("", "null", "none"):
            intrinsics_path = None
        # mapping provides an intrinsics file, and caller didn't override
        elif intrinsics_path is None and isinstance(intr_file, str) and intr_file.strip():
            p = Path(intr_file.strip())
            intrinsics_path = p if p.is_absolute() else (mapping_path.parent / p)

    intr: CameraIntrinsics | None = None
    if intrinsics_path is not None:
        intr = load_intrinsics(intrinsics_path)

    return PlanarMapper(mapping=mapping, intrinsics=intr)
