#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Open a Metriplane USD replay inside Isaac Sim (requires Isaac/omni.isaac).

This is a thin loader: it exports the .usda (via metriplane_to_usd) if needed, then opens
it in an Isaac Sim stage. It is intentionally guarded so importing this module never fails
on machines without NVIDIA software.

Usage (inside an Isaac Sim Python environment):
    python integrations/isaac/metriplane_isaac_replay.py --run-dir runs/<id>
"""

from __future__ import annotations

import argparse
from pathlib import Path


def open_in_isaac(usda_path: str | Path) -> None:  # pragma: no cover - needs Isaac
    try:
        from omni.isaac.kit import SimulationApp
    except Exception as e:
        raise SystemExit(
            "Isaac Sim not available in this environment. Export the .usda with "
            "metriplane_to_usd.py and open it manually in Omniverse/Isaac.\n"
            f"(import error: {e})"
        )
    sim = SimulationApp({"headless": False})
    import omni.usd

    omni.usd.get_context().open_stage(str(usda_path))
    while sim.is_running():
        sim.update()
    sim.close()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    p = argparse.ArgumentParser("metriplane_isaac_replay")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--usda", default=None)
    args = p.parse_args(argv)

    usda = args.usda
    if usda is None:
        from integrations.isaac.metriplane_to_usd import write_usda_replay

        usda = str(Path(args.run_dir) / "isaac" / "metriplane_replay.usda")
        write_usda_replay(run_dir=args.run_dir, output_path=usda)
    open_in_isaac(usda)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
