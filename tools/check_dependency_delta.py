# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Review the exact dependency-bearing path delta without repository settings."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

if __package__:
    from tools.supply_chain_paths import is_dockerfile_path
else:
    from supply_chain_paths import is_dockerfile_path


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
    policy: dict[str, Any],
    changed_paths: Iterable[str],
    *,
    dependency_neutral_manifests: Iterable[str] = (),
) -> dict[str, object]:
    declared, project_locks = _declared_paths(policy)
    changed = sorted(set(changed_paths))
    _require(all(path and not path.startswith("/") for path in changed), "invalid changed path")
    dependency_paths: list[str] = []
    for path in changed:
        pure = PurePosixPath(path)
        dependency_like = (
            pure.name in {"pyproject.toml", "uv.lock"}
            or is_dockerfile_path(pure)
            or path in {".github/dependabot.yml", "supply-chain-policy.json"}
            or path.startswith("LICENSES/")
            or path in {"LICENSE", "NOTICE"}
        )
        if dependency_like:
            _require(path in declared, f"undeclared dependency-bearing path: {path}")
            dependency_paths.append(path)
    changed_set = set(changed)
    neutral_manifests = set(dependency_neutral_manifests)
    _require(neutral_manifests <= set(project_locks), "unknown dependency-neutral manifest")
    for manifest, lock in project_locks.items():
        _require(
            manifest not in changed_set or lock in changed_set or manifest in neutral_manifests,
            f"changed project manifest lacks its lock delta: {manifest}",
        )
    return {
        "dependency_paths": dependency_paths,
        "dependency_path_count": len(dependency_paths),
    }


def _manifest_dependency_projection(payload: bytes, *, path: str) -> dict[str, object]:
    try:
        document = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DependencyDeltaError(f"cannot parse dependency manifest {path}: {exc}") from exc
    project = document.get("project", {})
    _require(isinstance(project, dict), f"dependency manifest project table is invalid: {path}")
    dynamic = project.get("dynamic", [])
    _require(isinstance(dynamic, list), f"dependency manifest dynamic field is invalid: {path}")
    _require(
        not {"dependencies", "optional-dependencies"}.intersection(dynamic),
        f"dynamic dependency manifest requires its lock delta: {path}",
    )
    tool = document.get("tool", {})
    _require(isinstance(tool, dict), f"dependency manifest tool table is invalid: {path}")
    return {
        "build-system": document.get("build-system"),
        "dependency-groups": document.get("dependency-groups"),
        "project": {
            key: project.get(key)
            for key in ("dependencies", "dynamic", "optional-dependencies", "requires-python")
        },
        "tool.uv": tool.get("uv"),
    }


def _dependency_neutral_manifests(
    root: Path,
    *,
    base: str,
    head: str,
    changed: set[str],
    project_locks: dict[str, str],
) -> set[str]:
    neutral: set[str] = set()
    for manifest, lock in project_locks.items():
        if manifest not in changed or lock in changed:
            continue
        before = _run_git(root, "show", f"{base}:{manifest}")
        after = _run_git(root, "show", f"{head}:{manifest}")
        if _manifest_dependency_projection(
            before, path=manifest
        ) == _manifest_dependency_projection(after, path=manifest):
            neutral.add(manifest)
    return neutral


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
    _, project_locks = _declared_paths(policy)
    neutral_manifests = _dependency_neutral_manifests(
        root,
        base=base,
        head=head,
        changed=set(changed),
        project_locks=project_locks,
    )
    result = validate_changed_paths(
        policy,
        changed,
        dependency_neutral_manifests=neutral_manifests,
    )
    return {
        "base": base,
        "dependency_neutral_manifests": sorted(neutral_manifests),
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
