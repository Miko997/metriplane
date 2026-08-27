# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser("metriplane contracts")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate a contract file")
    v.add_argument("path")

    t = sub.add_parser("test", help="Run a contract against a replay fixture")
    t.add_argument("--contract", required=True)
    t.add_argument("--input", required=True)
    t.add_argument("--expect", default=None)
    t.add_argument("--objects", default=None)
    t.add_argument("--output", default=None, help="Write JSON result here")

    args = p.parse_args(argv)

    if args.cmd == "validate":
        from metriplane.contracts.validate import validate_contract

        ok, msgs = validate_contract(args.path)
        for m in msgs:
            print(m)
        return 0 if ok else 1

    if args.cmd == "test":
        return _test(args)

    return 1


def _test(args: argparse.Namespace) -> int:
    from metriplane.contracts.evaluate import evaluate_contract_session
    from metriplane.contracts.expectations import compare, load_expectations
    from metriplane.contracts.load import load_spatial_contract
    from metriplane.sentinel.incidents import build_incidents
    from metriplane.sentinel.registry import load_registry

    package = load_spatial_contract(args.contract)
    registry = load_registry(args.objects) if args.objects else None
    events, run_id = evaluate_contract_session(args.input, package, registry)
    incidents = build_incidents([e.to_rule_alert() for e in events])

    result_obj = {
        "phase": 16,
        "contract_id": package.contract_id,
        "rules_count": len(package.rules),
        "observed_events": len(events),
        "observed_incidents": len(incidents),
    }

    if args.expect:
        expected = load_expectations(args.expect)
        res = compare(events, expected)
        result_obj.update(
            {
                "expected_incidents": res.expected_incidents,
                "false_positives": res.false_positives,
                "missed": res.missed,
                "pass": res.ok,
            }
        )
        print(
            f"contract_id={package.contract_id} schema={package.schema_version} "
            f"rules={len(package.rules)} result={'PASS' if res.ok else 'FAIL'}"
        )
        print(
            f"expected_incidents={res.expected_incidents} "
            f"observed_incidents={res.observed_incidents} "
            f"false_positives={res.false_positives} missed={res.missed}"
        )
        rc = 0 if res.ok else 1
    else:
        print(
            f"contract_id={package.contract_id} rules={len(package.rules)} "
            f"observed_events={len(events)} observed_incidents={len(incidents)}"
        )
        result_obj["pass"] = True
        rc = 0

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result_obj, indent=2))

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
