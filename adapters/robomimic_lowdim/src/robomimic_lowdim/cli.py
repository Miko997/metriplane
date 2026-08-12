# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import (
    AdapterError,
    acquire,
    compare_raw_prepared,
    convert,
    finalize_conversion_equivalence,
    inspect_source,
)
from .fixture import FixtureError


def _source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--json", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robomimic-lowdim",
        description=(
            "Audit and convert one pinned robomimic Can PH low-dimensional trajectory "
            "without simulator imports or action replay."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    acquire_parser = commands.add_parser("acquire", help="acquire the exact pinned HDF5 pair")
    acquire_parser.add_argument("--out", type=Path, required=True)
    acquire_parser.add_argument("--raw", type=Path, help="verify a pre-downloaded raw file")
    acquire_parser.add_argument(
        "--prepared", type=Path, help="verify a pre-downloaded prepared file"
    )
    acquire_parser.add_argument("--overwrite", action="store_true")
    acquire_parser.add_argument("--json", action="store_true")

    inspect_parser = commands.add_parser(
        "inspect", help="inspect the exact pair and named raw-state witnesses"
    )
    _source_arguments(inspect_parser)

    compare_parser = commands.add_parser(
        "compare-raw-prepared", help="prove all-demo raw/prepared correspondence"
    )
    _source_arguments(compare_parser)

    convert_parser = commands.add_parser(
        "convert", help="convert all 118 demo_0 obs rows into incident/control bundles"
    )
    _source_arguments(convert_parser)
    convert_parser.add_argument("--config", type=Path, required=True)
    convert_parser.add_argument("--out", type=Path, required=True)
    convert_parser.add_argument(
        "--adapter-commit",
        default=os.environ.get("ROBOMIMIC_LOWDIM_ADAPTER_COMMIT"),
        required=os.environ.get("ROBOMIMIC_LOWDIM_ADAPTER_COMMIT") is None,
        help="exact lowercase 40-hex commit containing this frozen adapter",
    )
    convert_parser.add_argument("--overwrite", action="store_true")

    finalize_parser = commands.add_parser(
        "finalize-equivalence",
        help="verify three clean conversions and finalize demonstrated equivalence",
    )
    finalize_parser.add_argument("--conversion-root", action="append", type=Path, required=True)
    finalize_parser.add_argument("--run-id", action="append")
    finalize_parser.add_argument("--out", type=Path, required=True)
    finalize_parser.add_argument("--overwrite", action="store_true")
    finalize_parser.add_argument("--json", action="store_true")
    return parser


def _emit(value: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, allow_nan=False, sort_keys=True))
    else:
        print(json.dumps(value, allow_nan=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "acquire":
            result = acquire(
                args.out,
                downloaded_raw=args.raw,
                downloaded_prepared=args.prepared,
                overwrite=args.overwrite,
            )
        elif args.command == "inspect":
            result = inspect_source(args.raw, args.prepared)
        elif args.command == "compare-raw-prepared":
            result = compare_raw_prepared(args.raw, args.prepared)
        elif args.command == "convert":
            result = convert(
                args.raw,
                args.prepared,
                config_path=args.config,
                output_root=args.out,
                adapter_commit=args.adapter_commit,
                overwrite=args.overwrite,
            )
        elif args.command == "finalize-equivalence":
            keyword_arguments = {}
            if args.run_id is not None:
                keyword_arguments["run_ids"] = args.run_id
            result = finalize_conversion_equivalence(
                args.conversion_root,
                output_root=args.out,
                overwrite=args.overwrite,
                **keyword_arguments,
            )
        else:  # pragma: no cover - argparse enforces this
            parser.error(f"unsupported command: {args.command}")
        _emit(result, args.json)
        return 0
    except (AdapterError, FixtureError) as exc:
        print(f"robomimic-lowdim: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
