# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

from metriplane.schema import ObjectStateModel


@dataclass
class OverlayConfig:
    # If set, ONLY these ids get labels (huge readability improvement)
    include_ids: Optional[Set[str]] = None

    # Only these ids show x/y line (robot only by default)
    show_xy_ids: Set[str] = field(default_factory=set)

    # General toggles
    show_zone: bool = True
    show_units: bool = True

    # Visual tuning
    font_scale: float = 0.55
    thickness: int = 1
    pad: int = 6
    bg_alpha: float = 0.70

    # Safety valve
    max_labels: int = 12

    # If True: skip objects that don't have pixel coords (extra["px"])
    require_px: bool = True


def _rects_intersect(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or bx1 > ax2 or ay2 < by1 or by1 > ay2)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _get_px(obj: ObjectStateModel) -> Optional[Tuple[int, int]]:
    extra = obj.extra or {}
    px = extra.get("px")
    if not px or not isinstance(px, (list, tuple)) or len(px) < 2:
        return None
    try:
        return (int(float(px[0])), int(float(px[1])))
    except Exception:
        return None


def _format_lines(
    obj: ObjectStateModel,
    *,
    units: str = "m",
    show_xy: bool = True,
    show_zone: bool = True,
    show_units: bool = True,
) -> List[str]:
    oid = str(obj.id)
    zone = getattr(obj, "zone", None) or "-"
    pw = obj.pos_world or None

    lines: List[str] = []

    # Line 1: short
    if oid == "7":
        lines.append("robot id=7")
    else:
        lines.append(f"id={oid}")

    # Line 2: x/y (robot only usually)
    if show_xy and pw and len(pw) >= 2:
        x = float(pw[0])
        y = float(pw[1])
        if show_units:
            lines.append(f"x={x:.3f}  y={y:.3f}  {units}")
        else:
            lines.append(f"x={x:.3f}  y={y:.3f}")

    # Line 3: zone
    if show_zone:
        lines.append(f"zone={zone}")

    return lines


def draw_overlay_bgr(
    bgr: np.ndarray,
    objects: Sequence[ObjectStateModel],
    cfg: OverlayConfig,
    *,
    units: str = "m",
) -> np.ndarray:
    """
    Draw readable labels:
    - Optional include_ids whitelist
    - Robot shows x/y + zone, others mostly id + zone
    - Tries multiple offsets to reduce overlap
    """
    if bgr is None or bgr.size == 0:
        return bgr

    h, w = bgr.shape[:2]

    # Candidate offsets (dx, dy) around marker center
    offsets = [
        (12, -12),
        (12, 12),
        (-12, -12),
        (-12, 12),
        (24, -24),
        (24, 24),
        (-24, -24),
        (-24, 24),
        (0, -28),
        (0, 28),
    ]

    placed: List[Tuple[int, int, int, int]] = []

    # Prefer stable ordering (top-to-bottom, left-to-right)
    items = []
    for obj in objects:
        oid = str(obj.id)

        if cfg.include_ids is not None and oid not in cfg.include_ids:
            continue

        px = _get_px(obj)
        if cfg.require_px and px is None:
            continue

        items.append((oid, px, obj))

    # Limit count early
    items = items[: cfg.max_labels]

    # Sort by pixel if available
    items.sort(key=lambda t: (t[1][1] if t[1] else 10**9, t[1][0] if t[1] else 10**9))

    out = bgr.copy()

    for oid, px, obj in items:
        if px is None:
            continue

        # robot gets XY, others don't
        show_xy = oid in cfg.show_xy_ids
        lines = _format_lines(
            obj,
            units=units,
            show_xy=show_xy,
            show_zone=cfg.show_zone,
            show_units=cfg.show_units,
        )

        # compute box size
        line_sizes = []
        max_tw = 0
        total_th = 0
        baseline_max = 0
        for line in lines:
            (tw, th), baseline = cv2.getTextSize(
                line, cv2.FONT_HERSHEY_SIMPLEX, cfg.font_scale, cfg.thickness
            )
            line_sizes.append((tw, th, baseline))
            max_tw = max(max_tw, tw)
            baseline_max = max(baseline_max, baseline)
            total_th += th + baseline + 2

        box_w = max_tw + 2 * cfg.pad
        box_h = total_th + 2 * cfg.pad

        cx, cy = px

        chosen = None
        for dx, dy in offsets:
            x1 = cx + dx
            y1 = cy + dy - box_h  # prefer above
            x1 = _clamp(x1, 0, max(0, w - box_w))
            y1 = _clamp(y1, 0, max(0, h - box_h))
            rect = (x1, y1, x1 + box_w, y1 + box_h)

            if any(_rects_intersect(rect, r) for r in placed):
                continue
            chosen = rect
            break

        # if every offset overlaps, just clamp near the marker
        if chosen is None:
            x1 = _clamp(cx + 12, 0, max(0, w - box_w))
            y1 = _clamp(cy - 12 - box_h, 0, max(0, h - box_h))
            chosen = (x1, y1, x1 + box_w, y1 + box_h)

        placed.append(chosen)
        x1, y1, x2, y2 = chosen

        # alpha background
        overlay = out.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), thickness=-1)
        out = cv2.addWeighted(overlay, cfg.bg_alpha, out, 1.0 - cfg.bg_alpha, 0)

        # text
        y_cursor = y1 + cfg.pad + 14
        for line, (tw, th, baseline) in zip(lines, line_sizes):
            cv2.putText(
                out,
                line,
                (x1 + cfg.pad, y_cursor),
                cv2.FONT_HERSHEY_SIMPLEX,
                cfg.font_scale,
                (255, 255, 255),
                cfg.thickness,
                cv2.LINE_AA,
            )
            y_cursor += th + baseline + 6

    return out
