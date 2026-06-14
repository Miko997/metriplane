# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse


def main_camera_trust(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane camera-trust")
    sub = p.add_subparsers(dest="cmd", required=True)

    an = sub.add_parser("analyze", help="Analyze camera trust from a session JSONL")
    an.add_argument("--input", required=True)
    an.add_argument("--out", default=None)

    args = p.parse_args(argv)

    if args.cmd == "analyze":
        from metriplane.camera_trust.analyzer import analyze_session
        from metriplane.camera_trust.export import export_camera_trust_report

        report = analyze_session(args.input)
        if args.out:
            export_camera_trust_report(args.out, report)
            print(f"wrote {args.out}")
        for cid, cs in report.camera_scores.items():
            print(f"{cid}: {cs.status} score={cs.score} dropout={cs.dropout_rate} "
                  f"disagreement_m={cs.mean_disagreement_m}")
        for rec in report.recommendations:
            print(f"  - {rec}")
        return 0
    return 1
