# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools import public_surface_provenance as provenance

ROOT = Path(__file__).parents[1]


@dataclass(frozen=True)
class StagedEntry:
    path: str
    mode: str
    oid: str
    data: bytes


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


class StagedSnapshot:
    def __init__(self, entries: dict[str, StagedEntry]) -> None:
        self.entries = entries

    def parser_entry(self, path: str) -> StagedEntry:
        return self.entries[path]


def _fixture(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    *,
    extra_sources: tuple[tuple[str, str, str], ...] = (),
) -> tuple[StagedSnapshot, tuple[PythonModule, ...]]:
    path = "src/fixture.py"
    encoded = source.encode("utf-8")
    entries = {
        path: StagedEntry(path, "100644", "0" * 40, encoded),
    }
    modules = [PythonModule(path, "fixture", ast.parse(encoded, filename=path))]
    for extra_path, module_name, extra_source in extra_sources:
        extra_bytes = extra_source.encode("utf-8")
        entries[extra_path] = StagedEntry(extra_path, "100644", "1" * 40, extra_bytes)
        modules.append(
            PythonModule(
                extra_path,
                module_name,
                ast.parse(extra_bytes, filename=extra_path),
            )
        )
    monkeypatch.setattr(
        provenance,
        "_MANIFEST_ROOTS",
        (
            provenance._ManifestRoot(
                path,
                "fixture",
                "build_manifest",
                "return",
            ),
        ),
    )
    return StagedSnapshot(entries), tuple(modules)


def _keys(observations: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(item.key for item in observations if isinstance(item, ManifestKeyObservation))


def test_exact_alias_shape_passes_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
def build_manifest():
    manifest = {"known": {"nested": 1}, "items": [{"name": "one"}]}
    alias = manifest
    alias["added"] = {"child": 2}
    return manifest
""",
        extra_sources=(("src/unused.py", "unused", "value = 1\n"),),
    )

    forward = provenance.discover_manifest_keys(snapshot, modules)
    reverse = provenance.discover_manifest_keys(snapshot, tuple(reversed(modules)))

    assert forward == reverse
    assert _keys(forward) == (
        "/added",
        "/added/child",
        "/items",
        "/items/*/name",
        "/known",
        "/known/nested",
    )


def test_hook_rejects_ast_that_differs_from_exact_staged_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        'def build_manifest():\n    return {"staged": 1}\n',
    )
    divergent = PythonModule(
        modules[0].path,
        modules[0].module,
        ast.parse('def build_manifest():\n    return {"different": 1}\n'),
    )

    with pytest.raises(provenance.AnalysisError, match="differs from exact staged source"):
        provenance.discover_manifest_keys(snapshot, (divergent,))


@pytest.mark.parametrize(
    "mutation",
    (
        'alias[runtime_key()] = {"hidden": 1}',
        'alias.update({runtime_key(): {"hidden": 1}})',
        'alias.unknown_mutator("hidden", {"child": 1})',
    ),
)
def test_dynamic_or_unknown_manifest_mutators_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        f"""
def build_manifest():
    manifest = {{"known": 1}}
    alias = manifest
    {mutation}
    return manifest
""",
    )

    with pytest.raises(provenance.AnalysisError, match="dynamic manifest|unknown manifest"):
        provenance.discover_manifest_keys(snapshot, modules)


@pytest.mark.parametrize(
    "callback",
    (
        "external_callback(alias)",
        'getattr(alias, "update")({"hidden": 1})',
    ),
)
def test_callback_and_reflection_over_manifest_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    callback: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        f"""
def build_manifest():
    manifest = {{"known": 1}}
    alias = manifest
    {callback}
    return manifest
""",
    )

    with pytest.raises(provenance.AnalysisError, match="callback|reflective"):
        provenance.discover_manifest_keys(snapshot, modules)


def test_recursive_manifest_projection_fails_within_fixed_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
def recursive(value):
    return recursive(value)

def build_manifest():
    return recursive({"known": 1})
""",
    )

    with pytest.raises(provenance.AnalysisError, match="recursive manifest projection"):
        provenance.discover_manifest_keys(snapshot, modules)


