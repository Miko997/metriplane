from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Frame:
    ts_cam_read: float
    image: Any
    camera_id: str | None = None
