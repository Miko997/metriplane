# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Iterable, Sequence

import cv2


def _as_px(obj: Any) -> tuple[int, int] | None:
    """
    Best-effort: tries obj.extra["px"] = (cx,cy).
    Returns (x,y) integer pixels or None.
    """
    extra = getattr(obj, "extra", None) or {}
    if isinstance(extra, dict):
        px = extra.get("px")
        if isinstance(px, (list, tuple)) and len(px) >= 2:
            try:
                return int(float(px[0])), int(float(px[1]))
            except Exception:
                return None
    return None


def _draw_multiline_box(
    img: Any,
    *,
    x: int,
    y: int,
    lines: Sequence[str],
    font_scale: float = 0.55,
    thickness: int = 2,
    pad: int = 4,
    line_gap: int = 3,
) -> None:
    """
    Draws a filled background rectangle + multiple text lines.
    (x,y) is top-left of the box; function clamps to frame bounds.
    """
    if not lines:
        return

    font = cv2.FONT_HERSHEY_SIMPLEX

    # measure text sizes
    sizes = [cv2.getTextSize(str(t), font, font_scale, thickness)[0] for t in lines]
    text_w = max(w for (w, h) in sizes)
    text_hs = [h for (w, h) in sizes]
    box_w = text_w + 2 * pad
    box_h = sum(text_hs) + (len(lines) - 1) * line_gap + 2 * pad

    h_img, w_img = img.shape[:2]

    # clamp box position into frame
    x0 = max(0, min(int(x), w_img - box_w - 1))
    y0 = max(0, min(int(y), h_img - box_h - 1))

    # background box
    cv2.rectangle(img, (x0, y0), (x0 + box_w, y0 + box_h), (0, 0, 0), -1)

    # text (white)
    yy = y0 + pad + text_hs[0]
    for i, line in enumerate(lines):
        cv2.putText(
            img,
            str(line),
            (x0 + pad, yy),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
        if i + 1 < len(lines):
            yy += text_hs[i + 1] + line_gap


def draw_tracking_overlay(
    frame_bgr: Any,
    objects: Iterable[Any],
    *,
    units: str = "meters",
) -> None:
    """
    Draw per-object label in 2–3 rows near the marker center if available:
      row1: id=<id>
      row2: x=... y=...
      row3: zone=<zone or '-'>
    """
    for obj in objects:
        oid = str(getattr(obj, "id", "?"))

        # world XY
        x_s = "-"
        y_s = "-"
        pw = getattr(obj, "pos_world", None)
        if isinstance(pw, (list, tuple)) and len(pw) >= 2:
            try:
                x_s = f"{float(pw[0]):.3f}"
                y_s = f"{float(pw[1]):.3f}"
            except Exception:
                pass

        zone = getattr(obj, "zone", None)
        zone_s = str(zone) if zone is not None else "-"

        lines = [
            f"id={oid}",
            f"x={x_s}  y={y_s}  {units}",
            f"zone={zone_s}",
        ]

        px = _as_px(obj)
        if px is not None:
            # offset so it doesn't sit exactly on marker
            x0, y0 = px[0] + 8, px[1] - 8
        else:
            # fallback: stack in top-left if no pixel location available
            x0, y0 = 10, 10

        _draw_multiline_box(frame_bgr, x=x0, y=y0, lines=lines)
