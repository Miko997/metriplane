# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import AdapterError, convert, inspect_source
from .finalize import FinalizationError, finalize_conversion_equivalence
from .generator import SourceGenerationError, generate_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metriplane-ros2-mcap",
        description="Operate the bounded synthetic ROS 2/MCAP recorded-state profile.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate-source", help="generate the exact synthetic MCAP")
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--overwrite", action="store_true")

    inspect = commands.add_parser("inspect", help="audit the exact MCAP source")
    inspect.add_argument("--source", type=Path, required=True)

    conversion = commands.add_parser("convert", help="convert the exact source")
    conversion.add_argument("--source", type=Path, required=True)
    conversion.add_argument("--config", type=Path, required=True)
    conversion.add_argument("--out", type=Path, required=True)
    conversion.add_argument(
        "--adapter-commit",
        default=os.environ.get("ROS2_MCAP_ADAPTER_COMMIT"),
        required=os.environ.get("ROS2_MCAP_ADAPTER_COMMIT") is None,
    )
    conversion.add_argument("--overwrite", action="store_true")

    finalize = commands.add_parser(
        "finalize-equivalence", help="verify three clean conversions and finalize evidence"
    )
    finalize.add_argument("--conversion-root", action="append", type=Path, required=True)
    finalize.add_argument("--run-id", action="append")
    finalize.add_argument("--out", type=Path, required=True)
    finalize.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate-source":
            result = generate_source(args.out, overwrite=args.overwrite)
        elif args.command == "inspect":
            result = inspect_source(args.source)
        elif args.command == "convert":
            result = convert(
                args.source,
                config_path=args.config,
                output_root=args.out,
                adapter_commit=args.adapter_commit,
                overwrite=args.overwrite,
            )
        elif args.command == "finalize-equivalence":
            keywords = {}
            if args.run_id is not None:
                keywords["run_ids"] = args.run_id
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
    except (AdapterError, FinalizationError, SourceGenerationError) as exc:
        print(f"metriplane-ros2-mcap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
