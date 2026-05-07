from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Tuple

import cv2  # type: ignore
import numpy as np  # type: ignore
import yaml


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """
    Camera intrinsics + distortion.

    camera_matrix: 3x3
    dist_coeffs: (N,) where N is typically 5 or 8
    """
    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    image_width: int | None = None
    image_height: int | None = None

    def undistort_points_px(self, pts_px: Iterable[Tuple[float, float]]) -> list[tuple[float, float]]:
        """
        Undistort pixel points and return in pixel coordinates (same scale as input).

        Uses cv2.undistortPoints(..., P=K) so output is still in pixel space.
        """
        pts = np.array([[float(x), float(y)] for (x, y) in pts_px], dtype=np.float32)
        if pts.size == 0:
            return []
        pts = pts.reshape(-1, 1, 2)  # (N,1,2)

        K = np.asarray(self.camera_matrix, dtype=np.float64)
        D = np.asarray(self.dist_coeffs, dtype=np.float64).reshape(-1, 1)

        und = cv2.undistortPoints(pts, K, D, P=K)
        und = und.reshape(-1, 2)
        return [(float(p[0]), float(p[1])) for p in und]


def load_intrinsics(path: Path) -> CameraIntrinsics:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("intrinsics file must parse to a mapping")

    K = data.get("camera_matrix")
    D = data.get("dist_coeffs")

    if not isinstance(K, list) or len(K) != 3:
        raise ValueError("intrinsics: camera_matrix must be 3x3 list")
    km = np.array(K, dtype=np.float64)
    if km.shape != (3, 3):
        raise ValueError(f"intrinsics: camera_matrix must be 3x3, got {km.shape}")

    if not isinstance(D, list) or len(D) < 4:
        raise ValueError("intrinsics: dist_coeffs must be list (len>=4)")
    dc = np.array(D, dtype=np.float64).reshape(-1)

    w = data.get("image_width")
    h = data.get("image_height")
    iw = int(w) if isinstance(w, (int, float, str)) and str(w).strip() else None
    ih = int(h) if isinstance(h, (int, float, str)) and str(h).strip() else None

    return CameraIntrinsics(camera_matrix=km, dist_coeffs=dc, image_width=iw, image_height=ih)
