from __future__ import annotations

import argparse
import json
from pathlib import Path


def main_ask(argv: list[str]) -> int:
    p = argparse.ArgumentParser("metriplane ask")
    p.add_argument("question")
    p.add_argument("--run-dir", default=None)
    p.add_argument("--bundle", default=None)
    p.add_argument("--json", action="store_true", default=False,
                   help="Print the full AssistantAnswer as JSON")
    args = p.parse_args(argv)

    run_dir = args.run_dir or args.bundle
    if not run_dir:
        print("error: provide --run-dir or --bundle")
        return 2
    if not Path(run_dir).exists():
        print(f"error: path not found: {run_dir}")
        return 2

    from metriplane.assistant.answer import answer_question

    ans = answer_question(args.question, run_dir)
    if args.json:
        print(ans.model_dump_json(indent=2))
        return 0

    print(ans.answer)
    if ans.citations:
        print("\nEvidence:")
        for c in ans.citations:
            ref = c.source_path
            if c.record_id:
                ref += f" [{c.record_id}]"
            print(f"  - {ref} ({c.source_type})")
    if ans.limitations:
        print("\nLimitations:")
        for lim in ans.limitations:
            print(f"  - {lim}")
    return 0
