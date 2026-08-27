# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse

from metriplane.sentinel.events import IncidentRecord, RuleAlert


def main_incidents(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane incidents")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Detect incidents from a session")
    run.add_argument("--session", required=True)
    run.add_argument("--rules", required=True)
    run.add_argument("--objects", default=None)
    run.add_argument("--out", default=None, help="Write incidents JSON to this path")

    ls = sub.add_parser("list", help="List incidents from an incidents.json")
    ls.add_argument("--incidents", required=True)

    show = sub.add_parser("show", help="Show one incident")
    show.add_argument("incident_id")
    show.add_argument("--incidents", required=True)

    bundle = sub.add_parser("bundle", help="Export an evidence bundle for an incident")
    bundle.add_argument("incident_id")
    bundle.add_argument("--session", required=True)
    bundle.add_argument("--rules", required=True)
    bundle.add_argument("--objects", default=None)
    bundle.add_argument("--zones", default=None)
    bundle.add_argument("--config", default=None)
    bundle.add_argument("--out", required=True)
    bundle.add_argument("--overwrite", action="store_true")

    verify = sub.add_parser("verify-bundle", help="Verify an evidence bundle")
    verify.add_argument("bundle_dir")

    args = p.parse_args(argv)

    if args.cmd == "run":
        return _run(args)
    if args.cmd == "list":
        return _list(args)
    if args.cmd == "show":
        return _show(args)
    if args.cmd == "bundle":
        return _bundle(args)
    if args.cmd == "verify-bundle":
        return _verify(args)
    return 1


def _detect(args: argparse.Namespace) -> tuple[list[RuleAlert], list[IncidentRecord]]:
    from metriplane.sentinel.engine import evaluate_session
    from metriplane.sentinel.incidents import build_incidents
    from metriplane.sentinel.registry import load_registry
    from metriplane.sentinel.rules import load_rules

    ruleset = load_rules(args.rules)
    registry = load_registry(args.objects) if args.objects else None
    alerts, _ = evaluate_session(args.session, ruleset, registry)
    incidents = build_incidents(alerts)
    return alerts, incidents


def _run(args: argparse.Namespace) -> int:
    from metriplane.sentinel.events import write_incidents_json

    _, incidents = _detect(args)
    if args.out:
        write_incidents_json(incidents, args.out)
        print(f"Wrote {len(incidents)} incidents to {args.out}")
    else:
        for inc in incidents:
            print(
                f"{inc.incident_id}  {inc.rule_id}  {inc.severity}  "
                f"dur={inc.duration_s}s  {inc.summary}"
            )
    return 0


def _list(args: argparse.Namespace) -> int:
    from metriplane.sentinel.events import read_incidents_json

    incidents = read_incidents_json(args.incidents)
    for inc in incidents:
        print(
            f"{inc.incident_id}  {inc.rule_id}  {inc.severity}  "
            f"dur={inc.duration_s}s  objects={','.join(inc.object_ids)}"
        )
    return 0


def _show(args: argparse.Namespace) -> int:
    from metriplane.sentinel.events import read_incidents_json

    incidents = {i.incident_id: i for i in read_incidents_json(args.incidents)}
    inc = incidents.get(args.incident_id)
    if inc is None:
        print(f"not found: {args.incident_id}")
        return 1
    print(f"incident_id:  {inc.incident_id}")
    print(f"rule_id:      {inc.rule_id}")
    print(f"severity:     {inc.severity}")
    print(f"status:       {inc.status}")
    print(f"opened_ts:    {inc.opened_ts}")
    print(f"closed_ts:    {inc.closed_ts}")
    print(f"duration_s:   {inc.duration_s}")
    print(f"objects:      {', '.join(inc.object_ids) or '-'}")
    print(f"zones:        {', '.join(inc.zones) or '-'}")
    print(f"alerts:       {len(inc.alert_ids)}")
    print(f"summary:      {inc.summary}")
    return 0


def _bundle(args: argparse.Namespace) -> int:
    from metriplane.sentinel.bundles import create_bundle

    alerts, incidents = _detect(args)
    inc = next((i for i in incidents if i.incident_id == args.incident_id), None)
    if inc is None:
        print(f"not found: {args.incident_id}")
        print("available: " + ", ".join(i.incident_id for i in incidents))
        return 1
    bundle = create_bundle(
        incident=inc,
        alerts=alerts,
        out_dir=args.out,
        session_path=args.session,
        objects_path=args.objects,
        rules_path=args.rules,
        zones_path=args.zones,
        config_path=args.config,
        overwrite=args.overwrite,
    )
    print(f"Bundle created: {bundle}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    from metriplane.sentinel.bundles import verify_bundle

    ok, messages = verify_bundle(args.bundle_dir)
    for m in messages:
        print(m)
    return 0 if ok else 1
