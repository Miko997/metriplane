# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools.public_surface_provenance import (
    AnalysisError,
    AnalysisSession,
    Approximation,
    ModuleSource,
    Phase,
    ProgramIndex,
    Proposal,
    QueryKind,
    Reason,
    SemanticValue,
    StableIndexer,
)


def _index(source: str) -> ProgramIndex:
    return StableIndexer.index_module("fixture", "src/fixture.py", source)


def _manifest_result(
    source: str,
    *,
    budget: int | None = None,
):
    index = _index(source)
    session = AnalysisSession(index, max_queries=budget)
    root = session.manifest_query("fixture", "build_manifest")
    result = session.solve((root,))[root]
    return index, session, result


def _value_identities(result) -> set[str]:
    return {value.identity for value in result.values}


def test_stable_index_covers_structural_nodes_without_mutating_ast() -> None:
    source = """
import pathlib as paths

def build_manifest(flag: int, *items: str, **options: object):
    with open("example") as handle:
        selected = [item for item in items if item]
        match flag:
            case {"key": value}:
                return {"known": helper(value=value)}
    return {"known": selected}
"""
    first = _index(source)
    second = ProgramIndex.build((ModuleSource("fixture", "src/fixture.py", source),))

    assert first.stable_projection() == second.stable_projection()
    assert tuple(item.semantic_id for item in first.occurrences) == tuple(
        item.semantic_id for item in second.occurrences
    )
    assert all(item.semantic_id.path == item.path for item in first.occurrences)
    assert all(not isinstance(item.node, ast.expr_context) for item in first.occurrences)
    assert all(not isinstance(item.node, ast.operator) for item in first.occurrences)
    assert any(edge.marker_kind == "Load" for edges in first.markers.values() for edge in edges)

    kinds = {item.semantic_id.node_kind for item in first.occurrences}
    assert {
        "alias",
        "arg",
        "arguments",
        "comprehension",
        "keyword",
        "match_case",
        "withitem",
    } <= kinds

    occurrence = next(item for item in first.occurrences if item.path)
    assert (
        first.semantic_id(
            occurrence.path,
            module_name="fixture",
        )
        == occurrence.semantic_id
    )
    first.assert_ast_immutable()
    with pytest.raises(TypeError):
        first.nodes[occurrence.semantic_id] = ast.Constant(value="mutation")

    implementation = (
        Path(__file__).parents[1] / "tools" / "public_surface_provenance.py"
    ).read_text(encoding="utf-8")
    assert "id(node)" not in implementation
    assert "setattr(" not in implementation
    assert "deepcopy" not in implementation
    assert "copy.copy" not in implementation


def test_nonrecursive_worklist_finalizes_recursive_branch_as_unresolved() -> None:
    source = """
def choose(flag):
    return {"known": 1} if flag else choose(flag)

def build_manifest():
    return choose(runtime_flag)
"""
    _index_value, session, result = _manifest_result(source)

    assert result.phase is Phase.UNRESOLVED
    assert Reason.CYCLE in result.reasons
    assert any(identity.endswith(":known") for identity in _value_identities(result))
    assert session.query_count < 40
    assert session.pending_count == 0
    assert session.active_count == 0
    assert session.scheduled_count == 0
    assert session.active_queries == ()
    assert session.worklist == ()


def test_query_budget_fails_closed_without_unbounded_branching() -> None:
    source = """
def recurse():
    return recurse()

def build_manifest():
    return recurse()
"""
    _index_value, session, result = _manifest_result(source, budget=2)

    assert result.phase is Phase.UNRESOLVED
    assert Reason.QUERY_BUDGET in result.reasons
    assert session.query_count == 2
    assert session.pending_count == 0
    assert session.worklist == ()


def test_assigned_unknown_call_taints_structured_manifest_value() -> None:
    source = """
def build_manifest():
    payload = {"known": 1}
    payload["nested"] = external_value()
    return payload
"""
    _index_value, _session, result = _manifest_result(source)

    assert result.phase is Phase.UNRESOLVED
    assert Reason.UNKNOWN_CALL in result.reasons
    identities = _value_identities(result)
    assert any(identity.endswith(":known") for identity in identities)
    assert any(identity.endswith(":nested") for identity in identities)


@pytest.mark.parametrize(
    "imports, alias_call, key_call",
    [
        (
            "from external import alias_of_manifest, runtime_key",
            "alias_of_manifest()",
            "runtime_key()",
        ),
        (
            "import external",
            "external.alias_of_manifest()",
            "external.runtime_key()",
        ),
    ],
)
def test_dynamic_key_mutation_of_unknown_alias_fails_closed(
    imports: str,
    alias_call: str,
    key_call: str,
) -> None:
    source = f"""
{imports}

manifest = {{"known": 1}}
alias = {alias_call}
alias[{key_call}] = {{"hidden": {{"child": 1}}}}

def build_manifest():
    return manifest
"""
    _index_value, session, result = _manifest_result(source)

    assert result.phase is Phase.UNRESOLVED
    assert {Reason.UNKNOWN_CALL, Reason.DYNAMIC_KEY} <= result.reasons
    assert any(identity.endswith(":known") for identity in _value_identities(result))
    assert session.effect_universe <= result.conservative(session.effect_universe)


def test_custom_transfer_scc_is_deterministic_and_has_no_pending_escape() -> None:
    index = _index("left = 1\nright = 2\n")
    names = {
        node.id: identity
        for identity, node in index.nodes.items()
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }

    def solve(root_order: tuple[str, str]):
        session: AnalysisSession
        keys = {}

        def transfer(active: AnalysisSession, key):
            assert isinstance(
                active.depend(keys["right" if key == keys["left"] else "left"]),
                Approximation,
            )
            label = "left" if key == keys["left"] else "right"
            return Proposal(
                Phase.PENDING,
                values=frozenset({SemanticValue("fixture", label)}),
            )

        session = AnalysisSession(
            index,
            max_queries=8,
            transfers={QueryKind.EXPRESSION_SHAPE: transfer},
        )
        keys = {name: session.expression_query(identity) for name, identity in names.items()}
        roots = tuple(keys[name] for name in root_order)
        results = session.solve(roots)
        return session, {
            name: (
                results[key].phase,
                results[key].values,
                results[key].reasons,
            )
            for name, key in keys.items()
        }

    first_session, first = solve(("left", "right"))
    second_session, second = solve(("right", "left"))

    assert first == second
    assert all(value[0] is Phase.UNRESOLVED for value in first.values())
    assert all(Reason.CYCLE in value[2] for value in first.values())
    assert all(
        value[1]
        == frozenset(
            {
                SemanticValue("fixture", "left"),
                SemanticValue("fixture", "right"),
            }
        )
        for value in first.values()
    )
    assert first_session.pending_count == second_session.pending_count == 0
    assert first_session.worklist == second_session.worklist == ()


def test_session_solves_exactly_one_root_batch() -> None:
    index = _index('def build_manifest():\n    return {"known": 1}\n')
    session = AnalysisSession(index)
    root = session.manifest_query("fixture", "build_manifest")
    session.solve((root,))

    with pytest.raises(AnalysisError, match="exactly one root batch"):
        session.solve((root,))
