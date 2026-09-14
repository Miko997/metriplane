# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Read-only assignment-time validation of the governed functional inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from tools import discover_functional_surface
except ImportError:  # Direct ``python tools/check_functional_inventory.py`` execution.
    import discover_functional_surface

SCHEMA_VERSION = "metriplane.validation-result.v1"


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
    inventory: Path,
    profiles: Path,
) -> tuple[int, dict[str, Any]]:
    if not task_id.startswith("MP2-") or re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
        raise ValueError("explicit task and base identities are required")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    paths = {
        "inventory": (root / inventory).resolve(strict=True),
        "profiles": (root / profiles).resolve(strict=True),
    }
    if any(not path.is_relative_to(root) for path in paths.values()):
        raise ValueError("registry input escapes repository")
    checks = {"base_is_head": actual == base_sha, "functional_inventory_current": False}
    if checks["base_is_head"]:
        checks["functional_inventory_current"] = (
            discover_functional_surface.run(
                "check",
                repository_root=root,
                inventory=paths["inventory"],
                profiles=paths["profiles"],
                minimum_leaf_actions=71,
            )
            == 0
        )
    verdict = "READY" if all(checks.values()) else "BLOCKED_NOT_READY"
    return (
        0 if verdict == "READY" else 3,
        {
            "base_sha": base_sha,
            "checks": checks,
            "inputs": {name: _digest(path) for name, path in sorted(paths.items())},
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "validator": "functional_inventory",
            "verdict": verdict,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.repository_root.resolve(strict=True)
        code, result = validate(
            root,
            task_id=args.task_id,
            base_sha=args.base_sha,
            inventory=args.inventory,
            profiles=args.profiles,
        )
        _write_new(args.out, result)
        return code
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        discover_functional_surface.DiscoveryError,
    ) as exc:
        print(f"functional inventory validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
