# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Build the release artifact identity through the established artifact owner."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from metriplane.release_control import make_record, write_immutable_json

if __package__:
    from tools.release_artifacts import create_manifest, inspect_sdist, release_artifacts
else:
    from release_artifacts import create_manifest, inspect_sdist, release_artifacts


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--sequence", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    digests = create_manifest(args.dist, args.manifest, args.version)
    _, sdist = release_artifacts(args.dist, args.version)
    inspect_sdist(sdist, args.version)
    record = make_record(
        "release-artifact-manifest",
        {
            "artifacts": digests,
            "tool": "release_artifacts.py",
            "version": f"v{args.version}",
        },
        invocation_id=args.invocation_id,
        sequence=args.sequence,
        synthetic=False,
    )
    write_immutable_json(args.output, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
