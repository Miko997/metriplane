# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Discover and govern the repository's complete CLI command surface."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

TASK_ID = "MP2-011"
PROFILE_ID = "repository.current-cli.measured"
ROW_PREFIX = f"{TASK_ID}.CLI."
CRITERIA = ("MP2-011.A01", "MP2-011.A02")
CONSUMERS = ("MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018")
INVENTORY_VALIDATOR = (
    "tests/test_discover_functional_surface.py::"
    "test_committed_inventory_matches_current_cli_surface"
)
PROFILE_VALIDATOR = (
    "tests/test_discover_functional_surface.py::"
    "test_cli_profile_is_closed_measured_and_not_an_environment_claim"
)
SCANNER_PATH = "tools/discover_functional_surface.py"

JsonObject = dict[str, Any]
CommandPath = tuple[str, ...]


class DiscoveryError(ValueError):
    """The source or committed registry cannot be interpreted canonically."""


@dataclass(frozen=True)
class EntryPoint:
    script: str
    target: str
    project_path: str
    module_path: str
    function: str
    adapter: bool


@dataclass(frozen=True)
class ParserCommand:
    command: CommandPath
    source_path: str
    aliases: tuple[str, ...]
    group: bool


@dataclass(frozen=True)
class RootDispatch:
    command: str
    target_path: str
    target_function: str


@dataclass(frozen=True)
class Discovery:
    adapter_console_scripts: int
    aliases: int
    entry_points: int
    implicit_config_routes: int
    parser_declarations: int
    parser_groups: int
    parser_leaves: int
    root_console_scripts: int
    root_dispatches: int
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


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_constant(value: str) -> NoReturn:
    _fail(f"non-finite JSON constant is forbidden: {value}")


def _reject_pairs(pairs: list[tuple[str, Any]]) -> JsonObject:
    value: JsonObject = {}
    for key, item in pairs:
        if key in value:
            _fail(f"duplicate JSON key is forbidden: {key!r}")
        value[key] = item
    return value


def _read_json(path: Path) -> JsonObject:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_reject_pairs, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"cannot read canonical JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"canonical JSON must be an object: {path}")
    return value


def _repository_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or "\\" in relative:
        _fail(f"repository path is not canonical: {relative!r}")
    candidate = root.joinpath(*relative.split("/"))
    try:
        info = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DiscoveryError(f"repository source is unavailable: {relative}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"repository source is not a regular non-symlink file: {relative}")
    if not resolved.is_relative_to(root):
        _fail(f"repository source escapes the repository: {relative}")
    return resolved


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise DiscoveryError(f"source path escapes the repository: {path}") from exc


def _parse_python(root: Path, relative: str) -> tuple[Path, ast.Module]:
    path = _repository_file(root, relative)
    try:
        return path, ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise DiscoveryError(f"cannot parse Python source {relative}: {exc}") from exc


def _module_file(root: Path, module: str, search_roots: tuple[Path, ...]) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module) is None:
        _fail(f"entry-point module is not literal and canonical: {module!r}")
    parts = module.split(".")
    candidates: list[Path] = []
    for search_root in search_roots:
        candidates.extend(
            (
                search_root.joinpath(*parts).with_suffix(".py"),
                search_root.joinpath(*parts, "__init__.py"),
            )
        )
    existing: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.is_file():
                existing.append(candidate.resolve(strict=True))
        except OSError as exc:
            raise DiscoveryError(f"cannot resolve entry-point module {module}: {exc}") from exc
    unique = sorted(set(existing))
    if len(unique) != 1:
        _fail(f"entry-point module must resolve to exactly one source: {module!r}")
    return _relative(root, unique[0])


def _parse_target(value: Any) -> tuple[str, str]:
    if not isinstance(value, str) or value.count(":") != 1:
        _fail(f"console-script target must be a literal module:function string: {value!r}")
    module, function = value.split(":", 1)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function) is None:
        _fail(f"console-script function is not canonical: {value!r}")
    return module, function


