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
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, TypeAlias


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
                        if (root_name := _root_name(nodes, children, value)) is not None
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
        current: ScopeId | None = scope
        use_key = _node_sort_key(use)
        while current is not None:
            records = self.bindings.get((current, name), ())
            eligible = [
                record
                for record in records
                if _node_sort_key(record.identity.defining_node) <= use_key
            ]
            if eligible:
                return eligible[-1]
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
            return self.index.resolve_function(self.index.scopes[call], node.id)
        return None

    def _is_inert_scalar_call(self, call: NodeId) -> bool:
        function_node = self.index.child(call, "func")
        if function_node is None:
            return False
        node = self.index.nodes[function_node]
        return isinstance(node, ast.Name) and node.id in _INERT_SCALAR_CALLS

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

    def _transfer_expression(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, NodeId)
        identity = key.subject
        node = self.index.nodes[identity]
        if isinstance(node, ast.Constant):
            return Proposal(Phase.IRRELEVANT)
        if isinstance(node, ast.Name):
            binding = self.index.binding_at(key.scope, node.id, identity)
            if binding is None or binding.value is None:
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
            if value is None:
                return Proposal(
                    Phase.UNRESOLVED,
                    reasons=frozenset({Reason.UNSUPPORTED_FORM}),
                )
            return self._combine((self.expression_query(value),))
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
        return self._combine(self.expression_query(value) for value in function.returns)

    def _subscript_parts(self, target: NodeId) -> tuple[NodeId | None, NodeId | None]:
        return self.index.child(target, "value"), self.index.child(target, "slice")

    def _transfer_effects(self, key: QueryKey) -> Proposal:
        assert isinstance(key.subject, ScopeId)
        scope = key.subject
        roots = set(key.effect_roots)
        unknown_results: set[str] = set()
        dependencies: list[QueryKey] = []
        values: set[SemanticValue] = set()
        reasons: set[Reason] = set()

        def target_value(name: str) -> SemanticValue:
            return SemanticValue("effect_target", f"{scope.module.import_name}:{name}")

        def relevant(name: str | None) -> bool:
            return name is not None and (name in roots or name in unknown_results)

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
                if self._unknown_call(value):
                    unknown_results.update(names)
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
                        continue
                    assert root_name is not None
                    values.add(target_value(root_name))
                    if self._literal_string(selected) is None:
                        reasons.add(Reason.DYNAMIC_KEY)
                        if root_name in unknown_results:
                            reasons.add(Reason.UNKNOWN_CALL)
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
            elif isinstance(node, ast.Call):
                function_node = self.index.child(identity, "func")
                if function_node is None:
                    continue
                function = self.index.nodes[function_node]
                if (
                    not isinstance(function, ast.Attribute)
                    or function.attr not in _MUTATING_METHODS
                ):
                    continue
                receiver = self.index.child(function_node, "value")
                root_name = self.index.root_name(receiver) if receiver is not None else None
                if not relevant(root_name):
                    continue
                assert root_name is not None
                values.add(target_value(root_name))
                arguments = self._call_argument_expressions(identity)
                if function.attr in {"__setitem__", "setdefault"}:
                    selected = arguments[0] if arguments else None
                    if self._literal_string(selected) is None:
                        reasons.add(Reason.DYNAMIC_KEY)
                        if root_name in unknown_results:
                            reasons.add(Reason.UNKNOWN_CALL)
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
