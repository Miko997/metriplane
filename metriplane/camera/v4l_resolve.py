# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from typing import Union


def resolve_v4l_to_index(dev: Union[int, str]) -> int:
    """
    Accepts:
      - 0 / 1 (int)
      - "0" / "1" (digit string)
      - "/dev/video2"
      - "/dev/v4l/by-id/..." (symlink to /dev/videoN)
      - "/dev/v4l/by-path/..." (symlink to /dev/videoN)
    Returns OpenCV index N (for /dev/videoN).
    """

    # 1) already an int
    if isinstance(dev, int):
        return int(dev)

    s = str(dev).strip()

    # 2) numeric string like "0"
    if s.isdigit():
        return int(s)

    # 3) /dev/videoN direct
    if s.startswith("/dev/video"):
        tail = s.replace("/dev/video", "").strip()
        if tail.isdigit():
            return int(tail)

    # 4) by-id / by-path symlink -> /dev/videoN
    p = Path(s)
    if p.exists():
        try:
            real = p.resolve()
        except Exception:
            real = p

        rp = str(real)
        if rp.startswith("/dev/video"):
            tail = rp.replace("/dev/video", "").strip()
            if tail.isdigit():
                return int(tail)

    raise ValueError(f"cannot resolve camera device to index: {dev}")
