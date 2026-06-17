# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse


def main_rules(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane rules")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate rules.yaml")
    v.add_argument("path")

    ls = sub.add_parser("list", help="List rules")
    ls.add_argument("--config", required=True)

    run = sub.add_parser("run", help="Evaluate rules against a session and emit alerts")
    run.add_argument("--session", required=True)
    run.add_argument("--rules", required=True)
    run.add_argument("--objects", default=None)
    run.add_argument("--out", default=None, help="Write alerts JSONL to this path")

    args = p.parse_args(argv)

    from metriplane.sentinel.rules import load_rules, validate_rules

    if args.cmd == "validate":
        errors = validate_rules(args.path)
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            return 1
        print("PASS: rules.yaml valid")
        return 0

    if args.cmd == "list":
        rs = load_rules(args.config)
        for r in rs.rules:
            print(f"{r.id}  type={r.type}  severity={r.severity}")
        return 0

    if args.cmd == "run":
        from metriplane.sentinel.engine import evaluate_session
        from metriplane.sentinel.events import write_alerts_jsonl
        from metriplane.sentinel.registry import load_registry

        ruleset = load_rules(args.rules)
        registry = load_registry(args.objects) if args.objects else None
        alerts, _ = evaluate_session(args.session, ruleset, registry)
        if args.out:
            write_alerts_jsonl(alerts, args.out)
            print(f"Wrote {len(alerts)} alerts to {args.out}")
        else:
            for a in alerts:
                objs = ",".join(a.object_ids)
                print(f"{a.ts}  {a.rule_id}  {a.severity}  [{objs}]  zone={a.zone or '-'}")
        return 0

    return 1
