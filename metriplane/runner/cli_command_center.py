from __future__ import annotations

import argparse
import json


def main_command_center(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane command-center")
    sub = p.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="Export command-center data JSON for the dashboard")
    ex.add_argument("run_dir", help="Run dir or incident bundle")
    ex.add_argument("--out", default=None, help="Output JSON (default: <run_dir>/command_center_data.json)")

    sm = sub.add_parser("summary", help="Print live summary for a run dir")
    sm.add_argument("run_dir")

    args = p.parse_args(argv)

    from metriplane.runner.command_center_api import (
        export_command_center,
        get_live_summary,
    )

    if args.cmd == "export":
        from pathlib import Path
        out = args.out or str(Path(args.run_dir) / "command_center_data.json")
        payload = export_command_center(args.run_dir, out)
        print(f"wrote {out}")
        print(f"objects={len(payload['objects'])} "
              f"incidents={len(payload['incidents'])} "
              f"events={len(payload['events'])}")
        return 0

    if args.cmd == "summary":
        print(json.dumps(get_live_summary(args.run_dir), indent=2))
        return 0

    return 1
