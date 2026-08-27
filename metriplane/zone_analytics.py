# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from metriplane.schema import ObjectStateModel, ZoneEventModel
from metriplane.zones import ZoneMap


def _now_ts() -> float:
    return float(time.time())


@dataclass
class ZoneAnalytics:
    """
    Stateful zone analytics:
    - Determines zone per object (using pos_world XY).
    - Emits zone_enter/zone_exit events on changes.
    - Accumulates dwell time per (object, zone).
    - Counts transitions per (from_zone, to_zone).

    IMPORTANT:
    Real streams often do: zoneA -> None -> zoneB (briefly outside zone polygon).
    We therefore count transitions across a short "gap" via _pending_exit.
    """

    zone_map: ZoneMap

    # If an object exits zone A -> None, then later enters zone B, count A->B
    # as long as the gap is not ridiculously long.
    # Set higher if your zones have large gaps or you move slowly across the middle.
    transition_window_s: float = 10.0

    _last_zone: Dict[str, str | None] = field(default_factory=dict)
    _enter_ts: Dict[str, float] = field(default_factory=dict)  # per object, current-zone entry time
    _dwell_s: Dict[Tuple[str, str], float] = field(default_factory=dict)  # (oid, zone) -> seconds
    _transitions: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (from,to) -> count
    _events: List[ZoneEventModel] = field(default_factory=list)

    # oid -> (from_zone, ts_exit)
    _pending_exit: Dict[str, Tuple[str, float]] = field(default_factory=dict)

    def _zone_for_obj(self, obj: ObjectStateModel) -> str | None:
        pw = obj.pos_world
        if not pw or len(pw) < 2:
            return None
        x = float(pw[0])
        y = float(pw[1])
        return self.zone_map.zone_for_xy(x, y)

    def _accumulate_exit(self, oid: str, zone: str, ts: float) -> None:
        enter = self._enter_ts.get(oid)
        if enter is None:
            return
        dt = float(ts) - float(enter)
        if dt < 0:
            return
        key = (oid, zone)
        self._dwell_s[key] = float(self._dwell_s.get(key, 0.0)) + float(dt)
        self._enter_ts.pop(oid, None)

    def _prune_pending(self, ts: float) -> None:
        """Drop old pending exits so they don't create weird late transitions."""
        if not self._pending_exit:
            return
        cutoff = float(ts) - float(self.transition_window_s)
        for oid, (_z, t_exit) in list(self._pending_exit.items()):
            if float(t_exit) < cutoff:
                self._pending_exit.pop(oid, None)

    def update(
        self, ts: float, objects: List[ObjectStateModel]
    ) -> tuple[List[ObjectStateModel], List[ZoneEventModel]]:
        """
        Update analytics with the *current tracked objects list*.
        Returns:
          - objects_out: same objects but with .zone filled in (best effort)
          - events_now: events emitted at this ts
        """
        ts_f = float(ts)
        self._prune_pending(ts_f)

        # Compute current zone per object id
        current: Dict[str, str | None] = {}
        objects_out: List[ObjectStateModel] = []

        for obj in objects:
            oid = str(obj.id)
            z = self._zone_for_obj(obj)
            current[oid] = z
            try:
                objects_out.append(obj.model_copy(update={"zone": z}))
            except Exception:
                objects_out.append(obj)

        events_now: List[ZoneEventModel] = []

        prev_ids = set(self._last_zone.keys())
        now_ids = set(current.keys())

        # Handle disappeared objects (expired from registry)
        disappeared = prev_ids - now_ids
        for oid in disappeared:
            prev_zone = self._last_zone.get(oid)
            if prev_zone is not None:
                # exit event
                events_now.append(
                    ZoneEventModel(type="zone_exit", object_id=oid, zone=str(prev_zone), ts=ts_f)
                )
                self._events.append(events_now[-1])

                # dwell close
                self._accumulate_exit(oid, str(prev_zone), ts_f)

                # store pending exit (so a later reappearance can form a transition)
                self._pending_exit[oid] = (str(prev_zone), ts_f)

            self._last_zone.pop(oid, None)
            self._enter_ts.pop(oid, None)

        # Handle present objects (zone changes)
        for oid, new_zone in current.items():
            prev_zone = self._last_zone.get(oid)

            if prev_zone == new_zone:
                continue

            # exiting old zone
            if prev_zone is not None:
                events_now.append(
                    ZoneEventModel(type="zone_exit", object_id=oid, zone=str(prev_zone), ts=ts_f)
                )
                self._events.append(events_now[-1])
                self._accumulate_exit(oid, str(prev_zone), ts_f)

                # If we are going into "no zone", store pending exit.
                if new_zone is None:
                    self._pending_exit[oid] = (str(prev_zone), ts_f)
                else:
                    # direct zone->zone transition, pending no longer relevant
                    self._pending_exit.pop(oid, None)

            # entering new zone
            if new_zone is not None:
                events_now.append(
                    ZoneEventModel(type="zone_enter", object_id=oid, zone=str(new_zone), ts=ts_f)
                )
                self._events.append(events_now[-1])
                self._enter_ts[oid] = ts_f

            # ---- Transition counting ----
            # A) direct: zoneA -> zoneB in one step
            if prev_zone is not None and new_zone is not None and str(prev_zone) != str(new_zone):
                k = (str(prev_zone), str(new_zone))
                self._transitions[k] = int(self._transitions.get(k, 0)) + 1

            # B) indirect: zoneA -> None -> zoneB
            if prev_zone is None and new_zone is not None:
                pending = self._pending_exit.get(oid)
                if pending is not None:
                    from_zone, ts_exit = pending
                    if (ts_f - float(ts_exit)) <= float(
                        self.transition_window_s
                    ) and from_zone != str(new_zone):
                        k = (str(from_zone), str(new_zone))
                        self._transitions[k] = int(self._transitions.get(k, 0)) + 1
                    # once we re-enter any zone, clear pending
                    self._pending_exit.pop(oid, None)

            self._last_zone[oid] = new_zone

        return objects_out, events_now

    def finalize(self, ts_end: float | None = None) -> None:
        """Close any open zone intervals so dwell is correct at export time."""
        ts_f = float(ts_end) if ts_end is not None else _now_ts()
        for oid, z in list(self._last_zone.items()):
            if z is None:
                continue
            self._accumulate_exit(oid, str(z), ts_f)

    def export_csv(self, out_dir: Path, prefix: str = "m6") -> dict[str, Path]:
        """
        Export:
          - <prefix>_zone_events.csv
          - <prefix>_zone_dwell.csv
          - <prefix>_zone_transitions.csv
          - <prefix>_zone_dwell_by_zone.csv
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        # Events
        p_events = out_dir / f"{prefix}_zone_events.csv"
        with p_events.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ts", "type", "object_id", "zone"])
            w.writeheader()
            for e in self._events:
                w.writerow(
                    {
                        "ts": float(e.ts),
                        "type": str(e.type),
                        "object_id": str(e.object_id),
                        "zone": str(e.zone),
                    }
                )
        paths["events"] = p_events

        # Dwell per object-zone
        p_dwell = out_dir / f"{prefix}_zone_dwell.csv"
        with p_dwell.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["object_id", "zone", "dwell_s"])
            w.writeheader()
            for (oid, zone), dwell in sorted(
                self._dwell_s.items(), key=lambda kv: (kv[0][0], kv[0][1])
            ):
                w.writerow({"object_id": oid, "zone": zone, "dwell_s": float(dwell)})
        paths["dwell"] = p_dwell

        # Dwell aggregated by zone
        dwell_by_zone: Dict[str, float] = {}
        for (_, zone), dwell in self._dwell_s.items():
            dwell_by_zone[zone] = float(dwell_by_zone.get(zone, 0.0)) + float(dwell)

        p_dwell_zone = out_dir / f"{prefix}_zone_dwell_by_zone.csv"
        with p_dwell_zone.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["zone", "dwell_s"])
            w.writeheader()
            for zone, dwell in sorted(dwell_by_zone.items(), key=lambda kv: kv[0]):
                w.writerow({"zone": zone, "dwell_s": float(dwell)})
        paths["dwell_by_zone"] = p_dwell_zone

        # Transitions
        p_trans = out_dir / f"{prefix}_zone_transitions.csv"
        with p_trans.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["from_zone", "to_zone", "count"])
            w.writeheader()
            for (fz, tz), c in sorted(
                self._transitions.items(), key=lambda kv: (kv[0][0], kv[0][1])
            ):
                w.writerow({"from_zone": fz, "to_zone": tz, "count": int(c)})
        paths["transitions"] = p_trans

        return paths
