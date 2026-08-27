# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse


def main_traces(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane traces")
    sub = p.add_subparsers(dest="cmd", required=True)

    sm = sub.add_parser("summarize", help="Summarize object traces from session JSONL")
    sm.add_argument("--session", required=True)
    sm.add_argument("--objects", default=None)

    ex = sub.add_parser("export", help="Export trace points as CSV")
    ex.add_argument("--session", required=True)
    ex.add_argument("--objects", default=None)
    ex.add_argument("--out", required=True)

    ob = sub.add_parser("object", help="Show trace summary for one object")
    ob.add_argument("object_id")
    ob.add_argument("--session", required=True)
    ob.add_argument("--objects", default=None)

    args = p.parse_args(argv)

    from metriplane.trace.store import TraceStore

    store = TraceStore(registry_path=args.objects)
    store.load_session(args.session)

    if args.cmd == "summarize":
        for s in store.summarize():
            zones = ",".join(s.zones_visited) if s.zones_visited else "-"
            print(
                f"{s.object_id}  dur={s.duration_s}s  dist={s.total_distance_m}m"
                f"  zones={zones}  gaps={s.gap_count}"
            )
        return 0

    if args.cmd == "export":
        store.export_csv(args.out)
        print(f"Exported {len(store.points())} points to {args.out}")
        return 0

    if args.cmd == "object":
        summaries = {s.object_id: s for s in store.summarize()}
        if args.object_id not in summaries:
            print(f"not found: {args.object_id}")
            return 1
        s = summaries[args.object_id]
        print(f"object_id:       {s.object_id}")
        print(f"marker_id:       {s.marker_id}")
        print(f"duration_s:      {s.duration_s}")
        print(f"total_distance:  {s.total_distance_m}m")
        print(f"max_speed:       {s.max_speed_mps} m/s")
        print(f"zones_visited:   {', '.join(s.zones_visited) or '-'}")
        print(f"point_count:     {s.point_count}")
        print(f"gap_count:       {s.gap_count}")
        return 0

    return 1
