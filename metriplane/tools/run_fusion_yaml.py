import argparse
import logging
from pathlib import Path

from metriplane.config import load_config, apply_profile_defaults
from metriplane.run_fusion import run_loop_fusion


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    ap = argparse.ArgumentParser(description="Run Metriplane multi-camera fusion from YAML config.")
    ap.add_argument("config", help="Path to YAML config (e.g. config.m8_fusion.yaml)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    cfg = apply_profile_defaults(cfg)  # fills per-cam mapping/intrinsics from calib profile
    run_loop_fusion(cfg)


if __name__ == "__main__":
    main()