def _project_scripts(root: Path, project_path: str, *, adapter: bool) -> list[EntryPoint]:
    path = _repository_file(root, project_path)
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DiscoveryError(f"cannot parse project metadata {project_path}: {exc}") from exc
    project = document.get("project")
    if not isinstance(project, dict):
        _fail(f"project metadata has no project table: {project_path}")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        _fail(f"project.scripts must be a table: {project_path}")
    project_root = path.parent
    search_roots = (project_root / "src", project_root) if adapter else (root,)
    result: list[EntryPoint] = []
    for script, target in sorted(scripts.items()):
        if (
            not isinstance(script, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", script) is None
        ):
            _fail(f"console-script name is not canonical: {script!r}")
        module, function = _parse_target(target)
        result.append(
            EntryPoint(
                script=script,
                target=target,
                project_path=project_path,
                module_path=_module_file(root, module, search_roots),
                function=function,
                adapter=adapter,
            )
        )
    return result


def _entry_points(root: Path) -> tuple[EntryPoint, ...]:
    entries = _project_scripts(root, "pyproject.toml", adapter=False)
    adapters = root / "adapters"
    if not adapters.is_dir():
        _fail("repository has no direct adapters directory")
    for project in sorted(adapters.glob("*/pyproject.toml")):
        entries.extend(_project_scripts(root, _relative(root, project), adapter=True))
    names = [entry.script for entry in entries]
    if len(names) != len(set(names)):
        _fail("console-script names are not unique across root and direct adapters")
    return tuple(sorted(entries, key=lambda item: item.script))


def _function(
    module: ast.Module, name: str, *, source: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    functions = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(functions) != 1:
        _fail(f"callable {name!r} must resolve once in {source}")
    return functions[0]


def _assignment(call_node: ast.AST) -> tuple[str, ast.Call] | None:
    if (
        isinstance(call_node, ast.Assign)
        and len(call_node.targets) == 1
        and isinstance(call_node.targets[0], ast.Name)
        and isinstance(call_node.value, ast.Call)
    ):
        return call_node.targets[0].id, call_node.value
    if (
        isinstance(call_node, ast.AnnAssign)
        and isinstance(call_node.target, ast.Name)
        and isinstance(call_node.value, ast.Call)
    ):
        return call_node.target.id, call_node.value
    return None


def _call_attribute(call: ast.Call) -> tuple[str, str] | None:
    if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
        return None
    return call.func.value.id, call.func.attr


def _line(node: ast.AST) -> int:
    return int(getattr(node, "lineno", 0))


def _literal_aliases(call: ast.Call, *, source: str) -> tuple[str, ...]:
    values: tuple[str, ...] = ()
    aliases_seen = False
    for keyword in call.keywords:
        if keyword.arg is None:
            _fail(
                f"dynamic add_parser aliases via **kwargs are forbidden in {source}:{call.lineno}"
            )
        if keyword.arg != "aliases":
            continue
        if aliases_seen:
            _fail(f"duplicate add_parser aliases are forbidden in {source}:{call.lineno}")
        aliases_seen = True
        if not isinstance(keyword.value, (ast.List, ast.Tuple)):
            _fail(f"dynamic add_parser aliases are forbidden in {source}:{call.lineno}")
        aliases: list[str] = []
        for item in keyword.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                _fail(f"dynamic add_parser aliases are forbidden in {source}:{call.lineno}")
            aliases.append(item.value)
        if len(aliases) != len(set(aliases)):
            _fail(f"duplicate add_parser aliases are forbidden in {source}:{call.lineno}")
        values = tuple(sorted(aliases))
    return values


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []
        self.nested_scopes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.nested_scopes.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.nested_scopes.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.nested_scopes.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.nested_scopes.append(node)


def _parser_api_attribute(call: ast.Call) -> tuple[str, str] | None:
    attribute = _call_attribute(call)
    if attribute is None:
        return None
    receiver, method = attribute
    if method in {"add_parser", "add_subparsers"} or (
        receiver == "argparse" and method == "ArgumentParser"
    ):
        return attribute
    return None


def _parser_builder_functions(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> frozenset[str]:
    calls: dict[str, set[str]] = {}
    builders: set[str] = set()
    for name, function in functions.items():
        nodes = tuple(ast.walk(function))
        calls[name] = {
            node.func.id
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in functions
        }
        if any(
            isinstance(node, ast.Call) and _parser_api_attribute(node) is not None for node in nodes
        ):
            builders.add(name)

    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if name not in builders and callees & builders:
                builders.add(name)
                changed = True
    return frozenset(builders)


def _function_scope_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    source: str,
    parser_builders: frozenset[str],
) -> tuple[ast.AST, ...]:
    collector = _ScopeCollector()
    for statement in function.body:
        collector.visit(statement)
    for scope in collector.nested_scopes:
        for candidate in ast.walk(scope):
            if not isinstance(candidate, ast.Call):
                continue
            if _parser_api_attribute(candidate) is not None:
                _fail(f"nested parser declarations are forbidden in {source}:{_line(scope)}")
            if isinstance(candidate.func, ast.Name) and candidate.func.id in parser_builders:
                _fail(f"nested parser-builder calls are forbidden in {source}:{_line(scope)}")
    return tuple(
        sorted(
            collector.nodes,
            key=lambda node: (_line(node), int(getattr(node, "col_offset", -1))),
        )
    )


def _direct_call(node: ast.AST) -> tuple[str | None, ast.Call] | None:
    assigned = _assignment(node)
    if assigned is not None:
        return assigned
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return None, node.value
    return None


def _parser_commands(
    root: Path, source: str, function_name: str, prefix: CommandPath
) -> tuple[ParserCommand, ...]:
    _path, module = _parse_python(root, source)
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    _function(module, function_name, source=source)
    parser_builders = _parser_builder_functions(functions)
    pending = [function_name]
    reachable: list[str] = []
    scoped_nodes: dict[str, tuple[ast.AST, ...]] = {}
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.append(current)
        nodes = _function_scope_nodes(
            functions[current], source=source, parser_builders=parser_builders
        )
        scoped_nodes[current] = nodes
        called = {
            call.func.id
            for call in nodes
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in functions
        }
        pending.extend(sorted(called, reverse=True))
    declarations: list[tuple[CommandPath, tuple[str, ...]]] = []
    for reachable_name in reachable:
        nodes = scoped_nodes[reachable_name]
        parser_paths: dict[str, CommandPath] = {}
        subparser_paths: dict[str, CommandPath] = {}
        handled_calls: set[int] = set()
        for node in nodes:
            direct = _direct_call(node)
            if direct is None:
                continue
            target, call = direct
            attribute = _parser_api_attribute(call)
            if attribute is None:
                continue
            handled_calls.add(id(call))
            receiver, method = attribute
            if method == "ArgumentParser" and receiver == "argparse":
                if target is None:
                    _fail(f"ArgumentParser must be assigned in {source}:{_line(node)}")
                if target in parser_paths or target in subparser_paths:
                    _fail(f"ambiguous parser variable {target!r} in {source}:{_line(node)}")
                parser_paths[target] = prefix
                continue
            if method == "add_subparsers":
                if target is None:
                    _fail(f"add_subparsers must be assigned in {source}:{_line(node)}")
                if receiver not in parser_paths:
                    _fail(f"unresolved add_subparsers owner in {source}:{_line(node)}")
                if target in parser_paths or target in subparser_paths:
                    _fail(f"ambiguous subparser variable {target!r} in {source}:{_line(node)}")
                subparser_paths[target] = parser_paths[receiver]
                continue
            if method != "add_parser":
                continue
            if receiver not in subparser_paths:
                _fail(f"unresolved add_parser owner in {source}:{_line(node)}")
            if (
                not call.args
                or not isinstance(call.args[0], ast.Constant)
                or not isinstance(call.args[0].value, str)
            ):
                _fail(f"dynamic add_parser names are forbidden in {source}:{_line(node)}")
            name = call.args[0].value
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None:
                _fail(f"add_parser name is not canonical in {source}:{_line(node)}")
            command = (*subparser_paths[receiver], name)
            if command in {item[0] for item in declarations}:
                _fail(f"duplicate command path is forbidden: {' '.join(command)}")
            declarations.append((command, _literal_aliases(call, source=source)))
            if target is None:
                continue
            if target in parser_paths or target in subparser_paths:
                _fail(f"ambiguous parser variable {target!r} in {source}:{_line(node)}")
            parser_paths[target] = command
        for node in nodes:
            if (
                isinstance(node, ast.Call)
                and _parser_api_attribute(node) is not None
                and id(node) not in handled_calls
            ):
                _fail(
                    "parser declarations must be direct assignments or expressions in "
                    f"{source}:{_line(node)}"
                )
    command_set = {item[0] for item in declarations}
    return tuple(
        ParserCommand(
            command=command,
            source_path=source,
            aliases=aliases,
            group=any(other[:-1] == command for other in command_set),
        )
        for command, aliases in declarations
    )


def _argv_zero_compare(node: ast.AST, *, source: str) -> str | None:
    for candidate in ast.walk(node):
        if not isinstance(candidate, ast.Compare) or len(candidate.ops) != 1:
            continue
        left = candidate.left
        if not (
            isinstance(left, ast.Subscript)
            and isinstance(left.value, ast.Name)
            and left.value.id == "argv"
            and isinstance(left.slice, ast.Constant)
            and left.slice.value == 0
        ):
            continue
        if not isinstance(candidate.ops[0], ast.Eq) or len(candidate.comparators) != 1:
            _fail(f"root argv[0] dispatch must use literal equality in {source}:{candidate.lineno}")
        comparator = candidate.comparators[0]
        if not isinstance(comparator, ast.Constant) or not isinstance(comparator.value, str):
            _fail(f"dynamic root argv[0] dispatch is forbidden in {source}:{candidate.lineno}")
        return comparator.value
    return None


def _return_call_names(nodes: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for statement in nodes:
        for node in ast.walk(statement):
            if isinstance(node, ast.Return) and node.value is not None:
                for call in ast.walk(node.value):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                        names.add(call.func.id)
    return names


def _root_dispatches(root: Path, entry: EntryPoint) -> tuple[RootDispatch, ...]:
    source = entry.module_path
    _path, module = _parse_python(root, source)
    function = _function(module, entry.function, source=source)
    local_functions = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    dispatches: list[RootDispatch] = []
    for statement in function.body:
        if not isinstance(statement, ast.If):
            continue
        command = _argv_zero_compare(statement.test, source=source)
        if command is None:
            continue
        imports: dict[str, tuple[str, str]] = {}
        for node in ast.walk(statement):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module, alias.name)
        targets: set[tuple[str, str]] = set()
        for name in _return_call_names(statement.body):
            if name in imports:
                module_name, function_name = imports[name]
                targets.add((_module_file(root, module_name, (root,)), function_name))
            elif name in local_functions:
                targets.add((source, name))
        if len(targets) != 1:
            _fail(f"root dispatch {command!r} must resolve to one callable in {source}")
        target_path, target_function = targets.pop()
        dispatches.append(RootDispatch(command, target_path, target_function))
    commands = [item.command for item in dispatches]
    if len(commands) != len(set(commands)):
        _fail("root dispatcher contains duplicate command tokens")
    direct_run_fallback = False
    for node in ast.walk(function):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        for call in ast.walk(node.value):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_main_run"
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "argv"
            ):
                direct_run_fallback = True
    if not direct_run_fallback:
        _fail("root dispatcher has no literal implicit-config fallback")
    return tuple(sorted(dispatches, key=lambda item: item.command))


def _normalize(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    if not normalized:
        _fail(f"cannot normalize stable ID component: {value!r}")
    return normalized


def _source(root: Path, path: str, locator: str) -> JsonObject:
    return {
        "digest_sha256": _file_digest(_repository_file(root, path)),
        "locator": locator,
        "path": path,
        "type": "repository_discovery",
    }


def _row(
    root: Path,
    *,
    identifier: str,
    kind: str,
    name: str,
    statement: str,
    source_path: str,
    locator: str,
    obligation: str,
    criteria: tuple[str, ...],
) -> JsonObject:
    return {
        "claim": {
            "classification": "compatibility",
            "limitation_ids": [],
            "statement": statement,
        },
        "consumer_task_ids": list(CONSUMERS),
        "id": identifier,
        "kind": kind,
        "name": name,
        "owner": TASK_ID,
        "profile": PROFILE_ID,
        "source": _source(root, source_path, locator),
        "status": "active",
        "test": obligation,
        "trace_criterion_ids": list(criteria),
        "validator_ids": [INVENTORY_VALIDATOR],
    }


def discover(repository_root: Path, *, minimum_leaf_actions: int = 71) -> Discovery:
    root = repository_root.resolve(strict=True)
    if minimum_leaf_actions < 1:
        _fail("minimum leaf-action floor must be positive")
    entries = _entry_points(root)
    root_entries = [entry for entry in entries if not entry.adapter]
    root_dispatch_entry = [entry for entry in root_entries if entry.script == "metriplane"]
    if len(root_dispatch_entry) != 1:
        _fail("root project must declare exactly one metriplane console script")
    dispatches = _root_dispatches(root, root_dispatch_entry[0])
    parser_commands: list[ParserCommand] = []
    for dispatch in dispatches:
        parser_commands.extend(
            _parser_commands(
                root,
                dispatch.target_path,
                dispatch.target_function,
                ("metriplane", dispatch.command),
            )
        )
    for entry in entries:
        if entry.adapter:
            parser_commands.extend(
                _parser_commands(root, entry.module_path, entry.function, (entry.script,))
            )
    command_paths = [item.command for item in parser_commands]
    if len(command_paths) != len(set(command_paths)):
        _fail("reachable parser command paths are not unique")
    leaves = sum(not item.group for item in parser_commands)
    groups = sum(item.group for item in parser_commands)
    if leaves < minimum_leaf_actions:
        _fail(f"leaf-action floor failed: observed {leaves}, required {minimum_leaf_actions}")

    rows: list[JsonObject] = []
    for entry in entries:
        obligation = (
            "MP2-011.OBL.ADAPTER_ENTRY_POINTS"
            if entry.adapter
            else (
                "MP2-011.OBL.STANDALONE_RUN_ENTRY_POINT"
                if entry.script == "metriplane-run"
                else "MP2-011.OBL.CANONICAL_DISCOVERY"
            )
        )
        rows.append(
            _row(
                root,
                identifier=f"{ROW_PREFIX}ENTRYPOINT.{_normalize(entry.script)}",
                kind="cli_entry_point",
                name=entry.script,
                statement=f"Repository metadata declares the {entry.script} console script.",
                source_path=entry.project_path,
                locator=f"project.scripts.{entry.script}={entry.target}",
                obligation=obligation,
                criteria=("MP2-011.A01",),
            )
        )
    root_source = root_dispatch_entry[0].module_path
    for dispatch in dispatches:
        command = f"metriplane {dispatch.command}"
        rows.append(
            _row(
                root,
                identifier=f"{ROW_PREFIX}COMMAND.{_normalize(command)}",
                kind="cli_command",
                name=command,
                statement=f"The root dispatcher exposes the {command} command.",
                source_path=root_source,
                locator=command,
                obligation="MP2-011.OBL.ROOT_DISPATCH",
                criteria=("MP2-011.A01",),
            )
        )
    alias_count = 0
    for item in sorted(parser_commands, key=lambda value: value.command):
        command = " ".join(item.command)
        rows.append(
            _row(
                root,
                identifier=f"{ROW_PREFIX}COMMAND.{_normalize(command)}",
                kind="cli_command_group" if item.group else "cli_command",
                name=command,
                statement=(
                    f"Static parser discovery exposes the {'grouping' if item.group else 'leaf'} "
                    f"command {command}."
                ),
                source_path=item.source_path,
                locator=command,
                obligation="MP2-011.OBL.SUBPARSER_CENSUS",
                criteria=("MP2-011.A02",),
            )
        )
        for alias in item.aliases:
            alias_command = " ".join((*item.command[:-1], alias))
            alias_count += 1
            rows.append(
                _row(
                    root,
                    identifier=f"{ROW_PREFIX}ALIAS.{_normalize(alias_command)}",
                    kind="cli_alias",
                    name=alias_command,
                    statement=f"The compatibility alias {alias_command} resolves to {command}.",
                    source_path=item.source_path,
                    locator=f"{alias_command}->{command}",
                    obligation="MP2-011.OBL.ALIAS_DISCOVERY",
                    criteria=("MP2-011.A01",),
                )
            )
    rows.append(
        _row(
            root,
            identifier=f"{ROW_PREFIX}IMPLICIT_CONFIG",
            kind="cli_implicit_config",
            name="metriplane implicit runtime configuration",
            statement=(
                "The terminal root fallback preserves no-command and leading --config runtime "
                "invocations."
            ),
            source_path=root_source,
            locator="main terminal fallback:_main_run(argv)",
            obligation="MP2-011.OBL.IMPLICIT_CONFIG",
            criteria=("MP2-011.A01",),
        )
    )
    rows.sort(key=lambda item: item["id"])
    ids = [str(item["id"]) for item in rows]
    if len(ids) != len(set(ids)):
        _fail("normalized functional row IDs collide")
    return Discovery(
        adapter_console_scripts=sum(entry.adapter for entry in entries),
        aliases=alias_count,
        entry_points=len(entries),
        implicit_config_routes=1,
        parser_declarations=len(parser_commands),
        parser_groups=groups,
        parser_leaves=leaves,
        root_console_scripts=len(root_entries),
        root_dispatches=len(dispatches),
        rows=tuple(rows),
    )


def _profile(root: Path) -> JsonObject:
    return {
        "claim": {
            "classification": "compatibility",
            "limitation_ids": [],
            "statement": (
                "Static repository CLI discovery is measured at the current source bytes; this "
                "profile makes no runtime platform support claim."
            ),
        },
        "id": PROFILE_ID,
        "kind": "repository_cli_discovery",
        "owner": TASK_ID,
        "source": _source(root, SCANNER_PATH, "canonical CLI discovery scanner"),
        "status": "active",
        "support_disposition": "measured",
        "test": "MP2-011.OBL.PROFILE",
    }


def _array(document: JsonObject, field: str, *, label: str) -> list[JsonObject]:
    value = document.get(field)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        _fail(f"{label}.{field} must be an array of objects")
    return value


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
    profile_ids = {str(item["id"]) for item in profile_rows}
    for row in rows:
        if row.get("status") in {"active", "deprecated"} and row.get("profile") not in profile_ids:
            _fail(f"functional row has no active profile binding: {row.get('id')}")
        if require_owned_projection and str(row.get("id", "")).startswith(ROW_PREFIX):
            required = {
                "claim",
                "consumer_task_ids",
                "id",
                "kind",
                "name",
                "owner",
                "profile",
                "source",
                "status",
                "test",
                "trace_criterion_ids",
                "validator_ids",
            }
            if (
                set(row) != required
                or row.get("owner") != TASK_ID
                or row.get("profile") != PROFILE_ID
            ):
                _fail(f"generated row shape or ownership is invalid: {row.get('id')}")
            source = row.get("source")
            if not isinstance(source, dict) or source.get("type") != "repository_discovery":
                _fail(f"generated row source is invalid: {row.get('id')}")
            source_path = source.get("path")
            if not isinstance(source_path, str) or source.get("digest_sha256") != _file_digest(
                _repository_file(root, source_path)
            ):
                _fail(f"generated row source digest is stale: {row.get('id')}")
    owned_profiles = [item for item in profile_rows if item.get("owner") == TASK_ID]
    if require_owned_projection:
        if len(owned_profiles) != 1 or owned_profiles[0].get("id") != PROFILE_ID:
            _fail("MP2-011 must own exactly one canonical support profile")
        profile = owned_profiles[0]
        if (
            profile.get("support_disposition") != "measured"
            or not isinstance(profile.get("claim"), dict)
            or profile["claim"].get("classification") != "compatibility"
        ):
            _fail("MP2-011 support profile is not a measured compatibility claim")


def build_candidates(
    repository_root: Path,
    inventory_path: Path,
    profiles_path: Path,
    *,
    minimum_leaf_actions: int = 71,
) -> tuple[JsonObject, JsonObject, Discovery]:
    root = repository_root.resolve(strict=True)
    inventory = _read_json(inventory_path)
    profiles = _read_json(profiles_path)
    _validate_pair(root, inventory, profiles)
    discovered = discover(root, minimum_leaf_actions=minimum_leaf_actions)
    foreign_rows = [
        item
        for item in _array(inventory, "rows", label="inventory")
        if not str(item.get("id", "")).startswith(ROW_PREFIX)
    ]
    foreign_profiles = [
        item
        for item in _array(profiles, "profiles", label="profiles")
        if item.get("id") != PROFILE_ID and item.get("owner") != TASK_ID
    ]
    candidate_inventory = dict(inventory)
    candidate_inventory["rows"] = sorted(
        [*foreign_rows, *discovered.rows], key=lambda item: item["id"]
    )
    candidate_inventory["rows_sha256"] = _digest(candidate_inventory["rows"])
    candidate_profiles = dict(profiles)
    candidate_profiles["profiles"] = sorted(
        [*foreign_profiles, _profile(root)], key=lambda item: item["id"]
    )
    candidate_profiles["profiles_sha256"] = _digest(candidate_profiles["profiles"])
    _validate_pair(
        root,
        candidate_inventory,
        candidate_profiles,
        require_owned_projection=True,
    )
    return candidate_inventory, candidate_profiles, discovered


def _stage(path: Path, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    staged = Path(raw_path)
    try:
        os.fchmod(descriptor, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
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


def _replace_pair(
    inventory_path: Path,
    inventory_bytes: bytes,
    profiles_path: Path,
    profiles_bytes: bytes,
) -> None:
    old_inventory = inventory_path.read_bytes()
    old_profiles = profiles_path.read_bytes()
    staged_inventory = _stage(inventory_path, inventory_bytes)
    staged_profiles = _stage(profiles_path, profiles_bytes)
    replaced_profiles = False
    replaced_inventory = False
    try:
        os.replace(staged_profiles, profiles_path)
        replaced_profiles = True
        os.replace(staged_inventory, inventory_path)
        replaced_inventory = True
        _sync_directory(profiles_path.parent)
        if inventory_path.parent != profiles_path.parent:
            _sync_directory(inventory_path.parent)
    except BaseException:
        if replaced_profiles:
            rollback = _stage(profiles_path, old_profiles)
            os.replace(rollback, profiles_path)
        if replaced_inventory:
            rollback = _stage(inventory_path, old_inventory)
            os.replace(rollback, inventory_path)
        _sync_directory(profiles_path.parent)
        if inventory_path.parent != profiles_path.parent:
            _sync_directory(inventory_path.parent)
        raise
    finally:
        staged_inventory.unlink(missing_ok=True)
        staged_profiles.unlink(missing_ok=True)


def run(
    command: str,
    *,
    repository_root: Path,
    inventory: Path,
    profiles: Path,
    minimum_leaf_actions: int,
) -> int:
    root = repository_root.resolve(strict=True)
    inventory_path = (
        (root / inventory).resolve() if not inventory.is_absolute() else inventory.resolve()
    )
    profiles_path = (
        (root / profiles).resolve() if not profiles.is_absolute() else profiles.resolve()
    )
    if not inventory_path.is_relative_to(root) or not profiles_path.is_relative_to(root):
        _fail("registry paths must remain inside the repository")
    candidate_inventory, candidate_profiles, discovered = build_candidates(
        root,
        inventory_path,
        profiles_path,
        minimum_leaf_actions=minimum_leaf_actions,
    )
    inventory_bytes = _document_bytes(candidate_inventory)
    profiles_bytes = _document_bytes(candidate_profiles)
    changed = (
        inventory_path.read_bytes() != inventory_bytes
        or profiles_path.read_bytes() != profiles_bytes
    )
    if command == "check":
        if changed:
            print("functional CLI inventory drift detected", file=sys.stderr)
            return 1
    elif command == "generate":
        if changed:
            _replace_pair(inventory_path, inventory_bytes, profiles_path, profiles_bytes)
            verified_inventory = _read_json(inventory_path)
            verified_profiles = _read_json(profiles_path)
            _validate_pair(root, verified_inventory, verified_profiles)
            if verified_inventory != candidate_inventory or verified_profiles != candidate_profiles:
                _fail("generated registry readback differs from the validated candidate")
    else:
        _fail(f"unknown command: {command}")
    print(
        json.dumps(
            {
                "aliases": discovered.aliases,
                "entry_points": discovered.entry_points,
                "groups": discovered.parser_groups,
                "leaves": discovered.parser_leaves,
                "parser_declarations": discovered.parser_declarations,
                "root_dispatches": discovered.root_dispatches,
                "rows": len(discovered.rows),
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "generate"))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--inventory", type=Path, default=Path("docs/status/functional-inventory.json")
    )
    parser.add_argument("--profiles", type=Path, default=Path("docs/status/support-profiles.json"))
    parser.add_argument("--minimum-leaf-actions", type=int, default=71)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(
            args.command,
            repository_root=args.repository_root,
            inventory=args.inventory,
            profiles=args.profiles,
            minimum_leaf_actions=args.minimum_leaf_actions,
        )
    except (DiscoveryError, OSError) as exc:
        print(f"functional CLI discovery failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
