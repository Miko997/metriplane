# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

import argparse
import logging
from pathlib import Path

import yaml

from metriplane.config import Config
from metriplane.run import run_loop


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    ap = argparse.ArgumentParser(description="Run Metriplane live loop from a YAML config.")
    ap.add_argument("config", help="Path to YAML config (e.g. configs/examples/config.m6_....yaml)")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg = Config(**data)

    run_loop(cfg)


if __name__ == "__main__":
    main()
