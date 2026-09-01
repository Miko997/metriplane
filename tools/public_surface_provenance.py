# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Stable, bounded provenance analysis for public-surface discovery.

The kernel keeps parsed AST input immutable, assigns structural semantic
identities, and resolves one finite query graph through a deterministic
non-recursive worklist. Unsupported or incomplete interpretation stays
explicitly unresolved so inventory consumers fail closed.
"""

from __future__ import annotations

import ast
import hashlib
import heapq
import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias, cast


class AnalysisError(ValueError):
    """The maintained source or the analysis graph violates a kernel invariant."""


def _canonical_data(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                item.name: _canonical_data(getattr(value, item.name)) for item in fields(value)
            },
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_data(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (frozenset, set)):
        encoded = [_canonical_data(item) for item in value]
        return sorted(encoded, key=_canonical_bytes)
    if isinstance(value, (list, tuple)):
        return [_canonical_data(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"value has no canonical representation: {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_data(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, order=True)
class ModuleId:
    import_name: str
    tracked_path: str
    blob_digest: str


@dataclass(frozen=True)
class NodeId:
    module: ModuleId
    node_kind: str
    path: tuple[str, ...]
    located: bool
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self)


@dataclass(frozen=True)
class ScopeId:
    module: ModuleId
    lexical_kind: str
    owner: NodeId
    qualified_label: str

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self)


@dataclass(frozen=True)
class BindingId:
    scope: ScopeId
    local_name: str
    defining_node: NodeId
    ordinal: int


@dataclass(frozen=True)
class FunctionId:
    module: ModuleId
    qualified_name: str
    defining_node: NodeId


@dataclass(frozen=True)
class ClassId:
    module: ModuleId
    qualified_name: str
    defining_node: NodeId


@dataclass(frozen=True)
class ProgramPointId:
    scope: ScopeId
    statement_ordinal: int
    expression: NodeId


@dataclass(frozen=True, order=True)
class EnvironmentId:
    sha256: str


@dataclass(frozen=True)
class InvocationContextId:
    caller_label: str
    immediate_call_site: NodeId


@dataclass(frozen=True, order=True)
class BindingPlanId:
    sha256: str


@dataclass(frozen=True)
class ModuleSource:
    import_name: str
    tracked_path: str
    source_text: str

    def parse(self) -> ast.Module:
        path = PurePosixPath(self.tracked_path)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != self.tracked_path:
            raise AnalysisError(f"non-canonical tracked path: {self.tracked_path!r}")
        return ast.parse(self.source_text, filename=self.tracked_path)

    @property
    def module_id(self) -> ModuleId:
        return ModuleId(
            self.import_name,
            self.tracked_path,
            hashlib.sha256(self.source_text.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class ChildEdge:
    field_name: str
    ordinal: int
    child: NodeId


@dataclass(frozen=True)
class MarkerEdge:
    field_name: str
    ordinal: int
    marker_kind: str


@dataclass(frozen=True)
class NodeOccurrence:
    """One structural AST occurrence and its stable semantic identity."""

    semantic_id: NodeId
    path: tuple[str, ...]
    node: ast.AST


@dataclass(frozen=True)
class BindingRecord:
    identity: BindingId
    value: NodeId | None
    annotation: NodeId | None


@dataclass(frozen=True)
class FunctionRecord:
    identity: FunctionId
    definition_scope: ScopeId
    body_scope: ScopeId
    returns: tuple[NodeId, ...]
    return_root_names: tuple[str, ...]


@dataclass(frozen=True)
class ClassRecord:
    identity: ClassId
    definition_scope: ScopeId
    body_scope: ScopeId


_MARKER_TYPES = (
    ast.expr_context,
    ast.operator,
    ast.unaryop,
    ast.boolop,
    ast.cmpop,
)


def _node_id(module: ModuleId, node: ast.AST, path: tuple[str, ...]) -> NodeId:
    raw_line: object = getattr(node, "lineno", None)
    raw_column: object = getattr(node, "col_offset", None)
    located = isinstance(raw_line, int) and isinstance(raw_column, int)
    start_line: int = raw_line if isinstance(raw_line, int) else 0
    start_column: int = raw_column if isinstance(raw_column, int) else 0
    raw_end_line: object = getattr(node, "end_lineno", None)
    raw_end_column: object = getattr(node, "end_col_offset", None)
    end_line: int = raw_end_line if isinstance(raw_end_line, int) else start_line
    end_column: int = raw_end_column if isinstance(raw_end_column, int) else start_column
    return NodeId(
        module=module,
        node_kind=type(node).__name__,
        path=path,
        located=located,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
    )


def _node_sort_key(node: NodeId) -> tuple[Any, ...]:
    return (
        node.module.import_name,
        node.start_line,
        node.start_column,
        node.end_line,
        node.end_column,
        node.path,
        node.node_kind,
    )


def _target_names(
    index_nodes: Mapping[NodeId, ast.AST],
    children: Mapping[NodeId, tuple[ChildEdge, ...]],
    root: NodeId,
) -> tuple[tuple[str, NodeId], ...]:
    result: list[tuple[str, NodeId]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        node = index_nodes[current]
        if isinstance(node, ast.Name):
            result.append((node.id, current))
            continue
        if isinstance(node, (ast.List, ast.Tuple)):
            nested = [edge.child for edge in children.get(current, ()) if edge.field_name == "elts"]
            pending.extend(reversed(nested))
    return tuple(result)


def _root_name(
    index_nodes: Mapping[NodeId, ast.AST],
    children: Mapping[NodeId, tuple[ChildEdge, ...]],
    root: NodeId,
) -> str | None:
    current = root
    while True:
        node = index_nodes[current]
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            value = next(
                (edge.child for edge in children.get(current, ()) if edge.field_name == "value"),
                None,
            )
            if value is None:
                return None
            current = value
            continue
        return None


def _possible_root_names(
    index_nodes: Mapping[NodeId, ast.AST],
    children: Mapping[NodeId, tuple[ChildEdge, ...]],
    root: NodeId,
) -> frozenset[str]:
    found: set[str] = set()
    pending = [root]
    visited: set[NodeId] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        root_name = _root_name(index_nodes, children, current)
        if root_name is not None:
            found.add(root_name)
            continue
        node = index_nodes[current]
        if isinstance(node, ast.IfExp):
            fields = {"body", "orelse"}
        elif isinstance(node, ast.Dict):
            fields = {"values"}
        elif isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            fields = {"elts"}
        else:
            continue
        pending.extend(
            edge.child for edge in children.get(current, ()) if edge.field_name in fields
        )
    return frozenset(found)


class ProgramIndex:
    """Immutable side tables over parsed ASTs.

    AST objects are values addressed only through stable ``NodeId`` keys.  No
    reverse object-identity table exists.
    """

    def __init__(
        self,
        *,
        modules: Mapping[ModuleId, ast.Module],
        module_roots: Mapping[ModuleId, NodeId],
        nodes: Mapping[NodeId, ast.AST],
        children: Mapping[NodeId, tuple[ChildEdge, ...]],
        markers: Mapping[NodeId, tuple[MarkerEdge, ...]],
        parents: Mapping[NodeId, NodeId | None],
        scopes: Mapping[NodeId, ScopeId],
        owned_scopes: Mapping[NodeId, ScopeId],
        scope_parents: Mapping[ScopeId, ScopeId | None],
        nodes_in_scope: Mapping[ScopeId, tuple[NodeId, ...]],
        bindings: Mapping[tuple[ScopeId, str], tuple[BindingRecord, ...]],
        functions: Mapping[FunctionId, FunctionRecord],
        function_lookup: Mapping[tuple[ScopeId, str], FunctionId],
        classes: Mapping[ClassId, ClassRecord],
        environments: Mapping[ScopeId, EnvironmentId],
        statement_ordinals: Mapping[NodeId, int],
        fingerprints: Mapping[ModuleId, str],
    ) -> None:
        self.modules = MappingProxyType(dict(modules))
        self.module_roots = MappingProxyType(dict(module_roots))
        self.nodes = MappingProxyType(dict(nodes))
        self.children = MappingProxyType(dict(children))
        self.markers = MappingProxyType(dict(markers))
        self.parents = MappingProxyType(dict(parents))
        self.scopes = MappingProxyType(dict(scopes))
        self.owned_scopes = MappingProxyType(dict(owned_scopes))
        self.scope_parents = MappingProxyType(dict(scope_parents))
        self.nodes_in_scope = MappingProxyType(dict(nodes_in_scope))
        self.bindings = MappingProxyType(dict(bindings))
        self.functions = MappingProxyType(dict(functions))
        self.function_lookup = MappingProxyType(dict(function_lookup))
        self.classes = MappingProxyType(dict(classes))
        self.environments = MappingProxyType(dict(environments))
        self.statement_ordinals = MappingProxyType(dict(statement_ordinals))
        self._fingerprints = MappingProxyType(dict(fingerprints))

    @property
    def occurrences(self) -> tuple[NodeOccurrence, ...]:
        """Return structural nodes in deterministic semantic-ID order.

        Python's singleton context/operator marker objects are represented by
        ``MarkerEdge`` tags and intentionally do not receive semantic IDs.
        """

        return tuple(
            NodeOccurrence(identity, identity.path, self.nodes[identity])
            for identity in sorted(self.nodes, key=lambda item: item.canonical_bytes)
        )

    @property
    def fingerprints(self) -> Mapping[ModuleId, str]:
        return self._fingerprints

    def semantic_id(
        self,
        path: tuple[str, ...],
        *,
        module_name: str | None = None,
    ) -> NodeId:
        matches = [
            identity
            for identity in self.nodes
            if identity.path == path
            and (module_name is None or identity.module.import_name == module_name)
        ]
        if len(matches) != 1:
            raise AnalysisError(
                f"structural path must identify exactly one node: {module_name!r}:{path!r}"
            )
        return matches[0]

    @classmethod
    def build(cls, sources: Sequence[ModuleSource]) -> ProgramIndex:
        if not sources:
            raise AnalysisError("analysis requires at least one module")
        ordered_sources = sorted(sources, key=lambda item: (item.import_name, item.tracked_path))
        module_ids = [source.module_id for source in ordered_sources]
        if len(module_ids) != len(set(module_ids)):
            raise AnalysisError("duplicate module identity")
        if len({item.import_name for item in module_ids}) != len(module_ids):
            raise AnalysisError("duplicate canonical import name")

        modules: dict[ModuleId, ast.Module] = {}
        roots: dict[ModuleId, NodeId] = {}
        nodes: dict[NodeId, ast.AST] = {}
        children: dict[NodeId, tuple[ChildEdge, ...]] = {}
        markers: dict[NodeId, tuple[MarkerEdge, ...]] = {}
        parents: dict[NodeId, NodeId | None] = {}
        scopes: dict[NodeId, ScopeId] = {}
        owned_scopes: dict[NodeId, ScopeId] = {}
        scope_parents: dict[ScopeId, ScopeId | None] = {}
        fingerprints: dict[ModuleId, str] = {}

        for source in ordered_sources:
            module_id = source.module_id
            tree = source.parse()
            root = _node_id(module_id, tree, ())
            module_scope = ScopeId(module_id, "module", root, module_id.import_name)
            modules[module_id] = tree
            roots[module_id] = root
            nodes[root] = tree
            parents[root] = None
            scopes[root] = module_scope
            owned_scopes[root] = module_scope
            scope_parents[module_scope] = None
            fingerprints[module_id] = ast.dump(tree, annotate_fields=True, include_attributes=True)

            pending: list[tuple[NodeId, ast.AST, ScopeId]] = [(root, tree, module_scope)]
            while pending:
                current_id, current_node, current_scope = pending.pop()
                child_scope = current_scope
                if isinstance(current_node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
                    label = (
                        current_node.name
                        if isinstance(current_node, (ast.AsyncFunctionDef, ast.FunctionDef))
                        else f"<lambda@{current_id.start_line}:{current_id.start_column}>"
                    )
                    qualified = f"{current_scope.qualified_label}.{label}"
                    child_scope = ScopeId(module_id, "function", current_id, qualified)
                elif isinstance(current_node, ast.ClassDef):
                    qualified = f"{current_scope.qualified_label}.{current_node.name}"
                    child_scope = ScopeId(module_id, "class", current_id, qualified)
                elif isinstance(
                    current_node,
                    (ast.DictComp, ast.GeneratorExp, ast.ListComp, ast.SetComp),
                ):
                    label = f"<comprehension@{current_id.start_line}:{current_id.start_column}>"
                    child_scope = ScopeId(
                        module_id,
                        "comprehension",
                        current_id,
                        f"{current_scope.qualified_label}.{label}",
                    )
                if child_scope != current_scope:
                    owned_scopes[current_id] = child_scope
                    scope_parents[child_scope] = current_scope

                discovered: list[tuple[ChildEdge, ast.AST, ScopeId]] = []
                marker_edges: list[MarkerEdge] = []
                for field_name, raw_value in ast.iter_fields(current_node):
                    values: Iterable[tuple[int, ast.AST]]
                    if isinstance(raw_value, ast.AST):
                        values = ((0, raw_value),)
                    elif isinstance(raw_value, list):
                        values = (
                            (ordinal, item)
                            for ordinal, item in enumerate(raw_value)
                            if isinstance(item, ast.AST)
                        )
                    else:
                        continue
                    for ordinal, child_node in values:
                        if isinstance(child_node, _MARKER_TYPES):
                            marker_edges.append(
                                MarkerEdge(field_name, ordinal, type(child_node).__name__)
                            )
                            continue
                        path = (*current_id.path, f"{field_name}[{ordinal}]")
                        identity = _node_id(module_id, child_node, path)
                        if identity in nodes:
                            raise AnalysisError(
                                f"stable node identity collision: {identity.node_kind} {identity.path}"
                            )
                        nodes[identity] = child_node
                        parents[identity] = current_id
                        scopes[identity] = child_scope
                        edge = ChildEdge(field_name, ordinal, identity)
                        discovered.append((edge, child_node, child_scope))
                children[current_id] = tuple(item[0] for item in discovered)
                markers[current_id] = tuple(marker_edges)
                for edge, child_node, scope in reversed(discovered):
                    pending.append((edge.child, child_node, scope))

        grouped_nodes: dict[ScopeId, list[NodeId]] = defaultdict(list)
        for identity, scope in scopes.items():
            grouped_nodes[scope].append(identity)
        nodes_in_scope = {
            scope: tuple(sorted(values, key=_node_sort_key))
            for scope, values in grouped_nodes.items()
        }

        statement_ordinals: dict[NodeId, int] = {}
        for scope, identities in nodes_in_scope.items():
            statements = [
                identity for identity in identities if isinstance(nodes[identity], ast.stmt)
            ]
            for ordinal, identity in enumerate(statements):
                statement_ordinals[identity] = ordinal

        functions: dict[FunctionId, FunctionRecord] = {}
        function_lookup: dict[tuple[ScopeId, str], FunctionId] = {}
        classes: dict[ClassId, ClassRecord] = {}
        for identity in sorted(nodes, key=_node_sort_key):
            node = nodes[identity]
            definition_scope = scopes[identity]
            body_scope = owned_scopes.get(identity)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
                if body_scope is None:
                    raise AnalysisError("function has no owned lexical scope")
                name = (
                    node.name
                    if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                    else f"<lambda@{identity.start_line}:{identity.start_column}>"
                )
                function_id = FunctionId(identity.module, body_scope.qualified_label, identity)
                return_expressions: list[NodeId] = []
                if isinstance(node, ast.Lambda):
                    body = next(
                        edge.child
                        for edge in children.get(identity, ())
                        if edge.field_name == "body"
                    )
                    return_expressions.append(body)
                else:
                    for candidate in nodes_in_scope.get(body_scope, ()):
                        if not isinstance(nodes[candidate], ast.Return):
                            continue
                        value = next(
                            (
                                edge.child
                                for edge in children.get(candidate, ())
                                if edge.field_name == "value"
                            ),
                            None,
                        )
                        if value is not None:
                            return_expressions.append(value)
                return_roots = sorted(
                    {
                        root_name
                        for value in return_expressions
                        for root_name in _possible_root_names(nodes, children, value)
                    }
                )
                functions[function_id] = FunctionRecord(
                    function_id,
                    definition_scope,
                    body_scope,
                    tuple(sorted(return_expressions, key=_node_sort_key)),
                    tuple(return_roots),
                )
                if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    lookup_key = (definition_scope, name)
                    if lookup_key in function_lookup:
                        raise AnalysisError(f"function is redefined in one scope: {name}")
                    function_lookup[lookup_key] = function_id
            elif isinstance(node, ast.ClassDef):
                if body_scope is None:
                    raise AnalysisError("class has no owned lexical scope")
                class_id = ClassId(identity.module, body_scope.qualified_label, identity)
                classes[class_id] = ClassRecord(class_id, definition_scope, body_scope)

        binding_candidates: list[tuple[ScopeId, str, NodeId, NodeId | None, NodeId | None]] = []

        def child(identity: NodeId, name: str, ordinal: int | None = None) -> NodeId | None:
            for edge in children.get(identity, ()):
                if edge.field_name == name and (ordinal is None or edge.ordinal == ordinal):
                    return edge.child
            return None

        for identity in sorted(nodes, key=_node_sort_key):
            node = nodes[identity]
            scope = scopes[identity]
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)):
                binding_candidates.append((scope, node.name, identity, identity, None))
            elif isinstance(node, ast.Assign):
                value = child(identity, "value")
                for edge in children.get(identity, ()):
                    if edge.field_name != "targets":
                        continue
                    for name, target in _target_names(nodes, children, edge.child):
                        binding_candidates.append((scope, name, target, value, None))
            elif isinstance(node, ast.AnnAssign):
                target_identity = child(identity, "target")
                value = child(identity, "value")
                annotation = child(identity, "annotation")
                if target_identity is not None:
                    for name, target_node in _target_names(nodes, children, target_identity):
                        binding_candidates.append((scope, name, target_node, value, annotation))
            elif isinstance(node, ast.NamedExpr):
                target_identity = child(identity, "target")
                value = child(identity, "value")
                if target_identity is not None:
                    for name, target_node in _target_names(nodes, children, target_identity):
                        binding_candidates.append((scope, name, target_node, value, None))
            elif isinstance(node, ast.arg):
                annotation = child(identity, "annotation")
                binding_candidates.append((scope, node.arg, identity, None, annotation))
            elif isinstance(node, ast.Import):
                for ordinal, alias in enumerate(node.names):
                    name = alias.asname or alias.name.split(".", 1)[0]
                    binding_candidates.append((scope, name, identity, None, None))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        raise AnalysisError("wildcard import has no bounded binding universe")
                    binding_candidates.append(
                        (scope, alias.asname or alias.name, identity, None, None)
                    )

        binding_candidates.sort(
            key=lambda item: (
                item[0].canonical_bytes,
                _node_sort_key(item[2]),
                item[1],
            )
        )
        grouped_bindings: dict[tuple[ScopeId, str], list[BindingRecord]] = defaultdict(list)
        for scope, name, defining, value, annotation in binding_candidates:
            key = (scope, name)
            ordinal = len(grouped_bindings[key])
            grouped_bindings[key].append(
                BindingRecord(BindingId(scope, name, defining, ordinal), value, annotation)
            )
        bindings = {key: tuple(values) for key, values in grouped_bindings.items()}

        environments: dict[ScopeId, EnvironmentId] = {}
        for scope in scope_parents:
            visible: list[BindingId] = []
            current: ScopeId | None = scope
            shadowed: set[str] = set()
            while current is not None:
                local = [
                    (name, records[-1].identity)
                    for (candidate_scope, name), records in bindings.items()
                    if candidate_scope == current and records
                ]
                for name, binding in sorted(local, key=lambda item: item[0]):
                    if name not in shadowed:
                        visible.append(binding)
                        shadowed.add(name)
                current = scope_parents[current]
            environments[scope] = EnvironmentId(_sha256(tuple(visible)))

        return cls(
            modules=modules,
            module_roots=roots,
            nodes=nodes,
            children=children,
            markers=markers,
            parents=parents,
            scopes=scopes,
            owned_scopes=owned_scopes,
            scope_parents=scope_parents,
            nodes_in_scope=nodes_in_scope,
            bindings=bindings,
            functions=functions,
            function_lookup=function_lookup,
            classes=classes,
            environments=environments,
            statement_ordinals=statement_ordinals,
            fingerprints=fingerprints,
        )

    def child(self, identity: NodeId, field_name: str, ordinal: int | None = None) -> NodeId | None:
        for edge in self.children.get(identity, ()):
            if edge.field_name == field_name and (ordinal is None or edge.ordinal == ordinal):
                return edge.child
        return None

    def child_values(self, identity: NodeId, field_name: str) -> tuple[NodeId, ...]:
        return tuple(
            edge.child for edge in self.children.get(identity, ()) if edge.field_name == field_name
        )

    def root_name(self, identity: NodeId) -> str | None:
        return _root_name(self.nodes, self.children, identity)

    def binding_at(self, scope: ScopeId, name: str, use: NodeId) -> BindingRecord | None:
        origin = scope
        current: ScopeId | None = scope
        use_key = _node_sort_key(use)
        while current is not None:
            records = self.bindings.get((current, name), ())
            if records and current.lexical_kind == "module" and origin != current:
                return records[-1]
            eligible = [
                record
                for record in records
                if _node_sort_key(record.identity.defining_node) <= use_key
            ]
            if eligible:
                return eligible[-1]
            if (
                records
                and current == origin
                and current.lexical_kind
                in {
                    "comprehension",
                    "function",
                }
            ):
                return records[0]
            current = self.scope_parents[current]
        return None

    def resolve_function(self, scope: ScopeId, name: str) -> FunctionRecord | None:
        current: ScopeId | None = scope
        while current is not None:
            identity = self.function_lookup.get((current, name))
            if identity is not None:
                return self.functions[identity]
            current = self.scope_parents[current]
        return None

    def program_point(self, expression: NodeId) -> ProgramPointId:
        current: NodeId | None = expression
        while current is not None and current not in self.statement_ordinals:
            current = self.parents[current]
        ordinal = -1 if current is None else self.statement_ordinals.get(current, -1)
        return ProgramPointId(
            self.scopes[expression],
            ordinal,
            expression,
        )

    def assert_ast_immutable(self) -> None:
        for module_id, tree in self.modules.items():
            current = ast.dump(tree, annotate_fields=True, include_attributes=True)
            if current != self._fingerprints[module_id]:
                raise AnalysisError(f"analysis mutated AST input: {module_id.tracked_path}")

    def stable_projection(self) -> bytes:
        return _canonical_bytes(
            {
                "nodes": tuple(sorted(self.nodes, key=lambda item: item.canonical_bytes)),
                "scopes": tuple(
                    sorted(set(self.scopes.values()), key=lambda item: item.canonical_bytes)
                ),
                "bindings": tuple(
                    sorted(
                        (record.identity for values in self.bindings.values() for record in values),
                        key=_canonical_bytes,
                    )
                ),
                "functions": tuple(sorted(self.functions, key=_canonical_bytes)),
                "classes": tuple(sorted(self.classes, key=_canonical_bytes)),
                "environments": tuple(sorted(self.environments.values())),
            }
        )


ModuleIndex = ProgramIndex


class StableIndexer:
    """Small single-module facade for focused regression tests."""

    @staticmethod
    def index_module(module: str, path: str, source: str) -> ModuleIndex:
        return ProgramIndex.build((ModuleSource(module, path, source),))


class QueryKind(Enum):
    EXPRESSION_SHAPE = "expression_shape"
    CALL_RETURN_SHAPE = "call_return_shape"
    SCOPE_EFFECTS = "scope_effects"
    MANIFEST_SHAPE = "manifest_shape"


QuerySubject: TypeAlias = NodeId | FunctionId | ScopeId


@dataclass(frozen=True)
class QueryKey:
    kind: QueryKind
    subject: QuerySubject
    scope: ScopeId
    program_point: ProgramPointId | None
    environment: EnvironmentId
    invocation: InvocationContextId | None = None
    binding_plan: BindingPlanId | None = None
    requested_member: str = "shape"
    effect_roots: tuple[str, ...] = ()

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self)


class Phase(Enum):
    PENDING = "pending"
    IRRELEVANT = "irrelevant"
    KNOWN = "known"
    UNRESOLVED = "unresolved"


ProvenanceState = Phase


class Reason(Enum):
    CYCLE = "cycle"
    DYNAMIC_KEY = "dynamic_key"
    INCOMPLETE_TRANSFER = "incomplete_transfer"
    QUERY_BUDGET = "query_budget"
    UNKNOWN_CALL = "unknown_call"
    UNSUPPORTED_FORM = "unsupported_form"


ReasonCode = Reason


@dataclass(frozen=True, order=True)
class SemanticValue:
    kind: str
    identity: str


@dataclass(frozen=True)
class Approximation:
    phase: Phase = Phase.PENDING
    values: frozenset[SemanticValue] = frozenset()
    reasons: frozenset[Reason] = frozenset()


@dataclass(frozen=True)
class Proposal:
    phase: Phase
    values: frozenset[SemanticValue] = frozenset()
    reasons: frozenset[Reason] = frozenset()
    dependencies: frozenset[QueryKey] = frozenset()


Transfer = Proposal


@dataclass(frozen=True)
class Result:
    phase: Phase
    values: frozenset[SemanticValue]
    reasons: frozenset[Reason]

    def conservative(self, universe: Iterable[SemanticValue]) -> frozenset[SemanticValue]:
        values = set(self.values)
        if self.phase is Phase.UNRESOLVED:
            values.update(universe)
        return frozenset(values)


Provenance = Result


@dataclass(order=True)
class _WorkItem:
    sort_key: bytes
    key: QueryKey = field(compare=False)


_INERT_SCALAR_CALLS = frozenset(
    {
        "bool",
        "bytes",
        "float",
        "int",
        "len",
        "repr",
        "str",
    }
)
_MUTATING_METHODS = frozenset(
    {
        "__setitem__",
        "append",
        "extend",
        "insert",
        "setdefault",
        "update",
    }
)


class AnalysisSession:
    """Owns one finite query graph and solves it without resolver recursion."""

    def __init__(
        self,
        index: ProgramIndex,
        *,
        max_queries: int | None = None,
        transfers: Mapping[
            QueryKind,
            Callable[[AnalysisSession, QueryKey], Proposal],
        ]
        | None = None,
    ) -> None:
        self.index = index
        derived_limit = max(32, len(index.nodes) * len(QueryKind) * 4)
        self.max_queries = max_queries if max_queries is not None else derived_limit
        if self.max_queries < 1:
            raise AnalysisError("query budget must be positive")
        self._states: dict[QueryKey, Approximation] = {}
        self._dependencies: dict[QueryKey, set[QueryKey]] = defaultdict(set)
        self._reverse_dependencies: dict[QueryKey, set[QueryKey]] = defaultdict(set)
        self._work: list[_WorkItem] = []
        self._scheduled: set[QueryKey] = set()
        self._evaluating: set[QueryKey] = set()
        self._current_query: QueryKey | None = None
        self._captured_dependencies: set[QueryKey] = set()
        self._transfer_overrides = MappingProxyType(dict(transfers or {}))
        self._solved = False
        self._roots: tuple[QueryKey, ...] = ()
        effect_values = {
            SemanticValue("effect_target", f"{scope.module.import_name}:{name}")
            for (scope, name), records in index.bindings.items()
            if records and (name == "manifest" or name.endswith("_manifest"))
        }
        self.effect_universe = frozenset(effect_values)

    @property
    def query_count(self) -> int:
        return len(self._states)

    @property
    def active_count(self) -> int:
        return len(self._evaluating)

    @property
    def scheduled_count(self) -> int:
        return len(self._scheduled)

    @property
    def pending_count(self) -> int:
        return sum(state.phase is Phase.PENDING for state in self._states.values())

    @property
    def active_queries(self) -> tuple[QueryKey, ...]:
        return tuple(sorted(self._evaluating, key=lambda item: item.canonical_bytes))

    @property
    def worklist(self) -> tuple[QueryKey, ...]:
        return tuple(item.key for item in sorted(self._work))

    def depend(self, dependency: QueryKey) -> Approximation:
        """Declare one dependency from the currently executing transfer.

        The dependency is scheduled only after the transfer returns, which
        makes accidental resolver recursion impossible.
        """

        if self._current_query is None:
            raise AnalysisError("depend() is valid only inside a transfer")
        self._validate_key(dependency)
        self._captured_dependencies.add(dependency)
        return self._view(dependency)

    def _validate_key(self, key: QueryKey) -> None:
        if key.kind is QueryKind.EXPRESSION_SHAPE and not isinstance(key.subject, NodeId):
            raise AnalysisError("expression query requires NodeId subject")
        if key.kind in {
            QueryKind.CALL_RETURN_SHAPE,
            QueryKind.MANIFEST_SHAPE,
        } and not isinstance(key.subject, FunctionId):
            raise AnalysisError("call/manifest query requires FunctionId subject")
        if key.kind is QueryKind.SCOPE_EFFECTS and not isinstance(key.subject, ScopeId):
            raise AnalysisError("effect query requires ScopeId subject")
        if tuple(sorted(set(key.effect_roots))) != key.effect_roots:
            raise AnalysisError("effect roots must be unique and canonically sorted")

    def _enqueue(self, key: QueryKey) -> None:
        if key in self._scheduled:
            return
        self._scheduled.add(key)
        heapq.heappush(self._work, _WorkItem(key.canonical_bytes, key))

    def _register(self, key: QueryKey) -> bool:
        self._validate_key(key)
        if key in self._states:
            return True
        if len(self._states) >= self.max_queries:
            return False
        self._states[key] = Approximation()
        self._enqueue(key)
        return True

    def expression_query(self, identity: NodeId) -> QueryKey:
        scope = self.index.scopes[identity]
        return QueryKey(
            QueryKind.EXPRESSION_SHAPE,
            identity,
            scope,
            self.index.program_point(identity),
            self.index.environments[scope],
        )

    def manifest_query(self, module_name: str, function_name: str) -> QueryKey:
        candidates = [
            record
            for record in self.index.functions.values()
            if record.identity.module.import_name == module_name
            and record.identity.qualified_name.rsplit(".", 1)[-1] == function_name
        ]
        if len(candidates) != 1:
            raise AnalysisError(
                f"manifest root must resolve exactly once: {module_name}:{function_name}"
            )
        record = candidates[0]
        return QueryKey(
            QueryKind.MANIFEST_SHAPE,
            record.identity,
            record.body_scope,
            None,
            self.index.environments[record.body_scope],
            requested_member="manifest_shape",
        )

    def _effect_query(self, scope: ScopeId, roots: Iterable[str]) -> QueryKey:
        return QueryKey(
            QueryKind.SCOPE_EFFECTS,
            scope,
            scope,
            None,
            self.index.environments[scope],
            requested_member="effects",
            effect_roots=tuple(sorted(set(roots))),
        )

    def _call_query(self, call_site: NodeId, function: FunctionRecord) -> QueryKey:
        caller_scope = self.index.scopes[call_site]
        argument_ids = tuple(
            edge.child
            for edge in self.index.children.get(call_site, ())
            if edge.field_name in {"args", "keywords"}
        )
        plan = BindingPlanId(_sha256((function.identity, call_site, argument_ids)))
        invocation = InvocationContextId(caller_scope.qualified_label, call_site)
        return QueryKey(
            QueryKind.CALL_RETURN_SHAPE,
            function.identity,
            function.body_scope,
            self.index.program_point(call_site),
            self.index.environments[caller_scope],
            invocation=invocation,
            binding_plan=plan,
            requested_member="return_shape",
        )

    def _view(self, key: QueryKey) -> Approximation:
        return self._states.get(key, Approximation())

    def _combine(
        self,
        dependencies: Iterable[QueryKey],
        *,
        direct_values: Iterable[SemanticValue] = (),
        unresolved_reasons: Iterable[Reason] = (),
    ) -> Proposal:
        dependency_set = frozenset(dependencies)
        observed = [self._view(key) for key in dependency_set]
        values = set(direct_values)
        reasons = set(unresolved_reasons)
        for item in observed:
            values.update(item.values)
            reasons.update(item.reasons)
        if any(item.phase is Phase.PENDING for item in observed):
            return Proposal(
                Phase.PENDING,
                frozenset(values),
                frozenset(reasons),
                dependency_set,
            )
        if reasons or any(item.phase is Phase.UNRESOLVED for item in observed):
            return Proposal(
                Phase.UNRESOLVED,
                frozenset(values),
                frozenset(reasons),
                dependency_set,
            )
        if values or any(item.phase is Phase.KNOWN for item in observed):
            return Proposal(Phase.KNOWN, frozenset(values), frozenset(), dependency_set)
        return Proposal(Phase.IRRELEVANT, frozenset(), frozenset(), dependency_set)

    def _literal_string(self, identity: NodeId | None) -> str | None:
        if identity is None:
            return None
        node = self.index.nodes[identity]
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
            return node.value
        return None

    def _callee(self, call: NodeId) -> FunctionRecord | None:
        function_node = self.index.child(call, "func")
        if function_node is None:
            return None
        node = self.index.nodes[function_node]
        if isinstance(node, ast.Name):
            binding = self.index.binding_at(self.index.scopes[call], node.id, call)
            if binding is None or (
                binding.identity.scope == self.index.scopes[call]
                and _node_sort_key(binding.identity.defining_node) > _node_sort_key(call)
            ):
                return None
            return next(
                (
                    record
                    for record in self.index.functions.values()
                    if record.identity.defining_node == binding.identity.defining_node
                    and isinstance(
                        self.index.nodes[binding.identity.defining_node],
                        (ast.AsyncFunctionDef, ast.FunctionDef),
                    )
                ),
                None,
            )
        return None

    def _is_inert_scalar_call(self, call: NodeId) -> bool:
        function_node = self.index.child(call, "func")
        if function_node is None:
            return False
        node = self.index.nodes[function_node]
        return (
            isinstance(node, ast.Name)
            and node.id in _INERT_SCALAR_CALLS
            and self.index.binding_at(self.index.scopes[call], node.id, call) is None
        )

    def _unknown_call(self, identity: NodeId | None) -> bool:
        if identity is None or not isinstance(self.index.nodes[identity], ast.Call):
            return False
        return self._callee(identity) is None and not self._is_inert_scalar_call(identity)

    def _call_argument_expressions(self, call: NodeId) -> tuple[NodeId, ...]:
        result = list(self.index.child_values(call, "args"))
        for keyword in self.index.child_values(call, "keywords"):
            value = self.index.child(keyword, "value")
            if value is not None:
                result.append(value)
        return tuple(result)

    def _literal_mapping_member(
        self,
        identity: NodeId,
        selected: str,
        *,
        seen: frozenset[NodeId] = frozenset(),
    ) -> NodeId | None:
        if identity in seen:
            return None
        nested_seen = seen | {identity}
        node = self.index.nodes[identity]
        if isinstance(node, ast.Name):
            binding = self.index.binding_at(self.index.scopes[identity], node.id, identity)
            if binding is None or binding.value is None:
                return None
            return self._literal_mapping_member(binding.value, selected, seen=nested_seen)
        if not isinstance(node, ast.Dict):
            return None
        matches: list[NodeId] = []
        for ordinal in range(len(node.values)):
            key_node = self.index.child(identity, "keys", ordinal)
            value_node = self.index.child(identity, "values", ordinal)
            if (
                key_node is not None
                and value_node is not None
                and self._literal_string(key_node) == selected
            ):
                matches.append(value_node)
        return matches[0] if len(matches) == 1 else None

    def _transfer_expression(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, NodeId)
        identity = key.subject
        node = self.index.nodes[identity]
        if isinstance(node, ast.Constant):
            return Proposal(Phase.IRRELEVANT)
        if isinstance(node, ast.Name):
            binding = self.index.binding_at(key.scope, node.id, identity)
            if (
                binding is None
                or binding.value is None
                or (
                    binding.identity.scope == key.scope
                    and _node_sort_key(binding.identity.defining_node) > _node_sort_key(identity)
                )
            ):
                return Proposal(
                    Phase.UNRESOLVED,
                    reasons=frozenset({Reason.UNSUPPORTED_FORM}),
                )
            dependency = self.expression_query(binding.value)
            return self._combine((dependency,))
        if isinstance(node, ast.Dict):
            dependencies: list[QueryKey] = []
            values: set[SemanticValue] = {SemanticValue("structured", _sha256(identity))}
            reasons: set[Reason] = set()
            for ordinal in range(len(node.values)):
                key_node = self.index.child(identity, "keys", ordinal)
                value_node = self.index.child(identity, "values", ordinal)
                if key_node is None:
                    if value_node is not None:
                        dependencies.append(self.expression_query(value_node))
                    continue
                literal = self._literal_string(key_node)
                if literal is None:
                    reasons.add(Reason.DYNAMIC_KEY)
                    dependencies.append(self.expression_query(key_node))
                else:
                    values.add(
                        SemanticValue(
                            "mapping_key",
                            f"{identity.module.import_name}:{_sha256(identity)}:{literal}",
                        )
                    )
                if value_node is not None:
                    dependencies.append(self.expression_query(value_node))
            return self._combine(
                dependencies,
                direct_values=values,
                unresolved_reasons=reasons,
            )
        if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
            dependencies = [
                self.expression_query(child) for child in self.index.child_values(identity, "elts")
            ]
            return self._combine(
                dependencies,
                direct_values=(SemanticValue("structured", _sha256(identity)),),
            )
        if isinstance(node, ast.IfExp):
            dependencies = [
                self.expression_query(child)
                for field_name in ("body", "orelse")
                if (child := self.index.child(identity, field_name)) is not None
            ]
            return self._combine(dependencies)
        if isinstance(node, (ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare)):
            dependencies = [
                self.expression_query(edge.child)
                for edge in self.index.children.get(identity, ())
                if isinstance(self.index.nodes[edge.child], ast.expr)
            ]
            return self._combine(dependencies)
        if isinstance(node, ast.Call):
            function = self._callee(identity)
            if function is not None:
                return self._combine((self._call_query(identity, function),))
            if self._is_inert_scalar_call(identity):
                return Proposal(Phase.IRRELEVANT)
            dependencies = [
                self.expression_query(argument)
                for argument in self._call_argument_expressions(identity)
            ]
            return self._combine(
                dependencies,
                unresolved_reasons=(Reason.UNKNOWN_CALL,),
            )
        if isinstance(node, ast.Subscript):
            value = self.index.child(identity, "value")
            selected = self.index.child(identity, "slice")
            if value is None or selected is None:
                return Proposal(
                    Phase.UNRESOLVED,
                    reasons=frozenset({Reason.UNSUPPORTED_FORM}),
                )
            literal = self._literal_string(selected)
            if literal is None:
                return self._combine(
                    (self.expression_query(value), self.expression_query(selected)),
                    unresolved_reasons=(Reason.DYNAMIC_KEY,),
                )
            member = self._literal_mapping_member(value, literal)
            if member is None:
                return self._combine(
                    (self.expression_query(value),),
                    unresolved_reasons=(Reason.UNSUPPORTED_FORM,),
                )
            return self._combine((self.expression_query(member),))
        if isinstance(node, ast.Attribute):
            value = self.index.child(identity, "value")
            if value is None:
                return Proposal(
                    Phase.UNRESOLVED,
                    reasons=frozenset({Reason.UNSUPPORTED_FORM}),
                )
            return self._combine((self.expression_query(value),))
        if isinstance(node, (ast.JoinedStr, ast.Lambda)):
            return Proposal(Phase.IRRELEVANT)
        dependencies = [
            self.expression_query(edge.child)
            for edge in self.index.children.get(identity, ())
            if isinstance(self.index.nodes[edge.child], ast.expr)
        ]
        return self._combine(
            dependencies,
            unresolved_reasons=(Reason.UNSUPPORTED_FORM,),
        )

    def _transfer_call_return(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, FunctionId)
        function = self.index.functions[key.subject]
        if not function.returns:
            return Proposal(Phase.IRRELEVANT)
        dependencies = [self.expression_query(value) for value in function.returns]
        if function.return_root_names:
            dependencies.append(self._effect_query(function.body_scope, function.return_root_names))
        return self._combine(dependencies)

    def _subscript_parts(self, target: NodeId) -> tuple[NodeId | None, NodeId | None]:
        return self.index.child(target, "value"), self.index.child(target, "slice")

    def _transfer_effects(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, ScopeId)
        scope = key.subject
        roots = set(key.effect_roots)
        aliases = set(roots)
        unknown_results: set[str] = set()
        dependencies: list[QueryKey] = []
        values: set[SemanticValue] = set()
        reasons: set[Reason] = set()

        def target_value(name: str) -> SemanticValue:
            return SemanticValue("effect_target", f"{scope.module.import_name}:{name}")

        def relevant(name: str | None) -> bool:
            return name is not None and name in aliases

        def call_arguments(call: NodeId | None) -> tuple[NodeId, ...]:
            if call is None or not isinstance(self.index.nodes[call], ast.Call):
                return ()
            return self._call_argument_expressions(call)

        def relevant_arguments(call: NodeId | None) -> tuple[str, ...]:
            return tuple(
                sorted(
                    {
                        name
                        for argument in call_arguments(call)
                        for name in possible_roots(argument)
                        if relevant(name)
                    }
                )
            )

        def target_has_reflection(target: NodeId) -> bool:
            return any(
                isinstance(candidate, ast.Call)
                and isinstance(candidate.func, ast.Name)
                and candidate.func.id in _REFLECTIVE_CALLS
                for candidate in ast.walk(self.index.nodes[target])
            )

        def possible_roots(value: NodeId | None) -> frozenset[str]:
            if value is None:
                return frozenset()
            return _possible_root_names(self.index.nodes, self.index.children, value)

        for identity in self.index.nodes_in_scope.get(scope, ()):
            node = self.index.nodes[identity]
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                value = self.index.child(identity, "value")
                targets: list[NodeId] = []
                if isinstance(node, ast.Assign):
                    targets.extend(self.index.child_values(identity, "targets"))
                else:
                    target = self.index.child(identity, "target")
                    if target is not None:
                        targets.append(target)
                names = [
                    name
                    for target in targets
                    for name, _target in _target_names(
                        self.index.nodes, self.index.children, target
                    )
                ]
                if any(relevant(value_root) for value_root in possible_roots(value)):
                    aliases.update(names)
                if self._unknown_call(value):
                    unknown_results.update(names)
                    aliases.update(names)
                    argument_aliases = relevant_arguments(value)
                    if argument_aliases:
                        aliases.update(names)
                        for name in argument_aliases:
                            values.add(target_value(name))
                        reasons.add(Reason.UNKNOWN_CALL)
                    for name in names:
                        if name in roots:
                            values.add(target_value(name))
                            reasons.add(Reason.UNKNOWN_CALL)
                for target in targets:
                    target_node = self.index.nodes[target]
                    if not isinstance(target_node, ast.Subscript):
                        continue
                    receiver, selected = self._subscript_parts(target)
                    root_name = self.index.root_name(receiver) if receiver is not None else None
                    if not relevant(root_name):
                        if target_has_reflection(target):
                            reasons.update({Reason.UNKNOWN_CALL, Reason.DYNAMIC_KEY})
                            if value is not None:
                                dependencies.append(self.expression_query(value))
                        continue
                    assert root_name is not None
                    values.add(target_value(root_name))
                    if root_name in unknown_results:
                        reasons.add(Reason.UNKNOWN_CALL)
                    if self._literal_string(selected) is None:
                        reasons.add(Reason.DYNAMIC_KEY)
                    else:
                        values.add(
                            SemanticValue(
                                "mapping_key",
                                f"{scope.module.import_name}:{root_name}:{self._literal_string(selected)}",
                            )
                        )
                    if value is not None:
                        dependencies.append(self.expression_query(value))
                        if self._unknown_call(value):
                            reasons.add(Reason.UNKNOWN_CALL)
            elif isinstance(node, ast.Delete):
                for target in self.index.child_values(identity, "targets"):
                    receiver, _selected = self._subscript_parts(target)
                    root_name = self.index.root_name(receiver) if receiver is not None else None
                    if relevant(root_name):
                        assert root_name is not None
                        values.add(target_value(root_name))
                        reasons.add(Reason.UNSUPPORTED_FORM)
                    elif target_has_reflection(target):
                        reasons.add(Reason.UNKNOWN_CALL)
            elif isinstance(node, ast.AugAssign):
                target = self.index.child(identity, "target")
                root_name = self.index.root_name(target) if target is not None else None
                if relevant(root_name):
                    assert root_name is not None
                    values.add(target_value(root_name))
                    reasons.add(Reason.UNSUPPORTED_FORM)
            elif isinstance(node, ast.Call):
                function_node = self.index.child(identity, "func")
                if function_node is None:
                    continue
                function = self.index.nodes[function_node]
                arguments = self._call_argument_expressions(identity)
                if not isinstance(function, ast.Attribute):
                    if self._unknown_call(identity):
                        affected = relevant_arguments(identity)
                        reflective = isinstance(function, ast.Name) and (
                            function.id in _REFLECTIVE_CALLS
                        )
                        if affected or reflective:
                            for name in affected:
                                values.add(target_value(name))
                            reasons.add(Reason.UNKNOWN_CALL)
                            dependencies.extend(
                                self.expression_query(argument) for argument in arguments
                            )
                    continue
                receiver = self.index.child(function_node, "value")
                root_name = self.index.root_name(receiver) if receiver is not None else None
                if not relevant(root_name):
                    continue
                assert root_name is not None
                if function.attr in {"copy", "get", "items", "keys", "values"}:
                    continue
                values.add(target_value(root_name))
                if function.attr not in _MUTATING_METHODS:
                    reasons.add(Reason.UNSUPPORTED_FORM)
                    dependencies.extend(self.expression_query(argument) for argument in arguments)
                    continue
                if root_name in unknown_results:
                    reasons.add(Reason.UNKNOWN_CALL)
                if function.attr in {"__setitem__", "setdefault"}:
                    selected = arguments[0] if arguments else None
                    literal = self._literal_string(selected)
                    if literal is None:
                        reasons.add(Reason.DYNAMIC_KEY)
                    else:
                        values.add(
                            SemanticValue(
                                "mapping_key",
                                f"{scope.module.import_name}:{root_name}:{literal}",
                            )
                        )
                dependencies.extend(self.expression_query(argument) for argument in arguments)

        return self._combine(
            dependencies,
            direct_values=values,
            unresolved_reasons=reasons,
        )

    def _transfer_manifest(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, FunctionId)
        function = self.index.functions[key.subject]
        roots = function.return_root_names
        dependencies: list[QueryKey] = [self.expression_query(value) for value in function.returns]
        dependencies.append(self._effect_query(function.body_scope, roots))
        module_scope = self.index.scopes[self.index.module_roots[function.identity.module]]
        dependencies.append(self._effect_query(module_scope, roots))
        root_values = [
            SemanticValue(
                "manifest_root",
                f"{function.identity.module.import_name}:{name}",
            )
            for name in roots
        ]
        return self._combine(dependencies, direct_values=root_values)

    def _transfer(self, key: QueryKey) -> Proposal:
        override = self._transfer_overrides.get(key.kind)
        if override is not None:
            proposal = override(self, key)
            if not isinstance(proposal, Proposal):
                raise AnalysisError("custom transfer must return Proposal")
            return proposal
        if key.kind is QueryKind.EXPRESSION_SHAPE:
            return self._transfer_expression(key)
        if key.kind is QueryKind.CALL_RETURN_SHAPE:
            return self._transfer_call_return(key)
        if key.kind is QueryKind.SCOPE_EFFECTS:
            return self._transfer_effects(key)
        if key.kind is QueryKind.MANIFEST_SHAPE:
            return self._transfer_manifest(key)
        raise AnalysisError(f"unregistered query kind: {key.kind}")

    def _advance(self, previous: Approximation, proposal: Proposal) -> Approximation:
        values = previous.values | proposal.values
        reasons = previous.reasons | proposal.reasons
        if previous.phase is Phase.UNRESOLVED:
            return Approximation(Phase.UNRESOLVED, values, reasons)
        if proposal.phase is Phase.PENDING:
            if previous.phase is Phase.PENDING:
                return Approximation(Phase.PENDING, values, reasons)
            return Approximation(
                Phase.UNRESOLVED,
                values,
                reasons | {Reason.INCOMPLETE_TRANSFER},
            )
        if proposal.phase is Phase.UNRESOLVED:
            return Approximation(Phase.UNRESOLVED, values, reasons)
        if previous.phase is Phase.KNOWN or proposal.phase is Phase.KNOWN:
            return Approximation(Phase.KNOWN, values, reasons)
        return Approximation(Phase.IRRELEVANT, values, reasons)

    def _evaluate(self, key: QueryKey) -> None:
        if key in self._evaluating:
            raise AnalysisError("transfer attempted recursive evaluation")
        self._evaluating.add(key)
        self._current_query = key
        self._captured_dependencies.clear()
        try:
            proposal = self._transfer(key)
        finally:
            captured = frozenset(self._captured_dependencies)
            self._captured_dependencies.clear()
            self._current_query = None
            self._evaluating.remove(key)
        if captured:
            proposal = Proposal(
                proposal.phase,
                proposal.values,
                proposal.reasons,
                proposal.dependencies | captured,
            )

        accepted: set[QueryKey] = set()
        budget_exceeded = False
        for dependency in sorted(proposal.dependencies, key=lambda item: item.canonical_bytes):
            if self._register(dependency):
                accepted.add(dependency)
            else:
                budget_exceeded = True
        new_edges = accepted - self._dependencies[key]
        if new_edges:
            self._dependencies[key].update(new_edges)
            for dependency in new_edges:
                self._reverse_dependencies[dependency].add(key)
        if budget_exceeded:
            proposal = Proposal(
                Phase.UNRESOLVED,
                proposal.values,
                proposal.reasons | {Reason.QUERY_BUDGET},
                frozenset(accepted),
            )
        before = self._states[key]
        after = self._advance(before, proposal)
        if after != before or new_edges:
            self._states[key] = after
            for dependent in sorted(
                self._reverse_dependencies[key], key=lambda item: item.canonical_bytes
            ):
                self._enqueue(dependent)

    def _drain_worklist(self) -> None:
        while self._work:
            item = heapq.heappop(self._work)
            key = item.key
            self._scheduled.remove(key)
            self._evaluate(key)

    def _pending_components(self) -> tuple[tuple[QueryKey, ...], ...]:
        pending = sorted(
            (key for key, state in self._states.items() if state.phase is Phase.PENDING),
            key=lambda item: item.canonical_bytes,
        )
        pending_set = set(pending)
        adjacency = {
            key: tuple(
                sorted(
                    (item for item in self._dependencies[key] if item in pending_set),
                    key=lambda item: item.canonical_bytes,
                )
            )
            for key in pending
        }
        visited: set[QueryKey] = set()
        finish: list[QueryKey] = []
        for start in pending:
            if start in visited:
                continue
            visited.add(start)
            stack: list[tuple[QueryKey, int]] = [(start, 0)]
            while stack:
                current, offset = stack[-1]
                neighbours = adjacency[current]
                if offset < len(neighbours):
                    neighbour = neighbours[offset]
                    stack[-1] = (current, offset + 1)
                    if neighbour not in visited:
                        visited.add(neighbour)
                        stack.append((neighbour, 0))
                else:
                    finish.append(current)
                    stack.pop()

        reverse: dict[QueryKey, list[QueryKey]] = {key: [] for key in pending}
        for source, targets in adjacency.items():
            for target in targets:
                reverse[target].append(source)
        for values in reverse.values():
            values.sort(key=lambda item: item.canonical_bytes)

        assigned: set[QueryKey] = set()
        components: list[tuple[QueryKey, ...]] = []
        for start in reversed(finish):
            if start in assigned:
                continue
            assigned.add(start)
            component: list[QueryKey] = []
            component_stack = [start]
            while component_stack:
                current = component_stack.pop()
                component.append(current)
                for neighbour in reversed(reverse[current]):
                    if neighbour not in assigned:
                        assigned.add(neighbour)
                        component_stack.append(neighbour)
            components.append(tuple(sorted(component, key=lambda item: item.canonical_bytes)))
        return tuple(sorted(components, key=lambda values: values[0].canonical_bytes))

    def _finalize_one_sink_component(self) -> None:
        components = self._pending_components()
        if not components:
            return
        owner = {key: ordinal for ordinal, component in enumerate(components) for key in component}
        sinks = []
        for ordinal, component in enumerate(components):
            outgoing = {
                owner[target]
                for key in component
                for target in self._dependencies[key]
                if target in owner and owner[target] != ordinal
            }
            if not outgoing:
                sinks.append(component)
        if not sinks:
            raise AnalysisError("pending condensation graph has no sink")
        component = min(sinks, key=lambda values: values[0].canonical_bytes)
        cyclic = len(component) > 1 or any(key in self._dependencies[key] for key in component)
        reason = Reason.CYCLE if cyclic else Reason.INCOMPLETE_TRANSFER
        combined_values = frozenset(
            value for key in component for value in self._states[key].values
        )
        combined_reasons = frozenset(
            {reason} | {item for key in component for item in self._states[key].reasons}
        )
        for key in component:
            self._states[key] = Approximation(
                Phase.UNRESOLVED,
                combined_values,
                combined_reasons,
            )
            for dependent in self._reverse_dependencies[key]:
                self._enqueue(dependent)

    def solve(self, roots: Iterable[QueryKey]) -> Mapping[QueryKey, Result]:
        if self._solved:
            raise AnalysisError("one AnalysisSession may solve exactly one root batch")
        root_set = tuple(sorted(set(roots), key=lambda item: item.canonical_bytes))
        if not root_set:
            raise AnalysisError("analysis root batch is empty")
        self.index.assert_ast_immutable()
        for root in root_set:
            if not self._register(root):
                raise AnalysisError("root batch exceeds query budget")
        self._roots = root_set
        try:
            while True:
                self._drain_worklist()
                if not any(state.phase is Phase.PENDING for state in self._states.values()):
                    break
                self._finalize_one_sink_component()
            if self._work or self._scheduled or self._evaluating:
                raise AnalysisError("analysis session leaked active work")
            self._solved = True
            return MappingProxyType(
                {
                    root: Result(
                        self._states[root].phase,
                        self._states[root].values,
                        self._states[root].reasons,
                    )
                    for root in root_set
                }
            )
        finally:
            self.index.assert_ast_immutable()

    def result(self, key: QueryKey) -> Result:
        if not self._solved or key not in self._roots:
            raise AnalysisError("result is available only for a solved root")
        state = self._states[key]
        if state.phase is Phase.PENDING:
            raise AnalysisError("pending state escaped the analysis session")
        return Result(state.phase, state.values, state.reasons)


class _StagedEntryLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def data(self) -> bytes: ...


class _StagedSnapshotLike(Protocol):
    def parser_entry(self, path: str) -> _StagedEntryLike: ...


class _PythonModuleLike(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def module(self) -> str: ...

    @property
    def tree(self) -> ast.Module: ...


@dataclass(frozen=True)
class _ManifestRoot:
    path: str
    module: str
    function: str
    projection: Literal["return", "returned_assignment", "constructor", "dynamic_family"]
    selector: str = ""


_MANIFEST_ROOTS = (
    _ManifestRoot(
        "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py",
        "maniskill_pickcube.core",
        "_manifest",
        "return",
    ),
    _ManifestRoot(
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/fixture.py",
        "massrobotics_amr_adapter.fixture",
        "_manifest",
        "return",
    ),
    _ManifestRoot(
        "adapters/robomimic_lowdim/src/robomimic_lowdim/fixture.py",
        "robomimic_lowdim.fixture",
        "_manifest",
        "return",
    ),
    _ManifestRoot(
        "adapters/ros2_mcap/src/ros2_mcap_adapter/fixture.py",
        "ros2_mcap_adapter.fixture",
        "_manifest",
        "return",
    ),
    _ManifestRoot(
        "integrations/isaac/metriplane_to_usd.py",
        "integrations.isaac.metriplane_to_usd",
        "write_usda_replay",
        "returned_assignment",
        "manifest",
    ),
    _ManifestRoot(
        "metriplane/atlas/bundles.py",
        "metriplane.atlas.bundles",
        "export_bundle",
        "constructor",
        "BundleManifest",
    ),
    _ManifestRoot(
        "tools/release_artifacts.py",
        "tools.release_artifacts",
        "create_manifest",
        "dynamic_family",
        "digests",
    ),
)

_REFLECTIVE_CALLS = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "getattr",
        "globals",
        "locals",
        "setattr",
        "vars",
    }
)
_SAFE_SCALAR_CALLS = frozenset(
    {
        "bool",
        "bytes",
        "float",
        "hash",
        "int",
        "isinstance",
        "len",
        "max",
        "min",
        "repr",
        "round",
        "str",
        "sum",
    }
)
_SCALAR_PARAMETER_ANNOTATIONS = frozenset({"bool", "bytes", "float", "int", "str"})
_MAX_MANIFEST_CALLS = 256
_MAX_MANIFEST_STEPS = 50_000


class _Shape:
    pass


@dataclass
class _ScalarShape(_Shape):
    literal: object | None = None


@dataclass
class _UnknownShape(_Shape):
    origin: str


@dataclass
class _MappingShape(_Shape):
    entries: dict[str, _Shape]


@dataclass
class _ScalarValueMappingShape(_Shape):
    origin: str


@dataclass
class _SequenceShape(_Shape):
    items: list[_Shape]


@dataclass
class _TupleShape(_Shape):
    items: list[_Shape]


@dataclass
class _RecordShape(_Shape):
    fields: dict[str, _Shape]


@dataclass
class _ChoiceShape(_Shape):
    choices: list[_Shape]


@dataclass(frozen=True)
class _StaticModule:
    path: str
    module: str
    source_sha256: str
    tree: ast.Module
    functions: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef]
    imports: Mapping[str, tuple[str, str]]
    final_bindings: Mapping[str, ast.AST]


def _absolute_import(module: str, imported: str | None, level: int) -> str:
    if level == 0:
        return imported or ""
    package = module.rsplit(".", 1)[0] if "." in module else ""
    parts = package.split(".") if package else []
    remove = level - 1
    if remove > len(parts):
        raise AnalysisError(f"relative import escapes package: {module}")
    prefix = parts[: len(parts) - remove]
    if imported:
        prefix.extend(imported.split("."))
    return ".".join(prefix)


def _static_module(module: _PythonModuleLike, source_sha256: str) -> _StaticModule:
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    imports: dict[str, tuple[str, str]] = {}
    final_bindings: dict[str, ast.AST] = {}

    def names(target: ast.expr) -> tuple[str, ...]:
        pending = [target]
        result: list[str] = []
        while pending:
            current = pending.pop()
            if isinstance(current, ast.Name):
                result.append(current.id)
            elif isinstance(current, (ast.List, ast.Tuple)):
                pending.extend(reversed(current.elts))
        return tuple(result)

    for statement in module.tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name in functions:
                raise AnalysisError(
                    f"manifest module redefines function {statement.name}: {module.path}"
                )
            functions[statement.name] = statement
            final_bindings[statement.name] = statement
        elif isinstance(statement, ast.ClassDef):
            final_bindings[statement.name] = statement
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                for name in names(target):
                    final_bindings[name] = statement
        elif isinstance(statement, ast.AnnAssign):
            for name in names(statement.target):
                final_bindings[name] = statement
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                final_bindings[alias.asname or alias.name.split(".", 1)[0]] = statement
        elif isinstance(statement, ast.ImportFrom):
            target_module = _absolute_import(module.module, statement.module, statement.level)
            for alias in statement.names:
                if alias.name == "*":
                    raise AnalysisError(f"star import is not analyzable: {module.path}")
                local_name = alias.asname or alias.name
                imports[local_name] = (target_module, alias.name)
                final_bindings[local_name] = statement
    return _StaticModule(
        module.path,
        module.module,
        source_sha256,
        module.tree,
        MappingProxyType(functions),
        MappingProxyType(imports),
        MappingProxyType(final_bindings),
    )


def _literal(shape: _Shape) -> object | None:
    if isinstance(shape, _ScalarShape):
        return shape.literal
    return None


def _choices(shapes: Iterable[_Shape]) -> _Shape:
    flattened: list[_Shape] = []
    for shape in shapes:
        if isinstance(shape, _ChoiceShape):
            flattened.extend(shape.choices)
        else:
            flattened.append(shape)
    if not flattened:
        return _ScalarShape()
    if len(flattened) == 1:
        return flattened[0]
    return _ChoiceShape(flattened)


def _is_hashlib_sha256_call(module: _StaticModule, node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "sha256"
        and isinstance(node.func.value, ast.Name)
        and len(node.args) == 1
        and not node.keywords
    ):
        return False
    binding = module.final_bindings.get(node.func.value.id)
    if not isinstance(binding, ast.Import):
        return False
    return any(
        alias.name == "hashlib"
        and (alias.asname or alias.name.split(".", 1)[0]) == node.func.value.id
        for alias in binding.names
    )


def _is_hashlib_sha256_hexdigest_call(module: _StaticModule, node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "hexdigest"
        and not node.args
        and not node.keywords
        and isinstance(node.func.value, ast.Call)
        and _is_hashlib_sha256_call(module, node.func.value)
    )


class _LocalNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.globals: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)


def _function_local_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    collector = _LocalNameCollector()
    for statement in function.body:
        collector.visit(statement)
    parameters = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    if function.args.vararg is not None:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        parameters.add(function.args.kwarg.arg)
    return frozenset((collector.names | parameters) - collector.globals)


def _possibly_structured(value: _Shape) -> bool:
    pending = [value]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)
        if isinstance(current, (_MappingShape, _ScalarValueMappingShape, _SequenceShape)):
            return True
        if isinstance(current, _TupleShape):
            pending.extend(current.items)
        elif isinstance(current, _ChoiceShape):
            pending.extend(current.choices)
        elif isinstance(current, _RecordShape):
            pending.extend(current.fields.values())
    return False


class _ManifestInterpreter:
    """Bounded symbolic mapping-shape interpreter over staged AST values only."""

    def __init__(self, modules: Mapping[str, _StaticModule]) -> None:
        self.modules = modules
        self.steps = 0
        self.calls = 0
        self.stack: list[tuple[str, str]] = []
        self.local_bindings: list[frozenset[str]] = []

    def _step(self, node: ast.AST) -> None:
        self.steps += 1
        if self.steps > _MAX_MANIFEST_STEPS:
            raise AnalysisError(
                f"manifest projection step budget exceeded near line {getattr(node, 'lineno', 0)}"
            )

    @staticmethod
    def _module_binding_count(module: _StaticModule, name: str) -> int:
        class BindingCounter(ast.NodeVisitor):
            def __init__(self) -> None:
                self.count = 0

            def visit_Name(self, node: ast.Name) -> None:
                if node.id == name and isinstance(node.ctx, (ast.Del, ast.Store)):
                    self.count += 1

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node.name == name:
                    self.count += 1

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                if node.name == name:
                    self.count += 1

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                if node.name == name:
                    self.count += 1

            def visit_Lambda(self, node: ast.Lambda) -> None:
                return

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names:
                    if (alias.asname or alias.name.split(".", 1)[0]) == name:
                        self.count += 1

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                for alias in node.names:
                    if (alias.asname or alias.name) == name:
                        self.count += 1

        counter = BindingCounter()
        for statement in module.tree.body:
            counter.visit(statement)
        return counter.count

    @staticmethod
    def _module_attribute_write_count(module: _StaticModule, owner: str, attribute: str) -> int:
        return sum(
            1
            for node in ast.walk(module.tree)
            if isinstance(node, ast.Attribute)
            and node.attr == attribute
            and isinstance(node.ctx, (ast.Del, ast.Store))
            and isinstance(node.value, ast.Name)
            and node.value.id == owner
        )

    def _imported_scalar_binding(self, module: _StaticModule, name: str) -> _Shape | None:
        binding = module.final_bindings.get(name)
        imported = module.imports.get(name)
        if (
            not isinstance(binding, ast.ImportFrom)
            or imported is None
            or self._module_binding_count(module, name) != 1
        ):
            return None
        owner_name, declared_name = imported
        owner = self.modules.get(owner_name)
        if owner is None or self._module_binding_count(owner, declared_name) != 1:
            return None
        owner_binding = owner.final_bindings.get(declared_name)
        value: ast.expr | None = None
        if isinstance(owner_binding, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == declared_name
            for target in owner_binding.targets
        ):
            value = owner_binding.value
        elif (
            isinstance(owner_binding, ast.AnnAssign)
            and isinstance(owner_binding.target, ast.Name)
            and owner_binding.target.id == declared_name
        ):
            value = owner_binding.value
        return _ScalarShape(value.value) if isinstance(value, ast.Constant) else None

    def _function(self, module: _StaticModule, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
        function = module.functions.get(name)
        if function is None:
            raise AnalysisError(f"manifest root function is absent: {module.module}:{name}")
        return function

    def call_root(self, module: _StaticModule, name: str) -> _Shape:
        function = self._function(module, name)
        arguments = [
            self._parameter_shape(module, argument)
            for argument in (*function.args.posonlyargs, *function.args.args)
        ]
        keywords = {
            argument.arg: self._parameter_shape(module, argument)
            for argument in function.args.kwonlyargs
        }
        return self._call_function(module, function, arguments, keywords)

    def _parameter_shape(self, module: _StaticModule, argument: ast.arg) -> _Shape:
        if (
            isinstance(argument.annotation, ast.Subscript)
            and isinstance(argument.annotation.value, ast.Name)
            and argument.annotation.value.id == "Mapping"
            and module.imports.get("Mapping") == ("collections.abc", "Mapping")
            and isinstance(module.final_bindings.get("Mapping"), ast.ImportFrom)
            and self._module_binding_count(module, "Mapping") == 1
            and isinstance(argument.annotation.slice, ast.Tuple)
            and len(argument.annotation.slice.elts) == 2
            and all(isinstance(item, ast.Name) for item in argument.annotation.slice.elts)
            and cast(ast.Name, argument.annotation.slice.elts[0]).id == "str"
            and cast(ast.Name, argument.annotation.slice.elts[1]).id == "str"
        ):
            return _ScalarValueMappingShape(f"parameter:{argument.arg}")
        if not isinstance(argument.annotation, ast.Name):
            return _UnknownShape(f"parameter:{argument.arg}")
        type_name = argument.annotation.id
        if type_name in _SCALAR_PARAMETER_ANNOTATIONS and type_name not in module.final_bindings:
            return _ScalarShape()
        imported = module.imports.get(type_name)
        if imported is None or not isinstance(module.final_bindings.get(type_name), ast.ImportFrom):
            return _UnknownShape(f"parameter:{argument.arg}")
        owner_name, declared_name = imported
        owner = self.modules.get(owner_name)
        if owner is None:
            return _UnknownShape(f"parameter:{argument.arg}")
        declarations = [
            statement
            for statement in owner.tree.body
            if isinstance(statement, ast.ClassDef) and statement.name == declared_name
        ]
        if len(declarations) != 1:
            return _UnknownShape(f"parameter:{argument.arg}")
        if (
            owner.final_bindings.get(declared_name) is not declarations[0]
            or self._module_binding_count(owner, declared_name) != 1
        ):
            return _UnknownShape(f"parameter:{argument.arg}")
        annotated = self._dataclass_shape(owner, declarations[0], frozenset())
        constructors = [
            node
            for node in ast.walk(owner.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == declared_name
            and not node.args
            and all(keyword.arg is not None for keyword in node.keywords)
        ]
        if len(constructors) != 1:
            return annotated or _UnknownShape(f"parameter:{argument.arg}")
        fields = {}
        for keyword in constructors[0].keywords:
            key = cast(str, keyword.arg)
            value = self._eval(owner, {}, keyword.value)
            if (
                isinstance(value, _UnknownShape)
                and annotated is not None
                and key in annotated.fields
            ):
                value = annotated.fields[key]
            fields[key] = value
        if (
            owner.path == "adapters/ros2_mcap/src/ros2_mcap_adapter/decoder.py"
            and owner.module == "ros2_mcap_adapter.decoder"
            and owner.source_sha256
            == "aa86935989afc7a1d7343d5a07f212b14b9d00766d8482d4dd3a8b7e87a2455c"
            and declarations[0].name == "DecodedSource"
        ):
            fields["schema_inventory"] = _SequenceShape(
                [
                    _MappingShape(
                        {key: _ScalarShape() for key in ("encoding", "name", "schema_id", "sha256")}
                    )
                ]
            )
            fields["channel_inventory"] = _SequenceShape(
                [
                    _MappingShape(
                        {
                            key: _ScalarShape()
                            for key in (
                                "channel_id",
                                "message_encoding",
                                "schema_id",
                                "topic",
                            )
                        }
                    )
                ]
            )
        return _RecordShape(fields)

    def _dataclass_shape(
        self,
        module: _StaticModule,
        declaration: ast.ClassDef,
        seen: frozenset[tuple[str, str]],
    ) -> _RecordShape | None:
        identity = (module.module, declaration.name)
        if (
            identity in seen
            or module.imports.get("dataclass") != ("dataclasses", "dataclass")
            or not isinstance(module.final_bindings.get("dataclass"), ast.ImportFrom)
            or self._module_binding_count(module, "dataclass") != 1
        ):
            return None
        if not any(
            (isinstance(decorator, ast.Name) and decorator.id == "dataclass")
            or (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "dataclass"
            )
            for decorator in declaration.decorator_list
        ):
            return None
        fields: dict[str, _Shape] = {}
        for statement in declaration.body:
            if not (
                isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            ):
                continue
            fields[statement.target.id] = self._annotation_shape(
                module,
                statement.annotation,
                seen | {identity},
            )
        return _RecordShape(fields) if fields else None

    def _annotation_shape(
        self,
        module: _StaticModule,
        annotation: ast.expr,
        seen: frozenset[tuple[str, str]],
    ) -> _Shape:
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return _ScalarShape(None)
        if isinstance(annotation, ast.Name):
            if (
                annotation.id in _SCALAR_PARAMETER_ANNOTATIONS
                and annotation.id not in module.final_bindings
            ):
                return _ScalarShape()
            declarations = [
                statement
                for statement in module.tree.body
                if isinstance(statement, ast.ClassDef) and statement.name == annotation.id
            ]
            if len(declarations) == 1:
                return self._dataclass_shape(module, declarations[0], seen) or _UnknownShape(
                    f"annotation:{annotation.id}"
                )
            imported = module.imports.get(annotation.id)
            if imported is not None:
                owner = self.modules.get(imported[0])
                declarations = (
                    [
                        statement
                        for statement in owner.tree.body
                        if isinstance(statement, ast.ClassDef) and statement.name == imported[1]
                    ]
                    if owner is not None
                    else []
                )
                if owner is not None and len(declarations) == 1:
                    return self._dataclass_shape(owner, declarations[0], seen) or _UnknownShape(
                        f"annotation:{annotation.id}"
                    )
            return _UnknownShape(f"annotation:{annotation.id}")
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            left = self._annotation_shape(module, annotation.left, seen)
            right = self._annotation_shape(module, annotation.right, seen)
            if isinstance(left, _ScalarShape) and isinstance(right, _ScalarShape):
                return _ScalarShape()
            return _choices((left, right))
        return _UnknownShape(f"annotation:{ast.unparse(annotation)}")

    def _is_exact_maniskill_center(self, module: _StaticModule, node: ast.Subscript) -> bool:
        inner = node.value
        return (
            module.path == "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py"
            and module.module == "maniskill_pickcube.core"
            and module.source_sha256
            == "87920c6da5bd447b0367f26b7230120257bc7312e98bfac651399706af89e0f9"
            and bool(self.stack)
            and self.stack[-1] == (module.module, "_manifest")
            and isinstance(inner, ast.Subscript)
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "config"
            and isinstance(inner.slice, ast.Constant)
            and inner.slice.value == "target_polygon"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "center"
        )

    def returned_assignment(
        self,
        module: _StaticModule,
        function_name: str,
        variable: str,
    ) -> _Shape:
        function = self._function(module, function_name)
        returns_variable = any(
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Name)
            and statement.value.id == variable
            for statement in function.body
        )
        if not returns_variable:
            raise AnalysisError(
                f"manifest assignment is not returned: {module.module}:{function_name}:{variable}"
            )
        assignments = [
            statement
            for statement in function.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(name == variable for name in self._assignment_names(statement))
        ]
        if len(assignments) != 1:
            raise AnalysisError(
                f"returned manifest assignment must resolve once: {module.path}:{variable}"
            )
        assignment = assignments[0]
        value = assignment.value
        if value is None:
            raise AnalysisError(f"returned manifest assignment has no value: {module.path}")
        shape = self._eval(module, {}, value)
        if (
            module.path == "integrations/isaac/metriplane_to_usd.py"
            and module.module == "integrations.isaac.metriplane_to_usd"
            and module.source_sha256
            == "5a8fdaa4f64466df75a6d749a3d784069943092a82037c14a76d02aa7eb5e85e"
            and function_name == "write_usda_replay"
            and variable == "manifest"
        ):
            if not isinstance(shape, _MappingShape):
                raise AnalysisError("exact Isaac manifest did not produce a mapping shape")
            scalar_origins = {
                "fps": "name:fps",
                "run_id": "name:run_id",
                "scale": "name:scale",
            }
            for key, origin in scalar_origins.items():
                current = shape.entries.get(key)
                if not isinstance(current, _UnknownShape) or current.origin != origin:
                    raise AnalysisError(f"exact Isaac scalar proof disagrees at /{key}")
                shape.entries[key] = _ScalarShape()
            sequence_origins = {
                "incident_ids": "method:get",
                "object_ids": "attribute:object_id",
            }
            for key, origin in sequence_origins.items():
                current = shape.entries.get(key)
                if not (
                    isinstance(current, _SequenceShape)
                    and len(current.items) == 1
                    and isinstance(current.items[0], _UnknownShape)
                    and current.items[0].origin == origin
                ):
                    raise AnalysisError(f"exact Isaac sequence proof disagrees at /{key}/*")
                shape.entries[key] = _SequenceShape([_ScalarShape()])
        return shape

    def constructor_keys(
        self,
        module: _StaticModule,
        function_name: str,
        constructor: str,
    ) -> tuple[str, ...]:
        function = self._function(module, function_name)
        calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == constructor
        ]
        if len(calls) != 1:
            raise AnalysisError(
                f"manifest constructor must resolve once: {module.module}:{function_name}:{constructor}"
            )
        call = calls[0]
        if call.args or any(keyword.arg is None for keyword in call.keywords):
            raise AnalysisError(f"manifest constructor must use only named keys: {module.path}")
        keys = tuple(sorted(cast(str, keyword.arg) for keyword in call.keywords))
        if len(keys) != len(set(keys)):
            raise AnalysisError(f"manifest constructor repeats a key: {module.path}")
        return keys

    def dynamic_family(
        self,
        module: _StaticModule,
        function_name: str,
        variable: str,
    ) -> tuple[str, ...]:
        function = self._function(module, function_name)
        assignments = [
            statement
            for statement in function.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(name == variable for name in self._assignment_names(statement))
        ]
        if len(assignments) != 1:
            raise AnalysisError(
                f"bounded manifest family must resolve once: {module.path}:{variable}"
            )
        value = assignments[0].value
        if not isinstance(value, ast.DictComp) or len(value.generators) != 1:
            raise AnalysisError(
                f"bounded manifest family must be one dict comprehension: {module.path}"
            )
        generator = value.generators[0]
        if generator.is_async or generator.ifs:
            raise AnalysisError(f"bounded manifest family has dynamic control flow: {module.path}")
        if not (
            isinstance(generator.target, ast.Name)
            and isinstance(value.key, ast.Attribute)
            and isinstance(value.key.value, ast.Name)
            and value.key.value.id == generator.target.id
            and value.key.attr == "name"
        ):
            raise AnalysisError(f"bounded manifest family key is not artifact.name: {module.path}")
        if not (
            isinstance(generator.iter, ast.Call)
            and isinstance(generator.iter.func, ast.Name)
            and generator.iter.func.id == "sorted"
            and len(generator.iter.args) == 1
            and isinstance(generator.iter.args[0], (ast.List, ast.Tuple, ast.Set))
            and len(generator.iter.args[0].elts) > 0
        ):
            raise AnalysisError(f"bounded manifest family iterable is not finite: {module.path}")
        return ("*",)

    def _call_function(
        self,
        module: _StaticModule,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        positional: list[_Shape],
        keywords: Mapping[str, _Shape],
    ) -> _Shape:
        identity = (module.module, function.name)
        if identity in self.stack:
            chain = " -> ".join(f"{owner}:{name}" for owner, name in (*self.stack, identity))
            raise AnalysisError(f"recursive manifest projection is forbidden: {chain}")
        self.calls += 1
        if self.calls > _MAX_MANIFEST_CALLS:
            raise AnalysisError("manifest projection call budget exceeded")
        env: dict[str, _Shape] = {}
        parameters = [*function.args.posonlyargs, *function.args.args]
        for ordinal, argument in enumerate(parameters):
            env[argument.arg] = (
                positional[ordinal]
                if ordinal < len(positional)
                else keywords.get(argument.arg, _UnknownShape(f"parameter:{argument.arg}"))
            )
        for argument in function.args.kwonlyargs:
            env[argument.arg] = keywords.get(
                argument.arg,
                _UnknownShape(f"parameter:{argument.arg}"),
            )
        if function.args.vararg is not None:
            env[function.args.vararg.arg] = _SequenceShape(positional[len(parameters) :])
        if function.args.kwarg is not None:
            known = {argument.arg for argument in (*parameters, *function.args.kwonlyargs)}
            env[function.args.kwarg.arg] = _MappingShape(
                {key: value for key, value in keywords.items() if key not in known}
            )
        self.stack.append(identity)
        self.local_bindings.append(_function_local_names(function))
        try:
            for statement in function.body:
                returned = self._statement(module, env, statement)
                if returned is not None:
                    return returned
        finally:
            self.local_bindings.pop()
            popped = self.stack.pop()
            if popped != identity:
                raise AnalysisError("manifest interpreter call stack is corrupt")
        return _ScalarShape()

    @staticmethod
    def _assignment_names(statement: ast.Assign | ast.AnnAssign) -> tuple[str, ...]:
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        return tuple(target.id for target in targets if isinstance(target, ast.Name))

    def _statement(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        statement: ast.stmt,
    ) -> _Shape | None:
        self._step(statement)
        if isinstance(statement, ast.Assign):
            value = self._eval(module, env, statement.value)
            for target in statement.targets:
                self._bind(module, env, target, value)
            return None
        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                self._bind(module, env, statement.target, self._eval(module, env, statement.value))
            return None
        if isinstance(statement, ast.Expr):
            self._eval(module, env, statement.value)
            return None
        if isinstance(statement, ast.Return):
            return (
                _ScalarShape()
                if statement.value is None
                else self._eval(module, env, statement.value)
            )
        if isinstance(statement, (ast.Pass, ast.Assert)):
            return None
        if isinstance(statement, ast.If):
            return self._branch(module, env, statement.body, statement.orelse)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        raise AnalysisError(
            f"unsupported manifest statement {type(statement).__name__}:"
            f"{module.path}:{getattr(statement, 'lineno', 0)}"
        )

    def _branch(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        body: list[ast.stmt],
        orelse: list[ast.stmt],
    ) -> _Shape | None:
        if any(
            self._contains_structural_mutation(statement, env) for statement in (*body, *orelse)
        ):
            raise AnalysisError(
                f"conditional structural manifest mutation is ambiguous: {module.path}"
            )
        returned: list[_Shape] = []
        for branch in (body, orelse):
            local = dict(env)
            for statement in branch:
                result = self._statement(module, local, statement)
                if result is not None:
                    returned.append(result)
                    break
        return _choices(returned) if returned else None

    def _contains_structural_mutation(
        self,
        statement: ast.stmt,
        env: Mapping[str, _Shape],
    ) -> bool:
        for node in ast.walk(statement):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(target, ast.Subscript) for target in targets):
                    return True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and isinstance(env.get(node.func.value.id), (_MappingShape, _SequenceShape))
            ):
                return True
        return False

    def _bind(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        target: ast.expr,
        value: _Shape,
    ) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            items = value.items if isinstance(value, (_TupleShape, _SequenceShape)) else []
            if len(items) != len(target.elts):
                raise AnalysisError(
                    f"manifest destructuring is not statically exact:"
                    f"{module.path}:{getattr(target, 'lineno', 0)}"
                )
            for nested, item in zip(target.elts, items, strict=True):
                self._bind(module, env, nested, item)
            return
        if isinstance(target, ast.Subscript):
            receiver = self._eval(module, env, target.value)
            key = _literal(self._eval(module, env, target.slice))
            if not isinstance(receiver, _MappingShape):
                raise AnalysisError(
                    f"manifest subscript target is not a known mapping: {module.path}"
                )
            if not isinstance(key, str) or not key:
                raise AnalysisError(f"dynamic manifest mutation key is forbidden: {module.path}")
            receiver.entries[key] = value
            return
        raise AnalysisError(
            f"unsupported manifest assignment target {type(target).__name__}: {module.path}"
        )

    def _eval(self, module: _StaticModule, env: dict[str, _Shape], node: ast.AST) -> _Shape:
        self._step(node)
        if isinstance(node, ast.Constant):
            return _ScalarShape(node.value)
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if self.local_bindings and node.id in self.local_bindings[-1]:
                return _UnknownShape(f"name:{node.id}")
            return self._imported_scalar_binding(module, node.id) or _UnknownShape(
                f"name:{node.id}"
            )
        if isinstance(node, ast.Dict):
            result = _MappingShape({})
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                value = self._eval(module, env, value_node)
                if key_node is None:
                    sources = value.choices if isinstance(value, _ChoiceShape) else [value]
                    mappings = [item for item in sources if isinstance(item, _MappingShape)]
                    if len(mappings) != len(sources):
                        raise AnalysisError(
                            f"dynamic manifest mapping unpack is forbidden: {module.path}"
                        )
                    for source in mappings:
                        result.entries.update(source.entries)
                    continue
                key = _literal(self._eval(module, env, key_node))
                if not isinstance(key, str) or not key:
                    raise AnalysisError(f"dynamic manifest literal key is forbidden: {module.path}")
                if key in result.entries:
                    raise AnalysisError(f"duplicate manifest literal key {key!r}: {module.path}")
                result.entries[key] = value
            return result
        if isinstance(node, ast.List):
            return _SequenceShape([self._eval(module, env, item) for item in node.elts])
        if isinstance(node, (ast.Tuple, ast.Set)):
            return _TupleShape([self._eval(module, env, item) for item in node.elts])
        if isinstance(node, ast.IfExp):
            condition = self._condition(module, env, node.test)
            if condition is True:
                return self._eval(module, env, node.body)
            if condition is False:
                return self._eval(module, env, node.orelse)
            return _choices(
                (self._eval(module, env, node.body), self._eval(module, env, node.orelse))
            )
        if isinstance(node, ast.Subscript):
            if self._is_exact_maniskill_center(module, node):
                return _SequenceShape([_ScalarShape(), _ScalarShape()])
            receiver = self._eval(module, env, node.value)
            key = _literal(self._eval(module, env, node.slice))
            return self._subscript(module, receiver, key)
        if isinstance(node, ast.Attribute):
            receiver = self._eval(module, env, node.value)
            if isinstance(receiver, _RecordShape):
                return receiver.fields.get(node.attr, _UnknownShape(f"attribute:{node.attr}"))
            if isinstance(receiver, _MappingShape) and node.attr in receiver.entries:
                return receiver.entries[node.attr]
            return _UnknownShape(f"attribute:{node.attr}")
        if isinstance(node, ast.Call):
            return self._call(module, env, node)
        if isinstance(node, ast.ListComp):
            return _SequenceShape(self._comprehension(module, env, node.elt, node.generators))
        if isinstance(node, ast.GeneratorExp):
            return _SequenceShape(self._comprehension(module, env, node.elt, node.generators))
        if isinstance(node, ast.DictComp):
            entries: dict[str, _Shape] = {}
            for local in self._comprehension_envs(module, env, node.generators):
                key = _literal(self._eval(module, local, node.key))
                if not isinstance(key, str) or not key:
                    raise AnalysisError(
                        f"dynamic manifest comprehension key is forbidden: {module.path}"
                    )
                entries[key] = self._eval(module, local, node.value)
            return _MappingShape(entries)
        if isinstance(
            node,
            (
                ast.BinOp,
                ast.BoolOp,
                ast.Compare,
                ast.FormattedValue,
                ast.JoinedStr,
                ast.Lambda,
                ast.UnaryOp,
            ),
        ):
            return _ScalarShape()
        if isinstance(node, ast.Slice):
            return _ScalarShape()
        raise AnalysisError(
            f"unsupported manifest expression {type(node).__name__}:"
            f"{module.path}:{getattr(node, 'lineno', 0)}"
        )

    def _condition(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        node: ast.expr,
    ) -> bool | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Name)
        ):
            value = self._eval(module, env, node.args[0])
            expected = node.args[1].id
            if expected == "tuple":
                return isinstance(value, _TupleShape)
            if expected == "list":
                return isinstance(value, _SequenceShape)
            if expected == "dict":
                return isinstance(value, _MappingShape)
            if expected == "str" and isinstance(value, _ScalarShape):
                return isinstance(value.literal, str)
        return None

    def _subscript(self, module: _StaticModule, receiver: _Shape, key: object | None) -> _Shape:
        if isinstance(receiver, _ChoiceShape):
            return _choices(self._subscript(module, choice, key) for choice in receiver.choices)
        if isinstance(receiver, _MappingShape):
            if not isinstance(key, str):
                return _UnknownShape("dynamic-mapping-selection")
            return receiver.entries.get(key, _UnknownShape(f"missing-key:{key}"))
        if isinstance(receiver, _ScalarValueMappingShape):
            return (
                _ScalarShape()
                if isinstance(key, str)
                else _UnknownShape("dynamic-mapping-selection")
            )
        if isinstance(receiver, (_SequenceShape, _TupleShape)):
            if isinstance(key, int) and -len(receiver.items) <= key < len(receiver.items):
                return receiver.items[key]
            return _UnknownShape("dynamic-sequence-selection")
        return _UnknownShape("subscript")

    def _comprehension(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        element: ast.expr,
        generators: list[ast.comprehension],
    ) -> list[_Shape]:
        return [
            self._eval(module, local, element)
            for local in self._comprehension_envs(module, env, generators)
        ]

    def _comprehension_envs(
        self,
        module: _StaticModule,
        env: dict[str, _Shape],
        generators: list[ast.comprehension],
    ) -> list[dict[str, _Shape]]:
        environments = [dict(env)]
        for generator in generators:
            if generator.is_async:
                raise AnalysisError(f"async manifest comprehension is forbidden: {module.path}")
            expanded: list[dict[str, _Shape]] = []
            for current in environments:
                iterable = self._eval(module, current, generator.iter)
                items: list[_Shape]
                if isinstance(iterable, _UnknownShape):
                    items = [iterable]
                elif isinstance(iterable, (_SequenceShape, _TupleShape)):
                    items = iterable.items
                else:
                    raise AnalysisError(
                        f"unbounded manifest comprehension is forbidden: {module.path}"
                    )
                for item in items:
                    local = dict(current)
                    self._bind(module, local, generator.target, item)
                    expanded.append(local)
            environments = expanded
        return environments

    def _call(self, module: _StaticModule, env: dict[str, _Shape], node: ast.Call) -> _Shape:
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id in _REFLECTIVE_CALLS
        ):
            raise AnalysisError(
                f"reflective/callback manifest call is forbidden: {node.func.func.id}"
            )
        digest_call: ast.Call | None = None
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Call)
            and _is_hashlib_sha256_hexdigest_call(module, node)
        ):
            digest_call = node.func.value
        digest_owner = (
            digest_call.func.value
            if digest_call is not None and isinstance(digest_call.func, ast.Attribute)
            else None
        )
        if (
            digest_call is not None
            and isinstance(digest_owner, ast.Name)
            and not (self.local_bindings and digest_owner.id in self.local_bindings[-1])
            and self._module_binding_count(module, digest_owner.id) == 1
            and self._module_attribute_write_count(module, digest_owner.id, "sha256") == 0
        ):
            self._step(digest_call)
            self._eval(module, env, digest_call.args[0])
            return _ScalarShape()
        positional = [self._eval(module, env, argument) for argument in node.args]
        keywords: dict[str, _Shape] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                unpacked = self._eval(module, env, keyword.value)
                if not isinstance(unpacked, _MappingShape):
                    raise AnalysisError(
                        f"dynamic manifest call keywords are forbidden: {module.path}"
                    )
                keywords.update(unpacked.entries)
            else:
                keywords[keyword.arg] = self._eval(module, env, keyword.value)
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in _REFLECTIVE_CALLS or name in {"map", "filter"}:
                raise AnalysisError(f"reflective/callback manifest call is forbidden: {name}")
            local_shadow = bool(self.local_bindings and name in self.local_bindings[-1])
            binding = module.final_bindings.get(name)
            structured_arguments = any(
                _possibly_structured(value) for value in (*positional, *keywords.values())
            )
            if local_shadow:
                raise AnalysisError(f"local callback binding is unresolved: {name}")
            if name == "dict" and binding is None:
                return self._dict_call(module, positional, keywords)
            if name in {"list", "tuple", "set", "sorted"} and binding is None:
                return self._sequence_call(module, name, positional)
            if name in _SAFE_SCALAR_CALLS and binding is None:
                return _ScalarShape()
            function = (
                module.functions.get(name)
                if isinstance(binding, (ast.AsyncFunctionDef, ast.FunctionDef))
                else None
            )
            owner = module
            if function is None and isinstance(binding, ast.ImportFrom) and name in module.imports:
                target_module, target_name = module.imports[name]
                owner = self.modules.get(target_module)  # type: ignore[assignment]
                if owner is not None:
                    function = owner.functions.get(target_name)
            if function is not None:
                return self._call_function(owner, function, positional, keywords)
            if binding is not None:
                raise AnalysisError(f"shadowed callback binding is unresolved: {name}")
            if structured_arguments:
                raise AnalysisError(f"unknown callback may mutate manifest structure: {name}")
            return _UnknownShape(f"call:{name}")
        if isinstance(node.func, ast.Attribute):
            receiver = self._eval(module, env, node.func.value)
            return self._method_call(module, receiver, node.func.attr, positional, keywords)
        raise AnalysisError(f"dynamic manifest callable is forbidden: {module.path}")

    def _dict_call(
        self,
        module: _StaticModule,
        positional: list[_Shape],
        keywords: Mapping[str, _Shape],
    ) -> _Shape:
        if len(positional) > 1:
            raise AnalysisError(f"dict manifest call has too many arguments: {module.path}")
        result: dict[str, _Shape] = {}
        if positional:
            source = positional[0]
            if isinstance(source, _ChoiceShape):
                mappings = [
                    choice for choice in source.choices if isinstance(choice, _MappingShape)
                ]
                if len(mappings) != len(source.choices):
                    raise AnalysisError(f"dict manifest source is ambiguous: {module.path}")
                for mapping in mappings:
                    result.update(mapping.entries)
            elif isinstance(source, _MappingShape):
                result.update(source.entries)
            else:
                raise AnalysisError(f"dict manifest source is not a known mapping: {module.path}")
        result.update(keywords)
        return _MappingShape(result)

    def _sequence_call(
        self,
        module: _StaticModule,
        name: str,
        positional: list[_Shape],
    ) -> _Shape:
        if len(positional) > 1:
            raise AnalysisError(f"{name} manifest call has too many arguments: {module.path}")
        if not positional:
            return _SequenceShape([])
        source = positional[0]
        if isinstance(source, (_SequenceShape, _TupleShape)):
            return _SequenceShape(list(source.items))
        if isinstance(source, _ChoiceShape):
            choices = [self._sequence_call(module, name, [choice]) for choice in source.choices]
            return _choices(choices)
        if isinstance(source, _MappingShape):
            return _SequenceShape([_ScalarShape(key) for key in source.entries])
        if isinstance(source, _UnknownShape):
            if name == "sorted":
                return source
            return _SequenceShape([source])
        raise AnalysisError(f"{name} manifest source is not finite: {module.path}")

    def _method_call(
        self,
        module: _StaticModule,
        receiver: _Shape,
        method: str,
        positional: list[_Shape],
        keywords: Mapping[str, _Shape],
    ) -> _Shape:
        if isinstance(receiver, _ChoiceShape):
            return _choices(
                self._method_call(module, choice, method, positional, keywords)
                for choice in receiver.choices
            )
        if isinstance(receiver, _MappingShape):
            if method == "items" and not positional and not keywords:
                return _SequenceShape(
                    [
                        _TupleShape([_ScalarShape(key), value])
                        for key, value in receiver.entries.items()
                    ]
                )
            if method == "keys" and not positional and not keywords:
                return _SequenceShape([_ScalarShape(key) for key in receiver.entries])
            if method == "values" and not positional and not keywords:
                return _SequenceShape(list(receiver.entries.values()))
            if method == "copy" and not positional and not keywords:
                return _MappingShape(dict(receiver.entries))
            if method == "get" and 1 <= len(positional) <= 2 and not keywords:
                key = _literal(positional[0])
                if not isinstance(key, str):
                    return _UnknownShape("dynamic-get")
                default = positional[1] if len(positional) == 2 else _UnknownShape("missing-get")
                return receiver.entries.get(key, default)
            if method == "setdefault" and 1 <= len(positional) <= 2 and not keywords:
                key = _literal(positional[0])
                if not isinstance(key, str) or not key:
                    raise AnalysisError(
                        f"dynamic manifest setdefault key is forbidden: {module.path}"
                    )
                default = positional[1] if len(positional) == 2 else _ScalarShape()
                return receiver.entries.setdefault(key, default)
            if method == "update" and len(positional) <= 1:
                if positional:
                    source = positional[0]
                    if not isinstance(source, _MappingShape):
                        raise AnalysisError(f"dynamic manifest update is forbidden: {module.path}")
                    receiver.entries.update(source.entries)
                receiver.entries.update(keywords)
                return _ScalarShape()
            raise AnalysisError(f"unknown manifest mapping mutator/call {method!r}: {module.path}")
        if isinstance(receiver, _SequenceShape):
            if method == "append" and len(positional) == 1 and not keywords:
                receiver.items.append(positional[0])
                return _ScalarShape()
            if method == "extend" and len(positional) == 1 and not keywords:
                source = positional[0]
                if not isinstance(source, (_SequenceShape, _TupleShape)):
                    raise AnalysisError(f"dynamic manifest extend is forbidden: {module.path}")
                receiver.items.extend(source.items)
                return _ScalarShape()
            raise AnalysisError(f"unknown manifest sequence mutator/call {method!r}: {module.path}")
        if _possibly_structured(receiver) or any(
            _possibly_structured(value) for value in (*positional, *keywords.values())
        ):
            raise AnalysisError(
                f"unknown attribute callback may mutate manifest structure: {method}"
            )
        return _UnknownShape(f"method:{method}")


def _pointer_component(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _shape_pointers(shape: _Shape) -> tuple[str, ...]:
    pointers: set[str] = set()
    active: set[int] = set()

    def visit(value: _Shape, path: tuple[str, ...]) -> None:
        if isinstance(value, _ChoiceShape):
            for choice in value.choices:
                visit(choice, path)
            return
        if isinstance(value, _UnknownShape):
            if path:
                pointer = "/" + "/".join(_pointer_component(item) for item in path)
                raise AnalysisError(
                    f"manifest shape is unresolved beneath {pointer}: {value.origin}"
                )
            raise AnalysisError(f"manifest shape is unresolved at root: {value.origin}")
        if isinstance(value, _ScalarValueMappingShape):
            location = "/" + "/".join(_pointer_component(item) for item in path) if path else "root"
            raise AnalysisError(
                f"manifest shape is unresolved beneath {location}: {value.origin} keys"
            )
        if isinstance(value, (_MappingShape, _RecordShape)):
            identity = id(value)
            if identity in active:
                kind = "mapping" if isinstance(value, _MappingShape) else "record"
                raise AnalysisError(f"recursive manifest {kind} shape is forbidden")
            active.add(identity)
            try:
                entries = value.entries if isinstance(value, _MappingShape) else value.fields
                for key, child in sorted(entries.items()):
                    selected = (*path, key)
                    pointers.add("/" + "/".join(_pointer_component(item) for item in selected))
                    visit(child, selected)
            finally:
                active.remove(identity)
            return
        if isinstance(value, (_SequenceShape, _TupleShape)):
            identity = id(value)
            if identity in active:
                raise AnalysisError("recursive manifest sequence shape is forbidden")
            active.add(identity)
            try:
                selected = (*path, "*")
                for child in value.items:
                    visit(child, selected)
            finally:
                active.remove(identity)

    visit(shape, ())
    if not pointers:
        raise AnalysisError("manifest projection produced no keys")
    return tuple(sorted(pointers))


def _validated_modules(
    snapshot: _StagedSnapshotLike,
    modules: Sequence[_PythonModuleLike],
) -> Mapping[str, _StaticModule]:
    result: dict[str, _StaticModule] = {}
    paths: set[str] = set()
    for supplied in sorted(modules, key=lambda item: (item.module, item.path)):
        if supplied.module in result or supplied.path in paths:
            raise AnalysisError(
                f"duplicate staged Python module: {supplied.module}:{supplied.path}"
            )
        entry = snapshot.parser_entry(supplied.path)
        if entry.path != supplied.path:
            raise AnalysisError(f"staged parser entry path mismatch: {supplied.path}")
        try:
            source = entry.data.decode("utf-8")
            parsed = ast.parse(source, filename=supplied.path)
        except (UnicodeError, SyntaxError) as exc:
            raise AnalysisError(f"cannot parse exact staged source {supplied.path}: {exc}") from exc
        if ast.dump(parsed, include_attributes=True) != ast.dump(
            supplied.tree,
            include_attributes=True,
        ):
            raise AnalysisError(f"provided AST differs from exact staged source: {supplied.path}")
        indexed = _static_module(supplied, hashlib.sha256(entry.data).hexdigest())
        result[supplied.module] = indexed
        paths.add(supplied.path)
    return MappingProxyType(result)


def _observation_type(snapshot: object) -> type[Any]:
    owner = sys.modules.get(type(snapshot).__module__)
    observation = getattr(owner, "ManifestKeyObservation", None) if owner is not None else None
    if not isinstance(observation, type):
        raise AnalysisError(
            "scanner module does not expose ManifestKeyObservation beside StagedSnapshot"
        )
    fields = getattr(observation, "__dataclass_fields__", None)
    if not isinstance(fields, dict) or set(fields) != {"key", "source_path", "locator"}:
        raise AnalysisError("ManifestKeyObservation has an incompatible scanner contract")
    return observation


def discover_manifest_keys(
    snapshot: _StagedSnapshotLike,
    modules: Sequence[_PythonModuleLike],
) -> tuple[Any, ...]:
    """Project maintained production manifest keys from exact staged source ASTs.

    The scanner owns both input and observation classes.  Resolving the observation
    class beside the concrete snapshot type avoids importing a second scanner module
    when the scanner is executed as ``__main__``.
    """

    static_modules = _validated_modules(snapshot, modules)
    interpreter = _ManifestInterpreter(static_modules)
    projected: list[tuple[str, str, str]] = []
    for root in _MANIFEST_ROOTS:
        module = static_modules.get(root.module)
        if module is None or module.path != root.path:
            raise AnalysisError(f"maintained manifest module is absent: {root.path}")
        if root.projection == "return":
            keys = _shape_pointers(interpreter.call_root(module, root.function))
        elif root.projection == "returned_assignment":
            keys = _shape_pointers(
                interpreter.returned_assignment(module, root.function, root.selector)
            )
        elif root.projection == "constructor":
            keys = tuple(
                f"/{_pointer_component(key)}"
                for key in interpreter.constructor_keys(
                    module,
                    root.function,
                    root.selector,
                )
            )
        else:
            keys = tuple(
                f"/{_pointer_component(key)}"
                for key in interpreter.dynamic_family(
                    module,
                    root.function,
                    root.selector,
                )
            )
        projected.extend((key, root.path, f"{root.function}:{key}") for key in keys)
    projected.sort()
    if len(projected) != len(set(projected)):
        raise AnalysisError("manifest observation identities are not unique")
    observation = _observation_type(snapshot)
    return tuple(
        observation(key=key, source_path=source_path, locator=locator)
        for key, source_path, locator in projected
    )
