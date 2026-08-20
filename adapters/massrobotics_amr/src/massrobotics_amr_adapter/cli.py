# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .constants import DEFAULT_CONFIG
from .core import AdapterError, convert, inspect_source
from .finalize import FinalizationError, finalize_conversion_equivalence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metriplane-massrobotics-amr",
        description="Operate one bounded synthetic MassRobotics AMR offline-replay profile.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate and summarize one source directory")
    inspect.add_argument("--source-root", type=Path, required=True)
    inspect.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    conversion = commands.add_parser("convert", help="convert one strict source variant")
    conversion.add_argument("--source-root", type=Path, required=True)
    conversion.add_argument("--config", type=Path, required=True)
    conversion.add_argument("--out", type=Path, required=True)
    conversion.add_argument(
        "--adapter-commit",
        default=os.environ.get("MET55_COMMIT"),
        required=os.environ.get("MET55_COMMIT") is None,
    )
    conversion.add_argument(
        "--overwrite",
        action="store_true",
        help="legacy compatibility flag; replacement remains prohibited",
    )

    finalize = commands.add_parser(
        "finalize-equivalence",
        help="verify three byte-identical conversions per variant and finalize the profile",
    )
    finalize.add_argument("--conversion-root", action="append", type=Path, required=True)
    finalize.add_argument("--run-id", action="append")
    finalize.add_argument("--out", type=Path, required=True)
    finalize.add_argument(
        "--overwrite",
        action="store_true",
        help="legacy compatibility flag; replacement remains prohibited",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_source(args.source_root, config_path=args.config)
        elif args.command == "convert":
            result = convert(
                args.source_root,
                config_path=args.config,
                output_root=args.out,
                adapter_commit=args.adapter_commit,
                overwrite=args.overwrite,
            )
        elif args.command == "finalize-equivalence":
            keywords = {"run_ids": args.run_id} if args.run_id is not None else {}
            result = finalize_conversion_equivalence(
                args.conversion_root,
                output_root=args.out,
                overwrite=args.overwrite,
                **keywords,
            )
        else:  # pragma: no cover
            raise AssertionError(args.command)
        print(json.dumps(result, allow_nan=False, sort_keys=True))
        return 0
    except (AdapterError, FinalizationError) as exc:
        print(f"metriplane-massrobotics-amr: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
