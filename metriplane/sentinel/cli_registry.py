# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse


def main_objects(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane objects")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate objects.yaml")
    v.add_argument("path")

    ls = sub.add_parser("list", help="List registered objects")
    ls.add_argument("--config", required=True)

    res = sub.add_parser("resolve", help="Resolve marker ID to object ID")
    res.add_argument("--config", required=True)
    res.add_argument("marker_id")

    args = p.parse_args(argv)

    from metriplane.sentinel.registry import load_registry, validate_registry

    if args.cmd == "validate":
        errors = validate_registry(args.path)
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            return 1
        print("PASS: objects.yaml valid")
        return 0

    if args.cmd == "list":
        cfg = load_registry(args.config)
        for obj in cfg.objects:
            print(f"{obj.object_id}  marker={obj.marker_id}  type={obj.type}")
        return 0

    if args.cmd == "resolve":
        cfg = load_registry(args.config)
        print(cfg.resolve_id(args.marker_id))
        return 0

    return 1
