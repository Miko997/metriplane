# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse


def main_query(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane query")
    sub = p.add_subparsers(dest="cmd", required=True)

    inc = sub.add_parser("incidents", help="Search incidents")
    inc.add_argument("--incidents", required=True)
    _add_filters(inc)

    al = sub.add_parser("alerts", help="Search alerts")
    al.add_argument("--alerts", required=True)
    _add_filters(al)

    tr = sub.add_parser("traces", help="Search trace summaries")
    tr.add_argument("--session", required=True)
    tr.add_argument("--objects", default=None)
    tr.add_argument("--object", default=None, help="Filter to one object_id")
    tr.add_argument("--zone", default=None, help="Filter to objects that visited a zone")

    args = p.parse_args(argv)

    if args.cmd == "incidents":
        return _query_incidents(args)
    if args.cmd == "alerts":
        return _query_alerts(args)
    if args.cmd == "traces":
        return _query_traces(args)
    return 1


def _add_filters(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--severity", default=None, choices=["info", "warning", "critical"])
    sp.add_argument("--rule", default=None, help="Filter by rule_id")
    sp.add_argument("--object", default=None, help="Filter by object_id")
    sp.add_argument("--zone", default=None, help="Filter by zone")


def _query_incidents(args: argparse.Namespace) -> int:
    from metriplane.sentinel.events import read_incidents_json

    rows = read_incidents_json(args.incidents)
    matched = [
        inc
        for inc in rows
        if (args.severity is None or inc.severity == args.severity)
        and (args.rule is None or inc.rule_id == args.rule)
        and (args.object is None or args.object in inc.object_ids)
        and (args.zone is None or args.zone in inc.zones)
    ]
    for inc in matched:
        print(
            f"{inc.incident_id}  {inc.rule_id}  {inc.severity}  "
            f"dur={inc.duration_s}s  objects={','.join(inc.object_ids)}"
        )
    print(f"# {len(matched)} of {len(rows)} incidents matched")
    return 0


def _query_alerts(args: argparse.Namespace) -> int:
    from metriplane.sentinel.events import read_alerts_jsonl

    rows = read_alerts_jsonl(args.alerts)
    matched = [
        a
        for a in rows
        if (args.severity is None or a.severity == args.severity)
        and (args.rule is None or a.rule_id == args.rule)
        and (args.object is None or args.object in a.object_ids)
        and (args.zone is None or a.zone == args.zone)
    ]
    for a in matched:
        objs = ",".join(a.object_ids)
        print(f"{a.ts}  {a.alert_id}  {a.rule_id}  {a.severity}  [{objs}]  zone={a.zone or '-'}")
    print(f"# {len(matched)} of {len(rows)} alerts matched")
    return 0


def _query_traces(args: argparse.Namespace) -> int:
    from metriplane.trace.store import TraceStore

    store = TraceStore(registry_path=args.objects)
    store.load_session(args.session)
    summaries = store.summarize()
    matched = [
        s
        for s in summaries
        if (args.object is None or s.object_id == args.object)
        and (args.zone is None or args.zone in s.zones_visited)
    ]
    for s in matched:
        zones = ",".join(s.zones_visited) if s.zones_visited else "-"
        print(
            f"{s.object_id}  dur={s.duration_s}s  dist={s.total_distance_m}m  "
            f"zones={zones}  gaps={s.gap_count}"
        )
    print(f"# {len(matched)} of {len(summaries)} traces matched")
    return 0
