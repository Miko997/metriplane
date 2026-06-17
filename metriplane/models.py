# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Frame:
    ts_cam_read: float
    image: Any
    camera_id: str | None = None
