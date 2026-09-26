# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Review the exact dependency-bearing path delta without repository settings."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class DependencyDeltaError(ValueError):
    """The exact dependency delta is incomplete or cannot be established."""


SHA = re.compile(r"^[0-9a-f]{40}$")
EVENTS = {"pull_request", "push", "schedule"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DependencyDeltaError(message)


def _run_git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", *arguments], cwd=root, check=False, capture_output=True)
    if completed.returncode:
        raise DependencyDeltaError(
            f"git {' '.join(arguments)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _declared_paths(policy: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    declared = {".github/dependabot.yml", "supply-chain-policy.json"}
    project_locks: dict[str, str] = {}
    for project in policy["python_projects"]:
        directory = project["directory"]
        manifest = "pyproject.toml" if directory == "." else f"{directory}/pyproject.toml"
        lock = project["lock"]
        declared.update((manifest, lock))
        project_locks[manifest] = lock
    declared.update(policy["additional_locks"])
    declared.update(policy["images"]["scanned"])
    declared.update(item["path"] for item in policy["images"]["excluded"])
    declared.update(policy["license_files"])
    return declared, project_locks


def validate_changed_paths(
    policy: dict[str, Any], changed_paths: Iterable[str]
) -> dict[str, object]:
    declared, project_locks = _declared_paths(policy)
    changed = sorted(set(changed_paths))
    _require(all(path and not path.startswith("/") for path in changed), "invalid changed path")
    dependency_paths: list[str] = []
    for path in changed:
        pure = PurePosixPath(path)
        dependency_like = (
            pure.name in {"pyproject.toml", "uv.lock"}
            or pure.name.endswith("Dockerfile")
            or path in {".github/dependabot.yml", "supply-chain-policy.json"}
            or path.startswith("LICENSES/")
            or path in {"LICENSE", "NOTICE"}
        )
        if dependency_like:
            _require(path in declared, f"undeclared dependency-bearing path: {path}")
            dependency_paths.append(path)
    changed_set = set(changed)
    for manifest, lock in project_locks.items():
        _require(
            manifest not in changed_set or lock in changed_set,
            f"changed project manifest lacks its lock delta: {manifest}",
        )
    return {
        "dependency_paths": dependency_paths,
        "dependency_path_count": len(dependency_paths),
    }


def validate_dependency_delta(
    root: Path, *, event_name: str, base: str, head: str
) -> dict[str, object]:
    _require(event_name in EVENTS, "unsupported provider event")
    _require(SHA.fullmatch(base) is not None, "invalid base SHA")
    _require(SHA.fullmatch(head) is not None, "invalid head SHA")
    actual_head = _run_git(root, "rev-parse", "HEAD").decode().strip()
    _require(actual_head == head, "checked-out source differs from head SHA")
    if event_name == "schedule":
        _require(base == head, "scheduled current-snapshot review must bind one SHA")
        changed: list[str] = []
    elif base == "0" * 40:
        _require(event_name == "push", "zero base is valid only for an initial push")
        changed = []
    else:
        _run_git(root, "merge-base", "--is-ancestor", base, head)
        raw = _run_git(root, "diff", "--name-only", "-z", base, head)
        changed = [item.decode() for item in raw.split(b"\0") if item]
    policy = json.loads((root / "supply-chain-policy.json").read_text(encoding="utf-8"))
    _require(isinstance(policy, dict), "supply-chain policy is not an object")
    result = validate_changed_paths(policy, changed)
    return {
        "base": base,
        "event_name": event_name,
        "head": head,
        **result,
        "schema_version": "metriplane.dependency-delta-review.v1",
        "verdict": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        result = validate_dependency_delta(
            args.repository_root.resolve(),
            event_name=args.event_name,
            base=args.base,
            head=args.head,
        )
    except (DependencyDeltaError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"dependency delta review failed: {exc}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
