from __future__ import annotations

import argparse
from pathlib import Path


def main_counterfactual(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane counterfactual")
    p.add_argument("bundle", help="Path to an incident evidence bundle")
    p.add_argument("--sweep-rule", action="append", default=[],
                   help="rule_id.field=start:stop:step (repeatable)")
    p.add_argument("--slow-object", action="append", default=[],
                   help="object_id=factor (repeatable)")
    p.add_argument("--remove-object", action="append", default=[],
                   help="object_id (repeatable)")
    p.add_argument("--max-cases", type=int, default=50)
    p.add_argument("--output", default=None, help="Write JSON report here")
    p.add_argument("--no-write-reports", action="store_true", default=False)
    args = p.parse_args(argv)

    from metriplane.counterfactuals.evaluator import (
        CounterfactualError,
        CounterfactualEvaluator,
    )
    from metriplane.counterfactuals.models import CounterfactualTransform
    from metriplane.counterfactuals.report import print_summary, write_json, write_md
    from metriplane.counterfactuals.rule_sweep import sweep_transforms

    transforms: list[CounterfactualTransform] = []
    for spec in args.sweep_rule:
        try:
            transforms.extend(sweep_transforms(spec))
        except ValueError as e:
            print(f"error: {e}")
            return 2
    for spec in args.slow_object:
        if "=" not in spec:
            print(f"error: --slow-object expects object_id=factor, got {spec!r}")
            return 2
        obj, factor = spec.split("=", 1)
        transforms.append(CounterfactualTransform(
            type="object_speed_scale", target=obj, params={"factor": float(factor)}))
    for obj in args.remove_object:
        transforms.append(CounterfactualTransform(type="object_remove", target=obj))

    if not transforms:
        print("error: no transforms specified "
              "(use --sweep-rule / --slow-object / --remove-object)")
        return 2

    try:
        report = CounterfactualEvaluator(max_cases=args.max_cases).evaluate(
            args.bundle, transforms)
    except CounterfactualError as e:
        print(f"counterfactual failed: {e}")
        return 1

    print_summary(report)

    if not args.no_write_reports:
        bundle = Path(args.bundle)
        write_json(report, bundle / "counterfactual_report.json")
        write_md(report, bundle / "counterfactual_report.md")
    if args.output:
        write_json(report, args.output)
    return 0
