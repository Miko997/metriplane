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
from constants import IMPORTED_SCALAR

def build_manifest():
    manifest = {
        "known": {"nested": 1},
        "items": [{"name": "one"}],
        "imported": IMPORTED_SCALAR,
    }
    alias = manifest
    alias["added"] = {"child": 2}
    return manifest
""",
        extra_sources=(("src/constants.py", "constants", 'IMPORTED_SCALAR = "known"\n'),),
    )

    forward = provenance.discover_manifest_keys(snapshot, modules)
    reverse = provenance.discover_manifest_keys(snapshot, tuple(reversed(modules)))

    assert forward == reverse
    assert _keys(forward) == (
        "/added",
        "/added/child",
        "/imported",
        "/items",
        "/items/*/name",
        "/known",
        "/known/nested",
    )

    known_record = provenance._MappingShape(
        {"record": provenance._RecordShape({"field": provenance._ScalarShape()})}
    )
    assert provenance._shape_pointers(known_record) == ("/record", "/record/field")

    unresolved_record = provenance._MappingShape(
        {"record": provenance._RecordShape({"field": provenance._UnknownShape("record-field")})}
    )
    with pytest.raises(
        provenance.AnalysisError,
        match=r"manifest shape is unresolved beneath /record/field: record-field",
    ):
        provenance._shape_pointers(unresolved_record)

    scalar_snapshot, scalar_modules = _fixture(
        monkeypatch,
        """
def build_manifest(value: str):
    return {"value": value}
""",
    )
    assert _keys(provenance.discover_manifest_keys(scalar_snapshot, scalar_modules)) == ("/value",)

    fail_closed_fixtures = (
        (
            """
import hashlib

def build_manifest(hashlib):
    return {"sha256": hashlib.sha256(b"shadowed").hexdigest()}
""",
            (),
        ),
        (
            """
import hashlib
if runtime_flag:
    hashlib = shadowed

def build_manifest():
    return {"sha256": hashlib.sha256(b"rebound").hexdigest()}
""",
            (),
        ),
        (
            """
import hashlib
hashlib.sha256 = external_sha256

def build_manifest():
    return {"sha256": hashlib.sha256(b"rebound").hexdigest()}
""",
            (),
        ),
        (
            """
def build_manifest(value):
    return {"sha256": value.hexdigest()}
""",
            (),
        ),
        (
            """
from constants import IMPORTED_SCALAR

def build_manifest():
    return {"imported": IMPORTED_SCALAR}
""",
            (
                (
                    "src/constants.py",
                    "constants",
                    'IMPORTED_SCALAR = "known"\nif runtime_flag:\n    IMPORTED_SCALAR = {"hidden": 1}\n',
                ),
            ),
        ),
    )
    for fail_source, fail_extras in fail_closed_fixtures:
        fail_snapshot, fail_modules = _fixture(
            monkeypatch,
            fail_source,
            extra_sources=fail_extras,
        )
        with pytest.raises(provenance.AnalysisError, match="manifest shape is unresolved"):
            provenance.discover_manifest_keys(fail_snapshot, fail_modules)


def test_unmodified_hashlib_sha256_call_remains_a_known_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
import hashlib

def build_manifest():
    return {"sha256": hashlib.sha256(b"safe").hexdigest()}
""",
    )

    assert _keys(provenance.discover_manifest_keys(snapshot, modules)) == ("/sha256",)


def test_hashlib_sha256_setattr_replacement_with_structured_digest_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
import hashlib

class Digest:
    def hexdigest(self):
        return {'hidden': 1}

def external_sha256(_):
    return Digest()

setattr(hashlib, 'sha256', external_sha256)

def build_manifest():
    return {'digest': hashlib.sha256(b'x').hexdigest()}
""",
    )

    with pytest.raises(provenance.AnalysisError):
        provenance.discover_manifest_keys(snapshot, modules)


@pytest.mark.parametrize(
    "mutation",
    (
        pytest.param(
            "hashlib.sha256 = external_sha256",
            id="direct-assignment",
        ),
        pytest.param(
            'delattr(hashlib, "sha256")',
            id="builtin-delattr",
        ),
        pytest.param(
            "setattr(hashlib, runtime_attribute(), external_sha256)",
            id="dynamic-reflected-attribute",
        ),
        pytest.param(
            'mutate = setattr\nmutate(hashlib, "sha256", external_sha256)',
            id="builtin-setattr-alias",
        ),
        pytest.param(
            'import builtins\nbuiltins.setattr(hashlib, "sha256", external_sha256)',
            id="builtins-setattr",
        ),
        pytest.param(
            'import builtins\nbuiltins.delattr(hashlib, "sha256")',
            id="builtins-delattr",
        ),
        pytest.param(
            """def setattr(owner, name, value):
    return None

