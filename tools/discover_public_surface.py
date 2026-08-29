# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Discover and govern Metriplane's maintained public repository surface."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import configparser
import copy
import csv
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, NoReturn

import yaml

TASK_ID = "MP2-013"
ISSUE_ID = "MET-78"
PROFILE_ID = "repository.current-public-surface.static"
ROW_PREFIX = f"{TASK_ID}.PUBLIC."
MATERIALIZATION_SHA256 = "c60407ff3f8cd4f6f67cfab644425ea88e6fa735439c285bdb4315561df7e471"
CONSUMERS = ("MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018")
SCANNER_PATH = "tools/discover_public_surface.py"
INVENTORY_PATH = "docs/status/functional-inventory.json"
PROFILES_PATH = "docs/status/support-profiles.json"
DOCS_PATH = "docs/status/public-surface-inventory.md"
GENERATED_TARGETS = frozenset((INVENTORY_PATH, PROFILES_PATH, DOCS_PATH))
TRANSACTION_JOURNAL_NAME = ".public-surface-generation.transaction.json"
TRANSACTION_SCHEMA = "metriplane.public-surface-generation-transaction.v1"
GENERATION_LOCK_NAME = "metriplane-public-surface-generation.lock"
ANNOTATION_SHAPE_ATTRIBUTE = "_metriplane_manifest_shape"
ANNOTATION_CLASS_FIELDS_ATTRIBUTE = "_metriplane_manifest_class_fields"
ANNOTATIONS_POSTPONED_ATTRIBUTE = "_metriplane_annotations_postponed"
IMPLICIT_DECORATOR_CALL_ATTRIBUTE = "_metriplane_implicit_decorator_call"
VARIABLE_ANNOTATION_EXECUTED_ATTRIBUTE = "_metriplane_variable_annotation_executed"
FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE = "_metriplane_definition_assignments"
FUNCTION_DEFAULT_ASSIGNMENTS_ATTRIBUTE = "_metriplane_default_assignments"
CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE = "_metriplane_class_definition_assignments"
CLASS_BASE_BINDINGS_ATTRIBUTE = "_metriplane_class_base_bindings"
SNAPSHOT_SOURCE_EXPRESSION_ATTRIBUTE = "_metriplane_snapshot_source_expression"
ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE = "_metriplane_assignment_origin_module"
ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE = "_metriplane_assignment_origin_scope"
MUTATING_CONTAINER_METHODS = frozenset(
    (
        "__delitem__",
        "__iadd__",
        "__imul__",
        "__ior__",
        "__setitem__",
        "add",
        "append",
        "clear",
        "difference_update",
        "delitem",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "setitem",
        "sort",
        "symmetric_difference_update",
        "update",
    )
)
QUALIFIED_ARGUMENT_MUTATORS = frozenset(
    (
        "heapify",
        "heappop",
        "heappush",
        "heappushpop",
        "iadd",
        "iand",
        "iconcat",
        "ifloordiv",
        "ilshift",
        "imatmul",
        "imod",
        "imul",
        "insort",
        "insort_left",
        "insort_right",
        "ior",
        "ipow",
        "irshift",
        "isub",
        "itruediv",
        "ixor",
        "mutate",
        "setitem",
        "delitem",
        "heapreplace",
    )
)
RETAINED_INVALID_CONFIGS = {
    "configs/examples/config.m8_fusion_live.yaml": (
        "bfdbc6ac1261f661eadf37be968adb8f13a29070744d384c1a7ae5def2f778ea"
    ),
    "configs/health_demo.yaml": (
        "80a0ca7c40f6f6a02110aeaaaf7ddc2f402348b9df7a386f7f2eed2c45dc3c2d"
    ),
}
CHECKSUM_PINNED_MANIFEST_LEAVES = {
    "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py": (
        "87920c6da5bd447b0367f26b7230120257bc7312e98bfac651399706af89e0f9",
        ((1077, 36, "config['target_polygon']['center']"),),
    ),
    "integrations/isaac/metriplane_to_usd.py": (
        "5a8fdaa4f64466df75a6d749a3d784069943092a82037c14a76d02aa7eb5e85e",
        (
            (134, 15, "max((t.samples[-1][0] for t in tracks if t.samples), default=0)"),
            (228, 22, "[t.object_id for t in tracks]"),
            (229, 24, "[i.get('incident_id') for i in incidents]"),
        ),
    ),
}
CHECKSUM_PINNED_MANIFEST_SUBTREES = {
    "adapters/ros2_mcap/src/ros2_mcap_adapter/fixture.py": (
        "85614bfb3650b4bee39d6937a3a759945faa0a821ec6a654bfade1d561e81804",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/decoder.py",
        "aa86935989afc7a1d7343d5a07f212b14b9d00766d8482d4dd3a8b7e87a2455c",
        (
            (
                904,
                37,
                "list(source.channel_inventory)",
                (
                    418,
                    12,
                    "{'channel_id': channel.id, 'message_encoding': channel.message_encoding, 'schema_id': channel.schema_id, 'topic': channel.topic}",
                ),
                (
                    "/*/channel_id",
                    "/*/message_encoding",
                    "/*/schema_id",
                    "/*/topic",
                ),
            ),
            (
                912,
                36,
                "list(source.schema_inventory)",
                (
                    409,
                    12,
                    "{'encoding': schema.encoding, 'name': schema.name, 'schema_id': schema.id, 'sha256': sha256_bytes(schema.data)}",
                ),
                ("/*/encoding", "/*/name", "/*/schema_id", "/*/sha256"),
            ),
        ),
    ),
    "tools/release_artifacts.py": (
        "810cf8fc56a47c6d2ab686f51ab1afdd1acd0a219bce556534630df093059125",
        "tools/release_artifacts.py",
        "810cf8fc56a47c6d2ab686f51ab1afdd1acd0a219bce556534630df093059125",
        (
            (
                478,
                11,
                "digests",
                (
                    470,
                    14,
                    "{path.name: sha256_file(path) for path in sorted((wheel, sdist), key=lambda p: p.name)}",
                ),
                ("/*",),
            ),
        ),
    ),
}
INVENTORY_VALIDATOR = (
    "tests/test_discover_public_surface.py::test_committed_inventory_matches_current_public_surface"
)

FAMILY_KIND = {
    "configs": "maintained_config",
    "current_claims": "current_claim",
    "examples": "maintained_example",
    "jobs": "workflow_job_declaration",
    "manifest_keys": "artifact_manifest_key",
    "model_fields": "python_model_field",
    "models": "python_model",
    "proofs": "maintained_proof",
    "public_api": "python_public_api",
    "resources": "repository_resource",
    "workflows": "workflow_declaration",
}
FAMILY_ID = {
    "configs": "CONFIG",
    "current_claims": "CLAIM",
    "examples": "EXAMPLE",
    "jobs": "JOB",
    "manifest_keys": "MANIFEST_KEY",
    "model_fields": "MODEL_FIELD",
    "models": "MODEL",
    "proofs": "PROOF",
    "public_api": "API",
    "resources": "RESOURCE",
    "workflows": "WORKFLOW",
}
FAMILY_OBLIGATION = {
    "configs": "MP2-013.OBL.RESOURCE_DISCOVERY",
    "current_claims": "MP2-013.OBL.CURRENT_CLAIM_DISCOVERY",
    "examples": "MP2-013.OBL.RESOURCE_DISCOVERY",
    "jobs": "MP2-013.OBL.WORKFLOW_JOB_DISCOVERY",
    "manifest_keys": "MP2-013.OBL.MANIFEST_KEY_DISCOVERY",
    "model_fields": "MP2-013.OBL.MODEL_DISCOVERY",
    "models": "MP2-013.OBL.MODEL_DISCOVERY",
    "proofs": "MP2-013.OBL.RESOURCE_DISCOVERY",
    "public_api": "MP2-013.OBL.PUBLIC_API_DISCOVERY",
    "resources": "MP2-013.OBL.RESOURCE_DISCOVERY",
    "workflows": "MP2-013.OBL.WORKFLOW_JOB_DISCOVERY",
}
MODEL_BASES = frozenset(("BaseModel", "Enum", "IntEnum", "NamedTuple", "StrEnum", "TypedDict"))
KNOWN_EXTERNAL_CALLABLE_OBJECTS = frozenset({("time", "sleep")})

JsonObject = dict[str, Any]
AssignmentMap = dict[str, tuple[ast.AST, ...]]
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
CallbackBinding = tuple[FunctionNode | ast.Lambda, str, int]
ClassFields = dict[str, dict[str, ast.AST]]
ExternalClasses = dict[tuple[str, str], dict[str, ast.AST]]
ExternalClassAssignments = dict[tuple[str, str], AssignmentMap]


class DiscoveryError(ValueError):
    """A maintained source cannot be interpreted without guessing."""


@dataclass(frozen=True)
class PythonModule:
    module: str
    path: str
    tree: ast.Module

    def __post_init__(self) -> None:
        postponed = any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == "__future__"
            and any(alias.name == "annotations" for alias in statement.names)
            for statement in self.tree.body
        )
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
                setattr(node, ANNOTATIONS_POSTPONED_ATTRIBUTE, postponed)

        def mark_variable_annotations(node: ast.AST, *, executed: bool) -> None:
            if isinstance(node, ast.AnnAssign):
                setattr(node, VARIABLE_ANNOTATION_EXECUTED_ATTRIBUTE, executed)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                for statement in node.body:
                    mark_variable_annotations(statement, executed=False)
                return
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    mark_variable_annotations(statement, executed=not postponed)
                return
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    mark_variable_annotations(child, executed=executed)

        for statement in self.tree.body:
            mark_variable_annotations(statement, executed=not postponed)


@dataclass
class FunctionContext:
    node: FunctionNode
    source: str
    module_assignments: AssignmentMap
    definition_assignments: AssignmentMap
    default_assignments: AssignmentMap
    functions: dict[str, FunctionContext] = dataclass_field(default_factory=dict)
    qualified_functions: dict[tuple[str, str], FunctionContext] = dataclass_field(
        default_factory=dict
    )
    qualified_classes: ExternalClasses = dataclass_field(default_factory=dict)
    qualified_class_assignments: ExternalClassAssignments = dataclass_field(default_factory=dict)
    qualified_assignments: dict[str, AssignmentMap] = dataclass_field(default_factory=dict)
    classes: ClassFields = dataclass_field(default_factory=dict)
    direct_mutated_free_bindings: frozenset[str] | None = None
    mutated_free_bindings: frozenset[str] | None = None
    mutated_parameters: frozenset[str] | None = None


ExternalFunctions = dict[tuple[str, str], FunctionContext]


class _ManifestShape(Enum):
    KEYS = "keys"
    LEAF = "leaf"
    UNKNOWN = "unknown"


class _ProvenanceState(Enum):
    KNOWN = "known"
    IRRELEVANT = "irrelevant"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class _Provenance[T]:
    state: _ProvenanceState
    values: frozenset[T] = frozenset()

    def conservative(self, universe: Iterable[T]) -> set[T]:
        values = set(self.values)
        if self.state is _ProvenanceState.UNRESOLVED:
            values.update(universe)
        return values


def _known_provenance[T](values: Iterable[T]) -> _Provenance[T]:
    frozen = frozenset(values)
    return _Provenance(
        _ProvenanceState.KNOWN if frozen else _ProvenanceState.IRRELEVANT,
        frozen,
    )


def _irrelevant_provenance[T]() -> _Provenance[T]:
    return _Provenance(_ProvenanceState.IRRELEVANT)


def _unresolved_provenance[T](values: Iterable[T] = ()) -> _Provenance[T]:
    return _Provenance(_ProvenanceState.UNRESOLVED, frozenset(values))


def _merge_provenance[T](results: Iterable[_Provenance[T]]) -> _Provenance[T]:
    collected = tuple(results)
    values = frozenset(value for result in collected for value in result.values)
    if any(result.state is _ProvenanceState.UNRESOLVED for result in collected):
        return _Provenance(_ProvenanceState.UNRESOLVED, values)
    return _known_provenance(values)


class _ImportBinding(ast.AST):
    _fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *, module: str, symbol: str | None = None) -> None:
        self.module = module
        self.symbol = symbol


class _ClassBinding(ast.expr):
    _fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *, module: str, symbol: str, node: ast.ClassDef) -> None:
        self.module = module
        self.symbol = symbol
        self.node = node
        self.invalidated = False


class _FunctionBinding(ast.expr):
    _fields: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        *,
        module: str,
        symbol: str,
        node: FunctionNode | ast.Lambda,
        implicit_positional_count: int = 0,
    ) -> None:
        self.module = module
        self.symbol = symbol
        self.node = node
        self.implicit_positional_count = implicit_positional_count


class _UnknownBinding(ast.AST):
    _fields: ClassVar[tuple[str, ...]] = ()


@dataclass(frozen=True)
class Discovery:
    config_parser_counts: dict[str, int]
    family_counts: dict[str, int]
    family_digests: dict[str, str]
    resource_facets: dict[str, int]
    source_counts: dict[str, int]
    rows: tuple[JsonObject, ...]


def _fail(message: str) -> NoReturn:
    raise DiscoveryError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _document_bytes(value: Any) -> bytes:
    return _canonical_bytes(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_constant(value: str) -> NoReturn:
    _fail(f"non-finite JSON constant is forbidden: {value}")


def _reject_pairs(pairs: list[tuple[str, Any]]) -> JsonObject:
    value: JsonObject = {}
    for key, item in pairs:
        if key in value:
            _fail(f"duplicate JSON key is forbidden: {key!r}")
        value[key] = item
    return value


def _read_json(path: Path, *, require_object: bool = True) -> Any:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"cannot parse strict JSON {path}: {exc}") from exc
    if require_object and not isinstance(value, dict):
        _fail(f"canonical JSON must be an object: {path}")
    return value


class _StrictYamlLoader(yaml.SafeLoader):
    pass


_StrictYamlLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for _resolver_key, _resolvers in list(_StrictYamlLoader.yaml_implicit_resolvers.items()):
    _StrictYamlLoader.yaml_implicit_resolvers[_resolver_key] = [
        item for item in _resolvers if item[0] != "tag:yaml.org,2002:bool"
    ]
_StrictYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)  # type: ignore[no-untyped-call]


def _strict_yaml_mapping(
    loader: _StrictYamlLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> JsonObject:
    authored: set[str] = set()
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=False)
        if not isinstance(key, str) or not key:
            _fail("YAML mapping keys must be non-empty strings")
        if key in authored:
            _fail(f"duplicate YAML key is forbidden: {key!r}")
        authored.add(key)
    loader.flatten_mapping(node)
    result: JsonObject = {}
    for key, value in loader.construct_pairs(node, deep=deep):
        if not isinstance(key, str) or not key:
            _fail("YAML mapping keys must be non-empty strings")
        result[key] = value
    return result


_StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_yaml_mapping
)


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictYamlLoader)
    except DiscoveryError as exc:
        raise DiscoveryError(f"cannot parse strict YAML {path}: {exc}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise DiscoveryError(f"cannot parse strict YAML {path}: {exc}") from exc


def _read_toml(path: Path) -> JsonObject:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DiscoveryError(f"cannot parse TOML {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"TOML root must be a table: {path}")
    return value


def _canonical_relative(relative: str) -> None:
    if (
        not relative
        or Path(relative).is_absolute()
        or "\\" in relative
        or PurePosixPath(relative).as_posix() != relative
        or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
    ):
        _fail(f"repository path is not canonical: {relative!r}")


def _repository_entry(root: Path, relative: str) -> Path:
    _canonical_relative(relative)
    candidate = root.joinpath(*relative.split("/"))
    try:
        candidate.relative_to(root)
        resolved_parent = candidate.parent.resolve(strict=True)
        candidate.lstat()
    except (OSError, ValueError) as exc:
        raise DiscoveryError(f"repository source is unavailable: {relative}: {exc}") from exc
    if not resolved_parent.is_relative_to(root):
        _fail(f"repository source parent escapes the repository: {relative}")
    return candidate


def _regular_file(root: Path, relative: str) -> Path:
    path = _repository_entry(root, relative)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DiscoveryError(f"cannot resolve repository source {relative}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"parser source must be a regular non-symlink file: {relative}")
    if not resolved.is_relative_to(root):
        _fail(f"repository source escapes the repository: {relative}")
    return resolved


def _path_digest(root: Path, relative: str) -> str:
    path = _repository_entry(root, relative)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        if Path(target).is_absolute():
            _fail(f"tracked symlink target must be relative: {relative}")
        try:
            resolved = (path.parent / target).resolve(strict=True)
        except OSError as exc:
            raise DiscoveryError(
                f"tracked symlink target is unavailable: {relative}: {exc}"
            ) from exc
        if not resolved.is_relative_to(root):
            _fail(f"tracked symlink escapes the repository: {relative}")
        payload = target.encode("utf-8")
    elif stat.S_ISREG(info.st_mode):
        payload = path.read_bytes()
    else:
        _fail(f"tracked path is neither a regular file nor symlink: {relative}")
    return hashlib.sha256(payload).hexdigest()


def _tracked_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        _fail(f"git tracked-path discovery failed: {completed.stderr.decode(errors='replace')}")
    try:
        raw = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiscoveryError("tracked repository paths are not UTF-8") from exc
    if raw and not raw.endswith("\0"):
        _fail("git tracked-path stream is not NUL terminated")
    paths = tuple(raw[:-1].split("\0")) if raw else ()
    if not paths or list(paths) != sorted(set(paths)):
        _fail("tracked repository paths must be non-empty, unique, and sorted")
    for relative in paths:
        _canonical_relative(relative)
    return paths


def _parse_python(root: Path, relative: str) -> ast.Module:
    path = _regular_file(root, relative)
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise DiscoveryError(f"cannot parse Python source {relative}: {exc}") from exc


def _string_array(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        _fail(f"{label} must be a non-empty array of strings")
    if len(value) != len(set(value)):
        _fail(f"{label} must not contain duplicates")
    return tuple(value)


def _packaged_modules(root: Path, tracked: tuple[str, ...]) -> tuple[PythonModule, ...]:
    tracked_set = set(tracked)
    selected: dict[str, str] = {}
    root_project = _read_toml(_regular_file(root, "pyproject.toml"))
    try:
        finder = root_project["tool"]["setuptools"]["packages"]["find"]
    except (KeyError, TypeError) as exc:
        raise DiscoveryError("root project has no canonical setuptools package finder") from exc
    if not isinstance(finder, dict):
        _fail("root setuptools package finder must be a table")
    where = _string_array(finder.get("where"), label="tool.setuptools.packages.find.where")
    include = _string_array(finder.get("include"), label="tool.setuptools.packages.find.include")
    exclude_value = finder.get("exclude", [])
    if not isinstance(exclude_value, list) or any(
        not isinstance(item, str) for item in exclude_value
    ):
        _fail("tool.setuptools.packages.find.exclude must be an array of strings")
    exclude = tuple(exclude_value)
    for base in where:
        prefix = "" if base == "." else f"{base.rstrip('/')}/"
        for relative in tracked:
            if not relative.startswith(prefix) or not relative.endswith(".py"):
                continue
            local = relative[len(prefix) :]
            parent = PurePosixPath(local).parent
            if str(parent) == ".":
                continue
            package = ".".join(parent.parts)
            init_path = f"{prefix}{parent.as_posix()}/__init__.py"
            if init_path not in tracked_set:
                continue
            if not any(fnmatch.fnmatchcase(package, pattern) for pattern in include):
                continue
            if any(fnmatch.fnmatchcase(package, pattern) for pattern in exclude):
                continue
            name = PurePosixPath(local).name
            module = package if name == "__init__.py" else f"{package}.{name[:-3]}"
            selected[relative] = module

    adapter_projects = sorted(
        path
        for path in tracked
        if re.fullmatch(r"adapters/[^/]+/pyproject\.toml", path) is not None
    )
    for project_path in adapter_projects:
        project = _read_toml(_regular_file(root, project_path))
        try:
            package_paths = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        except (KeyError, TypeError) as exc:
            raise DiscoveryError(
                f"adapter project has no canonical wheel packages: {project_path}"
            ) from exc
        packages = _string_array(package_paths, label=f"{project_path} wheel packages")
        project_root = PurePosixPath(project_path).parent
        for package_path in packages:
            package_root = (project_root / package_path).as_posix().rstrip("/")
            package_name = PurePosixPath(package_path).name
            init_path = f"{package_root}/__init__.py"
            if init_path not in tracked_set:
                _fail(f"declared adapter package has no tracked __init__.py: {package_root}")
            for relative in tracked:
                if not relative.startswith(f"{package_root}/") or not relative.endswith(".py"):
                    continue
                relative_module_path = PurePosixPath(relative).relative_to(package_root)
                parts = list(relative_module_path.parts)
                if parts[-1] == "__init__.py":
                    parts.pop()
                else:
                    parts[-1] = parts[-1][:-3]
                module = ".".join((package_name, *parts)) if parts else package_name
                if relative in selected and selected[relative] != module:
                    _fail(f"packaged Python path has conflicting module names: {relative}")
                selected[relative] = module

    if not selected:
        _fail("project metadata selected no packaged Python modules")
    module_names = list(selected.values())
    if len(module_names) != len(set(module_names)):
        _fail("project metadata produces duplicate packaged module names")
    return tuple(
        PythonModule(module=module, path=path, tree=_parse_python(root, path))
        for path, module in sorted(selected.items())
    )


def _manifest_modules(
    root: Path,
    tracked: tuple[str, ...],
    packaged_modules: tuple[PythonModule, ...],
) -> tuple[PythonModule, ...]:
    selected = {module.path: module for module in packaged_modules}
    for relative in tracked:
        path = PurePosixPath(relative)
        if (
            not relative.endswith(".py")
            or relative == SCANNER_PATH
            or "tests" in path.parts
            or path.name == "conftest.py"
            or path.name.startswith("test_")
            or relative in selected
        ):
            continue
        parts = list(path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            _fail(f"manifest Python path has no canonical module name: {relative}")
        selected[relative] = PythonModule(
            module=".".join(parts),
            path=relative,
            tree=_parse_python(root, relative),
        )
    module_names = [module.module for module in selected.values()]
    if len(module_names) != len(set(module_names)):
        _fail("maintained manifest Python paths produce duplicate module names")
    return tuple(selected[path] for path in sorted(selected))


def _literal_exports(node: ast.AST, *, source: str) -> tuple[str, ...]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        _fail(f"dynamic __all__ is forbidden in {source}")
    exports: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or not item.value:
            _fail(f"__all__ entries must be non-empty literal strings in {source}")
        exports.append(item.value)
    if len(exports) != len(set(exports)):
        _fail(f"duplicate __all__ export in {source}")
    return tuple(sorted(exports))


def _assigned_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.List, ast.Tuple)):
        return tuple(name for item in target.elts for name in _assigned_names(item))
    return ()


def _module_bindings(module: PythonModule) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in module.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = (
                "class"
                if isinstance(node, ast.ClassDef)
                else "async_function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function"
            )
            bindings[node.name] = kind
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".", 1)[0]] = "imported_symbol"
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    _fail(f"wildcard import prevents static public API discovery: {module.path}")
                bindings[alias.asname or alias.name] = "imported_symbol"
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assigned_names(target):
                    if name != "__all__":
                        bindings[name] = "constant"
        elif isinstance(node, ast.AnnAssign):
            for name in _assigned_names(node.target):
                if name != "__all__":
                    bindings[name] = "constant"
    return bindings


def _public_bindings(module: PythonModule) -> tuple[tuple[str, str], ...]:
    exports: list[tuple[str, ...]] = []
    for node in module.tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            exports.append(_literal_exports(node.value, source=module.path))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__all__":
                if node.value is None:
                    _fail(f"dynamic __all__ is forbidden in {module.path}")
                exports.append(_literal_exports(node.value, source=module.path))
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__all__":
                _fail(f"incremental __all__ is forbidden in {module.path}")
    if len(exports) > 1:
        _fail(f"__all__ must be assigned exactly once in {module.path}")
    bindings = _module_bindings(module)
    names = (
        exports[0]
        if exports
        else tuple(sorted(name for name in bindings if not name.startswith("_")))
    )
    missing = [name for name in names if name not in bindings]
    if missing:
        _fail(f"__all__ contains statically unresolved exports in {module.path}: {missing}")
    return tuple((name, bindings[name]) for name in names)


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _terminal_name(node.value)
    return None


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if _terminal_name(target) == "dataclass":
            return True
    return False


def _model_nodes(module: PythonModule) -> tuple[tuple[ast.ClassDef, str], ...]:
    classes = {node.name: node for node in module.tree.body if isinstance(node, ast.ClassDef)}
    models: dict[str, str] = {}
    for name, node in classes.items():
        bases = {_terminal_name(base) for base in node.bases}
        if _is_dataclass(node):
            models[name] = "dataclass"
        elif bases & {"BaseModel"}:
            models[name] = "pydantic_model"
        elif bases & {"Enum", "IntEnum", "StrEnum"}:
            models[name] = "enum_model"
        elif bases & {"TypedDict"}:
            models[name] = "typed_dict"
        elif bases & {"NamedTuple"}:
            models[name] = "named_tuple"
    changed = True
    while changed:
        changed = False
        for name, node in classes.items():
            if name in models:
                continue
            if any(_terminal_name(base) in models for base in node.bases):
                models[name] = "inherited_model"
                changed = True
    return tuple((classes[name], models[name]) for name in sorted(models))


def _model_fields(node: ast.ClassDef, kind: str) -> tuple[str, ...]:
    fields: list[str] = []
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if _terminal_name(statement.annotation) != "ClassVar":
                fields.append(statement.target.id)
        elif kind == "enum_model" and isinstance(statement, ast.Assign):
            for target in statement.targets:
                fields.extend(name for name in _assigned_names(target) if not name.startswith("_"))
    if len(fields) != len(set(fields)):
        _fail(f"model {node.name} declares duplicate fields")
    return tuple(sorted(fields))


def _normalize(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return normalized[:72] or "ITEM"


def _stable_id(family: str, key: str) -> str:
    suffix = hashlib.sha256(f"{family}\0{key}".encode()).hexdigest()[:12].upper()
    return f"{ROW_PREFIX}{FAMILY_ID[family]}.{_normalize(key)}.{suffix}"


def _source(
    root: Path,
    path: str,
    locator: str,
    *,
    source_type: str = "repository_discovery",
    digest: str | None = None,
) -> JsonObject:
    entry = _repository_entry(root, path)
    if stat.S_ISLNK(entry.lstat().st_mode):
        link_digest = _path_digest(root, path)
        locator = f"{locator};tracked-symlink:{path};link-sha256:{link_digest}"
        path = SCANNER_PATH
    return {
        "digest_sha256": digest or _path_digest(root, path),
        "locator": locator,
        "path": path,
        "type": source_type,
    }


def _row(
    *,
    root: Path,
    family: str,
    key: str,
    name: str,
    statement: str,
    source: JsonObject,
    criteria: tuple[str, ...] = ("MP2-013.A01",),
) -> JsonObject:
    return {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": [],
            "statement": statement,
        },
        "consumer_task_ids": list(CONSUMERS),
        "id": _stable_id(family, key),
        "kind": FAMILY_KIND[family],
        "name": name,
        "owner": TASK_ID,
        "profile": PROFILE_ID,
        "source": source,
        "status": "active",
        "test": FAMILY_OBLIGATION[family],
        "trace_criterion_ids": list(criteria),
        "validator_ids": [INVENTORY_VALIDATOR],
    }


def _python_rows(root: Path, modules: tuple[PythonModule, ...]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for module in modules:
        for name, api_kind in _public_bindings(module):
            qualified = f"{module.module}:{name}"
            rows.append(
                _row(
                    root=root,
                    family="public_api",
                    key=qualified,
                    name=qualified,
                    statement=(
                        f"Static AST discovery observes the {api_kind} {qualified}; this row "
                        "does not establish runtime or platform support."
                    ),
                    source=_source(root, module.path, qualified),
                )
            )
        for model, model_kind in _model_nodes(module):
            qualified = f"{module.module}:{model.name}"
            rows.append(
                _row(
                    root=root,
                    family="models",
                    key=qualified,
                    name=qualified,
                    statement=(
                        f"Static AST discovery observes the {model_kind} declaration {qualified}; "
                        "no generated runtime schema or support claim is implied."
                    ),
                    source=_source(root, module.path, qualified),
                )
            )
            for field in _model_fields(model, model_kind):
                field_name = f"{qualified}.{field}"
                rows.append(
                    _row(
                        root=root,
                        family="model_fields",
                        key=field_name,
                        name=field_name,
                        statement=(
                            f"Static AST discovery observes the declared model field {field_name}; "
                            "no generated runtime schema or support claim is implied."
                        ),
                        source=_source(root, module.path, field_name),
                    )
                )
    return rows


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_key_pointers(value: Any, pointer: str = "") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key in sorted(value):
            child = f"{pointer}/{_pointer_token(key)}"
            result.add(child)
            result.update(_json_key_pointers(value[key], child))
    elif isinstance(value, list):
        for item in value:
            result.update(_json_key_pointers(item, f"{pointer}/*"))
    return result


def _definition_time_expressions(node: ast.AST) -> tuple[ast.expr, ...]:
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
        arguments = node.args
        annotations = (
            []
            if getattr(node, ANNOTATIONS_POSTPONED_ATTRIBUTE, False)
            else [
                argument.annotation
                for argument in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                    *((arguments.vararg,) if arguments.vararg is not None else ()),
                    *((arguments.kwarg,) if arguments.kwarg is not None else ()),
                )
                if argument.annotation is not None
            ]
        )
        expressions: list[ast.expr] = []
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            expressions.extend(node.decorator_list)
        expressions.extend(
            (
                *arguments.defaults,
                *(default for default in arguments.kw_defaults if default is not None),
                *annotations,
            )
        )
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.returns is not None and not getattr(
                node, ANNOTATIONS_POSTPONED_ATTRIBUTE, False
            ):
                expressions.append(node.returns)
        return tuple(expressions)
    if isinstance(node, ast.ClassDef):
        return (
            *node.bases,
            *(keyword.value for keyword in node.keywords),
            *node.decorator_list,
        )
    return ()


def _implicit_decorator_calls(
    node: ast.AsyncFunctionDef | ast.ClassDef | ast.FunctionDef,
) -> tuple[ast.Call, ...]:
    calls: list[ast.Call] = []
    for decorator in reversed(node.decorator_list):
        call = ast.Call(
            func=decorator,
            args=[ast.Name(id=node.name, ctx=ast.Load())],
            keywords=[],
        )
        ast.copy_location(call, decorator)
        setattr(call, IMPLICIT_DECORATOR_CALL_ATTRIBUTE, True)
        calls.append(call)
    return tuple(calls)


def _field_argument_is_inert(
    node: ast.AST,
    assignments: AssignmentMap,
) -> bool:
    if isinstance(node, (ast.Constant, ast.Lambda)):
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        root = node.value
        while isinstance(root, ast.Attribute):
            root = root.value
        candidates = assignments.get(root.id, ()) if isinstance(root, ast.Name) else ()
        return (
            len(candidates) == 1
            and isinstance(candidates[0], _ImportBinding)
            and candidates[0].symbol is None
        )
    if isinstance(node, ast.Dict):
        return all(
            value is None or _field_argument_is_inert(value, assignments)
            for value in (*node.keys, *node.values)
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(_field_argument_is_inert(value, assignments) for value in node.elts)
    return False


def _class_value_may_be_descriptor(node: ast.AST, assignments: AssignmentMap) -> bool:
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, _FunctionBinding):
        return False
    if isinstance(node, _ClassBinding):
        return node.invalidated
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if len(candidates) == 1 and isinstance(candidates[0], _FunctionBinding):
            return False
        if len(candidates) == 1 and isinstance(candidates[0], _ClassBinding):
            return candidates[0].invalidated
    dataclass_field = isinstance(node, ast.Call) and (
        (
            isinstance(node.func, ast.Name)
            and _exact_definition_import(node.func, "dataclasses", "field", assignments)
        )
        or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "field"
            and _exact_definition_import(node.func.value, "dataclasses", None, assignments)
        )
    )
    if dataclass_field:
        if node.args or any(keyword.arg is None for keyword in node.keywords):
            return True
        return any(
            not _field_argument_is_inert(keyword.value, assignments)
            or (
                keyword.arg == "default"
                and _class_value_may_be_descriptor(keyword.value, assignments)
            )
            for keyword in node.keywords
        )
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        values = (*node.keys, *node.values) if isinstance(node, ast.Dict) else tuple(node.elts)
        return any(
            value is not None and _class_value_may_be_descriptor(value, assignments)
            for value in values
        )
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.IfExp, ast.UnaryOp)):
        return any(
            _class_value_may_be_descriptor(child, assignments)
            for child in ast.iter_child_nodes(node)
        )
    return not isinstance(node, ast.Lambda)


def _class_construction_may_execute_user_code(
    node: ast.ClassDef, assignments: AssignmentMap
) -> bool:
    if (
        any(not (isinstance(base, ast.Name) and base.id not in assignments) for base in node.bases)
        or node.keywords
    ):
        return True
    for statement in node.body:
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            value = statement.value
        if value is not None and _class_value_may_be_descriptor(value, assignments):
            return True
    return False


