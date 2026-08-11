# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .constants import EPISODE_ID
from .core import (
    AdapterError,
    acquire,
    convert,
    finalize_conversion_equivalence,
    inspect_source,
    restore_named_poses,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maniskill-pickcube",
        description="Convert one pinned ManiSkill PickCube trajectory without replaying actions.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    acquire_parser = commands.add_parser("acquire", help="acquire and verify the pinned source ZIP")
    acquire_parser.add_argument("--out", type=Path, required=True)
    acquire_parser.add_argument("--archive", type=Path, help="verify a pre-downloaded pinned ZIP")
    acquire_parser.add_argument("--overwrite", action="store_true")
    acquire_parser.add_argument("--json", action="store_true")

    inspect_parser = commands.add_parser("inspect", help="inspect the exact source and named poses")
    inspect_parser.add_argument("--trajectory", type=Path, required=True)
    inspect_parser.add_argument("--metadata", type=Path, required=True)
    inspect_parser.add_argument("--episode-id", type=int, default=EPISODE_ID)
    inspect_parser.add_argument(
        "--structural-only",
        action="store_true",
        help="skip named ManiSkill state restoration (does not satisfy the real-source audit)",
    )
    inspect_parser.add_argument("--json", action="store_true")

    convert_parser = commands.add_parser("convert", help="restore and convert all 75 source states")
    convert_parser.add_argument("--trajectory", type=Path, required=True)
    convert_parser.add_argument("--metadata", type=Path, required=True)
    convert_parser.add_argument("--config", type=Path, required=True)
    convert_parser.add_argument("--out", type=Path, required=True)
    convert_parser.add_argument(
        "--adapter-commit",
        default=os.environ.get("MANISKILL_PICKCUBE_ADAPTER_COMMIT"),
        required=os.environ.get("MANISKILL_PICKCUBE_ADAPTER_COMMIT") is None,
        help="exact 40-hex commit containing the frozen adapter implementation",
    )
    convert_parser.add_argument("--overwrite", action="store_true")
    convert_parser.add_argument("--json", action="store_true")

    finalize_parser = commands.add_parser(
        "finalize-equivalence",
        help="verify three clean conversions and finalize demonstrated equivalence",
    )
    finalize_parser.add_argument(
        "--conversion-root",
        action="append",
        type=Path,
        required=True,
        help="clean conversion root; provide exactly three",
    )
    finalize_parser.add_argument(
        "--run-id",
        action="append",
        help="stable run ID; when supplied, provide exactly three in root order",
    )
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
            result = acquire(args.out, overwrite=args.overwrite, downloaded_archive=args.archive)
        elif args.command == "inspect":
            result = inspect_source(
                args.trajectory,
                args.metadata,
                episode_id=args.episode_id,
                verify_hashes=True,
            )
            if not args.structural_only:
                frames, restoration = restore_named_poses(args.trajectory, args.metadata)
                result["restoration"] = {
                    **restoration,
                    "restored_state_count": len(frames),
                    "first_cube_pose": list(frames[0].cube_pose),
                    "first_tcp_pose": list(frames[0].tcp_pose),
                    "first_goal_pose": list(frames[0].goal_pose),
                    "last_cube_pose": list(frames[-1].cube_pose),
                    "last_tcp_pose": list(frames[-1].tcp_pose),
                }
        elif args.command == "convert":
            result = convert(
                args.trajectory,
                args.metadata,
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
    except AdapterError as exc:
        print(f"maniskill-pickcube: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
