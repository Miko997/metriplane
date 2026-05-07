from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from metriplane.schema import ObjectStateModel


@dataclass
class ObjectRegistry:
    """
    Keeps last-known ObjectStateModels alive for a short time after they disappear.

    - Update with detections each frame
    - Expire objects not seen for timeout_s
    """
    timeout_s: float = 1.5
    objects: Dict[str, ObjectStateModel] = field(default_factory=dict)
    last_seen_s: Dict[str, float] = field(default_factory=dict)

    def update(self, detections: Iterable[ObjectStateModel], now_s: float) -> List[str]:
        # Insert/update seen objects
        for obj in detections:
            oid = str(obj.id)
            self.objects[oid] = obj
            self.last_seen_s[oid] = now_s

        # Expire stale objects
        cutoff = now_s - self.timeout_s
        expired = [oid for oid, ts in self.last_seen_s.items() if ts < cutoff]
        for oid in expired:
            self.last_seen_s.pop(oid, None)
            self.objects.pop(oid, None)

        return expired

    def snapshot(self) -> List[ObjectStateModel]:
        # Stable list for frame emission
        return list(self.objects.values())

    def tracked_ids(self) -> List[str]:
        return sorted(self.objects.keys())