@pytest.mark.parametrize(
    "source",
    (
        """
def helper():
    return {"stale": 1}

def build_manifest():
    return helper()

helper = external_callback
""",
        """
def build_manifest():
    return {"known": 1, "count": len((1, 2))}

len = external_callback
""",
        """
def helper():
    return {"stale": 1}

def build_manifest():
    result = helper()
    helper = external_callback
    return result
""",
    ),
)
def test_late_or_future_binding_shadow_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    snapshot, modules = _fixture(monkeypatch, source)

    with pytest.raises(provenance.AnalysisError, match="callback binding"):
        provenance.discover_manifest_keys(snapshot, modules)


@pytest.mark.parametrize(
    "callback",
    (
        "external_callback(payload=manifest)",
        "external_callback(((manifest,),))",
        "external_callback(manifest if runtime_flag else 0)",
        "(manifest,).unknown_method()",
    ),
)
def test_recursively_nested_structured_callback_values_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    callback: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        f"""
def build_manifest():
    manifest = {{"known": 1}}
    {callback}
    return manifest
""",
    )

    with pytest.raises(provenance.AnalysisError, match="callback"):
        provenance.discover_manifest_keys(snapshot, modules)


def _module_name(path: str) -> str:
    relative = path.split("/src/", 1)[-1]
    if relative.endswith("/__init__.py"):
        relative = relative[: -len("/__init__.py")]
    elif relative.endswith(".py"):
        relative = relative[:-3]
    return relative.replace("/", ".")


def _json_pointers(value: object, path: tuple[str, ...] = ()) -> set[str]:
    pointers: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            selected = (*path, key)
            escaped = (part.replace("~", "~0").replace("/", "~1") for part in selected)
            pointers.add("/" + "/".join(escaped))
            pointers.update(_json_pointers(item, selected))
    elif isinstance(value, list):
        for item in value:
            pointers.update(_json_pointers(item, (*path, "*")))
    return pointers


def test_production_hook_has_exact_retained_manifest_projection() -> None:
    source_paths = {root.path for root in provenance._MANIFEST_ROOTS} | {
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/reporting.py",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/canonical.py",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/decoder.py",
    }
    entries: dict[str, StagedEntry] = {}
    modules: list[PythonModule] = []
    for path in sorted(source_paths):
        data = (ROOT / path).read_bytes()
        entries[path] = StagedEntry(path, "100644", "0" * 40, data)
        modules.append(PythonModule(path, _module_name(path), ast.parse(data, filename=path)))
    observations = provenance.discover_manifest_keys(StagedSnapshot(entries), tuple(modules))

    expected_counts = {
        "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py": 262,
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/fixture.py": 269,
        "adapters/robomimic_lowdim/src/robomimic_lowdim/fixture.py": 274,
        "adapters/ros2_mcap/src/ros2_mcap_adapter/fixture.py": 267,
        "integrations/isaac/metriplane_to_usd.py": 9,
        "metriplane/atlas/bundles.py": 5,
        "tools/release_artifacts.py": 1,
    }
    assert len(observations) == 1_087
    assert {
        path: sum(item.source_path == path for item in observations) for path in expected_counts
    } == expected_counts

    references = {
        "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py": "maniskill_pickcube",
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/fixture.py": ("massrobotics_amr"),
        "adapters/robomimic_lowdim/src/robomimic_lowdim/fixture.py": "robomimic_lowdim",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/fixture.py": "ros2_mcap",
    }
    for source_path, family in references.items():
        document = json.loads(
            (
                ROOT / "examples" / "external_sources" / family / "control" / "source-manifest.json"
            ).read_text(encoding="utf-8")
        )
        assert {
            item.key for item in observations if item.source_path == source_path
        } == _json_pointers(document)
