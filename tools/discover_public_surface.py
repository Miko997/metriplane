# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Discover and govern the complete staged public repository surface.

The Git index is the only source authority.  Worktree source files are never
dereferenced or parsed, which makes staged review, symlink identity, and
repeatable generation explicit parts of the contract.
"""

from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import csv
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType, ModuleType
from typing import Any, NoReturn


TASK_ID = "MP2-013"
ISSUE_ID = "MET-78"
PROFILE_ID = "repository.current-public-surface.static"
ROW_PREFIX = "MP2-013.PUBLIC."
SCANNER_PATH = "tools/discover_public_surface.py"
PROVENANCE_PATH = "tools/public_surface_provenance.py"
INVENTORY_PATH = "docs/status/functional-inventory.json"
PROFILES_PATH = "docs/status/support-profiles.json"
REPORT_PATH = "docs/status/public-surface-inventory.md"
GENERATED_PATHS = frozenset({INVENTORY_PATH, PROFILES_PATH, REPORT_PATH})
TRANSACTION_DIRECTORY = ".public-surface-generation.transaction"
TRANSACTION_SCHEMA = "metriplane.public-surface-generation-transaction.v1"
CONSUMERS = ("MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018")
CRITERIA = ("MP2-013.A01",)
VALIDATOR = (
    "tests/test_discover_public_surface.py::test_committed_inventory_matches_current_public_surface"
)
MAX_BLOB_BYTES = 64 * 1024 * 1024
MAX_INDEX_ENTRIES = 100_000
LOCK_TIMEOUT_SECONDS = 5.0

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
FAMILY_TOKEN = {
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
EXPECTED_FAMILY_COUNTS = {
    "configs": 167,
    "current_claims": 312,
    "examples": 172,
    "jobs": 55,
    "manifest_keys": 3580,
    "model_fields": 1389,
    "models": 229,
    "proofs": 322,
    "public_api": 2293,
    "resources": 1552,
    "workflows": 16,
}

JsonObject = dict[str, Any]


class DiscoveryError(ValueError):
    """The staged repository or a generated target violates the contract."""


def _fail(message: str) -> NoReturn:
    raise DiscoveryError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _document_bytes(value: Any) -> bytes:
    return _canonical_bytes(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_constant(value: str) -> NoReturn:
    _fail(f"non-finite JSON constant is forbidden: {value}")


def _reject_pairs(pairs: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key is forbidden: {key!r}")
        result[key] = value
    return result


def _parse_json(data: bytes, *, label: str) -> JsonObject:
    try:
        text = data.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"cannot parse canonical JSON {label}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"canonical JSON must be an object: {label}")
    return value


def _safe_path(value: str) -> str:
    if not value or "\\" in value or unicodedata.normalize("NFC", value) != value:
        _fail(f"non-canonical repository path: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail(f"unsafe repository path: {value!r}")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        _fail(f"repository path contains a control character: {value!r}")
    return value


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
        }
    )
    return environment


def _git(root: Path, arguments: Sequence[str], *, input_bytes: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(root), *arguments],
            check=False,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
        )
    except OSError as exc:
        raise DiscoveryError(f"cannot execute Git: {exc}") from exc
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        _fail(f"Git {' '.join(arguments)} failed: {message or completed.returncode}")
    return completed.stdout


def _git_blob_oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class StageEntry:
    path: str
    mode: str
    oid: str
    data: bytes

    @property
    def sha256(self) -> str:
        return _bytes_digest(self.data)


@dataclass(frozen=True)
class PythonModule:
    path: str
    module: str
    tree: ast.Module


@dataclass(frozen=True)
class ManifestKeyObservation:
    key: str
    source_path: str
    locator: str


@dataclass(frozen=True)
class Observation:
    family: str
    key: str
    name: str
    source_path: str
    locator: str


@dataclass(frozen=True)
class Discovery:
    observations: tuple[Observation, ...]
    rows: tuple[JsonObject, ...]
    family_counts: Mapping[str, int]
    family_digests: Mapping[str, str]
    resource_facets: Mapping[str, int]
    source_census: Mapping[str, int]
    parser_census: Mapping[str, int]


class StagedSnapshot:
    """An immutable projection of exact stage-0 index identities and blob bytes."""

    def __init__(self, root: Path, entries: Sequence[StageEntry]) -> None:
        ordered = tuple(sorted(entries, key=lambda item: item.path.encode("utf-8")))
        paths = [item.path for item in ordered]
        if paths != sorted(set(paths), key=lambda item: item.encode("utf-8")):
            _fail("stage-0 paths are duplicate or non-canonical")
        self.root = root
        self.entries = ordered
        self._by_path: Mapping[str, StageEntry] = MappingProxyType(
            {entry.path: entry for entry in ordered}
        )

    @classmethod
    def capture(cls, repository_root: Path) -> StagedSnapshot:
        root = repository_root.resolve(strict=True)
        if not root.is_dir():
            _fail("repository root is not a directory")
        raw = _git(root, ("ls-files", "--stage", "-z"))
        records = raw.split(b"\0")
        if records[-1] != b"":
            _fail("Git index listing is not NUL terminated")
        records.pop()
        if not records or len(records) > MAX_INDEX_ENTRIES:
            _fail("Git index entry count is empty or exceeds the bounded limit")
        headers: list[tuple[str, str, str]] = []
        requested: list[str] = []
        for record in records:
            try:
                header, raw_path = record.split(b"\t", 1)
                mode_bytes, oid_bytes, stage_bytes = header.split(b" ")
                path = raw_path.decode("utf-8", "strict")
                mode = mode_bytes.decode("ascii", "strict")
                oid = oid_bytes.decode("ascii", "strict")
                stage = stage_bytes.decode("ascii", "strict")
            except (ValueError, UnicodeError) as exc:
                raise DiscoveryError("malformed stage-0 Git index record") from exc
            _safe_path(path)
            if stage != "0":
                _fail(f"unmerged Git index stage is forbidden: {path}@{stage}")
            if mode not in {"100644", "100755", "120000"}:
                _fail(f"unsupported Git index mode {mode}: {path}")
            if re.fullmatch(r"[0-9a-f]{40}", oid) is None:
                _fail(f"non-SHA-1 Git blob identity in index: {path}")
            headers.append((path, mode, oid))
            requested.append(oid)

        unique_oids = tuple(dict.fromkeys(requested))
        request = b"".join(oid.encode("ascii") + b"\n" for oid in unique_oids)
        output = _git(root, ("cat-file", "--batch"), input_bytes=request)
        blobs: dict[str, bytes] = {}
        offset = 0
        for expected_oid in unique_oids:
            line_end = output.find(b"\n", offset)
            if line_end < 0:
                _fail("truncated git cat-file header")
            cat_header_parts = output[offset:line_end].split(b" ")
            if len(cat_header_parts) != 3:
                _fail("malformed git cat-file header")
            raw_oid, object_type, raw_size = cat_header_parts
            try:
                actual_oid = raw_oid.decode("ascii", "strict")
                size = int(raw_size.decode("ascii", "strict"))
            except (UnicodeError, ValueError) as exc:
                raise DiscoveryError("malformed git cat-file identity or size") from exc
            if actual_oid != expected_oid or object_type != b"blob":
                _fail(f"Git object identity/type mismatch for {expected_oid}")
            if size < 0 or size > MAX_BLOB_BYTES:
                _fail(f"Git blob exceeds bounded size: {expected_oid}")
            data_start = line_end + 1
            data_end = data_start + size
            if data_end >= len(output) or output[data_end : data_end + 1] != b"\n":
                _fail(f"truncated git cat-file body: {expected_oid}")
            data = output[data_start:data_end]
            if _git_blob_oid(data) != expected_oid:
                _fail(f"exact Git blob bytes do not match index identity: {expected_oid}")
            blobs[expected_oid] = data
            offset = data_end + 1
        if offset != len(output):
            _fail("git cat-file returned trailing bytes")
        return cls(
            root,
            [StageEntry(path, mode, oid, blobs[oid]) for path, mode, oid in headers],
        )

    def parser_entry(self, path: str) -> StageEntry:
        _safe_path(path)
        try:
            return self._by_path[path]
        except KeyError as exc:
            raise DiscoveryError(f"required staged blob is missing: {path}") from exc

    def maybe_entry(self, path: str) -> StageEntry | None:
        _safe_path(path)
        return self._by_path.get(path)


def validate_index_identity(
    entry: StageEntry,
    *,
    mode: str,
    oid: str,
    data: bytes,
) -> None:
    """Validate an expected Git representation without filesystem dereference."""

    if mode not in {"100644", "100755", "120000"}:
        _fail(f"unsupported expected Git mode: {mode}")
    if re.fullmatch(r"[0-9a-f]{40}", oid) is None:
        _fail("expected Git blob identity is malformed")
    if entry.mode != mode:
        _fail(f"Git mode mismatch for {entry.path}: {entry.mode} != {mode}")
    if entry.oid != oid:
        _fail(f"Git blob identity mismatch for {entry.path}: {entry.oid} != {oid}")
    if entry.data != data or _git_blob_oid(data) != oid:
        _fail(f"Git blob bytes mismatch for {entry.path}")


def validate_snapshot_identity(
    snapshot: StagedSnapshot,
    path: str,
    *,
    mode: str,
    oid: str,
    data: bytes,
) -> None:
    validate_index_identity(snapshot.parser_entry(path), mode=mode, oid=oid, data=data)


def _decode_text(entry: StageEntry, *, label: str | None = None) -> str:
    if entry.mode == "120000":
        _fail(f"parser input cannot be a symlink blob: {label or entry.path}")
    try:
        return entry.data.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise DiscoveryError(f"parser input is not UTF-8: {label or entry.path}") from exc


def _parse_toml(snapshot: StagedSnapshot, path: str) -> JsonObject:
    entry = snapshot.parser_entry(path)
    try:
        value = tomllib.loads(_decode_text(entry))
    except tomllib.TOMLDecodeError as exc:
        raise DiscoveryError(f"cannot parse staged TOML {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"TOML root must be a table: {path}")
    return value


def _parse_python(entry: StageEntry, *, module: str) -> PythonModule:
    text = _decode_text(entry)
    try:
        tree = ast.parse(text, filename=entry.path)
    except SyntaxError as exc:
        raise DiscoveryError(f"cannot parse staged Python {entry.path}: {exc}") from exc
    return PythonModule(entry.path, module, tree)


def _path_module(path: str, package_root: str) -> str:
    relative = (
        path if package_root in {"", "."} else path.removeprefix(package_root.rstrip("/") + "/")
    )
    if relative.endswith("/__init__.py"):
        relative = relative[: -len("/__init__.py")]
    elif relative.endswith(".py"):
        relative = relative[:-3]
    else:
        _fail(f"packaged Python path does not end in .py: {path}")
    parts = relative.split("/")
    if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) is None for part in parts):
        _fail(f"packaged module path is not importable: {path}")
    return ".".join(parts)


def _packaged_python_modules(snapshot: StagedSnapshot) -> tuple[PythonModule, ...]:
    selected: dict[str, tuple[str, str]] = {}
    root_project = _parse_toml(snapshot, "pyproject.toml")
    try:
        find = root_project["tool"]["setuptools"]["packages"]["find"]
        where = find["where"]
        include = find["include"]
        exclude = find["exclude"]
    except (KeyError, TypeError) as exc:
        raise DiscoveryError("root setuptools package discovery is missing") from exc
    if (
        where != ["."]
        or not isinstance(include, list)
        or not include
        or not all(isinstance(item, str) for item in include)
        or not isinstance(exclude, list)
        or not all(isinstance(item, str) for item in exclude)
    ):
        _fail("root setuptools package discovery is not a bounded literal declaration")
    for entry in snapshot.entries:
        if not entry.path.endswith(".py"):
            continue
        raw_module = entry.path[:-3].replace("/", ".")
        if raw_module.endswith(".__init__"):
            raw_module = raw_module[: -len(".__init__")]
        if not any(fnmatch.fnmatchcase(raw_module, pattern) for pattern in include):
            continue
        if any(fnmatch.fnmatchcase(raw_module, pattern) for pattern in exclude):
            continue
        module = _path_module(entry.path, ".")
        selected[entry.path] = (module, ".")

    project_paths = [
        entry.path
        for entry in snapshot.entries
        if entry.path.startswith("adapters/") and entry.path.endswith("/pyproject.toml")
    ]
    for project_path in sorted(project_paths):
        project = _parse_toml(snapshot, project_path)
        project_root = project_path.rsplit("/", 1)[0]
        try:
            packages = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        except (KeyError, TypeError):
            continue
        if (
            not isinstance(packages, list)
            or not packages
            or not all(isinstance(item, str) for item in packages)
        ):
            _fail(f"adapter wheel packages are not a literal nonempty array: {project_path}")
        for declared in packages:
            assert isinstance(declared, str)
            if declared.startswith("/") or "\\" in declared or ".." in declared.split("/"):
                _fail(f"unsafe adapter package declaration: {project_path}:{declared}")
            package_root = f"{project_root}/{declared}".rstrip("/")
            matched = False
            for entry in snapshot.entries:
                if entry.path == package_root + ".py" or (
                    entry.path.startswith(package_root + "/") and entry.path.endswith(".py")
                ):
                    module = _path_module(entry.path, project_root + "/src")
                    selected[entry.path] = (module, project_root + "/src")
                    matched = True
            if not matched:
                _fail(f"adapter package declaration matches no staged Python: {project_path}")

    modules = [
        _parse_python(snapshot.parser_entry(path), module=module)
        for path, (module, _root) in sorted(selected.items())
    ]
    names = [item.module for item in modules]
    if len(names) != len(set(names)):
        _fail("packaged Python module names are duplicate")
    return tuple(sorted(modules, key=lambda item: (item.module, item.path)))


def _all_python_modules(snapshot: StagedSnapshot) -> tuple[PythonModule, ...]:
    result: list[PythonModule] = []
    for entry in snapshot.entries:
        if not entry.path.endswith(".py") or entry.path in GENERATED_PATHS:
            continue
        module = entry.path[:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        result.append(_parse_python(entry, module=module))
    return tuple(result)


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _decorator_name(node.value) + "." + node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _base_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _model_observations(
    modules: Sequence[PythonModule],
) -> tuple[list[Observation], list[Observation]]:
    classes: dict[tuple[str, str], tuple[PythonModule, ast.ClassDef]] = {}
    annotated: set[tuple[str, str]] = set()
    pydantic: set[tuple[str, str]] = set()
    dataclasses: set[tuple[str, str]] = set()
    for module in modules:
        for node in module.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            identity = (module.module, node.name)
            classes[identity] = (module, node)
            public_fields = [
                item
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and not item.target.id.startswith("_")
            ]
            if not public_fields:
                public_fields = []
            else:
                annotated.add(identity)
            if any(
                _decorator_name(item).split(".")[-1] == "dataclass" for item in node.decorator_list
            ):
                dataclasses.add(identity)
            if any(_base_name(item).split(".")[-1] == "BaseModel" for item in node.bases):
                pydantic.add(identity)

    changed = True
    while changed:
        changed = False
        pydantic_names = {name for _module, name in pydantic}
        for identity, (_module, node) in classes.items():
            if identity in pydantic:
                continue
            if any(_base_name(base).split(".")[-1] in pydantic_names for base in node.bases):
                pydantic.add(identity)
                changed = True

    model_identities = (pydantic & annotated) | {
        identity for identity in dataclasses & annotated if not classes[identity][1].bases
    }
    field_identities = (pydantic | dataclasses) & annotated
    models: list[Observation] = []
    fields: list[Observation] = []
    for identity in sorted(model_identities):
        module, node = classes[identity]
        qualified = f"{module.module}.{node.name}"
        models.append(
            Observation(
                "models",
                qualified,
                qualified,
                module.path,
                f"class:{qualified}@L{node.lineno}",
            )
        )
    for identity in sorted(field_identities):
        module, node = classes[identity]
        qualified = f"{module.module}.{node.name}"
        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and not item.target.id.startswith("_")
            ):
                name = f"{qualified}.{item.target.id}"
                fields.append(
                    Observation(
                        "model_fields",
                        name,
                        name,
                        module.path,
                        f"field:{name}@L{item.lineno}",
                    )
                )
    return models, fields


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
    targets: Sequence[ast.expr]
    if isinstance(node, ast.Assign):
        targets = node.targets
    else:
        targets = (node.target,)
    result: list[str] = []
    pending = list(targets)
    while pending:
        target = pending.pop()
        if isinstance(target, ast.Name):
            result.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            pending.extend(reversed(target.elts))
    return tuple(result)


def _literal_all(tree: ast.Module, *, path: str) -> tuple[str, ...] | None:
    declarations: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and "__all__" in _assignment_names(node):
            declarations.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign) and "__all__" in _assignment_names(node) and node.value
        ):
            declarations.append(node.value)
    if not declarations:
        return None
    if len(declarations) != 1:
        _fail(f"packaged module has multiple __all__ declarations: {path}")
    try:
        value = ast.literal_eval(declarations[0])
    except (ValueError, TypeError) as exc:
        raise DiscoveryError(f"packaged module __all__ is not literal: {path}") from exc
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        _fail(f"packaged module __all__ must be a string array: {path}")
    names = tuple(value)
    if any(not item or (item.startswith("_") and item != "__version__") for item in names) or len(
        names
    ) != len(set(names)):
        _fail(f"packaged module __all__ contains invalid or duplicate names: {path}")
    return names


def _public_api_observations(modules: Sequence[PythonModule]) -> list[Observation]:
    """Return source-declared public bindings and class data members.

    Imports are dependencies rather than declarations.  Callable methods are
    reached through their declared class, while class Assign/AnnAssign names
    are stored public data declarations and therefore receive their own rows.
    A literal ``__all__`` may explicitly export a private module binding.
    """

    result: list[Observation] = []
    for module in modules:
        explicit = _literal_all(module.tree, path=module.path)
        bindings: dict[str, ast.AST] = {}
        for node in module.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.setdefault(node.name, node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for name in _assignment_names(node):
                    bindings.setdefault(name, node)
        names = {name for name in bindings if not name.startswith("_")}
        if explicit is not None:
            names.update(name for name in explicit if name.startswith("_"))
        for name in sorted(names):
            binding_node = bindings.get(name)
            if binding_node is None:
                _fail(f"__all__ name has no static module binding: {module.path}:{name}")
            qualified = f"{module.module}.{name}"
            result.append(
                Observation(
                    "public_api",
                    qualified,
                    qualified,
                    module.path,
                    f"module-public:{qualified}@L{getattr(binding_node, 'lineno', 0)}",
                )
            )
        for class_node in module.tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            member_bindings: dict[str, ast.AST] = {}
            for node in class_node.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                for name in _assignment_names(node):
                    if not name.startswith("_"):
                        member_bindings.setdefault(name, node)
            for name, member_node in sorted(member_bindings.items()):
                qualified = f"{module.module}.{class_node.name}.{name}"
                result.append(
                    Observation(
                        "public_api",
                        qualified,
                        qualified,
                        module.path,
                        f"class-public:{qualified}@L{getattr(member_node, 'lineno', 0)}",
                    )
                )
    return result


def _workflow_document(data: bytes, *, path: str) -> Mapping[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - repository dependency contract
        raise DiscoveryError("PyYAML is required for workflow discovery") from exc

    class UniqueLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                _fail(f"duplicate YAML key is forbidden: {path}:{key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    try:
        value = yaml.load(data.decode("utf-8", "strict"), Loader=UniqueLoader)
    except (UnicodeError, yaml.YAMLError) as exc:
        raise DiscoveryError(f"cannot parse staged workflow {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"workflow root must be a mapping: {path}")
    return value


def _workflow_observations(snapshot: StagedSnapshot) -> tuple[list[Observation], list[Observation]]:
    workflows: list[Observation] = []
    jobs: list[Observation] = []
    entries = [
        entry
        for entry in snapshot.entries
        if entry.path.startswith(".github/workflows/")
        and entry.path.lower().endswith((".yml", ".yaml"))
    ]
    for entry in entries:
        document = _workflow_document(entry.data, path=entry.path)
        job_table = document.get("jobs")
        if not isinstance(job_table, dict) or not job_table:
            _fail(f"workflow has no literal nonempty jobs mapping: {entry.path}")
        workflows.append(
            Observation(
                "workflows",
                entry.path,
                entry.path,
                entry.path,
                "workflow",
            )
        )
        for job_id, declaration in sorted(job_table.items(), key=lambda pair: str(pair[0])):
            if (
                not isinstance(job_id, str)
                or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", job_id) is None
                or not isinstance(declaration, dict)
            ):
                _fail(f"workflow job declaration is not a literal mapping: {entry.path}")
            key = f"{entry.path}#{job_id}"
            jobs.append(
                Observation(
                    "jobs",
                    key,
                    key,
                    entry.path,
                    f"jobs.{job_id}",
                )
            )
    return workflows, jobs


def _resource_observations(snapshot: StagedSnapshot) -> tuple[list[Observation], dict[str, int]]:
    resources: list[Observation] = []
    configs: list[Observation] = []
    examples: list[Observation] = []
    proofs: list[Observation] = []
    for entry in snapshot.entries:
        if entry.path in GENERATED_PATHS:
            continue
        locator = f"index:{entry.mode}"
        resources.append(Observation("resources", entry.path, entry.path, entry.path, locator))
        parts = entry.path.split("/")
        lowered_parts = [part.casefold() for part in parts[:-1]]
        if "example" in lowered_parts or "examples" in lowered_parts:
            examples.append(
                Observation("examples", entry.path, entry.path, entry.path, "facet:example")
            )
        if entry.path.startswith(("evidence/", "proofs/")):
            proofs.append(Observation("proofs", entry.path, entry.path, entry.path, "facet:proof"))
        if _is_config_path(entry.path):
            configs.append(
                Observation("configs", entry.path, entry.path, entry.path, "facet:config")
            )
    facets = {
        "configs": len(configs),
        "examples": len(examples),
        "proofs": len(proofs),
        "symlinks": sum(entry.mode == "120000" for entry in snapshot.entries),
    }
    return [*resources, *configs, *examples, *proofs], facets


def _is_config_path(path: str) -> bool:
    """Classify maintained configuration paths with an intentionally narrow rule."""

    lowered = path.casefold()
    if not lowered.endswith((".yaml", ".yml", ".toml")):
        return False
    return not lowered.startswith(
        (".github/workflows/", ".github/issue_template/", "evidence/", "proofs/")
    )


def _claim_observations(snapshot: StagedSnapshot) -> list[Observation]:
    """Project governed foreign claims without introducing a self-reference."""

    inventory = _parse_json(snapshot.parser_entry(INVENTORY_PATH).data, label=INVENTORY_PATH)
    rows = inventory.get("rows")
    if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
        _fail("governed inventory rows are not an object array")
    result: list[Observation] = []
    allowed_owners = {"MP2-010", "MP2-011", "MP2-012"}
    for row in rows:
        owner = row.get("owner")
        if owner == TASK_ID:
            continue
        if owner not in allowed_owners:
            _fail(f"current-claim source has an unexpected foreign owner: {owner!r}")
        identifier = row.get("id")
        claim = row.get("claim")
        source = row.get("source")
        if (
            not isinstance(identifier, str)
            or not isinstance(claim, dict)
            or not isinstance(claim.get("statement"), str)
            or not claim["statement"]
            or not isinstance(source, dict)
            or not isinstance(source.get("path"), str)
            or not isinstance(source.get("digest_sha256"), str)
        ):
            _fail(f"governed current claim is malformed: {identifier!r}")
        source_entry = snapshot.parser_entry(source["path"])
        pointer = source.get("json_pointer")
        if pointer is None:
            actual_source_digest = source_entry.sha256
        else:
            if not isinstance(pointer, str) or not pointer.startswith("/"):
                _fail(f"governed frozen claim pointer is malformed: {identifier}")
            pointed: Any = _parse_json(source_entry.data, label=source_entry.path)
            for raw_token in pointer[1:].split("/"):
                token = raw_token.replace("~1", "/").replace("~0", "~")
                if isinstance(pointed, dict) and token in pointed:
                    pointed = pointed[token]
                elif isinstance(pointed, list) and token.isdigit() and int(token) < len(pointed):
                    pointed = pointed[int(token)]
                else:
                    _fail(f"governed frozen claim pointer does not resolve: {identifier}")
            actual_source_digest = _digest(pointed)
            count = source.get("count")
            if count is not None and (
                not isinstance(count, int) or not isinstance(pointed, list) or len(pointed) != count
            ):
                _fail(f"governed frozen claim count is stale: {identifier}")
        if actual_source_digest != source["digest_sha256"]:
            _fail(f"governed current claim source digest is stale: {identifier}")
        result.append(
            Observation(
                "current_claims",
                f"governed:{identifier}",
                claim["statement"],
                source_entry.path,
                f"governed-claim:{identifier}",
            )
        )

    manifest_path = "docs/evaluations/commissioned-first-use-v030/SOURCE_MANIFEST.json"
    manifest = _parse_json(snapshot.parser_entry(manifest_path).data, label=manifest_path)
    claims = manifest.get("claims")
    if not isinstance(claims, list) or any(not isinstance(item, dict) for item in claims):
        _fail("commissioned first-use claims are not an object array")
    claim_ids: list[str] = []
    for ordinal, claim in enumerate(claims):
        identifier = claim.get("claim_id")
        statement = claim.get("claim")
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"C[0-9]{2}", identifier) is None
            or not isinstance(statement, str)
            or not statement
        ):
            _fail("commissioned first-use claim is malformed")
        claim_ids.append(identifier)
        result.append(
            Observation(
                "current_claims",
                f"commissioned-first-use:{identifier}",
                statement,
                manifest_path,
                f"claim:/claims/{ordinal};claim_id={identifier}",
            )
        )
    if claim_ids != sorted(set(claim_ids)):
        _fail("commissioned first-use claim IDs are duplicate or non-canonical")
    return result


def _load_provenance_kernel() -> ModuleType:
    canonical_name = "tools.public_surface_provenance"
    loaded = sys.modules.get(canonical_name)
    if loaded is not None:
        return loaded
    try:
        return __import__(canonical_name, fromlist=["discover_manifest_keys"])
    except ModuleNotFoundError:
        sibling = Path(__file__).with_name("public_surface_provenance.py")
        spec = importlib.util.spec_from_file_location(canonical_name, sibling)
        if spec is None or spec.loader is None:
            _fail("cannot construct sibling provenance-kernel import")
        module = importlib.util.module_from_spec(spec)
        sys.modules[canonical_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(canonical_name, None)
            raise
        return module


def _read_regular_nofollow(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DiscoveryError(f"{label} is unavailable as a non-symlink file: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail(f"{label} is not a regular file")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BLOB_BYTES:
                _fail(f"{label} exceeds the bounded file size")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _assert_executing_sources_match_snapshot(
    snapshot: StagedSnapshot,
    kernel: ModuleType,
) -> None:
    sources = (
        (SCANNER_PATH, Path(__file__), "executing public-surface scanner"),
        (
            PROVENANCE_PATH,
            Path(str(getattr(kernel, "__file__", ""))),
            "executing public-surface provenance kernel",
        ),
    )
    for relative, executing_path, label in sources:
        entry = snapshot.parser_entry(relative)
        if entry.mode not in {"100644", "100755"}:
            _fail(f"{label} has a non-regular staged Git mode: {entry.mode}")
        expected_path = snapshot.root.joinpath(*relative.split("/"))
        try:
            expected_resolved = expected_path.resolve(strict=True)
            executing_resolved = executing_path.resolve(strict=True)
        except OSError as exc:
            raise DiscoveryError(f"{label} path cannot be resolved: {exc}") from exc
        if executing_resolved != expected_resolved:
            _fail(f"{label} path differs from the staged repository source")
        if _read_regular_nofollow(executing_path, label=label) != entry.data:
            _fail(f"{label} bytes differ from the exact stage-0 Git blob")


def _manifest_observations(
    snapshot: StagedSnapshot,
    modules: Sequence[PythonModule],
    *,
    kernel: ModuleType | None = None,
) -> list[Observation]:
    if kernel is None:
        kernel = _load_provenance_kernel()
    hook = getattr(kernel, "discover_manifest_keys", None)
    if not callable(hook):
        _fail("provenance kernel has no discover_manifest_keys hook")
    raw = hook(snapshot, tuple(modules))
    if not isinstance(raw, (tuple, list)):
        _fail("manifest-key hook result must be a finite sequence")
    result = _static_manifest_observations(snapshot, modules)
    for item in raw:
        key = getattr(item, "key", None)
        source_path = getattr(item, "source_path", None)
        locator = getattr(item, "locator", None)
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(source_path, str)
            or not source_path
            or not isinstance(locator, str)
            or not locator
        ):
            _fail("manifest-key hook emitted a malformed observation")
        snapshot.parser_entry(source_path)
        stable_key = f"{source_path}:{key}"
        result.append(
            Observation(
                "manifest_keys",
                stable_key,
                key,
                source_path,
                locator,
            )
        )
    return result


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_key_pointers(value: Any, pointer: str = "") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                _fail("JSON object key is not a string")
            child = f"{pointer}/{_pointer_token(key)}"
            result.add(child)
            result.update(_json_key_pointers(nested, child))
    elif isinstance(value, list):
        for nested in value:
            result.update(_json_key_pointers(nested, f"{pointer}/*"))
    return result


_MANIFEST_MODEL_ROOTS = (
    ("metriplane/atlas/models.py", "BundleManifest"),
    ("metriplane/atlas/models.py", "AtlasRunManifest"),
    ("metriplane/external_sources/contract.py", "ExternalSourceManifestV1"),
)


def _static_manifest_observations(
    snapshot: StagedSnapshot,
    modules: Sequence[PythonModule],
) -> list[Observation]:
    result: list[Observation] = []
    for entry in snapshot.entries:
        basename = entry.path.rsplit("/", 1)[-1].casefold()
        if not (basename.endswith(".json") and "manifest" in basename):
            continue
        document = _parse_json(entry.data, label=entry.path)
        pointers = sorted(_json_key_pointers(document))
        if not pointers:
            _fail(f"maintained JSON manifest has no object keys: {entry.path}")
        for pointer in pointers:
            result.append(
                Observation(
                    "manifest_keys",
                    f"json:{entry.path}:{pointer}",
                    pointer,
                    entry.path,
                    f"json-key:{pointer}",
                )
            )

    csv_path = "evidence/manifest.csv"
    csv_entry = snapshot.parser_entry(csv_path)
    try:
        rows = list(csv.reader(_decode_text(csv_entry).splitlines(), strict=True))
    except csv.Error as exc:
        raise DiscoveryError(f"cannot parse staged manifest CSV {csv_path}: {exc}") from exc
    if (
        not rows
        or not rows[0]
        or len(rows[0]) != len(set(rows[0]))
        or any(not field for field in rows[0])
    ):
        _fail("manifest CSV header is empty, duplicate, or malformed")
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        _fail("manifest CSV contains a row with the wrong field count")
    for column, field in enumerate(rows[0], start=1):
        result.append(
            Observation(
                "manifest_keys",
                f"csv:{csv_path}:{field}",
                field,
                csv_path,
                f"csv-header:{field}@column{column}",
            )
        )

    by_path = {module.path: module for module in modules}
    for path, class_name in _MANIFEST_MODEL_ROOTS:
        module = by_path.get(path)
        if module is None:
            _fail(f"maintained manifest model module is absent: {path}")
        matches = [
            node
            for node in module.tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(matches) != 1:
            _fail(f"maintained manifest model must resolve once: {path}:{class_name}")
        class_node = matches[0]
        fields = [
            node
            for node in class_node.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        ]
        if not fields:
            _fail(f"maintained manifest model has no declared fields: {path}:{class_name}")
        names: list[str] = []
        for field_node in fields:
            target = field_node.target
            if not isinstance(target, ast.Name):
                _fail(f"maintained manifest model has a dynamic field: {path}:{class_name}")
            names.append(target.id)
        if len(names) != len(set(names)):
            _fail(f"maintained manifest model has duplicate fields: {path}:{class_name}")
        for node in fields:
            assert isinstance(node.target, ast.Name)
            field = node.target.id
            pointer = f"/{_pointer_token(field)}"
            result.append(
                Observation(
                    "manifest_keys",
                    f"model:{module.module}.{class_name}:{pointer}",
                    pointer,
                    path,
                    f"manifest-model:{class_name}.{field}@L{node.lineno}",
                )
            )
    return result


def _normalize_identifier_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    if not normalized:
        normalized = "ITEM"
    return normalized[:72]


def _row_id(family: str, key: str) -> str:
    suffix = hashlib.sha256(f"{family}\0{key}".encode("utf-8")).hexdigest()[:12].upper()
    return f"{ROW_PREFIX}{FAMILY_TOKEN[family]}.{_normalize_identifier_key(key)}.{suffix}"


def _source(snapshot: StagedSnapshot, observation: Observation) -> JsonObject:
    entry = snapshot.parser_entry(observation.source_path)
    return {
        "digest_sha256": entry.sha256,
        "locator": f"git-blob:{entry.oid};{observation.locator}",
        "path": observation.source_path,
        "type": "repository_discovery",
    }


def _row(snapshot: StagedSnapshot, observation: Observation) -> JsonObject:
    return {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": [],
            "statement": (
                f"Static staged-source discovery observes {observation.family} item "
                f"{observation.name}; MP2-013 makes no runtime or support claim."
            ),
        },
        "consumer_task_ids": list(CONSUMERS),
        "id": _row_id(observation.family, observation.key),
        "kind": FAMILY_KIND[observation.family],
        "name": observation.name,
        "owner": TASK_ID,
        "profile": PROFILE_ID,
        "source": _source(snapshot, observation),
        "status": "active",
        "test": FAMILY_OBLIGATION[observation.family],
        "trace_criterion_ids": list(CRITERIA),
        "validator_ids": [VALIDATOR],
    }


def _validate_observations(observations: Sequence[Observation]) -> None:
    identities: set[tuple[str, str]] = set()
    for item in observations:
        if item.family not in FAMILY_KIND:
            _fail(f"unknown public-surface family: {item.family}")
        if not item.key or not item.name or not item.locator:
            _fail(f"empty public-surface observation field: {item.family}")
        identity = (item.family, item.key)
        if identity in identities:
            _fail(f"duplicate public-surface observation: {item.family}:{item.key}")
        identities.add(identity)


def discover(
    snapshot_or_root: StagedSnapshot | Path,
    *,
    enforce_production_counts: bool = True,
) -> Discovery:
    snapshot = (
        snapshot_or_root
        if isinstance(snapshot_or_root, StagedSnapshot)
        else StagedSnapshot.capture(snapshot_or_root)
    )
    kernel = _load_provenance_kernel()
    _assert_executing_sources_match_snapshot(snapshot, kernel)
    packaged = _packaged_python_modules(snapshot)
    packaged_by_path = {item.path: item for item in packaged}
    all_python = tuple(
        packaged_by_path.get(item.path, item) for item in _all_python_modules(snapshot)
    )
    observations, resource_facets = _resource_observations(snapshot)
    workflows, jobs = _workflow_observations(snapshot)
    models, fields = _model_observations(packaged)
    observations.extend(workflows)
    observations.extend(jobs)
    observations.extend(models)
    observations.extend(fields)
    observations.extend(_public_api_observations(packaged))
    observations.extend(_claim_observations(snapshot))
    observations.extend(_manifest_observations(snapshot, all_python, kernel=kernel))
    observations.sort(key=lambda item: (item.family, item.key))
    _validate_observations(observations)
    counts = Counter(item.family for item in observations)
    family_counts = {family: counts[family] for family in sorted(FAMILY_KIND)}
    if enforce_production_counts and family_counts != EXPECTED_FAMILY_COUNTS:
        differences = {
            family: {"expected": EXPECTED_FAMILY_COUNTS[family], "observed": family_counts[family]}
            for family in sorted(FAMILY_KIND)
            if family_counts[family] != EXPECTED_FAMILY_COUNTS[family]
        }
        _fail(
            f"public-surface production census changed: {json.dumps(differences, sort_keys=True)}"
        )
    family_digests = {
        family: _digest(
            [
                {
                    "key": item.key,
                    "locator": item.locator,
                    "path": item.source_path,
                }
                for item in observations
                if item.family == family
            ]
        )
        for family in sorted(FAMILY_KIND)
    }
    rows = tuple(
        sorted((_row(snapshot, item) for item in observations), key=lambda item: item["id"])
    )
    ids = [str(item["id"]) for item in rows]
    if ids != sorted(set(ids)):
        _fail("public-surface stable row IDs collide")
    source_census = {
        "git_entries": len(snapshot.entries),
        "regular_blobs": sum(item.mode in {"100644", "100755"} for item in snapshot.entries),
        "symlink_blobs": sum(item.mode == "120000" for item in snapshot.entries),
    }
    parser_census = {
        "all_python_modules": len(all_python),
        "packaged_python_modules": len(packaged),
        "workflow_documents": len(workflows),
    }
    return Discovery(
        tuple(observations),
        rows,
        MappingProxyType(family_counts),
        MappingProxyType(family_digests),
        MappingProxyType(dict(sorted(resource_facets.items()))),
        MappingProxyType(source_census),
        MappingProxyType(parser_census),
    )


def _array(document: JsonObject, field: str, *, label: str) -> list[JsonObject]:
    value = document.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        _fail(f"{label}.{field} must be an array of objects")
    return value


def _validate_registry_pair(inventory: JsonObject, profiles: JsonObject) -> None:
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
            _fail(f"{label} IDs must be unique and in canonical order")
    if inventory.get("rows_sha256") != _digest(rows):
        _fail("inventory rows_sha256 is stale")
    if profiles.get("profiles_sha256") != _digest(profile_rows):
        _fail("support profiles_sha256 is stale")
    profile_ids = {item["id"] for item in profile_rows}
    for row in rows:
        if row.get("status") in {"active", "deprecated"} and row.get("profile") not in profile_ids:
            _fail(f"functional row has no support-profile binding: {row.get('id')}")


def _profile(snapshot: StagedSnapshot) -> JsonObject:
    scanner = snapshot.parser_entry(SCANNER_PATH)
    return {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": [],
            "statement": (
                "Static Git-index public-surface discovery is current at exact staged blob "
                "identities; this profile makes no runtime platform or support claim."
            ),
        },
        "id": PROFILE_ID,
        "kind": "repository_public_surface_discovery",
        "owner": TASK_ID,
        "source": {
            "digest_sha256": scanner.sha256,
            "locator": f"git-blob:{scanner.oid};canonical public-surface discovery scanner",
            "path": SCANNER_PATH,
            "type": "repository_discovery",
        },
        "status": "active",
        "support_disposition": "not_measured",
        "test": "MP2-013.OBL.PROFILE",
    }


def _report(discovery: Discovery) -> bytes:
    rows_digest = _digest(list(discovery.rows))
    materialization = _digest(
        {
            "family_counts": dict(discovery.family_counts),
            "family_digests": dict(discovery.family_digests),
            "rows_sha256": rows_digest,
        }
    )
    lines = [
        "<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->",
        "<!-- SPDX-License-Identifier: MIT -->",
        "<!-- Generated by tools/discover_public_surface.py; do not edit. -->",
        "",
        "# Public Surface Inventory",
        "",
        f"- Task: `{TASK_ID}` / `{ISSUE_ID}`",
        f"- Materialization SHA-256: `{materialization}`",
        f"- Owned rows: `{len(discovery.rows)}`",
        f"- Owned rows SHA-256: `{rows_digest}`",
        "- Claim boundary: static staged-source observations only; no runtime, compatibility, or support claim.",
        "",
        "## Families",
        "",
        "| Family | Kind | Count | Canonical projection SHA-256 |",
        "|---|---|---:|---|",
    ]
    for family in sorted(discovery.family_counts):
        lines.append(
            f"| `{family}` | `{FAMILY_KIND[family]}` | {discovery.family_counts[family]} | "
            f"`{discovery.family_digests[family]}` |"
        )
    lines.extend(
        [
            "",
            "## Resource facets",
            "",
            "| Facet | Count |",
            "|---|---:|",
        ]
    )
    for name, count in discovery.resource_facets.items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(
        [
            "",
            "## Source census",
            "",
            "| Source identity | Count |",
            "|---|---:|",
        ]
    )
    for name, count in discovery.source_census.items():
        lines.append(f"| `{name}` | {count} |")
    lines.extend(
        [
            "",
            "## Parser census",
            "",
            "| Parser input | Count |",
            "|---|---:|",
        ]
    )
    for name, count in discovery.parser_census.items():
        lines.append(f"| `{name}` | {count} |")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def build_candidates(
    snapshot_or_root: StagedSnapshot | Path,
    *,
    enforce_production_counts: bool = True,
) -> tuple[JsonObject, JsonObject, bytes, Discovery]:
    snapshot = (
        snapshot_or_root
        if isinstance(snapshot_or_root, StagedSnapshot)
        else StagedSnapshot.capture(snapshot_or_root)
    )
    inventory = _parse_json(snapshot.parser_entry(INVENTORY_PATH).data, label=INVENTORY_PATH)
    profiles = _parse_json(snapshot.parser_entry(PROFILES_PATH).data, label=PROFILES_PATH)
    _validate_registry_pair(inventory, profiles)
    discovery = discover(snapshot, enforce_production_counts=enforce_production_counts)
    rows = _array(inventory, "rows", label="inventory")
    foreign_rows = [
        row
        for row in rows
        if row.get("owner") != TASK_ID and not str(row.get("id", "")).startswith(ROW_PREFIX)
    ]
    if len(foreign_rows) != len([row for row in rows if row.get("owner") != TASK_ID]):
        _fail("foreign inventory row illegally uses the MP2-013 stable-ID namespace")
    profile_rows = _array(profiles, "profiles", label="profiles")
    foreign_profiles = [
        profile
        for profile in profile_rows
        if profile.get("owner") != TASK_ID and profile.get("id") != PROFILE_ID
    ]
    if len(foreign_profiles) != len(
        [profile for profile in profile_rows if profile.get("owner") != TASK_ID]
    ):
        _fail("foreign support profile illegally uses the MP2-013 profile ID")
    candidate_inventory = dict(inventory)
    candidate_inventory["rows"] = sorted(
        [*foreign_rows, *discovery.rows], key=lambda item: item["id"]
    )
    candidate_inventory["rows_sha256"] = _digest(candidate_inventory["rows"])
    candidate_profiles = dict(profiles)
    candidate_profiles["profiles"] = sorted(
        [*foreign_profiles, _profile(snapshot)], key=lambda item: item["id"]
    )
    candidate_profiles["profiles_sha256"] = _digest(candidate_profiles["profiles"])
    _validate_registry_pair(candidate_inventory, candidate_profiles)
    return candidate_inventory, candidate_profiles, _report(discovery), discovery


def _root_target(root: Path, relative: str) -> Path:
    _safe_path(relative)
    target = root.joinpath(*relative.split("/"))
    parent = target.parent.resolve(strict=True)
    if not parent.is_relative_to(root):
        _fail(f"generated target parent escapes repository: {relative}")
    try:
        info = target.lstat()
    except FileNotFoundError:
        return target
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"generated target is not a regular non-symlink file: {relative}")
    return target


def _current_target_bytes(root: Path, relative: str) -> bytes | None:
    target = _root_target(root, relative)
    try:
        target.lstat()
    except FileNotFoundError:
        return None
    return _read_regular_nofollow(target, label=f"generated target {relative}")


@contextlib.contextmanager
def _root_lock(root: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    if timeout < 0 or timeout > 60:
        _fail("root-lock timeout is outside the bounded range")
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    _fail("timed out acquiring exclusive repository-root generation lock")
                time.sleep(0.025)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.public-surface-{os.getpid()}.tmp")
    descriptor = -1
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode, follow_symlinks=False)
        _sync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _journal_record(
    path: str, old: bytes | None, old_mode: int | None, candidate: bytes
) -> JsonObject:
    candidate_mode = old_mode if old_mode is not None else 0o644
    return {
        "candidate_base64": base64.b64encode(candidate).decode("ascii"),
        "candidate_mode": candidate_mode,
        "candidate_sha256": _bytes_digest(candidate),
        "old_base64": None if old is None else base64.b64encode(old).decode("ascii"),
        "old_mode": old_mode,
        "old_sha256": None if old is None else _bytes_digest(old),
        "path": path,
    }


def _write_journal(directory: Path, journal: JsonObject) -> None:
    directory.mkdir(mode=0o700, exist_ok=False)
    _sync_directory(directory.parent)
    _atomic_write(directory / "journal.json", _canonical_bytes(journal), 0o600)


def _decode_journal_payload(value: Any, digest: Any, *, label: str) -> bytes | None:
    if value is None:
        if digest is not None:
            _fail(f"transaction {label} digest exists without bytes")
        return None
    if not isinstance(value, str) or not isinstance(digest, str):
        _fail(f"transaction {label} bytes/digest are malformed")
    try:
        payload = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise DiscoveryError(f"transaction {label} bytes are not canonical Base64") from exc
    if base64.b64encode(payload).decode("ascii") != value or _bytes_digest(payload) != digest:
        _fail(f"transaction {label} bytes do not match digest")
    return payload


def _load_journal(root: Path, directory: Path) -> JsonObject:
    try:
        info = directory.lstat()
    except FileNotFoundError:
        _fail("transaction directory disappeared during recovery")
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        _fail("transaction path is not a real directory")
    journal_path = directory / "journal.json"
    try:
        journal_info = journal_path.lstat()
    except OSError as exc:
        raise DiscoveryError(f"transaction journal is unavailable: {exc}") from exc
    if not stat.S_ISREG(journal_info.st_mode) or stat.S_ISLNK(journal_info.st_mode):
        _fail("transaction journal is not a regular non-symlink file")
    journal = _parse_json(journal_path.read_bytes(), label=journal_path.as_posix())
    if journal.get("schema_version") != TRANSACTION_SCHEMA:
        _fail("transaction journal schema version is unknown")
    if journal.get("phase") not in {"PREPARED", "COMMITTED"}:
        _fail("transaction journal phase is invalid")
    records = journal.get("targets")
    if (
        not isinstance(records, list)
        or len(records) != 3
        or any(not isinstance(item, dict) for item in records)
    ):
        _fail("transaction journal must bind exactly three targets")
    paths = [item.get("path") for item in records]
    if paths != sorted(GENERATED_PATHS):
        _fail("transaction journal target set is not canonical")
    for record in records:
        path = record.get("path")
        assert isinstance(path, str)
        _root_target(root, path)
        old_mode = record.get("old_mode")
        candidate_mode = record.get("candidate_mode")
        if old_mode is not None and (not isinstance(old_mode, int) or old_mode & ~0o777):
            _fail(f"transaction old mode is invalid: {path}")
        if not isinstance(candidate_mode, int) or candidate_mode & ~0o777:
            _fail(f"transaction candidate mode is invalid: {path}")
        _decode_journal_payload(record.get("old_base64"), record.get("old_sha256"), label="old")
        if (
            _decode_journal_payload(
                record.get("candidate_base64"), record.get("candidate_sha256"), label="candidate"
            )
            is None
        ):
            _fail("transaction candidate bytes cannot be absent")
    return journal


def _remove_transaction(directory: Path) -> None:
    journal = directory / "journal.json"
    journal.unlink(missing_ok=True)
    directory.rmdir()
    _sync_directory(directory.parent)


def _apply_journal(root: Path, journal: JsonObject, *, candidate: bool) -> None:
    records = journal["targets"]
    assert isinstance(records, list)
    for record in records:
        assert isinstance(record, dict)
        relative = record["path"]
        assert isinstance(relative, str)
        target = _root_target(root, relative)
        if candidate:
            payload = _decode_journal_payload(
                record["candidate_base64"], record["candidate_sha256"], label="candidate"
            )
            mode = record["candidate_mode"]
        else:
            payload = _decode_journal_payload(
                record["old_base64"], record["old_sha256"], label="old"
            )
            mode = record["old_mode"]
        if payload is None:
            target.unlink(missing_ok=True)
            _sync_directory(target.parent)
        else:
            assert isinstance(mode, int)
            _atomic_write(target, payload, mode)


def _recover_transaction(root: Path) -> None:
    directory = root / TRANSACTION_DIRECTORY
    try:
        directory.lstat()
    except FileNotFoundError:
        return
    journal = _load_journal(root, directory)
    _apply_journal(root, journal, candidate=journal["phase"] == "COMMITTED")
    _remove_transaction(directory)


def _replace_three(root: Path, candidates: Mapping[str, bytes]) -> None:
    if set(candidates) != GENERATED_PATHS:
        _fail("generation candidate target set is not canonical")
    directory = root / TRANSACTION_DIRECTORY
    records: list[JsonObject] = []
    for relative in sorted(GENERATED_PATHS):
        target = _root_target(root, relative)
        try:
            info = target.lstat()
            old = target.read_bytes()
            old_mode = stat.S_IMODE(info.st_mode)
        except FileNotFoundError:
            old = None
            old_mode = None
        records.append(_journal_record(relative, old, old_mode, candidates[relative]))
    journal: JsonObject = {
        "phase": "PREPARED",
        "schema_version": TRANSACTION_SCHEMA,
        "targets": records,
    }
    _write_journal(directory, journal)
    try:
        _apply_journal(root, journal, candidate=True)
        committed = dict(journal)
        committed["phase"] = "COMMITTED"
        _atomic_write(directory / "journal.json", _canonical_bytes(committed), 0o600)
        _remove_transaction(directory)
    except BaseException:
        with contextlib.suppress(BaseException):
            current = _load_journal(root, directory)
            _apply_journal(root, current, candidate=False)
            _remove_transaction(directory)
        raise


def run(
    command: str,
    *,
    repository_root: Path,
    enforce_production_counts: bool = True,
    lock_timeout: float = LOCK_TIMEOUT_SECONDS,
) -> int:
    root = repository_root.resolve(strict=True)
    if command not in {"check", "generate"}:
        _fail(f"unknown command: {command}")
    with _root_lock(root, timeout=lock_timeout):
        transaction = root / TRANSACTION_DIRECTORY
        try:
            transaction.lstat()
        except FileNotFoundError:
            transaction_exists = False
        else:
            transaction_exists = True
        if command == "check":
            if transaction_exists:
                _fail("check mode refuses to recover a pending generation transaction")
        else:
            _recover_transaction(root)
        snapshot = StagedSnapshot.capture(root)
        inventory, profiles, report, discovery = build_candidates(
            snapshot,
            enforce_production_counts=enforce_production_counts,
        )
        candidates = {
            INVENTORY_PATH: _document_bytes(inventory),
            PROFILES_PATH: _document_bytes(profiles),
            REPORT_PATH: report,
        }
        changed = [
            relative
            for relative, payload in candidates.items()
            if _current_target_bytes(root, relative) != payload
        ]
        if command == "check":
            if changed:
                print(
                    "public-surface inventory drift detected: " + ", ".join(sorted(changed)),
                    file=sys.stderr,
                )
                return 1
        elif command == "generate":
            if changed:
                _replace_three(root, candidates)
                for relative, expected in candidates.items():
                    if _current_target_bytes(root, relative) != expected:
                        _fail(f"generated target readback differs: {relative}")
    print(
        json.dumps(
            {
                "families": dict(discovery.family_counts),
                "manifest_keys": discovery.family_counts["manifest_keys"],
                "public_api": discovery.family_counts["public_api"],
                "rows": len(discovery.rows),
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "generate"))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--lock-timeout", type=float, default=LOCK_TIMEOUT_SECONDS)
    parser.add_argument(
        "--no-production-counts",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return run(
            arguments.command,
            repository_root=arguments.repository_root,
            enforce_production_counts=not arguments.no_production_counts,
            lock_timeout=arguments.lock_timeout,
        )
    except (DiscoveryError, OSError) as exc:
        print(f"public-surface discovery failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
