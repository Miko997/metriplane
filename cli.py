from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from metriplane.config import load_config
from metriplane.logging import setup_logging
from metriplane.run import run_loop

# NEW (M9.1)
from metriplane.replay.engine import EngineConfig, iter_replay_outputs, write_outputs_jsonl

log = logging.getLogger("metriplane.cli")


def _main_run(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane")
    p.add_argument("--config", default="config.example.yaml", help="Path to YAML config")
    p.add_argument(
        "--profile",
        default=None,
        help=(
            "Calibration profile name (defaults to calib/active_profile.yaml). "
            "Profile maps to calib/profiles/<profile>/..."
        ),
    )

    # M9.4: provenance controls
    p.add_argument("--run-id", default=None, help="Optional run id override (otherwise auto).")
    p.add_argument(
        "--runs-dir",
        default=None,
        help=(
            "Override runs base dir (default: /data/runs in docker, ./runs on host). "
            "Example: --runs-dir ~/metriplane-runs"
        ),
    )

    # M9.3: reproducible fault injection (passthrough to run_loop)
    p.add_argument(
        "--fault",
        action="append",
        default=[],
        help="Fault injection (repeatable). Example: --fault ws_send_fail_after_s=12",
    )

    args = p.parse_args(argv)

    cfg = load_config(Path(args.config))

    # Allow CLI to override profile without requiring config edits.
    if args.profile:
        cfg = replace(cfg, profile=str(args.profile))

    log.info("loaded config: %s", cfg)

    run_loop(
        cfg,
        cli_faults=list(args.fault or []),
        config_path=Path(args.config),
        argv=["metriplane", *argv],
        run_id=str(args.run_id) if args.run_id else None,
        runs_dir=str(args.runs_dir) if args.runs_dir else None,
    )
    return 0


def _main_replay(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane replay")
    p.add_argument("--input", required=True, help="Input JSONL session file")
    p.add_argument("--clock", choices=["replay", "fixed"], default="replay")
    p.add_argument("--dt-ms", type=int, default=None, help="Required when --clock fixed")
    p.add_argument("--run-id", default=None)
    p.add_argument("--speed", type=float, default=None)
    p.add_argument(
        "--output-file",
        default=None,
        help="If set: write JSONL outputs and exit (NO WS server).",
    )
    args = p.parse_args(argv)

    if args.clock == "fixed" and args.dt_ms is None:
        p.error("--dt-ms is required when --clock fixed")

    if not args.output_file:
        # Spec rule you gave: output-file mode is the non-interactive path.
        # Keep it strict for now (we can add WS streaming later).
        p.error("--output-file is required for replay CLI in M9.1 (non-interactive determinism mode)")

    cfg = EngineConfig(
        input_path=Path(args.input),
        clock=str(args.clock),
        dt_ms=int(args.dt_ms) if args.dt_ms is not None else None,
        run_id=str(args.run_id or "replay"),
        speed=float(args.speed) if args.speed is not None else None,
    )

    outputs = iter_replay_outputs(cfg)
    out_path = Path(args.output_file)
    write_outputs_jsonl(out_path, outputs)
    print(f"[metriplane replay] wrote {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging()

    argv = list(sys.argv[1:] if argv is None else argv)

    # Backwards compatible dispatch:
    # - `metriplane replay ...` -> new replay CLI
    # - anything else -> existing run CLI
    if argv and argv[0] == "replay":
        return _main_replay(argv[1:])
    return _main_run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
