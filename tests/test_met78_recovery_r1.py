# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Retained executable P0/P1 regressions for MET-78 Recovery R1."""

from __future__ import annotations

from dataclasses import dataclass

from tools.public_surface_provenance import (
    AnalysisSession,
    Phase,
    Reason,
    Result,
    StableIndexer,
)


@dataclass(frozen=True)
class _Case:
    name: str
    source: str
    phase: Phase
    required_reasons: frozenset[Reason] = frozenset()
    required_keys: frozenset[str] = frozenset()
    forbidden_keys: frozenset[str] = frozenset()
    exact_keys: frozenset[str] | None = None
    expect_no_reasons: bool = False
    budget: int | None = None
    max_queries: int | None = None


def _manifest_result(
    source: str,
    *,
    budget: int | None = None,
) -> tuple[AnalysisSession, Result]:
    index = StableIndexer.index_module("fixture", "src/fixture.py", source)
    session = AnalysisSession(index, max_queries=budget)
    root = session.manifest_query("fixture", "build_manifest")
    return session, session.solve((root,))[root]


def _mapping_keys(result: Result) -> frozenset[str]:
    return frozenset(
        value.identity.rsplit(":", 1)[-1] for value in result.values if value.kind == "mapping_key"
    )


def _case_violations(case: _Case) -> tuple[str, ...]:
    try:
        session, result = _manifest_result(case.source, budget=case.budget)
    except Exception as error:  # pragma: no cover - retained diagnostic boundary
        return (f"{case.name}: raised {type(error).__name__}: {error}",)

    keys = _mapping_keys(result)
    violations: list[str] = []
    if result.phase is not case.phase:
        violations.append(f"{case.name}: phase={result.phase.value}, expected={case.phase.value}")
    missing_reasons = case.required_reasons - result.reasons
    if missing_reasons:
        violations.append(
            f"{case.name}: missing reasons "
            f"{sorted(reason.value for reason in missing_reasons)!r}; "
            f"actual={sorted(reason.value for reason in result.reasons)!r}"
        )
    if case.expect_no_reasons and result.reasons:
        violations.append(
            f"{case.name}: expected no reasons; "
            f"actual={sorted(reason.value for reason in result.reasons)!r}"
        )
    missing_keys = case.required_keys - keys
    if missing_keys:
        violations.append(
            f"{case.name}: missing mapping keys {sorted(missing_keys)!r}; actual={sorted(keys)!r}"
        )
    forbidden_keys = case.forbidden_keys & keys
    if forbidden_keys:
        violations.append(
            f"{case.name}: impossible mapping keys retained {sorted(forbidden_keys)!r}; "
            f"actual={sorted(keys)!r}"
        )
    if case.exact_keys is not None and keys != case.exact_keys:
        violations.append(
            f"{case.name}: mapping keys={sorted(keys)!r}, expected={sorted(case.exact_keys)!r}"
        )
    if case.max_queries is not None and session.query_count > case.max_queries:
        violations.append(f"{case.name}: query_count={session.query_count}, max={case.max_queries}")

    leaked = {
        "active": session.active_count,
        "pending": session.pending_count,
        "scheduled": session.scheduled_count,
        "active_queries": len(session.active_queries),
        "worklist": len(session.worklist),
    }
    if any(leaked.values()):
        violations.append(f"{case.name}: analysis work leaked {leaked!r}")
    return tuple(violations)


