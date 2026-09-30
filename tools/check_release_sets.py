#!/usr/bin/env python3
"""Validate the canonical v0.5 installable-family release-set BOM."""

from __future__ import annotations

import argparse
import ast
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
EXPECTED_VERSION_COORDINATES: Mapping[str, Mapping[str, str]] = {
    "maniskill-pickcube": {
        "authority_kind": "pyproject-static",
        "authority_path": "adapters/maniskill_pickcube/pyproject.toml",
        "authority_pointer": "project.version",
        "cross_adapter_component_id": "maniskill-pickcube",
        "current_version": "1.0.0",
        "lock_package": "maniskill-pickcube-adapter",
    },
    "massrobotics-amr": {
        "authority_kind": "pyproject-static",
        "authority_path": "adapters/massrobotics_amr/pyproject.toml",
        "authority_pointer": "project.version",
        "cross_adapter_component_id": "massrobotics-amr",
        "current_version": "1.0.0",
        "lock_package": "metriplane-massrobotics-amr-adapter",
    },
    "metriplane": {
        "authority_kind": "python-attribute",
        "authority_path": "metriplane/__init__.py",
        "authority_pointer": "__version__",
        "current_version": "0.5.0.dev0",
        "lock_package": "metriplane",
    },
    "robomimic-lowdim": {
        "authority_kind": "pyproject-static",
        "authority_path": "adapters/robomimic_lowdim/pyproject.toml",
        "authority_pointer": "project.version",
        "cross_adapter_component_id": "robomimic-lowdim",
        "current_version": "1.0.0",
        "lock_package": "robomimic-lowdim-adapter",
    },
    "ros2-mcap": {
        "authority_kind": "pyproject-static",
        "authority_path": "adapters/ros2_mcap/pyproject.toml",
        "authority_pointer": "project.version",
        "cross_adapter_component_id": "ros2-mcap",
        "current_version": "1.0.0",
        "lock_package": "metriplane-ros2-mcap-adapter",
    },
    "source-adapter-sdk": {
        "authority_kind": "pyproject-static",
        "authority_path": "adapters/source_adapter_sdk/pyproject.toml",
        "authority_pointer": "project.version",
        "cross_adapter_component_id": "source-adapter-sdk",
        "current_version": "1.0.0",
        "lock_package": "metriplane-source-adapter-sdk",
    },
}
EXPECTED_SCHEMA_SHA256 = "d58b0e6899af5ca892fb074419c0d238a52bf6a815bc978f1b17fcddf30eca35"
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


def _literal_assignment(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    if len(values) != 1:
        raise ReleaseSetError(f"{path}: {name} must have one literal string assignment")
    return values[0]


def _validate_historical_baseline(root: Path, registry: Mapping[str, Any]) -> None:
    baseline = registry.get("historical_audit_baseline")
    expected = {
        "authority_path": "tests/adapter_conformance/registry.json",
        "audited_base_commit": "34099903b3c3fdeb4f794edceddbf845a3f4aba8",
        "current_release_set_authority": False,
        "relationship": "historical-adapter-audit-baseline",
    }
    if baseline != expected:
        raise ReleaseSetError("historical adapter audit baseline relationship is not exact")
    adapter_registry = _read_json(root / "tests/adapter_conformance/registry.json")
    if adapter_registry.get("audited_base_commit") != expected["audited_base_commit"]:
        raise ReleaseSetError("historical adapter audit baseline differs from its authority")


def _cross_adapter_versions(root: Path) -> Mapping[str, str]:
    registry = _read_json(root / "tests/adapter_conformance/registry.json")
    components = [*registry.get("shared_infrastructure", []), *registry.get("adapters", [])]
    if not all(isinstance(component, Mapping) for component in components):
        raise ReleaseSetError("cross-adapter component records are malformed")
    versions = {
        str(component["component_id"]): str(component["package_version"])
        for component in components
    }
    expected = set(EXPECTED_PROJECTS) - {"metriplane"}
    if set(versions) != expected:
        raise ReleaseSetError("cross-adapter version component set is not exact")
    return versions


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

    if set(registry) != {
        "historical_audit_baseline",
        "owner",
        "projects",
        "python_requires",
        "schema_version",
        "sets",
    }:
        raise ReleaseSetError("registry fields are not exact")
    if registry.get("owner") != "MP2-041":
        raise ReleaseSetError("registry owner is not MP2-041")
    if registry.get("schema_version") != "metriplane.release-sets.v1":
        raise ReleaseSetError("registry schema version is not exact")
    if registry.get("python_requires") != ">=3.12,<3.14":
        raise ReleaseSetError("registry Python contract is not exact")

    projects = registry.get("projects")
    sets = registry.get("sets")
    if not isinstance(projects, Mapping) or set(projects) != set(EXPECTED_PROJECTS):
        raise ReleaseSetError("project BOM is not the exact v0.5 package family")
    if not isinstance(sets, Mapping) or set(sets) != set(EXPECTED_SET_SHAPES):
        raise ReleaseSetError("release-set names are not exact")

    _validate_historical_baseline(root, registry)
    cross_adapter_versions = _cross_adapter_versions(root)
    root_extras: set[str] = set()
    for project_id, raw in projects.items():
        if not isinstance(raw, Mapping):
            raise ReleaseSetError(f"project {project_id} is malformed")
        expected_project = EXPECTED_PROJECTS[project_id]
        if {key: raw.get(key) for key in expected_project} != expected_project:
            raise ReleaseSetError(f"project {project_id} BOM coordinates are not exact")
        if set(raw) != {*expected_project, "version_coordinate"}:
            raise ReleaseSetError(f"project {project_id} fields are not exact")
        coordinate = raw.get("version_coordinate")
        if coordinate != EXPECTED_VERSION_COORDINATES[project_id]:
            raise ReleaseSetError(f"project {project_id} version coordinate is not exact")
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
        current_version = coordinate["current_version"]
        if coordinate["authority_kind"] == "pyproject-static":
            if metadata.get("version") != current_version:
                raise ReleaseSetError(f"project {project_id} pyproject version differs")
        else:
            pyproject = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("dynamic") != ["version"]:
                raise ReleaseSetError("root project version must remain dynamic")
            if pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get(
                "version", {}
            ).get("attr") != ("metriplane.__version__"):
                raise ReleaseSetError("root project version attribute differs")
            if _literal_assignment(
                root / coordinate["authority_path"], coordinate["authority_pointer"]
            ) != (current_version):
                raise ReleaseSetError("root project version authority differs")
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        lock_records = [
            package
            for package in lock.get("package", [])
            if package.get("name") == coordinate["lock_package"]
        ]
        if len(lock_records) != 1 or lock_records[0].get("source") != {"editable": "."}:
            raise ReleaseSetError(f"project {project_id} editable lock identity differs")
        lock_version = lock_records[0].get("version")
        if project_id == "metriplane":
            if lock_version is not None:
                raise ReleaseSetError("dynamic root lock must not assert a static version")
        elif lock_version != current_version:
            raise ReleaseSetError(f"project {project_id} lock version differs")
        component_id = coordinate.get("cross_adapter_component_id")
        if project_id == "metriplane":
            if component_id is not None:
                raise ReleaseSetError("root project may not claim a cross-adapter component")
        elif (
            not isinstance(component_id, str)
            or cross_adapter_versions.get(component_id) != current_version
        ):
            raise ReleaseSetError(f"project {project_id} cross-adapter version differs")
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
