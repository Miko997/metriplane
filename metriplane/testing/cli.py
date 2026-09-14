# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
from pathlib import Path


def main_test(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane test")
    p.add_argument("bundle", help="Path to an incident evidence bundle")
    p.add_argument("--output", default=None, help="Write JSON result to this path")
    p.add_argument("--strict-extra-incidents", action="store_true", default=False)
    p.add_argument("--strict-extra-events", action="store_true", default=False)
    p.add_argument("--skip-checksums", action="store_true", default=False)
    p.add_argument(
        "--no-write-reports",
        action="store_true",
        default=False,
        help="Do not write test_result.json/md into the bundle",
    )
    args = p.parse_args(argv)

    from metriplane.testing.report import print_summary, write_json, write_md
    from metriplane.testing.runner import PhysicalRegressionRunner

    runner = PhysicalRegressionRunner(
        verify_checksums=not args.skip_checksums,
        strict_extra_incidents=args.strict_extra_incidents,
        strict_extra_events=args.strict_extra_events,
    )
    result = runner.run_bundle(args.bundle)
    print_summary(result)

    if not args.no_write_reports:
        bundle = Path(args.bundle)
        if bundle.is_dir() and not bundle.is_symlink():
            write_json(result, bundle / "test_result.json")
            write_md(result, bundle / "test_result.md")
    if args.output:
        write_json(result, args.output)

    return 0 if result.pass_ else 1
