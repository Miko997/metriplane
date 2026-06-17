# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass

from metriplane.sentinel.events import IncidentRecord, RuleAlert


@dataclass
class IncidentEngineConfig:
    """
    Controls how alerts are grouped into incidents.

    gap_close_s:
        An open incident closes when no matching alert is seen for longer than
        this many seconds. The close timestamp is the last alert ts.
    """
    gap_close_s: float = 1.0


def _incident_key(alert: RuleAlert) -> tuple[str, tuple[str, ...], str]:
    """Group alerts by rule, the set of objects involved, and zone."""
    return (alert.rule_id, tuple(sorted(alert.object_ids)), alert.zone or "")


def _summarize(rule_id: str, object_ids: list[str], zones: list[str],
               duration_s: float) -> str:
    objs = ", ".join(object_ids) if object_ids else "object"
    zone_part = f" in {zones[0]}" if zones else ""
    return f"{objs} triggered {rule_id}{zone_part} for {round(duration_s, 1)}s"


class IncidentEngine:
    """
    Groups RuleAlerts into IncidentRecords.

    Alerts sharing the same (rule_id, objects, zone) key that are contiguous in
    time (no gap longer than gap_close_s) form one incident. Incident IDs are
    sequential (inc_0001, ...) so output is deterministic across replays.
    """

    def __init__(self, config: IncidentEngineConfig | None = None):
        self.config = config or IncidentEngineConfig()
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"inc_{self._seq:04d}"

    def group(self, alerts: list[RuleAlert]) -> list[IncidentRecord]:
        ordered = sorted(alerts, key=lambda a: (a.ts, a.alert_id))

        # open incident per group key
        open_inc: dict[tuple, IncidentRecord] = {}
        open_last_ts: dict[tuple, float] = {}
        closed: list[IncidentRecord] = []

        def flush_expired(now_ts: float) -> None:
            for key in list(open_inc.keys()):
                if now_ts - open_last_ts[key] > self.config.gap_close_s:
                    inc = open_inc.pop(key)
                    last = open_last_ts.pop(key)
                    inc.close(last)
                    inc.summary = _summarize(inc.rule_id, inc.object_ids,
                                             inc.zones, inc.duration_s or 0.0)
                    closed.append(inc)

        for alert in ordered:
            flush_expired(alert.ts)
            key = _incident_key(alert)
            inc = open_inc.get(key)
            if inc is None:
                zones = [alert.zone] if alert.zone else []
                inc = IncidentRecord(
                    incident_id=self._next_id(),
                    run_id=alert.run_id,
                    rule_id=alert.rule_id,
                    severity=alert.severity,
                    status="open",
                    opened_ts=alert.ts,
                    object_ids=list(alert.object_ids),
                    zones=zones,
                    summary="",
                    alert_ids=[alert.alert_id],
                )
                open_inc[key] = inc
            else:
                inc.alert_ids.append(alert.alert_id)
                # escalate severity if a later alert is more severe
                if _severity_rank(alert.severity) > _severity_rank(inc.severity):
                    inc.severity = alert.severity
            open_last_ts[key] = alert.ts

        # close any still-open incidents at their last alert ts
        for key, inc in open_inc.items():
            last = open_last_ts[key]
            inc.close(last)
            inc.summary = _summarize(inc.rule_id, inc.object_ids,
                                     inc.zones, inc.duration_s or 0.0)
            closed.append(inc)

        closed.sort(key=lambda i: (i.opened_ts, i.incident_id))
        return closed


def _severity_rank(sev: str) -> int:
    return {"info": 0, "warning": 1, "critical": 2}.get(sev, 0)


def build_incidents(alerts: list[RuleAlert],
                    config: IncidentEngineConfig | None = None) -> list[IncidentRecord]:
    return IncidentEngine(config).group(alerts)