_CASES = (
    _Case(
        "recursive branching is bounded and quiescent",
        """
def branch(flag):
    if flag:
        return branch(flag)
    return branch(flag) if runtime_flag else {"known": 1}

def build_manifest():
    return branch(runtime_flag)
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.CYCLE}),
        required_keys=frozenset({"known"}),
        max_queries=40,
    ),
    _Case(
        "unknown value assigned into a structured result taints it",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest["nested"] = external_value()
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known", "nested"}),
    ),
    _Case(
        "assigned unknown alias of a structured value taints it",
        """
def build_manifest():
    manifest = {"known": 1}
    alias = external_alias(manifest)
    alias["possible"] = {"child": 1}
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "dynamic subscript assignment fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest[runtime_key()] = {"hidden": 1}
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
    _Case(
        "dynamic __setitem__ fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest.__setitem__(runtime_key(), {"hidden": 1})
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
    _Case(
        "dynamic setdefault fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest.setdefault(runtime_key(), {"hidden": 1})
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
    _Case(
        "dynamic update fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest.update({runtime_key(): {"hidden": 1}})
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
    _Case(
        "branch assignment preserves a may-alias",
        """
manifest = {"known": 1}
if runtime_flag:
    alias = manifest
else:
    alias = {}
alias[runtime_key()] = {"hidden": 1}

def build_manifest():
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
    _Case(
        "live assignment shadows an earlier function",
        """
def helper():
    return {"stale": 1}

helper = external_callback

def build_manifest():
    return helper()
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        forbidden_keys=frozenset({"stale"}),
    ),
    _Case(
        "live function definition shadows an earlier assignment",
        """
helper = external_callback

def helper():
    return {"live": 1}

def build_manifest():
    return helper()
""",
        Phase.KNOWN,
        exact_keys=frozenset({"live"}),
        expect_no_reasons=True,
    ),
    _Case(
        "late module assignment shadows a helper used by an earlier definition",
        """
def helper():
    return {"stale": 1}

def build_manifest():
    return helper()

helper = external_callback
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        forbidden_keys=frozenset({"stale"}),
    ),
    _Case(
        "late module binding shadows an inert builtin in an earlier definition",
        """
def build_manifest():
    return {"known": 1, "count": len((1, 2))}

len = external_callback
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known", "count"}),
    ),
    _Case(
        "future local binding blocks fallback to an outer helper",
        """
def helper():
    return {"stale": 1}

def build_manifest():
    result = helper()
    helper = external_callback
    return result
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        forbidden_keys=frozenset({"stale"}),
    ),
    _Case(
        "live binding shadows an inert builtin name",
        """
len = external_callback

def build_manifest():
    return {"known": 1, "count": len((1, 2))}
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known", "count"}),
    ),
    _Case(
        "literal subscript selects exactly one structured member",
        """
def build_manifest():
    return {
        "selected": {"kept": 1},
        "ignored": {"excluded": 2},
    }["selected"]
""",
        Phase.KNOWN,
        exact_keys=frozenset({"kept"}),
        expect_no_reasons=True,
    ),
    _Case(
        "dynamic subscript selection fails closed",
        """
def build_manifest(selector):
    return {
        "selected": {"kept": 1},
        "ignored": {"excluded": 2},
    }[selector]
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
    ),
    _Case(
        "clear fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest.clear()
    return manifest
""",
        Phase.UNRESOLVED,
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "pop fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest.pop("known")
    return manifest
""",
        Phase.UNRESOLVED,
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "del fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    del manifest["known"]
    return manifest
""",
        Phase.UNRESOLVED,
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "mapping union assignment fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest |= {"merged": 2}
    return manifest
""",
        Phase.UNRESOLVED,
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback receiving a structured value fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback(manifest)
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback receiving a tuple-wrapped structured value fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback((manifest,))
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback receiving a mapping-wrapped structured value fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback({"payload": manifest})
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback receiving a conditional structured value fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback(manifest if runtime_flag else 0)
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback receiving a deeply wrapped keyword value fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback(payload=({"nested": (manifest if runtime_flag else 0,)},))
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unknown callback follows structured alias wrappers",
        """
def build_manifest():
    manifest = {"known": 1}
    inner = (manifest,)
    outer = {"payload": inner}
    external_callback(outer)
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "known helper return includes its literal scope effects",
        """
def helper():
    payload = {"known": 1}
    payload["added"] = {"child": 2}
    return payload

def build_manifest():
    return helper()
""",
        Phase.KNOWN,
        exact_keys=frozenset({"added", "child", "known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "known helper return includes its unknown callback scope effects",
        """
def helper():
    payload = {"known": 1}
    external_callback(payload)
    return payload

def build_manifest():
    return helper()
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "recursive helper with a named return root remains bounded",
        """
def helper():
    payload = {"known": 1}
    if runtime_flag:
        return helper()
    return payload

def build_manifest():
    return helper()
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.CYCLE}),
        required_keys=frozenset({"known"}),
        max_queries=40,
    ),
    _Case(
        "conditional test-only use does not expose the manifest to an unknown callback",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback(1 if manifest else 0)
    return manifest
""",
        Phase.KNOWN,
        exact_keys=frozenset({"known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "nested structured value observed by an inert scalar call remains known",
        """
def build_manifest():
    manifest = {"known": 1}
    len((manifest,))
    return manifest
""",
        Phase.KNOWN,
        exact_keys=frozenset({"known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "unknown callback receiving only scalars does not taint the manifest",
        """
def build_manifest():
    manifest = {"known": 1}
    external_callback((1, 2, 3))
    return manifest
""",
        Phase.KNOWN,
        exact_keys=frozenset({"known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "dynamic getattr callback fails closed",
        """
def build_manifest():
    manifest = {"known": 1}
    getattr(manifest, runtime_method())()
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.UNKNOWN_CALL}),
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "globals reflection mutation fails closed",
        """
manifest = {"known": 1}

def build_manifest():
    globals()["manifest"][runtime_key()] = {"hidden": 1}
    return manifest
""",
        Phase.UNRESOLVED,
        required_keys=frozenset({"known"}),
    ),
    _Case(
        "unshadowed maintained scalar calls remain inert",
        """
def build_manifest():
    return {
        "bool": bool(1),
        "bytes": bytes(1),
        "float": float(1),
        "int": int(1),
        "len": len((1,)),
        "repr": repr(1),
        "str": str(1),
        "joined": f"value={1}",
        "deferred": lambda: external_callback(),
    }
""",
        Phase.KNOWN,
        exact_keys=frozenset(
            {
                "bool",
                "bytes",
                "deferred",
                "float",
                "int",
                "joined",
                "len",
                "repr",
                "str",
            }
        ),
        expect_no_reasons=True,
    ),
    _Case(
        "unshadowed inert observer remains known",
        """
def build_manifest():
    manifest = {"known": 1}
    len(manifest)
    return manifest
""",
        Phase.KNOWN,
        exact_keys=frozenset({"known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "ordinary literal write remains exactly known",
        """
def build_manifest():
    manifest = {"known": 1}
    manifest["added"] = {"child": 2}
    return manifest
""",
        Phase.KNOWN,
        exact_keys=frozenset({"added", "child", "known"}),
        expect_no_reasons=True,
    ),
    _Case(
        "conditional expression assignment preserves a may-alias",
        """
def build_manifest():
    manifest = {"known": 1}
    alias = manifest if runtime_flag else {}
    alias[runtime_key()] = {"hidden": 1}
    return manifest
""",
        Phase.UNRESOLVED,
        required_reasons=frozenset({Reason.DYNAMIC_KEY}),
        required_keys=frozenset({"known", "hidden"}),
    ),
)


def test_met78_recovery_r1_historical_p0_p1_regressions() -> None:
    failures = [violation for case in _CASES for violation in _case_violations(case)]

    assert not failures, "MET-78 Recovery R1 regression failures:\n" + "\n".join(failures)
