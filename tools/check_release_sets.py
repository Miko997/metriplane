#!/usr/bin/env python3
"""Validate the canonical v0.5 installable-family release-set BOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

EXPECTED_PROJECTS = {
    "maniskill-pickcube": {
        "lock": "adapters/maniskill_pickcube/uv.lock",
        "name": "maniskill-pickcube-adapter",
        "path": "adapters/maniskill_pickcube",
    },
    "massrobotics-amr": {
        "lock": "adapters/massrobotics_amr/uv.lock",
        "name": "metriplane-massrobotics-amr-adapter",
        "path": "adapters/massrobotics_amr",
    },
    "metriplane": {"lock": "uv.lock", "name": "metriplane", "path": "."},
    "robomimic-lowdim": {
        "lock": "adapters/robomimic_lowdim/uv.lock",
        "name": "robomimic-lowdim-adapter",
        "path": "adapters/robomimic_lowdim",
    },
    "ros2-mcap": {
        "lock": "adapters/ros2_mcap/uv.lock",
        "name": "metriplane-ros2-mcap-adapter",
        "path": "adapters/ros2_mcap",
    },
    "source-adapter-sdk": {
        "lock": "adapters/source_adapter_sdk/uv.lock",
        "name": "metriplane-source-adapter-sdk",
        "path": "adapters/source_adapter_sdk",
    },
}
EXPECTED_SCHEMA_SHA256 = "eb8983491deb210af038ad37f4c8084dd3a539ad3b5e0ee564b40d5460ac546e"
EXPECTED_SET_SHAPES: Mapping[str, Mapping[str, object]] = {
    "adapters": {
        "extends": ["core"],
        "projects": [
            "maniskill-pickcube",
            "massrobotics-amr",
            "robomimic-lowdim",
            "ros2-mcap",
            "source-adapter-sdk",
        ],
        "root_extras": [],
    },
    "analytics": {"extends": ["core"], "projects": [], "root_extras": ["plots"]},
    "compat": {
        "extends": ["adapters", "analytics", "connectors", "live", "ops", "review", "robotics"],
        "projects": [],
        "root_extras": [],
    },
    "connectors": {"extends": ["core"], "projects": [], "root_extras": []},
    "core": {"extends": [], "projects": ["metriplane"], "root_extras": []},
    "full": {"extends": ["compat", "research"], "projects": [], "root_extras": []},
    "gpu": {
        "extends": ["core"],
        "projects": [],
        "root_extras": [],
        "variants": {"cuda12x": ["gpu-cuda12x"], "cuda13x": ["gpu-cuda13x"]},
    },
    "live": {"extends": ["core"], "projects": [], "root_extras": []},
    "ops": {"extends": ["core"], "projects": [], "root_extras": []},
    "research": {"extends": ["analytics", "review"], "projects": [], "root_extras": []},
    "review": {"extends": ["core"], "projects": [], "root_extras": []},
    "robotics": {"extends": ["adapters"], "projects": [], "root_extras": []},
}


class ReleaseSetError(ValueError):
    """The release-set registry is incomplete, ambiguous, or stale."""


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ReleaseSetError(f"{path}: root must be an object")
    return value


def _unique_sorted(values: object, label: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ReleaseSetError(f"{label} must be a string list")
    if values != sorted(set(values)):
        raise ReleaseSetError(f"{label} must be sorted and unique")
    return values


def validate(root: Path, registry_path: Path, schema_path: Path) -> None:
    registry = _read_json(registry_path)
    schema_bytes = schema_path.read_bytes()
    if hashlib.sha256(schema_bytes).hexdigest() != EXPECTED_SCHEMA_SHA256:
        raise ReleaseSetError("release-set schema bytes are not canonical")
    schema = _read_json(schema_path)
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        jsonschema = None
    if jsonschema is not None:
        jsonschema.Draft202012Validator.check_schema(schema)
        try:
            jsonschema.Draft202012Validator(schema).validate(registry)
        except jsonschema.ValidationError as exc:
            raise ReleaseSetError(f"registry schema failure: {exc.message}") from exc

    if set(registry) != {"owner", "projects", "python_requires", "schema_version", "sets"}:
        raise ReleaseSetError("registry fields are not exact")
    if registry.get("owner") != "MP2-041":
        raise ReleaseSetError("registry owner is not MP2-041")
    if registry.get("schema_version") != "metriplane.release-sets.v1":
        raise ReleaseSetError("registry schema version is not exact")
    if registry.get("python_requires") != ">=3.12,<3.14":
        raise ReleaseSetError("registry Python contract is not exact")

    projects = registry.get("projects")
    sets = registry.get("sets")
    if projects != EXPECTED_PROJECTS:
        raise ReleaseSetError("project BOM is not the exact v0.5 package family")
    if not isinstance(sets, Mapping) or set(sets) != set(EXPECTED_SET_SHAPES):
        raise ReleaseSetError("release-set names are not exact")

    root_extras: set[str] = set()
    for project_id, raw in projects.items():
        if not isinstance(raw, Mapping):
            raise ReleaseSetError(f"project {project_id} is malformed")
        project_root = (root / str(raw["path"])).resolve()
        if project_root != root.resolve() and root.resolve() not in project_root.parents:
            raise ReleaseSetError(f"project {project_id} escapes the repository")
        metadata_path = project_root / "pyproject.toml"
        lock_path = (root / str(raw["lock"])).resolve()
        if root.resolve() not in lock_path.parents:
            raise ReleaseSetError(f"project {project_id} lock escapes the repository")
        if not metadata_path.is_file() or not lock_path.is_file():
            raise ReleaseSetError(f"project {project_id} lacks metadata or lock")
        metadata = tomllib.loads(metadata_path.read_text(encoding="utf-8"))["project"]
        if metadata.get("name") != raw["name"]:
            raise ReleaseSetError(f"project {project_id} name differs from pyproject.toml")
        if metadata.get("requires-python") != registry.get("python_requires"):
            raise ReleaseSetError(f"project {project_id} Python contract differs")
        if project_id == "metriplane":
            extras = metadata.get("optional-dependencies", {})
            if not isinstance(extras, Mapping):
                raise ReleaseSetError("root optional-dependencies are malformed")
            root_extras = set(extras)

    visiting: set[str] = set()
    complete: dict[str, set[str]] = {}

    def closure(name: str) -> set[str]:
        if name in complete:
            return complete[name]
        if name in visiting:
            raise ReleaseSetError("release-set inheritance contains a cycle")
        visiting.add(name)
        raw = sets[name]
        if not isinstance(raw, Mapping):
            raise ReleaseSetError(f"release set {name} is malformed")
        expected = EXPECTED_SET_SHAPES[name]
        expected_fields = set(expected) | {"purpose"}
        if set(raw) != expected_fields or any(
            raw.get(key) != value for key, value in expected.items()
        ):
            raise ReleaseSetError(f"release set {name} does not match its canonical BOM")
        if not isinstance(raw.get("purpose"), str) or not raw["purpose"]:
            raise ReleaseSetError(f"release set {name} purpose is missing")
        parents = _unique_sorted(raw.get("extends"), f"{name}.extends")
        direct = _unique_sorted(raw.get("projects"), f"{name}.projects")
        extras = _unique_sorted(raw.get("root_extras"), f"{name}.root_extras")
        if not set(parents) <= set(EXPECTED_SET_SHAPES) or name in parents:
            raise ReleaseSetError(f"{name} names an unknown or self parent")
        if not set(direct) <= set(EXPECTED_PROJECTS):
            raise ReleaseSetError(f"{name} names an unknown project")
        if not set(extras) <= root_extras:
            raise ReleaseSetError(f"{name} names an unknown root extra")
        resolved = set(direct)
        for parent in parents:
            resolved.update(closure(parent))
        visiting.remove(name)
        complete[name] = resolved
        return resolved

    for set_name in sorted(EXPECTED_SET_SHAPES):
        closure(set_name)
    if complete["core"] != {"metriplane"}:
        raise ReleaseSetError("core must contain only the root distribution")
    if complete["adapters"] != set(EXPECTED_PROJECTS):
        raise ReleaseSetError("adapters must close over the complete package family")
    if complete["compat"] != set(EXPECTED_PROJECTS) or complete["full"] != set(EXPECTED_PROJECTS):
        raise ReleaseSetError("compat and full must cover every packaged project")
    gpu = sets["gpu"]
    variants = gpu.get("variants") if isinstance(gpu, Mapping) else None
    if variants != {"cuda12x": ["gpu-cuda12x"], "cuda13x": ["gpu-cuda13x"]}:
        raise ReleaseSetError("GPU variants are not exact and mutually selectable")
    for extras in variants.values():
        if not set(extras) <= root_extras:
            raise ReleaseSetError("GPU variant names an unknown root extra")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--registry", type=Path, default=Path("docs/status/release-sets.json"))
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/metriplane.release-sets.v1.schema.json")
    )
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    try:
        validate(root, (root / args.registry).resolve(), (root / args.schema).resolve())
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        ReleaseSetError,
    ) as exc:
        print(f"release-set validation failed: {exc}", file=sys.stderr)
        return 1
    print("release-set validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