def _lexical_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    if isinstance(scope, ast.AnnAssign):
        yield scope.target
        yield from _lexical_nodes(scope.target)
        if scope.value is not None:
            yield scope.value
            yield from _lexical_nodes(scope.value)
        if getattr(scope, VARIABLE_ANNOTATION_EXECUTED_ATTRIBUTE, False):
            yield scope.annotation
            yield from _lexical_nodes(scope.annotation)
        return
    for child in ast.iter_child_nodes(scope):
        yield child
        if isinstance(child, ast.AnnAssign):
            yield from _lexical_nodes(child)
            continue
        if isinstance(
            child,
            (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef, ast.Lambda),
        ):
            for expression in _definition_time_expressions(child):
                yield expression
                yield from _lexical_nodes(expression)
            if isinstance(child, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
                for call in _implicit_decorator_calls(child):
                    yield call
                    yield from _lexical_nodes(call)
            continue
        yield from _lexical_nodes(child)


def _target_root_name(target: ast.AST) -> str | None:
    current = target
    while isinstance(current, (ast.Attribute, ast.Starred, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _static_sequence_elements(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[ast.AST, ...] | None:
    current = node
    while isinstance(current, ast.Name):
        candidates = definitions.get(current.id, ())
        if current.id in seen or len(candidates) != 1:
            return None
        seen = seen | {current.id}
        current = candidates[0]
    if not isinstance(current, (ast.List, ast.Tuple)):
        return None
    elements: list[ast.AST] = []
    for element in current.elts:
        if not isinstance(element, ast.Starred):
            elements.append(element)
            continue
        nested = _static_sequence_elements(
            element.value,
            definitions,
            seen=seen,
        )
        if nested is None:
            return None
        elements.extend(nested)
    return tuple(elements)


def _static_mapping_entries(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[tuple[ast.expr, ast.expr], ...] | None:
    current = node
    while isinstance(current, ast.Name):
        candidates = definitions.get(current.id, ())
        if current.id in seen or len(candidates) != 1:
            return None
        seen = seen | {current.id}
        current = candidates[0]
    if not isinstance(current, ast.Dict):
        return None
    entries: list[tuple[ast.expr, ast.expr]] = []
    for key, value in zip(current.keys, current.values, strict=True):
        if key is not None:
            entries.append((key, value))
            continue
        nested = _static_mapping_entries(
            value,
            definitions,
            seen=seen,
        )
        if nested is None:
            return None
        entries.extend(nested)
    return tuple(entries)


def _static_mapping_selection(
    node: ast.AST,
    key_value: object,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> _Provenance[ast.AST]:
    current = node
    while isinstance(current, ast.Name):
        candidates = definitions.get(current.id, ())
        if current.id in seen or len(candidates) != 1:
            return _unresolved_provenance()
        seen = seen | {current.id}
        current = candidates[0]
    if not isinstance(current, ast.Dict):
        return _unresolved_provenance()
    for key, value in reversed(tuple(zip(current.keys, current.values, strict=True))):
        if key is None:
            nested = _static_mapping_selection(
                value,
                key_value,
                definitions,
                seen=seen,
            )
            if nested.state is not _ProvenanceState.IRRELEVANT:
                return nested
            continue
        if not isinstance(key, ast.Constant):
            return _unresolved_provenance()
        if key.value == key_value:
            return _known_provenance((value,))
    return _irrelevant_provenance()


def _selected_reference_provenance(
    node: ast.Subscript,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> _Provenance[ast.AST]:
    container: ast.AST = node.value
    if isinstance(container, ast.Subscript):
        selected_container = _selected_reference_provenance(
            container,
            definitions,
            seen=seen,
        )
        if selected_container.state is not _ProvenanceState.KNOWN:
            return selected_container
        if len(selected_container.values) != 1:
            return _unresolved_provenance(selected_container.values)
        container = next(iter(selected_container.values))
    while isinstance(container, ast.Name):
        candidates = definitions.get(container.id, ())
        if container.id in seen or len(candidates) != 1:
            return _unresolved_provenance()
        seen = seen | {container.id}
        container = candidates[0]
    if isinstance(container, ast.Dict):
        if not isinstance(node.slice, ast.Constant):
            return _unresolved_provenance()
        return _static_mapping_selection(
            container,
            node.slice.value,
            definitions,
            seen=seen,
        )
    sequence_elements = _static_sequence_elements(container, definitions, seen=seen)
    if sequence_elements is not None:
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, int):
            return _unresolved_provenance()
        index = node.slice.value
        if -len(sequence_elements) <= index < len(sequence_elements):
            return _known_provenance((sequence_elements[index],))
        return _irrelevant_provenance()
    if isinstance(container, (ast.Constant, ast.Set)):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _selected_reference_expression(
    node: ast.Subscript,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> ast.AST | None:
    selected = _selected_reference_provenance(node, definitions, seen=seen)
    if selected.state is _ProvenanceState.KNOWN and len(selected.values) == 1:
        return next(iter(selected.values))
    return None


def _snapshot_bound_expression(
    node: ast.expr,
    definitions: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
    blocked: frozenset[str] = frozenset(),
) -> ast.expr:
    if isinstance(node, ast.Name):
        if node.id in blocked:
            return node
        candidates = definitions.get(node.id, ())
        if node.id not in seen and len(candidates) == 1 and isinstance(candidates[0], ast.expr):
            return candidates[0]
        return node
    if isinstance(node, ast.Subscript):
        selected = _selected_reference_expression(node, definitions, seen=seen)
        if isinstance(selected, ast.expr):
            return selected
        if isinstance(node.value, ast.Name):
            return node
        return ast.copy_location(
            ast.Subscript(
                value=_snapshot_bound_expression(
                    node.value, definitions, seen=seen, blocked=blocked
                ),
                slice=(
                    _snapshot_bound_expression(node.slice, definitions, seen=seen, blocked=blocked)
                    if isinstance(node.slice, ast.expr)
                    else node.slice
                ),
                ctx=getattr(node, "ctx", ast.Load()),
            ),
            node,
        )
    if isinstance(node, ast.Dict):
        return ast.copy_location(
            ast.Dict(
                keys=[
                    _snapshot_bound_expression(key, definitions, seen=seen, blocked=blocked)
                    if key is not None
                    else None
                    for key in node.keys
                ],
                values=[
                    _snapshot_bound_expression(value, definitions, seen=seen, blocked=blocked)
                    for value in node.values
                ],
            ),
            node,
        )
    if isinstance(node, ast.List):
        return ast.copy_location(
            ast.List(
                elts=[
                    _snapshot_bound_expression(value, definitions, seen=seen, blocked=blocked)
                    for value in node.elts
                ],
                ctx=node.ctx,
            ),
            node,
        )
    if isinstance(node, ast.Set):
        return ast.copy_location(
            ast.Set(
                elts=[
                    _snapshot_bound_expression(value, definitions, seen=seen, blocked=blocked)
                    for value in node.elts
                ]
            ),
            node,
        )
    if isinstance(node, ast.Tuple):
        return ast.copy_location(
            ast.Tuple(
                elts=[
                    _snapshot_bound_expression(value, definitions, seen=seen, blocked=blocked)
                    for value in node.elts
                ],
                ctx=node.ctx,
            ),
            node,
        )
    if isinstance(node, ast.Starred):
        return ast.copy_location(
            ast.Starred(
                value=_snapshot_bound_expression(
                    node.value, definitions, seen=seen, blocked=blocked
                ),
                ctx=node.ctx,
            ),
            node,
        )
    if isinstance(node, ast.BoolOp):
        return ast.copy_location(
            ast.BoolOp(
                op=node.op,
                values=[
                    _snapshot_bound_expression(value, definitions, seen=seen, blocked=blocked)
                    for value in node.values
                ],
            ),
            node,
        )
    if isinstance(node, ast.IfExp):
        return ast.copy_location(
            ast.IfExp(
                test=node.test,
                body=_snapshot_bound_expression(node.body, definitions, seen=seen, blocked=blocked),
                orelse=_snapshot_bound_expression(
                    node.orelse, definitions, seen=seen, blocked=blocked
                ),
            ),
            node,
        )
    if isinstance(node, ast.Attribute):
        return ast.copy_location(
            ast.Attribute(
                value=_snapshot_bound_expression(
                    node.value, definitions, seen=seen, blocked=blocked
                ),
                attr=node.attr,
                ctx=node.ctx,
            ),
            node,
        )
    if isinstance(node, ast.Call):
        replacement = ast.copy_location(
            ast.Call(
                func=node.func,
                args=[
                    _snapshot_bound_expression(argument, definitions, seen=seen, blocked=blocked)
                    for argument in node.args
                ],
                keywords=[
                    ast.keyword(
                        arg=keyword.arg,
                        value=_snapshot_bound_expression(
                            keyword.value,
                            definitions,
                            seen=seen,
                            blocked=blocked,
                        ),
                    )
                    for keyword in node.keywords
                ],
            ),
            node,
        )
        setattr(
            replacement,
            SNAPSHOT_SOURCE_EXPRESSION_ATTRIBUTE,
            getattr(node, SNAPSHOT_SOURCE_EXPRESSION_ATTRIBUTE, ast.unparse(node)),
        )
        for attribute in (
            ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
            ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE,
        ):
            if hasattr(node, attribute):
                setattr(replacement, attribute, getattr(node, attribute))
        return replacement
    if isinstance(node, ast.GeneratorExp):
        outer = node.generators[0]
        return ast.copy_location(
            ast.GeneratorExp(
                elt=node.elt,
                generators=[
                    ast.comprehension(
                        target=outer.target,
                        iter=_snapshot_bound_expression(
                            outer.iter,
                            definitions,
                            seen=seen,
                            blocked=blocked,
                        ),
                        ifs=outer.ifs,
                        is_async=outer.is_async,
                    ),
                    *node.generators[1:],
                ],
            ),
            node,
        )
    if isinstance(node, (ast.DictComp, ast.ListComp, ast.SetComp)):
        generator_blocked = blocked
        generators: list[ast.comprehension] = []
        for generator in node.generators:
            iterator_candidates = (
                definitions.get(generator.iter.id, ())
                if isinstance(generator.iter, ast.Name)
                else ()
            )
            iterator = (
                _snapshot_bound_expression(
                    generator.iter,
                    definitions,
                    seen=seen,
                    blocked=generator_blocked,
                )
                if not isinstance(generator.iter, ast.Name)
                or (
                    len(iterator_candidates) == 1
                    and _may_reference_mutable_literal(iterator_candidates[0], definitions)
                )
                else generator.iter
            )
            generator_blocked = generator_blocked | frozenset(_assigned_names(generator.target))
            generators.append(
                ast.comprehension(
                    target=generator.target,
                    iter=iterator,
                    ifs=[
                        _snapshot_bound_expression(
                            condition,
                            definitions,
                            seen=seen,
                            blocked=generator_blocked,
                        )
                        for condition in generator.ifs
                    ],
                    is_async=generator.is_async,
                )
            )
        if isinstance(node, ast.DictComp):
            replacement: ast.expr = ast.DictComp(
                key=_snapshot_bound_expression(
                    node.key,
                    definitions,
                    seen=seen,
                    blocked=generator_blocked,
                ),
                value=_snapshot_bound_expression(
                    node.value,
                    definitions,
                    seen=seen,
                    blocked=generator_blocked,
                ),
                generators=generators,
            )
        else:
            element = _snapshot_bound_expression(
                node.elt,
                definitions,
                seen=seen,
                blocked=generator_blocked,
            )
            if isinstance(node, ast.ListComp):
                replacement = ast.ListComp(elt=element, generators=generators)
            else:
                replacement = ast.SetComp(elt=element, generators=generators)
        return ast.copy_location(replacement, node)
    return node


def _exact_definition_import(
    node: ast.AST,
    module: str,
    symbol: str | None,
    definitions: dict[str, tuple[ast.AST, ...]],
) -> bool:
    if not isinstance(node, ast.Name):
        return False
    candidates = definitions.get(node.id, ())
    return (
        len(candidates) == 1
        and isinstance(candidates[0], _ImportBinding)
        and candidates[0].module == module
        and candidates[0].symbol == symbol
    )


def _known_path_expression(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        candidates = definitions.get(node.id, ())
        return len(candidates) == 1 and _known_path_expression(
            candidates[0], definitions, seen=seen | {node.id}
        )
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name) and _exact_definition_import(
        node.func, "pathlib", "Path", definitions
    ):
        return True
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "Path"
        and _exact_definition_import(node.func.value, "pathlib", None, definitions)
    ):
        return True
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr
        in {
            "absolute",
            "resolve",
            "with_name",
            "with_stem",
            "with_suffix",
        }
        and _known_path_expression(node.func.value, definitions, seen=seen)
    )


def _known_hash_expression(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
) -> bool:
    return isinstance(node, ast.Call) and (
        (
            isinstance(node.func, ast.Name)
            and _exact_definition_import(node.func, "hashlib", "sha256", definitions)
        )
        or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "sha256"
            and _exact_definition_import(node.func.value, "hashlib", None, definitions)
        )
    )


def _known_builtin_container_expression(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(
        node,
        (
            ast.Dict,
            ast.DictComp,
            ast.GeneratorExp,
            ast.List,
            ast.ListComp,
            ast.Set,
            ast.SetComp,
            ast.Tuple,
        ),
    ):
        return True
    if isinstance(node, ast.Subscript):
        selected = _selected_reference_expression(node, definitions)
        return selected is not None and _known_builtin_container_expression(
            selected,
            definitions,
            seen=seen,
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return all(
            _known_builtin_container_expression(branch, definitions, seen=seen)
            for branch in branches
        )
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        candidates = tuple(
            candidate
            for candidate in definitions.get(node.id, ())
            if not isinstance(candidate, _UnknownBinding)
        )
        return bool(candidates) and all(
            _known_builtin_container_expression(candidate, definitions, seen=seen | {node.id})
            for candidate in candidates
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"dict", "frozenset", "list", "set", "tuple"}
        and node.func.id not in definitions
    )


def _known_non_aliasing_call(
    node: ast.Call,
    definitions: dict[str, tuple[ast.AST, ...]],
) -> bool:
    if _known_path_expression(node, definitions):
        return True
    if isinstance(node.func, ast.Name):
        return _exact_definition_import(
            node.func, "json", "dumps", definitions
        ) or _exact_definition_import(node.func, "hashlib", "sha256", definitions)
    if not isinstance(node.func, ast.Attribute):
        return False
    if (
        node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, (bytes, str))
    ):
        return True
    if node.func.attr == "dumps":
        return _exact_definition_import(node.func.value, "json", None, definitions)
    if node.func.attr == "sha256":
        return _exact_definition_import(node.func.value, "hashlib", None, definitions)
    if node.func.attr in {"digest", "hexdigest"}:
        return _known_hash_expression(node.func.value, definitions)
    if node.func.attr in {"as_posix", "write_bytes", "write_text"}:
        return _known_path_expression(node.func.value, definitions)
    if node.func.attr in {"absolute", "resolve", "with_name", "with_stem", "with_suffix"}:
        return _known_path_expression(node.func.value, definitions)
    return False


def _contained_possible_reference_roots(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if isinstance(node, ast.Dict):
        return {
            root
            for value in (*node.keys, *node.values)
            if value is not None
            for root in _contained_possible_reference_roots(value, definitions, seen=seen)
        }
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return {
            root
            for value in node.elts
            for root in _contained_possible_reference_roots(value, definitions, seen=seen)
        }
    if isinstance(node, ast.Starred):
        return _contained_possible_reference_roots(node.value, definitions, seen=seen)
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return _contained_possible_reference_roots(node.elt, definitions, seen=seen) | {
            root
            for generator in node.generators
            for root in _contained_possible_reference_roots(generator.iter, definitions, seen=seen)
        }
    if isinstance(node, ast.DictComp):
        return (
            _contained_possible_reference_roots(node.key, definitions, seen=seen)
            | _contained_possible_reference_roots(node.value, definitions, seen=seen)
            | {
                root
                for generator in node.generators
                for root in _contained_possible_reference_roots(
                    generator.iter, definitions, seen=seen
                )
            }
        )
    return _possible_returned_reference_roots(node, definitions, seen=seen)


def _constructor_nested_reference_roots(
    node: ast.Call,
    definitions: dict[str, tuple[ast.AST, ...]],
    *,
    seen: frozenset[str],
) -> set[str]:
    roots = {
        root
        for keyword in node.keywords
        for root in _possible_returned_reference_roots(keyword.value, definitions, seen=seen)
    }
    for argument in node.args:
        candidate: ast.AST = argument
        if isinstance(candidate, ast.Name):
            if candidate.id in seen:
                continue
            values = definitions.get(candidate.id, ())
            if len(values) != 1:
                continue
            candidate = values[0]
            nested_seen = seen | {argument.id}
        else:
            nested_seen = seen
        if isinstance(candidate, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
            roots.update(
                _contained_possible_reference_roots(candidate, definitions, seen=nested_seen)
            )
        elif (
            isinstance(candidate, ast.Call)
            and isinstance(candidate.func, ast.Name)
            and candidate.func.id
            in {
                "dict",
                "enumerate",
                "filter",
                "frozenset",
                "iter",
                "list",
                "map",
                "reversed",
                "set",
                "sorted",
                "tuple",
                "zip",
            }
        ):
            roots.update(_reachable_assignment_roots(candidate, definitions))
        elif isinstance(candidate, (ast.DictComp, ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            roots.update(
                _contained_possible_reference_roots(candidate, definitions, seen=nested_seen)
            )
    return roots


def _possible_returned_reference_roots(
    node: ast.AST,
    definitions: dict[str, tuple[ast.AST, ...]] | None = None,
    *,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    definitions = definitions or {}
    if isinstance(node, (ast.Attribute, ast.Name)):
        root_name = _target_root_name(node)
        return {root_name} if root_name is not None else set()
    if isinstance(node, ast.Subscript):
        roots: set[str] = set()
        root_name = _target_root_name(node)
        if root_name is not None:
            roots.add(root_name)
        selected = _selected_reference_expression(node, definitions)
        if selected is not None:
            roots.update(_possible_returned_reference_roots(selected, definitions, seen=seen))
        elif root_name is None:
            roots.update(_possible_returned_reference_roots(node.value, definitions, seen=seen))
        return roots
    if isinstance(node, ast.Starred):
        return _possible_returned_reference_roots(node.value, definitions, seen=seen)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {
            "dict",
            "frozenset",
            "list",
            "set",
            "tuple",
        }:
            return _constructor_nested_reference_roots(node, definitions, seen=seen)
        if _known_non_aliasing_call(node, definitions):
            return set()
        roots = {
            root_name
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
            for root_name in _contained_possible_reference_roots(argument, definitions, seen=seen)
        }
        if isinstance(node.func, ast.Attribute):
            receiver = _target_root_name(node.func.value)
            if receiver is not None:
                roots.add(receiver)
                if receiver not in seen:
                    for candidate in definitions.get(receiver, ()):
                        roots.update(
                            _contained_possible_reference_roots(
                                candidate, definitions, seen=seen | {receiver}
                            )
                        )
        return roots
    if isinstance(node, ast.IfExp):
        return _possible_returned_reference_roots(
            node.body, definitions, seen=seen
        ) | _possible_returned_reference_roots(node.orelse, definitions, seen=seen)
    if isinstance(node, ast.BoolOp):
        return {
            root
            for value in node.values
            for root in _possible_returned_reference_roots(value, definitions, seen=seen)
        }
    if isinstance(node, ast.BinOp):
        return _possible_returned_reference_roots(
            node.left, definitions, seen=seen
        ) | _possible_returned_reference_roots(node.right, definitions, seen=seen)
    if isinstance(node, ast.NamedExpr):
        return _possible_returned_reference_roots(node.value, definitions, seen=seen)
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return set()
    return set()


def _assignment_alias_graph(nodes: tuple[ast.AST, ...]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    mutated_names: set[str] = set()
    definitions: dict[str, list[ast.AST]] = {}

    def define(target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            definitions.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Starred):
            define(target.value, value)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for index, child in enumerate(target.elts):
                define(child, ast.Subscript(value=value, slice=ast.Constant(index)))

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                define(target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            define(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            define(node.target, node.value)

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            mutated_names.update(
                root_name
                for target in targets
                if not isinstance(target, ast.Name)
                for root_name in (_target_root_name(target),)
                if root_name is not None
            )
        elif isinstance(node, ast.Delete):
            mutated_names.update(
                root_name
                for target in node.targets
                for root_name in (_target_root_name(target),)
                if root_name is not None
            )
        elif isinstance(node, ast.Call):
            root_name = _mutating_call_root(node)
            if root_name is not None:
                mutated_names.add(root_name)

    frozen_definitions = {name: tuple(values) for name, values in definitions.items()}

    def connect(target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Starred):
            connect(target.value, value)
            return
        if isinstance(target, ast.Name):
            direct_source = _target_root_name(value)
            sources = (
                _possible_returned_reference_roots(value, frozen_definitions)
                if direct_source is not None
                else (
                    _possible_returned_reference_roots(value, frozen_definitions)
                    if target.id in mutated_names
                    else set()
                )
            )
            for source in sources - {target.id}:
                graph.setdefault(target.id, set()).add(source)
                graph.setdefault(source, set()).add(target.id)
            return
        if isinstance(target, (ast.List, ast.Tuple)):
            elements = (
                tuple(value.elts)
                if isinstance(value, (ast.List, ast.Tuple)) and len(target.elts) == len(value.elts)
                else tuple(
                    ast.Subscript(value=value, slice=ast.Constant(index))
                    for index in range(len(target.elts))
                )
            )
            for child, element in zip(target.elts, elements, strict=True):
                connect(child, element)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                connect(target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            connect(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            connect(node.target, node.value)
    return graph


def _alias_component(name: str, graph: dict[str, set[str]]) -> set[str]:
    component: set[str] = set()
    pending = [name]
    while pending:
        candidate = pending.pop()
        if candidate in component:
            continue
        component.add(candidate)
        pending.extend(graph.get(candidate, ()))
    return component


def _current_alias_component(name: str, assignments: AssignmentMap) -> set[str]:
    graph: dict[str, set[str]] = {}
    definitions = {
        local_name: tuple(candidate for candidate in candidates if isinstance(candidate, ast.AST))
        for local_name, candidates in assignments.items()
    }
    for local_name, candidates in assignments.items():
        if len(candidates) != 1:
            continue
        for source in _possible_returned_reference_roots(candidates[0], definitions) - {local_name}:
            graph.setdefault(local_name, set()).add(source)
            graph.setdefault(source, set()).add(local_name)
    return _alias_component(name, graph)


def _mutating_call_root(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in MUTATING_CONTAINER_METHODS:
        return None
    return _target_root_name(node.func.value)


def _loaded_root_names(node: ast.AST) -> set[str]:
    return {
        candidate.id
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Name) and isinstance(candidate.ctx, ast.Load)
    }


def _contained_reference_roots(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.Attribute, ast.Name, ast.Subscript)):
        root_name = _target_root_name(node)
        return {root_name} if root_name is not None else set()
    if isinstance(node, ast.Starred):
        return _contained_reference_roots(node.value)
    if isinstance(node, ast.Dict):
        return {
            root_name
            for value in (*node.keys, *node.values)
            if value is not None
            for root_name in _contained_reference_roots(value)
        }
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return {root_name for value in node.elts for root_name in _contained_reference_roots(value)}
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return _contained_reference_roots(node.elt) | {
            root_name
            for generator in node.generators
            for root_name in _contained_reference_roots(generator.iter)
        }
    if isinstance(node, ast.DictComp):
        return (
            _contained_reference_roots(node.key)
            | _contained_reference_roots(node.value)
            | {
                root_name
                for generator in node.generators
                for root_name in _contained_reference_roots(generator.iter)
            }
        )
    if isinstance(node, ast.Call):
        return {
            root_name
            for value in (*node.args, *(keyword.value for keyword in node.keywords))
            for root_name in _contained_reference_roots(value)
        }
    if isinstance(node, ast.IfExp):
        return _contained_reference_roots(node.body) | _contained_reference_roots(node.orelse)
    if isinstance(node, ast.BoolOp):
        return {
            root_name for value in node.values for root_name in _contained_reference_roots(value)
        }
    return set()


def _reachable_assignment_roots(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    follow_identity: bool = False,
) -> set[str]:
    available = set(assignments)
    identity_roots: dict[int, set[str]] = {}
    if follow_identity:
        for name, candidates in assignments.items():
            for candidate in candidates:
                if not isinstance(candidate, _UnknownBinding):
                    identity_roots.setdefault(id(candidate), set()).add(name)
    roots = (_loaded_root_names(node) & available) | (
        {_target_root_name(node)} if _target_root_name(node) is not None else set()
    )
    if follow_identity:
        roots.update(
            linked_root
            for nested_candidate in ast.walk(node)
            for linked_root in identity_roots.get(id(nested_candidate), ())
        )
    pending = list(roots)
    while pending:
        root = pending.pop()
        for candidate in assignments.get(root, ()):
            if not isinstance(candidate, ast.AST):
                continue
            nested_roots = _contained_reference_roots(candidate) & available
            if follow_identity:
                nested_roots.update(
                    linked_root
                    for nested_candidate in ast.walk(candidate)
                    for linked_root in identity_roots.get(id(nested_candidate), ())
                )
            for nested in nested_roots:
                if nested not in roots:
                    roots.add(nested)
                    pending.append(nested)
    return {root for root in roots if root is not None}


def _retained_generator_assignment_roots(name: str, assignments: AssignmentMap) -> set[str]:
    retained_identities = {
        id(candidate)
        for candidate in assignments.get(name, ())
        if not isinstance(candidate, _UnknownBinding)
    }
    if not retained_identities:
        return set()
    return {
        retained_name
        for retained_name, candidates in assignments.items()
        if any(
            id(nested_candidate) in retained_identities
            for candidate in candidates
            if isinstance(candidate, ast.GeneratorExp)
            for nested_candidate in ast.walk(candidate)
        )
    }


def _with_retained_generator_roots(names: set[str], assignments: AssignmentMap) -> set[str]:
    affected = set(names)
    pending = list(names)
    while pending:
        for retained in _retained_generator_assignment_roots(pending.pop(), assignments):
            if retained not in affected:
                affected.add(retained)
                pending.append(retained)
    return affected


def _unbound_mutation_argument_root(
    node: ast.Call,
    assignments: AssignmentMap | None = None,
    qualified_assignments: dict[str, AssignmentMap] | None = None,
) -> str | None:
    syntactic_attribute_mutator = isinstance(node.func, ast.Name) and node.func.id in {
        "delattr",
        "setattr",
    }
    exact_attribute_mutator = assignments is not None and any(
        _exact_builtin_assignment_accessor(
            node.func,
            accessor,
            assignments,
            qualified_assignments or {},
        )
        for accessor in ("delattr", "setattr")
    )
    if node.args and (
        exact_attribute_mutator or (assignments is None and syntactic_attribute_mutator)
    ):
        return _target_root_name(node.args[0])
    if (
        not isinstance(node.func, ast.Attribute)
        or not isinstance(node.func.value, ast.Name)
        or node.func.attr not in MUTATING_CONTAINER_METHODS
        or not node.args
        or (
            node.func.value.id not in {"dict", "list", "set"}
            and node.func.attr not in {"delitem", "setitem"}
        )
    ):
        return None
    return _target_root_name(node.args[0])


def _qualified_call_argument_roots(
    node: ast.Call,
    definitions: dict[str, tuple[ast.AST, ...]] | None = None,
) -> set[str]:
    if not isinstance(node.func, ast.Attribute):
        return set()
    definitions = definitions or {}
    if _known_non_aliasing_call(node, definitions):
        return set()
    if node.func.attr in QUALIFIED_ARGUMENT_MUTATORS:
        values = (*node.args, *(keyword.value for keyword in node.keywords))
        values = values[:1]
    else:
        values = (*node.args, *(keyword.value for keyword in node.keywords))
    return {
        root for value in values for root in _contained_possible_reference_roots(value, definitions)
    }


def _callback_dispatcher(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[str | None, ast.expr | None, bool]:
    builtin_dispatchers = {"filter", "iter", "map", "max", "min", "sorted"}
    module_dispatchers = {
        "bisect": {
            "bisect",
            "bisect_left",
            "bisect_right",
            "insort",
            "insort_left",
            "insort_right",
        },
        "functools": {"reduce"},
        "heapq": {"merge", "nlargest", "nsmallest"},
        "itertools": {
            "accumulate",
            "dropwhile",
            "filterfalse",
            "groupby",
            "starmap",
            "takewhile",
        },
    }

    def trusted_import(binding: _ImportBinding) -> bool:
        if binding.module == "builtins":
            return binding.symbol in builtin_dispatchers
        return binding.symbol in module_dispatchers.get(binding.module, set())

    def imported_module(candidate: ast.AST, nested_seen: frozenset[str]) -> str | None:
        if not isinstance(candidate, ast.Name) or candidate.id in nested_seen:
            return None
        values = assignments.get(candidate.id, ())
        if len(values) != 1:
            return None
        value = values[0]
        if isinstance(value, _ImportBinding) and value.symbol is None:
            return value.module
        if isinstance(value, ast.Name):
            return imported_module(value, nested_seen | {candidate.id})
        return None

    if isinstance(node, ast.Name):
        if node.id in seen:
            return node.id, None, False
        candidates = assignments.get(node.id, ())
        if len(candidates) == 1:
            candidate = candidates[0]
            if isinstance(candidate, _ImportBinding):
                return (
                    candidate.symbol or candidate.module.rsplit(".", 1)[-1],
                    None,
                    trusted_import(candidate),
                )
            if isinstance(candidate, (ast.Attribute, ast.Name, ast.Subscript)):
                return _callback_dispatcher(
                    candidate,
                    assignments,
                    seen=seen | {node.id},
                )
            if isinstance(candidate, ast.Call):
                for value in (*candidate.args, *(item.value for item in candidate.keywords)):
                    resolved, receiver, resolved_trusted = _callback_dispatcher(
                        value,
                        assignments,
                        seen=seen | {node.id},
                    )
                    if resolved_trusted:
                        return resolved, receiver, False
        return node.id, None, not candidates and node.id in builtin_dispatchers
    if isinstance(node, ast.Attribute):
        module = imported_module(node.value, seen)
        trusted = (
            (node.attr == "sort" and _known_list_expression(node.value, assignments))
            or (module == "builtins" and node.attr in builtin_dispatchers)
            or node.attr in module_dispatchers.get(module or "", set())
        )
        return node.attr, node.value, trusted
    if isinstance(node, ast.Subscript):
        selected = _selected_reference_expression(node, assignments)
        if selected is not None:
            return _callback_dispatcher(selected, assignments, seen=seen)
    if isinstance(node, ast.Call):
        for value in (*node.args, *(item.value for item in node.keywords)):
            resolved, receiver, trusted = _callback_dispatcher(value, assignments, seen=seen)
            if trusted:
                return resolved, receiver, False
    return _terminal_name(node), None, False


def _known_list_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, (ast.List, ast.ListComp)):
        return True
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        candidates = assignments.get(node.id, ())
        return bool(candidates) and all(
            _known_list_expression(candidate, assignments, seen=seen | {node.id})
            for candidate in candidates
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "list"
        and node.func.id not in assignments
    )


def _known_protocol_inert_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        candidates = assignments.get(node.id, ())
        return bool(candidates) and all(
            _known_protocol_inert_expression(candidate, assignments, seen=seen | {node.id})
            for candidate in candidates
        )
    if isinstance(node, ast.Dict):
        values = (*node.keys, *node.values)
        return all(
            value is None or _known_protocol_inert_expression(value, assignments, seen=seen)
            for value in values
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(
            _known_protocol_inert_expression(value, assignments, seen=seen) for value in node.elts
        )
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.IfExp, ast.UnaryOp)):
        return all(
            _known_protocol_inert_expression(child, assignments, seen=seen)
            for child in ast.iter_child_nodes(node)
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "items"
        and not node.args
        and not node.keywords
    ):
        return _known_literal_mapping_keys(node.func.value, assignments, seen=seen)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        in {
            "bool",
            "bytes",
            "complex",
            "dict",
            "float",
            "frozenset",
            "int",
            "list",
            "range",
            "set",
            "str",
            "tuple",
        }
        and node.func.id not in assignments
        and all(
            _known_protocol_inert_expression(value, assignments, seen=seen)
            for value in (*node.args, *(keyword.value for keyword in node.keywords))
        )
    )


def _known_literal_mapping_keys(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(node, ast.Dict):
        keys = [key.value for key in node.keys if isinstance(key, ast.Constant)]
        return len(keys) == len(node.keys) == len(set(keys)) and all(
            isinstance(key, (bytes, float, int, str)) for key in keys
        )
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        candidates = assignments.get(node.id, ())
        return bool(candidates) and all(
            _known_literal_mapping_keys(candidate, assignments, seen=seen | {node.id})
            for candidate in candidates
        )
    return False


def _imported_module_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    if isinstance(node, _ImportBinding) and node.symbol is None:
        return node.module
    if not isinstance(node, ast.Name) or node.id in seen:
        return None
    candidates = assignments.get(node.id, ())
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if isinstance(candidate, _ImportBinding) and candidate.symbol is None:
        return candidate.module
    if isinstance(candidate, ast.Name):
        return _imported_module_expression(
            candidate,
            assignments,
            seen=seen | {node.id},
        )
    return None


def _may_reference_mutable_literal(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    functions: dict[str, FunctionNode] | None = None,
    function_assignments: dict[str, AssignmentMap] | None = None,
    function_scopes: dict[int, tuple[dict[str, FunctionNode], AssignmentMap]] | None = None,
    qualified_functions: dict[tuple[str, str], FunctionNode] | None = None,
    seen: frozenset[str] = frozenset(),
    seen_functions: frozenset[str] = frozenset(),
) -> bool:
    functions = functions or {}
    function_assignments = function_assignments or {}
    function_scopes = function_scopes or {}
    qualified_functions = qualified_functions or {}
    if isinstance(node, (ast.Dict, ast.List, ast.Set)):
        return True
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        return any(
            _may_reference_mutable_literal(
                candidate,
                assignments,
                functions=functions,
                function_assignments=function_assignments,
                function_scopes=function_scopes,
                qualified_functions=qualified_functions,
                seen=seen | {node.id},
                seen_functions=seen_functions,
            )
            for candidate in assignments.get(node.id, ())
        )
    if isinstance(node, ast.Subscript):
        selected = _selected_reference_expression(node, assignments)
        return _may_reference_mutable_literal(
            selected if selected is not None else node.value,
            assignments,
            functions=functions,
            function_assignments=function_assignments,
            function_scopes=function_scopes,
            qualified_functions=qualified_functions,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, (ast.BinOp, ast.BoolOp, ast.IfExp, ast.Tuple)):
        return any(
            _may_reference_mutable_literal(
                child,
                assignments,
                functions=functions,
                function_assignments=function_assignments,
                function_scopes=function_scopes,
                qualified_functions=qualified_functions,
                seen=seen,
                seen_functions=seen_functions,
            )
            for child in ast.iter_child_nodes(node)
        )
    if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
        function_name = _terminal_name(node.func) or ""
        function = functions.get(function_name) if isinstance(node.func, ast.Name) else None
        if isinstance(node.func, ast.Attribute):
            imported_module = _imported_module_expression(node.func.value, assignments)
            if imported_module is not None:
                function = qualified_functions.get((imported_module, node.func.attr))
                function_name = f"{imported_module}:{node.func.attr}"
        if function is None:
            candidates = assignments.get(function_name, ())
            if len(candidates) == 1 and isinstance(candidates[0], ast.Name):
                function_name = candidates[0].id
                function = functions.get(function_name)
        if function is not None and function_name not in seen_functions:
            scoped_functions, defining_assignments = function_scopes.get(
                id(function),
                (functions, function_assignments.get(function_name, assignments)),
            )
            return any(
                _may_reference_mutable_literal(
                    value,
                    defining_assignments,
                    functions=scoped_functions,
                    function_assignments={name: defining_assignments for name in scoped_functions},
                    function_scopes=function_scopes,
                    qualified_functions=qualified_functions,
                    seen=seen,
                    seen_functions=seen_functions | {function_name},
                )
                for value in _return_values(
                    function,
                    source=f"protocol helper {function_name}",
                )
            )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"dict", "list", "set"}
        and node.func.id not in assignments
    )


def _callback_value_provenance(
    provenance: _Provenance[ast.AST],
) -> _Provenance[ast.expr]:
    values = frozenset(
        value
        for value in provenance.values
        if isinstance(value, ast.expr)
        and not (isinstance(value, ast.Constant) and value.value is None)
    )
    unresolved = provenance.state is _ProvenanceState.UNRESOLVED or any(
        not isinstance(value, ast.expr) for value in provenance.values
    )
    return _unresolved_provenance(values) if unresolved else _known_provenance(values)


def _callback_keyword_provenance(
    node: ast.Call,
    name: str,
    assignments: AssignmentMap,
    *,
    select_mapping: Callable[[ast.expr, str], _Provenance[ast.AST]] | None = None,
) -> _Provenance[ast.expr]:
    results: list[_Provenance[ast.AST]] = [
        _known_provenance((keyword.value,)) for keyword in node.keywords if keyword.arg == name
    ]
    for keyword in node.keywords:
        if keyword.arg is not None:
            continue
        if select_mapping is None:
            selected = _selected_reference_provenance(
                ast.Subscript(
                    value=keyword.value,
                    slice=ast.Constant(name),
                    ctx=ast.Load(),
                ),
                assignments,
            )
        else:
            selected = select_mapping(keyword.value, name)
        results.append(selected)
    return _callback_value_provenance(_merge_provenance(results))


def _qualified_callback_keyword_provenance(
    node: ast.Call,
    name: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
) -> _Provenance[ast.expr]:
    def select_mapping(mapping: ast.expr, key: str) -> _Provenance[ast.AST]:
        return _qualified_selected_reference_expressions(
            ast.Subscript(
                value=mapping,
                slice=ast.Constant(key),
                ctx=ast.Load(),
            ),
            assignments,
            qualified_assignments,
        )

    return _callback_keyword_provenance(
        node,
        name,
        assignments,
        select_mapping=select_mapping,
    )


def _executed_callback(
    node: ast.Call,
    assignments: AssignmentMap,
    *,
    resolve_keyword: Callable[
        [ast.Call, str, AssignmentMap], _Provenance[ast.expr]
    ] = _callback_keyword_provenance,
) -> tuple[_Provenance[ast.expr], tuple[ast.expr, ...], int, bool]:
    dispatcher, receiver, trusted = _callback_dispatcher(node.func, assignments)
    if not trusted:
        callback = _merge_provenance(
            (
                resolve_keyword(node, "key", assignments),
                resolve_keyword(node, "func", assignments),
            )
        )
        if (
            callback.state is _ProvenanceState.IRRELEVANT
            and dispatcher
            in {
                "dropwhile",
                "filter",
                "filterfalse",
                "map",
                "reduce",
                "starmap",
                "takewhile",
            }
            and node.args
        ):
            callback = _callback_value_provenance(_known_provenance((node.args[0],)))
        if (
            callback.state is _ProvenanceState.IRRELEVANT
            and dispatcher in {"accumulate", "groupby"}
            and len(node.args) >= 2
        ):
            callback = _callback_value_provenance(_known_provenance((node.args[1],)))
        if (
            callback.state is _ProvenanceState.IRRELEVANT
            and dispatcher == "iter"
            and len(node.args) == 2
        ):
            callback = _callback_value_provenance(_known_provenance((node.args[0],)))
        inputs = (*((receiver,) if receiver is not None else ()), *node.args)
        implicit_protocol = dispatcher in {
            "accumulate",
            "bisect",
            "bisect_left",
            "bisect_right",
            "groupby",
            "insort",
            "insort_left",
            "insort_right",
            "iter",
            "max",
            "merge",
            "min",
            "nlargest",
            "nsmallest",
            "sort",
            "sorted",
        }
        return (
            callback,
            inputs,
            0,
            callback.state is not _ProvenanceState.IRRELEVANT or implicit_protocol,
        )
    if dispatcher in {"filter", "map"} and len(node.args) >= 2:
        callback = _callback_value_provenance(_known_provenance((node.args[0],)))
        return (
            callback,
            tuple(node.args[1:]),
            len(node.args) - 1 if dispatcher == "map" else 1,
            dispatcher == "filter" and isinstance(node.args[0], ast.Constant),
        )
    if dispatcher == "sorted" and node.args:
        return resolve_keyword(node, "key", assignments), (node.args[0],), 1, True
    if dispatcher in {"max", "min"} and node.args:
        inputs = (node.args[0],) if len(node.args) == 1 else tuple(node.args)
        return resolve_keyword(node, "key", assignments), inputs, 1, True
    if dispatcher == "sort":
        return (
            resolve_keyword(node, "key", assignments),
            ((receiver,) if receiver is not None else ()),
            1,
            True,
        )
    if dispatcher == "iter" and len(node.args) == 2:
        return (
            _callback_value_provenance(_known_provenance((node.args[0],))),
            tuple(node.args),
            0,
            True,
        )
    if dispatcher == "reduce" and len(node.args) >= 2:
        inputs = (node.args[1], *node.args[2:3])
        return _callback_value_provenance(_known_provenance((node.args[0],))), inputs, 2, False
    if dispatcher in {"groupby", "accumulate"} and node.args:
        callback = (
            _callback_value_provenance(_known_provenance((node.args[1],)))
            if len(node.args) >= 2
            else resolve_keyword(
                node,
                "key" if dispatcher == "groupby" else "func",
                assignments,
            )
        )
        inputs = (node.args[0],)
        initial = resolve_keyword(node, "initial", assignments)
        if dispatcher == "accumulate" and initial.values:
            inputs = (*inputs, *initial.values)
        return callback, inputs, 1 if dispatcher == "groupby" else 2, True
    if dispatcher in {"dropwhile", "filterfalse", "takewhile"} and len(node.args) >= 2:
        return (
            _callback_value_provenance(_known_provenance((node.args[0],))),
            (node.args[1],),
            1,
            False,
        )
    if dispatcher == "starmap" and len(node.args) >= 2:
        return (
            _callback_value_provenance(_known_provenance((node.args[0],))),
            (node.args[1],),
            0,
            False,
        )
    if dispatcher == "merge" and node.args:
        return resolve_keyword(node, "key", assignments), tuple(node.args), 1, True
    if dispatcher in {"nlargest", "nsmallest"} and len(node.args) >= 2:
        return resolve_keyword(node, "key", assignments), (node.args[1],), 1, True
    if (
        dispatcher
        in {"bisect", "bisect_left", "bisect_right", "insort", "insort_left", "insort_right"}
        and node.args
    ):
        return resolve_keyword(node, "key", assignments), tuple(node.args[:2]), 1, True
    return _irrelevant_provenance(), (), 0, False


def _direct_mutation_roots(function: FunctionNode | ast.Lambda) -> set[str]:
    mutated: set[str] = set()
    for node in _lexical_nodes(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            mutated.update(
                root
                for target in targets
                if not isinstance(target, ast.Name)
                for root in (_target_root_name(target),)
                if root is not None
            )
        elif isinstance(node, ast.Delete):
            mutated.update(
                root
                for target in node.targets
                for root in (_target_root_name(target),)
                if root is not None
            )
        elif isinstance(node, ast.Call):
            mutated.update(
                root
                for root in (
                    _mutating_call_root(node),
                    _unbound_mutation_argument_root(node),
                    *_qualified_call_argument_roots(node),
                )
                if root is not None
            )
    return mutated


def _direct_mutated_parameter_names(function: FunctionNode) -> set[str]:
    parameters = set(_function_parameter_annotations(function))
    return _direct_mutation_roots(function) & parameters


def _parameter_defaults(function: FunctionNode | ast.Lambda) -> dict[str, ast.expr]:
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults = {
        parameter.arg: default
        for parameter, default in zip(
            positional[-len(arguments.defaults) :] if arguments.defaults else (),
            arguments.defaults,
            strict=True,
        )
    }
    defaults.update(
        {
            parameter.arg: default
            for parameter, default in zip(
                arguments.kwonlyargs,
                arguments.kw_defaults,
                strict=True,
            )
            if default is not None
        }
    )
    return defaults


def _default_mutation_roots(
    function: FunctionNode | ast.Lambda,
    mutated_parameters: set[str],
    supplied_positional_count: int,
    assignments: AssignmentMap,
) -> set[str]:
    positional = [*function.args.posonlyargs, *function.args.args]
    supplied = {parameter.arg for parameter in positional[:supplied_positional_count]}
    defaults = _parameter_defaults(function)
    return {
        root
        for parameter_name in mutated_parameters - supplied
        for default in (defaults.get(parameter_name),)
        if default is not None
        for root in _reachable_assignment_roots(default, assignments)
    }


def _mutated_callback_parameter_names(
    function: FunctionNode | ast.Lambda,
    inherited_assignments: AssignmentMap,
    *,
    qualified_assignments: dict[str, AssignmentMap] | None = None,
) -> set[str]:
    parameters = set(_function_parameter_annotations(function))
    assignments = _assignment_map(
        function,
        inherited_assignments,
        qualified_assignments=qualified_assignments,
    )
    return (_direct_mutation_roots(function) & parameters) | {
        name
        for name in parameters
        if any(isinstance(candidate, _UnknownBinding) for candidate in assignments.get(name, ()))
    }


def _replace_ast_identity(
    node: ast.AST,
    previous: ast.AST,
    replacement: ast.AST,
) -> ast.AST:
    if node is previous:
        return replacement
    updates: dict[str, object] = {}
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            updated = _replace_ast_identity(value, previous, replacement)
            if updated is not value:
                updates[field_name] = updated
        elif isinstance(value, list):
            updated_items = [
                _replace_ast_identity(item, previous, replacement)
                if isinstance(item, ast.AST)
                else item
                for item in value
            ]
            if any(updated is not original for updated, original in zip(updated_items, value)):
                updates[field_name] = updated_items
    if not updates:
        return node
    updated_node = copy.copy(node)
    for field_name, value in updates.items():
        setattr(updated_node, field_name, value)
    return updated_node


def _closed_mutation_expression(
    node: ast.Call,
    previous: ast.expr,
    definitions: AssignmentMap | None = None,
) -> ast.expr | None:
    definitions = {} if definitions is None else definitions
    if not isinstance(node.func, ast.Attribute):
        return None
    method = node.func.attr
    if method in {"append", "extend"}:
        if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
            return None
        added = node.args[0]
        previous_elements = _static_sequence_elements(previous, definitions)
        elements = (
            list(previous_elements)
            if previous_elements is not None
            else [ast.Starred(value=previous, ctx=ast.Load())]
        )
        added_elements = (
            _static_sequence_elements(added, definitions) if method == "extend" else None
        )
        elements.extend(
            added_elements
            if added_elements is not None
            else [ast.Starred(value=added, ctx=ast.Load())]
            if method == "extend"
            else [added]
        )
        return ast.List(
            elts=elements,
            ctx=ast.Load(),
        )
    if method != "update" or len(node.args) > 1:
        return None
    if any(isinstance(argument, ast.Starred) for argument in node.args) or any(
        keyword.arg is None for keyword in node.keywords
    ):
        return None
    previous_entries = _static_mapping_entries(previous, definitions)
    keys: list[ast.expr | None] = (
        [key for key, _value in previous_entries] if previous_entries is not None else [None]
    )
    values: list[ast.expr] = (
        [value for _key, value in previous_entries] if previous_entries is not None else [previous]
    )
    if node.args:
        added_entries = _static_mapping_entries(node.args[0], definitions)
        if added_entries is None:
            keys.append(None)
            values.append(node.args[0])
        else:
            keys.extend(key for key, _value in added_entries)
            values.extend(value for _key, value in added_entries)
    for keyword in node.keywords:
        if keyword.arg is None:
            return None
        keys.append(ast.Constant(keyword.arg))
        values.append(keyword.value)
    return ast.Dict(keys=keys, values=values)


def _assignment_map(
    scope: ast.AST,
    inherited_assignments: AssignmentMap | None = None,
    *,
    qualified_assignments: dict[str, AssignmentMap] | None = None,
    deferred_callable_ids: frozenset[int] = frozenset(),
) -> AssignmentMap:
    nodes = tuple(_lexical_nodes(scope))
    alias_graph = _assignment_alias_graph(nodes)
    nested_functions = {
        node.name: node
        for node in nodes
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    callable_parameters = (
        set(_function_parameter_annotations(scope))
        if isinstance(scope, (ast.AsyncFunctionDef, ast.FunctionDef))
        else set()
    )
    grouped: dict[str, list[ast.AST]] = {}

    def record_unknown_name(name: str) -> None:
        for alias in _alias_component(name, alias_graph):
            grouped.setdefault(alias, []).append(_UnknownBinding())

    def record_unknown_with_contents(name: str) -> None:
        current: AssignmentMap = {
            **(inherited_assignments or {}),
            **{local_name: tuple(values) for local_name, values in grouped.items()},
        }
        reachable = _reachable_assignment_roots(
            ast.Name(id=name, ctx=ast.Load()),
            current,
            follow_identity=True,
        ) | {name}
        for reachable in _with_retained_generator_roots(reachable, current):
            record_unknown_name(reachable)

    def record_unknown_with_retained(name: str) -> None:
        current: AssignmentMap = {
            **(inherited_assignments or {}),
            **{local_name: tuple(values) for local_name, values in grouped.items()},
        }
        for affected in _with_retained_generator_roots({name}, current):
            record_unknown_name(affected)

    def record_all_current_with_contents() -> None:
        inherited_objects = {
            name
            for name, candidates in (inherited_assignments or {}).items()
            if any(isinstance(candidate, ast.expr) for candidate in candidates)
        }
        for name in inherited_objects | set(grouped) | callable_parameters:
            record_unknown_with_contents(name)

    def resolve_nested_callback(
        name: str, *, seen: frozenset[str] = frozenset()
    ) -> FunctionNode | None:
        if name in seen:
            return None
        nested = nested_functions.get(name)
        if nested is not None:
            return nested
        for candidate in grouped.get(name, ()):
            if isinstance(candidate, ast.Name):
                resolved = resolve_nested_callback(candidate.id, seen=seen | {name})
                if resolved is not None:
                    return resolved
        return None

    def resolved_callback_mutated_parameters(
        function: FunctionNode | ast.Lambda,
        current: AssignmentMap,
        *,
        seen: frozenset[int] = frozenset(),
    ) -> set[str]:
        marker = id(function)
        if marker in seen:
            return set()
        parameters = set(_function_parameter_annotations(function))
        mutated = _mutated_callback_parameter_names(
            function,
            current,
            qualified_assignments=qualified_assignments,
        )
        for callback_call in _lexical_nodes(function):
            if not isinstance(callback_call, ast.Call) or not isinstance(
                callback_call.func, ast.Name
            ):
                continue
            delegated = resolve_nested_callback(callback_call.func.id)
            if delegated is None:
                continue
            bound = _bound_function_call_arguments(callback_call, delegated)
            if bound is None:
                continue
            delegated_mutated = resolved_callback_mutated_parameters(
                delegated,
                current,
                seen=seen | {marker},
            )
            for parameter_name in delegated_mutated:
                actual = bound.get(parameter_name)
                if actual is not None:
                    mutated.update(_loaded_root_names(actual[0]) & parameters)
        return mutated

    def record_callback_mutations(node: ast.Call) -> None:
        current: AssignmentMap = {
            **(inherited_assignments or {}),
            **{name: tuple(values) for name, values in grouped.items()},
        }

        def resolve_keyword(
            call: ast.Call,
            name: str,
            state: AssignmentMap,
        ) -> _Provenance[ast.expr]:
            if qualified_assignments is None:
                return _callback_keyword_provenance(call, name, state)
            return _qualified_callback_keyword_provenance(
                call,
                name,
                state,
                qualified_assignments,
            )

        callback_provenance, iterables, supplied_positional_count, executes_protocol = (
            _executed_callback(
                node,
                current,
                resolve_keyword=resolve_keyword,
            )
        )
        if callback_provenance.state is _ProvenanceState.UNRESOLVED:
            record_all_current_with_contents()
        if callback_provenance.state is _ProvenanceState.IRRELEVANT:
            inferred_callback = next(
                (
                    argument
                    for argument in node.args
                    if isinstance(argument, ast.Lambda)
                    or (
                        isinstance(argument, ast.Name)
                        and resolve_nested_callback(argument.id) is not None
                    )
                ),
                None,
            )
            if inferred_callback is not None:
                callback_provenance = _known_provenance((inferred_callback,))
                iterables = tuple(
                    argument for argument in node.args if argument is not inferred_callback
                )
                supplied_positional_count = 0
                executes_protocol = True
        callbacks = tuple(callback_provenance.values)
        protocol_values = iterables
        if executes_protocol and any(
            not _known_protocol_inert_expression(value, current) for value in protocol_values
        ):
            for name, candidates in tuple(current.items()):
                if any(
                    _may_reference_mutable_literal(
                        candidate,
                        current,
                        functions=nested_functions,
                    )
                    for candidate in candidates
                ):
                    record_unknown_with_contents(name)
            for value in protocol_values:
                for root in _reachable_assignment_roots(value, current):
                    record_unknown_with_contents(root)
        if not callbacks:
            return
        if len(callbacks) != 1:
            record_all_current_with_contents()
            return
        callback = callbacks[0]
        mutates_inputs = True
        if isinstance(callback, ast.Lambda):
            parameters = set(_function_parameter_annotations(callback))
            mutation_roots = _direct_mutation_roots(callback)
            for captured_root in mutation_roots - parameters:
                record_unknown_with_contents(captured_root)
            for callback_call in _lexical_nodes(callback):
                if not isinstance(callback_call, ast.Call) or not isinstance(
                    callback_call.func, ast.Name
                ):
                    continue
                delegated = resolve_nested_callback(callback_call.func.id)
                if delegated is None:
                    continue
                delegated_inherited = {
                    **(inherited_assignments or {}),
                    **{name: tuple(values) for name, values in grouped.items()},
                }
                for captured_root in _mutated_free_bindings(
                    delegated,
                    delegated_inherited,
                    qualified_assignments=qualified_assignments,
                ):
                    record_unknown_with_contents(captured_root)
                bound = _bound_function_call_arguments(callback_call, delegated)
                if bound is not None:
                    for parameter_name in resolved_callback_mutated_parameters(delegated, current):
                        actual = bound.get(parameter_name)
                        if actual is None:
                            continue
                        for root in _reachable_assignment_roots(actual[0], current):
                            record_unknown_with_contents(root)
            mutated_parameters = resolved_callback_mutated_parameters(callback, current)
            for root in _default_mutation_roots(
                callback,
                mutated_parameters,
                supplied_positional_count,
                current,
            ):
                record_unknown_with_contents(root)
            mutates_inputs = bool(mutated_parameters)
        elif (
            isinstance(callback, ast.Name)
            and (nested := resolve_nested_callback(callback.id)) is not None
        ):
            nested_inherited = {
                **(inherited_assignments or {}),
                **{name: tuple(values) for name, values in grouped.items()},
            }
            for captured_root in _mutated_free_bindings(
                nested,
                nested_inherited,
                qualified_assignments=qualified_assignments,
            ):
                record_unknown_with_contents(captured_root)
            mutated_parameters = resolved_callback_mutated_parameters(nested, nested_inherited)
            for root in _default_mutation_roots(
                nested,
                mutated_parameters,
                supplied_positional_count,
                nested_inherited,
            ):
                record_unknown_with_contents(root)
            mutates_inputs = bool(mutated_parameters)
        else:
            record_all_current_with_contents()
        if not mutates_inputs:
            return
        for iterable in iterables:
            for root in _reachable_assignment_roots(iterable, current):
                record_unknown_with_contents(root)

    def record_mutating_call(node: ast.Call, root_name: str) -> None:
        aliases = _alias_component(root_name, alias_graph)
        previous = grouped.get(root_name, ())
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == root_name
        ):
            record_unknown_with_contents(root_name)
            return
        if len(aliases) == 1 and len(previous) == 1 and isinstance(previous[0], ast.expr):
            current: AssignmentMap = {
                **(inherited_assignments or {}),
                **{name: tuple(values) for name, values in grouped.items()},
            }
            replacement = _closed_mutation_expression(node, previous[0], current)
            if replacement is not None:
                for name, candidates in tuple(grouped.items()):
                    grouped[name] = [
                        _replace_ast_identity(candidate, previous[0], replacement)
                        for candidate in candidates
                    ]
                return
        record_unknown_with_retained(root_name)

    def record(target: ast.AST, value: ast.expr) -> None:
        current: AssignmentMap = {
            **(inherited_assignments or {}),
            **{name: tuple(values) for name, values in grouped.items()},
        }
        value = _snapshot_bound_expression(value, current)
        if isinstance(target, ast.Name):
            grouped.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Subscript):
            root_name = _target_root_name(target)
            if root_name is not None and len(_alias_component(root_name, alias_graph)) > 1:
                record_unknown_name(root_name)
                return
            if (
                isinstance(target.value, ast.Name)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
                and target.slice.value
            ):
                previous = grouped.get(target.value.id, ())
                if len(previous) == 1 and isinstance(previous[0], ast.expr):
                    replacement = ast.Dict(
                        keys=[None, ast.Constant(target.slice.value)],
                        values=[previous[0], value],
                    )
                    for name, candidates in tuple(grouped.items()):
                        grouped[name] = [
                            _replace_ast_identity(candidate, previous[0], replacement)
                            for candidate in candidates
                        ]
                    return
            record_unknown(target)
        elif isinstance(target, (ast.Attribute, ast.Starred)):
            record_unknown(target)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for index, child in enumerate(target.elts):
                record(child, ast.Subscript(value=value, slice=ast.Constant(index)))

    def record_unknown(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            record_unknown_name(target.id)
        elif isinstance(target, ast.Starred):
            record_unknown(target.value)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            root_name = _target_root_name(target)
            if root_name is not None:
                record_unknown_with_contents(root_name)
        elif isinstance(target, (ast.List, ast.Tuple)):
            for child in target.elts:
                record_unknown(child)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target, node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            record(node.target, node.value)
        elif isinstance(node, ast.NamedExpr):
            record(node.target, node.value)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                record_unknown_with_retained(node.target.id)
            else:
                record_unknown(node.target)
        elif isinstance(node, (ast.AsyncFor, ast.For)):
            record_unknown(node.target)
        elif isinstance(node, (ast.AsyncWith, ast.With)):
            for item in node.items:
                if item.optional_vars is not None:
                    record_unknown(item.optional_vars)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                record_unknown(target)
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            grouped.setdefault(node.name, []).append(_UnknownBinding())
        elif isinstance(node, ast.MatchAs) and node.name is not None:
            grouped.setdefault(node.name, []).append(_UnknownBinding())
        elif isinstance(node, ast.MatchStar) and node.name is not None:
            grouped.setdefault(node.name, []).append(_UnknownBinding())
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            grouped.setdefault(node.rest, []).append(_UnknownBinding())
        elif isinstance(node, ast.ClassDef):
            nested_inherited = {
                **(inherited_assignments or {}),
                **{name: tuple(values) for name, values in grouped.items()},
            }
            if _class_construction_may_execute_user_code(node, nested_inherited):
                record_all_current_with_contents()
            for captured_root in _mutated_free_bindings(
                node,
                nested_inherited,
                qualified_assignments=qualified_assignments,
            ):
                record_unknown_name(captured_root)
            grouped.setdefault(node.name, []).append(_UnknownBinding())
        elif isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            grouped.setdefault(node.name, []).append(_UnknownBinding())
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                imported_name = alias.name if alias.asname else alias.name.split(".")[0]
                grouped.setdefault(local_name, []).append(_ImportBinding(module=imported_name))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    grouped.setdefault(alias.asname or alias.name, []).append(
                        _ImportBinding(module=node.module or "", symbol=alias.name)
                    )
        elif isinstance(node, ast.Call):
            record_callback_mutations(node)
            root_name = _mutating_call_root(node)
            if root_name is not None:
                record_mutating_call(node, root_name)
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATING_CONTAINER_METHODS
            ):
                for bound_name in set(grouped) | callable_parameters:
                    record_unknown_name(bound_name)
            argument_root = _unbound_mutation_argument_root(node)
            if argument_root is not None:
                record_unknown_with_contents(argument_root)
            if root_name is None and isinstance(node.func, ast.Attribute):
                definitions = {
                    name: tuple(
                        candidate for candidate in candidates if isinstance(candidate, ast.AST)
                    )
                    for name, candidates in {
                        **(inherited_assignments or {}),
                        **grouped,
                    }.items()
                }
                for qualified_root in _qualified_call_argument_roots(node, definitions):
                    record_unknown_with_contents(qualified_root)
                if (
                    not node.args
                    and not node.keywords
                    and not _known_non_aliasing_call(node, definitions)
                    and not _known_builtin_container_expression(node.func.value, definitions)
                ):
                    receiver_root = _target_root_name(node.func.value)
                    if receiver_root is not None:
                        receiver_candidates = tuple(grouped.get(receiver_root, ())) or (
                            inherited_assignments or {}
                        ).get(receiver_root, ())
                        if any(
                            isinstance(candidate, ast.Call)
                            and (
                                not candidate.args
                                and not candidate.keywords
                                or (_terminal_name(candidate.func) or "")[:1].isupper()
                            )
                            for candidate in receiver_candidates
                        ):
                            record_unknown_with_contents(receiver_root)
                            record_all_current_with_contents()
            if getattr(node, IMPLICIT_DECORATOR_CALL_ATTRIBUTE, False) and not (
                isinstance(node.func, ast.Name) and node.func.id in nested_functions
            ):
                for bound_name in set(grouped) | callable_parameters:
                    record_unknown_with_contents(bound_name)
            if isinstance(node.func, ast.Name):
                if node.func.id in {"eval", "exec"}:
                    for bound_name in set(grouped) | callable_parameters:
                        record_unknown_name(bound_name)
                nested = nested_functions.get(node.func.id)
                if nested is not None:
                    nested_inherited = {
                        **(inherited_assignments or {}),
                        **{name: tuple(values) for name, values in grouped.items()},
                    }
                    for captured_root in _mutated_free_bindings(
                        nested,
                        nested_inherited,
                        qualified_assignments=qualified_assignments,
                    ):
                        record_unknown_name(captured_root)
                    bound = _bound_function_call_arguments(node, nested)
                    if bound is not None:
                        for parameter_name in _direct_mutated_parameter_names(nested):
                            actual = bound.get(parameter_name)
                            if actual is None or actual[1]:
                                continue
                            for default_root in _loaded_root_names(actual[0]):
                                record_unknown_name(default_root)
                call_bindings = grouped.get(node.func.id, ())
                if not call_bindings:
                    inherited_call_bindings = (inherited_assignments or {}).get(node.func.id, ())
                    if any(isinstance(binding, ast.Call) for binding in inherited_call_bindings):
                        call_bindings = inherited_call_bindings
                if node.func.id in callable_parameters or call_bindings:
                    if not node.args and not node.keywords:
                        record_all_current_with_contents()
                    for argument in (
                        *node.args,
                        *(keyword.value for keyword in node.keywords),
                    ):
                        for argument_root in _loaded_root_names(argument):
                            record_unknown_name(argument_root)
                    current: AssignmentMap = {
                        **(inherited_assignments or {}),
                        **{name: tuple(values) for name, values in grouped.items()},
                    }
                    for binding in call_bindings:
                        if isinstance(binding, ast.expr):
                            for captured_root in _reachable_assignment_roots(
                                binding,
                                current,
                                follow_identity=True,
                            ):
                                record_unknown_with_contents(captured_root)
                        if (
                            isinstance(binding, ast.Attribute)
                            and binding.attr in MUTATING_CONTAINER_METHODS
                        ):
                            bound_root = _target_root_name(binding.value)
                            if bound_root is not None:
                                record_unknown_name(bound_root)
            elif not isinstance(node.func, ast.Attribute):
                current = {
                    **(inherited_assignments or {}),
                    **{name: tuple(values) for name, values in grouped.items()},
                }
                callable_provenance = (
                    _qualified_callable_provenance(
                        node.func,
                        current,
                        qualified_assignments,
                    )
                    if qualified_assignments is not None
                    else _unresolved_provenance()
                )
                if not (
                    callable_provenance.values
                    and callable_provenance.state is _ProvenanceState.KNOWN
                    and all(
                        id(called) in deferred_callable_ids
                        for called, _module, _implicit_count in callable_provenance.values
                    )
                ):
                    if not node.args and not node.keywords:
                        record_all_current_with_contents()
                    for argument in (
                        *node.args,
                        *(keyword.value for keyword in node.keywords),
                    ):
                        for argument_root in _loaded_root_names(argument):
                            record_unknown_name(argument_root)
                    for captured_root in _reachable_assignment_roots(
                        node.func,
                        current,
                        follow_identity=True,
                    ):
                        record_unknown_with_contents(captured_root)
    return {name: tuple(values) for name, values in grouped.items()}


def _mutated_free_bindings(
    scope: FunctionNode | ast.ClassDef,
    inherited_assignments: AssignmentMap | None = None,
    *,
    qualified_assignments: dict[str, AssignmentMap] | None = None,
) -> set[str]:
    if isinstance(scope, ast.ClassDef):
        assignments = _assignment_map(
            scope,
            inherited_assignments,
            qualified_assignments=qualified_assignments,
        )
        unknown = {
            name
            for name, candidates in assignments.items()
            if any(isinstance(candidate, _UnknownBinding) for candidate in candidates)
        }
        first_bind: dict[str, int] = {}
        for statement in scope.body:
            definitely_executed = isinstance(
                statement,
                (
                    ast.AnnAssign,
                    ast.Assign,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.FunctionDef,
                    ast.Import,
                    ast.ImportFrom,
                    ast.NamedExpr,
                ),
            )
            for name in _statement_bound_names(statement) if definitely_executed else ():
                first_bind.setdefault(name, statement.lineno)
        first_mutation: dict[str, int] = {}
        definitions = {
            name: tuple(candidate for candidate in candidates if isinstance(candidate, ast.AST))
            for name, candidates in {
                **(inherited_assignments or {}),
                **assignments,
            }.items()
        }
        for statement in scope.body:
            for node in (statement, *_lexical_nodes(statement)):
                roots: set[str] = set()
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                    roots.update(
                        root
                        for target in targets
                        if not isinstance(target, ast.Name)
                        for root in (_target_root_name(target),)
                        if root is not None
                    )
                elif isinstance(node, ast.Delete):
                    roots.update(
                        root
                        for target in node.targets
                        for root in (_target_root_name(target),)
                        if root is not None
                    )
                elif isinstance(node, ast.Call):
                    roots.update(
                        root
                        for root in (
                            _mutating_call_root(node),
                            _unbound_mutation_argument_root(node),
                        )
                        if root is not None
                    )
                    roots.update(_qualified_call_argument_roots(node, definitions))
                    if isinstance(node.func, ast.Name):
                        roots.update(
                            root
                            for value in (*node.args, *(kw.value for kw in node.keywords))
                            for root in _loaded_root_names(value)
                        )
                for root in roots:
                    first_mutation.setdefault(root, getattr(node, "lineno", statement.lineno))
        mutation_before_binding = {
            name
            for name, mutation_line in first_mutation.items()
            if name in assignments and (name not in first_bind or mutation_line <= first_bind[name])
        }
        unresolved = {
            name
            for name in unknown
            if name not in first_bind
            or name not in first_mutation
            or first_mutation[name] <= first_bind[name]
        }
        return mutation_before_binding | unresolved
    local_names = (
        set(_function_parameter_annotations(scope))
        if isinstance(scope, (ast.AsyncFunctionDef, ast.FunctionDef))
        else set()
    )
    for statement in scope.body:
        local_names.update(_statement_bound_names(statement))
    return {
        name
        for name, candidates in _assignment_map(
            scope,
            inherited_assignments,
            qualified_assignments=qualified_assignments,
        ).items()
        if name not in local_names
        and any(isinstance(candidate, _UnknownBinding) for candidate in candidates)
    }


def _return_values(scope: ast.AST, *, source: str) -> tuple[ast.expr, ...]:
    return_nodes = [node for node in _lexical_nodes(scope) if isinstance(node, ast.Return)]
    if not return_nodes or any(node.value is None for node in return_nodes):
        _fail(f"manifest mapping has no closed return in {source}")
    values: list[ast.expr] = []
    for node in return_nodes:
        if node.value is None:
            _fail(f"manifest mapping has no closed return in {source}")
        values.append(node.value)
    return tuple(values)


def _selected_manifest_expression(
    node: ast.Subscript, assignments: AssignmentMap
) -> tuple[ast.AST, AssignmentMap] | None:
    if not isinstance(node.value, ast.Name):
        return None
    containers = assignments.get(node.value.id, ())
    if len(containers) != 1:
        return None
    container = containers[0]
    if isinstance(container, ast.DictComp):
        return container.value, _comprehension_assignments(container.generators, assignments)
    if isinstance(container, ast.ListComp):
        return container.elt, _comprehension_assignments(container.generators, assignments)
    if isinstance(container, ast.Dict):
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, str):
            return None
        for key, value in zip(container.keys, container.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == node.slice.value:
                return value, assignments
        return None
    if isinstance(container, (ast.List, ast.Tuple)):
        if not isinstance(node.slice, ast.Constant) or not isinstance(node.slice.value, int):
            return None
        index = node.slice.value
        if -len(container.elts) <= index < len(container.elts):
            return container.elts[index], assignments
    return None


def _function_parameter_annotations(function: FunctionNode) -> dict[str, ast.AST]:
    arguments = function.args
    annotated = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        annotated.append(arguments.vararg)
    if arguments.kwarg is not None:
        annotated.append(arguments.kwarg)
    return {
        argument.arg: argument.annotation or ast.Name(id="object", ctx=ast.Load())
        for argument in annotated
    }


def _annotation_is_builtin(
    annotation: ast.AST,
    name: str,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name) and target.id == name:
        return _unshadowed_builtin(name, assignments, functions, classes, parameters)
    return (
        isinstance(target, ast.Attribute)
        and target.attr == name
        and isinstance(target.value, ast.Name)
        and _exact_imported_module(
            target.value.id,
            "builtins",
            assignments,
            functions,
            classes,
            parameters,
        )
    )


def _annotation_is_imported(
    annotation: ast.AST,
    module: str,
    symbol: str,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> bool:
    target = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(target, ast.Name) and target.id == symbol:
        return _exact_imported_symbol(
            target.id,
            module,
            symbol,
            assignments,
            functions,
            classes,
            parameters,
        )
    return (
        isinstance(target, ast.Attribute)
        and target.attr == symbol
        and isinstance(target.value, ast.Name)
        and _exact_imported_module(
            target.value.id,
            module,
            assignments,
            functions,
            classes,
            parameters,
        )
    )


def _annotation_shape(
    annotation: ast.AST | None,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> _ManifestShape:
    if annotation is None:
        return _ManifestShape.UNKNOWN
    bound_shape = getattr(annotation, ANNOTATION_SHAPE_ATTRIBUTE, None)
    if isinstance(bound_shape, _ManifestShape):
        return bound_shape
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        shapes = (
            _annotation_shape(
                branch,
                assignments,
                functions,
                classes,
                parameters,
            )
            for branch in (annotation.left, annotation.right)
        )
        return (
            _ManifestShape.LEAF
            if all(shape is _ManifestShape.LEAF for shape in shapes)
            else _ManifestShape.UNKNOWN
        )
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return _ManifestShape.LEAF
    if any(
        _annotation_is_builtin(
            annotation,
            name,
            assignments,
            functions,
            classes,
            parameters,
        )
        for name in ("bool", "bytes", "float", "int", "str")
    ) or _annotation_is_imported(
        annotation,
        "pathlib",
        "Path",
        assignments,
        functions,
        classes,
        parameters,
    ):
        return _ManifestShape.LEAF
    if not isinstance(annotation, ast.Subscript):
        return _ManifestShape.UNKNOWN
    sequence_name: str | None = None
    if _annotation_is_builtin(
        annotation,
        "list",
        assignments,
        functions,
        classes,
        parameters,
    ) or _annotation_is_imported(
        annotation,
        "typing",
        "List",
        assignments,
        functions,
        classes,
        parameters,
    ):
        sequence_name = "list"
    elif _annotation_is_builtin(
        annotation,
        "tuple",
        assignments,
        functions,
        classes,
        parameters,
    ) or _annotation_is_imported(
        annotation,
        "typing",
        "Tuple",
        assignments,
        functions,
        classes,
        parameters,
    ):
        sequence_name = "tuple"
    elif _annotation_is_imported(
        annotation,
        "collections.abc",
        "Sequence",
        assignments,
        functions,
        classes,
        parameters,
    ) or _annotation_is_imported(
        annotation,
        "typing",
        "Sequence",
        assignments,
        functions,
        classes,
        parameters,
    ):
        sequence_name = "sequence"
    if sequence_name is None:
        return _ManifestShape.UNKNOWN
    elements = (
        tuple(annotation.slice.elts)
        if isinstance(annotation.slice, ast.Tuple)
        else (annotation.slice,)
    )
    if sequence_name != "tuple" and len(elements) != 1:
        return _ManifestShape.UNKNOWN
    if (
        sequence_name == "tuple"
        and len(elements) == 2
        and isinstance(elements[1], ast.Constant)
        and elements[1].value is Ellipsis
    ):
        elements = elements[:1]
    if not elements:
        return _ManifestShape.UNKNOWN
    if all(
        _annotation_shape(
            element,
            assignments,
            functions,
            classes,
            parameters,
        )
        is _ManifestShape.LEAF
        for element in elements
    ):
        return _ManifestShape.LEAF
    return _ManifestShape.UNKNOWN


def _bind_annotation_provenance(annotation: ast.AST | None, assignments: AssignmentMap) -> None:
    if annotation is None:
        return
    for node in reversed(list(ast.walk(annotation))):
        setattr(
            node,
            ANNOTATION_SHAPE_ATTRIBUTE,
            _annotation_shape(node, assignments, {}, {}, {}),
        )


def _bind_function_annotation_provenance(
    function: FunctionNode, assignments: AssignmentMap
) -> None:
    arguments = function.args
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg is not None else ()),
        *((arguments.kwarg,) if arguments.kwarg is not None else ()),
    ):
        _bind_annotation_provenance(argument.annotation, assignments)
    _bind_annotation_provenance(function.returns, assignments)


def _bind_annotation_class_provenance(annotation: ast.AST | None, classes: ClassFields) -> None:
    if annotation is None:
        return
    for node in ast.walk(annotation):
        setattr(
            node,
            ANNOTATION_CLASS_FIELDS_ATTRIBUTE,
            classes.get(_terminal_name(node) or ""),
        )


def _bind_function_class_provenance(function: FunctionNode, classes: ClassFields) -> None:
    arguments = function.args
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg is not None else ()),
        *((arguments.kwarg,) if arguments.kwarg is not None else ()),
    ):
        _bind_annotation_class_provenance(argument.annotation, classes)
    _bind_annotation_class_provenance(function.returns, classes)


def _annotation_class_fields(
    annotation: ast.AST | None, classes: ClassFields
) -> dict[str, ast.AST] | None:
    if annotation is None:
        return None
    if hasattr(annotation, ANNOTATION_CLASS_FIELDS_ATTRIBUTE):
        bound = getattr(annotation, ANNOTATION_CLASS_FIELDS_ATTRIBUTE)
        return bound if isinstance(bound, dict) else None
    return classes.get(_terminal_name(annotation) or "")


def _subscript_result_annotation(
    annotation: ast.AST | None, index: ast.AST | None = None
) -> ast.AST | None:
    if not isinstance(annotation, ast.Subscript):
        return None
    name = _terminal_name(annotation.value)
    arguments = (
        annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
    )
    if name in {"dict", "Dict", "Mapping", "MutableMapping"} and len(arguments) == 2:
        return arguments[1]
    if name in {"list", "List", "Sequence", "set", "Set"} and len(arguments) == 1:
        return arguments[0]
    if name in {"tuple", "Tuple"} and arguments:
        if (
            len(arguments) == 2
            and isinstance(arguments[1], ast.Constant)
            and arguments[1].value is Ellipsis
        ):
            return arguments[0]
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            position = index.value
            if -len(arguments) <= position < len(arguments):
                return arguments[position]
    return None


def _expression_annotation(
    node: ast.AST,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
    *,
    seen: frozenset[str] = frozenset(),
) -> ast.AST | None:
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if candidates:
            if node.id in seen or len(candidates) != 1:
                return None
            return _expression_annotation(
                candidates[0],
                assignments,
                functions,
                classes,
                parameters,
                seen=seen | {node.id},
            )
        return parameters.get(node.id)
    if isinstance(node, ast.Attribute):
        parent = _expression_annotation(
            node.value,
            assignments,
            functions,
            classes,
            parameters,
            seen=seen,
        )
        fields = _annotation_class_fields(parent, classes)
        return fields.get(node.attr) if fields is not None else None
    if isinstance(node, ast.Subscript):
        selected = _selected_manifest_expression(node, assignments)
        if selected is not None:
            selected_node, selected_assignments = selected
            return _expression_annotation(
                selected_node,
                selected_assignments,
                functions,
                classes,
                parameters,
                seen=seen,
            )
        parent = _expression_annotation(
            node.value,
            assignments,
            functions,
            classes,
            parameters,
            seen=seen,
        )
        return _subscript_result_annotation(parent, node.slice)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = functions.get(node.func.id)
        if (
            function is not None
            and _helper_call_context(
                node,
                function,
                assignments,
                functions,
                classes,
                parameters,
                source=None,
                seen=seen,
                seen_functions=frozenset(),
            )
            is not None
        ):
            return function.node.returns
        if node.func.id in classes:
            return ast.Name(id=node.func.id, ctx=ast.Load())
        if node.func.id in {"bool", "float", "int", "str"}:
            return ast.Name(id=node.func.id, ctx=ast.Load())
    if isinstance(node, ast.IfExp):
        body = _expression_annotation(
            node.body,
            assignments,
            functions,
            classes,
            parameters,
            seen=seen,
        )
        other = _expression_annotation(
            node.orelse,
            assignments,
            functions,
            classes,
            parameters,
            seen=seen,
        )
        if isinstance(body, ast.expr) and isinstance(other, ast.expr):
            return ast.BinOp(left=body, op=ast.BitOr(), right=other)
    return None


def _merge_manifest_shapes(shapes: Iterator[_ManifestShape]) -> _ManifestShape:
    result = _ManifestShape.LEAF
    for shape in shapes:
        if shape is _ManifestShape.UNKNOWN:
            return shape
        if shape is _ManifestShape.KEYS:
            result = shape
    return result


def _sequence_elements(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    seen: frozenset[str] = frozenset(),
) -> tuple[ast.AST, ...] | None:
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if node.id in seen or len(candidates) != 1:
            return None
        return _sequence_elements(candidates[0], assignments, seen=seen | {node.id})
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return tuple(node.elts)
    if (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "items"
    ):
        mapping: ast.AST = node.func.value
        if isinstance(mapping, ast.Name):
            candidates = assignments.get(mapping.id, ())
            if mapping.id in seen or len(candidates) != 1:
                return None
            mapping = candidates[0]
        if isinstance(mapping, ast.Dict) and all(key is not None for key in mapping.keys):
            return tuple(
                ast.Tuple(elts=[key, value], ctx=ast.Load())
                for key, value in zip(mapping.keys, mapping.values, strict=True)
                if key is not None
            )
    return None


def _bind_comprehension_target(
    target: ast.AST,
    elements: tuple[ast.AST, ...],
    assignments: AssignmentMap,
) -> None:
    if isinstance(target, ast.Name):
        assignments[target.id] = elements or (_UnknownBinding(),)
        return
    if isinstance(target, ast.Starred):
        _bind_comprehension_target(target.value, (), assignments)
        return
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        root_name = _target_root_name(target)
        if root_name is not None:
            assignments[root_name] = (_UnknownBinding(),)
        return
    if not isinstance(target, (ast.List, ast.Tuple)):
        return
    rows = [
        element.elts
        for element in elements
        if isinstance(element, (ast.List, ast.Tuple)) and len(element.elts) == len(target.elts)
    ]
    if len(rows) != len(elements):
        for child in target.elts:
            _bind_comprehension_target(child, (), assignments)
        return
    for index, child in enumerate(target.elts):
        _bind_comprehension_target(
            child,
            tuple(row[index] for row in rows),
            assignments,
        )


def _comprehension_assignments(
    generators: list[ast.comprehension], assignments: AssignmentMap
) -> AssignmentMap:
    scoped = dict(assignments)
    for generator in generators:
        elements = _sequence_elements(generator.iter, scoped)
        _bind_comprehension_target(generator.target, elements or (), scoped)
    return scoped


def _checksum_pinned_manifest_leaf(source: str | None, node: ast.AST) -> bool:
    if source is None or source not in CHECKSUM_PINNED_MANIFEST_LEAVES:
        return False
    _digest_value, declarations = CHECKSUM_PINNED_MANIFEST_LEAVES[source]
    expression = getattr(node, SNAPSHOT_SOURCE_EXPRESSION_ATTRIBUTE, ast.unparse(node))
    identity = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0), expression)
    return identity in declarations


def _checksum_pinned_manifest_subtree(source: str | None, node: ast.AST) -> frozenset[str] | None:
    if source is None or source not in CHECKSUM_PINNED_MANIFEST_SUBTREES:
        return None
    _source_digest, _producer_path, _producer_digest, declarations = (
        CHECKSUM_PINNED_MANIFEST_SUBTREES[source]
    )
    expression = getattr(node, SNAPSHOT_SOURCE_EXPRESSION_ATTRIBUTE, ast.unparse(node))
    identity = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0), expression)
    for line, column, expression, _producer_identity, pointers in declarations:
        if identity == (line, column, expression):
            return frozenset(pointers)
    return None


def _unshadowed_builtin(
    name: str | None,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> bool:
    return (
        name is not None
        and name not in assignments
        and name not in functions
        and name not in classes
        and name not in parameters
    )


def _exact_imported_module(
    name: str,
    module: str,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> bool:
    candidates = assignments.get(name, ())
    return (
        name not in functions
        and name not in classes
        and name not in parameters
        and len(candidates) == 1
        and isinstance(candidates[0], _ImportBinding)
        and candidates[0].module == module
        and candidates[0].symbol is None
    )


def _exact_imported_symbol(
    name: str,
    module: str,
    symbol: str,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
) -> bool:
    candidates = assignments.get(name, ())
    return (
        name not in functions
        and name not in classes
        and name not in parameters
        and len(candidates) == 1
        and isinstance(candidates[0], _ImportBinding)
        and candidates[0].module == module
        and candidates[0].symbol == symbol
    )


def _helper_call_context(
    call: ast.Call,
    function: FunctionContext,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    classes: ClassFields,
    parameters: dict[str, ast.AST],
    *,
    source: str | None,
    seen: frozenset[str],
    seen_functions: frozenset[str],
) -> tuple[AssignmentMap, dict[str, ast.AST]] | None:
    arguments = function.node.args
    if (
        arguments.vararg is not None
        or arguments.kwarg is not None
        or any(isinstance(argument, ast.Starred) for argument in call.args)
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return None

    positional = [*arguments.posonlyargs, *arguments.args]
    keyword_only = list(arguments.kwonlyargs)
    if len(call.args) > len(positional):
        return None

    bound: dict[str, tuple[ast.AST, bool]] = {
        parameter.arg: (argument, True)
        for parameter, argument in zip(positional, call.args, strict=False)
    }
    keyword_names = {parameter.arg for parameter in arguments.args + arguments.kwonlyargs}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in keyword_names or keyword.arg in bound:
            return None
        bound[keyword.arg] = (keyword.value, True)

    positional_defaults = {
        parameter.arg: default
        for parameter, default in zip(
            positional[-len(arguments.defaults) :] if arguments.defaults else (),
            arguments.defaults,
            strict=True,
        )
    }
    keyword_defaults = {
        parameter.arg: default
        for parameter, default in zip(keyword_only, arguments.kw_defaults, strict=True)
        if default is not None
    }
    for parameter in positional + keyword_only:
        if parameter.arg in bound:
            continue
        default = positional_defaults.get(parameter.arg) or keyword_defaults.get(parameter.arg)
        if default is None:
            return None
        bound[parameter.arg] = (default, False)

    helper_assignments = dict(function.module_assignments)
    helper_assignments.update(
        _assignment_map(
            function.node,
            function.module_assignments,
            qualified_assignments=function.qualified_assignments,
            deferred_callable_ids=frozenset(
                id(context.node)
                for context in (
                    *function.functions.values(),
                    *function.qualified_functions.values(),
                )
            ),
        )
    )
    _apply_helper_mutations(
        function.node,
        helper_assignments,
        function.functions,
        qualified_functions=function.qualified_functions,
        qualified_assignments=function.qualified_assignments,
    )
    helper_parameters = _function_parameter_annotations(function.node)
    function_id = f"{function.source}:{function.node.name}"
    for name, (value, from_caller) in bound.items():
        if from_caller:
            value_assignments = assignments
            value_functions = functions
            value_classes = classes
            value_parameters = parameters
            value_source = source
            shape = _manifest_expression_shape(
                value,
                value_assignments,
                value_functions,
                classes=value_classes,
                parameters=value_parameters,
                source=value_source,
                seen=seen,
                seen_functions=seen_functions,
            )
        else:
            value_assignments = function.definition_assignments
            value_functions = function.functions
            value_classes = function.classes
            value_parameters = {}
            value_source = function.source
            shape = _manifest_expression_shape(
                value,
                value_assignments,
                value_functions,
                classes=value_classes,
                parameters=value_parameters,
                source=value_source,
                seen=frozenset(),
                seen_functions=seen_functions | {function_id},
            )
        if shape is _ManifestShape.LEAF:
            helper_assignments.setdefault(name, (ast.Constant(value=None),))
            continue
        if shape is not _ManifestShape.UNKNOWN:
            return None
        actual_annotation = _expression_annotation(
            value,
            value_assignments,
            value_functions,
            value_classes,
            value_parameters,
        )
        formal_annotation = helper_parameters.get(name)
        actual_fields = _annotation_class_fields(actual_annotation, value_classes)
        formal_fields = _annotation_class_fields(formal_annotation, function.classes)
        if (
            actual_fields is None
            or formal_fields is None
            or actual_fields.keys() != formal_fields.keys()
            or any(
                ast.dump(actual_fields[field_name]) != ast.dump(formal_fields[field_name])
                for field_name in actual_fields
            )
        ):
            return None
    return helper_assignments, helper_parameters


def _bound_function_call_arguments(
    call: ast.Call, function: FunctionNode
) -> dict[str, tuple[ast.AST, bool]] | None:
    arguments = function.args
    if (
        arguments.vararg is not None
        or arguments.kwarg is not None
        or any(isinstance(argument, ast.Starred) for argument in call.args)
        or any(keyword.arg is None for keyword in call.keywords)
    ):
        return None
    positional = [*arguments.posonlyargs, *arguments.args]
    if len(call.args) > len(positional):
        return None
    bound: dict[str, tuple[ast.AST, bool]] = {
        parameter.arg: (argument, True)
        for parameter, argument in zip(positional, call.args, strict=False)
    }
    keyword_names = {parameter.arg for parameter in arguments.args + arguments.kwonlyargs}
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in keyword_names or keyword.arg in bound:
            return None
        bound[keyword.arg] = (keyword.value, True)
    positional_defaults = {
        parameter.arg: default
        for parameter, default in zip(
            positional[-len(arguments.defaults) :] if arguments.defaults else (),
            arguments.defaults,
            strict=True,
        )
    }
    keyword_defaults = {
        parameter.arg: default
        for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is not None
    }
    for parameter in (*positional, *arguments.kwonlyargs):
        if parameter.arg in bound:
            continue
        default = positional_defaults.get(parameter.arg) or keyword_defaults.get(parameter.arg)
        if default is None:
            return None
        bound[parameter.arg] = (default, False)
    return bound


def _bound_call_arguments(
    call: ast.Call, function: FunctionContext
) -> dict[str, tuple[ast.AST, bool]] | None:
    return _bound_function_call_arguments(call, function.node)


def _mutated_function_parameters(
    function: FunctionContext, *, seen: frozenset[str] = frozenset()
) -> set[str]:
    if function.mutated_parameters is not None:
        return set(function.mutated_parameters)
    function_id = f"{function.source}:{function.node.name}"
    if function_id in seen:
        return set()
    parameters = set(_function_parameter_annotations(function.node))
    assignments = _assignment_map(
        function.node,
        function.module_assignments,
        qualified_assignments=function.qualified_assignments,
    )
    mutated = {
        name
        for name in parameters
        if any(isinstance(candidate, _UnknownBinding) for candidate in assignments.get(name, ()))
    }
    for node in _lexical_nodes(function.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        called = function.functions.get(node.func.id)
        if called is None:
            continue
        bound = _bound_call_arguments(node, called)
        if bound is None:
            continue
        for name in _mutated_function_parameters(called, seen=seen | {function_id}):
            actual = bound.get(name)
            if actual is None or not actual[1]:
                continue
            mutated.update(_loaded_root_names(actual[0]) & parameters)
    if not seen:
        function.mutated_parameters = frozenset(mutated)
    return mutated


def _assignment_identity_aliases(assignments: AssignmentMap) -> dict[int, set[str]]:
    identities: dict[int, set[str]] = {}
    for name, candidates in assignments.items():
        for candidate in candidates:
            if isinstance(candidate, _UnknownBinding):
                continue
            for nested in ast.walk(candidate):
                identities.setdefault(id(nested), set()).add(name)
    return identities


def _origin_candidate_aliases(
    origin_candidates: tuple[ast.AST, ...],
    assignments: AssignmentMap,
    identity_aliases: dict[int, set[str]] | None = None,
    *,
    follow_contents: bool = False,
) -> set[str]:
    origin_candidates = tuple(
        candidate for candidate in origin_candidates if not isinstance(candidate, _UnknownBinding)
    )
    if not origin_candidates:
        return set()
    if identity_aliases is None:
        identity_aliases = _assignment_identity_aliases(assignments)
    matched: set[str] = set()
    for origin_candidate in origin_candidates:
        candidates = ast.walk(origin_candidate) if follow_contents else (origin_candidate,)
        for nested_candidate in candidates:
            for local_name in identity_aliases.get(id(nested_candidate), ()):
                matched.update(_current_alias_component(local_name, assignments))
    return matched


def _origin_binding_aliases(
    name: str,
    assignments: AssignmentMap,
    origin_assignments: AssignmentMap,
    identity_aliases: dict[int, set[str]] | None = None,
    *,
    follow_contents: bool = False,
) -> set[str]:
    return _origin_candidate_aliases(
        origin_assignments.get(name, ()),
        assignments,
        identity_aliases,
        follow_contents=follow_contents,
    )


def _assignment_origin_scope(
    node: ast.AST,
    inherited_scope: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
) -> AssignmentMap:
    origin_scope = getattr(node, ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE, None)
    if isinstance(origin_scope, dict):
        return origin_scope
    origin_module = getattr(node, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE, None)
    return qualified_assignments.get(origin_module, inherited_scope)


def _qualified_selected_reference_expressions(
    node: ast.Subscript,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[ast.AST]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (f"selection:{id(node.slice)}", id(node.value), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    selected = _selected_reference_provenance(node, assignments)
    if selected.state is _ProvenanceState.KNOWN:
        for value in selected.values:
            setattr(
                value,
                ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE,
                dict(assignments),
            )
        return selected
    if selected.state is _ProvenanceState.IRRELEVANT:
        return selected

    def select_candidate(
        candidate: ast.AST,
        candidate_assignments: AssignmentMap,
    ) -> _Provenance[ast.AST]:
        return _qualified_selected_reference_expressions(
            ast.Subscript(value=candidate, slice=node.slice, ctx=ast.Load()),
            candidate_assignments,
            qualified_assignments,
            seen=seen,
        )

    container = node.value
    if isinstance(container, _ImportBinding):
        if container.symbol is None:
            return _unresolved_provenance()
        imported_state = qualified_assignments.get(container.module)
        if imported_state is None:
            return _unresolved_provenance()
        candidates = imported_state.get(container.symbol, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            select_candidate(candidate, imported_state) for candidate in candidates
        )
    if isinstance(container, ast.Name):
        candidates = assignments.get(container.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            select_candidate(candidate, assignments) for candidate in candidates
        )
    if isinstance(container, ast.Attribute):
        owners = _qualified_imported_modules(
            container.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        unresolved = owners.state is _ProvenanceState.UNRESOLVED
        results: list[_Provenance[ast.AST]] = []
        for owner in owners.values:
            owner_state = qualified_assignments.get(owner)
            if owner_state is None:
                unresolved = True
                continue
            candidates = owner_state.get(container.attr, ())
            if not candidates:
                unresolved = True
                continue
            results.extend(select_candidate(candidate, owner_state) for candidate in candidates)
        owner_references = _qualified_assignment_references(
            container.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        if owner_references.state is _ProvenanceState.UNRESOLVED:
            unresolved = True
        for owner_module, owner_symbol in owner_references.values:
            owner_state = qualified_assignments.get(owner_module)
            if owner_state is None:
                unresolved = True
                continue
            owner_bindings = tuple(
                candidate
                for candidate in owner_state.get(owner_symbol, ())
                if isinstance(candidate, _ClassBinding)
            )
            if not owner_bindings:
                unresolved = True
                continue
            for owner_binding in owner_bindings:
                class_state = getattr(
                    owner_binding.node,
                    CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                    {},
                )
                candidates = class_state.get(container.attr, ())
                if not candidates:
                    unresolved = True
                    continue
                results.extend(select_candidate(candidate, class_state) for candidate in candidates)
        result = _merge_provenance(results)
        return (
            _unresolved_provenance(result.values)
            if unresolved or result.state is _ProvenanceState.IRRELEVANT
            else result
        )
    if isinstance(container, ast.Subscript):
        selected_containers = _qualified_selected_reference_expressions(
            container,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            select_candidate(candidate, assignments) for candidate in selected_containers.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected_containers.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(container, ast.Call):
        returned = _closed_call_returns(
            container,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            select_candidate(value, value_assignments)
            for value, value_assignments, _module in returned.values
        )
        return (
            _unresolved_provenance(result.values)
            if returned.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(container, ast.IfExp):
        branches = (container.body, container.orelse)
    elif isinstance(container, ast.BoolOp):
        branches = tuple(container.values)
    elif isinstance(container, ast.NamedExpr):
        branches = (container.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(select_candidate(branch, assignments) for branch in branches)
    return _unresolved_provenance()


def _exact_assignment_accessor(
    node: ast.AST,
    module: str,
    name: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}
    if isinstance(node, _ImportBinding):
        return node.module == module and node.symbol == name
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return module == "builtins" and node.id == name
        if len(candidates) != 1:
            return False
        return _exact_assignment_accessor(
            candidates[0],
            module,
            name,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute):
        if node.attr == name and _imported_module_expression(node.value, assignments) == module:
            return True
        owners = _qualified_imported_modules(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        if owners.state is not _ProvenanceState.KNOWN or not owners.values:
            return False
        candidates: list[tuple[ast.AST, AssignmentMap]] = []
        for owner in owners.values:
            owner_state = qualified_assignments.get(owner)
            if owner_state is None:
                return False
            owner_candidates = owner_state.get(node.attr, ())
            if not owner_candidates:
                return False
            candidates.extend((candidate, owner_state) for candidate in owner_candidates)
        return bool(candidates) and all(
            _exact_assignment_accessor(
                candidate,
                module,
                name,
                candidate_assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate, candidate_assignments in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        return (
            selected.state is _ProvenanceState.KNOWN
            and bool(selected.values)
            and all(
                _exact_assignment_accessor(
                    candidate,
                    module,
                    name,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in selected.values
            )
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        return (
            returned.state is _ProvenanceState.KNOWN
            and bool(returned.values)
            and all(
                _exact_assignment_accessor(
                    value,
                    module,
                    name,
                    value_assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for value, value_assignments, _module in returned.values
            )
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    return bool(branches) and all(
        _exact_assignment_accessor(
            branch,
            module,
            name,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        for branch in branches
    )


def _exact_builtin_assignment_accessor(
    node: ast.AST,
    name: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    return _exact_assignment_accessor(
        node,
        "builtins",
        name,
        assignments,
        qualified_assignments,
        seen=seen,
    )


def _exact_builtin_bound_attribute_accessor(
    node: ast.AST,
    owner: str,
    attribute: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        return len(candidates) == 1 and _exact_builtin_bound_attribute_accessor(
            candidates[0],
            owner,
            attribute,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute):
        return node.attr == attribute and _exact_builtin_assignment_accessor(
            node.value,
            owner,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
        )
        return (
            selected.state is _ProvenanceState.KNOWN
            and bool(selected.values)
            and all(
                _exact_builtin_bound_attribute_accessor(
                    candidate,
                    owner,
                    attribute,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in selected.values
            )
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return all(
            _exact_builtin_bound_attribute_accessor(
                branch,
                owner,
                attribute,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
        )
        return (
            returned.state is _ProvenanceState.KNOWN
            and bool(returned.values)
            and all(
                _exact_builtin_bound_attribute_accessor(
                    value,
                    owner,
                    attribute,
                    value_assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for value, value_assignments, _module in returned.values
            )
        )
    return False


@dataclass(frozen=True)
class _ClosedCallReturns:
    state: _ProvenanceState
    values: tuple[tuple[ast.AST, AssignmentMap, str], ...] = ()


def _qualified_callable_provenance(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    inherited_module: str | None = None,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[CallbackBinding]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("callable", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, _FunctionBinding):
        return _known_provenance(((node.node, node.module, node.implicit_positional_count),))
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
        module = getattr(
            node,
            ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
            inherited_module,
        )
        return (
            _known_provenance(((node, module, 0),))
            if isinstance(module, str)
            else _unresolved_provenance()
        )
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, _ImportBinding):
        if node.symbol is None:
            return _irrelevant_provenance()
        imported_state = qualified_assignments.get(node.module)
        if imported_state is None:
            return _unresolved_provenance()
        candidates = imported_state.get(node.symbol, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_callable_provenance(
                candidate,
                imported_state,
                qualified_assignments,
                inherited_module=node.module,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_callable_provenance(
                candidate,
                assignments,
                qualified_assignments,
                inherited_module=inherited_module,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Attribute):
        imported_module = _imported_module_expression(node.value, assignments)
        if imported_module is None:
            return _unresolved_provenance()
        imported_state = qualified_assignments.get(imported_module)
        if imported_state is None:
            return _unresolved_provenance()
        candidates = imported_state.get(node.attr, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_callable_provenance(
                candidate,
                imported_state,
                qualified_assignments,
                inherited_module=imported_module,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_callable_provenance(
                candidate,
                assignments,
                qualified_assignments,
                inherited_module=inherited_module,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_callable_provenance(
                branch,
                assignments,
                qualified_assignments,
                inherited_module=inherited_module,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            inherited_module=inherited_module,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_callable_provenance(
                value,
                value_assignments,
                qualified_assignments,
                inherited_module=module,
                seen=seen,
            )
            for value, value_assignments, module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(node, (ast.Constant, ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return _irrelevant_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _closed_call_returns(
    node: ast.Call,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    inherited_module: str | None = None,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _ClosedCallReturns:
    callables = _qualified_callable_provenance(
        node.func,
        assignments,
        qualified_assignments,
        inherited_module=inherited_module,
        seen=seen,
    )
    unresolved = callables.state is _ProvenanceState.UNRESOLVED
    returned: list[tuple[ast.AST, AssignmentMap, str]] = []
    for called, module, implicit_positional_count in callables.values:
        expanded = (
            node
            if not implicit_positional_count
            else ast.Call(
                func=node.func,
                args=[
                    *(ast.Constant(value=None) for _ in range(implicit_positional_count)),
                    *node.args,
                ],
                keywords=node.keywords,
            )
        )
        bound = _bound_function_call_arguments(expanded, called)
        if bound is None:
            unresolved = True
            continue
        called_state = dict(
            getattr(
                called,
                FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                assignments,
            )
        )
        definition_state = dict(called_state)
        for parameter, (actual, supplied) in bound.items():
            actual_state = assignments if supplied else definition_state
            called_state[parameter] = (_snapshot_bound_expression(actual, actual_state),)
        returned_values = (
            (called.body,)
            if isinstance(called, ast.Lambda)
            else tuple(
                candidate.value
                for candidate in _lexical_nodes(called)
                if isinstance(candidate, ast.Return) and candidate.value is not None
            )
        )
        returned.extend((value, called_state, module) for value in returned_values)
    if unresolved:
        return _ClosedCallReturns(_ProvenanceState.UNRESOLVED, tuple(returned))
    return _ClosedCallReturns(
        _ProvenanceState.KNOWN if returned else _ProvenanceState.IRRELEVANT,
        tuple(returned),
    )


def _qualified_bound_object_provenance(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("bound-object", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, (_ClassBinding, _FunctionBinding)):
        return _known_provenance((node.module,))
    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
        module = getattr(node, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE, None)
        return _known_provenance((module,)) if isinstance(module, str) else _unresolved_provenance()
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, _ImportBinding):
        return (
            _known_provenance((node.module,))
            if node.symbol is None
            else _unresolved_provenance((node.module,))
        )
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_bound_object_provenance(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Attribute):
        imported_module = _imported_module_expression(node.value, assignments)
        if imported_module is None:
            return _unresolved_provenance()
        imported_state = qualified_assignments.get(imported_module)
        if imported_state is None:
            return _unresolved_provenance()
        candidates = imported_state.get(node.attr, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_bound_object_provenance(
                candidate,
                imported_state,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_bound_object_provenance(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_bound_object_provenance(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_bound_object_provenance(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(node, (ast.Constant, ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return _irrelevant_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_static_string_values(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("string", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _known_provenance((node.value,))
    if isinstance(node, ast.Constant):
        return _irrelevant_provenance()
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, (_ClassBinding, _FunctionBinding)):
        return _irrelevant_provenance()
    if isinstance(node, _ImportBinding):
        if node.symbol is None:
            return _irrelevant_provenance()
        imported_state = qualified_assignments.get(node.module)
        if imported_state is None:
            return _unresolved_provenance()
        candidates = imported_state.get(node.symbol, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_static_string_values(
                candidate,
                imported_state,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_static_string_values(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Attribute):
        owners = _qualified_imported_modules(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        unresolved = owners.state is _ProvenanceState.UNRESOLVED
        results: list[_Provenance[str]] = []
        for owner in owners.values:
            owner_state = qualified_assignments.get(owner)
            if owner_state is None:
                unresolved = True
                continue
            candidates = owner_state.get(node.attr, ())
            if not candidates:
                unresolved = True
                continue
            results.extend(
                _qualified_static_string_values(
                    candidate,
                    owner_state,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in candidates
            )
        result = _merge_provenance(results)
        return _unresolved_provenance(result.values) if unresolved else result
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_static_string_values(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_static_string_values(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_static_string_values(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
        return _irrelevant_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_bound_attribute_accessor_provenance(
    node: ast.AST,
    accessor: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (f"bound-accessor:{accessor}", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, ast.Attribute) and node.attr == accessor:
        return _qualified_bound_object_provenance(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute):
        return _unresolved_provenance()
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_bound_attribute_accessor_provenance(
                candidate,
                accessor,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_bound_attribute_accessor_provenance(
                candidate,
                accessor,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_bound_attribute_accessor_provenance(
                branch,
                accessor,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_bound_attribute_accessor_provenance(
                value,
                accessor,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(
        node,
        (
            ast.Constant,
            ast.Dict,
            ast.List,
            ast.Set,
            ast.Tuple,
            _ClassBinding,
            _FunctionBinding,
        ),
    ):
        return _irrelevant_provenance()
    if isinstance(node, _ImportBinding):
        return _irrelevant_provenance() if node.symbol is None else _unresolved_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_reflected_object_provenance(
    node: ast.AST,
    attribute: str,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (f"reflection:{attribute}", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, ast.Attribute) and node.attr == attribute:
        return _qualified_bound_object_provenance(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    reflected_object: ast.AST | None = None
    reflected_name: ast.AST | None = None
    if (
        isinstance(node, ast.Call)
        and len(node.args) in {2, 3}
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "getattr",
            assignments,
            qualified_assignments,
        )
    ):
        reflected_object, reflected_name = node.args[:2]
    elif isinstance(node, ast.Call) and not node.keywords:
        if len(node.args) == 1:
            accessor = _qualified_bound_attribute_accessor_provenance(
                node.func,
                "__getattribute__",
                assignments,
                qualified_assignments,
                seen=seen,
            )
            if accessor.state is _ProvenanceState.KNOWN:
                reflected_name = node.args[0]
                names = _qualified_static_string_values(
                    reflected_name,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                )
                if attribute not in names.values:
                    return (
                        _unresolved_provenance()
                        if names.state is _ProvenanceState.UNRESOLVED
                        else _irrelevant_provenance()
                    )
                return (
                    _unresolved_provenance(accessor.values)
                    if names.state is _ProvenanceState.UNRESOLVED
                    else accessor
                )
        if len(node.args) == 2 and _exact_builtin_bound_attribute_accessor(
            node.func,
            "object",
            "__getattribute__",
            assignments,
            qualified_assignments,
        ):
            reflected_object, reflected_name = node.args
    if reflected_object is None or reflected_name is None:
        if isinstance(node, ast.Call):
            returned = _closed_call_returns(
                node,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            reflected_returns = _merge_provenance(
                _qualified_reflected_object_provenance(
                    value,
                    attribute,
                    value_assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for value, value_assignments, _module in returned.values
            )
            if returned.state is _ProvenanceState.UNRESOLVED:
                return _unresolved_provenance(reflected_returns.values)
            if reflected_returns.state is not _ProvenanceState.IRRELEVANT:
                return reflected_returns
        return _irrelevant_provenance()
    names = _qualified_static_string_values(
        reflected_name,
        assignments,
        qualified_assignments,
        seen=seen,
    )
    objects = _qualified_bound_object_provenance(
        reflected_object,
        assignments,
        qualified_assignments,
        seen=seen,
    )
    if attribute not in names.values:
        return (
            _unresolved_provenance(objects.values)
            if names.state is _ProvenanceState.UNRESOLVED
            else _irrelevant_provenance()
        )
    if names.state is _ProvenanceState.UNRESOLVED or objects.state is _ProvenanceState.UNRESOLVED:
        return _unresolved_provenance(objects.values)
    return objects


def _qualified_module_name_values(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    reflected = _qualified_reflected_object_provenance(
        node,
        "__module__",
        assignments,
        qualified_assignments,
        seen=seen,
    )
    if reflected.state is not _ProvenanceState.IRRELEVANT:
        return reflected
    return _qualified_static_string_values(
        node,
        assignments,
        qualified_assignments,
        seen=seen,
    )


def _resolved_module_names(
    name: ast.AST,
    package: ast.AST | None,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
) -> _Provenance[str]:
    names = _qualified_module_name_values(
        name,
        assignments,
        qualified_assignments,
    )
    packages = (
        _qualified_module_name_values(
            package,
            assignments,
            qualified_assignments,
        )
        if package is not None
        else _irrelevant_provenance()
    )
    resolved = {candidate for candidate in names.values if not candidate.startswith(".")}
    relative = set(names.values) - resolved
    unresolved = names.state is _ProvenanceState.UNRESOLVED
    if relative and packages.state is not _ProvenanceState.KNOWN:
        unresolved = True
    for candidate in relative:
        level = len(candidate) - len(candidate.lstrip("."))
        suffix = candidate[level:]
        for package_name in packages.values:
            parts = package_name.split(".")
            retained = len(parts) - level + 1
            if retained <= 0:
                unresolved = True
                continue
            prefix = ".".join(parts[:retained])
            resolved.add(f"{prefix}.{suffix}" if suffix else prefix)
    return _unresolved_provenance(resolved) if unresolved else _known_provenance(resolved)


def _module_registry_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and _imported_module_expression(node.value, assignments) == "sys"
    ):
        return True
    return isinstance(node, ast.Name) and any(
        _module_registry_expression(
            candidate,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        for candidate in assignments.get(node.id, ())
    )


def _module_registry_getter_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}
    if (
        isinstance(node, ast.Attribute)
        and node.attr in {"get", "__getitem__"}
        and _module_registry_expression(
            node.value,
            assignments,
            qualified_assignments,
        )
    ):
        return True
    return isinstance(node, ast.Name) and any(
        _module_registry_getter_expression(
            candidate,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        for candidate in assignments.get(node.id, ())
    )


def _qualified_imported_modules(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("module", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if (
        isinstance(node, ast.Call)
        and len(node.args) in {1, 2}
        and all(keyword.arg == "package" for keyword in node.keywords)
        and _exact_assignment_accessor(
            node.func,
            "importlib",
            "import_module",
            assignments,
            qualified_assignments,
            seen=seen,
        )
    ):
        package = (
            node.args[1]
            if len(node.args) == 2
            else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "package"),
                None,
            )
        )
        return _resolved_module_names(
            node.args[0],
            package,
            assignments,
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and node.args
        and _exact_builtin_assignment_accessor(
            node.func,
            "__import__",
            assignments,
            qualified_assignments,
            seen=seen,
        )
    ):
        return _resolved_module_names(
            node.args[0],
            None,
            assignments,
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_assignment_accessor(
            node.func,
            "inspect",
            "getmodule",
            assignments,
            qualified_assignments,
            seen=seen,
        )
    ):
        return _qualified_bound_object_provenance(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Subscript) and _module_registry_expression(
        node.value,
        assignments,
        qualified_assignments,
    ):
        return _qualified_module_name_values(
            node.slice,
            assignments,
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) in {1, 2}
        and not node.keywords
        and _module_registry_getter_expression(
            node.func,
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_module_name_values(
            node.args[0],
            assignments,
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 2
        and not node.keywords
        and _exact_assignment_accessor(
            node.func,
            "operator",
            "getitem",
            assignments,
            qualified_assignments,
            seen=seen,
        )
        and _module_registry_expression(
            node.args[0],
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_module_name_values(
            node.args[1],
            assignments,
            qualified_assignments,
        )
    imported_module = _imported_module_expression(node, assignments)
    if imported_module is not None:
        return _known_provenance((imported_module,))
    if isinstance(node, _ImportBinding):
        return _unresolved_provenance()
    if isinstance(node, ast.Attribute):
        owners = _qualified_imported_modules(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        unresolved = owners.state is _ProvenanceState.UNRESOLVED
        results: list[_Provenance[str]] = []
        for owner in owners.values:
            owner_state = qualified_assignments.get(owner)
            if owner_state is None:
                unresolved = True
                continue
            candidates = owner_state.get(node.attr, ())
            if not candidates:
                unresolved = True
                continue
            results.extend(
                _qualified_imported_modules(
                    candidate,
                    owner_state,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in candidates
            )
        result = _merge_provenance(results)
        if unresolved:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_imported_modules(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_imported_modules(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_imported_modules(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_imported_modules(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(
        node,
        (
            ast.Constant,
            ast.Dict,
            ast.List,
            ast.Set,
            ast.Tuple,
            ast.Lambda,
            ast.AsyncFunctionDef,
            ast.FunctionDef,
            _ClassBinding,
            _FunctionBinding,
        ),
    ):
        return _irrelevant_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_namespace_modules(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("namespace", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "globals",
            assignments,
            qualified_assignments,
        )
    ):
        origin_module = getattr(node, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE, None)
        return (
            _known_provenance((origin_module,))
            if isinstance(origin_module, str)
            else _unresolved_provenance()
        )
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_namespace_modules(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_namespace_modules(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "vars",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_imported_modules(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_assignment_accessor(
            node.func,
            "types",
            "MappingProxyType",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_namespace_modules(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute) and node.attr == "__dict__":
        return _qualified_imported_modules(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute):
        reflected = _qualified_reflected_object_provenance(
            node,
            "__globals__",
            assignments,
            qualified_assignments,
            seen=seen,
        )
        if reflected.state is not _ProvenanceState.IRRELEVANT:
            return reflected
        return _unresolved_provenance()
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "dict",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_namespace_modules(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"items", "keys", "values"}
        and not node.args
        and not node.keywords
    ):
        return _qualified_namespace_modules(
            node.func.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "copy"
        and not node.args
        and not node.keywords
    ):
        return _qualified_namespace_modules(
            node.func.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_assignment_accessor(
            node.func,
            "copy",
            "copy",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_namespace_modules(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _merge_provenance(
            (
                _qualified_namespace_modules(
                    node.left,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                ),
                _qualified_namespace_modules(
                    node.right,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                ),
            )
        )
    if isinstance(node, ast.Dict):
        return _merge_provenance(
            _qualified_namespace_modules(
                value,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for key, value in zip(node.keys, node.values, strict=True)
            if key is None
        )
    if isinstance(node, (ast.DictComp, ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        return _merge_provenance(
            _qualified_namespace_modules(
                generator.iter,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for generator in node.generators
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "next",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_namespace_modules(
            node.args[0],
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_namespace_modules(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        reflected = _qualified_reflected_object_provenance(
            node,
            "__globals__",
            assignments,
            qualified_assignments,
            seen=seen,
        )
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        results = [
            _qualified_namespace_modules(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        ]
        results.extend(
            _qualified_namespace_modules(
                argument,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
        )
        result = _merge_provenance(results)
        if reflected.state is _ProvenanceState.KNOWN:
            return reflected
        if result.state is _ProvenanceState.KNOWN:
            return result
        if (
            reflected.state is _ProvenanceState.UNRESOLVED
            or returned.state is _ProvenanceState.UNRESOLVED
            or result.state is _ProvenanceState.UNRESOLVED
        ):
            return _unresolved_provenance((*reflected.values, *result.values))
        return _irrelevant_provenance()
    reflected = _qualified_reflected_object_provenance(
        node,
        "__globals__",
        assignments,
        qualified_assignments,
        seen=seen,
    )
    if reflected.state is not _ProvenanceState.IRRELEVANT:
        return reflected
    if isinstance(
        node,
        (
            ast.Constant,
            ast.List,
            ast.Set,
            ast.Tuple,
            ast.Lambda,
            ast.AsyncFunctionDef,
            ast.FunctionDef,
            _ClassBinding,
            _FunctionBinding,
        ),
    ):
        return _irrelevant_provenance()
    if isinstance(node, _ImportBinding):
        return _irrelevant_provenance() if node.symbol is None else _unresolved_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_namespace_dependency_modules(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("namespace-dependency", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    results = [
        _qualified_namespace_modules(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    ]
    if isinstance(node, ast.Call):
        referenced_names = _merge_provenance(
            _qualified_module_name_values(
                value,
                assignments,
                qualified_assignments,
            )
            for value in (*node.args, *(keyword.value for keyword in node.keywords))
        )
        matched_modules = {
            module
            for name in referenced_names.values
            for module in qualified_assignments
            if name == module or name.startswith(f"{module}.")
        }
        results.append(
            _unresolved_provenance(matched_modules)
            if referenced_names.state is _ProvenanceState.UNRESOLVED
            else _known_provenance(matched_modules)
        )
    seen = seen | {marker}
    if isinstance(node, _FunctionBinding):
        function_state = getattr(
            node.node,
            FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
            assignments,
        )
        if any(
            isinstance(candidate, ast.Call)
            and not candidate.args
            and not candidate.keywords
            and _exact_builtin_assignment_accessor(
                candidate.func,
                "globals",
                function_state,
                qualified_assignments,
            )
            for candidate in ast.walk(node.node)
        ):
            results.append(_known_provenance((node.module,)))
        results.append(
            _qualified_namespace_dependency_modules(
                node.node,
                function_state,
                qualified_assignments,
                seen=seen,
            )
        )
    elif isinstance(node, _ClassBinding):
        class_state = getattr(
            node.node,
            CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
            assignments,
        )
        if any(
            isinstance(candidate, ast.Call)
            and not candidate.args
            and not candidate.keywords
            and _exact_builtin_assignment_accessor(
                candidate.func,
                "globals",
                class_state,
                qualified_assignments,
            )
            for candidate in ast.walk(node.node)
        ):
            results.append(_known_provenance((node.module,)))
        results.append(
            _qualified_namespace_dependency_modules(
                node.node,
                class_state,
                qualified_assignments,
                seen=seen,
            )
        )
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        results.append(
            _merge_provenance(
                _qualified_namespace_dependency_modules(
                    candidate,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in candidates
            )
            if candidates
            else _unresolved_provenance()
        )
    results.extend(
        _qualified_namespace_dependency_modules(
            child,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        for child in ast.iter_child_nodes(node)
    )
    return _merge_provenance(results)


def _qualified_namespace_getters(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("namespace-getter", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, _UnknownBinding):
        return _unresolved_provenance()
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_namespace_getters(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.Attribute) and node.attr in {
        "get",
        "pop",
        "setdefault",
        "__getitem__",
    }:
        return _qualified_namespace_modules(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute) and node.attr == "__getattribute__":
        return _qualified_bound_object_provenance(
            node.value,
            assignments,
            qualified_assignments,
            seen=seen,
        )
    if isinstance(node, ast.Attribute):
        return _unresolved_provenance()
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_namespace_getters(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        return (
            _unresolved_provenance(result.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_namespace_getters(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_namespace_getters(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        if returned.state is _ProvenanceState.UNRESOLVED:
            return _unresolved_provenance(result.values)
        return result
    if isinstance(
        node,
        (
            ast.Constant,
            ast.Dict,
            ast.List,
            ast.Set,
            ast.Tuple,
            ast.Lambda,
            ast.AsyncFunctionDef,
            ast.FunctionDef,
            _ClassBinding,
            _FunctionBinding,
        ),
    ):
        return _irrelevant_provenance()
    if isinstance(node, _ImportBinding):
        return _irrelevant_provenance() if node.symbol is None else _unresolved_provenance()
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _qualified_expression_dependency_modules(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[str]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("expression-dependency", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    results = [
        _qualified_imported_modules(
            node,
            assignments,
            qualified_assignments,
        ),
        _qualified_namespace_modules(
            node,
            assignments,
            qualified_assignments,
        ),
    ]
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        results.append(
            _merge_provenance(
                _qualified_expression_dependency_modules(
                    candidate,
                    assignments,
                    qualified_assignments,
                    seen=seen,
                )
                for candidate in candidates
            )
            if candidates
            else _unresolved_provenance()
        )
    results.extend(
        _qualified_expression_dependency_modules(
            child,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        for child in ast.iter_child_nodes(node)
    )
    return _merge_provenance(results)


def _expression_depends_on_unknown_assignment(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    known_callable_names: frozenset[str] = frozenset(),
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if (
            node.id in known_callable_names
            and candidates
            and all(
                isinstance(candidate, (_ImportBinding, _UnknownBinding)) for candidate in candidates
            )
        ):
            return False
        if any(isinstance(candidate, _UnknownBinding) for candidate in candidates):
            return True
        if any(
            _expression_depends_on_unknown_assignment(
                candidate,
                assignments,
                qualified_assignments,
                known_callable_names=known_callable_names,
                seen=seen,
            )
            for candidate in candidates
        ):
            return True
    return any(
        _expression_depends_on_unknown_assignment(
            child,
            assignments,
            qualified_assignments,
            known_callable_names=known_callable_names,
            seen=seen,
        )
        for child in ast.iter_child_nodes(node)
    )


def _known_non_aliasing_default_value(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    known_callable_names: frozenset[str] = frozenset(),
    known_qualified_callables: frozenset[tuple[str, str]] = frozenset(),
    qualified_class_assignments: ExternalClassAssignments | None = None,
    inherited_module: str | None = None,
    seen: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    qualified_class_assignments = qualified_class_assignments or {}
    origin_module = getattr(
        node,
        ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
        inherited_module,
    )
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = (id(node), id(assignments))
    if marker in seen:
        return False
    seen = seen | {marker}

    def known(
        candidate: ast.AST,
        candidate_assignments: AssignmentMap = assignments,
        candidate_module: str | None = origin_module,
    ) -> bool:
        return _known_non_aliasing_default_value(
            candidate,
            candidate_assignments,
            qualified_assignments,
            known_callable_names=known_callable_names,
            known_qualified_callables=known_qualified_callables,
            qualified_class_assignments=qualified_class_assignments,
            inherited_module=candidate_module,
            seen=seen,
        )

    def qualified_values(
        expression: ast.AST,
    ) -> tuple[tuple[ast.AST, AssignmentMap, str], ...]:
        references = _qualified_assignment_references(
            expression,
            assignments,
            qualified_assignments,
        )
        if references.state is _ProvenanceState.UNRESOLVED:
            return ()
        resolved = tuple(
            (candidate, qualified_assignments.get(module, {}), module)
            for module, symbol in references.values
            for candidate in qualified_assignments.get(module, {}).get(symbol, ())
        )
        if resolved or not isinstance(expression, ast.Attribute):
            return resolved
        return tuple(
            (candidate, class_scope, owner.module)
            for owner, _owner_assignments, _owner_module in qualified_values(expression.value)
            if isinstance(owner, _ClassBinding)
            for class_scope in (qualified_class_assignments.get((owner.module, owner.symbol)),)
            if class_scope is not None
            for candidate in class_scope.get(expression.attr, ())
        )

    if isinstance(node, (ast.Constant, ast.Lambda)):
        return True
    if isinstance(node, _ClassBinding):
        return (node.module, node.symbol) in known_qualified_callables
    if isinstance(node, _FunctionBinding):
        return (node.module, node.symbol) in known_qualified_callables
    if isinstance(node, _ImportBinding):
        return (
            node.symbol is not None
            and (
                node.module,
                node.symbol,
            )
            in known_qualified_callables | KNOWN_EXTERNAL_CALLABLE_OBJECTS
        )
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if (
            (
                node.id in known_callable_names
                or (
                    origin_module is not None
                    and (origin_module, node.id) in known_qualified_callables
                )
            )
            and candidates
            and all(
                isinstance(candidate, (_ImportBinding, _UnknownBinding)) for candidate in candidates
            )
        ):
            return True
        return (
            bool(candidates)
            and not any(isinstance(candidate, _UnknownBinding) for candidate in candidates)
            and all(known(candidate) for candidate in candidates)
        )
    if isinstance(node, ast.Attribute):
        references = _qualified_assignment_references(
            node,
            assignments,
            qualified_assignments,
        )
        if _qualified_references_are_governed_callables(
            references,
            qualified_assignments,
            known_qualified_callables,
        ):
            return True
        qualified_candidates = qualified_values(node)
        return (
            bool(qualified_candidates)
            and not any(
                isinstance(candidate, _UnknownBinding)
                for candidate, _candidate_assignments, _candidate_module in qualified_candidates
            )
            and all(
                known(candidate, candidate_assignments, candidate_module)
                for candidate, candidate_assignments, candidate_module in qualified_candidates
            )
        )
    if isinstance(node, ast.Subscript):
        selected = _selected_reference_expression(node, assignments)
        if selected is not None:
            return known(selected)
        slices: list[ast.expr] = []
        qualified_base: ast.AST = node
        while isinstance(qualified_base, ast.Subscript):
            if not isinstance(qualified_base.slice, ast.expr):
                return False
            slices.append(qualified_base.slice)
            qualified_base = qualified_base.value
        qualified_containers = qualified_values(qualified_base)
        if not qualified_containers:
            return False
        for container, container_assignments, container_module in qualified_containers:
            selected_candidate: ast.AST | None = container
            for selected_slice in reversed(slices):
                if not isinstance(selected_candidate, ast.expr):
                    selected_candidate = None
                    break
                selected_candidate = _selected_reference_expression(
                    ast.Subscript(
                        value=selected_candidate,
                        slice=selected_slice,
                        ctx=ast.Load(),
                    ),
                    container_assignments,
                )
                if selected_candidate is None:
                    break
            if selected_candidate is None or not known(
                selected_candidate,
                container_assignments,
                container_module,
            ):
                return False
        return True
    if isinstance(node, ast.Call):
        if _known_non_aliasing_call(node, assignments):
            return True
        if not _known_builtin_container_expression(node, assignments):
            return (
                isinstance(node.func, ast.Name)
                and node.func.id == "object"
                and node.func.id not in assignments
                and not node.args
                and not node.keywords
            )
        return all(
            known(value) for value in (*node.args, *(keyword.value for keyword in node.keywords))
        )
    if isinstance(node, ast.Dict):
        return all(value is None or known(value) for value in (*node.keys, *node.values))
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return all(known(value) for value in node.elts)
    if isinstance(node, ast.IfExp):
        return known(node.body) and known(node.orelse)
    if isinstance(node, ast.BoolOp):
        return all(known(value) for value in node.values)
    if isinstance(node, ast.BinOp):
        return known(node.left) and known(node.right)
    if isinstance(node, ast.UnaryOp):
        return known(node.operand)
    if isinstance(node, ast.Compare):
        return known(node.left) and all(known(value) for value in node.comparators)
    if isinstance(node, ast.NamedExpr):
        return known(node.value)
    if isinstance(node, ast.Starred):
        return known(node.value)
    return isinstance(node, (ast.FormattedValue, ast.JoinedStr))


def _qualified_reference_provenance(
    modules: _Provenance[str],
    symbols: _Provenance[str],
    qualified_assignments: dict[str, AssignmentMap],
) -> _Provenance[tuple[str, str]]:
    if modules.state is _ProvenanceState.IRRELEVANT or symbols.state is _ProvenanceState.IRRELEVANT:
        return _irrelevant_provenance()
    references = {(module, symbol) for module in modules.values for symbol in symbols.values}
    if (
        modules.state is _ProvenanceState.UNRESOLVED
        or symbols.state is _ProvenanceState.UNRESOLVED
        or any(
            module not in qualified_assignments or symbol not in qualified_assignments[module]
            for module, symbol in references
        )
    ):
        return _unresolved_provenance(references)
    return _known_provenance(references)


def _qualified_references_are_governed_callables(
    references: _Provenance[tuple[str, str]],
    qualified_assignments: dict[str, AssignmentMap],
    known_qualified_callables: frozenset[tuple[str, str]],
) -> bool:
    return (
        references.state is not _ProvenanceState.IRRELEVANT
        and bool(references.values)
        and references.values <= known_qualified_callables | KNOWN_EXTERNAL_CALLABLE_OBJECTS
        and all(
            module not in qualified_assignments
            or (
                bool(qualified_assignments[module].get(symbol, ()))
                and all(
                    isinstance(candidate, (_ImportBinding, _UnknownBinding))
                    for candidate in qualified_assignments[module].get(symbol, ())
                )
            )
            for module, symbol in references.values
        )
    )


def _qualified_assignment_references(
    node: ast.AST,
    assignments: AssignmentMap,
    qualified_assignments: dict[str, AssignmentMap],
    *,
    seen: frozenset[tuple[str, int, int]] = frozenset(),
) -> _Provenance[tuple[str, str]]:
    assignments = _assignment_origin_scope(node, assignments, qualified_assignments)
    marker = ("assignment-reference", id(node), id(assignments))
    if marker in seen:
        return _unresolved_provenance()
    seen = seen | {marker}
    if isinstance(node, ast.Attribute):
        return _qualified_reference_provenance(
            _qualified_imported_modules(
                node.value,
                assignments,
                qualified_assignments,
            ),
            _known_provenance((node.attr,)),
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) in {2, 3}
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "getattr",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_reference_provenance(
            _qualified_imported_modules(
                node.args[0],
                assignments,
                qualified_assignments,
            ),
            _qualified_static_string_values(
                node.args[1],
                assignments,
                qualified_assignments,
            ),
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 2
        and not node.keywords
        and _exact_assignment_accessor(
            node.func,
            "operator",
            "getitem",
            assignments,
            qualified_assignments,
        )
    ):
        return _qualified_reference_provenance(
            _qualified_namespace_modules(
                node.args[0],
                assignments,
                qualified_assignments,
            ),
            _qualified_static_string_values(
                node.args[1],
                assignments,
                qualified_assignments,
            ),
            qualified_assignments,
        )
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _exact_builtin_assignment_accessor(
            node.func,
            "next",
            assignments,
            qualified_assignments,
        )
        and isinstance(node.args[0], ast.GeneratorExp)
        and len(node.args[0].generators) == 1
    ):
        generator_expression = node.args[0]
        generator = generator_expression.generators[0]
        target = generator.target
        if (
            isinstance(target, (ast.List, ast.Tuple))
            and len(target.elts) == 2
            and all(isinstance(item, ast.Name) for item in target.elts)
            and isinstance(generator_expression.elt, ast.Name)
            and generator_expression.elt.id == target.elts[1].id
        ):
            key_name = target.elts[0].id
            selected_names = {
                comparison.comparators[0].value
                for comparison in generator.ifs
                if isinstance(comparison, ast.Compare)
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.Eq)
                and len(comparison.comparators) == 1
                and isinstance(comparison.left, ast.Name)
                and comparison.left.id == key_name
                and isinstance(comparison.comparators[0], ast.Constant)
                and isinstance(comparison.comparators[0].value, str)
            }
            return _qualified_reference_provenance(
                _qualified_namespace_modules(
                    generator.iter,
                    assignments,
                    qualified_assignments,
                ),
                _known_provenance(selected_names),
                qualified_assignments,
            )
    if isinstance(node, ast.Subscript):
        selected = _qualified_selected_reference_expressions(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        selected_references = _merge_provenance(
            _qualified_assignment_references(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in selected.values
        )
        if selected.state is _ProvenanceState.KNOWN:
            return selected_references
        namespace_reference = _qualified_reference_provenance(
            _qualified_namespace_modules(
                node.value,
                assignments,
                qualified_assignments,
            ),
            _qualified_static_string_values(
                node.slice,
                assignments,
                qualified_assignments,
            ),
            qualified_assignments,
        )
        if namespace_reference.state is not _ProvenanceState.IRRELEVANT:
            return namespace_reference
        return (
            _unresolved_provenance(selected_references.values)
            if selected.state is _ProvenanceState.UNRESOLVED
            else selected_references
        )
    if isinstance(node, ast.Call) and len(node.args) in {1, 2} and not node.keywords:
        getter_reference = _qualified_reference_provenance(
            _qualified_namespace_getters(
                node.func,
                assignments,
                qualified_assignments,
            ),
            _qualified_static_string_values(
                node.args[0],
                assignments,
                qualified_assignments,
            ),
            qualified_assignments,
        )
        if getter_reference.state is not _ProvenanceState.IRRELEVANT:
            return getter_reference
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _unresolved_provenance()
        return _merge_provenance(
            _qualified_assignment_references(
                candidate,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for candidate in candidates
        )
    if isinstance(node, ast.IfExp):
        branches = (node.body, node.orelse)
    elif isinstance(node, ast.BoolOp):
        branches = tuple(node.values)
    elif isinstance(node, ast.NamedExpr):
        branches = (node.value,)
    else:
        branches = ()
    if branches:
        return _merge_provenance(
            _qualified_assignment_references(
                branch,
                assignments,
                qualified_assignments,
                seen=seen,
            )
            for branch in branches
        )
    if isinstance(node, ast.Call):
        returned = _closed_call_returns(
            node,
            assignments,
            qualified_assignments,
            seen=seen,
        )
        result = _merge_provenance(
            _qualified_assignment_references(
                value,
                value_assignments,
                qualified_assignments,
                seen=seen,
            )
            for value, value_assignments, _module in returned.values
        )
        return (
            _unresolved_provenance(result.values)
            if returned.state is _ProvenanceState.UNRESOLVED
            else result
        )
    if isinstance(
        node,
        (
            ast.AsyncFunctionDef,
            ast.Constant,
            ast.Dict,
            ast.FunctionDef,
            ast.Lambda,
            ast.List,
            ast.Set,
            ast.Tuple,
            _ClassBinding,
            _FunctionBinding,
        ),
    ):
        return _irrelevant_provenance()
    if isinstance(node, _ImportBinding):
        return (
            _irrelevant_provenance()
            if node.symbol is None
            else _unresolved_provenance(((node.module, node.symbol),))
        )
    if not isinstance(node, ast.expr):
        return _irrelevant_provenance()
    return _unresolved_provenance()


def _origin_expression_aliases(
    node: ast.expr,
    assignments: AssignmentMap,
    origin_assignments: AssignmentMap,
    identity_aliases: dict[int, set[str]] | None = None,
    qualified_origin_assignments: dict[str, AssignmentMap] | None = None,
    known_callable_names: frozenset[str] = frozenset(),
    known_qualified_callables: frozenset[tuple[str, str]] = frozenset(),
    qualified_class_assignments: ExternalClassAssignments | None = None,
) -> set[str]:
    if qualified_origin_assignments is not None:
        origin_assignments = _assignment_origin_scope(
            node,
            origin_assignments,
            qualified_origin_assignments,
        )
        if _expression_depends_on_unknown_assignment(
            node,
            origin_assignments,
            qualified_origin_assignments,
            known_callable_names=known_callable_names,
        ):
            _fail(
                "mutated omitted function default depends on an unresolved assignment: "
                f"{ast.unparse(node)}"
            )
    resolved = _snapshot_bound_expression(node, origin_assignments)
    matched = _origin_candidate_aliases(
        (resolved,),
        assignments,
        identity_aliases,
        follow_contents=True,
    )
    origin_names = _possible_returned_reference_roots(node, origin_assignments)
    for origin_name in origin_names:
        matched.update(
            _origin_binding_aliases(
                origin_name,
                assignments,
                origin_assignments,
                identity_aliases,
                follow_contents=True,
            )
        )
    qualified_expressions = [node, resolved]
    qualified_expressions.extend(
        candidate
        for origin_name in origin_names
        for candidate in origin_assignments.get(origin_name, ())
        if isinstance(candidate, ast.AST)
    )
    if qualified_origin_assignments is None:
        return matched
    pending = [(expression, origin_assignments) for expression in qualified_expressions]
    seen_qualified: set[tuple[int, int]] = set()
    while pending:
        expression, inherited_scope = pending.pop()
        expression_scope = _assignment_origin_scope(
            expression,
            inherited_scope,
            qualified_origin_assignments,
        )
        marker = (id(expression), id(expression_scope))
        if marker in seen_qualified:
            continue
        seen_qualified.add(marker)
        for candidate in ast.walk(expression):
            candidate_scope = _assignment_origin_scope(
                candidate,
                expression_scope,
                qualified_origin_assignments,
            )
            references = _qualified_assignment_references(
                candidate,
                candidate_scope,
                qualified_origin_assignments,
            )
            if references.state is _ProvenanceState.UNRESOLVED and not (
                _qualified_references_are_governed_callables(
                    references,
                    qualified_origin_assignments,
                    known_qualified_callables,
                )
            ):
                _fail(
                    "mutated omitted function default has unresolved qualified "
                    f"provenance: {ast.unparse(candidate)}"
                )
            for imported_module, symbol in references.values:
                imported_scope = qualified_origin_assignments.get(imported_module, {})
                imported_candidates = imported_scope.get(symbol, ())
                matched.update(
                    _origin_candidate_aliases(
                        imported_candidates,
                        assignments,
                        identity_aliases,
                        follow_contents=True,
                    )
                )
                pending.extend(
                    (imported_candidate, imported_scope)
                    for imported_candidate in imported_candidates
                    if isinstance(imported_candidate, ast.AST)
                )
            if isinstance(candidate, ast.Call) and references.state is _ProvenanceState.IRRELEVANT:
                dependencies = _merge_provenance(
                    _qualified_expression_dependency_modules(
                        argument,
                        candidate_scope,
                        qualified_origin_assignments,
                    )
                    for argument in (
                        candidate.func,
                        *candidate.args,
                        *(keyword.value for keyword in candidate.keywords),
                    )
                )
                dependent_modules = dependencies.conservative(qualified_origin_assignments)
                for dependent_module in dependent_modules:
                    dependent_scope = qualified_origin_assignments.get(dependent_module, {})
                    for imported_candidates in dependent_scope.values():
                        matched.update(
                            _origin_candidate_aliases(
                                imported_candidates,
                                assignments,
                                identity_aliases,
                                follow_contents=True,
                            )
                        )
                        pending.extend(
                            (imported_candidate, dependent_scope)
                            for imported_candidate in imported_candidates
                            if isinstance(imported_candidate, ast.AST)
                        )
    if not _known_non_aliasing_default_value(
        node,
        origin_assignments,
        qualified_origin_assignments,
        known_callable_names=known_callable_names,
        known_qualified_callables=known_qualified_callables,
        qualified_class_assignments=qualified_class_assignments,
    ):
        _fail(
            f"mutated omitted function default cannot be proven non-aliasing: {ast.unparse(node)}"
        )
    return matched


def _mutated_function_free_bindings(
    function: FunctionContext,
    *,
    seen: frozenset[int] = frozenset(),
) -> set[str]:
    if function.mutated_free_bindings is not None:
        return set(function.mutated_free_bindings)
    marker = id(function.node)
    if marker in seen:
        return set()
    if function.direct_mutated_free_bindings is None:
        function.direct_mutated_free_bindings = frozenset(
            _mutated_free_bindings(
                function.node,
                function.module_assignments,
                qualified_assignments=function.qualified_assignments,
            )
        )
    mutated = set(function.direct_mutated_free_bindings)
    identity_aliases: dict[int, set[str]] | None = None
    for node in _lexical_nodes(function.node):
        if not isinstance(node, ast.Call):
            continue
        called: FunctionContext | None = None
        if isinstance(node.func, ast.Name):
            called = function.functions.get(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            imported_module = _imported_module_expression(
                node.func.value, function.module_assignments
            )
            if imported_module is not None:
                called = function.qualified_functions.get((imported_module, node.func.attr))
        if called is None:
            continue
        for captured_root in _mutated_function_free_bindings(
            called,
            seen=seen | {marker},
        ):
            if identity_aliases is None:
                identity_aliases = _assignment_identity_aliases(function.module_assignments)
            mutated.update(
                _origin_binding_aliases(
                    captured_root,
                    function.module_assignments,
                    called.module_assignments,
                    identity_aliases,
                )
            )
        bound = _bound_call_arguments(node, called)
        if bound is not None:
            for parameter_name in _mutated_function_parameters(called):
                actual = bound.get(parameter_name)
                if actual is None:
                    continue
                value, from_caller = actual
                if from_caller:
                    mutated.update(_reachable_assignment_roots(value, function.module_assignments))
                else:
                    if identity_aliases is None:
                        identity_aliases = _assignment_identity_aliases(function.module_assignments)
                    mutated.update(
                        _origin_expression_aliases(
                            value,
                            function.module_assignments,
                            called.default_assignments,
                            identity_aliases,
                            called.qualified_assignments,
                            frozenset(called.functions) | frozenset(called.classes),
                            frozenset(called.qualified_functions)
                            | frozenset(called.qualified_classes),
                            called.qualified_class_assignments,
                        )
                    )
    if not seen:
        function.mutated_free_bindings = frozenset(mutated)
    return mutated


def _apply_helper_mutations(
    scope: ast.AST,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    *,
    qualified_functions: ExternalFunctions | None = None,
    qualified_assignments: dict[str, AssignmentMap] | None = None,
) -> None:
    qualified_functions = qualified_functions or {}
    qualified_assignments = qualified_assignments or {}
    contexts_by_node = {
        id(context.node): context
        for context in (*functions.values(), *qualified_functions.values())
    }
    identity_aliases: dict[int, set[str]] | None = None
    for node in _lexical_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        resolved_calls: list[tuple[FunctionContext, ast.Call]] = []
        if isinstance(node.func, ast.Name):
            function = functions.get(node.func.id)
            if function is not None:
                resolved_calls.append((function, node))
        elif isinstance(node.func, ast.Attribute):
            imported_module = _imported_module_expression(node.func.value, assignments)
            if imported_module is not None:
                function = qualified_functions.get((imported_module, node.func.attr))
                if function is not None:
                    resolved_calls.append((function, node))
        if qualified_assignments:
            provenance = _qualified_callable_provenance(
                node.func,
                assignments,
                qualified_assignments,
            )
            for called, _module, implicit_positional_count in provenance.values:
                function = contexts_by_node.get(id(called))
                if function is None or any(
                    existing is function for existing, _call in resolved_calls
                ):
                    continue
                expanded = (
                    node
                    if not implicit_positional_count
                    else ast.Call(
                        func=node.func,
                        args=[
                            *(ast.Constant(value=None) for _ in range(implicit_positional_count)),
                            *node.args,
                        ],
                        keywords=node.keywords,
                    )
                )
                resolved_calls.append((function, expanded))
        for function, resolved_call in resolved_calls:
            bound = _bound_call_arguments(resolved_call, function)
            if bound is None:
                continue
            for captured_root in _mutated_function_free_bindings(function):
                if identity_aliases is None:
                    identity_aliases = _assignment_identity_aliases(assignments)
                for alias in _origin_binding_aliases(
                    captured_root,
                    assignments,
                    function.module_assignments,
                    identity_aliases,
                ):
                    candidates = assignments.get(alias, ())
                    if not any(isinstance(candidate, _UnknownBinding) for candidate in candidates):
                        assignments[alias] = (*candidates, _UnknownBinding())
            for name in _mutated_function_parameters(function):
                actual = bound.get(name)
                if actual is None:
                    continue
                value, from_caller = actual
                if not from_caller and identity_aliases is None:
                    identity_aliases = _assignment_identity_aliases(assignments)
                aliases = (
                    {
                        alias
                        for root_name in _reachable_assignment_roots(
                            value,
                            assignments,
                            follow_identity=True,
                        )
                        for alias in _current_alias_component(root_name, assignments)
                    }
                    if from_caller
                    else _origin_expression_aliases(
                        value,
                        assignments,
                        function.default_assignments,
                        identity_aliases,
                        function.qualified_assignments,
                        frozenset(function.functions) | frozenset(function.classes),
                        frozenset(function.qualified_functions)
                        | frozenset(function.qualified_classes),
                        function.qualified_class_assignments,
                    )
                )
                for alias in aliases:
                    candidates = assignments.get(alias, ())
                    if not any(isinstance(candidate, _UnknownBinding) for candidate in candidates):
                        assignments[alias] = (*candidates, _UnknownBinding())


def _manifest_expression_shape(
    node: ast.AST,
    assignments: AssignmentMap,
    functions: dict[str, FunctionContext],
    *,
    classes: ClassFields | None = None,
    parameters: dict[str, ast.AST] | None = None,
    source: str | None = None,
    seen: frozenset[str] = frozenset(),
    seen_functions: frozenset[str] = frozenset(),
) -> _ManifestShape:
    parameters = parameters or {}
    classes = classes or {}
    if _checksum_pinned_manifest_leaf(source, node):
        return _ManifestShape.LEAF
    if _checksum_pinned_manifest_subtree(source, node) is not None:
        return _ManifestShape.KEYS
    if isinstance(node, ast.Dict):
        return _ManifestShape.KEYS
    if isinstance(node, ast.DictComp):
        return _ManifestShape.UNKNOWN
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return _merge_manifest_shapes(
            iter(
                _manifest_expression_shape(
                    value.value if isinstance(value, ast.Starred) else value,
                    assignments,
                    functions,
                    classes=classes,
                    parameters=parameters,
                    source=source,
                    seen=seen,
                    seen_functions=seen_functions,
                )
                for value in node.elts
            )
        )
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        scoped = _comprehension_assignments(node.generators, assignments)
        return _manifest_expression_shape(
            node.elt,
            scoped,
            functions,
            classes=classes,
            parameters=parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.Starred):
        return _manifest_expression_shape(
            node.value,
            assignments,
            functions,
            classes=classes,
            parameters=parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.IfExp):
        return _merge_manifest_shapes(
            iter(
                _manifest_expression_shape(
                    branch,
                    assignments,
                    functions,
                    classes=classes,
                    parameters=parameters,
                    source=source,
                    seen=seen,
                    seen_functions=seen_functions,
                )
                for branch in (node.body, node.orelse)
            )
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _merge_manifest_shapes(
            iter(
                _manifest_expression_shape(
                    operand,
                    assignments,
                    functions,
                    classes=classes,
                    parameters=parameters,
                    source=source,
                    seen=seen,
                    seen_functions=seen_functions,
                )
                for operand in (node.left, node.right)
            )
        )
    if isinstance(node, (ast.BinOp, ast.BoolOp)):
        values = (node.left, node.right) if isinstance(node, ast.BinOp) else tuple(node.values)
        shape = _merge_manifest_shapes(
            iter(
                _manifest_expression_shape(
                    value,
                    assignments,
                    functions,
                    classes=classes,
                    parameters=parameters,
                    source=source,
                    seen=seen,
                    seen_functions=seen_functions,
                )
                for value in values
            )
        )
        return _ManifestShape.LEAF if shape is _ManifestShape.LEAF else _ManifestShape.UNKNOWN
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if not candidates:
            return _annotation_shape(
                parameters.get(node.id),
                assignments,
                functions,
                classes,
                parameters,
            )
        if node.id in seen:
            return _ManifestShape.UNKNOWN
        shapes = tuple(
            _manifest_expression_shape(
                candidate,
                assignments,
                functions,
                classes=classes,
                parameters=parameters,
                source=source,
                seen=seen | {node.id},
                seen_functions=seen_functions,
            )
            for candidate in candidates
        )
        if len(candidates) > 1 and any(shape is not _ManifestShape.LEAF for shape in shapes):
            return _ManifestShape.UNKNOWN
        return _merge_manifest_shapes(iter(shapes))
    if isinstance(node, ast.Subscript):
        selected = _selected_manifest_expression(node, assignments)
        if selected is None:
            return _annotation_shape(
                _expression_annotation(
                    node,
                    assignments,
                    functions,
                    classes,
                    parameters,
                    seen=seen,
                ),
                assignments,
                functions,
                classes,
                parameters,
            )
        selected_node, selected_assignments = selected
        return _manifest_expression_shape(
            selected_node,
            selected_assignments,
            functions,
            classes=classes,
            parameters=parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.Attribute):
        return _annotation_shape(
            _expression_annotation(
                node,
                assignments,
                functions,
                classes,
                parameters,
                seen=seen,
            ),
            assignments,
            functions,
            classes,
            parameters,
        )
    if isinstance(node, (ast.Constant, ast.JoinedStr, ast.UnaryOp, ast.Compare)):
        return _ManifestShape.LEAF
    if isinstance(node, ast.NamedExpr):
        return _manifest_expression_shape(
            node.value,
            assignments,
            functions,
            classes=classes,
            parameters=parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
    if not isinstance(node, ast.Call):
        return _ManifestShape.UNKNOWN
    name = node.func.id if isinstance(node.func, ast.Name) else None
    if name in {
        "bool",
        "float",
        "int",
        "len",
        "str",
    } and _unshadowed_builtin(name, assignments, functions, classes, parameters):
        return _ManifestShape.LEAF
    if (
        name == "Path"
        and not node.keywords
        and not any(isinstance(argument, ast.Starred) for argument in node.args)
        and _exact_imported_symbol(
            name,
            "pathlib",
            "Path",
            assignments,
            functions,
            classes,
            parameters,
        )
    ):
        return _ManifestShape.LEAF
    if (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "hexdigest"
        and not node.args
        and not node.keywords
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Attribute)
        and isinstance(node.func.value.func.value, ast.Name)
        and node.func.value.func.attr == "sha256"
        and _exact_imported_module(
            node.func.value.func.value.id,
            "hashlib",
            assignments,
            functions,
            classes,
            parameters,
        )
    ):
        return _ManifestShape.LEAF
    if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        value_annotation = _subscript_result_annotation(
            _expression_annotation(
                node.func.value,
                assignments,
                functions,
                classes,
                parameters,
                seen=seen,
            )
        )
        get_shapes = [
            _annotation_shape(
                value_annotation,
                assignments,
                functions,
                classes,
                parameters,
            )
        ]
        get_shapes.extend(
            _manifest_expression_shape(
                argument,
                assignments,
                functions,
                classes=classes,
                parameters=parameters,
                source=source,
                seen=seen,
                seen_functions=seen_functions,
            )
            for argument in node.args[1:]
        )
        return (
            _ManifestShape.LEAF
            if len(node.args) in {1, 2}
            and not node.keywords
            and all(shape is _ManifestShape.LEAF for shape in get_shapes)
            else _ManifestShape.UNKNOWN
        )
    if name in {"frozenset", "list", "set", "tuple"} and _unshadowed_builtin(
        name, assignments, functions, classes, parameters
    ):
        if len(node.args) != 1 or node.keywords:
            return (
                _ManifestShape.LEAF
                if not node.args and not node.keywords
                else _ManifestShape.UNKNOWN
            )
        argument_shape = _manifest_expression_shape(
            node.args[0],
            assignments,
            functions,
            classes=classes,
            parameters=parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
        return (
            _ManifestShape.LEAF if argument_shape is _ManifestShape.LEAF else _ManifestShape.UNKNOWN
        )
    if name == "dict" and _unshadowed_builtin(name, assignments, functions, classes, parameters):
        if len(node.args) > 1:
            return _ManifestShape.UNKNOWN
        if node.args:
            argument_shape = _manifest_expression_shape(
                node.args[0],
                assignments,
                functions,
                classes=classes,
                parameters=parameters,
                source=source,
                seen=seen,
                seen_functions=seen_functions,
            )
            if argument_shape is not _ManifestShape.KEYS:
                return _ManifestShape.UNKNOWN
        if any(keyword.arg is None for keyword in node.keywords):
            return _ManifestShape.UNKNOWN
        return _ManifestShape.KEYS
    if name is None or name not in functions:
        return _ManifestShape.UNKNOWN
    function = functions[name]
    function_id = f"{function.source}:{function.node.name}"
    if function_id in seen_functions:
        return _ManifestShape.UNKNOWN
    helper_context = _helper_call_context(
        node,
        function,
        assignments,
        functions,
        classes,
        parameters,
        source=source,
        seen=seen,
        seen_functions=seen_functions,
    )
    if helper_context is None:
        return _ManifestShape.UNKNOWN
    helper_assignments, helper_parameters = helper_context
    return _merge_manifest_shapes(
        iter(
            _manifest_expression_shape(
                return_value,
                helper_assignments,
                function.functions,
                classes=function.classes,
                parameters=helper_parameters,
                source=function.source,
                seen=seen,
                seen_functions=seen_functions | {function_id},
            )
            for return_value in _return_values(function.node, source=f"helper {name}")
        )
    )


def _import_from_module(module: PythonModule, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = module.module.split(".")
    if PurePosixPath(module.path).name != "__init__.py":
        package.pop()
    ascend = node.level - 1
    if ascend > len(package):
        return None
    if ascend:
        package = package[:-ascend]
    if node.module:
        package.extend(node.module.split("."))
    return ".".join(package) or None


def _resolve_dict_expression(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    source: str,
    functions: dict[str, FunctionContext],
    classes: ClassFields | None = None,
    parameters: dict[str, ast.AST] | None = None,
    seen: frozenset[str] = frozenset(),
    seen_functions: frozenset[str] = frozenset(),
) -> set[str]:
    parameters = parameters or {}
    classes = classes or {}
    pinned_subtree = _checksum_pinned_manifest_subtree(source, node)
    if pinned_subtree is not None:
        return set(pinned_subtree)
    if isinstance(node, ast.Name):
        candidates = assignments.get(node.id, ())
        if node.id in seen or not candidates:
            _fail(f"dynamic manifest mapping is forbidden in {source}: {node.id}")
        if len(candidates) != 1:
            _fail(f"manifest mapping assignment is ambiguous in {source}: {node.id}")
        return _resolve_dict_expression(
            candidates[0],
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen | {node.id},
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.Subscript):
        selected = _selected_manifest_expression(node, assignments)
        if selected is None:
            _fail(f"dynamic manifest mapping subscript is forbidden in {source}")
        selected_node, selected_assignments = selected
        return _resolve_dict_expression(
            selected_node,
            selected_assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen | ({node.value.id} if isinstance(node.value, ast.Name) else set()),
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name == "dict" and _unshadowed_builtin(
            name,
            assignments,
            functions,
            classes,
            parameters,
        ):
            if len(node.args) > 1 or any(keyword.arg is None for keyword in node.keywords):
                _fail(f"dynamic manifest mapping is forbidden in {source}")
            result = (
                _resolve_manifest_children(
                    node.args[0],
                    assignments,
                    source=source,
                    functions=functions,
                    classes=classes,
                    parameters=parameters,
                    seen=seen,
                    seen_functions=seen_functions,
                )
                if node.args
                else set()
            )
            for keyword in node.keywords:
                if keyword.arg is None:
                    _fail(f"dynamic manifest mapping is forbidden in {source}")
                token = f"/{_pointer_token(keyword.arg)}"
                result.add(token)
                for child in _resolve_manifest_children(
                    keyword.value,
                    assignments,
                    source=source,
                    functions=functions,
                    classes=classes,
                    parameters=parameters,
                    seen=seen,
                    seen_functions=seen_functions,
                ):
                    result.add(f"{token}{child}")
            return result
        if name is None or name not in functions:
            _fail(f"dynamic manifest mapping is forbidden in {source}")
        function = functions[name]
        function_id = f"{function.source}:{function.node.name}"
        if function_id in seen_functions:
            _fail(f"recursive manifest helper is forbidden in {source}: {name}")
        helper_context = _helper_call_context(
            node,
            function,
            assignments,
            functions,
            classes,
            parameters,
            source=source,
            seen=seen,
            seen_functions=seen_functions,
        )
        if helper_context is None:
            _fail(f"manifest helper arguments are not closed in {source}: {name}")
        helper_assignments, helper_parameters = helper_context
        helper_result: set[str] = set()
        for return_value in _return_values(
            function.node, source=f"{function.source}: helper {name}"
        ):
            helper_result.update(
                _resolve_manifest_children(
                    return_value,
                    helper_assignments,
                    source=function.source,
                    functions=function.functions,
                    classes=function.classes,
                    parameters=helper_parameters,
                    seen=seen,
                    seen_functions=seen_functions | {function_id},
                )
            )
        return helper_result
    if isinstance(node, ast.IfExp):
        return _resolve_manifest_children(
            node.body,
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen,
            seen_functions=seen_functions,
        ) | _resolve_manifest_children(
            node.orelse,
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _resolve_manifest_children(
            node.left,
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen,
            seen_functions=seen_functions,
        ) | _resolve_manifest_children(
            node.right,
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen,
            seen_functions=seen_functions,
        )
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        sequence_result: set[str] = set()
        for value in node.elts:
            candidate = value.value if isinstance(value, ast.Starred) else value
            children = _resolve_manifest_children(
                candidate,
                assignments,
                source=source,
                functions=functions,
                classes=classes,
                parameters=parameters,
                seen=seen,
                seen_functions=seen_functions,
            )
            if isinstance(value, ast.Starred):
                sequence_result.update(children)
            else:
                sequence_result.update(f"/*{child}" for child in children)
        return sequence_result
    if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
        scoped = _comprehension_assignments(node.generators, assignments)
        return {
            f"/*{child}"
            for child in _resolve_manifest_children(
                node.elt,
                scoped,
                source=source,
                functions=functions,
                classes=classes,
                parameters=parameters,
                seen=seen,
                seen_functions=seen_functions,
            )
        }
    if isinstance(node, ast.DictComp):
        _fail(f"dynamic manifest mapping is forbidden in {source}")
    if not isinstance(node, ast.Dict):
        _fail(f"dynamic manifest mapping is forbidden in {source}")
    mapping_result: set[str] = set()
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            mapping_result.update(
                _resolve_dict_expression(
                    value,
                    assignments,
                    source=source,
                    functions=functions,
                    classes=classes,
                    parameters=parameters,
                    seen=seen,
                    seen_functions=seen_functions,
                )
            )
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str) or not key.value:
            _fail(f"manifest keys must be non-empty literal strings in {source}")
        token = f"/{_pointer_token(key.value)}"
        mapping_result.add(token)
        for child in _resolve_manifest_children(
            value,
            assignments,
            source=source,
            functions=functions,
            classes=classes,
            parameters=parameters,
            seen=seen,
            seen_functions=seen_functions,
        ):
            mapping_result.add(f"{token}{child}")
    return mapping_result


def _resolve_manifest_children(
    node: ast.AST,
    assignments: AssignmentMap,
    *,
    source: str,
    functions: dict[str, FunctionContext],
    classes: ClassFields | None = None,
    parameters: dict[str, ast.AST] | None = None,
    seen: frozenset[str] = frozenset(),
    seen_functions: frozenset[str] = frozenset(),
) -> set[str]:
    classes = classes or {}
    pinned_subtree = _checksum_pinned_manifest_subtree(source, node)
    if pinned_subtree is not None:
        return set(pinned_subtree)
    shape = _manifest_expression_shape(
        node,
        assignments,
        functions,
        classes=classes,
        parameters=parameters,
        source=source,
        seen=seen,
        seen_functions=seen_functions,
    )
    if shape is _ManifestShape.LEAF:
        return set()
    if shape is _ManifestShape.UNKNOWN:
        expression = ast.unparse(node)
        _fail(f"unresolved nested manifest value is forbidden in {source}: {expression[:160]}")
    return _resolve_dict_expression(
        node,
        assignments,
        source=source,
        functions=functions,
        classes=classes,
        parameters=parameters,
        seen=seen,
        seen_functions=seen_functions,
    )


def _statement_bound_names(statement: ast.stmt) -> set[str]:
    names: set[str] = set()

    def collect(node: ast.AST) -> None:
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
            names.add(node.name)
            return
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
            return
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
            return
        if isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.add(node.name)
        if isinstance(node, ast.MatchAs) and node.name is not None:
            names.add(node.name)
        if isinstance(node, ast.MatchStar) and node.name is not None:
            names.add(node.name)
        if isinstance(node, ast.MatchMapping) and node.rest is not None:
            names.add(node.rest)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        for child in ast.iter_child_nodes(node):
            collect(child)

    collect(statement)
    return names


def _function_bindings(
    module: PythonModule, external_functions: ExternalFunctions
) -> dict[str, FunctionContext]:
    functions: dict[str, FunctionContext] = {}
    for node in module.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = external_functions[(module.module, node.name)]
            continue
        if isinstance(node, ast.ImportFrom):
            imported_module = _import_from_module(module, node)
            if any(alias.name == "*" for alias in node.names):
                functions.clear()
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                imported = (
                    external_functions.get((imported_module, alias.name))
                    if imported_module is not None
                    else None
                )
                if imported is None:
                    functions.pop(local_name, None)
                else:
                    functions[local_name] = imported
            continue
        for name in _statement_bound_names(node):
            functions.pop(name, None)
    return functions


def _module_assignment_registry(
    modules: tuple[PythonModule, ...],
) -> dict[str, AssignmentMap]:
    modules_by_name = {module.module: module for module in modules}
    function_bindings_cache: dict[str, dict[str, tuple[FunctionNode, str]]] = {}
    class_bindings_cache: dict[str, dict[str, tuple[ast.ClassDef, str]]] = {}
    function_origins = {
        id(node): module.module
        for module in modules
        for node in module.tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    class_origins = {
        id(node): module.module
        for module in modules
        for node in module.tree.body
        if isinstance(node, ast.ClassDef)
    }
    qualified_function_nodes = {
        (module.module, node.name): node
        for module in modules
        for node in module.tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    resolved: dict[str, AssignmentMap] = {}
    resolving: dict[str, AssignmentMap] = {}
    invalidated_class_identities: set[tuple[str, str]] = set()

    def static_function_bindings(
        module_name: str,
        seen: frozenset[str] = frozenset(),
    ) -> dict[str, tuple[FunctionNode, str]]:
        if module_name in function_bindings_cache:
            return function_bindings_cache[module_name]
        module = modules_by_name.get(module_name)
        if module is None or module_name in seen:
            return {}
        bindings: dict[str, tuple[FunctionNode, str]] = {}
        for statement in module.tree.body:
            if isinstance(statement, (ast.AsyncFunctionDef, ast.FunctionDef)):
                bindings[statement.name] = (statement, module_name)
                continue
            if isinstance(statement, ast.ImportFrom):
                imported_module = _import_from_module(module, statement)
                if any(alias.name == "*" for alias in statement.names):
                    bindings.clear()
                    continue
                imported = static_function_bindings(
                    imported_module or "",
                    seen | {module_name},
                )
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    binding = imported.get(alias.name)
                    if binding is None:
                        bindings.pop(local_name, None)
                    else:
                        bindings[local_name] = binding
                continue
            for name in _statement_bound_names(statement):
                bindings.pop(name, None)
        function_bindings_cache[module_name] = bindings
        return bindings

    def static_class_bindings(
        module_name: str,
        seen: frozenset[str] = frozenset(),
    ) -> dict[str, tuple[ast.ClassDef, str]]:
        if module_name in class_bindings_cache:
            return class_bindings_cache[module_name]
        module = modules_by_name.get(module_name)
        if module is None or module_name in seen:
            return {}
        bindings: dict[str, tuple[ast.ClassDef, str]] = {}

        def resolve_alias(value: ast.AST) -> tuple[ast.ClassDef, str] | None:
            if isinstance(value, ast.Name):
                return bindings.get(value.id)
            if isinstance(value, ast.Subscript):
                selected = _selected_reference_expression(value, {})
                return resolve_alias(selected) if selected is not None else None
            if isinstance(value, (ast.BoolOp, ast.IfExp)):
                return next(
                    (
                        resolved_alias
                        for child in ast.iter_child_nodes(value)
                        for resolved_alias in (resolve_alias(child),)
                        if resolved_alias is not None
                    ),
                    None,
                )
            return None

        for statement in module.tree.body:
            if isinstance(statement, ast.ClassDef):
                bindings[statement.name] = (statement, module_name)
                continue
            if isinstance(statement, ast.ImportFrom):
                imported_module = _import_from_module(module, statement)
                if any(alias.name == "*" for alias in statement.names):
                    bindings.clear()
                    continue
                imported = static_class_bindings(
                    imported_module or "",
                    seen | {module_name},
                )
                for alias in statement.names:
                    local_name = alias.asname or alias.name
                    binding = imported.get(alias.name)
                    if binding is None:
                        bindings.pop(local_name, None)
                    else:
                        bindings[local_name] = binding
                continue
            if isinstance(statement, ast.Assign):
                binding = resolve_alias(statement.value)
                for target in statement.targets:
                    for name in _assigned_names(target):
                        if binding is None:
                            bindings.pop(name, None)
                        else:
                            bindings[name] = binding
                continue
            if isinstance(statement, ast.AnnAssign):
                binding = resolve_alias(statement.value) if statement.value is not None else None
                for name in _assigned_names(statement.target):
                    if binding is None:
                        bindings.pop(name, None)
                    else:
                        bindings[name] = binding
                continue
            for name in _statement_bound_names(statement):
                bindings.pop(name, None)
        class_bindings_cache[module_name] = bindings
        return bindings

    def static_class_identities(module_names: Iterable[str]) -> set[tuple[str, str]]:
        return {
            (origin_module, class_node.name)
            for candidate_module in module_names
            for class_node, origin_module in static_class_bindings(candidate_module).values()
        }

    def resolve(module_name: str, seen: frozenset[str]) -> AssignmentMap:
        if module_name in resolved:
            return resolved[module_name]
        if module_name in resolving:
            return resolving[module_name]
        module = modules_by_name.get(module_name)
        if module is None:
            return {}
        assignments: AssignmentMap = {}
        resolving[module_name] = assignments
        function_bindings = static_function_bindings(module_name)
        module_functions = {
            name: function for name, (function, _origin) in function_bindings.items()
        }
        module_function_origins = {
            name: origin for name, (_function, origin) in function_bindings.items()
        }
        module_classes = {
            name: class_node
            for name, (class_node, _origin) in static_class_bindings(module_name).items()
        }

        def expression_qualified_assignments(
            value: ast.AST,
            state: AssignmentMap,
        ) -> dict[str, AssignmentMap]:
            qualified = {**resolved, **resolving}
            pending: list[tuple[ast.AST, AssignmentMap]] = [(value, state)]
            traversed: set[tuple[int, int]] = set()
            while pending:
                candidate, inherited_state = pending.pop()
                scoped_state = _assignment_origin_scope(
                    candidate,
                    inherited_state,
                    qualified,
                )
                marker = (id(candidate), id(scoped_state))
                if marker in traversed:
                    continue
                traversed.add(marker)
                for root in _loaded_root_names(candidate):
                    for binding in scoped_state.get(root, ()):
                        if isinstance(binding, _ImportBinding):
                            if binding.module not in modules_by_name:
                                continue
                            imported_state = qualified.get(binding.module)
                            if imported_state is None:
                                imported_state = resolve(
                                    binding.module,
                                    seen | {module_name},
                                )
                                qualified[binding.module] = imported_state
                            if binding.symbol is not None:
                                pending.extend(
                                    (imported, imported_state)
                                    for imported in imported_state.get(binding.symbol, ())
                                )
                            continue
                        if isinstance(binding, _FunctionBinding):
                            called_state = getattr(
                                binding.node,
                                FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                                scoped_state,
                            )
                            default_values = (
                                *binding.node.args.defaults,
                                *(
                                    default
                                    for default in binding.node.args.kw_defaults
                                    if default is not None
                                ),
                            )
                            returned_values = (
                                (binding.node.body,)
                                if isinstance(binding.node, ast.Lambda)
                                else tuple(
                                    returned.value
                                    for returned in _lexical_nodes(binding.node)
                                    if isinstance(returned, ast.Return)
                                    and returned.value is not None
                                )
                            )
                            pending.extend((default, called_state) for default in default_values)
                            pending.extend((returned, called_state) for returned in returned_values)
                            continue
                        if isinstance(binding, ast.expr):
                            pending.append((binding, scoped_state))
            return qualified

        def callback_call_arguments(
            call: ast.Call,
            callback: CallbackBinding,
        ) -> dict[str, tuple[ast.AST, bool]] | None:
            called, _origin, implicit_positional_count = callback
            if not implicit_positional_count:
                return _bound_function_call_arguments(call, called)
            expanded = ast.Call(
                func=call.func,
                args=[
                    *(ast.Constant(value=None) for _ in range(implicit_positional_count)),
                    *call.args,
                ],
                keywords=call.keywords,
            )
            return _bound_function_call_arguments(expanded, called)

        def class_instance_expression(
            value: ast.AST,
            state: AssignmentMap,
            *,
            seen_names: frozenset[str] = frozenset(),
        ) -> bool:
            if isinstance(value, ast.Call):
                return resolve_module_class(value.func, state) is not None
            if isinstance(value, ast.Name):
                if value.id in seen_names:
                    return False
                return any(
                    class_instance_expression(
                        candidate,
                        state,
                        seen_names=seen_names | {value.id},
                    )
                    for candidate in state.get(value.id, ())
                )
            if isinstance(value, ast.Subscript):
                selected = _selected_reference_expression(value, state)
                return selected is not None and class_instance_expression(
                    selected,
                    state,
                    seen_names=seen_names,
                )
            return False

        def callback_bindings_for_expression(
            value: ast.AST,
            state: AssignmentMap,
            *,
            current_module: str = module_name,
            seen_expressions: frozenset[tuple[int, int, str]] = frozenset(),
            seen_functions: frozenset[tuple[str, str]] = frozenset(),
        ) -> tuple[CallbackBinding, ...]:
            qualified_assignments = expression_qualified_assignments(value, state)
            scoped_state = _assignment_origin_scope(
                value,
                state,
                qualified_assignments,
            )
            scoped_module = getattr(
                value,
                ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
                current_module,
            )
            marker = (id(value), id(scoped_state), scoped_module)
            if marker in seen_expressions:
                return ()
            seen_expressions = seen_expressions | {marker}
            bindings: dict[tuple[str, str, int], CallbackBinding] = {}

            def collect(candidates: Iterable[CallbackBinding]) -> None:
                for candidate, origin, implicit_positional_count in candidates:
                    name = (
                        candidate.name
                        if isinstance(candidate, (ast.AsyncFunctionDef, ast.FunctionDef))
                        else f"<lambda:{id(candidate)}>"
                    )
                    bindings.setdefault(
                        (origin, name, implicit_positional_count),
                        (candidate, origin, implicit_positional_count),
                    )

            if isinstance(value, ast.Lambda):
                collect(((value, scoped_module, 0),))
                return tuple(bindings.values())
            if isinstance(value, _FunctionBinding):
                collect(((value.node, value.module, value.implicit_positional_count),))
                return tuple(bindings.values())
            if isinstance(value, _ImportBinding):
                imported = (
                    static_function_bindings(value.module).get(value.symbol)
                    if value.symbol is not None
                    else None
                )
                if imported is not None:
                    collect(((imported[0], imported[1], 0),))
                return tuple(bindings.values())
            if isinstance(value, ast.Name):
                direct = static_function_bindings(scoped_module).get(value.id)
                if direct is not None:
                    collect(((direct[0], direct[1], 0),))
                for candidate in scoped_state.get(value.id, ()):
                    collect(
                        callback_bindings_for_expression(
                            candidate,
                            scoped_state,
                            current_module=scoped_module,
                            seen_expressions=seen_expressions,
                            seen_functions=seen_functions,
                        )
                    )
                return tuple(bindings.values())
            if isinstance(value, ast.Attribute):
                imported_modules = _qualified_imported_modules(
                    value.value,
                    scoped_state,
                    qualified_assignments,
                )
                for imported_module in imported_modules.conservative(qualified_assignments):
                    imported = static_function_bindings(imported_module).get(value.attr)
                    if imported is not None:
                        collect(((imported[0], imported[1], 0),))
                owner = resolve_module_class(value.value, scoped_state)
                if owner is not None:

                    def collect_class_member(
                        class_node: ast.ClassDef,
                        *,
                        bind_instance: bool,
                        seen_classes: frozenset[int] = frozenset(),
                    ) -> None:
                        if id(class_node) in seen_classes:
                            return
                        seen_classes = seen_classes | {id(class_node)}
                        class_state = getattr(
                            class_node,
                            CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                            {},
                        )
                        class_module = class_origins.get(id(class_node), scoped_module)
                        defines_member = any(
                            value.attr in _statement_bound_names(statement)
                            for statement in class_node.body
                        )
                        if not defines_member:
                            base_classes = getattr(
                                class_node,
                                CLASS_BASE_BINDINGS_ATTRIBUTE,
                                (),
                            )
                            for base_class in base_classes:
                                collect_class_member(
                                    base_class,
                                    bind_instance=bind_instance,
                                    seen_classes=seen_classes,
                                )
                            return
                        for candidate in class_state.get(value.attr, ()):
                            collect(
                                (
                                    called,
                                    origin,
                                    implicit_positional_count + int(bind_instance),
                                )
                                for (
                                    called,
                                    origin,
                                    implicit_positional_count,
                                ) in callback_bindings_for_expression(
                                    candidate,
                                    class_state,
                                    current_module=class_module,
                                    seen_expressions=seen_expressions,
                                    seen_functions=seen_functions,
                                )
                            )
                        method = next(
                            (
                                statement
                                for statement in reversed(class_node.body)
                                if isinstance(
                                    statement,
                                    (ast.AsyncFunctionDef, ast.FunctionDef),
                                )
                                and statement.name == value.attr
                            ),
                            None,
                        )
                        if method is None or not method.decorator_list:
                            return
                        decorators = {
                            _terminal_name(decorator) for decorator in method.decorator_list
                        }
                        if decorators == {"staticmethod"}:
                            collect(((method, class_module, 0),))
                        elif decorators == {"classmethod"}:
                            collect(((method, class_module, 1),))

                    collect_class_member(
                        owner,
                        bind_instance=class_instance_expression(
                            value.value,
                            scoped_state,
                        ),
                    )
                return tuple(bindings.values())
            if isinstance(value, ast.Subscript):
                selected = _qualified_selected_reference_expressions(
                    value,
                    scoped_state,
                    qualified_assignments,
                )
                for candidate in selected.values:
                    collect(
                        callback_bindings_for_expression(
                            candidate,
                            scoped_state,
                            current_module=scoped_module,
                            seen_expressions=seen_expressions,
                            seen_functions=seen_functions,
                        )
                    )
                return tuple(bindings.values())
            if isinstance(value, ast.Call):
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get"
                    and len(value.args) in {1, 2}
                    and not value.keywords
                ):
                    selected = _qualified_selected_reference_expressions(
                        ast.Subscript(
                            value=value.func.value,
                            slice=value.args[0],
                            ctx=ast.Load(),
                        ),
                        scoped_state,
                        qualified_assignments,
                    )
                    for candidate in selected.values:
                        collect(
                            callback_bindings_for_expression(
                                candidate,
                                scoped_state,
                                current_module=scoped_module,
                                seen_expressions=seen_expressions,
                                seen_functions=seen_functions,
                            )
                        )
                for callback in callback_bindings_for_expression(
                    value.func,
                    scoped_state,
                    current_module=scoped_module,
                    seen_expressions=seen_expressions,
                    seen_functions=seen_functions,
                ):
                    called, called_module, _implicit_positional_count = callback
                    called_name = (
                        called.name
                        if isinstance(called, (ast.AsyncFunctionDef, ast.FunctionDef))
                        else f"<lambda:{id(called)}>"
                    )
                    function_key = (called_module, called_name)
                    if function_key in seen_functions:
                        continue
                    bound = callback_call_arguments(value, callback)
                    if bound is None:
                        continue
                    called_state = dict(
                        scoped_state
                        if called_module == scoped_module
                        else resolve(called_module, seen | {module_name})
                    )
                    for parameter, (actual, _supplied) in bound.items():
                        actual_callbacks = callback_bindings_for_expression(
                            actual,
                            scoped_state,
                            current_module=scoped_module,
                            seen_expressions=seen_expressions,
                            seen_functions=seen_functions,
                        )
                        called_state[parameter] = (
                            _FunctionBinding(
                                module=actual_callbacks[0][1],
                                symbol=(
                                    actual_callbacks[0][0].name
                                    if isinstance(
                                        actual_callbacks[0][0],
                                        (ast.AsyncFunctionDef, ast.FunctionDef),
                                    )
                                    else f"<lambda:{id(actual_callbacks[0][0])}>"
                                ),
                                node=actual_callbacks[0][0],
                                implicit_positional_count=actual_callbacks[0][2],
                            )
                            if len(actual_callbacks) == 1
                            else actual,
                        )
                    returned_values = (
                        (called.body,)
                        if isinstance(called, ast.Lambda)
                        else tuple(
                            candidate.value
                            for candidate in _lexical_nodes(called)
                            if isinstance(candidate, ast.Return) and candidate.value is not None
                        )
                    )
                    for returned in returned_values:
                        collect(
                            callback_bindings_for_expression(
                                returned,
                                called_state,
                                current_module=called_module,
                                seen_expressions=seen_expressions,
                                seen_functions=seen_functions | {function_key},
                            )
                        )
                return tuple(bindings.values())
            if isinstance(value, ast.IfExp):
                branches = (value.body, value.orelse)
            elif isinstance(value, ast.BoolOp):
                branches = tuple(value.values)
            elif isinstance(value, ast.NamedExpr):
                branches = (value.value,)
            else:
                branches = ()
            for branch in branches:
                collect(
                    callback_bindings_for_expression(
                        branch,
                        scoped_state,
                        current_module=scoped_module,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                )
            return tuple(bindings.values())

        def class_bindings_for_expression(
            value: ast.AST,
            state: AssignmentMap,
            *,
            seen_expressions: frozenset[tuple[int, int]] = frozenset(),
            seen_functions: frozenset[tuple[str, str]] = frozenset(),
        ) -> _Provenance[_ClassBinding]:
            qualified_assignments = expression_qualified_assignments(value, state)
            state = _assignment_origin_scope(
                value,
                state,
                qualified_assignments,
            )
            marker = (id(value), id(state))
            if marker in seen_expressions:
                return _unresolved_provenance()
            seen_expressions = seen_expressions | {marker}

            def merged(
                results: Iterable[_Provenance[_ClassBinding]],
            ) -> _Provenance[_ClassBinding]:
                result = _merge_provenance(results)
                bindings = {(binding.module, binding.symbol): binding for binding in result.values}
                return _Provenance(result.state, frozenset(bindings.values()))

            if isinstance(value, _ClassBinding):
                return _known_provenance((value,))
            if isinstance(value, _UnknownBinding):
                return _unresolved_provenance()
            if isinstance(
                value,
                (
                    ast.AsyncFunctionDef,
                    ast.Constant,
                    ast.FunctionDef,
                    ast.Lambda,
                    _FunctionBinding,
                    _ImportBinding,
                ),
            ):
                return _irrelevant_provenance()

            references = _qualified_assignment_references(
                value,
                state,
                qualified_assignments,
            )
            if references.state is not _ProvenanceState.IRRELEVANT:
                bindings = {
                    (candidate.module, candidate.symbol): candidate
                    for imported_module, symbol in references.values
                    for imported_state in (
                        qualified_assignments.get(imported_module)
                        or resolve(imported_module, seen | {module_name}),
                    )
                    for candidate in imported_state.get(symbol, ())
                    if isinstance(candidate, _ClassBinding)
                }
                return _Provenance(
                    references.state
                    if references.state is _ProvenanceState.UNRESOLVED
                    else (_ProvenanceState.KNOWN if bindings else _ProvenanceState.IRRELEVANT),
                    frozenset(bindings.values()),
                )

            if isinstance(value, ast.Attribute):
                owners = class_bindings_for_expression(
                    value.value,
                    state,
                    seen_expressions=seen_expressions,
                    seen_functions=seen_functions,
                )
                result = merged(
                    class_bindings_for_expression(
                        candidate,
                        class_state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for owner in owners.values
                    for class_state in (
                        getattr(
                            owner.node,
                            CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                            {},
                        ),
                    )
                    for candidate in class_state.get(value.attr, ())
                )
                if owners.state is _ProvenanceState.UNRESOLVED:
                    return _unresolved_provenance(result.values)
                if owners.state is _ProvenanceState.IRRELEVANT:
                    return _unresolved_provenance(result.values)
                return (
                    result
                    if result.state is not _ProvenanceState.IRRELEVANT
                    else _unresolved_provenance()
                )

            if isinstance(value, ast.Name):
                candidates = state.get(value.id, ())
                if not candidates:
                    return _unresolved_provenance()
                return merged(
                    class_bindings_for_expression(
                        candidate,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for candidate in candidates
                )
            if isinstance(value, ast.Subscript):
                selected = _qualified_selected_reference_expressions(
                    value,
                    state,
                    qualified_assignments,
                )
                result = merged(
                    class_bindings_for_expression(
                        candidate,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for candidate in selected.values
                )
                return (
                    _unresolved_provenance(result.values)
                    if selected.state is _ProvenanceState.UNRESOLVED
                    else result
                )
            if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
                return merged(
                    class_bindings_for_expression(
                        element,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for element in value.elts
                )
            if isinstance(value, ast.Dict):
                return merged(
                    class_bindings_for_expression(
                        element,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for element in value.values
                )
            if isinstance(value, ast.IfExp):
                branches = (value.body, value.orelse)
            elif isinstance(value, ast.BoolOp):
                branches = tuple(value.values)
            elif isinstance(value, ast.NamedExpr):
                branches = (value.value,)
            else:
                branches = ()
            if branches:
                return merged(
                    class_bindings_for_expression(
                        branch,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    for branch in branches
                )
            if not isinstance(value, ast.Call):
                return (
                    _unresolved_provenance()
                    if isinstance(value, ast.expr)
                    else _irrelevant_provenance()
                )

            callbacks = callback_bindings_for_expression(
                value.func,
                state,
            )
            if not callbacks:
                return _unresolved_provenance()
            results: list[_Provenance[_ClassBinding]] = []
            unresolved = False
            for called, called_module, _implicit_positional_count in callbacks:
                called_name = (
                    called.name
                    if isinstance(called, (ast.AsyncFunctionDef, ast.FunctionDef))
                    else f"<lambda:{id(called)}>"
                )
                function_key = (called_module, called_name)
                if function_key in seen_functions:
                    unresolved = True
                    continue
                callback = (called, called_module, _implicit_positional_count)
                bound = callback_call_arguments(value, callback)
                if bound is None:
                    unresolved = True
                    continue
                called_state = dict(
                    state
                    if called_module == module_name
                    else resolve(called_module, seen | {module_name})
                )
                for parameter, (actual, _supplied) in bound.items():
                    actual_bindings = class_bindings_for_expression(
                        actual,
                        state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions,
                    )
                    called_state[parameter] = (
                        next(iter(actual_bindings.values))
                        if actual_bindings.state is _ProvenanceState.KNOWN
                        and len(actual_bindings.values) == 1
                        else actual,
                    )
                returned_values = (
                    (called.body,)
                    if isinstance(called, ast.Lambda)
                    else tuple(
                        candidate.value
                        for candidate in _lexical_nodes(called)
                        if isinstance(candidate, ast.Return) and candidate.value is not None
                    )
                )
                results.extend(
                    class_bindings_for_expression(
                        returned,
                        called_state,
                        seen_expressions=seen_expressions,
                        seen_functions=seen_functions | {function_key},
                    )
                    for returned in returned_values
                )
            result = merged(results)
            return _unresolved_provenance(result.values) if unresolved else result

        def class_owner_bindings_for_expression(
            value: ast.AST,
            state: AssignmentMap,
            *,
            seen_expressions: frozenset[tuple[int, int]] = frozenset(),
        ) -> _Provenance[_ClassBinding]:
            qualified_assignments = expression_qualified_assignments(value, state)
            state = _assignment_origin_scope(value, state, qualified_assignments)
            marker = (id(value), id(state))
            if marker in seen_expressions:
                return _unresolved_provenance()
            seen_expressions = seen_expressions | {marker}

            def merged(
                results: Iterable[_Provenance[_ClassBinding]],
            ) -> _Provenance[_ClassBinding]:
                result = _merge_provenance(results)
                bindings = {(binding.module, binding.symbol): binding for binding in result.values}
                return _Provenance(result.state, frozenset(bindings.values()))

            direct = class_bindings_for_expression(value, state)
            if direct.state is _ProvenanceState.KNOWN and direct.values:
                return direct
            if isinstance(value, _UnknownBinding):
                return _unresolved_provenance()
            if isinstance(value, _ClassBinding):
                return _known_provenance((value,))
            if isinstance(
                value,
                (
                    ast.AsyncFunctionDef,
                    ast.Constant,
                    ast.FunctionDef,
                    ast.Lambda,
                    _FunctionBinding,
                    _ImportBinding,
                ),
            ):
                return direct
            if isinstance(value, ast.Name):
                candidates = state.get(value.id, ())
                if not candidates:
                    return _unresolved_provenance()
                return merged(
                    class_owner_bindings_for_expression(
                        candidate,
                        state,
                        seen_expressions=seen_expressions,
                    )
                    for candidate in candidates
                )
            if isinstance(value, ast.Attribute):
                base = class_bindings_for_expression(value.value, state)
                if base.state is _ProvenanceState.KNOWN and base.values:
                    return base
                inherited = class_owner_bindings_for_expression(
                    value.value,
                    state,
                    seen_expressions=seen_expressions,
                )
                if inherited.state is _ProvenanceState.KNOWN and inherited.values:
                    return inherited
                return _unresolved_provenance((*direct.values, *inherited.values))
            if isinstance(value, ast.Subscript):
                selected = _qualified_selected_reference_expressions(
                    value,
                    state,
                    qualified_assignments,
                )
                result = merged(
                    class_owner_bindings_for_expression(
                        candidate,
                        state,
                        seen_expressions=seen_expressions,
                    )
                    for candidate in selected.values
                )
                return (
                    _unresolved_provenance(result.values)
                    if selected.state is _ProvenanceState.UNRESOLVED
                    else result
                )
            if isinstance(value, (ast.List, ast.Set, ast.Tuple)):
                return merged(
                    class_owner_bindings_for_expression(
                        element,
                        state,
                        seen_expressions=seen_expressions,
                    )
                    for element in value.elts
                )
            if isinstance(value, ast.Dict):
                return merged(
                    class_owner_bindings_for_expression(
                        element,
                        state,
                        seen_expressions=seen_expressions,
                    )
                    for element in value.values
                )
            if isinstance(value, ast.IfExp):
                branches = (value.body, value.orelse)
            elif isinstance(value, ast.BoolOp):
                branches = tuple(value.values)
            elif isinstance(value, ast.NamedExpr):
                branches = (value.value,)
            else:
                branches = ()
            if branches:
                return merged(
                    class_owner_bindings_for_expression(
                        branch,
                        state,
                        seen_expressions=seen_expressions,
                    )
                    for branch in branches
                )
            if isinstance(value, ast.Call):
                returned = _closed_call_returns(
                    value,
                    state,
                    qualified_assignments,
                )
                result = merged(
                    class_owner_bindings_for_expression(
                        returned_value,
                        returned_state,
                        seen_expressions=seen_expressions,
                    )
                    for returned_value, returned_state, _module in returned.values
                )
                return (
                    _unresolved_provenance(result.values)
                    if returned.state is _ProvenanceState.UNRESOLVED
                    else result
                )
            return _unresolved_provenance(direct.values)

        def snapshot_qualified_class_bindings(
            value: ast.expr,
            state: AssignmentMap,
        ) -> ast.expr:
            resolved_value: ast.AST = value
            for candidate in tuple(ast.walk(value)):
                if isinstance(candidate, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
                    continue
                candidate_bindings = class_bindings_for_expression(candidate, state)
                if (
                    candidate_bindings.state is not _ProvenanceState.KNOWN
                    or len(candidate_bindings.values) != 1
                ):
                    continue
                resolved_value = _replace_ast_identity(
                    resolved_value,
                    candidate,
                    next(iter(candidate_bindings.values)),
                )
            return resolved_value if isinstance(resolved_value, ast.expr) else value

        def invalidate_class_references(
            value: ast.AST,
            state: AssignmentMap,
        ) -> _Provenance[_ClassBinding]:
            resolved_value = (
                snapshot_qualified_class_bindings(value, state)
                if isinstance(value, ast.expr)
                else value
            )
            direct_provenance = class_bindings_for_expression(resolved_value, state)
            owner_provenance = class_owner_bindings_for_expression(resolved_value, state)
            scoped_provenance = (
                owner_provenance
                if direct_provenance.state is not _ProvenanceState.KNOWN
                and owner_provenance.state is _ProvenanceState.KNOWN
                and owner_provenance.values
                else direct_provenance
            )
            direct_bindings = scoped_provenance.values
            identities = {(binding.module, binding.symbol) for binding in direct_bindings}
            class_provenance = scoped_provenance
            if scoped_provenance.state is _ProvenanceState.IRRELEVANT:
                class_provenance = _merge_provenance(
                    class_bindings_for_expression(candidate, state)
                    for candidate in ast.walk(resolved_value)
                )
                identities.update(
                    (binding.module, binding.symbol) for binding in class_provenance.values
                )
            qualified_assignments = expression_qualified_assignments(value, state)
            if class_provenance.state is _ProvenanceState.UNRESOLVED:
                identities.update(static_class_identities(modules_by_name))
            namespace_provenance = _merge_provenance(
                (
                    _qualified_imported_modules(
                        value,
                        state,
                        qualified_assignments,
                    ),
                    _qualified_namespace_dependency_modules(
                        value,
                        state,
                        qualified_assignments,
                    ),
                )
            )
            namespace_modules = (
                set()
                if scoped_provenance.state is _ProvenanceState.KNOWN and direct_bindings
                else namespace_provenance.conservative(modules_by_name)
            )
            identities.update(static_class_identities(namespace_modules))
            if not identities:
                return scoped_provenance
            invalidated_class_identities.update(identities)
            for candidate_state in (state, *resolved.values(), *resolving.values()):
                for candidates in candidate_state.values():
                    for bound_value in candidates:
                        for nested in ast.walk(bound_value):
                            if (
                                isinstance(nested, _ClassBinding)
                                and (nested.module, nested.symbol) in identities
                            ):
                                nested.invalidated = True
            return scoped_provenance

        def exact_class_provenance(
            provenance: _Provenance[_ClassBinding],
        ) -> bool:
            return provenance.state is _ProvenanceState.KNOWN and bool(provenance.values)

        def bind(target: ast.AST, value: ast.expr, state: AssignmentMap) -> None:
            if not hasattr(value, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE):
                setattr(value, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE, module_name)
                setattr(value, ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE, dict(state))
            value = _snapshot_bound_expression(value, state)
            value = snapshot_qualified_class_bindings(value, state)
            if not hasattr(value, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE):
                setattr(value, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE, module_name)
                setattr(value, ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE, dict(state))
            if isinstance(target, ast.Name):
                state[target.id] = (value,)
            elif isinstance(target, ast.Subscript):
                root_name = _target_root_name(target)
                if root_name is not None and len(_current_alias_component(root_name, state)) > 1:
                    bind_unknown(root_name, state)
                    return
                previous_candidates = (
                    state.get(target.value.id, ()) if isinstance(target.value, ast.Name) else ()
                )
                if (
                    isinstance(target.value, ast.Name)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                    and target.slice.value
                    and len(previous_candidates) == 1
                    and isinstance(previous_candidates[0], ast.expr)
                ):
                    previous = previous_candidates[0]
                    replacement = ast.Dict(
                        keys=[None, ast.Constant(target.slice.value)],
                        values=[previous, value],
                    )
                    for name, candidates in tuple(state.items()):
                        state[name] = tuple(
                            _replace_ast_identity(candidate, previous, replacement)
                            for candidate in candidates
                        )
                else:
                    bind_unknown_target(target, state)
            elif isinstance(target, ast.Attribute):
                bind_unknown_target(target, state)
            elif isinstance(target, ast.Starred):
                bind_unknown_target(target.value, state)
            elif isinstance(target, (ast.List, ast.Tuple)):
                for index, child in enumerate(target.elts):
                    bind(
                        child,
                        ast.Subscript(value=value, slice=ast.Constant(index)),
                        state,
                    )

        def bind_unknown(name: str, state: AssignmentMap) -> None:
            for alias in _current_alias_component(name, state):
                for candidate in state.get(alias, ()):
                    invalidate_class_references(candidate, state)
                state[alias] = (_UnknownBinding(),)

        def bind_unknown_with_contents(name: str, state: AssignmentMap) -> None:
            reachable = _reachable_assignment_roots(
                ast.Name(id=name, ctx=ast.Load()),
                dict(state),
                follow_identity=True,
            ) | {name}
            for reachable in _with_retained_generator_roots(reachable, state):
                bind_unknown(reachable, state)

        def bind_unknown_with_retained(name: str, state: AssignmentMap) -> None:
            affected_names = _with_retained_generator_roots({name}, state)
            for affected in affected_names:
                bind_unknown(affected, state)

        def exact_import_decorator(node: ast.AST, state: AssignmentMap) -> bool:
            allowed = {
                ("contextlib", "contextmanager"),
                ("dataclasses", "dataclass"),
                ("functools", "cache"),
                ("functools", "lru_cache"),
            }
            target = node
            while isinstance(target, ast.Call):
                target = target.func
            if isinstance(target, ast.Name):
                candidates = state.get(target.id, ())
                return (
                    len(candidates) == 1
                    and isinstance(candidates[0], _ImportBinding)
                    and (candidates[0].module, candidates[0].symbol) in allowed
                )
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                candidates = state.get(target.value.id, ())
                return (
                    len(candidates) == 1
                    and isinstance(candidates[0], _ImportBinding)
                    and candidates[0].symbol is None
                    and (candidates[0].module, target.attr) in allowed
                )
            return False

        def bind_all_current_objects(state: AssignmentMap) -> None:
            for name, candidates in tuple(state.items()):
                if any(isinstance(candidate, ast.expr) for candidate in candidates):
                    bind_unknown_with_contents(name, state)

        def bind_current_mutable_literals(state: AssignmentMap) -> None:
            defining_assignments = {
                name: (state if origin == module_name else resolved.get(origin, {}))
                for name, origin in module_function_origins.items()
            }
            function_scopes = {
                function_id: (
                    {
                        name: function
                        for name, (function, _origin) in static_function_bindings(origin).items()
                    },
                    state if origin == module_name else resolved.get(origin, {}),
                )
                for function_id, origin in function_origins.items()
            }
            for name, candidates in tuple(state.items()):
                if any(
                    _may_reference_mutable_literal(
                        candidate,
                        state,
                        functions=module_functions,
                        function_assignments=defining_assignments,
                        function_scopes=function_scopes,
                        qualified_functions=qualified_function_nodes,
                    )
                    for candidate in candidates
                ):
                    bind_unknown_with_contents(name, state)

        def resolve_module_class(
            target: ast.AST,
            state: AssignmentMap,
            *,
            seen: frozenset[str] = frozenset(),
        ) -> ast.ClassDef | None:
            if isinstance(target, _ClassBinding):
                binding = static_class_bindings(target.module).get(target.symbol)
                return binding[0] if binding is not None else None
            if isinstance(target, ast.Call):
                constructed_owner = resolve_module_class(target.func, state, seen=seen)
                if constructed_owner is not None:
                    return constructed_owner
            if isinstance(target, ast.Call) and isinstance(target.func, ast.Name):
                wrapper = module_functions.get(target.func.id)
                if wrapper is None:
                    return None
                bound = _bound_function_call_arguments(target, wrapper)
                if bound is None:
                    return None
                wrapper_state = dict(state)
                wrapper_state.update(
                    {parameter: (actual,) for parameter, (actual, _supplied) in bound.items()}
                )
                for returned in _return_values(
                    wrapper,
                    source=f"constructor wrapper {target.func.id}",
                ):
                    resolved_wrapper = resolve_module_class(
                        returned,
                        wrapper_state,
                        seen=seen | {target.func.id},
                    )
                    if resolved_wrapper is not None:
                        return resolved_wrapper
                return None
            if isinstance(target, ast.Subscript):
                selected = _selected_reference_expression(target, state)
                return (
                    resolve_module_class(selected, state, seen=seen)
                    if selected is not None
                    else None
                )
            if isinstance(target, (ast.BoolOp, ast.IfExp)):
                for value in ast.iter_child_nodes(target):
                    resolved_branch = resolve_module_class(value, state, seen=seen)
                    if resolved_branch is not None:
                        return resolved_branch
                return None
            if isinstance(target, ast.Attribute):
                imported_module = _imported_module_expression(target.value, state)
                if imported_module is not None:
                    imported_class = static_class_bindings(imported_module).get(target.attr)
                    if imported_class is not None:
                        return imported_class[0]
                owner = resolve_module_class(target.value, state, seen=seen)
                if owner is None:
                    return None
                for statement in reversed(owner.body):
                    value: ast.expr | None = None
                    if isinstance(statement, ast.Assign) and any(
                        isinstance(item, ast.Name) and item.id == target.attr
                        for item in statement.targets
                    ):
                        value = statement.value
                    elif (
                        isinstance(statement, ast.AnnAssign)
                        and isinstance(statement.target, ast.Name)
                        and statement.target.id == target.attr
                    ):
                        value = statement.value
                    if value is not None:
                        return resolve_module_class(value, state, seen=seen)
                return None
            if not isinstance(target, ast.Name) or target.id in seen:
                return None
            class_node = module_classes.get(target.id)
            if class_node is not None:
                return class_node
            for candidate in state.get(target.id, ()):
                if isinstance(
                    candidate,
                    (
                        _ClassBinding,
                        ast.Attribute,
                        ast.BoolOp,
                        ast.Call,
                        ast.IfExp,
                        ast.Name,
                        ast.Subscript,
                    ),
                ):
                    resolved_class = resolve_module_class(
                        candidate,
                        state,
                        seen=seen | {target.id},
                    )
                    if resolved_class is not None:
                        return resolved_class
            return None

        def resolve_module_callback(
            name: str,
            state: AssignmentMap,
        ) -> FunctionNode | None:
            return next(
                (
                    callback
                    for callback, _origin, _implicit_positional_count in (
                        callback_bindings_for_expression(
                            ast.Name(id=name, ctx=ast.Load()),
                            state,
                        )
                    )
                    if isinstance(callback, (ast.AsyncFunctionDef, ast.FunctionDef))
                ),
                None,
            )

        def callback_state(
            callback: FunctionNode | ast.Lambda,
            state: AssignmentMap,
        ) -> tuple[str, AssignmentMap]:
            origin = function_origins.get(
                id(callback),
                getattr(
                    callback,
                    ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
                    module_name,
                ),
            )
            return (
                origin,
                state if origin == module_name else resolve(origin, seen | {module_name}),
            )

        def resolved_module_callback_mutated_parameters(
            function: FunctionNode | ast.Lambda,
            state: AssignmentMap,
            *,
            seen: frozenset[int] = frozenset(),
        ) -> set[str]:
            marker = id(function)
            if marker in seen:
                return set()
            function_module, function_state = callback_state(function, state)
            parameters = set(_function_parameter_annotations(function))
            mutated = _mutated_callback_parameter_names(
                function,
                function_state,
                qualified_assignments=expression_qualified_assignments(
                    function,
                    function_state,
                ),
            )
            for callback_call in _lexical_nodes(function):
                if not isinstance(callback_call, ast.Call):
                    continue
                for delegated_callback in callback_bindings_for_expression(
                    callback_call.func,
                    function_state,
                    current_module=function_module,
                ):
                    delegated, _delegated_module, _implicit_count = delegated_callback
                    bound = callback_call_arguments(callback_call, delegated_callback)
                    if bound is None:
                        continue
                    delegated_mutated = resolved_module_callback_mutated_parameters(
                        delegated,
                        function_state,
                        seen=seen | {marker},
                    )
                    for parameter_name in delegated_mutated:
                        actual = bound.get(parameter_name)
                        if actual is not None:
                            mutated.update(_loaded_root_names(actual[0]) & parameters)
            return mutated

        def resolve_qualified_callback_keyword(
            node: ast.Call,
            name: str,
            state: AssignmentMap,
        ) -> _Provenance[ast.expr]:
            return _qualified_callback_keyword_provenance(
                node,
                name,
                state,
                expression_qualified_assignments(node, state),
            )

        def apply_callback_mutations(
            node: ast.Call,
            state: AssignmentMap,
            *,
            infer_unrecognized: bool,
        ) -> None:
            callback_provenance, iterables, supplied_positional_count, executes_protocol = (
                _executed_callback(
                    node,
                    state,
                    resolve_keyword=resolve_qualified_callback_keyword,
                )
            )
            recognized_callback = callback_provenance.state is not _ProvenanceState.IRRELEVANT
            if callback_provenance.state is _ProvenanceState.UNRESOLVED:
                invalidate_class_references(_UnknownBinding(), state)
                bind_all_current_objects(state)
            if callback_provenance.state is _ProvenanceState.IRRELEVANT and infer_unrecognized:
                inferred_callback = next(
                    (
                        argument
                        for argument in node.args
                        if isinstance(argument, ast.Lambda)
                        or (
                            isinstance(argument, ast.Name)
                            and resolve_module_callback(argument.id, state) is not None
                        )
                    ),
                    None,
                )
                if inferred_callback is not None:
                    callback_provenance = _known_provenance((inferred_callback,))
                    iterables = tuple(
                        argument for argument in node.args if argument is not inferred_callback
                    )
                    supplied_positional_count = 0
                    executes_protocol = True
            callbacks = tuple(callback_provenance.values)
            protocol_values = iterables
            if executes_protocol and any(
                not _known_protocol_inert_expression(value, state) for value in protocol_values
            ):
                bind_current_mutable_literals(state)
                for value in protocol_values:
                    for root in _reachable_assignment_roots(value, state):
                        bind_unknown_with_contents(root, state)
            if not callbacks:
                return
            if len(callbacks) != 1:
                invalidate_class_references(_UnknownBinding(), state)
                bind_all_current_objects(state)
                return
            callback = callbacks[0]
            mutates_inputs = True
            if isinstance(callback, ast.Lambda):
                callback_module, callback_assignments = callback_state(callback, state)
                parameters = set(_function_parameter_annotations(callback))
                mutation_roots = _direct_mutation_roots(callback)
                for captured_root in mutation_roots - parameters:
                    if captured_root in callback_assignments:
                        bind_unknown_with_contents(captured_root, callback_assignments)
                for callback_call in _lexical_nodes(callback):
                    if not isinstance(callback_call, ast.Call):
                        continue
                    for delegated_callback in callback_bindings_for_expression(
                        callback_call.func,
                        callback_assignments,
                        current_module=callback_module,
                    ):
                        delegated, _delegated_module, _implicit_count = delegated_callback
                        _, delegated_assignments = callback_state(
                            delegated,
                            callback_assignments,
                        )
                        captured_roots = (
                            _mutated_free_bindings(
                                delegated,
                                delegated_assignments,
                                qualified_assignments=expression_qualified_assignments(
                                    delegated,
                                    delegated_assignments,
                                ),
                            )
                            if isinstance(
                                delegated,
                                (ast.AsyncFunctionDef, ast.FunctionDef),
                            )
                            else set()
                        )
                        for captured_root in captured_roots:
                            if captured_root in delegated_assignments:
                                bind_unknown_with_contents(
                                    captured_root,
                                    delegated_assignments,
                                )
                        bound = callback_call_arguments(
                            callback_call,
                            delegated_callback,
                        )
                        if bound is not None:
                            for parameter_name in resolved_module_callback_mutated_parameters(
                                delegated,
                                delegated_assignments,
                            ):
                                actual = bound.get(parameter_name)
                                if actual is None:
                                    continue
                                for root in _reachable_assignment_roots(
                                    actual[0],
                                    callback_assignments,
                                ):
                                    bind_unknown_with_contents(root, callback_assignments)
                mutated_parameters = resolved_module_callback_mutated_parameters(callback, state)
                for root in _default_mutation_roots(
                    callback,
                    mutated_parameters,
                    supplied_positional_count,
                    callback_assignments,
                ):
                    bind_unknown_with_contents(root, callback_assignments)
                mutates_inputs = bool(mutated_parameters)
            else:
                resolved_callbacks = callback_bindings_for_expression(callback, state)
                if recognized_callback:
                    callable_provenance = _qualified_callable_provenance(
                        callback,
                        state,
                        expression_qualified_assignments(callback, state),
                        inherited_module=module_name,
                    )
                    if callable_provenance.state is _ProvenanceState.UNRESOLVED:
                        invalidate_class_references(callback, state)
                        bind_all_current_objects(state)
                if not resolved_callbacks:
                    bind_all_current_objects(state)
                else:
                    mutates_inputs = False
                    for called, _origin, implicit_positional_count in resolved_callbacks:
                        _, called_assignments = callback_state(called, state)
                        for captured_root in _mutated_free_bindings(
                            called,
                            called_assignments,
                            qualified_assignments=expression_qualified_assignments(
                                called,
                                called_assignments,
                            ),
                        ):
                            if captured_root in called_assignments:
                                bind_unknown_with_contents(captured_root, called_assignments)
                        mutated_parameters = resolved_module_callback_mutated_parameters(
                            called,
                            called_assignments,
                        )
                        for root in _default_mutation_roots(
                            called,
                            mutated_parameters,
                            supplied_positional_count + implicit_positional_count,
                            called_assignments,
                        ):
                            bind_unknown_with_contents(root, called_assignments)
                        mutates_inputs = mutates_inputs or bool(mutated_parameters)
            if mutates_inputs:
                for iterable in iterables:
                    for root in _reachable_assignment_roots(iterable, state):
                        bind_unknown_with_contents(root, state)

        def apply_mutating_call(node: ast.Call, root_name: str, state: AssignmentMap) -> None:
            aliases = _current_alias_component(root_name, state)
            previous = state.get(root_name, ())
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == root_name
            ):
                bind_unknown_with_contents(root_name, state)
                return
            if len(aliases) == 1 and len(previous) == 1 and isinstance(previous[0], ast.expr):
                replacement = _closed_mutation_expression(node, previous[0], state)
                if replacement is not None:
                    for name, candidates in tuple(state.items()):
                        state[name] = tuple(
                            _replace_ast_identity(candidate, previous[0], replacement)
                            for candidate in candidates
                        )
                    return
            bind_unknown_with_retained(root_name, state)

        def bind_unknown_target(target: ast.AST, state: AssignmentMap) -> None:
            if isinstance(target, ast.Name):
                bind_unknown(target.id, state)
            elif isinstance(target, ast.Starred):
                bind_unknown_target(target.value, state)
            elif isinstance(target, (ast.Attribute, ast.Subscript)):
                target_provenance = invalidate_class_references(target.value, state)
                root_name = _target_root_name(target)
                if root_name is not None and not (
                    isinstance(target, ast.Attribute) and exact_class_provenance(target_provenance)
                ):
                    bind_unknown_with_contents(root_name, state)
            elif isinstance(target, (ast.List, ast.Tuple)):
                for child in target.elts:
                    bind_unknown_target(child, state)

        def process(node: ast.stmt, state: AssignmentMap) -> None:
            if isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    process(ast.Expr(value=node.value), state)
                    bind(node.target, node.value, state)
                if getattr(node, VARIABLE_ANNOTATION_EXECUTED_ATTRIBUTE, False):
                    process(ast.Expr(value=node.annotation), state)
                    _bind_annotation_provenance(node.annotation, state)
                return
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                setattr(
                    node,
                    FUNCTION_DEFAULT_ASSIGNMENTS_ATTRIBUTE,
                    dict(state),
                )
            execution_roots: tuple[ast.AST, ...] = (
                (
                    *_definition_time_expressions(node),
                    *_implicit_decorator_calls(node),
                )
                if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
                else (node,)
            )
            for execution_root in execution_roots:
                if isinstance(execution_root, ast.expr):
                    setattr(
                        execution_root,
                        ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
                        module_name,
                    )
                    setattr(
                        execution_root,
                        ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE,
                        dict(state),
                    )
                execution_nodes = (execution_root, *_lexical_nodes(execution_root))
                for candidate in execution_nodes:
                    if isinstance(candidate, ast.NamedExpr):
                        target_root = _target_root_name(candidate.target)
                        if target_root is not None:
                            bind_unknown_with_contents(target_root, state)
                            if isinstance(candidate.target, ast.Name):
                                state[target_root] = (candidate.value, _UnknownBinding())
                        else:
                            bind_unknown_target(candidate.target, state)
                for candidate in execution_nodes:
                    if isinstance(candidate, ast.Call):
                        implicit_decorator = getattr(
                            candidate, IMPLICIT_DECORATOR_CALL_ATTRIBUTE, False
                        )
                        if implicit_decorator and exact_import_decorator(candidate.func, state):
                            continue
                        if not hasattr(candidate, ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE):
                            setattr(
                                candidate,
                                ASSIGNMENT_ORIGIN_MODULE_ATTRIBUTE,
                                module_name,
                            )
                            setattr(
                                candidate,
                                ASSIGNMENT_ORIGIN_SCOPE_ATTRIBUTE,
                                dict(state),
                            )
                        candidate_qualified_assignments = expression_qualified_assignments(
                            candidate,
                            state,
                        )
                        namespace_provenance = _qualified_namespace_modules(
                            candidate,
                            state,
                            candidate_qualified_assignments,
                        )
                        imported_module_provenance = _qualified_imported_modules(
                            candidate,
                            state,
                            candidate_qualified_assignments,
                        )
                        exact_assignment_accessor = any(
                            _exact_builtin_assignment_accessor(
                                candidate.func,
                                accessor,
                                state,
                                candidate_qualified_assignments,
                            )
                            for accessor in (
                                "delattr",
                                "dict",
                                "getattr",
                                "setattr",
                                "vars",
                            )
                        ) or (
                            any(
                                provenance.state is _ProvenanceState.KNOWN
                                and bool(provenance.values)
                                for provenance in (
                                    namespace_provenance,
                                    imported_module_provenance,
                                )
                            )
                        )
                        assignment_references = _qualified_assignment_references(
                            candidate,
                            state,
                            candidate_qualified_assignments,
                        )
                        exact_assignment_lookup = (
                            assignment_references.state is _ProvenanceState.KNOWN
                            and bool(assignment_references.values)
                        )
                        called_callbacks = callback_bindings_for_expression(
                            candidate.func,
                            state,
                        )
                        root_name = _mutating_call_root(candidate)
                        mutating_receiver_provenance: _Provenance[_ClassBinding] = (
                            _irrelevant_provenance()
                        )
                        exact_class_receiver = False
                        mutating_container_call = (
                            isinstance(candidate.func, ast.Attribute)
                            and candidate.func.attr in MUTATING_CONTAINER_METHODS
                        )
                        if mutating_container_call and isinstance(
                            candidate.func,
                            ast.Attribute,
                        ):
                            receiver = candidate.func.value
                            if isinstance(receiver, ast.Attribute):
                                mutating_receiver_provenance = invalidate_class_references(
                                    receiver.value,
                                    state,
                                )
                                exact_class_receiver = exact_class_provenance(
                                    mutating_receiver_provenance
                                )
                            if not exact_class_receiver:
                                mutating_receiver_provenance = invalidate_class_references(
                                    receiver,
                                    state,
                                )
                                exact_class_receiver = exact_class_provenance(
                                    mutating_receiver_provenance
                                )
                        known_local_container_receiver = (
                            mutating_container_call
                            and mutating_receiver_provenance.state is _ProvenanceState.IRRELEVANT
                            and isinstance(candidate.func, ast.Attribute)
                            and _known_builtin_container_expression(candidate.func.value, state)
                        )
                        if not (
                            called_callbacks
                            or exact_assignment_accessor
                            or exact_assignment_lookup
                            or known_local_container_receiver
                        ):
                            for argument in (
                                *candidate.args,
                                *(keyword.value for keyword in candidate.keywords),
                            ):
                                invalidate_class_references(argument, state)
                        if not exact_assignment_accessor and not exact_assignment_lookup:
                            apply_callback_mutations(
                                candidate,
                                state,
                                infer_unrecognized=not known_local_container_receiver,
                            )
                        resolved_constructor = resolve_module_class(candidate.func, state)
                        local_method_owner = (
                            resolve_module_class(candidate.func.value, state)
                            if isinstance(candidate.func, ast.Attribute)
                            else None
                        )
                        callable_provenance = _qualified_callable_provenance(
                            candidate.func,
                            state,
                            candidate_qualified_assignments,
                            inherited_module=module_name,
                        )
                        known_inert_callable = _known_builtin_container_expression(
                            candidate,
                            state,
                        ) or _known_non_aliasing_call(candidate, state)
                        unresolved_callable = (
                            callable_provenance.state is _ProvenanceState.UNRESOLVED
                            and resolved_constructor is None
                            and local_method_owner is None
                            and not exact_assignment_accessor
                            and not exact_assignment_lookup
                            and not called_callbacks
                            and not known_inert_callable
                            and not known_local_container_receiver
                        )
                        unresolved_local_callable = unresolved_callable and any(
                            any(
                                not isinstance(binding, _ImportBinding)
                                for binding in state.get(root, ())
                            )
                            for root in _reachable_assignment_roots(
                                candidate.func,
                                state,
                                follow_identity=True,
                            )
                        )
                        call_bindings = (
                            state.get(candidate.func.id, ())
                            if isinstance(candidate.func, ast.Name)
                            else ()
                        )
                        unresolved_name_callable = (
                            isinstance(candidate.func, ast.Name)
                            and candidate.func.id not in module_functions
                            and resolved_constructor is None
                            and not exact_assignment_accessor
                            and not exact_assignment_lookup
                            and not called_callbacks
                            and any(
                                isinstance(binding, (_UnknownBinding, ast.Name))
                                or (
                                    isinstance(binding, _ImportBinding)
                                    and binding.module in modules_by_name
                                )
                                for binding in call_bindings
                            )
                        )
                        wrapped_callable = isinstance(candidate.func, ast.Call) or (
                            isinstance(candidate.func, ast.Name)
                            and any(
                                isinstance(binding, (ast.Attribute, ast.Call, ast.Subscript))
                                for binding in state.get(candidate.func.id, ())
                            )
                        )
                        if (
                            (
                                resolved_constructor is not None
                                or local_method_owner is not None
                                or unresolved_name_callable
                                or unresolved_local_callable
                                or wrapped_callable
                            )
                            and not exact_assignment_accessor
                            and not exact_assignment_lookup
                            and not called_callbacks
                            and not exact_class_receiver
                            and not known_local_container_receiver
                        ):
                            bind_current_mutable_literals(state)
                            for value in (
                                *candidate.args,
                                *(keyword.value for keyword in candidate.keywords),
                            ):
                                for reachable in _reachable_assignment_roots(value, state):
                                    bind_unknown_with_contents(reachable, state)
                        if root_name is not None:
                            if not exact_class_receiver:
                                apply_mutating_call(candidate, root_name, state)
                        elif (
                            mutating_container_call
                            and mutating_receiver_provenance.state
                            is not _ProvenanceState.IRRELEVANT
                        ):
                            for bound_name in tuple(state):
                                bind_unknown(bound_name, state)
                        argument_root = _unbound_mutation_argument_root(
                            candidate,
                            state,
                            candidate_qualified_assignments,
                        )
                        if argument_root is not None:
                            argument_provenance = (
                                invalidate_class_references(candidate.args[0], state)
                                if candidate.args
                                else _irrelevant_provenance()
                            )
                            exact_attribute_mutator = any(
                                _exact_builtin_assignment_accessor(
                                    candidate.func,
                                    accessor,
                                    state,
                                    candidate_qualified_assignments,
                                )
                                for accessor in ("delattr", "setattr")
                            )
                            if not (
                                exact_attribute_mutator
                                and exact_class_provenance(argument_provenance)
                            ):
                                bind_unknown_with_contents(argument_root, state)
                        if (
                            root_name is None
                            and isinstance(candidate.func, ast.Attribute)
                            and not called_callbacks
                            and not exact_assignment_accessor
                            and not exact_assignment_lookup
                            and not known_local_container_receiver
                        ):
                            definitions = {
                                name: tuple(value for value in values if isinstance(value, ast.AST))
                                for name, values in state.items()
                            }
                            for qualified_root in _qualified_call_argument_roots(
                                candidate, definitions
                            ):
                                bind_unknown_with_contents(qualified_root, state)
                            if (
                                not candidate.args
                                and not candidate.keywords
                                and not _known_non_aliasing_call(candidate, definitions)
                                and not _known_builtin_container_expression(
                                    candidate.func.value, definitions
                                )
                            ):
                                receiver_root = _target_root_name(candidate.func.value)
                                if receiver_root is not None and any(
                                    isinstance(value, ast.Call)
                                    and (
                                        not value.args
                                        and not value.keywords
                                        or (_terminal_name(value.func) or "")[:1].isupper()
                                    )
                                    for value in state.get(receiver_root, ())
                                ):
                                    bind_unknown_with_contents(receiver_root, state)
                                    bind_all_current_objects(state)
                        if implicit_decorator and not (
                            isinstance(candidate.func, ast.Name)
                            and candidate.func.id in module_functions
                        ):
                            for bound_name in tuple(state):
                                bind_unknown_with_contents(bound_name, state)
                        for called_callback in called_callbacks:
                            called_node, _called_module, _implicit_count = called_callback
                            _, called_assignments = callback_state(called_node, state)
                            captured_roots = (
                                _mutated_free_bindings(
                                    called_node,
                                    called_assignments,
                                    qualified_assignments=expression_qualified_assignments(
                                        called_node,
                                        called_assignments,
                                    ),
                                )
                                if isinstance(
                                    called_node,
                                    (ast.AsyncFunctionDef, ast.FunctionDef),
                                )
                                else set()
                            )
                            for captured_root in captured_roots:
                                if captured_root in called_assignments:
                                    bind_unknown(captured_root, called_assignments)
                            bound = callback_call_arguments(candidate, called_callback)
                            if bound is None:
                                continue
                            for parameter_name in resolved_module_callback_mutated_parameters(
                                called_node,
                                called_assignments,
                            ):
                                actual = bound.get(parameter_name)
                                if actual is None:
                                    continue
                                actual_provenance = invalidate_class_references(actual[0], state)
                                if not exact_class_provenance(actual_provenance):
                                    for actual_root in _loaded_root_names(actual[0]):
                                        if actual_root in state:
                                            bind_unknown_with_contents(actual_root, state)
                        if isinstance(candidate.func, ast.Name):
                            if candidate.func.id in {"eval", "exec"}:
                                for bound_name in tuple(state):
                                    bind_unknown(bound_name, state)
                            if (
                                call_bindings
                                and not called_callbacks
                                and not exact_assignment_accessor
                                and not exact_assignment_lookup
                            ):
                                if (
                                    not candidate.args
                                    and not candidate.keywords
                                    and any(
                                        isinstance(binding, ast.Call) for binding in call_bindings
                                    )
                                ):
                                    bind_all_current_objects(state)
                                for argument in (
                                    *candidate.args,
                                    *(keyword.value for keyword in candidate.keywords),
                                ):
                                    for called_root in _loaded_root_names(argument):
                                        bind_unknown_with_contents(called_root, state)
                                for binding in call_bindings:
                                    if isinstance(binding, ast.expr):
                                        for captured_root in _reachable_assignment_roots(
                                            binding,
                                            state,
                                            follow_identity=True,
                                        ):
                                            bind_unknown_with_contents(captured_root, state)
                                    if (
                                        isinstance(binding, ast.Attribute)
                                        and binding.attr in MUTATING_CONTAINER_METHODS
                                    ):
                                        bound_root = _target_root_name(binding.value)
                                        if bound_root is not None:
                                            bind_unknown(bound_root, state)
                        elif (
                            not isinstance(candidate.func, ast.Attribute)
                            and not called_callbacks
                            and not exact_assignment_accessor
                            and not exact_assignment_lookup
                        ):
                            for argument in (
                                *candidate.args,
                                *(keyword.value for keyword in candidate.keywords),
                            ):
                                for called_root in _loaded_root_names(argument):
                                    bind_unknown_with_contents(called_root, state)
                            for captured_root in _reachable_assignment_roots(
                                candidate.func,
                                state,
                                follow_identity=True,
                            ):
                                bind_unknown_with_contents(captured_root, state)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target, node.value, state)
                return
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".")[0]
                    imported_name = alias.name if alias.asname else alias.name.split(".")[0]
                    state[local_name] = (_ImportBinding(module=imported_name),)
                return
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    for name in tuple(state):
                        bind_unknown(name, state)
                    return
                imported_module = _import_from_module(module, node)
                imported_assignments = (
                    resolve(imported_module, seen | {module_name})
                    if imported_module is not None
                    else {}
                )
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    candidates = imported_assignments.get(alias.name)
                    state[local_name] = candidates or (
                        _ImportBinding(
                            module=imported_module or node.module or "",
                            symbol=alias.name,
                        ),
                    )
                return
            if isinstance(node, (ast.AsyncWith, ast.With)):
                for item in node.items:
                    if item.optional_vars is not None:
                        bind_unknown_target(item.optional_vars, state)
                for child in node.body:
                    process(child, state)
                return
            if isinstance(node, ast.Delete):
                for target in node.targets:
                    bind_unknown_target(target, state)
                return
            if isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    bind_unknown_with_retained(node.target.id, state)
                else:
                    bind_unknown_target(node.target, state)
                return
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                _bind_function_annotation_provenance(node, state)
                setattr(
                    node,
                    FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                    dict(state),
                )
                state[node.name] = (
                    _FunctionBinding(
                        module=module_name,
                        symbol=node.name,
                        node=node,
                    )
                    if not node.decorator_list
                    else _UnknownBinding(),
                )
                return
            if isinstance(node, ast.ClassDef):
                setattr(
                    node,
                    CLASS_BASE_BINDINGS_ATTRIBUTE,
                    tuple(
                        base_class
                        for base in node.bases
                        for base_class in (resolve_module_class(base, state),)
                        if base_class is not None
                    ),
                )
                construction_may_execute_user_code = _class_construction_may_execute_user_code(
                    node,
                    state,
                )
                class_identity_is_stable = (
                    not node.decorator_list and not construction_may_execute_user_code
                )
                if construction_may_execute_user_code:
                    for bound_name in tuple(state):
                        bind_unknown_with_contents(bound_name, state)
                class_state = dict(state)
                for child in node.body:
                    process(child, class_state)
                setattr(
                    node,
                    CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                    dict(class_state),
                )
                for captured_root in _mutated_free_bindings(
                    node,
                    state,
                    qualified_assignments=expression_qualified_assignments(node, state),
                ):
                    if captured_root in state:
                        bind_unknown(captured_root, state)
                class_binding = (
                    _ClassBinding(
                        module=module_name,
                        symbol=node.name,
                        node=node,
                    )
                    if class_identity_is_stable
                    else _UnknownBinding()
                )
                if isinstance(class_binding, _ClassBinding):
                    class_binding.invalidated = (
                        module_name,
                        node.name,
                    ) in invalidated_class_identities
                state[node.name] = (class_binding,)
                return
            for name in _statement_bound_names(node):
                bind_unknown(name, state)

        for node in module.tree.body:
            process(node, assignments)
        resolving.pop(module_name)
        resolved[module_name] = assignments
        return assignments

    for module in sorted(modules, key=lambda candidate: candidate.module):
        resolve(module.module, frozenset())
    return resolved


def _bind_module_class_provenance(
    modules: tuple[PythonModule, ...], registry: ExternalClasses
) -> None:
    def bind_import(
        module: PythonModule,
        node: ast.ImportFrom,
        classes: ClassFields,
    ) -> None:
        if any(alias.name == "*" for alias in node.names):
            classes.clear()
            return
        imported_module = _import_from_module(module, node)
        for alias in node.names:
            local_name = alias.asname or alias.name
            fields = (
                registry.get((imported_module, alias.name)) if imported_module is not None else None
            )
            if fields is None:
                classes.pop(local_name, None)
            else:
                classes[local_name] = fields

    def shadow_statement(statement: ast.stmt, classes: ClassFields) -> None:
        for name in _statement_bound_names(statement):
            classes.pop(name, None)

    def process_class_body(
        module: PythonModule,
        node: ast.ClassDef,
        inherited_classes: ClassFields,
    ) -> None:
        classes = dict(inherited_classes)
        for child in node.body:
            if isinstance(child, ast.AnnAssign):
                _bind_annotation_class_provenance(child.annotation, classes)
                if child.value is not None:
                    shadow_statement(child, classes)
                continue
            if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef)):
                _bind_function_class_provenance(child, classes)
                classes.pop(child.name, None)
                continue
            if isinstance(child, ast.ImportFrom):
                bind_import(module, child, classes)
                continue
            if isinstance(child, (ast.AsyncWith, ast.With)):
                shadow_statement(child, classes)
                continue
            shadow_statement(child, classes)

    for module in modules:
        classes: ClassFields = {}
        for node in module.tree.body:
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                _bind_function_class_provenance(node, classes)
                classes.pop(node.name, None)
                continue
            if isinstance(node, ast.ClassDef):
                process_class_body(module, node, classes)
                classes[node.name] = registry[(module.module, node.name)]
                continue
            if isinstance(node, ast.ImportFrom):
                bind_import(module, node, classes)
                continue
            shadow_statement(node, classes)


def _class_field_registry(
    modules: tuple[PythonModule, ...],
    module_assignments: dict[str, AssignmentMap] | None = None,
) -> ExternalClasses:
    if module_assignments is None:
        _module_assignment_registry(modules)
    registry: ExternalClasses = {}
    for module in modules:
        for node in module.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            key = (module.module, node.name)
            if key in registry:
                _fail("maintained manifest Python module redefines a top-level class")
            fields: dict[str, ast.AST] = {
                child.target.id: child.annotation
                for child in node.body
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
            }
            registry[key] = fields
    while True:
        aliases = {
            (module.module, name): fields
            for module in modules
            for name, fields in _class_bindings(module, registry).items()
            if (module.module, name) not in registry
        }
        if not aliases:
            break
        registry.update(aliases)
    _bind_module_class_provenance(modules, registry)
    return registry


def _class_bindings(module: PythonModule, external_classes: ExternalClasses) -> ClassFields:
    classes: ClassFields = {}

    def bind(module_name: str, class_name: str, local_name: str) -> None:
        fields = external_classes.get((module_name, class_name))
        if fields is None:
            classes.pop(local_name, None)
            return
        classes[local_name] = fields
        for annotation in fields.values():
            referenced = _terminal_name(annotation)
            if referenced is not None and referenced not in classes:
                bind(module_name, referenced, referenced)

    for node in module.tree.body:
        if isinstance(node, ast.ClassDef):
            bind(module.module, node.name, node.name)
            continue
        if isinstance(node, ast.ImportFrom):
            imported_module = _import_from_module(module, node)
            if any(alias.name == "*" for alias in node.names):
                classes.clear()
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                if imported_module is None:
                    classes.pop(local_name, None)
                else:
                    bind(imported_module, alias.name, local_name)
            continue
        for name in _statement_bound_names(node):
            classes.pop(name, None)
    return classes


def _retains_class_identity(
    key: tuple[str, str],
    fields: dict[str, ast.AST],
    module_assignments: dict[str, AssignmentMap],
    external_classes: ExternalClasses,
) -> bool:
    candidates = module_assignments.get(key[0], {}).get(key[1], ())
    if len(candidates) != 1 or not isinstance(candidates[0], _ClassBinding):
        return False
    binding = candidates[0]
    return (
        not binding.invalidated and external_classes.get((binding.module, binding.symbol)) is fields
    )


def _function_context_registry(
    modules: tuple[PythonModule, ...],
    module_assignments: dict[str, AssignmentMap],
    external_classes: ExternalClasses | None = None,
) -> ExternalFunctions:
    external_classes = external_classes or _class_field_registry(modules, module_assignments)
    class_assignments_by_fields = {
        id(external_classes[(module.module, node.name)]): getattr(
            node,
            CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
            {
                **module_assignments[module.module],
                **_assignment_map(
                    node,
                    qualified_assignments=module_assignments,
                ),
            },
        )
        for module in modules
        for node in module.tree.body
        if isinstance(node, ast.ClassDef)
    }
    qualified_class_assignments = {
        key: class_assignments_by_fields[id(fields)]
        for key, fields in external_classes.items()
        if id(fields) in class_assignments_by_fields
        and _retains_class_identity(key, fields, module_assignments, external_classes)
    }
    registry: ExternalFunctions = {}
    for module in modules:
        for node in module.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = (module.module, node.name)
            if key in registry:
                _fail("maintained manifest Python module redefines a top-level function")
            registry[key] = FunctionContext(
                node=node,
                source=module.path,
                module_assignments=module_assignments[module.module],
                definition_assignments=getattr(
                    node,
                    FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                    module_assignments[module.module],
                ),
                default_assignments=getattr(
                    node,
                    FUNCTION_DEFAULT_ASSIGNMENTS_ATTRIBUTE,
                    module_assignments[module.module],
                ),
            )
    while True:
        aliases = {
            (module.module, name): context
            for module in modules
            for name, context in _function_bindings(module, registry).items()
            if (module.module, name) not in registry
        }
        if not aliases:
            break
        registry.update(aliases)
    for context in registry.values():
        context.qualified_functions.update(registry)
        context.qualified_classes.update(external_classes)
        context.qualified_class_assignments.update(qualified_class_assignments)
        context.qualified_assignments.update(module_assignments)
    for module in modules:
        bindings = _function_bindings(module, registry)
        classes = _class_bindings(module, external_classes)
        for node in module.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                context = registry[(module.module, node.name)]
                context.functions.update(bindings)
                context.classes.update(classes)
    return registry


def _manifest_assignment_name(name: str) -> bool:
    lowered = name.lower()
    return lowered == "manifest" or lowered.endswith("_manifest")


def _artifact_manifest_function_name(name: str) -> bool:
    lowered = name.lower().lstrip("_")
    if lowered == "manifest":
        return True
    if not lowered.endswith("_manifest"):
        return False
    roles = {
        "artifact",
        "assemble",
        "build",
        "compose",
        "create",
        "emit",
        "generate",
        "make",
        "produce",
        "render",
        "write",
    }
    return bool(set(lowered.removesuffix("_manifest").split("_")) & roles)


def _manifest_ast_pointers(
    module: PythonModule,
    external_functions: ExternalFunctions,
    module_assignments_by_name: dict[str, AssignmentMap] | None = None,
    external_classes: ExternalClasses | None = None,
) -> set[str]:
    results: set[str] = set()
    effective_assignment_registry = module_assignments_by_name or _module_assignment_registry(
        (module,)
    )
    module_assignments = effective_assignment_registry.get(module.module)
    if module_assignments is None:
        module_assignments = _assignment_map(
            module.tree,
            qualified_assignments=effective_assignment_registry,
        )
    effective_classes = dict(
        external_classes or _class_field_registry((module,), {module.module: module_assignments})
    )
    effective_class_assignments: ExternalClassAssignments = {
        key: class_assignments
        for context in external_functions.values()
        for key, class_assignments in context.qualified_class_assignments.items()
    }
    for node in module.tree.body:
        if isinstance(node, ast.ClassDef):
            key = (module.module, node.name)
            fields = effective_classes.get(key) or {
                child.target.id: child.annotation
                for child in node.body
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
            }
            effective_classes[key] = fields
            if _retains_class_identity(
                key,
                fields,
                effective_assignment_registry,
                effective_classes,
            ):
                effective_class_assignments[key] = getattr(
                    node,
                    CLASS_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                    {
                        **module_assignments,
                        **_assignment_map(
                            node,
                            module_assignments,
                            qualified_assignments=effective_assignment_registry,
                        ),
                    },
                )
            else:
                effective_class_assignments.pop(key, None)
    classes = _class_bindings(module, effective_classes)
    local_functions = {
        node.name: external_functions.get((module.module, node.name))
        or FunctionContext(
            node=node,
            source=module.path,
            module_assignments=module_assignments,
            definition_assignments=getattr(
                node,
                FUNCTION_DEFINITION_ASSIGNMENTS_ATTRIBUTE,
                module_assignments,
            ),
            default_assignments=getattr(
                node,
                FUNCTION_DEFAULT_ASSIGNMENTS_ATTRIBUTE,
                module_assignments,
            ),
            classes=dict(classes),
            qualified_classes=dict(effective_classes),
            qualified_class_assignments=dict(effective_class_assignments),
        )
        for node in module.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    effective_functions = dict(external_functions)
    effective_functions.update(
        {(module.module, name): context for name, context in local_functions.items()}
    )
    for context in local_functions.values():
        context.qualified_functions.update(effective_functions)
        context.qualified_classes.update(effective_classes)
        context.qualified_class_assignments.update(effective_class_assignments)
        context.qualified_assignments.update(effective_assignment_registry)
    functions = _function_bindings(module, effective_functions)
    deferred_callable_ids = frozenset(id(context.node) for context in effective_functions.values())
    for context in local_functions.values():
        context.functions.update(functions)
        context.classes.update(classes)
    module_assignments = dict(module_assignments)
    _apply_helper_mutations(
        module.tree,
        module_assignments,
        functions,
        qualified_functions=effective_functions,
        qualified_assignments=effective_assignment_registry,
    )
    for node in module.tree.body:
        named_values: tuple[tuple[ast.Name, ast.expr], ...] = ()
        if isinstance(node, ast.Assign):
            named_values = tuple(
                (target, node.value) for target in node.targets if isinstance(target, ast.Name)
            )
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            named_values = ((node.target, node.value),)
        for target, value in named_values:
            if _manifest_assignment_name(target.id) and isinstance(value, ast.Dict) and value.keys:
                for pointer in _resolve_dict_expression(
                    ast.Name(id=target.id, ctx=ast.Load()),
                    module_assignments,
                    source=module.path,
                    functions=functions,
                    classes=classes,
                ):
                    results.add(f"assignment:module:{target.id}{pointer}")
    scopes: list[tuple[str, FunctionContext]] = [
        (function.node.name, function) for function in local_functions.values()
    ]
    for scope_name, context in scopes:
        scope = context.node
        manifest_assignments: list[tuple[str, ast.expr]] = []
        for walked_node in _lexical_nodes(scope):
            named_values = ()
            if isinstance(walked_node, ast.Assign):
                named_values = tuple(
                    (target, walked_node.value)
                    for target in walked_node.targets
                    if isinstance(target, ast.Name)
                )
            elif (
                isinstance(walked_node, ast.AnnAssign)
                and isinstance(walked_node.target, ast.Name)
                and walked_node.value is not None
            ):
                named_values = ((walked_node.target, walked_node.value),)
            manifest_assignments.extend(
                (target.id, value)
                for target, value in named_values
                if _manifest_assignment_name(target.id)
                and isinstance(value, ast.Dict)
                and value.keys
            )
        if manifest_assignments:
            assignments = dict(module_assignments)
            assignments.update(
                _assignment_map(
                    scope,
                    module_assignments,
                    qualified_assignments=effective_assignment_registry,
                    deferred_callable_ids=deferred_callable_ids,
                )
            )
            _apply_helper_mutations(
                scope,
                assignments,
                functions,
                qualified_functions=effective_functions,
                qualified_assignments=effective_assignment_registry,
            )
            parameters = _function_parameter_annotations(context.node)
            for target_name, _value in manifest_assignments:
                for pointer in _resolve_dict_expression(
                    ast.Name(id=target_name, ctx=ast.Load()),
                    assignments,
                    source=module.path,
                    functions=functions,
                    classes=classes,
                    parameters=parameters,
                ):
                    results.add(f"assignment:{scope_name}:{target_name}{pointer}")
    for context in local_functions.values():
        function = context.node
        if not _artifact_manifest_function_name(function.name):
            continue
        assignments = dict(module_assignments)
        assignments.update(
            _assignment_map(
                function,
                module_assignments,
                qualified_assignments=effective_assignment_registry,
                deferred_callable_ids=deferred_callable_ids,
            )
        )
        _apply_helper_mutations(
            function,
            assignments,
            functions,
            qualified_functions=effective_functions,
            qualified_assignments=effective_assignment_registry,
        )
        parameters = _function_parameter_annotations(function)
        return_values = _return_values(
            function, source=f"{module.path}: manifest builder {function.name}"
        )
        for return_value in return_values:
            for pointer in _resolve_dict_expression(
                return_value,
                assignments,
                source=module.path,
                functions=functions,
                classes=classes,
                parameters=parameters,
            ):
                results.add(f"function:{function.name}{pointer}")
    return results


def _validate_checksum_pinned_manifest_leaves(
    root: Path, modules: tuple[PythonModule, ...]
) -> None:
    modules_by_path = {module.path: module for module in modules}
    declared_paths = set(CHECKSUM_PINNED_MANIFEST_LEAVES)
    present_paths = declared_paths & set(modules_by_path)
    if not present_paths:
        return
    if present_paths != declared_paths:
        _fail("checksum-pinned manifest leaf source set is incomplete")
    for path, (expected_digest, declarations) in CHECKSUM_PINNED_MANIFEST_LEAVES.items():
        module = modules_by_path.get(path)
        if module is None:
            _fail(f"checksum-pinned manifest leaf source is not maintained: {path}")
        actual_digest = hashlib.sha256(_regular_file(root, path).read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            _fail(f"checksum-pinned manifest leaf source changed: {path}")
        available = {
            (getattr(node, "lineno", 0), getattr(node, "col_offset", 0), ast.unparse(node))
            for node in ast.walk(module.tree)
        }
        if len(declarations) != len(set(declarations)) or not set(declarations).issubset(available):
            _fail(f"checksum-pinned manifest leaf declarations are stale: {path}")


def _validate_checksum_pinned_manifest_subtrees(
    root: Path, modules: tuple[PythonModule, ...]
) -> None:
    modules_by_path = {module.path: module for module in modules}
    declared_paths = set(CHECKSUM_PINNED_MANIFEST_SUBTREES)
    present_paths = declared_paths & set(modules_by_path)
    if not present_paths:
        return
    if present_paths != declared_paths:
        _fail("checksum-pinned manifest subtree source set is incomplete")
    for path, (
        expected_digest,
        producer_path,
        producer_digest,
        declarations,
    ) in CHECKSUM_PINNED_MANIFEST_SUBTREES.items():
        module = modules_by_path.get(path)
        if module is None:
            _fail(f"checksum-pinned manifest subtree source is not maintained: {path}")
        actual_digest = hashlib.sha256(_regular_file(root, path).read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            _fail(f"checksum-pinned manifest subtree source changed: {path}")
        if producer_path not in modules_by_path:
            _fail(f"checksum-pinned manifest subtree producer is not maintained: {producer_path}")
        actual_producer_digest = hashlib.sha256(
            _regular_file(root, producer_path).read_bytes()
        ).hexdigest()
        if actual_producer_digest != producer_digest:
            _fail(f"checksum-pinned manifest subtree producer changed: {producer_path}")
        available = {
            (getattr(node, "lineno", 0), getattr(node, "col_offset", 0), ast.unparse(node))
            for node in ast.walk(module.tree)
        }
        producer_mappings = {
            (node.lineno, node.col_offset, ast.unparse(node)): node
            for node in ast.walk(modules_by_path[producer_path].tree)
            if isinstance(node, (ast.Dict, ast.DictComp))
        }
        identities = {
            (line, column, expression)
            for line, column, expression, _producer_identity, _pointers in declarations
        }
        pointer_sets = [
            pointers for _line, _column, _expression, _producer_identity, pointers in declarations
        ]
        if (
            len(identities) != len(declarations)
            or not identities.issubset(available)
            or any(
                not pointers
                or len(pointers) != len(set(pointers))
                or any(not pointer.startswith("/") for pointer in pointers)
                for pointers in pointer_sets
            )
        ):
            _fail(f"checksum-pinned manifest subtree declarations are stale: {path}")
        for _line, _column, _expression, producer_identity, pointers in declarations:
            producer = producer_mappings.get(producer_identity)
            if producer is None:
                _fail(f"checksum-pinned manifest subtree producer declaration is stale: {path}")
            if isinstance(producer, ast.DictComp):
                produced_pointers = {"/*"}
            else:
                if any(
                    not isinstance(key, ast.Constant) or not isinstance(key.value, str)
                    for key in producer.keys
                ):
                    _fail(f"checksum-pinned manifest subtree producer declaration is stale: {path}")
                produced_pointers = {
                    f"/*/{_pointer_token(key.value)}"
                    for key in producer.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
            if produced_pointers != set(pointers):
                _fail(f"checksum-pinned manifest subtree producer keys changed: {path}")


def _manifest_rows(
    root: Path, tracked: tuple[str, ...], modules: tuple[PythonModule, ...]
) -> tuple[list[JsonObject], int]:
    rows: list[JsonObject] = []
    _validate_checksum_pinned_manifest_leaves(root, modules)
    _validate_checksum_pinned_manifest_subtrees(root, modules)
    module_assignments = _module_assignment_registry(modules)
    external_classes = _class_field_registry(modules, module_assignments)
    external_functions = _function_context_registry(
        modules,
        module_assignments,
        external_classes,
    )
    manifest_documents = tuple(
        path
        for path in tracked
        if path.lower().endswith(".json") and "manifest" in PurePosixPath(path).name.lower()
    )
    for relative in manifest_documents:
        value = _read_json(_regular_file(root, relative))
        for pointer in sorted(_json_key_pointers(value)):
            key = f"json:{relative}:{pointer}"
            rows.append(
                _row(
                    root=root,
                    family="manifest_keys",
                    key=key,
                    name=f"{relative}{pointer}",
                    statement=(
                        f"Strict JSON discovery observes artifact manifest key {pointer} in "
                        f"{relative}; the observation does not expand support."
                    ),
                    source=_source(root, relative, pointer),
                )
            )
    csv_path = "evidence/manifest.csv"
    if csv_path not in tracked:
        _fail("canonical evidence manifest CSV is not tracked")
    try:
        with _regular_file(root, csv_path).open(newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream, strict=True)
            records = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DiscoveryError(f"cannot parse manifest CSV {csv_path}: {exc}") from exc
    if not records:
        _fail("manifest CSV must contain a header")
    header = records[0]
    if not header or any(not value for value in header) or len(header) != len(set(header)):
        _fail("manifest CSV header must be non-empty and unique")
    if any(len(record) != len(header) for record in records[1:]):
        _fail("manifest CSV records must match the header width")
    for column in header:
        locator = f"/header/{_pointer_token(column)}"
        rows.append(
            _row(
                root=root,
                family="manifest_keys",
                key=f"csv:{csv_path}:{locator}",
                name=f"{csv_path}{locator}",
                statement=(
                    f"Strict CSV discovery observes artifact manifest column {column} in "
                    f"{csv_path}; the observation does not expand support."
                ),
                source=_source(root, csv_path, locator),
            )
        )
    for module in modules:
        for locator in sorted(
            _manifest_ast_pointers(
                module,
                external_functions,
                module_assignments,
                external_classes,
            )
        ):
            rows.append(
                _row(
                    root=root,
                    family="manifest_keys",
                    key=f"ast:{module.path}:{locator}",
                    name=f"{module.module}:{locator}",
                    statement=(
                        f"Static AST discovery observes literal artifact manifest key {locator} "
                        f"in {module.module}; no discovered module was imported or executed."
                    ),
                    source=_source(root, module.path, locator),
                )
            )
        for model, model_kind in _model_nodes(module):
            if "manifest" not in model.name.lower():
                continue
            for field in _model_fields(model, model_kind):
                locator = f"model:{module.module}:{model.name}.{field}"
                rows.append(
                    _row(
                        root=root,
                        family="manifest_keys",
                        key=locator,
                        name=locator,
                        statement=(
                            f"Static model discovery observes declared manifest field {field} on "
                            f"{module.module}:{model.name}; no runtime schema was generated."
                        ),
                        source=_source(root, module.path, locator),
                    )
                )
    return rows, len(manifest_documents)


def _is_config_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    name = path.name.lower()
    parts = tuple(part.lower() for part in path.parts)
    exact = {
        ".pre-commit-config.yaml",
        "compose.yaml",
        "config.example.yaml",
        "mkdocs.yml",
        "pyproject.toml",
        "uv.lock",
    }
    return (
        name in exact
        or "config" in parts[:-1]
        or parts[0] in {"calib", "configs"}
        or (parts[0] == ".github" and path.suffix.lower() in {".yml", ".yaml"})
        or name.startswith("config.")
    )


def _validate_config(root: Path, relative: str) -> str:
    path = _repository_entry(root, relative)
    if stat.S_ISLNK(path.lstat().st_mode):
        _path_digest(root, relative)
        return "safe tracked-symlink"
    regular = _regular_file(root, relative)
    name = regular.name.lower()
    suffix = regular.suffix.lower()
    parser_name = ""
    try:
        if suffix == ".toml" or name == "uv.lock":
            _read_toml(regular)
            parser_name = "strict TOML"
        elif suffix == ".json":
            _read_json(regular, require_object=False)
            parser_name = "strict JSON"
        elif suffix in {".yaml", ".yml"}:
            _read_yaml(regular)
            parser_name = "strict YAML"
        elif suffix in {".cfg", ".ini"}:
            parser = configparser.ConfigParser(strict=True)
            with regular.open(encoding="utf-8") as stream:
                parser.read_file(stream)
            parser_name = "strict INI"
        elif suffix == ".csv":
            with regular.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream, strict=True))
            if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
                _fail(f"configuration CSV is empty or non-rectangular: {relative}")
            parser_name = "strict CSV"
        elif suffix == ".py":
            _parse_python(root, relative)
            parser_name = "static Python AST"
        elif suffix == ".md":
            regular.read_text(encoding="utf-8")
            parser_name = "UTF-8 text"
        else:
            _fail(f"maintained configuration has no governed parser: {relative}")
    except (OSError, UnicodeError, csv.Error, configparser.Error) as exc:
        error = DiscoveryError(f"cannot parse configuration {relative}: {exc}")
    except DiscoveryError as exc:
        error = exc
    else:
        return parser_name

    expected_digest = RETAINED_INVALID_CONFIGS.get(relative)
    if expected_digest is not None and _path_digest(root, relative) == expected_digest:
        return "checksum-pinned retained-invalid"
    raise error


def _resource_facet(relative: str) -> str:
    first = PurePosixPath(relative).parts[0]
    if relative.startswith(".github/workflows/"):
        return "workflow"
    if _is_config_path(relative):
        return "configuration"
    return {
        "adapters": "adapter",
        "benchmarks": "benchmark",
        "calib": "calibration",
        "datasets": "dataset",
        "docker": "container",
        "docs": "documentation",
        "evidence": "evidence",
        "examples": "example",
        "fuzz": "fuzzing",
        "integrations": "integration",
        "metriplane": "package",
        "proofs": "proof",
        "schemas": "schema",
        "scripts": "tooling",
        "tests": "test",
        "tools": "tooling",
        "web": "web_asset",
    }.get(first, "repository_metadata")


def _resource_rows(
    root: Path, tracked: tuple[str, ...]
) -> tuple[list[JsonObject], dict[str, int], dict[str, int]]:
    rows: list[JsonObject] = []
    facets: Counter[str] = Counter()
    config_parsers: Counter[str] = Counter()
    retained_invalid: set[str] = set()
    for relative in tracked:
        if relative in GENERATED_TARGETS:
            continue
        facet = _resource_facet(relative)
        facets[facet] += 1
        rows.append(
            _row(
                root=root,
                family="resources",
                key=relative,
                name=relative,
                statement=(
                    f"The Git index observes maintained {facet} resource {relative}; its byte "
                    "identity is inventoried without making a support claim."
                ),
                source=_source(root, relative, f"tracked {facet} resource"),
            )
        )
        if _is_config_path(relative):
            parser_name = _validate_config(root, relative)
            config_parsers[parser_name] += 1
            if parser_name == "checksum-pinned retained-invalid":
                retained_invalid.add(relative)
                statement = (
                    f"Strict parsing rejects retained compatibility configuration {relative}; "
                    "only its exact checksum-pinned bytes remain inventoried, and any change "
                    "fails closed."
                )
                locator = "checksum-pinned retained-invalid configuration"
            else:
                statement = (
                    f"{parser_name} discovery observes maintained configuration {relative}; "
                    "the row does not establish deployment support."
                )
                locator = f"{parser_name} maintained configuration"
            rows.append(
                _row(
                    root=root,
                    family="configs",
                    key=relative,
                    name=relative,
                    statement=statement,
                    source=_source(root, relative, locator),
                )
            )
        if "examples" in PurePosixPath(relative).parts:
            rows.append(
                _row(
                    root=root,
                    family="examples",
                    key=relative,
                    name=relative,
                    statement=(
                        f"Tracked-path discovery observes maintained example {relative}; examples "
                        "are not support or provider-state claims."
                    ),
                    source=_source(root, relative, "maintained example"),
                )
            )
        if PurePosixPath(relative).parts[0] in {"evidence", "proofs"}:
            rows.append(
                _row(
                    root=root,
                    family="proofs",
                    key=relative,
                    name=relative,
                    statement=(
                        f"Tracked-path discovery observes retained proof resource {relative}; the "
                        "inventory preserves its claim boundary without upgrading it."
                    ),
                    source=_source(root, relative, "maintained proof resource"),
                )
            )
    if retained_invalid != set(RETAINED_INVALID_CONFIGS):
        _fail("retained-invalid configuration exception set is stale or incomplete")
    return rows, dict(sorted(facets.items())), dict(sorted(config_parsers.items()))


def _workflow_rows(root: Path, tracked: tuple[str, ...]) -> tuple[list[JsonObject], int]:
    rows: list[JsonObject] = []
    workflows = tuple(
        path
        for path in tracked
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    )
    if not workflows:
        _fail("repository has no maintained workflows")
    for relative in workflows:
        document = _read_yaml(_regular_file(root, relative))
        if not isinstance(document, dict):
            _fail(f"workflow root must be a mapping: {relative}")
        name = document.get("name", relative)
        jobs = document.get("jobs")
        if not isinstance(name, str) or not name:
            _fail(f"workflow name must be a non-empty string: {relative}")
        if not isinstance(jobs, dict) or not jobs:
            _fail(f"workflow jobs must be a non-empty mapping: {relative}")
        rows.append(
            _row(
                root=root,
                family="workflows",
                key=relative,
                name=name,
                statement=(
                    f"Strict YAML discovery observes maintained workflow {name} at {relative}; "
                    "inventory does not assert hosted execution success."
                ),
                source=_source(root, relative, "workflow declaration"),
            )
        )
        for job_id, job in sorted(jobs.items()):
            if not isinstance(job_id, str) or not job_id or not isinstance(job, dict):
                _fail(f"workflow jobs must be named mappings: {relative}")
            rows.append(
                _row(
                    root=root,
                    family="jobs",
                    key=f"{relative}:{job_id}",
                    name=f"{name} / {job_id}",
                    statement=(
                        f"Strict YAML discovery observes authored job {job_id} in {relative}; "
                        "inventory does not assert hosted execution success."
                    ),
                    source=_source(root, relative, f"jobs.{job_id}"),
                )
            )
    return rows, len(workflows)


def _array(document: JsonObject, field: str, *, label: str) -> list[JsonObject]:
    value = document.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        _fail(f"{label}.{field} must be an array of objects")
    return value


def _foreign_objects(
    inventory: JsonObject, profiles: JsonObject
) -> tuple[list[JsonObject], list[JsonObject]]:
    foreign_rows: list[JsonObject] = []
    for row in _array(inventory, "rows", label="inventory"):
        owned_id = str(row.get("id", "")).startswith(ROW_PREFIX)
        owned_owner = row.get("owner") == TASK_ID
        if owned_id != owned_owner:
            _fail(f"MP2-013 row ID and owner disagree: {row.get('id')}")
        if not owned_id:
            foreign_rows.append(copy.deepcopy(row))
    foreign_profiles: list[JsonObject] = []
    for profile in _array(profiles, "profiles", label="profiles"):
        owned_id = profile.get("id") == PROFILE_ID
        owned_owner = profile.get("owner") == TASK_ID
        if owned_id != owned_owner:
            _fail(f"MP2-013 profile ID and owner disagree: {profile.get('id')}")
        if not owned_id:
            foreign_profiles.append(copy.deepcopy(profile))
    return foreign_rows, foreign_profiles


def _claim_rows(
    root: Path, foreign_rows: list[JsonObject], foreign_profiles: list[JsonObject]
) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for registry, path, values in (
        ("functional row", INVENTORY_PATH, foreign_rows),
        ("support profile", PROFILES_PATH, foreign_profiles),
    ):
        for value in values:
            identifier = value.get("id")
            claim = value.get("claim")
            if not isinstance(identifier, str) or not isinstance(claim, dict):
                _fail(f"{registry} has no canonical ID and claim")
            classification = claim.get("classification")
            if not isinstance(classification, str):
                _fail(f"{registry} claim classification is not canonical: {identifier}")
            key = f"{registry}:{identifier}"
            rows.append(
                _row(
                    root=root,
                    family="current_claims",
                    key=key,
                    name=key,
                    statement=(
                        f"Canonical registry discovery observes the current {classification} claim "
                        f"on {registry} {identifier} without changing or upgrading that claim."
                    ),
                    source=_source(
                        root,
                        SCANNER_PATH,
                        f"{path}:{identifier}:claim-sha256:{_digest(claim)}",
                        source_type="generated_registry",
                    ),
                    criteria=("MP2-013.A02",),
                )
            )
    return rows


def discover(
    repository_root: Path,
    *,
    inventory: JsonObject | None = None,
    profiles: JsonObject | None = None,
    tracked_paths: tuple[str, ...] | None = None,
) -> Discovery:
    root = repository_root.resolve(strict=True)
    tracked = tracked_paths or _tracked_paths(root)
    if list(tracked) != sorted(set(tracked)):
        _fail("injected tracked paths must be unique and sorted")
    inventory_document = inventory or _read_json(_regular_file(root, INVENTORY_PATH))
    profiles_document = profiles or _read_json(_regular_file(root, PROFILES_PATH))
    foreign_rows, foreign_profiles = _foreign_objects(inventory_document, profiles_document)
    packaged_modules = _packaged_modules(root, tracked)
    manifest_modules = _manifest_modules(root, tracked, packaged_modules)
    rows = _python_rows(root, packaged_modules)
    manifest_rows, manifest_documents = _manifest_rows(root, tracked, manifest_modules)
    rows.extend(manifest_rows)
    resource_rows, facets, config_parsers = _resource_rows(root, tracked)
    rows.extend(resource_rows)
    workflow_rows, workflow_count = _workflow_rows(root, tracked)
    rows.extend(workflow_rows)
    rows.extend(_claim_rows(root, foreign_rows, foreign_profiles))
    rows.sort(key=lambda item: item["id"])
    ids = [str(item["id"]) for item in rows]
    if len(ids) != len(set(ids)):
        _fail("normalized public-surface row IDs collide")
    family_rows = {
        family: [row for row in rows if row["kind"] == kind] for family, kind in FAMILY_KIND.items()
    }
    family_counts = {family: len(values) for family, values in sorted(family_rows.items())}
    if any(count == 0 for count in family_counts.values()):
        empty = [family for family, count in family_counts.items() if count == 0]
        _fail(f"required public-surface families are empty: {empty}")
    return Discovery(
        config_parser_counts=config_parsers,
        family_counts=family_counts,
        family_digests={family: _digest(values) for family, values in sorted(family_rows.items())},
        resource_facets=facets,
        source_counts={
            "generated_targets_excluded": len(GENERATED_TARGETS),
            "manifest_json_documents": manifest_documents,
            "manifest_python_modules": len(manifest_modules),
            "packaged_python_modules": len(packaged_modules),
            "tracked_python_paths": sum(path.endswith(".py") for path in tracked),
            "tracked_paths": len(tracked),
            "workflow_documents": workflow_count,
        },
        rows=tuple(rows),
    )


def _profile(root: Path) -> JsonObject:
    return {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": [],
            "statement": (
                "Static parser-backed repository discovery at current source bytes; this profile "
                "makes no runtime, platform, hosted-provider, or support claim."
            ),
        },
        "id": PROFILE_ID,
        "kind": "repository_public_surface_discovery",
        "owner": TASK_ID,
        "source": _source(root, SCANNER_PATH, "canonical public-surface discovery scanner"),
        "status": "active",
        "support_disposition": "not_measured",
        "test": "MP2-013.OBL.PROFILE",
    }


def _validate_pair(
    root: Path,
    inventory: JsonObject,
    profiles: JsonObject,
    *,
    require_owned_projection: bool = False,
) -> None:
    if inventory.get("schema_version") != "metriplane.functional-inventory.v1":
        _fail("inventory schema version is not canonical")
    if profiles.get("schema_version") != "metriplane.support-profiles.v1":
        _fail("support-profile schema version is not canonical")
    rows = _array(inventory, "rows", label="inventory")
    profile_rows = _array(profiles, "profiles", label="profiles")
    for label, values in (("row", rows), ("profile", profile_rows)):
        ids: list[str] = []
        for item in values:
            identifier = item.get("id")
            if not isinstance(identifier, str):
                _fail(f"{label} IDs must be strings")
            ids.append(identifier)
        if ids != sorted(set(ids)):
            _fail(f"{label} IDs must be unique and canonically sorted")
    if inventory.get("rows_sha256") != _digest(rows):
        _fail("inventory rows_sha256 is stale")
    if profiles.get("profiles_sha256") != _digest(profile_rows):
        _fail("support profiles_sha256 is stale")
    profile_ids = {str(profile["id"]) for profile in profile_rows}
    for row in rows:
        if row.get("status") in {"active", "deprecated"} and row.get("profile") not in profile_ids:
            _fail(f"functional row has no profile binding: {row.get('id')}")
        if require_owned_projection and str(row.get("id", "")).startswith(ROW_PREFIX):
            if (
                row.get("owner") != TASK_ID
                or row.get("profile") != PROFILE_ID
                or row.get("status") != "active"
                or row.get("test") not in set(FAMILY_OBLIGATION.values())
                or row.get("consumer_task_ids") != list(CONSUMERS)
                or row.get("validator_ids") != [INVENTORY_VALIDATOR]
            ):
                _fail(f"generated row lineage is invalid: {row.get('id')}")
            claim = row.get("claim")
            if (
                not isinstance(claim, dict)
                or claim.get("classification") != "observed_not_supported"
            ):
                _fail(f"generated row expands support: {row.get('id')}")
            source = row.get("source")
            if not isinstance(source, dict):
                _fail(f"generated row source is invalid: {row.get('id')}")
            if source.get("type") in {"generated_registry", "repository_discovery"}:
                path = source.get("path")
                if not isinstance(path, str) or source.get("digest_sha256") != _path_digest(
                    root, path
                ):
                    _fail(f"generated row source digest is stale: {row.get('id')}")
                if source.get("type") == "generated_registry" and "claim-sha256:" not in str(
                    source.get("locator", "")
                ):
                    _fail(f"generated claim locator is not digest-bound: {row.get('id')}")
            else:
                _fail(f"generated row source type is invalid: {row.get('id')}")
    owned_profiles = [profile for profile in profile_rows if profile.get("owner") == TASK_ID]
    if require_owned_projection:
        if len(owned_profiles) != 1 or owned_profiles[0].get("id") != PROFILE_ID:
            _fail("MP2-013 must own exactly one canonical support profile")
        owned = owned_profiles[0]
        claim = owned.get("claim")
        if (
            owned.get("support_disposition") != "not_measured"
            or not isinstance(claim, dict)
            or claim.get("classification") != "observed_not_supported"
        ):
            _fail("MP2-013 profile improperly expands support")


def _markdown(
    discovery: Discovery, inventory: JsonObject, profiles: JsonObject, profile: JsonObject
) -> str:
    family_rows = [
        f"| `{family}` | {discovery.family_counts[family]} | `{discovery.family_digests[family]}` |"
        for family in sorted(discovery.family_counts)
    ]
    facet_rows = [
        f"| `{facet}` | {count} |" for facet, count in sorted(discovery.resource_facets.items())
    ]
    source_rows = [
        f"| `{name}` | {count} |" for name, count in sorted(discovery.source_counts.items())
    ]
    parser_rows = [
        f"| `{name}` | {count} |" for name, count in sorted(discovery.config_parser_counts.items())
    ]
    lines = [
        "# Public surface inventory",
        "",
        "This document is generated from the same static discovery object as the canonical",
        "functional inventory. It inventories observations only and makes no runtime, platform,",
        "hosted-provider, safety, or support claim.",
        "",
        "## Canonical projection",
        "",
        f"- Task: `{TASK_ID}` / `{ISSUE_ID}`",
        f"- Materialization: `{MATERIALIZATION_SHA256}`",
        f"- Owned rows: `{len(discovery.rows)}`",
        f"- Owned rows SHA-256: `{_digest(list(discovery.rows))}`",
        f"- Functional rows SHA-256: `{inventory['rows_sha256']}`",
        f"- Owned profile SHA-256: `{_digest(profile)}`",
        f"- Support profiles SHA-256: `{profiles['profiles_sha256']}`",
        "- Support disposition: `not_measured`",
        "",
        "## Discovery families",
        "",
        "| Family | Rows | Canonical row SHA-256 |",
        "| --- | ---: | --- |",
        *family_rows,
        "",
        "## Resource facets",
        "",
        "| Facet | Tracked paths |",
        "| --- | ---: |",
        *facet_rows,
        "",
        "## Source census",
        "",
        "| Source | Count |",
        "| --- | ---: |",
        *source_rows,
        "",
        "## Configuration parsers",
        "",
        "| Parser result | Files |",
        "| --- | ---: |",
        *parser_rows,
        "",
        "## Parser and trust boundaries",
        "",
        "- Python modules are parsed with `ast`; discovered modules are never imported or executed.",
        "- Project/package declarations and maintained TOML configurations use `tomllib`.",
        "- JSON rejects duplicate keys and non-finite constants; YAML rejects duplicate or non-string keys.",
        "- Artifact CSV headers use the strict CSV parser; workflow and job declarations use strict YAML.",
        "- Exact checksum-pinned retained-invalid v0.2 provenance configurations: "
        + ", ".join(f"`{path}`" for path in sorted(RETAINED_INVALID_CONFIGS))
        + "; changed bytes or any additional malformed configuration fail closed.",
        "- Dynamic `__all__`, wildcard imports, unproved manifest mappings or values, unsafe symlinks, and stale source digests fail closed.",
        f"- {sum(len(nodes) for _digest_value, nodes in CHECKSUM_PINNED_MANIFEST_LEAVES.values())} non-literal manifest payload leaves are accepted only at exact source-hash and AST-location proofs; any changed source byte fails closed.",
        f"- {sum(len(nodes) for _source_digest, _producer_path, _producer_digest, nodes in CHECKSUM_PINNED_MANIFEST_SUBTREES.values())} non-literal structured manifest payloads expand only to checksum-pinned producer keys; any changed consumer or producer source byte fails closed.",
        "- The three generated targets are excluded from direct resource-byte rows to avoid self-reference and are bound by candidate parity checks.",
        "- Generation privately stages every target and durably journals the prior set before replacement; interrupted prepared transactions recover the prior set, while committed transactions verify the new set before cleanup. Individual replacements are atomic, but POSIX does not provide one atomic rename spanning all three paths.",
        "- Foreign functional rows and support profiles are preserved exactly; current claims are projected from canonical claim-object digests.",
        "",
    ]
    return "\n".join(lines)


def build_candidates(
    repository_root: Path,
    inventory_path: Path,
    profiles_path: Path,
    docs_path: Path,
    *,
    tracked_paths: tuple[str, ...] | None = None,
) -> tuple[JsonObject, JsonObject, str, Discovery]:
    root = repository_root.resolve(strict=True)
    inventory = _read_json(inventory_path)
    profiles = _read_json(profiles_path)
    _validate_pair(root, inventory, profiles)
    foreign_rows, foreign_profiles = _foreign_objects(inventory, profiles)
    discovery = discover(
        root,
        inventory=inventory,
        profiles=profiles,
        tracked_paths=tracked_paths,
    )
    candidate_inventory = copy.deepcopy(inventory)
    candidate_inventory["rows"] = sorted(
        [*foreign_rows, *copy.deepcopy(list(discovery.rows))], key=lambda item: item["id"]
    )
    candidate_inventory["rows_sha256"] = _digest(candidate_inventory["rows"])
    owned_profile = _profile(root)
    candidate_profiles = copy.deepcopy(profiles)
    candidate_profiles["profiles"] = sorted(
        [*foreign_profiles, owned_profile], key=lambda item: item["id"]
    )
    candidate_profiles["profiles_sha256"] = _digest(candidate_profiles["profiles"])
    if [row for row in candidate_inventory["rows"] if row.get("owner") != TASK_ID] != foreign_rows:
        _fail("candidate generation changed or reordered foreign functional rows")
    if [
        row for row in candidate_profiles["profiles"] if row.get("owner") != TASK_ID
    ] != foreign_profiles:
        _fail("candidate generation changed or reordered foreign support profiles")
    _validate_pair(
        root,
        candidate_inventory,
        candidate_profiles,
        require_owned_projection=True,
    )
    markdown = _markdown(discovery, candidate_inventory, candidate_profiles, owned_profile)
    if docs_path.name != PurePosixPath(DOCS_PATH).name:
        _fail("public-surface documentation target is not canonical")
    return candidate_inventory, candidate_profiles, markdown, discovery


def _stage(path: Path, payload: bytes, *, mode: int | None = None) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    staged = Path(raw_path)
    try:
        target_mode = (
            mode
            if mode is not None
            else stat.S_IMODE(path.stat().st_mode)
            if path.exists()
            else 0o644
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), target_mode)
            os.fsync(stream.fileno())
        return staged
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        staged.unlink(missing_ok=True)
        raise


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _generation_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        _fail("generation lock requires no-follow open support")
    flags = os.O_CLOEXEC | os.O_RDWR | no_follow
    created = False
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise DiscoveryError(
                f"cannot open generation lock as a regular non-symlink file: {exc}"
            ) from exc
    except OSError as exc:
        raise DiscoveryError(
            f"cannot open generation lock as a regular non-symlink file: {exc}"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail("generation lock must be a regular non-symlink file")
        if info.st_nlink != 1:
            _fail("generation lock must have exactly one link")
        if created:
            os.fchmod(descriptor, 0o600)
        elif stat.S_IMODE(info.st_mode) != 0o600:
            _fail("existing generation lock must have mode 600")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, operation)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class _TransactionTarget:
    path: Path
    old_payload: bytes | None
    old_mode: int | None
    new_sha256: str
    new_mode: int
    staged: Path


def _transaction_journal(paths: tuple[Path, ...]) -> Path:
    if not paths:
        _fail("public-surface generation has no targets")
    parents = {path.parent for path in paths}
    if len(parents) != 1:
        _fail("public-surface generation targets must share one directory")
    names = [path.name for path in paths]
    if len(names) != len(set(names)) or TRANSACTION_JOURNAL_NAME in names:
        _fail("public-surface generation target names are invalid")
    return next(iter(parents)) / TRANSACTION_JOURNAL_NAME


def _journal_present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DiscoveryError(f"cannot inspect generation transaction journal: {exc}") from exc
    return True


def _write_transaction_journal(path: Path, record: JsonObject) -> None:
    staged = _stage(path, _document_bytes(record), mode=0o600)
    try:
        os.replace(staged, path)
        _sync_directory(path.parent)
    finally:
        staged.unlink(missing_ok=True)


def _transaction_record(
    journal: Path, expected_paths: tuple[Path, ...]
) -> tuple[str, tuple[_TransactionTarget, ...]]:
    try:
        info = journal.lstat()
    except OSError as exc:
        raise DiscoveryError(f"cannot inspect generation transaction journal: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail("generation transaction journal must be a regular non-symlink file")
    value = _read_json(journal)
    if set(value) != {"schema_version", "state", "targets"}:
        _fail("generation transaction journal shape is invalid")
    if value.get("schema_version") != TRANSACTION_SCHEMA or value.get("state") not in {
        "committed",
        "prepared",
    }:
        _fail("generation transaction journal state is invalid")
    raw_targets = value.get("targets")
    if not isinstance(raw_targets, list):
        _fail("generation transaction targets are invalid")
    expected = {path.name: path for path in expected_paths}
    parsed: list[_TransactionTarget] = []
    seen_names: set[str] = set()
    for raw in raw_targets:
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "new_mode",
            "new_sha256",
            "old_mode",
            "old_payload_base64",
            "old_sha256",
            "staged_name",
        }:
            _fail("generation transaction target shape is invalid")
        name = raw["name"]
        staged_name = raw["staged_name"]
        new_mode = raw["new_mode"]
        new_sha256 = raw["new_sha256"]
        if (
            not isinstance(name, str)
            or name not in expected
            or name in seen_names
            or not isinstance(staged_name, str)
            or Path(staged_name).name != staged_name
            or not staged_name.startswith(f".{name}.")
            or not staged_name.endswith(".tmp")
            or type(new_mode) is not int
            or not 0 <= new_mode <= 0o7777
            or not isinstance(new_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", new_sha256) is None
        ):
            _fail("generation transaction target identity is invalid")
        old_payload_raw = raw["old_payload_base64"]
        old_mode = raw["old_mode"]
        old_sha256 = raw["old_sha256"]
        old_payload: bytes | None
        if old_payload_raw is None:
            if old_mode is not None or old_sha256 is not None:
                _fail("absent generation transaction target has old metadata")
            old_payload = None
        else:
            if (
                not isinstance(old_payload_raw, str)
                or type(old_mode) is not int
                or not 0 <= old_mode <= 0o7777
                or not isinstance(old_sha256, str)
            ):
                _fail("generation transaction rollback metadata is invalid")
            try:
                old_payload = base64.b64decode(old_payload_raw, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise DiscoveryError("generation transaction rollback payload is invalid") from exc
            if hashlib.sha256(old_payload).hexdigest() != old_sha256:
                _fail("generation transaction rollback payload digest is invalid")
        seen_names.add(name)
        parsed.append(
            _TransactionTarget(
                path=expected[name],
                old_payload=old_payload,
                old_mode=old_mode,
                new_sha256=new_sha256,
                new_mode=new_mode,
                staged=journal.parent / staged_name,
            )
        )
    if seen_names != set(expected):
        _fail("generation transaction target set is invalid")
    return str(value["state"]), tuple(sorted(parsed, key=lambda item: item.path.name))


def _target_matches(path: Path, payload: bytes, mode: int) -> bool:
    try:
        info = path.lstat()
        return (
            stat.S_ISREG(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == mode
            and path.read_bytes() == payload
        )
    except OSError:
        return False


def _target_digest_matches(path: Path, digest: str, mode: int) -> bool:
    try:
        info = path.lstat()
        return (
            stat.S_ISREG(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and stat.S_IMODE(info.st_mode) == mode
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        )
    except OSError:
        return False


def _recover_transaction(paths: tuple[Path, ...]) -> None:
    journal = _transaction_journal(paths)
    if not _journal_present(journal):
        return
    state, targets = _transaction_record(journal, paths)
    errors: list[str] = []
    if state == "prepared":
        for target in targets:
            try:
                if target.old_payload is None:
                    if target.path.is_symlink():
                        _fail(f"rollback target became a symlink: {target.path.name}")
                    target.path.unlink(missing_ok=True)
                elif not _target_matches(target.path, target.old_payload, target.old_mode or 0):
                    restored_stage = _stage(
                        target.path,
                        target.old_payload,
                        mode=target.old_mode,
                    )
                    try:
                        os.replace(restored_stage, target.path)
                    finally:
                        restored_stage.unlink(missing_ok=True)
            except BaseException as exc:
                errors.append(f"restore {target.path.name}: {exc}")
        try:
            _sync_directory(journal.parent)
        except BaseException as exc:
            errors.append(f"sync restored directory: {exc}")
        for target in targets:
            was_restored = (
                not target.path.exists()
                if target.old_payload is None
                else _target_matches(target.path, target.old_payload, target.old_mode or 0)
            )
            if not was_restored:
                errors.append(f"verify restored target {target.path.name}")
    else:
        for target in targets:
            if not _target_digest_matches(target.path, target.new_sha256, target.new_mode):
                errors.append(f"verify committed target {target.path.name}")
    if errors:
        _fail("generation transaction recovery incomplete: " + "; ".join(errors))
    cleanup_errors: list[str] = []
    for target in targets:
        try:
            target.staged.unlink(missing_ok=True)
        except BaseException as exc:
            cleanup_errors.append(f"clean {target.staged.name}: {exc}")
    try:
        _sync_directory(journal.parent)
    except BaseException as exc:
        cleanup_errors.append(f"sync transaction cleanup: {exc}")
    if cleanup_errors:
        _fail("generation transaction cleanup incomplete: " + "; ".join(cleanup_errors))
    journal.unlink()
    _sync_directory(journal.parent)


def _replace_many_locked(payloads: dict[Path, bytes]) -> None:
    paths = tuple(sorted(payloads, key=lambda item: item.as_posix()))
    journal = _transaction_journal(paths)
    _recover_transaction(paths)
    old = {path: path.read_bytes() if path.exists() else None for path in paths}
    old_modes = {
        path: stat.S_IMODE(path.stat().st_mode) if path.exists() else None for path in paths
    }
    staged: dict[Path, Path] = {}
    try:
        for path in paths:
            staged[path] = _stage(path, payloads[path])
        transaction_targets: list[JsonObject] = []
        for path in paths:
            previous = old[path]
            transaction_targets.append(
                {
                    "name": path.name,
                    "new_mode": stat.S_IMODE(staged[path].stat().st_mode),
                    "new_sha256": hashlib.sha256(payloads[path]).hexdigest(),
                    "old_mode": old_modes[path],
                    "old_payload_base64": (
                        base64.b64encode(previous).decode("ascii") if previous is not None else None
                    ),
                    "old_sha256": (
                        hashlib.sha256(previous).hexdigest() if previous is not None else None
                    ),
                    "staged_name": staged[path].name,
                }
            )
        record: JsonObject = {
            "schema_version": TRANSACTION_SCHEMA,
            "state": "prepared",
            "targets": transaction_targets,
        }
        _write_transaction_journal(journal, record)
        for path in paths:
            os.replace(staged[path], path)
        _sync_directory(journal.parent)
        for target in record["targets"]:
            if not _target_digest_matches(
                journal.parent / target["name"], target["new_sha256"], target["new_mode"]
            ):
                _fail(f"generated target readback differs: {target['name']}")
        committed = dict(record)
        committed["state"] = "committed"
        _write_transaction_journal(journal, committed)
        _recover_transaction(paths)
    except BaseException as original:
        recovery_error: BaseException | None = None
        if _journal_present(journal):
            try:
                _recover_transaction(paths)
            except BaseException as exc:
                recovery_error = exc
        if recovery_error is not None:
            raise DiscoveryError(
                f"generation failed and durable recovery remains pending: {recovery_error}"
            ) from original
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def _replace_many(payloads: dict[Path, bytes]) -> None:
    paths = tuple(sorted(payloads, key=lambda item: item.as_posix()))
    lock_path = _transaction_journal(paths).parent / f".{GENERATION_LOCK_NAME}"
    with _generation_lock(lock_path):
        _replace_many_locked(payloads)


def _repository_generation_lock(root: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", GENERATION_LOCK_NAME],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        _fail(f"cannot resolve generation lock path: {completed.stderr.strip()}")
    raw = completed.stdout.strip()
    if not raw or "\0" in raw or "\n" in raw:
        _fail("generation lock path is invalid")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise DiscoveryError(f"cannot resolve generation lock directory: {exc}") from exc
    return parent / path.name


def _target(root: Path, value: Path) -> Path:
    target = value if value.is_absolute() else root / value
    resolved_parent = target.parent.resolve(strict=True)
    candidate = resolved_parent / target.name
    if not candidate.is_relative_to(root) or candidate.is_symlink():
        _fail(f"generated target is outside the repository or a symlink: {value}")
    return candidate


def run(
    command: str,
    *,
    repository_root: Path,
    inventory: Path,
    profiles: Path,
    docs: Path,
) -> int:
    root = repository_root.resolve(strict=True)
    inventory_path = _target(root, inventory)
    profiles_path = _target(root, profiles)
    docs_path = _target(root, docs)
    targets = tuple(sorted((inventory_path, profiles_path, docs_path), key=lambda path: path.name))
    if command not in {"check", "generate"}:
        _fail(f"unknown command: {command}")
    with _generation_lock(
        _repository_generation_lock(root),
        exclusive=command == "generate",
    ):
        journal = _transaction_journal(targets)
        if command == "generate":
            _recover_transaction(targets)
        elif _journal_present(journal):
            _fail("pending public-surface generation recovery; run generate before check")
        candidate_inventory, candidate_profiles, markdown, discovery = build_candidates(
            root, inventory_path, profiles_path, docs_path
        )
        payloads = {
            inventory_path: _document_bytes(candidate_inventory),
            profiles_path: _document_bytes(candidate_profiles),
            docs_path: markdown.encode("utf-8"),
        }
        changed = any(
            not path.exists() or path.read_bytes() != payload for path, payload in payloads.items()
        )
        if command == "check":
            if changed:
                print("public-surface inventory drift detected", file=sys.stderr)
                return 1
        elif changed:
            _replace_many_locked(payloads)
            verified_inventory, verified_profiles, verified_markdown, _ = build_candidates(
                root, inventory_path, profiles_path, docs_path
            )
            if (
                verified_inventory != candidate_inventory
                or verified_profiles != candidate_profiles
                or verified_markdown != markdown
                or any(path.read_bytes() != payload for path, payload in payloads.items())
            ):
                _fail("generated public-surface readback differs from validated candidates")
        print(
            json.dumps(
                {
                    "families": discovery.family_counts,
                    "resource_facets": discovery.resource_facets,
                    "rows": len(discovery.rows),
                    "sources": discovery.source_counts,
                },
                sort_keys=True,
            )
        )
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "generate"))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--inventory", type=Path, default=Path(INVENTORY_PATH))
    parser.add_argument("--profiles", type=Path, default=Path(PROFILES_PATH))
    parser.add_argument("--docs", type=Path, default=Path(DOCS_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(
            args.command,
            repository_root=args.repository_root,
            inventory=args.inventory,
            profiles=args.profiles,
            docs=args.docs,
        )
    except (DiscoveryError, OSError) as exc:
        print(f"public-surface discovery failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
