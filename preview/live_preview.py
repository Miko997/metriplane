from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import cv2
import numpy as np


@dataclass
class LivePreview:
    scale: float = 1.0
    topdown_size: Tuple[int, int] = (720, 520)  # (w,h)

    def _resize(self, img: np.ndarray) -> np.ndarray:
        if self.scale == 1.0:
            return img
        return cv2.resize(img, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA)

    def render_cam(self, cam_name: str, frame_bgr: Optional[np.ndarray]) -> None:
        if frame_bgr is None:
            return
        cv2.imshow(cam_name, self._resize(frame_bgr))

    def render_topdown_layers(
        self,
        name: str,
        *,
        bounds: Tuple[float, float, float, float],  # (xmin,xmax,ymin,ymax)
        cam0_pts: Iterable[Tuple[str, float, float]],
        cam1_pts: Iterable[Tuple[str, float, float]],
        fused_pts: Iterable[Tuple[str, float, float]],
    ) -> None:
        xmin, xmax, ymin, ymax = bounds
        w, h = self.topdown_size
        img = np.zeros((h, w, 3), dtype=np.uint8)

        # border
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), (80, 80, 80), 1)

        def to_px(x: float, y: float) -> Tuple[int, int]:
            u = int(round((x - xmin) / max(xmax - xmin, 1e-9) * (w - 1)))
            v = int(round((ymax - y) / max(ymax - ymin, 1e-9) * (h - 1)))
            return u, v

        # colors (BGR)
        col_cam0 = (0, 255, 0)      # green
        col_cam1 = (0, 255, 255)    # yellow
        col_fused = (255, 255, 0)   # cyan-ish

        def draw_pts(pts: Iterable[Tuple[str, float, float]], col: Tuple[int, int, int], r: int) -> None:
            for oid, x, y in pts:
                u, v = to_px(float(x), float(y))
                if 0 <= u < w and 0 <= v < h:
                    cv2.circle(img, (u, v), r, col, -1)
                    cv2.putText(img, str(oid), (u + 7, v - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        # draw raw first, fused on top
        draw_pts(cam0_pts, col_cam0, 5)
        draw_pts(cam1_pts, col_cam1, 5)
        draw_pts(fused_pts, col_fused, 7)

        # legend
        cv2.putText(img, "cam0(raw)", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col_cam0, 2, cv2.LINE_AA)
        cv2.putText(img, "cam1(raw)", (120, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col_cam1, 2, cv2.LINE_AA)
        cv2.putText(img, "fused", (230, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col_fused, 2, cv2.LINE_AA)

        cv2.imshow(name, img)

    def tick(self) -> bool:
        key = cv2.waitKey(1) & 0xFF
        return key not in (27, ord("q"))

    def close(self) -> None:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
