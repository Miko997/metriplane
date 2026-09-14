#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Generate a Metriplane USD replay for Omniverse.

This delegates to the Isaac exporter (the .usda is plain USD and opens in Omniverse USD
Composer / Create). Kept as a separate entry point for discoverability.

Usage:
    python integrations/omniverse/metriplane_usd_replay.py --run-dir runs/<id> --out scene.usda
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from integrations.isaac.metriplane_to_usd import write_usda_replay

    p = argparse.ArgumentParser("metriplane_usd_replay")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--fps", type=float, default=30.0)
    args = p.parse_args(argv)

    out = args.out or str(Path(args.run_dir) / "omniverse" / "metriplane_replay.usda")
    manifest = write_usda_replay(run_dir=args.run_dir, output_path=out, fps=args.fps)
    print(f"wrote USD replay for Omniverse: {out}")
    print(f"open it in Omniverse USD Composer; objects={len(manifest['object_ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