setattr(hashlib, "sha256", external_sha256)""",
            id="shadowed-setattr",
        ),
    ),
)
def test_hashlib_sha256_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        f"""
import hashlib

{mutation}

def build_manifest():
    return {{"sha256": hashlib.sha256(b"unsafe").hexdigest()}}
""",
    )

    with pytest.raises(provenance.AnalysisError):
        provenance.discover_manifest_keys(snapshot, modules)


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


@pytest.mark.parametrize(
    ("source", "location", "origin"),
    (
        (
            """
def build_manifest():
    manifest = {"known": 1}
    manifest["nested"] = external_value()
    return manifest
""",
            "/nested",
            "call:external_value",
        ),
        (
            """
def build_manifest():
    return external_value()
""",
            "root",
            "call:external_value",
        ),
        (
            """
def build_manifest():
    return {"outer": {"inner": external_value()}}
""",
            "/outer/inner",
            "call:external_value",
        ),
        (
            """
def build_manifest():
    return {"nested": [external_value()]}
""",
            "/nested/*",
            "call:external_value",
        ),
        (
            """
def build_manifest():
    return {"nested": external_value() if runtime_flag else {"known": 1}}
""",
            "/nested",
            "call:external_value",
        ),
    ),
)
def test_unknown_manifest_shapes_fail_closed_at_every_depth(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    location: str,
    origin: str,
) -> None:
    snapshot, modules = _fixture(monkeypatch, source)

    with pytest.raises(provenance.AnalysisError) as captured:
        provenance.discover_manifest_keys(snapshot, modules)

    assert "manifest shape is unresolved" in str(captured.value)
    assert location in str(captured.value)
    assert origin in str(captured.value)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            """
def build_manifest():
    return {"known": 1}
""",
            ("/known",),
        ),
        (
            """
def build_manifest():
    return {"outer": {"inner": 1}}
""",
            ("/outer", "/outer/inner"),
        ),
        (
            """
import hashlib

def build_manifest():
    return {
        "count": len((1, 2)),
        "sha256": hashlib.sha256(b"safe").hexdigest(),
    }
""",
            ("/count", "/sha256"),
        ),
    ),
)
def test_known_manifest_shapes_still_project_completely(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected: tuple[str, ...],
) -> None:
    snapshot, modules = _fixture(monkeypatch, source)

    assert _keys(provenance.discover_manifest_keys(snapshot, modules)) == expected


@pytest.mark.parametrize(
    "unrelated_statement",
    (
        pytest.param("", id="unchanged-imported-dataclass"),
        pytest.param(
            """@dataclass
class Unrelated:
    ignored: str

Unrelated = dict""",
            id="unrelated-rebind",
        ),
    ),
)
def test_imported_dataclass_with_exact_final_classdefs_passes(
    monkeypatch: pytest.MonkeyPatch,
    unrelated_statement: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
from models import Parent

def build_manifest(payload: Parent):
    return {"payload": payload.child}
""",
        extra_sources=(
            (
                "src/models.py",
                "models",
                f"""
from dataclasses import dataclass

@dataclass
class Child:
    field: str

{unrelated_statement}

@dataclass
class Parent:
    child: Child
""",
            ),
        ),
    )

    assert _keys(provenance.discover_manifest_keys(snapshot, modules)) == (
        "/payload",
        "/payload/field",
    )


@pytest.mark.parametrize(
    "child_rebinding",
    (
        pytest.param("Child = dict", id="assignment"),
        pytest.param("Child: object = dict", id="annotated-assignment"),
        pytest.param("from replacements import Child", id="import"),
        pytest.param(
            "if runtime_flag:\n    Child = dict",
            id="conditional-ambiguity",
        ),
        pytest.param("del Child", id="deletion"),
    ),
)
def test_imported_dataclass_child_rebinding_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    child_rebinding: str,
) -> None:
    snapshot, modules = _fixture(
        monkeypatch,
        """
from models import Parent

def build_manifest(payload: Parent):
    return {"payload": payload.child}
""",
        extra_sources=(
            (
                "src/models.py",
                "models",
                f"""
from dataclasses import dataclass

@dataclass
class Child:
    field: str

{child_rebinding}

@dataclass
class Parent:
    child: Child
""",
            ),
        ),
    )

    with pytest.raises(provenance.AnalysisError):
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
        "adapters/maniskill_pickcube/src/maniskill_pickcube/constants.py",
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/constants.py",
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/models.py",
        "adapters/massrobotics_amr/src/massrobotics_amr_adapter/reporting.py",
        "adapters/robomimic_lowdim/src/robomimic_lowdim/constants.py",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/canonical.py",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/constants.py",
        "adapters/ros2_mcap/src/ros2_mcap_adapter/decoder.py",
        "metriplane/atlas/models.py",
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
