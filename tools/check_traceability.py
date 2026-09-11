# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Read-only assignment-time validation of the governed traceability graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from tools import build_traceability_graph
except ImportError:
    import build_traceability_graph

SCHEMA_VERSION = "metriplane.assignment-validation-result.v1"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def validate(
    root: Path,
    *,
    task_id: str,
    base_sha: str,
    graph: Path,
    ledger: Path,
    obligations: Path,
) -> tuple[int, dict[str, Any]]:
    if not task_id.startswith("MP2-") or len(base_sha) != 40:
        raise ValueError("explicit task and base identities are required")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    paths = {"graph": graph, "ledger": ledger, "obligations": obligations}
    canonical = {
        "graph": build_traceability_graph.GRAPH_PATH,
        "ledger": build_traceability_graph.LEDGER_PATH,
        "obligations": build_traceability_graph.OBLIGATIONS_PATH,
    }
    resolved: dict[str, Path] = {}
    for name, path in paths.items():
        candidate = (root / path).resolve(strict=True)
        expected = (root / canonical[name]).resolve(strict=True)
        if candidate != expected:
            raise ValueError(f"{name} must name the canonical governed path")
        resolved[name] = candidate
    checks = {"base_is_head": actual == base_sha, "traceability_current": False}
    if checks["base_is_head"]:
        outputs = build_traceability_graph._check()
        checks["traceability_current"] = all(
            (root / path).read_bytes() == payload for path, payload in outputs.items()
        )
    verdict = "READY" if all(checks.values()) else "BLOCKED_NOT_READY"
    return (
        0 if verdict == "READY" else 3,
        {
            "base_sha": base_sha,
            "checks": checks,
            "inputs": {name: _digest(path) for name, path in sorted(resolved.items())},
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "validator": "traceability",
            "verdict": verdict,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--obligations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve(strict=True)
        code, result = validate(
            root,
            task_id=args.task_id,
            base_sha=args.base_sha,
            graph=args.graph,
            ledger=args.ledger,
            obligations=args.obligations,
        )
        _write_new(args.out, result)
        return code
    except (OSError, ValueError, build_traceability_graph.TraceabilityError) as exc:
        print(f"traceability validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
