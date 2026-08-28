# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNER_PATH = ROOT / "tools" / "discover_public_surface.py"
INVENTORY_PATH = ROOT / "docs" / "status" / "functional-inventory.json"
PROFILES_PATH = ROOT / "docs" / "status" / "support-profiles.json"
DOCS_PATH = ROOT / "docs" / "status" / "public-surface-inventory.md"

EXPECTED_FAMILY_COUNTS = {
    "configs": 167,
    "current_claims": 309,
    "examples": 172,
    "jobs": 55,
    "manifest_keys": 3580,
    "model_fields": 1389,
    "models": 229,
    "proofs": 322,
    "public_api": 2286,
    "resources": 1548,
    "workflows": 16,
}
EXPECTED_SOURCE_COUNTS = {
    "generated_targets_excluded": 3,
    "manifest_json_documents": 14,
    "manifest_python_modules": 290,
    "packaged_python_modules": 203,
    "tracked_paths": 1551,
    "tracked_python_paths": 445,
    "workflow_documents": 16,
}
EXPECTED_CONFIG_PARSERS = {
    "UTF-8 text": 5,
    "checksum-pinned retained-invalid": 2,
    "safe tracked-symlink": 3,
    "static Python AST": 5,
    "strict CSV": 1,
    "strict JSON": 4,
    "strict TOML": 22,
    "strict YAML": 125,
}


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("metriplane_public_surface_scanner", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner = _load_scanner()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _owned_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in document["rows"] if str(row["id"]).startswith(scanner.ROW_PREFIX)]


def _python_module(
    source: str,
    *,
    path: str = "package/module.py",
    module: str = "package.module",
) -> Any:
    return scanner.PythonModule(
        module=module,
        path=path,
        tree=ast.parse(source, filename=path),
    )


def _function_registry(*modules: Any) -> Any:
    values = tuple(modules)
    assignments = scanner._module_assignment_registry(values)
    return scanner._function_context_registry(values, assignments), assignments


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _mini_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    _write(
        root / "pyproject.toml",
        '[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["demo*"]\nexclude = []\n',
    )
    _write(
        root / "demo" / "__init__.py",
        "from dataclasses import dataclass\n\n"
        '__all__ = ["Config", "build_manifest"]\n\n'
        "@dataclass\n"
        "class Config:\n"
        "    enabled: bool\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"artifact": {"sha256": "0" * 64}}\n',
    )
    _write(
        root / ".github" / "workflows" / "ci.yml",
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
    )
    _write(root / "configs" / "examples" / "example.yaml", "enabled: true\n")
    for relative in scanner.RETAINED_INVALID_CONFIGS:
        _copy(ROOT / relative, root / relative)
    _write(root / "evidence" / "manifest.csv", "id,path\nartifact,proofs/proof.txt\n")
    _write(
        root / "evidence" / "artifact-manifest.json",
        '{"artifact":{"path":"proofs/proof.txt","sha256":"0"}}\n',
    )
    _write(root / "proofs" / "proof.txt", "retained proof\n")
    _copy(SCANNER_PATH, root / scanner.SCANNER_PATH)
    _copy(INVENTORY_PATH, root / scanner.INVENTORY_PATH)
    _copy(PROFILES_PATH, root / scanner.PROFILES_PATH)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    return root


@pytest.fixture(scope="module")
def candidates() -> Any:
    return scanner.build_candidates(ROOT, INVENTORY_PATH, PROFILES_PATH, DOCS_PATH)


def test_committed_inventory_matches_current_public_surface(
    candidates: tuple[dict[str, Any], dict[str, Any], str, Any],
) -> None:
    inventory, profiles, markdown, discovery = candidates

    assert inventory == _load(INVENTORY_PATH)
    assert profiles == _load(PROFILES_PATH)
    assert markdown == DOCS_PATH.read_text(encoding="utf-8")
    assert discovery.family_counts == EXPECTED_FAMILY_COUNTS
    assert discovery.source_counts == EXPECTED_SOURCE_COUNTS
    assert discovery.config_parser_counts == EXPECTED_CONFIG_PARSERS
    assert len(discovery.rows) == sum(EXPECTED_FAMILY_COUNTS.values()) == 10073
    assert len(_owned_rows(inventory)) == 10073


def test_discovery_is_three_run_deterministic() -> None:
    runs = [scanner.discover(ROOT) for _ in range(3)]
    projections = [
        _canonical_bytes(
            {
                "config_parser_counts": run.config_parser_counts,
                "family_counts": run.family_counts,
                "family_digests": run.family_digests,
                "resource_facets": run.resource_facets,
                "rows": run.rows,
                "source_counts": run.source_counts,
            }
        )
        for run in runs
    ]

    assert projections[0] == projections[1] == projections[2]


def test_static_python_discovery_never_imports_or_executes_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        forbidden = (
            "maniskill_pickcube_adapter",
            "massrobotics_amr_adapter",
            "metriplane",
            "robomimic_lowdim_adapter",
            "ros2_mcap_adapter",
            "source_adapter_sdk",
        )
        if name in forbidden or name.startswith(tuple(f"{item}." for item in forbidden)):
            raise AssertionError(f"discovered module import attempted: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    discovery = scanner.discover(ROOT)
    module = _python_module(
        "raise RuntimeError('must not execute')\n"
        "from dataclasses import dataclass\n"
        '__all__ = ["Record"]\n\n'
        "@dataclass\n"
        "class Record:\n"
        "    value: int\n"
    )

    assert discovery.family_counts["public_api"] == EXPECTED_FAMILY_COUNTS["public_api"]
    assert scanner._public_bindings(module) == (("Record", "class"),)
    models = scanner._model_nodes(module)
    assert [(node.name, kind) for node, kind in models] == [("Record", "dataclass")]
    assert scanner._model_fields(models[0][0], models[0][1]) == ("value",)


@pytest.mark.parametrize(
    "source",
    (
        "exports = ['public']\n__all__ = exports\npublic = 1\n",
        "from package.exports import *\n",
    ),
)
def test_dynamic_or_wildcard_public_exports_fail_closed(source: str) -> None:
    with pytest.raises(scanner.DiscoveryError):
        scanner._public_bindings(_python_module(source))


def test_literal_manifest_keys_are_complete_and_dynamic_mappings_fail_closed() -> None:
    literal = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        '    payload = {"artifact": {"path": "proof.txt", "sha256": "0"}}\n'
        "    return payload\n"
    )
    dynamic = _python_module(
        'def build_manifest() -> dict[str, object]:\n    return {runtime_key(): "value"}\n'
    )
    ambiguous = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        '    payload = {"first": 1}\n'
        '    payload = {"second": 2}\n'
        "    return payload\n"
    )
    imported_helper = _python_module(
        "from .reporting import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    refs = {name: file_ref(name) for name in ("proof",)}\n'
        '    return {"artifact": {**refs["proof"]}}\n'
    )
    unimported_helper = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        '    refs = {name: file_ref(name) for name in ("proof",)}\n'
        '    return {"artifact": {**refs["proof"]}}\n'
    )
    wrongly_imported_helper = _python_module(
        "from .other import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    refs = {name: file_ref(name) for name in ("proof",)}\n'
        '    return {"artifact": {**refs["proof"]}}\n'
    )
    helper_module = _python_module(
        'def file_ref(name: str) -> dict[str, str]:\n    return {"path": name, "sha256": "0"}\n',
        path="package/reporting.py",
        module="package.reporting",
    )

    assert scanner._manifest_ast_pointers(literal, {}) == {
        "function:build_manifest/artifact",
        "function:build_manifest/artifact/path",
        "function:build_manifest/artifact/sha256",
    }
    with pytest.raises(scanner.DiscoveryError, match="manifest keys must"):
        scanner._manifest_ast_pointers(dynamic, {})
    with pytest.raises(scanner.DiscoveryError, match="assignment is ambiguous"):
        scanner._manifest_ast_pointers(ambiguous, {})
    external, _assignments = _function_registry(imported_helper, helper_module)
    assert scanner._manifest_ast_pointers(imported_helper, external) == {
        "function:build_manifest/artifact",
        "function:build_manifest/artifact/path",
        "function:build_manifest/artifact/sha256",
    }
    with pytest.raises(scanner.DiscoveryError, match="dynamic manifest mapping"):
        scanner._manifest_ast_pointers(unimported_helper, external)
    with pytest.raises(scanner.DiscoveryError, match="dynamic manifest mapping"):
        scanner._manifest_ast_pointers(wrongly_imported_helper, external)

    conventional = _python_module(
        "def artifact_manifest():\n"
        '    return {"artifact": {"sha256": "0"}}\n\n'
        "def create_manifest() -> dict[str, object] | None:\n"
        '    return {"created": 1}\n\n'
        "def generate_manifest():\n"
        '    return {"generated": 1}\n\n'
        "def write_manifest():\n"
        '    return {"written": 1}\n\n'
        "def build_artifact_manifest():\n"
        '    return {"composite_artifact": 1}\n\n'
        "def create_release_manifest():\n"
        '    return {"composite_release": 1}\n'
    )
    assert scanner._manifest_ast_pointers(conventional, {}) == {
        "function:artifact_manifest/artifact",
        "function:artifact_manifest/artifact/sha256",
        "function:build_artifact_manifest/composite_artifact",
        "function:create_manifest/created",
        "function:create_release_manifest/composite_release",
        "function:generate_manifest/generated",
        "function:write_manifest/written",
    }

    dynamic_builder = _python_module("def create_manifest(source):\n    return source\n")
    with pytest.raises(scanner.DiscoveryError, match="dynamic manifest mapping"):
        scanner._manifest_ast_pointers(dynamic_builder, {})

    annotated = _python_module(
        'manifest: dict[str, object] = {"artifact": {"sha256": "0"}}\n\n'
        "def collect() -> None:\n"
        '    artifact_manifest: dict[str, object] = {"created": 1}\n'
    )
    assert scanner._manifest_ast_pointers(annotated, {}) == {
        "assignment:collect:artifact_manifest/created",
        "assignment:module:manifest/artifact",
        "assignment:module:manifest/artifact/sha256",
    }


def test_reflection_provenance_has_three_explicit_states() -> None:
    owner = _python_module(
        "class Holder:\n    pass\n\ndef marker():\n    pass\n",
        path="package/owner.py",
        module="package.owner",
    )
    bridge = _python_module(
        "from .owner import marker\n\nclass Holder:\n    pass\n",
        path="package/bridge.py",
        module="package.bridge",
    )
    probe = _python_module(
        "import package.bridge as bridge\n"
        "from .owner import marker\n"
        "from external import (\n"
        "    EXTERNAL_ACCESS, MODULE_NAME, NAMESPACE, attribute_name, lookup, module_name, reflect,\n"
        ")\n\n"
        "def exact_module_name():\n"
        '    return "package.owner"\n\n'
        "def unknown_namespace():\n"
        "    return reflect(marker)\n\n"
        "def unknown_callable():\n"
        "    return reflect\n\n"
        "def local_lookup(name):\n"
        "    return getattr(marker, '__globals__')[name]\n\n"
        "KNOWN_CALLABLE = exact_module_name\n"
        "UNKNOWN_CALLABLE = reflect\n"
        "UNKNOWN_ATTRIBUTE_CALLABLE = EXTERNAL_ACCESS.lookup\n"
        "UNKNOWN_CONTAINER_CALLABLE = [reflect][0]\n"
        "UNKNOWN_HELPER_CALLABLE = unknown_callable()\n"
        "UNKNOWN_QUALIFIED_CALLABLE = bridge.UNKNOWN_CALLABLE\n"
        "IRRELEVANT_CALLABLE = 42\n"
        "KNOWN_NAME = exact_module_name()\n"
        "NAME_GETTER = exact_module_name\n"
        "KNOWN_ALIAS_NAME = NAME_GETTER()\n"
        "KNOWN_DUPLICATE_NAME = "
        "{'pick': module_name, 'pick': exact_module_name}['pick']()\n"
        "KNOWN_SPREAD_NAME = {**NAMESPACE, 'pick': exact_module_name}['pick']()\n"
        "IRRELEVANT_NAME = 42\n"
        'KNOWN_NS = getattr(marker, "__globals__")\n'
        "ACCESS = getattr\n"
        'KNOWN_ALIAS_NS = ACCESS(marker, "__globals__")\n'
        "BOUND = marker.__getattribute__\n"
        'KNOWN_BOUND_NS = BOUND("__globals__")\n'
        'KNOWN_CONTAINER_NS = [getattr(marker, "__globals__")][0]\n'
        "KNOWN_REEXPORTED_NS = bridge.marker.__globals__\n"
        'KNOWN_UNBOUND_NS = object.__getattribute__(marker, "__globals__")\n'
        'KNOWN_CLASS = KNOWN_NS["Holder"]\n'
        'KNOWN_ALIAS_CLASS = KNOWN_ALIAS_NS["Holder"]\n'
        'KNOWN_BOUND_CLASS = KNOWN_BOUND_NS["Holder"]\n'
        'KNOWN_CONTAINER_CLASS = KNOWN_CONTAINER_NS["Holder"]\n'
        'KNOWN_REEXPORTED_CLASS = KNOWN_REEXPORTED_NS["Holder"]\n'
        'KNOWN_UNBOUND_CLASS = KNOWN_UNBOUND_NS["Holder"]\n'
        "UNKNOWN_NAME = module_name()\n"
        "MODULE_GETTER = module_name\n"
        "UNKNOWN_ALIAS_NAME = MODULE_GETTER()\n"
        "UNKNOWN_CONTAINER_NAME = [module_name][0]()\n"
        "UNKNOWN_IMPORTED_NAME = MODULE_NAME\n"
        "UNKNOWN_QUALIFIED_NAME = bridge.UNKNOWN_NAME\n"
        "UNKNOWN_DUPLICATE_NAME = "
        "{'pick': exact_module_name, 'pick': module_name}['pick']()\n"
        "UNKNOWN_SPREAD_NAME = {'pick': exact_module_name, **NAMESPACE}['pick']()\n"
        "UNKNOWN_NS = reflect(marker)\n"
        "UNKNOWN_HELPER_NS = unknown_namespace()\n"
        "UNKNOWN_CONTAINER_NS = [reflect(marker)][0]\n"
        "UNKNOWN_QUALIFIED_NS = bridge.UNKNOWN_NAMESPACE\n"
        'UNKNOWN_CLASS = UNKNOWN_NS["Holder"]\n'
        'UNKNOWN_HELPER_CLASS = UNKNOWN_HELPER_NS["Holder"]\n'
        'UNKNOWN_ATTR_CLASS = getattr(marker, attribute_name())["Holder"]\n'
        "LOCAL_LOOKUP_ALIAS = local_lookup\n"
        'KNOWN_HELPER_GETTER_CLASS = local_lookup("Holder")\n'
        'KNOWN_ALIAS_GETTER_CLASS = LOCAL_LOOKUP_ALIAS("Holder")\n'
        'UNKNOWN_IMPORTED_NAMESPACE_CLASS = NAMESPACE["Holder"]\n'
        'UNKNOWN_IMPORTED_CONTAINER_CLASS = [NAMESPACE][0]["Holder"]\n'
        "UNKNOWN_QUALIFIED_CLASS = bridge.UNKNOWN_CLASSES[0]\n"
        'UNKNOWN_IMPORTED_GETTER_CLASS = lookup("Holder")\n'
        'UNKNOWN_IMPORTED_ACCESSOR_CLASS = EXTERNAL_ACCESS("__globals__")["Holder"]\n'
        'UNKNOWN_CALL_NS = EXTERNAL_ACCESS(marker, "__globals__")\n'
        "UNKNOWN_ATTRIBUTE_ACCESSOR = EXTERNAL_ACCESS.lookup\n"
        "UNKNOWN_UNBOUND_NS = "
        "EXTERNAL_ACCESS.__getattribute__(marker, '__globals__')\n"
        'UNKNOWN_UNBOUND_CLASS = UNKNOWN_UNBOUND_NS["Holder"]\n',
        path="package/probe.py",
        module="package.probe",
    )
    assignments = scanner._module_assignment_registry((owner, bridge, probe))
    probe_assignments = assignments[probe.module]
    expressions = {
        node.targets[0].id: node.value
        for node in probe.tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }

    for name in (
        "KNOWN_NAME",
        "KNOWN_ALIAS_NAME",
        "KNOWN_DUPLICATE_NAME",
        "KNOWN_SPREAD_NAME",
    ):
        result = scanner._qualified_module_name_values(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.KNOWN, name
        assert result.values == {"package.owner"}
    irrelevant = scanner._qualified_module_name_values(
        expressions["IRRELEVANT_NAME"], probe_assignments, assignments
    )
    assert irrelevant.state is scanner._ProvenanceState.IRRELEVANT
    assert not irrelevant.values
    for name in (
        "UNKNOWN_NAME",
        "UNKNOWN_ALIAS_NAME",
        "UNKNOWN_CONTAINER_NAME",
        "UNKNOWN_IMPORTED_NAME",
        "UNKNOWN_QUALIFIED_NAME",
        "UNKNOWN_DUPLICATE_NAME",
        "UNKNOWN_SPREAD_NAME",
    ):
        result = scanner._qualified_module_name_values(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.UNRESOLVED

    known_callable = scanner._qualified_callable_provenance(
        expressions["KNOWN_CALLABLE"], probe_assignments, assignments
    )
    assert known_callable.state is scanner._ProvenanceState.KNOWN
    assert {callback.name for callback, _module, _implicit in known_callable.values} == {
        "exact_module_name"
    }
    for name in (
        "UNKNOWN_CALLABLE",
        "UNKNOWN_ATTRIBUTE_CALLABLE",
        "UNKNOWN_CONTAINER_CALLABLE",
        "UNKNOWN_HELPER_CALLABLE",
        "UNKNOWN_QUALIFIED_CALLABLE",
    ):
        result = scanner._qualified_callable_provenance(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.UNRESOLVED
    irrelevant_callable = scanner._qualified_callable_provenance(
        expressions["IRRELEVANT_CALLABLE"], probe_assignments, assignments
    )
    assert irrelevant_callable.state is scanner._ProvenanceState.IRRELEVANT

    for name in (
        "KNOWN_NS",
        "KNOWN_ALIAS_NS",
        "KNOWN_BOUND_NS",
        "KNOWN_CONTAINER_NS",
        "KNOWN_REEXPORTED_NS",
        "KNOWN_UNBOUND_NS",
    ):
        result = scanner._qualified_namespace_modules(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.KNOWN, name
        assert result.values == {"package.owner"}
    for name in (
        "UNKNOWN_NS",
        "UNKNOWN_HELPER_NS",
        "UNKNOWN_CONTAINER_NS",
        "UNKNOWN_QUALIFIED_NS",
        "UNKNOWN_CALL_NS",
        "UNKNOWN_UNBOUND_NS",
    ):
        result = scanner._qualified_namespace_modules(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.UNRESOLVED

    for name in ("UNKNOWN_CALL_NS", "UNKNOWN_UNBOUND_NS"):
        result = scanner._qualified_reflected_object_provenance(
            expressions[name],
            "__globals__",
            probe_assignments,
            assignments,
        )
        assert result.state is scanner._ProvenanceState.UNRESOLVED
    attribute_accessor = scanner._qualified_bound_attribute_accessor_provenance(
        expressions["UNKNOWN_ATTRIBUTE_ACCESSOR"],
        "__getattribute__",
        probe_assignments,
        assignments,
    )
    assert attribute_accessor.state is scanner._ProvenanceState.UNRESOLVED

    for name in (
        "KNOWN_CLASS",
        "KNOWN_ALIAS_CLASS",
        "KNOWN_BOUND_CLASS",
        "KNOWN_CONTAINER_CLASS",
        "KNOWN_REEXPORTED_CLASS",
        "KNOWN_UNBOUND_CLASS",
        "KNOWN_HELPER_GETTER_CLASS",
        "KNOWN_ALIAS_GETTER_CLASS",
    ):
        result = scanner._qualified_assignment_references(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.KNOWN
        assert result.values == {("package.owner", "Holder")}
    for name in (
        "UNKNOWN_CLASS",
        "UNKNOWN_HELPER_CLASS",
        "UNKNOWN_ATTR_CLASS",
        "UNKNOWN_IMPORTED_NAMESPACE_CLASS",
        "UNKNOWN_IMPORTED_CONTAINER_CLASS",
        "UNKNOWN_IMPORTED_GETTER_CLASS",
        "UNKNOWN_IMPORTED_ACCESSOR_CLASS",
        "UNKNOWN_UNBOUND_CLASS",
    ):
        result = scanner._qualified_assignment_references(
            expressions[name], probe_assignments, assignments
        )
        assert result.state is scanner._ProvenanceState.UNRESOLVED, name

    qualified_selection = scanner._qualified_selected_reference_expressions(
        expressions["UNKNOWN_QUALIFIED_CLASS"],
        probe_assignments,
        assignments,
    )
    assert qualified_selection.state is scanner._ProvenanceState.UNRESOLVED

    _assert_provenance_scope_survives_qualified_aliases_and_wrappers()


def _assert_provenance_scope_survives_qualified_aliases_and_wrappers() -> None:
    def module(source: str, name: str) -> scanner.PythonModule:
        return _python_module(
            source,
            path=f"{name.replace('.', '/')}.py",
            module=name,
        )

    def invalidation_flags(
        registry: dict[str, scanner.AssignmentMap],
        *keys: tuple[str, str],
    ) -> tuple[bool, ...]:
        flags: list[bool] = []
        for module_name, symbol in keys:
            values = registry[module_name][symbol]
            assert len(values) == 1
            assert isinstance(values[0], scanner._ClassBinding)
            flags.append(values[0].invalidated)
        return tuple(flags)

    owner = module(
        "class Holder:\n"
        "    ITEMS = []\n"
        "    changed = 0\n\n"
        "class Sibling:\n"
        "    ITEMS = []\n"
        "    changed = 0\n"
        "\n"
        "def marker():\n"
        "    pass\n",
        "package.owner",
    )
    bridge = module(
        "from .owner import Holder as Alias\n\nclass BridgeDecoy:\n    changed = 0\n",
        "package.bridge",
    )
    owner_keys = (
        ("package.owner", "Holder"),
        ("package.owner", "Sibling"),
        ("package.bridge", "BridgeDecoy"),
    )
    exact_accessor_sources = (
        "import builtins as b\n"
        "import package.owner as target\n\n"
        "b.setattr(target.Holder, 'changed', 1)\n",
        "import builtins as b\n"
        "import package.owner as target\n\n"
        "ACCESS = b.setattr\n"
        "ACCESS(target.Holder, 'changed', 1)\n",
        "import builtins as b\n"
        "import package.owner as target\n\n"
        "FIRST = b.setattr\n"
        "ACCESS = FIRST\n"
        "ACCESS(target.Holder, 'changed', 1)\n",
        "import builtins as b\n"
        "import package.owner as target\n\n"
        "ACCESS = b.delattr\n"
        "ACCESS(target.Holder, 'changed')\n",
        "import builtins as b\n"
        "import package.bridge as target\n\n"
        "ACCESS = b.setattr\n"
        "ACCESS(target.Alias, 'changed', 1)\n",
        "import builtins as b\n"
        "import package.owner as target\n\n"
        "ACCESS = b.vars\n"
        "Alias = ACCESS(target)['Holder']\n"
        "Alias.changed = 1\n",
        "from package.owner import marker\n"
        "ACCESS = object.__getattribute__\n"
        "Alias = ACCESS(marker, '__globals__')['Holder']\n"
        "Alias.changed = 1\n",
        "from package.owner import marker\n"
        "FIRST = object.__getattribute__\n"
        "ACCESS = FIRST\n"
        "Alias = ACCESS(marker, '__globals__')['Holder']\n"
        "Alias.changed = 1\n",
    )
    owner_orders = (
        lambda mutator: (owner, bridge, mutator),
        lambda mutator: (mutator, bridge, owner),
        lambda mutator: (bridge, owner, mutator),
    )
    for source in exact_accessor_sources:
        for order in owner_orders:
            mutator = module(source, "package.mutator")
            registry = scanner._module_assignment_registry(order(mutator))
            assert invalidation_flags(registry, *owner_keys) == (True, False, False), source

    wrapper_sources = (
        "import package.owner as target\nAlias = vars(target)['Holder']\nAlias.changed = 1\n",
        "import package.owner as target\n"
        "def namespace():\n"
        "    return vars(target)\n"
        "Alias = namespace()['Holder']\n"
        "Alias.changed = 1\n",
        "import package.owner as target\nAlias = dict(vars(target))['Holder']\nAlias.changed = 1\n",
        "import copy\n"
        "import package.owner as target\n"
        "Alias = copy.copy(vars(target))['Holder']\n"
        "Alias.changed = 1\n",
        "import package.owner as target\n"
        "def identity(value):\n"
        "    return value\n"
        "Alias = identity(vars(target))['Holder']\n"
        "Alias.changed = 1\n",
        "from types import MappingProxyType\n"
        "import package.owner as target\n"
        "Alias = MappingProxyType(vars(target))['Holder']\n"
        "Alias.changed = 1\n",
    )
    for source in wrapper_sources:
        for order in owner_orders:
            mutator = module(source, "package.mutator")
            registry = scanner._module_assignment_registry(order(mutator))
            assert invalidation_flags(registry, *owner_keys) == (True, False, False), source

    helper = module(
        "def change(cls):\n    cls.changed = 1\nCALLBACKS = (change,)\n",
        "package.helper",
    )
    reexport = module("from .helper import CALLBACKS\n", "package.reexport")
    callback_sources = (
        "from package.helper import CALLBACKS\n"
        "import package.owner as target\n"
        "CALLBACKS[0](target.Holder)\n",
        "from package.reexport import CALLBACKS\n"
        "import package.owner as target\n"
        "CALLBACKS[0](target.Holder)\n",
        "import package.helper as helper\n"
        "import package.owner as target\n"
        "helper.CALLBACKS[0](target.Holder)\n",
        "import package.helper as helper\n"
        "import package.owner as target\n"
        "CALLBACKS = helper.CALLBACKS\n"
        "CALLBACKS[0](target.Holder)\n",
        "import package.reexport as helper\n"
        "import package.owner as target\n"
        "helper.CALLBACKS[0](target.Holder)\n",
    )
    for source in callback_sources:
        mutator = module(source, "package.mutator")
        registry = scanner._module_assignment_registry((mutator, reexport, helper, bridge, owner))
        assert invalidation_flags(registry, *owner_keys) == (True, False, False), source

    box = module(
        "from .owner import Holder\nBOX = [Holder]\n",
        "package.box",
    )
    class_container_sources = (
        "import package.owner as target\nBOX = [target.Holder]\nBOX[0].changed = 1\n",
        "import package.box as box\nbox.BOX[0].changed = 1\n",
    )
    for source in class_container_sources:
        mutator = module(source, "package.mutator")
        registry = scanner._module_assignment_registry((mutator, box, bridge, owner))
        assert invalidation_flags(registry, *owner_keys) == (True, False, False), source

    class_owned_container_sources = (
        "import package.owner as target\ntarget.Holder.ITEMS.append(1)\n",
        "import package.owner as target\nITEMS = target.Holder.ITEMS\nITEMS.append(1)\n",
        "import package.owner as target\nBOX = [target.Holder.ITEMS]\nBOX[0].append(1)\n",
    )
    for source in class_owned_container_sources:
        for order in owner_orders:
            mutator = module(source, "package.mutator")
            registry = scanner._module_assignment_registry(order(mutator))
            assert invalidation_flags(registry, *owner_keys) == (True, False, False), source

    names = module(
        "MODULE_NAME = 'package.owner'\nNAMES = (MODULE_NAME,)\n",
        "package.names",
    )
    probe = module(
        "import package.names as names\n"
        "from package.names import MODULE_NAME, NAMES\n"
        "A = names.MODULE_NAME\n"
        "B = names.NAMES[0]\n"
        "C = MODULE_NAME\n"
        "D = NAMES[0]\n",
        "package.probe",
    )
    assignments = scanner._module_assignment_registry((probe, names, owner))
    state = assignments[probe.module]
    expressions = {
        node.targets[0].id: node.value
        for node in probe.tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    for name in ("A", "B", "C", "D"):
        result = scanner._qualified_module_name_values(expressions[name], state, assignments)
        assert result.state is scanner._ProvenanceState.KNOWN, name
        assert result.values == {"package.owner"}, name


def test_nested_manifest_aliases_helpers_and_sequences_are_complete() -> None:
    module = _python_module(
        "def file_ref() -> dict[str, str]:\n"
        '    return {"path": "proof.txt", "sha256": "0"}\n\n'
        "def source_artifacts() -> list[dict[str, object]]:\n"
        '    return [{"artifact_id": "proof", "metadata": {"media_type": "text/plain"}}]\n\n'
        "def build_manifest() -> dict[str, object]:\n"
        "    reference = file_ref()\n"
        '    reference["media_type"] = "text/plain"\n'
        '    references = {name: file_ref() for name in ("proof",)}\n'
        '    inline = [{"nested": {"enabled": True}}]\n'
        '    return {"alias": reference, "helper_list": source_artifacts(), '
        '"inline_list": inline, "selected": references["proof"]}\n'
    )

    assert scanner._manifest_ast_pointers(module, {}) == {
        "function:build_manifest/alias",
        "function:build_manifest/alias/media_type",
        "function:build_manifest/alias/path",
        "function:build_manifest/alias/sha256",
        "function:build_manifest/helper_list",
        "function:build_manifest/helper_list/*/artifact_id",
        "function:build_manifest/helper_list/*/metadata",
        "function:build_manifest/helper_list/*/metadata/media_type",
        "function:build_manifest/inline_list",
        "function:build_manifest/inline_list/*/nested",
        "function:build_manifest/inline_list/*/nested/enabled",
        "function:build_manifest/selected",
        "function:build_manifest/selected/path",
        "function:build_manifest/selected/sha256",
    }

    alias_mutation = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        '    payload = {"known": 1}\n'
        "    alias = payload\n"
        '    alias["hidden"] = {"child": 1}\n'
        "    return payload\n"
    )
    accessor_alias = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    alias = payload.get("nested")\n'
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    returned_alias = _python_module(
        "def identity(value):\n"
        "    return value\n\n"
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    alias = identity(payload["nested"])\n'
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    boolean_alias = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    alias = payload.get("nested") or {}\n'
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    unpacked_alias = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    box = [payload["nested"]]\n'
        "    alias, = box\n"
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    indexed_returned_alias = _python_module(
        "def identity(value):\n"
        "    return value\n\n"
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    alias = identity([payload["nested"]])[0]\n'
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    popped_alias = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    box = [payload["nested"]]\n'
        "    alias = box.pop()\n"
        '    alias.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    wrapped_builtin_aliases = (
        _python_module(
            "def build_manifest():\n"
            '    payload = {"nested": {"known": 1}}\n'
            '    alias = list([payload["nested"]])[0]\n'
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"nested": {"known": 1}}\n'
            '    alias = dict(item=payload["nested"])["item"]\n'
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"nested": {"known": 1}}\n'
            '    alias = tuple(list([payload["nested"]]))[0]\n'
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"nested": {"known": 1}}\n'
            '    alias = tuple(item for item in [payload["nested"]])[0]\n'
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        ),
    )
    nested_wrapper_mutation = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    box = [payload]\n"
        '    box[0].update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    retained_wrapper_writes = (
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    box = [payload]\n"
            '    box[0]["hidden"] = {"child": 1}\n'
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1, "count": 0}\n'
            "    box = [payload]\n"
            '    box[0]["count"] += 1\n'
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1, "hidden": {"child": 1}}\n'
            "    box = [payload]\n"
            '    del box[0]["hidden"]\n'
            "    return payload\n"
        ),
    )
    comprehension_helper_mutation = _python_module(
        "def mutate(box):\n"
        '    box[0]["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    box = [item for item in [payload]]\n"
        "    mutate(box)\n"
        "    return payload\n"
    )
    iterator_call_aliases = tuple(
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            f"    alias = list({expression})[0]\n"
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        )
        for expression in (
            "map(lambda value: value, [payload])",
            "filter(lambda value: True, [payload])",
            "zip([payload], strict=True)",
        )
    )
    named_iterator_call_aliases = tuple(
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    container = [payload]\n"
            f"    alias = list({expression})[0]\n"
            '    alias.update({"hidden": {"child": 1}})\n'
            "    return payload\n"
        )
        for expression in (
            "map(lambda value: value, container)",
            "filter(lambda value: True, container)",
            "zip(container, strict=True)",
        )
    )
    iterator_callback_mutations = tuple(
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            f"    {expression}\n"
            "    return payload\n"
        )
        for expression in (
            'list(map(lambda _: payload.update({"hidden": {"child": 1}}), [0]))',
            'list(filter(lambda _: payload.update({"hidden": {"child": 1}}), [0]))',
            'sorted([0], key=lambda _: payload.update({"hidden": {"child": 1}}))',
            'max([0], key=lambda _: payload.update({"hidden": {"child": 1}}))',
            'min([0], key=lambda _: payload.update({"hidden": {"child": 1}}))',
            'values = [0]; values.sort(key=lambda _: payload.update({"hidden": {"child": 1}}))',
            'list(iter(lambda: payload.update({"hidden": {"child": 1}}), None))',
        )
    )
    callback_provenance_mutations = (
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    list(map(\n"
            '        lambda _, value=payload: value.update({"hidden": {"child": 1}}),\n'
            "        [0],\n"
            "    ))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def mutate():\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "    list(map(lambda _: mutate(), [0]))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def mutate(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "    alias = mutate\n"
            "    list(map(alias, [0]))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    class Helper:\n"
            "        def mutate(self, _):\n"
            '            payload.update({"hidden": {"child": 1}})\n'
            "    helper = Helper()\n"
            "    list(map(helper.mutate, [0]))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    class Item:\n"
            "        def __str__(self):\n"
            '            payload.update({"hidden": {"child": 1}})\n'
            '            return "item"\n'
            "    list(map(str, [Item()]))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(_, value=payload):\n"
            '        dict.update(value, {"hidden": {"child": 1}})\n'
            "    list(map(callback, [0]))\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def mutate(value):\n"
            '        value.update({"hidden": {"child": 1}})\n'
            "    def callback(_, *, value=payload):\n"
            "        mutate(value)\n"
            "    alias = callback\n"
            "    list(map(alias, [0]))\n"
            "    return payload\n"
        ),
    )
    stdlib_callback_mutations = (
        _python_module(
            "from functools import reduce as fold\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(left, right):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return left + right\n"
            "    fold(callback, [0, 1])\n"
            "    return payload\n"
        ),
        _python_module(
            "import itertools\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return 0\n"
            "    list(itertools.groupby([0], key=callback))\n"
            "    return payload\n"
        ),
    )
    dispatcher_provenance_mutations = (
        _python_module(
            "def max(items, key):\n"
            "    key()\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(value=payload):\n"
            '        value.update({"hidden": {"child": 1}})\n'
            "    max([0], key=callback)\n"
            "    return payload\n"
        ),
        _python_module(
            "class Helper:\n"
            "    def sort(self, key):\n"
            "        key()\n\n"
            "helper = Helper()\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(value=payload):\n"
            '        value.update({"hidden": {"child": 1}})\n'
            "    helper.sort(key=callback)\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def key(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return 0\n"
            '    dispatch = {"run": max}["run"]\n'
            "    dispatch([0], key=key)\n"
            "    return payload\n"
        ),
        _python_module(
            "def identity(value):\n"
            "    return value\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def key(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return 0\n"
            "    dispatch = identity(max)\n"
            "    dispatch([0], key=key)\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    values = [0]\n"
            "    def key(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return 0\n"
            '    dispatch = {"run": values.sort}["run"]\n'
            "    dispatch(key=key)\n"
            "    return payload\n"
        ),
        _python_module(
            "import builtins\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def key(_):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return 0\n"
            "    builtins.max([0], key=key)\n"
            "    return payload\n"
        ),
        _python_module(
            "import functools\n\n"
            "def identity(value):\n"
            "    return value\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def callback(left, right):\n"
            '        payload.update({"hidden": {"child": 1}})\n'
            "        return left + right\n"
            "    dispatch = identity(functools.reduce)\n"
            "    dispatch(callback, [0, 1])\n"
            "    return payload\n"
        ),
        _python_module(
            "def identity(value):\n"
            "    return value\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    class Item:\n"
            "        def __lt__(self, other):\n"
            '            payload.update({"hidden": {"child": 1}})\n'
            "            return False\n"
            "    dispatch = identity(max)\n"
            "    dispatch(Item(), Item())\n"
            "    return payload\n"
        ),
    )
    method_mutation = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        '    payload = {"known": 1}\n'
        '    payload.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    nested_list_mutation = _python_module(
        "def build_manifest() -> dict[str, object]:\n"
        "    items = []\n"
        '    payload = {"items": items}\n'
        '    items.append({"child": 1})\n'
        "    return payload\n"
    )
    retained_subscript_write = _python_module(
        'payload = {"known": 1}\n'
        "manifest = payload\n"
        'payload["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        "    return manifest\n"
    )
    nested_retained_subscript_write = _python_module(
        'payload = {"known": 1}\n'
        "items = [payload]\n"
        'payload["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        '    return {"items": items}\n'
    )
    constructor_snapshot = _python_module(
        'payload = {"known": 1}\n'
        "manifest = dict(item=payload)\n"
        'payload = {"decoy": 1}\n\n'
        "def build_manifest():\n"
        "    return manifest\n"
    )
    comprehension_snapshot = _python_module(
        'payload = {"known": 1}\n'
        "manifest = [item for item in [payload]]\n"
        'payload = {"decoy": 1}\n\n'
        "def build_manifest():\n"
        '    return {"items": manifest}\n'
    )
    lazy_generator_rebind = _python_module(
        'payload = {"known": 1}\n'
        "generator = (payload for _ in [0])\n"
        'payload = {"decoy": 1}\n'
        "manifest = [*generator]\n\n"
        "def build_manifest():\n"
        '    return {"items": manifest}\n'
    )
    generator_outer_iter_snapshot = _python_module(
        'items = [{"known": 1}]\n'
        "generator = (item for item in items)\n"
        'items = [{"decoy": 1}]\n'
        "manifest = [*generator]\n\n"
        "def build_manifest():\n"
        '    return {"items": manifest}\n'
    )
    generator_inner_iter_rebind = _python_module(
        'items = [{"known": 1}]\n'
        "generator = (item for _ in [0] for item in items)\n"
        'items = [{"decoy": 1}]\n'
        "manifest = [*generator]\n\n"
        "def build_manifest():\n"
        '    return {"items": manifest}\n'
    )
    generator_outer_iter_mutations = tuple(
        _python_module(
            'items = [{"known": 1}]\n'
            "generator = (item for item in items)\n"
            f"{mutation}\n"
            "manifest = [*generator]\n\n"
            "def build_manifest():\n"
            '    return {"items": manifest}\n'
        )
        for mutation in (
            'items[0] = {"decoy": 1}',
            "del items[0]",
            'items[:] = [{"decoy": 1}]',
            'items += [{"decoy": 1}]',
            "items *= 0",
            "items.__imul__(0)",
            "items.clear()",
            "items.pop()",
            "items.reverse()",
        )
    )
    generator_nested_outer_iter_mutations = tuple(
        _python_module(
            'items = [{"known": 1}]\n'
            "holder = [items]\n"
            "generator = (item for item in items)\n"
            f"{mutation}\n"
            "manifest = [*generator]\n\n"
            "def build_manifest():\n"
            '    return {"items": manifest}\n'
        )
        for mutation in (
            'holder[0][0] = {"decoy": 1}',
            "holder[0].clear()",
            "holder[0].reverse()",
        )
    )
    eagerly_consumed_generator = _python_module(
        'items = [{"value": 1}]\n'
        'n_frames = max((item["value"] for item in items), default=0)\n'
        "items.reverse()\n"
        'manifest = {"frames": n_frames + 1}\n\n'
        "def build_manifest():\n"
        "    return manifest\n"
    )
    composite_default_mutations = tuple(
        _python_module(
            'GLOBAL = {"known": 1}\n'
            'BOX = {"item": GLOBAL}\n\n'
            f"def effect(value={default_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n\n'
            "manifest = GLOBAL\n"
            "effect()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        )
        for default_expression in (
            "GLOBAL if True else {}",
            "GLOBAL or {}",
            'BOX.get("item")',
        )
    )
    helper_mutation = _python_module(
        "def mutate(value) -> None:\n"
        '    value["hidden"] = {"child": 1}\n\n'
        "def build_manifest() -> dict[str, object]:\n"
        '    payload = {"known": 1}\n'
        "    mutate(payload)\n"
        "    return payload\n"
    )
    wrapped_helper_mutation = _python_module(
        "def mutate(box):\n"
        '    box[0]["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    box = [payload]\n"
        "    mutate(box)\n"
        "    return payload\n"
    )
    literal_helper_mutation = _python_module(
        "def mutate(box):\n"
        '    box[0]["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    mutate([payload])\n"
        "    return payload\n"
    )
    default_helper_mutation = _python_module(
        'payload = {"known": 1}\n\n'
        "def mutate(value=payload):\n"
        '    value["hidden"] = {"child": 1}\n\n'
        "def build_manifest():\n"
        "    mutate()\n"
        "    return payload\n"
    )
    nested_update = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    payload["nested"].update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    nested_append = _python_module(
        "def build_manifest():\n"
        '    payload = {"items": []}\n'
        '    payload["items"].append({"child": 1})\n'
        "    return payload\n"
    )
    bound_mutator = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    mutate = payload.update\n"
        '    mutate({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    reflected_mutator = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    mutate = getattr(payload, "update")\n'
        '    mutate({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    indexed_mutator = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    mutators = {"update": payload.update}\n'
        '    mutators["update"]({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    unbound_mutator = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    dict.update(payload, {"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    operator_mutator = _python_module(
        "import operator\n\n"
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    operator.setitem(payload, "hidden", {"child": 1})\n'
        "    return payload\n"
    )
    qualified_mutators = (
        _python_module(
            f"import {module_name}\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            f"    {call}\n"
            "    return payload\n"
        )
        for module_name, call in (
            ("operator", 'operator.ior(payload, {"hidden": {"child": 1}})'),
            ("heapq", 'heapq.heappush(payload, {"hidden": {"child": 1}})'),
            ("bisect", 'bisect.insort(payload, {"hidden": {"child": 1}})'),
            ("helper", "helper.mutate(payload)"),
        )
    )
    transformed_qualified_calls = (
        _python_module(
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value["hidden"] = {"child": 1}\n\n'
            "def identity(value):\n"
            "    return value\n\n"
            "helper = Helper()\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    helper.touch(identity(payload))\n"
            "    return payload\n"
        ),
        _python_module(
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    ignored = helper.touch(payload)\n"
            "    return payload\n"
        ),
        _python_module(
            "class Helper:\n"
            "    def write_text(self, value):\n"
            '        value["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n\n"
            "def identity(value):\n"
            "    return value\n\n"
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    helper.write_text(identity(payload))\n"
            "    return payload\n"
        ),
    )
    nested_helper = _python_module(
        "def build_manifest():\n"
        "    def mutate(value):\n"
        '        value["hidden"] = {"child": 1}\n'
        '    payload = {"known": 1}\n'
        "    mutate(payload)\n"
        "    return payload\n"
    )
    nested_closure = _python_module(
        "def build_manifest():\n"
        "    def mutate():\n"
        '        payload["hidden"] = {"child": 1}\n'
        '    payload = {"known": 1}\n'
        "    mutate()\n"
        "    return payload\n"
    )
    nested_default_helper = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    def mutate(value=payload):\n"
        '        value["hidden"] = {"child": 1}\n'
        "    mutate()\n"
        "    return payload\n"
    )
    nested_default_mutation = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    def inner(value=payload.update({"hidden": {"child": 1}})):\n'
        "        return value\n"
        "    return payload\n"
    )
    nested_class_mutation = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    class Inner:\n"
        '        value = payload.update({"hidden": {"child": 1}})\n'
        "    return payload\n"
    )
    class_mutation_before_binding = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    class Inner:\n"
        '        value = payload.update({"hidden": {"child": 1}})\n'
        '        payload = {"class_only": 1}\n'
        "    return payload\n"
    )
    decorated_definition_mutation = _python_module(
        "def decorate(value):\n"
        '    value["hidden"] = {"child": 1}\n'
        "    return lambda function: function\n\n"
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    @decorate(payload)\n"
        "    def inner():\n"
        "        pass\n"
        "    return payload\n"
    )
    implicit_decorator_mutations = (
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def decorate(function):\n"
            '        payload["hidden"] = {"child": 1}\n'
            "        return function\n"
            "    @decorate\n"
            "    def inner():\n"
            "        pass\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def factory():\n"
            "        def decorate(function):\n"
            '            payload["hidden"] = {"child": 1}\n'
            "            return function\n"
            "        return decorate\n"
            "    @factory()\n"
            "    def inner():\n"
            "        pass\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def decorate(function):\n"
            '        payload["hidden"] = {"child": 1}\n'
            "        return function\n"
            "    alias = decorate\n"
            "    @alias\n"
            "    def inner():\n"
            "        pass\n"
            "    return payload\n"
        ),
        _python_module(
            "def build_manifest():\n"
            '    payload = {"known": 1}\n'
            "    def decorate(value):\n"
            '        payload["hidden"] = {"child": 1}\n'
            "        return value\n"
            "    @decorate\n"
            "    class Inner:\n"
            "        pass\n"
            "    return payload\n"
        ),
    )
    dynamic_receiver = _python_module(
        "def build_manifest():\n"
        '    payload = {"nested": {"known": 1}}\n'
        '    getattr(payload, "nested").update({"hidden": 1})\n'
        "    return payload\n"
    )
    for unresolved_mutation in (
        accessor_alias,
        alias_mutation,
        boolean_alias,
        bound_mutator,
        class_mutation_before_binding,
        decorated_definition_mutation,
        default_helper_mutation,
        dynamic_receiver,
        helper_mutation,
        indexed_mutator,
        indexed_returned_alias,
        literal_helper_mutation,
        nested_append,
        nested_closure,
        nested_class_mutation,
        nested_default_helper,
        nested_helper,
        nested_wrapper_mutation,
        nested_update,
        operator_mutator,
        popped_alias,
        reflected_mutator,
        returned_alias,
        unbound_mutator,
        unpacked_alias,
        wrapped_helper_mutation,
        *callback_provenance_mutations,
        *dispatcher_provenance_mutations,
        *implicit_decorator_mutations,
        *iterator_call_aliases,
        *iterator_callback_mutations,
        *named_iterator_call_aliases,
        *qualified_mutators,
        *retained_wrapper_writes,
        *stdlib_callback_mutations,
        *transformed_qualified_calls,
        *wrapped_builtin_aliases,
        comprehension_helper_mutation,
    ):
        try:
            scanner._manifest_ast_pointers(unresolved_mutation, {})
        except scanner.DiscoveryError:
            continue
        pytest.fail(f"mutation repro escaped:\n{ast.unparse(unresolved_mutation.tree)}")
    assert scanner._manifest_ast_pointers(nested_default_mutation, {}) == {
        "function:build_manifest/hidden",
        "function:build_manifest/hidden/child",
        "function:build_manifest/known",
    }
    postponed_annotation = _python_module(
        "from __future__ import annotations\n\n"
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    def inner(value: payload.update({"invented": {"child": 1}})):\n'
        "        return value\n"
        "    return payload\n"
    )
    assert scanner._manifest_ast_pointers(postponed_annotation, {}) == {
        "function:build_manifest/known"
    }
    class_local_binding = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    class Inner:\n"
        '        payload = {"class_only": {"child": 1}}\n'
        "    return payload\n"
    )
    assert scanner._manifest_ast_pointers(class_local_binding, {}) == {
        "function:build_manifest/known"
    }
    class_local_mutation = _python_module(
        "class Helper:\n"
        "    def touch(self, value):\n"
        '        value["class_only"] = {"child": 1}\n\n'
        "helper = Helper()\n\n"
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        "    class Inner:\n"
        '        payload = {"local": 1}\n'
        "        helper.touch(payload)\n"
        "    return payload\n"
    )
    assert scanner._manifest_ast_pointers(class_local_mutation, {}) == {
        "function:build_manifest/known"
    }
    conditional_class_binding = _python_module(
        'manifest = {"known": 1}\n'
        "flag = False\n\n"
        "class Inner:\n"
        "    if flag:\n"
        '        manifest = {"class_only": 1}\n'
        '    manifest.update({"hidden": {"child": 1}})\n'
    )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(conditional_class_binding, {})
    postponed_variable_annotation = _python_module(
        "from __future__ import annotations\n\n"
        'manifest = {"known": 1}\n'
        'field: manifest.update({"invented": {"child": 1}})\n'
    )
    assert scanner._manifest_ast_pointers(postponed_variable_annotation, {}) == {
        "assignment:module:manifest/known"
    }
    local_variable_annotation = _python_module(
        "def build_manifest():\n"
        '    payload = {"known": 1}\n'
        '    field: payload.update({"invented": {"child": 1}})\n'
        "    return payload\n"
    )
    assert scanner._manifest_ast_pointers(local_variable_annotation, {}) == {
        "function:build_manifest/known"
    }
    scalar_constructor_dependencies = _python_module(
        "from pathlib import Path\n\n"
        "class Track:\n"
        "    samples: list[int]\n\n"
        "def registry(path: Path) -> dict[str, Track]:\n"
        "    return {}\n\n"
        "def load(run_dir: str | Path) -> tuple[list[Track], str | None]:\n"
        "    run = Path(run_dir)\n"
        "    reg = registry(run)\n"
        "    tracks: dict[str, Track] = {}\n"
        "    run_id: str | None = None\n"
        "    for item in []:\n"
        "        tr = tracks.get(item)\n"
        "        if tr is None:\n"
        "            tr = Track()\n"
        "            tracks[item] = tr\n"
        "        tr.samples.append(1)\n"
        "    return list(tracks.values()), run_id\n\n"
        "def build_manifest(run_dir: str | Path):\n"
        "    tracks, run_id = load(run_dir)\n"
        '    return {"run_id": run_id}\n'
    )
    dependency_functions, dependency_assignments = _function_registry(
        scalar_constructor_dependencies
    )
    assert scanner._manifest_ast_pointers(
        scalar_constructor_dependencies,
        dependency_functions,
        dependency_assignments,
    ) == {"function:build_manifest/run_id"}
    module_definition_time_mutations = (
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Holder:\n"
            "    def decorate(self, cls):\n"
            '        manifest["hidden"] = {"child": 1}\n'
            "        return cls\n\n"
            "holder = Holder()\n\n"
            "@holder.decorate\n"
            "class Inner:\n"
            "    pass\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "def factory():\n"
            "    def decorate(cls):\n"
            '        manifest["hidden"] = {"child": 1}\n'
            "        return cls\n"
            "    return decorate\n\n"
            "@factory()\n"
            "class Inner:\n"
            "    pass\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "def decorate(cls):\n"
            '    manifest["hidden"] = {"child": 1}\n'
            "    return cls\n\n"
            "alias = decorate\n\n"
            "@alias\n"
            "class Inner:\n"
            "    pass\n"
        ),
        _python_module(
            "import json\n\n"
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def dumps(self, value):\n"
            '        value["hidden"] = {"child": 1}\n'
            "        return object\n\n"
            "json: json.dumps(manifest) = Helper()\n"
        ),
        _python_module(
            "import json\n\n"
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def dumps(self, value):\n"
            '        value["hidden"] = {"child": 1}\n'
            "        return object\n\n"
            "def inner(value=(json := Helper())) -> json.dumps(manifest):\n"
            "    return value\n"
        ),
        _python_module(
            "import json\n\n"
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def decorate(self, function):\n"
            "        return function\n"
            "    def dumps(self, value):\n"
            '        value["hidden"] = {"child": 1}\n'
            "        return object\n\n"
            "@(json := Helper()).decorate\n"
            "def inner(value: json.dumps(manifest)):\n"
            "    return value\n"
        ),
        _python_module(
            'manifest = {"known": 1}\nbox = [manifest]\nbox[0]["hidden"] = {"child": 1}\n'
        ),
        _python_module(
            'manifest = {"known": 1}\n'
            "box = [manifest]\n\n"
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value[0]["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n"
            "box: tuple = (helper.touch(box), [])\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n'
            "box = [manifest]\n\n"
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value[0]["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n"
            "result = (helper.touch(box), (box := []))\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value[0]["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n"
            "result = ((box := [manifest]), helper.touch(box))\n"
        ),
        _python_module(
            "from external_decorators import decorate\n\n"
            'manifest = {"known": 1}\n\n'
            "@decorate\n"
            "class Inner:\n"
            "    value = manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def touch(self, value):\n"
            '        value[0]["hidden"] = {"child": 1}\n\n'
            "helper = Helper()\n\n"
            "def build_manifest():\n"
            "    box = [manifest]\n"
            "    helper.touch(box)\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Helper:\n"
            "    def mutate(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "helper = Helper()\n\n"
            "def build_manifest():\n"
            "    helper.mutate()\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Base:\n"
            "    def __init_subclass__(cls):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Inner(Base):\n"
            "    pass\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Meta(type):\n"
            "    def __new__(cls, name, bases, namespace):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return super().__new__(cls, name, bases, namespace)\n\n"
            "class Inner(metaclass=Meta):\n"
            "    pass\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Descriptor:\n"
            "    def __set_name__(self, owner, name):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Inner:\n"
            "    value = Descriptor()\n"
        ),
        _python_module(
            "from dataclasses import field\n\n"
            'manifest = {"known": 1}\n\n'
            "class Descriptor:\n"
            "    def __set_name__(self, owner, name):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Inner:\n"
            "    value = field(default=Descriptor())\n"
        ),
        _python_module(
            "from dataclasses import field as data_field\n\n"
            'manifest = {"known": 1}\n\n'
            "class Descriptor:\n"
            "    def __set_name__(self, owner, name):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Inner:\n"
            "    value = data_field(default=Descriptor())\n"
        ),
        _python_module(
            "import dataclasses\n\n"
            'manifest = {"known": 1}\n\n'
            "class Descriptor:\n"
            "    def __set_name__(self, owner, name):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Inner:\n"
            "    value = dataclasses.field(default=Descriptor())\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "def callback(_, value=manifest):\n"
            '    value.update({"hidden": {"child": 1}})\n\n'
            "list(map(callback, [0]))\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Item:\n"
            "    def __lt__(self, other):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return False\n\n"
            "max(Item(), Item())\n"
        ),
        _python_module(
            "from dataclasses import field\n\n"
            'manifest = {"known": 1}\n\n'
            "def make_factory():\n"
            '    manifest.update({"hidden": {"child": 1}})\n'
            "    return lambda: None\n\n"
            "class Inner:\n"
            "    value = field(default_factory=make_factory())\n"
        ),
        _python_module(
            "import itertools\n\n"
            'manifest = {"known": 1}\n\n'
            "class Item:\n"
            "    def __add__(self, other):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return self\n\n"
            "list(itertools.accumulate([Item(), Item()]))\n"
        ),
        _python_module(
            "import itertools\n\n"
            'manifest = {"known": 1}\n\n'
            "class Item:\n"
            "    def __eq__(self, other):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return False\n\n"
            "groups = itertools.groupby([Item(), Item()])\n"
            "list((key, list(group)) for key, group in groups)\n"
        ),
        _python_module(
            "def make_payload():\n"
            '    return {"known": 1}\n\n'
            "manifest = make_payload()\n\n"
            "def build_manifest():\n"
            "    return manifest\n\n"
            "class Item:\n"
            "    def __lt__(self, other):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return False\n\n"
            "max(Item(), Item())\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "Inner()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "if True:\n"
            "    Alias = Inner\n\n"
            "Alias()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "(Alias := Inner)\n"
            "Alias()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "try:\n"
            "    Alias = Inner\n"
            "except Exception:\n"
            "    Alias = Inner\n\n"
            "Alias()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "for Alias in [Inner]:\n"
            "    pass\n\n"
            "Alias()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "match Inner:\n"
            "    case Alias:\n"
            "        pass\n\n"
            "Alias()\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __new__(cls):\n"
            '        manifest.update({"hidden": {"child": 1}})\n'
            "        return super().__new__(cls)\n\n"
            "constructors = [Inner]\n"
            "constructors[0]()\n"
        ),
        _python_module(
            "from dataclasses import dataclass, field\n\n"
            'manifest = {"known": 1}\n\n'
            "def factory():\n"
            '    manifest.update({"hidden": {"child": 1}})\n'
            "    return 0\n\n"
            "@dataclass\n"
            "class Inner:\n"
            "    value: int = field(default_factory=factory)\n\n"
            "Alias = Inner\n"
            "Alias()\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self, ignored):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "def identity(value):\n"
            "    return value\n\n"
            "identity(Inner)(0)\n\n"
            "def build_manifest():\n"
            "    return manifest\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self, ignored):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "def identity(value):\n"
            "    return value\n\n"
            "constructor = identity(Inner)\n"
            "constructor(0)\n"
        ),
        _python_module(
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self, ignored):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "class Holder:\n"
            "    Inner = Inner\n\n"
            "Holder.Inner(0)\n"
        ),
        _python_module(
            "class Helper:\n"
            "    def run(self, ignored):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "helper = Helper()\n"
            'manifest = {"known": 1}\n'
            "helper.run(0)\n"
        ),
        _python_module(
            "from functools import partial\n\n"
            'manifest = {"known": 1}\n\n'
            "class Inner:\n"
            "    def __init__(self, ignored):\n"
            '        manifest.update({"hidden": {"child": 1}})\n\n'
            "partial(Inner)(0)\n"
        ),
    )
    for unresolved_module_mutation in module_definition_time_mutations:
        try:
            scanner._manifest_ast_pointers(unresolved_module_mutation, {})
        except scanner.DiscoveryError:
            continue
        pytest.fail(
            f"module mutation repro escaped:\n{ast.unparse(unresolved_module_mutation.tree)}"
        )
    imported_helper = _python_module(
        'GLOBAL = {"known": 1}\n\n'
        "BOX = [GLOBAL]\n\n"
        "def inner():\n"
        "    return GLOBAL\n\n"
        "def make_payload():\n"
        "    return inner()\n\n"
        "def mutate():\n"
        '    GLOBAL.update({"hidden": {"child": 1}})\n\n'
        "def effect():\n"
        "    mutate()\n\n"
        "def default_effect(value=GLOBAL):\n"
        '    value.update({"hidden": {"child": 1}})\n\n'
        "def kw_default_effect(*, value=GLOBAL):\n"
        '    value.update({"hidden": {"child": 1}})\n\n'
        "def boxed_effect(value=BOX[0]):\n"
        '    value.update({"hidden": {"child": 1}})\n\n'
        "def delegated_default_effect():\n"
        "    default_effect()\n\n"
        "class Inner:\n"
        "    def __init__(self, ignored):\n"
        '        GLOBAL.update({"hidden": {"child": 1}})\n\n'
        "Alias = Inner\n",
        path="package/helper.py",
        module="package.helper",
    )
    imported_consumer = _python_module(
        "from .helper import make_payload as renamed\n\n"
        "manifest = renamed()\n\n"
        "def build_manifest():\n"
        "    return manifest\n\n"
        "class Item:\n"
        "    def __lt__(self, other):\n"
        '        manifest.update({"hidden": {"child": 1}})\n'
        "        return False\n\n"
        "max(Item(), Item())\n",
        path="package/consumer.py",
        module="package.consumer",
    )
    imported_constructor_consumer = _python_module(
        "from .helper import GLOBAL as manifest, Alias as Constructor\n\n"
        "Constructor(0)\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/constructor_consumer.py",
        module="package.constructor_consumer",
    )
    qualified_helper_consumer = _python_module(
        "import package.helper as helper_module\n\n"
        "manifest = helper_module.make_payload()\n\n"
        "def build_manifest():\n"
        "    return manifest\n\n"
        "class Item:\n"
        "    def __lt__(self, other):\n"
        '        manifest.update({"hidden": {"child": 1}})\n'
        "        return False\n\n"
        "max(Item(), Item())\n",
        path="package/qualified_helper_consumer.py",
        module="package.qualified_helper_consumer",
    )
    qualified_constructor_consumer = _python_module(
        "import package.helper as helper_module\n"
        "from .helper import GLOBAL as manifest\n\n"
        "helper_module.Alias(0)\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/qualified_constructor_consumer.py",
        module="package.qualified_constructor_consumer",
    )
    imported_mutation_consumer = _python_module(
        "from .helper import GLOBAL as manifest, effect as run\n\n"
        "run()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/mutation_consumer.py",
        module="package.mutation_consumer",
    )
    qualified_mutation_consumer = _python_module(
        "import package.helper as helper_module\n"
        "from .helper import GLOBAL as manifest\n\n"
        "helper_module.effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/qualified_mutation_consumer.py",
        module="package.qualified_mutation_consumer",
    )
    rebound_mutation_consumer = _python_module(
        "from .helper import GLOBAL as source, effect\n\n"
        "manifest = source\n"
        'source = {"decoy": 1}\n'
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/rebound_mutation_consumer.py",
        module="package.rebound_mutation_consumer",
    )
    qualified_rebound_mutation_consumer = _python_module(
        "import package.helper as helper_module\n"
        "from .helper import GLOBAL as source\n\n"
        "manifest = source\n"
        'source = {"decoy": 1}\n'
        "helper_module.effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/qualified_rebound_mutation_consumer.py",
        module="package.qualified_rebound_mutation_consumer",
    )
    nested_rebound_mutation_consumer = _python_module(
        "from .helper import GLOBAL as source, effect\n\n"
        "items = [source]\n"
        'source = {"decoy": 1}\n'
        "effect()\n\n"
        "def build_manifest():\n"
        '    return {"items": items}\n',
        path="package/nested_rebound_mutation_consumer.py",
        module="package.nested_rebound_mutation_consumer",
    )
    default_mutation_consumers = tuple(
        _python_module(
            f"from .helper import GLOBAL as manifest, {helper_name} as run\n\n"
            "run()\n\n"
            "def build_manifest():\n"
            "    return manifest\n",
            path=f"package/{module_name}.py",
            module=f"package.{module_name}",
        )
        for module_name, helper_name in (
            ("default_mutation_consumer", "default_effect"),
            ("kw_default_mutation_consumer", "kw_default_effect"),
            ("boxed_default_mutation_consumer", "boxed_effect"),
            ("delegated_default_mutation_consumer", "delegated_default_effect"),
        )
    )
    imported_functions, imported_assignments = _function_registry(
        *default_mutation_consumers,
        imported_consumer,
        imported_constructor_consumer,
        imported_helper,
        imported_mutation_consumer,
        nested_rebound_mutation_consumer,
        qualified_constructor_consumer,
        qualified_helper_consumer,
        qualified_mutation_consumer,
        qualified_rebound_mutation_consumer,
        rebound_mutation_consumer,
    )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(
            imported_consumer,
            imported_functions,
            imported_assignments,
        )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(
            imported_constructor_consumer,
            imported_functions,
            imported_assignments,
        )
    for qualified_consumer in (
        qualified_constructor_consumer,
        qualified_helper_consumer,
        qualified_mutation_consumer,
    ):
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(
                qualified_consumer,
                imported_functions,
                imported_assignments,
            )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(
            imported_mutation_consumer,
            imported_functions,
            imported_assignments,
        )
    for origin_alias_consumer in (
        *default_mutation_consumers,
        nested_rebound_mutation_consumer,
        qualified_rebound_mutation_consumer,
        rebound_mutation_consumer,
    ):
        try:
            scanner._manifest_ast_pointers(
                origin_alias_consumer,
                imported_functions,
                imported_assignments,
            )
        except scanner.DiscoveryError:
            continue
        pytest.fail(f"origin alias mutation escaped: {origin_alias_consumer.module}")
    rebound_default_helper = _python_module(
        'GLOBAL = {"known": 1}\n'
        "EXPORTED = GLOBAL\n\n"
        "def effect(value=GLOBAL):\n"
        '    value.update({"hidden": {"child": 1}})\n\n'
        'GLOBAL = {"decoy": 1}\n',
        path="package/rebound_default_helper.py",
        module="package.rebound_default_helper",
    )
    rebound_default_consumer = _python_module(
        "from .rebound_default_helper import EXPORTED as manifest, effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/rebound_default_consumer.py",
        module="package.rebound_default_consumer",
    )
    rebound_functions, rebound_assignments = _function_registry(
        rebound_default_consumer,
        rebound_default_helper,
    )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(
            rebound_default_consumer,
            rebound_functions,
            rebound_assignments,
        )
    qualified_default_values = _python_module(
        'GLOBAL = {"known": 1}\n',
        path="package/qualified_default_values.py",
        module="package.qualified_default_values",
    )
    qualified_default_consumer = _python_module(
        "from .qualified_default_values import GLOBAL as manifest\n"
        "from .qualified_default_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/qualified_default_consumer.py",
        module="package.qualified_default_consumer",
    )
    for qualified_default_expression in (
        "values.GLOBAL",
        "ALIAS",
        'BOX["item"]',
        'BOX.get("item")',
        'getattr(values, "GLOBAL")',
        'getattr(values, "GLOBAL", None)',
        'vars(values)["GLOBAL"]',
        'vars(values).get("GLOBAL")',
        'values.__dict__["GLOBAL"]',
        'values.__dict__.get("GLOBAL")',
        'ACCESS(values, "GLOBAL")',
        'NAMESPACE(values)["GLOBAL"]',
        'NS["GLOBAL"]',
        'NS.get("GLOBAL")',
        'NS.__getitem__("GLOBAL")',
        'GET("GLOBAL")',
        'MODULE_DICT["GLOBAL"]',
        'MODULE_DICT.__getitem__("GLOBAL")',
        'values.__getattribute__("GLOBAL")',
        'values.__dict__.__getitem__("GLOBAL")',
        'MODULE_ACCESS("GLOBAL")',
        'MODULE_ITEM("GLOBAL")',
        'ACCESSORS["module"]("GLOBAL")',
        'ACCESSORS["dict"]("GLOBAL")',
    ):
        qualified_default_helper = _python_module(
            "import package.qualified_default_values as values\n\n"
            "ALIAS = values.GLOBAL\n"
            'BOX = {"item": values.GLOBAL}\n'
            "ACCESS = getattr\n"
            "NAMESPACE = vars\n"
            "NS = vars(values)\n"
            "GET = NS.get\n"
            "MODULE_DICT = values.__dict__\n\n"
            "MODULE_ACCESS = values.__getattribute__\n"
            "MODULE_ITEM = values.__dict__.__getitem__\n"
            'ACCESSORS = {"module": MODULE_ACCESS, "dict": MODULE_ITEM}\n\n'
            f"def effect(value={qualified_default_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/qualified_default_helper.py",
            module="package.qualified_default_helper",
        )
        qualified_default_orders = (
            (
                qualified_default_values,
                qualified_default_helper,
                qualified_default_consumer,
            ),
            (
                qualified_default_consumer,
                qualified_default_values,
                qualified_default_helper,
            ),
            (
                qualified_default_helper,
                qualified_default_consumer,
                qualified_default_values,
            ),
        )
        for qualified_default_order in qualified_default_orders:
            qualified_functions, qualified_assignments = _function_registry(
                *qualified_default_order
            )
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    qualified_default_consumer,
                    qualified_functions,
                    qualified_assignments,
                )
    ordered_default_values = _python_module(
        'GLOBAL = {"known": 1}\nOTHER = {"other": 1}\n',
        path="package/ordered_default_values.py",
        module="package.ordered_default_values",
    )
    ordered_default_consumer = _python_module(
        "from .ordered_default_values import OTHER as manifest\n"
        "from .ordered_default_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/ordered_default_consumer.py",
        module="package.ordered_default_consumer",
    )
    for ordered_default_source in (
        "import package.ordered_default_values as values\n\n"
        "ACCESS = getattr\n\n"
        "def fake(obj, name):\n"
        "    return obj.OTHER\n\n"
        'def effect(first=(ACCESS := fake), value=ACCESS(values, "GLOBAL")):\n'
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.ordered_default_values as values\n\n"
        'BOX = {"item": values.GLOBAL}\n\n'
        'def effect(first=BOX.update({"item": values.OTHER}), value=BOX["item"]):\n'
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.ordered_default_values as values\n\n"
        'BOX = {"item": values.GLOBAL}\n\n'
        "def replace():\n"
        '    BOX["item"] = values.OTHER\n\n'
        'def effect(first=replace(), value=BOX["item"]):\n'
        '    value.update({"hidden": {"child": 1}})\n',
    ):
        ordered_default_helper = _python_module(
            ordered_default_source,
            path="package/ordered_default_helper.py",
            module="package.ordered_default_helper",
        )
        for ordered_default_order in (
            (
                ordered_default_values,
                ordered_default_helper,
                ordered_default_consumer,
            ),
            (
                ordered_default_consumer,
                ordered_default_values,
                ordered_default_helper,
            ),
            (
                ordered_default_helper,
                ordered_default_consumer,
                ordered_default_values,
            ),
        ):
            ordered_functions, ordered_assignments = _function_registry(*ordered_default_order)
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    ordered_default_consumer,
                    ordered_functions,
                    ordered_assignments,
                )
    factory_default_values = _python_module(
        'OTHER = {"other": 1}\n',
        path="package/factory_default_values.py",
        module="package.factory_default_values",
    )
    factory_default_consumer = _python_module(
        "from .factory_default_values import OTHER as manifest\n"
        "from .factory_default_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/factory_default_consumer.py",
        module="package.factory_default_consumer",
    )
    for factory_default_source in (
        "import package.factory_default_values as values\n\n"
        "def factory():\n"
        "    return values.OTHER\n\n"
        "def effect(value=factory()):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.factory_default_values as values\n\n"
        "def factory():\n"
        "    return values.OTHER\n\n"
        "ALIAS = factory\n\n"
        "def effect(value=ALIAS()):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.factory_default_values as values\n\n"
        "def factory():\n"
        "    return values.OTHER\n\n"
        "def delegated():\n"
        "    return factory()\n\n"
        "def effect(value=delegated()):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.factory_default_values as values\n\n"
        "class Factory:\n"
        "    def __new__(cls):\n"
        "        return values.OTHER\n\n"
        "def effect(value=Factory()):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        "import package.factory_default_values as values\n\n"
        "def factory():\n"
        "    return values.OTHER\n\n"
        'def effect(value={"item": factory()}):\n'
        '    value["item"].update({"hidden": {"child": 1}})\n',
    ):
        factory_default_helper = _python_module(
            factory_default_source,
            path="package/factory_default_helper.py",
            module="package.factory_default_helper",
        )
        for factory_default_order in (
            (
                factory_default_values,
                factory_default_helper,
                factory_default_consumer,
            ),
            (
                factory_default_consumer,
                factory_default_values,
                factory_default_helper,
            ),
            (
                factory_default_helper,
                factory_default_consumer,
                factory_default_values,
            ),
        ):
            factory_functions, factory_assignments = _function_registry(*factory_default_order)
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    factory_default_consumer,
                    factory_functions,
                    factory_assignments,
                )
    dynamic_default_consumer = _python_module(
        "from .dynamic_default_helper import OTHER as manifest, effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/dynamic_default_consumer.py",
        module="package.dynamic_default_consumer",
    )
    for dynamic_default_setup, dynamic_default_expression in (
        ("", 'getattr(sys.modules[__name__], "OTHER")'),
        ("", 'sys.modules[__name__].__dict__["OTHER"]'),
        ("", 'sys.modules[__name__].__dict__.get("OTHER")'),
        (
            'UNKNOWN = getattr(sys.modules[__name__], "OTHER")\n\n',
            "UNKNOWN",
        ),
    ):
        dynamic_default_helper = _python_module(
            "import sys\n\n"
            'OTHER = {"other": 1}\n'
            f"{dynamic_default_setup}"
            f"def effect(value={dynamic_default_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/dynamic_default_helper.py",
            module="package.dynamic_default_helper",
        )
        for dynamic_default_order in (
            (dynamic_default_helper, dynamic_default_consumer),
            (dynamic_default_consumer, dynamic_default_helper),
        ):
            dynamic_functions, dynamic_assignments = _function_registry(*dynamic_default_order)
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    dynamic_default_consumer,
                    dynamic_functions,
                    dynamic_assignments,
                )
    mixed_default_values = _python_module(
        'KNOWN = {"known": 1}\nOTHER = {"other": 1}\n',
        path="package/mixed_default_values.py",
        module="package.mixed_default_values",
    )
    mixed_default_factory = _python_module(
        "import package.mixed_default_values as values\n\ndef make():\n    return values.OTHER\n",
        path="package/mixed_default_factory.py",
        module="package.mixed_default_factory",
    )
    mixed_default_consumer = _python_module(
        "from .mixed_default_values import KNOWN as decoy, OTHER as manifest\n"
        "from .mixed_default_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/mixed_default_consumer.py",
        module="package.mixed_default_consumer",
    )
    for mixed_default_expression in (
        "values.KNOWN and makers.make()",
        "makers.make() or values.KNOWN",
        "makers.make() if FLAG else values.KNOWN",
        "(values.KNOWN, makers.make())[1]",
    ):
        mixed_default_helper = _python_module(
            "import package.mixed_default_factory as makers\n"
            "import package.mixed_default_values as values\n\n"
            "FLAG = True\n\n"
            f"def effect(value={mixed_default_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/mixed_default_helper.py",
            module="package.mixed_default_helper",
        )
        for mixed_default_order in (
            (
                mixed_default_values,
                mixed_default_factory,
                mixed_default_helper,
                mixed_default_consumer,
            ),
            (
                mixed_default_consumer,
                mixed_default_values,
                mixed_default_helper,
                mixed_default_factory,
            ),
            (
                mixed_default_helper,
                mixed_default_factory,
                mixed_default_consumer,
                mixed_default_values,
            ),
        ):
            mixed_functions, mixed_assignments = _function_registry(*mixed_default_order)
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    mixed_default_consumer,
                    mixed_functions,
                    mixed_assignments,
                )
    qualified_class_values = _python_module(
        'OTHER = {"other": 1}\n\nclass Factory:\n    def __new__(cls):\n        return OTHER\n',
        path="package/qualified_class_values.py",
        module="package.qualified_class_values",
    )
    qualified_class_bridge = _python_module(
        "from .qualified_class_values import Factory as Alias\n\n"
        "class Holder:\n"
        "    Inner = Alias\n"
        "    ITEMS = [Alias]\n"
        "    NESTED = [[Alias]]\n\n"
        "BOX = [Alias]\n"
        "NESTED = [[Alias]]\n",
        path="package/qualified_class_bridge.py",
        module="package.qualified_class_bridge",
    )
    qualified_class_consumer = _python_module(
        "from .qualified_class_values import OTHER as manifest\n"
        "from .qualified_class_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/qualified_class_consumer.py",
        module="package.qualified_class_consumer",
    )
    for qualified_class_setup, qualified_class_expression in (
        ("", "values.Factory"),
        ("", "[values.Factory][0]"),
        ("BOX = [values.Factory]\n\n", "BOX[0]"),
        ("BOX = [[values.Factory]]\n\n", "BOX[0][0]"),
        ("", "bridge.Alias"),
        ("", "bridge.BOX[0]"),
        ("", "bridge.NESTED[0][0]"),
        ("", "bridge.Holder.Inner"),
        ("", "bridge.Holder.ITEMS[0]"),
        ("", "bridge.Holder.NESTED[0][0]"),
    ):
        qualified_class_helper = _python_module(
            "import package.qualified_class_bridge as bridge\n"
            "import package.qualified_class_values as values\n\n"
            f"{qualified_class_setup}"
            f"def effect(value={qualified_class_expression}):\n"
            "    value.review_marker = 1\n",
            path="package/qualified_class_helper.py",
            module="package.qualified_class_helper",
        )
        for qualified_class_order in (
            (
                qualified_class_values,
                qualified_class_bridge,
                qualified_class_helper,
                qualified_class_consumer,
            ),
            (
                qualified_class_consumer,
                qualified_class_values,
                qualified_class_helper,
                qualified_class_bridge,
            ),
            (
                qualified_class_helper,
                qualified_class_bridge,
                qualified_class_consumer,
                qualified_class_values,
            ),
        ):
            qualified_class_functions, qualified_class_assignments = _function_registry(
                *qualified_class_order
            )
            assert scanner._manifest_ast_pointers(
                qualified_class_consumer,
                qualified_class_functions,
                qualified_class_assignments,
            ) == {"function:build_manifest/other"}
    qualified_class_call_helper = _python_module(
        "import package.qualified_class_bridge as bridge\n\n"
        "def effect(value=bridge.Alias()):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        path="package/qualified_class_helper.py",
        module="package.qualified_class_helper",
    )
    qualified_class_functions, qualified_class_assignments = _function_registry(
        qualified_class_values,
        qualified_class_bridge,
        qualified_class_call_helper,
        qualified_class_consumer,
    )
    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(
            qualified_class_consumer,
            qualified_class_functions,
            qualified_class_assignments,
        )
    for temporal_class_bridge_source, temporal_class_expression in (
        (
            "from .qualified_class_values import Factory, OTHER\n\n"
            "Alias = OTHER\n\n"
            "class Holder:\n"
            "    Inner = Alias\n\n"
            "Alias = Factory\n",
            "bridge.Holder.Inner",
        ),
        (
            "from .qualified_class_values import Factory, OTHER\n\n"
            "Alias = OTHER\n"
            "BOX = [Alias]\n"
            "Alias = Factory\n",
            "bridge.BOX[0]",
        ),
    ):
        temporal_class_bridge = _python_module(
            temporal_class_bridge_source,
            path="package/qualified_class_bridge.py",
            module="package.qualified_class_bridge",
        )
        temporal_class_helper = _python_module(
            "import package.qualified_class_bridge as bridge\n\n"
            f"def effect(value={temporal_class_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/qualified_class_helper.py",
            module="package.qualified_class_helper",
        )
        for temporal_class_order in (
            (
                qualified_class_values,
                temporal_class_bridge,
                temporal_class_helper,
                qualified_class_consumer,
            ),
            (
                qualified_class_consumer,
                temporal_class_helper,
                qualified_class_values,
                temporal_class_bridge,
            ),
            (
                temporal_class_bridge,
                qualified_class_consumer,
                temporal_class_helper,
                qualified_class_values,
            ),
        ):
            temporal_class_functions, temporal_class_assignments = _function_registry(
                *temporal_class_order
            )
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    qualified_class_consumer,
                    temporal_class_functions,
                    temporal_class_assignments,
                )
    retained_class_bridge = _python_module(
        "from .qualified_class_values import Factory, OTHER\n\n"
        "Alias = Factory\n\n"
        "class Holder:\n"
        "    Inner = Alias\n\n"
        "Alias = OTHER\n",
        path="package/qualified_class_bridge.py",
        module="package.qualified_class_bridge",
    )
    retained_class_helper = _python_module(
        "import package.qualified_class_bridge as bridge\n\n"
        "def effect(value=bridge.Holder.Inner):\n"
        "    value.review_marker = 1\n",
        path="package/qualified_class_helper.py",
        module="package.qualified_class_helper",
    )
    for retained_class_order in (
        (
            qualified_class_values,
            retained_class_bridge,
            retained_class_helper,
            qualified_class_consumer,
        ),
        (
            qualified_class_consumer,
            retained_class_helper,
            retained_class_bridge,
            qualified_class_values,
        ),
        (
            retained_class_bridge,
            qualified_class_values,
            qualified_class_consumer,
            retained_class_helper,
        ),
    ):
        retained_class_functions, retained_class_assignments = _function_registry(
            *retained_class_order
        )
        assert scanner._manifest_ast_pointers(
            qualified_class_consumer,
            retained_class_functions,
            retained_class_assignments,
        ) == {"function:build_manifest/other"}
    for post_class_mutation in (
        "Holder.Inner = OTHER\n",
        'setattr(Holder, "Inner", OTHER)\n',
        "def replace():\n    Holder.Inner = OTHER\n\nreplace()\n",
        "Holder.ITEMS[0] = OTHER\n",
        "Holder.ITEMS.clear()\nHolder.ITEMS.append(OTHER)\n",
        "Alias = Holder\nAlias.Inner = OTHER\n",
    ):
        mutated_class_bridge = _python_module(
            "from .qualified_class_values import Factory, OTHER\n\n"
            "class Holder:\n"
            "    Inner = Factory\n"
            "    ITEMS = [Factory]\n\n"
            f"{post_class_mutation}",
            path="package/qualified_class_bridge.py",
            module="package.qualified_class_bridge",
        )
        mutated_class_helper = _python_module(
            "import package.qualified_class_bridge as bridge\n\n"
            "def effect(value=bridge.Holder.Inner):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/qualified_class_helper.py",
            module="package.qualified_class_helper",
        )
        for mutated_class_order in (
            (
                qualified_class_values,
                mutated_class_bridge,
                mutated_class_helper,
                qualified_class_consumer,
            ),
            (
                qualified_class_consumer,
                mutated_class_helper,
                mutated_class_bridge,
                qualified_class_values,
            ),
            (
                mutated_class_bridge,
                qualified_class_values,
                qualified_class_consumer,
                mutated_class_helper,
            ),
        ):
            mutated_class_functions, mutated_class_assignments = _function_registry(
                *mutated_class_order
            )
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    qualified_class_consumer,
                    mutated_class_functions,
                    mutated_class_assignments,
                )
    cross_module_class_owner = _python_module(
        "from .qualified_class_values import Factory\n\n"
        "class Holder:\n"
        "    Inner = Factory\n\n"
        "def marker():\n"
        "    pass\n\n"
        "def namespace():\n"
        "    return globals()\n",
        path="package/qualified_class_bridge.py",
        module="package.qualified_class_bridge",
    )
    cross_module_class_reexport = _python_module(
        "from .qualified_class_bridge import marker\n\nclass Holder:\n    pass\n",
        path="package/qualified_class_reexport.py",
        module="package.qualified_class_reexport",
    )
    cross_module_class_helper = _python_module(
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "GLOBAL = vars(bridge)\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "def namespace():\n"
        "    return GLOBAL\n\n"
        "def replace(cls):\n"
        "    cls.Inner = OTHER\n\n"
        "def leaf(cls):\n"
        "    cls.Inner = OTHER\n\n"
        "def outer(cls):\n"
        "    leaf(cls)\n\n"
        "def effect(value=bridge.Holder.Inner):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        path="package/qualified_class_helper.py",
        module="package.qualified_class_helper",
    )
    for cross_module_mutator_source in (
        "from .qualified_class_bridge import Holder as Alias\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = bridge.Holder\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "BOX = [bridge.Holder]\n"
        "BOX[0].Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "bridge.Holder.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "setattr(bridge.Holder, 'Inner', OTHER)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def replace(cls):\n"
        "    cls.Inner = OTHER\n\n"
        "replace(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "module = bridge or bridge\n"
        "Alias = module.Holder\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = getattr(bridge, 'Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = vars(bridge)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = bridge.__dict__['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "ACCESS = getattr\n"
        "Alias = ACCESS(bridge, 'Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "ACCESS = vars\n"
        "Alias = ACCESS(bridge)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = vars(bridge)\n"
        "ACCESS = namespace.get\n"
        "Alias = ACCESS('Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "Alias = identity(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "keep = identity\n"
        "Alias = keep(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "first = identity\n"
        "keep = first\n"
        "Alias = keep(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "keep = [identity][0]\n"
        "Alias = keep(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "keep = lambda value: value\n"
        "Alias = keep(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "import package.qualified_class_helper as helpers\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = helpers.identity(bridge.Holder)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "import package.qualified_class_helper as mutations\n\n"
        "mutations.replace(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer as call\n\n"
        "call(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "saved = outer\n"
        "outer = lambda value: None\n"
        "saved(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "saved = [outer]\n"
        "outer = lambda value: None\n"
        "saved[0](bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer as imported\n\n"
        "saved = imported\n"
        "imported = lambda value: None\n"
        "saved(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "def choose(value):\n"
        "    return value\n\n"
        "call = choose(outer)\n"
        "call(bridge.Holder)\n",
        "from functools import partial\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "call = partial(outer)\n"
        "call(bridge.Holder)\n",
        "from functools import partial\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def outer(prefix, cls):\n"
        "    cls.Inner = OTHER\n\n"
        "call = partial(outer, None)\n"
        "call(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "call = {'outer': outer}.get('outer')\n"
        "call(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_helper import outer\n\n"
        "class Ops:\n"
        "    call = outer\n\n"
        "Ops.call(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    def replace(self, cls):\n"
        "        cls.Inner = OTHER\n\n"
        "Ops().replace(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    def replace(self, cls):\n"
        "        cls.Inner = OTHER\n\n"
        "ops = Ops()\n"
        "replace = ops.replace\n"
        "replace(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    def replace(self, cls=bridge.Holder):\n"
        "        cls.Inner = OTHER\n\n"
        "Ops().replace()\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    @classmethod\n"
        "    def replace(cls, target=bridge.Holder):\n"
        "        target.Inner = OTHER\n\n"
        "Ops.replace()\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    @staticmethod\n"
        "    def replace(target=bridge.Holder):\n"
        "        target.Inner = OTHER\n\n"
        "Ops.replace()\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Base:\n"
        "    def replace(self, cls=bridge.Holder):\n"
        "        cls.Inner = OTHER\n\n"
        "class Sub(Base):\n"
        "    pass\n\n"
        "Sub().replace()\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Base:\n"
        "    def replace(self, cls):\n"
        "        cls.Inner = OTHER\n\n"
        "class Sub(Base):\n"
        "    pass\n\n"
        "Sub().replace(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "class Ops:\n"
        "    def replace(self, cls=bridge.Holder):\n"
        "        cls.Inner = OTHER\n\n"
        "    alias = replace\n\n"
        "Ops().alias()\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = {key: value for key, value in vars(bridge).items()}\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = dict(vars(bridge).items())\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = next(\n"
        "    value for key, value in vars(bridge).items() if key == 'Holder'\n"
        ")\n"
        "Alias.Inner = OTHER\n",
        "from collections import ChainMap\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = ChainMap(vars(bridge))\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from collections import UserDict\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = UserDict(vars(bridge))\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = dict(zip(vars(bridge).keys(), vars(bridge).values()))\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = dict(filter(lambda item: True, vars(bridge).items()))\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_helper import namespace\n"
        "from .qualified_class_values import OTHER\n\n"
        "ns = namespace()\n"
        "Alias = ns['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "GLOBAL = vars(bridge)\n\n"
        "def outer():\n"
        "    def inner():\n"
        "        return GLOBAL\n"
        "    return inner\n\n"
        "ns = outer()()\n"
        "Alias = ns['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def wrap(_):\n"
        "    return vars(bridge)\n\n"
        "ns = next(map(wrap, [None]))\n"
        "Alias = ns['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "GLOBAL = vars(bridge)\n\n"
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.ns = GLOBAL\n\n"
        "ns = Box().ns\n"
        "Alias = ns['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "def namespace():\n"
        "    return vars(import_module('package.qualified_class_bridge'))\n\n"
        "Alias = namespace()['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "def module_name():\n"
        "    return 'package.qualified_class_bridge'\n\n"
        "Alias = vars(import_module(module_name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "def module_name():\n"
        "    return 'package.qualified_class_bridge'\n\n"
        "name = module_name\n"
        "Alias = vars(import_module(name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from external import MODULE_NAME\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = vars(import_module(MODULE_NAME))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "def module_name():\n"
        "    return 'package.qualified_class_bridge'\n\n"
        "name = [module_name][0]\n"
        "Alias = vars(import_module(name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "module_name = lambda: 'package.qualified_class_bridge'\n"
        "Alias = vars(import_module(module_name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_values import OTHER\n\n"
        "def module_name():\n"
        "    return 'package.qualified_class_bridge'\n\n"
        "def imported_module():\n"
        "    return import_module(module_name())\n\n"
        "Alias = vars(imported_module())['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from external import module_name\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = vars(import_module(module_name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from external import module_name\n"
        "from .qualified_class_values import OTHER\n\n"
        "name = module_name\n"
        "Alias = vars(import_module(name()))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from external import module_name\n"
        "from .qualified_class_values import OTHER\n\n"
        "def decoy_module_name():\n"
        "    return 'package.qualified_class_reexport'\n\n"
        "name = {'pick': decoy_module_name, 'pick': module_name}['pick']()\n"
        "Alias = vars(import_module(name))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import importlib as il\n"
        "from .qualified_class_values import OTHER\n\n"
        "module = il.import_module('package.qualified_class_bridge')\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_values import OTHER\n\n"
        "module = __import__(\n"
        "    'package.qualified_class_bridge', fromlist=['Holder']\n"
        ")\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = marker.__globals__['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = getattr(marker, '__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "ACCESS = getattr\n"
        "Alias = ACCESS(marker, '__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = marker.__getattribute__('__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "ACCESS = marker.__getattribute__\n"
        "Alias = ACCESS('__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "ACCESS = [getattr][0]\n"
        "Alias = ACCESS(marker, '__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from external import ACCESS\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = ACCESS.__getattribute__(marker, '__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_reexport as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = bridge.marker.__globals__['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = object.__getattribute__(marker, '__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def namespace():\n"
        "    return getattr(marker, '__globals__')\n\n"
        "Alias = namespace()['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "Alias = identity(getattr(marker, '__globals__'))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def lookup(name):\n"
        "    return getattr(marker, '__globals__')[name]\n\n"
        "Alias = lookup('Holder')\n"
        "Alias.Inner = OTHER\n",
        "from external import NAMESPACE\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = NAMESPACE['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from external import lookup\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = lookup('Holder')\n"
        "Alias.Inner = OTHER\n",
        "from external import ACCESS\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = ACCESS('__globals__')['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from external import reflect\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = reflect(marker)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from external import reflect\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def namespace():\n"
        "    return reflect(marker)\n\n"
        "Alias = namespace()['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from external import attribute_name\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = getattr(marker, attribute_name())['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def namespace():\n"
        "    return marker.__globals__\n\n"
        "Alias = namespace()['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import sys\n"
        "from .qualified_class_values import OTHER\n\n"
        "modules = sys.modules\n"
        "Alias = vars(modules['package.qualified_class_bridge'])['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge\n"
        "import sys\n"
        "from .qualified_class_values import OTHER\n\n"
        "lookup = sys.modules.get\n"
        "Alias = vars(lookup('package.qualified_class_bridge'))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge\n"
        "import sys\n"
        "from .qualified_class_values import OTHER\n\n"
        "lookup = sys.modules.__getitem__\n"
        "Alias = vars(lookup('package.qualified_class_bridge'))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import inspect\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = vars(inspect.getmodule(marker))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "module = import_module(marker.__module__)\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import Holder\n"
        "from .qualified_class_values import OTHER\n\n"
        "marker = lambda: None\n"
        "Alias = marker.__globals__['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "module = import_module(identity(marker).__module__)\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import inspect\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def identity(value):\n"
        "    return value\n\n"
        "module = inspect.getmodule(identity(marker))\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from importlib import import_module\n"
        "from .qualified_class_bridge import marker\n"
        "from .qualified_class_values import OTHER\n\n"
        "def passthrough(function):\n"
        "    return function\n\n"
        "@passthrough\n"
        "def identity(value):\n"
        "    return value\n\n"
        "module = import_module(identity(marker).__module__)\n"
        "Alias = vars(module)['Holder']\n"
        "Alias.Inner = OTHER\n",
        "from .qualified_class_bridge import namespace\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = namespace()['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = vars(bridge) | {}\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = {**vars(bridge)}\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import copy\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = copy.copy(vars(bridge))\n"
        "Alias = namespace['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = vars(bridge)\n"
        "Alias = namespace.pop('Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "namespace = vars(bridge)\n"
        "Alias = namespace.setdefault('Holder', None)\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "lookup = bridge.__dict__.__getitem__\n"
        "Alias = lookup('Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "lookup = bridge.__getattribute__\n"
        "Alias = lookup('Holder')\n"
        "Alias.Inner = OTHER\n",
        "import operator\n"
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = operator.getitem(vars(bridge), 'Holder')\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from types import MappingProxyType\n"
        "from .qualified_class_values import OTHER\n\n"
        "Alias = MappingProxyType(vars(bridge))['Holder']\n"
        "Alias.Inner = OTHER\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def inner(cls):\n"
        "    cls.Inner = OTHER\n\n"
        "def outer(cls):\n"
        "    inner(cls)\n\n"
        "outer(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def inner(*, cls):\n"
        "    cls.Inner = OTHER\n\n"
        "def outer(cls):\n"
        "    inner(cls=cls)\n\n"
        "outer(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def inner(box):\n"
        "    box[0].Inner = OTHER\n\n"
        "def outer(cls):\n"
        "    inner([cls])\n\n"
        "outer(bridge.Holder)\n",
        "import package.qualified_class_bridge as bridge\n"
        "from .qualified_class_values import OTHER\n\n"
        "def inner(cls):\n"
        "    cls.Inner = OTHER\n\n"
        "def outer(cls=bridge.Holder):\n"
        "    inner(cls)\n\n"
        "outer()\n",
    ):
        cross_module_class_mutator = _python_module(
            cross_module_mutator_source,
            path="package/qualified_class_mutator.py",
            module="package.qualified_class_mutator",
        )
        for cross_module_class_order in (
            (
                qualified_class_values,
                cross_module_class_owner,
                cross_module_class_reexport,
                cross_module_class_mutator,
                cross_module_class_helper,
                qualified_class_consumer,
            ),
            (
                qualified_class_consumer,
                cross_module_class_helper,
                cross_module_class_mutator,
                cross_module_class_reexport,
                cross_module_class_owner,
                qualified_class_values,
            ),
            (
                cross_module_class_mutator,
                qualified_class_values,
                cross_module_class_reexport,
                qualified_class_consumer,
                cross_module_class_owner,
                cross_module_class_helper,
            ),
        ):
            cross_module_functions, cross_module_assignments = _function_registry(
                *cross_module_class_order
            )
            try:
                scanner._manifest_ast_pointers(
                    qualified_class_consumer,
                    cross_module_functions,
                    cross_module_assignments,
                )
            except scanner.DiscoveryError:
                pass
            else:
                pytest.fail(
                    "cross-module class mutation retained a stale default:\n"
                    f"{cross_module_mutator_source}"
                )
    early_victim = _python_module(
        "class Holder:\n    pass\n\ndef marker():\n    pass\n",
        path="package/_victim.py",
        module="package._victim",
    )
    late_victim = _python_module(
        "class Holder:\n    pass\n",
        path="package/z_victim.py",
        module="package.z_victim",
    )
    for unresolved_mutator_source in (
        "from external import candidate\n\ncandidate.changed = 1\n",
        "from external import getattr\n"
        "from ._victim import marker\n\n"
        "Alias = getattr(marker, '__globals__')['Holder']\n"
        "Alias.changed = 1\n",
        "from external import ACCESS\n"
        "from ._victim import marker\n\n"
        "Alias = ACCESS.__getattribute__(marker, '__globals__')['Holder']\n"
        "Alias.changed = 1\n",
    ):
        unresolved_mutator = _python_module(
            unresolved_mutator_source,
            path="package/a_mutator.py",
            module="package.a_mutator",
        )
        order_registry = scanner._module_assignment_registry(
            (late_victim, unresolved_mutator, early_victim)
        )
        for victim in (early_victim, late_victim):
            binding = order_registry[victim.module]["Holder"]
            assert len(binding) == 1 and isinstance(binding[0], scanner._ClassBinding)
            assert binding[0].invalidated, (
                f"unresolved mutation missed {victim.module}:\n{unresolved_mutator_source}"
            )
    known_owner = _python_module(
        "class Holder:\n    ITEMS = []\n\nclass Sibling:\n    pass\n",
        path="package/known_owner.py",
        module="package.known_owner",
    )
    known_bridge = _python_module(
        "from .known_owner import Holder as Alias\n\nclass BridgeDecoy:\n    pass\n",
        path="package/known_bridge.py",
        module="package.known_bridge",
    )
    for known_mutator_source in (
        "import package.known_owner as bridge\n\nbridge.Holder.changed = 1\n",
        "import package.known_bridge as bridge\n\nbridge.Alias.changed = 1\n",
        "import package.known_owner as bridge\n\nsetattr(bridge.Holder, 'changed', 1)\n",
        "import package.known_bridge as bridge\n\nsetattr(bridge.Alias, 'changed', 1)\n",
        "import package.known_owner as bridge\n\n"
        "ACCESS = setattr\n"
        "ACCESS(bridge.Holder, 'changed', 1)\n",
        "from builtins import delattr as ACCESS\n"
        "import package.known_bridge as bridge\n\n"
        "ACCESS(bridge.Alias, 'changed')\n",
        "import package.known_owner as bridge\n\n"
        "def change(cls):\n"
        "    cls.changed = 1\n\n"
        "change(bridge.Holder)\n",
        "import package.known_owner as bridge\n\nbridge.Holder.ITEMS.append(1)\n",
    ):
        known_mutator = _python_module(
            known_mutator_source,
            path="package/z_known_mutator.py",
            module="package.z_known_mutator",
        )
        for known_order in (
            (known_owner, known_bridge, known_mutator),
            (known_mutator, known_bridge, known_owner),
            (known_bridge, known_owner, known_mutator),
        ):
            known_registry = scanner._module_assignment_registry(known_order)
            holder = known_registry[known_owner.module]["Holder"]
            sibling = known_registry[known_owner.module]["Sibling"]
            decoy = known_registry[known_bridge.module]["BridgeDecoy"]
            assert len(holder) == 1 and isinstance(holder[0], scanner._ClassBinding)
            assert len(sibling) == 1 and isinstance(sibling[0], scanner._ClassBinding)
            assert len(decoy) == 1 and isinstance(decoy[0], scanner._ClassBinding)
            assert holder[0].invalidated, known_mutator_source
            assert not sibling[0].invalidated, known_mutator_source
            assert not decoy[0].invalidated, known_mutator_source
    for class_hook_source in (
        "from .qualified_class_values import Factory, OTHER\n\n"
        "def decorate(cls):\n"
        "    cls.Inner = OTHER\n"
        "    return cls\n\n"
        "@decorate\n"
        "class Holder:\n"
        "    Inner = Factory\n",
        "from .qualified_class_values import Factory, OTHER\n\n"
        "class Meta(type):\n"
        "    def __new__(mcls, name, bases, namespace):\n"
        "        namespace['Inner'] = OTHER\n"
        "        return super().__new__(mcls, name, bases, namespace)\n\n"
        "class Holder(metaclass=Meta):\n"
        "    Inner = Factory\n",
        "from .qualified_class_values import Factory, OTHER\n\n"
        "class Descriptor:\n"
        "    def __set_name__(self, owner, name):\n"
        "        owner.Inner = OTHER\n\n"
        "class Holder:\n"
        "    Inner = Factory\n"
        "    trigger = Descriptor()\n",
        "from .qualified_class_values import Factory, OTHER\n\n"
        "class Base:\n"
        "    def __init_subclass__(cls):\n"
        "        cls.Inner = OTHER\n\n"
        "class Holder(Base):\n"
        "    Inner = Factory\n",
    ):
        class_hook_bridge = _python_module(
            class_hook_source,
            path="package/qualified_class_bridge.py",
            module="package.qualified_class_bridge",
        )
        class_hook_helper = _python_module(
            "import package.qualified_class_bridge as bridge\n\n"
            "def effect(value=bridge.Holder.Inner):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/qualified_class_helper.py",
            module="package.qualified_class_helper",
        )
        for class_hook_order in (
            (
                qualified_class_values,
                class_hook_bridge,
                class_hook_helper,
                qualified_class_consumer,
            ),
            (
                qualified_class_consumer,
                class_hook_helper,
                class_hook_bridge,
                qualified_class_values,
            ),
            (
                class_hook_bridge,
                qualified_class_values,
                qualified_class_consumer,
                class_hook_helper,
            ),
        ):
            class_hook_functions, class_hook_assignments = _function_registry(*class_hook_order)
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    qualified_class_consumer,
                    class_hook_functions,
                    class_hook_assignments,
                )
    qualified_default_bridge = _python_module(
        "import package.qualified_default_values as values\n\n"
        "ALIAS = values.GLOBAL\n"
        'BOX = {"item": values.GLOBAL}\n'
        "NS = vars(values)\n"
        "GET = NS.get\n"
        "MODULE_ACCESS = values.__getattribute__\n"
        "MODULE_ITEM = values.__dict__.__getitem__\n"
        'ACCESSORS = {"module": MODULE_ACCESS, "dict": MODULE_ITEM}\n',
        path="package/qualified_default_bridge.py",
        module="package.qualified_default_bridge",
    )
    for reexported_default_expression in (
        "ALIAS",
        "LOCAL",
        "bridge.ALIAS",
        'getattr(bridge, "ALIAS")',
        'vars(bridge)["ALIAS"]',
        'bridge.BOX["item"]',
        'bridge.BOX.get("item")',
        'NS["GLOBAL"]',
        'GET("GLOBAL")',
        'bridge.NS["GLOBAL"]',
        'bridge.GET("GLOBAL")',
        'bridge.__getattribute__("ALIAS")',
        'bridge.__dict__.__getitem__("ALIAS")',
        'MODULE_ACCESS("GLOBAL")',
        'MODULE_ITEM("GLOBAL")',
        'ACCESSORS["module"]("GLOBAL")',
        'ACCESSORS["dict"]("GLOBAL")',
        'bridge.MODULE_ACCESS("GLOBAL")',
        'bridge.MODULE_ITEM("GLOBAL")',
        'bridge.ACCESSORS["module"]("GLOBAL")',
        'bridge.ACCESSORS["dict"]("GLOBAL")',
    ):
        reexported_default_helper = _python_module(
            "import package.qualified_default_bridge as bridge\n"
            "from .qualified_default_bridge import (\n"
            "    ACCESSORS,\n"
            "    ALIAS,\n"
            "    GET,\n"
            "    MODULE_ACCESS,\n"
            "    MODULE_ITEM,\n"
            "    NS,\n"
            ")\n\n"
            "LOCAL = ALIAS\n\n"
            f"def effect(value={reexported_default_expression}):\n"
            '    value.update({"hidden": {"child": 1}})\n',
            path="package/qualified_default_helper.py",
            module="package.qualified_default_helper",
        )
        reexported_default_orders = (
            (
                qualified_default_values,
                qualified_default_bridge,
                reexported_default_helper,
                qualified_default_consumer,
            ),
            (
                qualified_default_consumer,
                reexported_default_helper,
                qualified_default_bridge,
                qualified_default_values,
            ),
            (
                reexported_default_helper,
                qualified_default_consumer,
                qualified_default_values,
                qualified_default_bridge,
            ),
        )
        for reexported_default_order in reexported_default_orders:
            reexported_functions, reexported_assignments = _function_registry(
                *reexported_default_order
            )
            with pytest.raises(scanner.DiscoveryError):
                scanner._manifest_ast_pointers(
                    qualified_default_consumer,
                    reexported_functions,
                    reexported_assignments,
                )
    spoofed_accessor_values = _python_module(
        'GLOBAL = {"known": 1}\nOTHER = {"other": 1}\n',
        path="package/spoofed_accessor_values.py",
        module="package.spoofed_accessor_values",
    )
    spoofed_accessor_bridge = _python_module(
        "def getattr(obj, name):\n    return obj.OTHER\n\nACCESS = getattr\n",
        path="package/spoofed_accessor_bridge.py",
        module="package.spoofed_accessor_bridge",
    )
    spoofed_accessor_helper = _python_module(
        "import package.spoofed_accessor_values as values\n"
        "from .spoofed_accessor_bridge import ACCESS\n\n"
        'def effect(value=ACCESS(values, "GLOBAL")):\n'
        '    value.update({"hidden": {"child": 1}})\n',
        path="package/spoofed_accessor_helper.py",
        module="package.spoofed_accessor_helper",
    )
    spoofed_accessor_consumer = _python_module(
        "from .spoofed_accessor_values import OTHER as manifest\n"
        "from .spoofed_accessor_helper import effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/spoofed_accessor_consumer.py",
        module="package.spoofed_accessor_consumer",
    )
    for spoofed_accessor_order in (
        (
            spoofed_accessor_values,
            spoofed_accessor_bridge,
            spoofed_accessor_helper,
            spoofed_accessor_consumer,
        ),
        (
            spoofed_accessor_consumer,
            spoofed_accessor_helper,
            spoofed_accessor_bridge,
            spoofed_accessor_values,
        ),
        (
            spoofed_accessor_bridge,
            spoofed_accessor_consumer,
            spoofed_accessor_values,
            spoofed_accessor_helper,
        ),
    ):
        spoofed_functions, spoofed_assignments = _function_registry(*spoofed_accessor_order)
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(
                spoofed_accessor_consumer,
                spoofed_functions,
                spoofed_assignments,
            )
    circular_default_a = _python_module(
        'GLOBAL = {"known": 1}\nEXPORTED = GLOBAL\nfrom .circular_default_b import effect\n',
        path="package/circular_default_a.py",
        module="package.circular_default_a",
    )
    circular_default_b = _python_module(
        "from .circular_default_a import GLOBAL\n\n"
        "def effect(value=GLOBAL):\n"
        '    value.update({"hidden": {"child": 1}})\n',
        path="package/circular_default_b.py",
        module="package.circular_default_b",
    )
    circular_default_consumer = _python_module(
        "from .circular_default_a import EXPORTED as manifest, effect\n\n"
        "effect()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/circular_default_consumer.py",
        module="package.circular_default_consumer",
    )
    circular_orders = (
        (circular_default_a, circular_default_b, circular_default_consumer),
        (circular_default_b, circular_default_a, circular_default_consumer),
        (circular_default_consumer, circular_default_b, circular_default_a),
        (circular_default_consumer, circular_default_a, circular_default_b),
    )
    for circular_order in circular_orders:
        circular_functions, circular_assignments = _function_registry(*circular_order)
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(
                circular_default_consumer,
                circular_functions,
                circular_assignments,
            )
    circular_origin = _python_module(
        'manifest = {"known": 1}\n\n'
        "class Original:\n"
        "    def __init__(self):\n"
        '        manifest.update({"hidden": {"child": 1}})\n\n'
        "from .circular_export import Exported\n\n"
        "Exported()\n\n"
        "def build_manifest():\n"
        "    return manifest\n",
        path="package/circular_origin.py",
        module="package.circular_origin",
    )
    circular_export = _python_module(
        "from .circular_origin import Original as Imported\n\nExported = Imported\n",
        path="package/circular_export.py",
        module="package.circular_export",
    )
    for circular_modules in (
        (circular_origin, circular_export),
        (circular_export, circular_origin),
    ):
        circular_functions, circular_assignments = _function_registry(*circular_modules)
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(
                circular_origin,
                circular_functions,
                circular_assignments,
            )
    assert scanner._manifest_ast_pointers(method_mutation, {}) == {
        "function:build_manifest/hidden",
        "function:build_manifest/hidden/child",
        "function:build_manifest/known",
    }
    assert scanner._manifest_ast_pointers(nested_list_mutation, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/child",
    }
    assert scanner._manifest_ast_pointers(retained_subscript_write, {}) == {
        "function:build_manifest/hidden",
        "function:build_manifest/hidden/child",
        "function:build_manifest/known",
    }
    assert scanner._manifest_ast_pointers(nested_retained_subscript_write, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/hidden",
        "function:build_manifest/items/*/hidden/child",
        "function:build_manifest/items/*/known",
    }
    assert scanner._manifest_ast_pointers(constructor_snapshot, {}) == {
        "function:build_manifest/item",
        "function:build_manifest/item/known",
    }
    assert scanner._manifest_ast_pointers(comprehension_snapshot, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/known",
    }
    assert scanner._manifest_ast_pointers(lazy_generator_rebind, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/decoy",
    }
    assert scanner._manifest_ast_pointers(generator_outer_iter_snapshot, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/known",
    }
    assert scanner._manifest_ast_pointers(generator_inner_iter_rebind, {}) == {
        "function:build_manifest/items",
        "function:build_manifest/items/*/decoy",
    }
    for generator_outer_iter_mutation in generator_outer_iter_mutations:
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(generator_outer_iter_mutation, {})
    for generator_nested_outer_iter_mutation in generator_nested_outer_iter_mutations:
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(generator_nested_outer_iter_mutation, {})
    eager_assignments = scanner._assignment_map(eagerly_consumed_generator.tree)
    assert not any(
        isinstance(candidate, scanner._UnknownBinding)
        for candidate in eager_assignments["n_frames"]
    )
    for composite_default_mutation in composite_default_mutations:
        with pytest.raises(scanner.DiscoveryError):
            scanner._manifest_ast_pointers(composite_default_mutation, {})


def test_imported_manifest_helper_uses_defining_module_bindings() -> None:
    caller = _python_module(
        "from .reporting import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    GLOBAL = {"wrong": 1}\n'
        '    return {"nested": file_ref()}\n'
    )
    helper = _python_module(
        'GLOBAL = {"right": 1}\n\ndef file_ref() -> dict[str, object]:\n    return GLOBAL\n',
        path="package/reporting.py",
        module="package.reporting",
    )
    external, assignments = _function_registry(caller, helper)

    assert scanner._manifest_ast_pointers(caller, external, assignments) == {
        "function:build_manifest/nested",
        "function:build_manifest/nested/right",
    }

    values = _python_module(
        'GLOBAL = {"imported": 1}\n',
        path="package/values.py",
        module="package.values",
    )
    local_last_caller = _python_module(
        "from .reporting_local_last import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": file_ref()}\n'
    )
    local_last_helper = _python_module(
        "from .values import GLOBAL\n"
        'GLOBAL = {"local": 1}\n\n'
        "def file_ref() -> dict[str, object]:\n"
        "    return GLOBAL\n",
        path="package/reporting_local_last.py",
        module="package.reporting_local_last",
    )
    local_external, local_assignments = _function_registry(
        local_last_caller, local_last_helper, values
    )
    assert scanner._manifest_ast_pointers(local_last_caller, local_external, local_assignments) == {
        "function:build_manifest/nested",
        "function:build_manifest/nested/local",
    }

    import_last_caller = _python_module(
        "from .reporting_import_last import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": file_ref()}\n'
    )
    import_last_helper = _python_module(
        'GLOBAL = {"local": 1}\n'
        "from .values import GLOBAL\n\n"
        "def file_ref() -> dict[str, object]:\n"
        "    return GLOBAL\n",
        path="package/reporting_import_last.py",
        module="package.reporting_import_last",
    )
    import_external, import_assignments = _function_registry(
        import_last_caller, import_last_helper, values
    )
    assert scanner._manifest_ast_pointers(
        import_last_caller, import_external, import_assignments
    ) == {
        "function:build_manifest/nested",
        "function:build_manifest/nested/imported",
    }

    qualified_caller = _python_module(
        "from .reporting import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": unrelated.file_ref()}\n'
    )
    qualified_external, qualified_assignments = _function_registry(qualified_caller, helper)
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(
            qualified_caller,
            qualified_external,
            qualified_assignments,
        )


def test_manifest_function_bindings_follow_source_order() -> None:
    imported_last = _python_module(
        "def file_ref() -> dict[str, object]:\n"
        '    return {"local": 1}\n\n'
        "from .reporting import file_ref\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": file_ref()}\n'
    )
    local_last = _python_module(
        "from .reporting import file_ref\n\n"
        "def file_ref() -> dict[str, object]:\n"
        '    return {"local": 1}\n\n'
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": file_ref()}\n'
    )
    helper = _python_module(
        'def file_ref() -> dict[str, object]:\n    return {"imported": 1}\n',
        path="package/reporting.py",
        module="package.reporting",
    )

    imported_external, imported_assignments = _function_registry(imported_last, helper)
    assert scanner._manifest_ast_pointers(
        imported_last, imported_external, imported_assignments
    ) == {
        "function:build_manifest/nested",
        "function:build_manifest/nested/imported",
    }
    local_external, local_assignments = _function_registry(local_last, helper)
    assert scanner._manifest_ast_pointers(local_last, local_external, local_assignments) == {
        "function:build_manifest/nested",
        "function:build_manifest/nested/local",
    }


def test_manifest_class_bindings_follow_source_order() -> None:
    imported_last = _python_module(
        "class Config:\n"
        "    payload: dict[str, object]\n\n"
        "from .types import Config\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n',
        path="package/imported_last.py",
        module="package.imported_last",
    )
    local_last = _python_module(
        "from .types import Config\n\n"
        "class Config:\n"
        "    payload: dict[str, object]\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n',
        path="package/local_last.py",
        module="package.local_last",
    )
    types = _python_module(
        "class Config:\n    payload: str\n",
        path="package/types.py",
        module="package.types",
    )
    external_classes = scanner._class_field_registry((imported_last, local_last, types))

    assert scanner._manifest_ast_pointers(imported_last, {}, external_classes=external_classes) == {
        "function:build_manifest/nested"
    }
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(local_last, {}, external_classes=external_classes)

    function_before_import = _python_module(
        "class Config:\n"
        "    payload: dict[str, object]\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n\n'
        "from .types import Config\n",
        path="package/function_before_import.py",
        module="package.function_before_import",
    )
    function_before_local = _python_module(
        "from .types import Config\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n\n'
        "class Config:\n"
        "    payload: dict[str, object]\n",
        path="package/function_before_local.py",
        module="package.function_before_local",
    )
    definition_classes = scanner._class_field_registry(
        (function_before_import, function_before_local, types)
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(
            function_before_import,
            {},
            external_classes=definition_classes,
        )
    assert scanner._manifest_ast_pointers(
        function_before_local,
        {},
        external_classes=definition_classes,
    ) == {"function:build_manifest/nested"}

    duplicate = _python_module(
        "class Config:\n"
        "    payload: dict[str, object]\n\n"
        "MappingConfig = Config\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n\n'
        "class Config:\n"
        "    payload: str\n",
        path="package/duplicate.py",
        module="package.duplicate",
    )
    with pytest.raises(scanner.DiscoveryError, match="redefines a top-level class"):
        scanner._manifest_ast_pointers(duplicate, {})


@pytest.mark.parametrize(
    "body",
    (
        '    return {"items": [{"known": 1}, runtime_item]}\n',
        '    return {"items": [item for item in source]}\n',
        '    return {"nested": runtime_item}\n',
        '    return {"nested": config["payload"]}\n',
        '    return {"nested": config.payload}\n',
        '    return {"nested": config.get("payload")}\n',
    ),
)
def test_unresolved_nested_manifest_values_fail_closed(body: str) -> None:
    module = _python_module("def build_manifest(config) -> dict[str, object]:\n" + body)

    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(module, {})


def test_typed_scalar_manifest_selections_are_closed_leaves() -> None:
    module = _python_module(
        "from collections.abc import Mapping\n\n"
        "class Config:\n"
        "    payload: str\n\n"
        "def build_manifest(config: Config, values: Mapping[str, str]) -> dict[str, object]:\n"
        '    return {"attribute": config.payload, "subscript": values["payload"]}\n'
    )

    assert scanner._manifest_ast_pointers(module, {}) == {
        "function:build_manifest/attribute",
        "function:build_manifest/subscript",
    }

    imported_path = _python_module(
        "from pathlib import Path\n\n"
        "def build_manifest(value: Path) -> dict[str, object]:\n"
        '    return {"path": value}\n'
    )
    assert scanner._manifest_ast_pointers(imported_path, {}) == {"function:build_manifest/path"}

    function_before_import = _python_module(
        "class Path(dict):\n"
        "    pass\n\n"
        "def build_manifest(value: Path) -> dict[str, object]:\n"
        '    return {"nested": value}\n\n'
        "from pathlib import Path\n"
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(function_before_import, {})

    function_before_shadow = _python_module(
        "from pathlib import Path\n\n"
        "def build_manifest(value: Path) -> dict[str, object]:\n"
        '    return {"nested": value}\n\n'
        "class Path(dict):\n"
        "    pass\n"
    )
    assert scanner._manifest_ast_pointers(function_before_shadow, {}) == {
        "function:build_manifest/nested"
    }

    for scalar_name in ("Path", "str"):
        shadowed = _python_module(
            f"class {scalar_name}(dict):\n"
            "    pass\n\n"
            f"def build_manifest(value: {scalar_name}) -> dict[str, object]:\n"
            '    return {"nested": value}\n'
        )
        with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
            scanner._manifest_ast_pointers(shadowed, {})

    mixed_tuple = _python_module(
        "def build_manifest(value: tuple[str, dict[str, object]]) -> dict[str, object]:\n"
        '    return {"nested": value}\n'
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(mixed_tuple, {})

    shadowed_types = _python_module(
        "class Path(dict):\n    pass\n\nclass Config:\n    payload: Path\n",
        path="package/shadowed_types.py",
        module="package.shadowed_types",
    )
    shadowed_caller = _python_module(
        "from .shadowed_types import Config\n"
        "from pathlib import Path\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n'
    )
    shadowed_classes = scanner._class_field_registry((shadowed_caller, shadowed_types))
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(
            shadowed_caller,
            {},
            external_classes=shadowed_classes,
        )

    imported_types = _python_module(
        "from pathlib import Path\n\nclass Config:\n    payload: Path\n",
        path="package/imported_types.py",
        module="package.imported_types",
    )
    imported_caller = _python_module(
        "from .imported_types import Config\n\n"
        "class Path(dict):\n"
        "    pass\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n'
    )
    imported_classes = scanner._class_field_registry((imported_caller, imported_types))
    assert scanner._manifest_ast_pointers(
        imported_caller,
        {},
        external_classes=imported_classes,
    ) == {"function:build_manifest/nested"}

    field_before_import = _python_module(
        "class Path(dict):\n"
        "    pass\n\n"
        "class Config:\n"
        "    payload: Path\n\n"
        "from pathlib import Path\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n'
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(field_before_import, {})

    field_before_shadow = _python_module(
        "from pathlib import Path\n\n"
        "class Config:\n"
        "    payload: Path\n\n"
        "class Path(dict):\n"
        "    pass\n\n"
        "def build_manifest(config: Config) -> dict[str, object]:\n"
        '    return {"nested": config.payload}\n'
    )
    assert scanner._manifest_ast_pointers(field_before_shadow, {}) == {
        "function:build_manifest/nested"
    }


def test_shadowed_builtin_manifest_calls_fail_closed() -> None:
    shadowed_scalar = _python_module(
        'def build_manifest(str) -> dict[str, object]:\n    return {"nested": str()}\n'
    )
    shadowed_mapping = _python_module(
        "from runtime import dict\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return dict(nested={"hidden": 1})\n'
    )

    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(shadowed_scalar, {})
    with pytest.raises(scanner.DiscoveryError, match="dynamic manifest mapping"):
        scanner._manifest_ast_pointers(shadowed_mapping, {})


def test_manifest_leaf_requires_exact_import_provenance() -> None:
    imported = _python_module(
        "import hashlib as secure_hashlib\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"digest": secure_hashlib.sha256(b"value").hexdigest()}\n'
    )
    shadowed = _python_module(
        "def build_manifest(hashlib) -> dict[str, object]:\n"
        '    return {"digest": hashlib.sha256(b"value").hexdigest()}\n'
    )
    imported_module_value = _python_module(
        "import hashlib\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": hashlib}\n'
    )
    loop_shadowed = _python_module(
        "import hashlib\n\n"
        "def build_manifest(values) -> dict[str, object]:\n"
        "    for hashlib in values:\n"
        "        pass\n"
        '    return {"digest": hashlib.sha256(b"value").hexdigest()}\n'
    )

    assert scanner._manifest_ast_pointers(imported, {}) == {"function:build_manifest/digest"}
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(shadowed, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(imported_module_value, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(loop_shadowed, {})

    imported_path = _python_module(
        "from pathlib import Path\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"path": Path("proof.txt")}\n'
    )
    shadowed_path = _python_module(
        'def build_manifest(Path) -> dict[str, object]:\n    return {"nested": Path("proof.txt")}\n'
    )

    assert scanner._manifest_ast_pointers(imported_path, {}) == {"function:build_manifest/path"}
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(shadowed_path, {})


def test_reassigned_manifest_parameter_does_not_keep_stale_annotation() -> None:
    module = _python_module(
        "class ScalarConfig:\n"
        "    payload: str\n\n"
        "class MappingConfig:\n"
        "    payload: dict[str, object]\n\n"
        "def build_manifest(config: ScalarConfig) -> dict[str, object]:\n"
        "    config = MappingConfig()\n"
        '    return {"nested": config.payload}\n'
    )

    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(module, {})

    loop_reassigned = _python_module(
        "class ScalarConfig:\n"
        "    payload: str\n\n"
        "def build_manifest(config: ScalarConfig, configs) -> dict[str, object]:\n"
        "    for config in configs:\n"
        "        pass\n"
        '    return {"nested": config.payload}\n'
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(loop_reassigned, {})

    pattern_reassigned = _python_module(
        "class ScalarConfig:\n"
        "    payload: str\n\n"
        "def build_manifest(config: ScalarConfig, source) -> dict[str, object]:\n"
        "    match source:\n"
        "        case [config]:\n"
        "            pass\n"
        '    return {"nested": config.payload}\n'
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(pattern_reassigned, {})

    field_reassigned = _python_module(
        "class ScalarConfig:\n"
        "    payload: str\n\n"
        "def build_manifest(config: ScalarConfig) -> dict[str, object]:\n"
        '    config.payload = {"hidden": 1}\n'
        '    return {"nested": config.payload}\n'
    )
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(field_reassigned, {})


def test_nonartifact_manifest_named_maps_are_not_inventoried() -> None:
    module = _python_module(
        "def validate(source: dict[str, object]) -> None:\n"
        '    manifest_equalities = {"dynamic": source.get("payload")}\n'
        "    assert manifest_equalities\n"
    )

    assert scanner._manifest_ast_pointers(module, {}) == set()

    command_map = _python_module(
        "def _manifest_command_map(commands) -> dict[str, object]:\n"
        "    mapped: dict[str, object] = {}\n"
        "    for command in commands:\n"
        '        mapped[command["id"]] = command\n'
        "    return mapped\n"
    )
    assert scanner._manifest_ast_pointers(command_map, {}) == set()


def test_checksum_pinned_manifest_leaves_require_exact_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "package/source.py"
    source = "payload = source.value\n"
    _write(tmp_path / path, source)
    module = _python_module(source, path=path, module="package.source")
    attribute = next(node for node in ast.walk(module.tree) if isinstance(node, ast.Attribute))
    declaration = (attribute.lineno, attribute.col_offset, ast.unparse(attribute))
    monkeypatch.setattr(
        scanner,
        "CHECKSUM_PINNED_MANIFEST_LEAVES",
        {path: (hashlib.sha256(source.encode()).hexdigest(), (declaration,))},
    )

    scanner._validate_checksum_pinned_manifest_leaves(tmp_path, (module,))
    (tmp_path / path).write_text(source + "\n", encoding="utf-8")
    with pytest.raises(scanner.DiscoveryError, match="source changed"):
        scanner._validate_checksum_pinned_manifest_leaves(tmp_path, (module,))


def test_checksum_pinned_manifest_subtrees_expand_producer_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consumer_path = "package/consumer.py"
    producer_path = "package/producer.py"
    consumer_source = (
        "def build_manifest(source) -> dict[str, object]:\n"
        '    return {"records": list(source.records)}\n'
    )
    producer_source = 'RECORD = {"id": 1, "metadata": {}}\n'
    _write(tmp_path / consumer_path, consumer_source)
    _write(tmp_path / producer_path, producer_source)
    consumer = _python_module(consumer_source, path=consumer_path, module="package.consumer")
    producer = _python_module(producer_source, path=producer_path, module="package.producer")
    expression = next(node for node in ast.walk(consumer.tree) if isinstance(node, ast.Call))
    producer_mapping = next(node for node in ast.walk(producer.tree) if isinstance(node, ast.Dict))
    declaration = (
        expression.lineno,
        expression.col_offset,
        ast.unparse(expression),
        (
            producer_mapping.lineno,
            producer_mapping.col_offset,
            ast.unparse(producer_mapping),
        ),
        ("/*/id", "/*/metadata"),
    )
    monkeypatch.setattr(
        scanner,
        "CHECKSUM_PINNED_MANIFEST_SUBTREES",
        {
            consumer_path: (
                hashlib.sha256(consumer_source.encode()).hexdigest(),
                producer_path,
                hashlib.sha256(producer_source.encode()).hexdigest(),
                (declaration,),
            )
        },
    )

    assert scanner._manifest_ast_pointers(consumer, {}) == {
        "function:build_manifest/records",
        "function:build_manifest/records/*/id",
        "function:build_manifest/records/*/metadata",
    }
    scanner._validate_checksum_pinned_manifest_subtrees(tmp_path, (consumer, producer))
    monkeypatch.setattr(
        scanner,
        "CHECKSUM_PINNED_MANIFEST_SUBTREES",
        {
            consumer_path: (
                hashlib.sha256(consumer_source.encode()).hexdigest(),
                producer_path,
                hashlib.sha256(producer_source.encode()).hexdigest(),
                ((*declaration[:-1], ("/*/id",)),),
            )
        },
    )
    with pytest.raises(scanner.DiscoveryError, match="producer keys changed"):
        scanner._validate_checksum_pinned_manifest_subtrees(tmp_path, (consumer, producer))
    (tmp_path / producer_path).write_text(producer_source + "\n", encoding="utf-8")
    with pytest.raises(scanner.DiscoveryError, match="producer changed"):
        scanner._validate_checksum_pinned_manifest_subtrees(tmp_path, (consumer, producer))

    dynamic_path = "package/dynamic.py"
    dynamic_source = (
        "def create_manifest(items):\n"
        "    digests = {item.name: digest(item) for item in items}\n"
        "    return digests\n"
    )
    _write(tmp_path / dynamic_path, dynamic_source)
    dynamic = _python_module(dynamic_source, path=dynamic_path, module="package.dynamic")
    returned = next(
        node.value
        for node in ast.walk(dynamic.tree)
        if isinstance(node, ast.Return) and node.value is not None
    )
    comprehension = next(node for node in ast.walk(dynamic.tree) if isinstance(node, ast.DictComp))
    dynamic_declaration = (
        returned.lineno,
        returned.col_offset,
        ast.unparse(returned),
        (comprehension.lineno, comprehension.col_offset, ast.unparse(comprehension)),
        ("/*",),
    )
    dynamic_digest = hashlib.sha256(dynamic_source.encode()).hexdigest()
    monkeypatch.setattr(
        scanner,
        "CHECKSUM_PINNED_MANIFEST_SUBTREES",
        {
            dynamic_path: (
                dynamic_digest,
                dynamic_path,
                dynamic_digest,
                (dynamic_declaration,),
            )
        },
    )
    assert scanner._manifest_ast_pointers(dynamic, {}) == {"function:create_manifest/*"}
    scanner._validate_checksum_pinned_manifest_subtrees(tmp_path, (dynamic,))
    monkeypatch.setattr(
        scanner,
        "CHECKSUM_PINNED_MANIFEST_SUBTREES",
        {
            dynamic_path: (
                dynamic_digest,
                dynamic_path,
                dynamic_digest,
                ((*dynamic_declaration[:-1], ("/*/child",)),),
            )
        },
    )
    with pytest.raises(scanner.DiscoveryError, match="producer keys changed"):
        scanner._validate_checksum_pinned_manifest_subtrees(tmp_path, (dynamic,))


def test_unresolved_helper_return_and_mapping_argument_fail_closed() -> None:
    unresolved_return = _python_module(
        "def records() -> list[dict[str, object]]:\n"
        "    return runtime_items\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"items": records()}\n'
    )
    unresolved_argument = _python_module(
        "def identity(value: str) -> str:\n"
        "    return value\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": identity({"hidden": 1})}\n'
    )
    unresolved_attribute_argument = _python_module(
        "class Box:\n"
        "    payload: str\n\n"
        "def identity(value: str) -> Box:\n"
        "    return Box()\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    return {"nested": identity({"hidden": 1}).payload}\n'
    )
    unresolved_comprehension_argument = _python_module(
        "def identity(value: str) -> str:\n"
        "    return value\n\n"
        "def build_manifest(value: str, source) -> dict[str, object]:\n"
        '    return {"items": [identity(value) for value in source]}\n'
    )
    unresolved_starred_comprehension = _python_module(
        "def identity(value: str) -> str:\n"
        "    return value\n\n"
        "def build_manifest(value: str, source) -> dict[str, object]:\n"
        '    return {"items": [identity(value) for *prefix, value in source]}\n'
    )

    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(unresolved_return, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(unresolved_argument, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(unresolved_attribute_argument, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(unresolved_comprehension_argument, {})
    with pytest.raises(scanner.DiscoveryError, match="unresolved nested manifest value"):
        scanner._manifest_ast_pointers(unresolved_starred_comprehension, {})


@pytest.mark.parametrize(
    "nested",
    (
        "runtime_mapping()",
        '{key: "value" for key in runtime_keys()}',
        "ambiguous",
    ),
)
def test_dynamic_nested_manifest_containers_fail_closed(nested: str) -> None:
    module = _python_module(
        "def runtime_mapping() -> dict[str, object]:\n"
        "    return dict(runtime_items())\n\n"
        "def build_manifest() -> dict[str, object]:\n"
        '    ambiguous = {"first": 1}\n'
        '    ambiguous = {"second": 2}\n'
        f'    return {{"artifact": {nested}}}\n'
    )

    with pytest.raises(scanner.DiscoveryError):
        scanner._manifest_ast_pointers(module, {})


@pytest.mark.parametrize(
    ("name", "content", "reader"),
    (
        ("duplicate.json", '{"key":1,"key":2}', "json"),
        ("nonfinite.json", '{"key":NaN}', "json"),
        ("duplicate.yaml", "key: 1\nkey: 2\n", "yaml"),
        ("nonstring.yaml", "1: value\n", "yaml"),
        ("duplicate.toml", "key = 1\nkey = 2\n", "toml"),
    ),
)
def test_ambiguous_structured_documents_fail_closed(
    tmp_path: Path, name: str, content: str, reader: str
) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")

    with pytest.raises(scanner.DiscoveryError):
        getattr(scanner, f"_read_{reader}")(path)


def test_yaml_merge_override_is_unambiguous(tmp_path: Path) -> None:
    path = tmp_path / "merge.yaml"
    path.write_text(
        "base: &base\n  enabled: false\nmerged:\n  <<: *base\n  enabled: true\n",
        encoding="utf-8",
    )

    assert scanner._read_yaml(path) == {
        "base": {"enabled": False},
        "merged": {"enabled": True},
    }


def test_only_exact_retained_invalid_config_bytes_are_allowed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    for relative, expected_digest in scanner.RETAINED_INVALID_CONFIGS.items():
        destination = root / relative
        _copy(ROOT / relative, destination)
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == expected_digest
        assert scanner._validate_config(root, relative) == "checksum-pinned retained-invalid"
        destination.write_bytes(destination.read_bytes() + b"\n")
        with pytest.raises(scanner.DiscoveryError):
            scanner._validate_config(root, relative)

    unknown = root / "configs" / "unknown.yaml"
    _write(unknown, "key: 1\nkey: 2\n")
    with pytest.raises(scanner.DiscoveryError):
        scanner._validate_config(root, "configs/unknown.yaml")


def test_manifest_json_and_csv_reject_noncanonical_shapes(tmp_path: Path) -> None:
    root = _mini_repository(tmp_path)
    manifest = root / "evidence" / "artifact-manifest.json"
    manifest.write_text("[]\n", encoding="utf-8")
    with pytest.raises(scanner.DiscoveryError, match="canonical JSON must be an object"):
        scanner.discover(root)

    manifest.write_text('{"artifact":{"path":"proofs/proof.txt"}}\n', encoding="utf-8")
    (root / "evidence" / "manifest.csv").write_text("id,path\nartifact\n", encoding="utf-8")
    with pytest.raises(scanner.DiscoveryError, match="header width"):
        scanner.discover(root)


def test_workflow_and_job_declarations_are_exact_and_strict(tmp_path: Path) -> None:
    discovery = scanner.discover(ROOT)
    rows = list(discovery.rows)
    workflows = [row for row in rows if row["kind"] == scanner.FAMILY_KIND["workflows"]]
    jobs = [row for row in rows if row["kind"] == scanner.FAMILY_KIND["jobs"]]
    assert len(workflows) == EXPECTED_FAMILY_COUNTS["workflows"]
    assert len(jobs) == EXPECTED_FAMILY_COUNTS["jobs"]

    root = tmp_path / "repo"
    path = root / ".github" / "workflows" / "duplicate.yml"
    _write(path, "name: CI\njobs:\n  test: {}\njobs:\n  lint: {}\n")
    with pytest.raises(scanner.DiscoveryError, match="duplicate YAML key"):
        scanner._workflow_rows(root, (".github/workflows/duplicate.yml",))


def test_tracked_resources_are_complete_and_symlinks_are_bounded(tmp_path: Path) -> None:
    tracked = scanner._tracked_paths(ROOT)
    discovery = scanner.discover(ROOT)
    resource_names = {
        row["name"] for row in discovery.rows if row["kind"] == scanner.FAMILY_KIND["resources"]
    }
    assert resource_names == set(tracked) - set(scanner.GENERATED_TARGETS)

    root = tmp_path / "repo"
    root.mkdir()
    _write(root / "target.txt", "target\n")
    (root / "safe-link").symlink_to("target.txt")
    assert scanner._path_digest(root, "safe-link") == hashlib.sha256(b"target.txt").hexdigest()
    _write(tmp_path / "outside.txt", "outside\n")
    (root / "escape-link").symlink_to("../outside.txt")
    with pytest.raises(scanner.DiscoveryError, match="escapes the repository"):
        scanner._path_digest(root, "escape-link")

    outside_directory = tmp_path / "outside-directory"
    _write(outside_directory / "secret.txt", "secret\n")
    (root / "intermediate-link").symlink_to(outside_directory, target_is_directory=True)
    with pytest.raises(scanner.DiscoveryError, match="parent escapes the repository"):
        scanner._path_digest(root, "intermediate-link/secret.txt")


def test_generated_rows_are_closed_source_bound_and_traceable(
    candidates: tuple[dict[str, Any], dict[str, Any], str, Any],
) -> None:
    inventory, profiles, _markdown, discovery = candidates
    profile = next(item for item in profiles["profiles"] if item["id"] == scanner.PROFILE_ID)
    rows = _owned_rows(inventory)

    assert profile["support_disposition"] == "not_measured"
    assert profile["claim"]["classification"] == "observed_not_supported"
    assert (
        profile["source"]["digest_sha256"] == hashlib.sha256(SCANNER_PATH.read_bytes()).hexdigest()
    )
    assert [row["id"] for row in rows] == sorted({row["id"] for row in rows})
    assert tuple(rows) == discovery.rows
    for row in rows:
        assert row["owner"] == scanner.TASK_ID
        assert row["profile"] == scanner.PROFILE_ID
        assert row["claim"]["classification"] == "observed_not_supported"
        assert row["consumer_task_ids"] == list(scanner.CONSUMERS)
        assert row["trace_criterion_ids"] in [["MP2-013.A01"], ["MP2-013.A02"]]
        assert row["validator_ids"] == [scanner.INVENTORY_VALIDATOR]
        source = row["source"]
        assert source["digest_sha256"] == scanner._path_digest(ROOT, source["path"])


def test_current_claim_rows_bind_every_foreign_claim_digest(
    candidates: tuple[dict[str, Any], dict[str, Any], str, Any],
) -> None:
    inventory, profiles, _markdown, discovery = candidates
    foreign = [
        ("functional row", scanner.INVENTORY_PATH, row)
        for row in inventory["rows"]
        if row["owner"] != scanner.TASK_ID
    ] + [
        ("support profile", scanner.PROFILES_PATH, profile)
        for profile in profiles["profiles"]
        if profile["owner"] != scanner.TASK_ID
    ]
    claims = {
        row["name"]: row
        for row in discovery.rows
        if row["kind"] == scanner.FAMILY_KIND["current_claims"]
    }

    assert len(claims) == len(foreign) == EXPECTED_FAMILY_COUNTS["current_claims"]
    for kind, path, value in foreign:
        row = claims[f"{kind}:{value['id']}"]
        claim_digest = hashlib.sha256(_canonical_bytes(value["claim"])).hexdigest()
        assert row["source"]["type"] == "generated_registry"
        assert row["source"]["path"] == scanner.SCANNER_PATH
        assert row["source"]["locator"] == (f"{path}:{value['id']}:claim-sha256:{claim_digest}")


def test_foreign_supported_and_compatibility_objects_are_byte_preserved(
    candidates: tuple[dict[str, Any], dict[str, Any], str, Any],
) -> None:
    candidate_inventory, candidate_profiles, _markdown, _discovery = candidates
    before_inventory = _load(INVENTORY_PATH)
    before_profiles = _load(PROFILES_PATH)
    foreign_rows = copy.deepcopy(
        [row for row in before_inventory["rows"] if row["owner"] != scanner.TASK_ID]
    )
    foreign_profiles = copy.deepcopy(
        [profile for profile in before_profiles["profiles"] if profile["owner"] != scanner.TASK_ID]
    )

    assert [
        row for row in candidate_inventory["rows"] if row["owner"] != scanner.TASK_ID
    ] == foreign_rows
    assert [
        profile for profile in candidate_profiles["profiles"] if profile["owner"] != scanner.TASK_ID
    ] == foreign_profiles
    classifications = {"compatibility", "supported"}
    before_measured = [
        item
        for item in [*foreign_rows, *foreign_profiles]
        if item["claim"]["classification"] in classifications
    ]
    after_measured = [
        item
        for item in [*candidate_inventory["rows"], *candidate_profiles["profiles"]]
        if item["owner"] != scanner.TASK_ID and item["claim"]["classification"] in classifications
    ]
    assert _canonical_bytes(after_measured) == _canonical_bytes(before_measured)


def test_generated_docs_project_exact_family_and_profile_digests(
    candidates: tuple[dict[str, Any], dict[str, Any], str, Any],
) -> None:
    inventory, profiles, markdown, discovery = candidates
    profile = next(item for item in profiles["profiles"] if item["id"] == scanner.PROFILE_ID)

    assert f"- Owned rows: `{len(discovery.rows)}`" in markdown
    assert f"- Owned rows SHA-256: `{scanner._digest(list(discovery.rows))}`" in markdown
    assert f"- Functional rows SHA-256: `{inventory['rows_sha256']}`" in markdown
    assert f"- Owned profile SHA-256: `{scanner._digest(profile)}`" in markdown
    assert f"- Support profiles SHA-256: `{profiles['profiles_sha256']}`" in markdown
    for family, count in discovery.family_counts.items():
        assert f"| `{family}` | {count} | `{discovery.family_digests[family]}` |" in markdown
    for path in scanner.RETAINED_INVALID_CONFIGS:
        assert f"`{path}`" in markdown


def test_generate_is_three_run_idempotent_and_check_is_read_only(tmp_path: Path) -> None:
    root = _mini_repository(tmp_path)
    outputs = (
        root / scanner.INVENTORY_PATH,
        root / scanner.PROFILES_PATH,
        root / scanner.DOCS_PATH,
    )

    snapshots: list[tuple[bytes, bytes, bytes]] = []
    for _ in range(3):
        assert (
            scanner.run(
                "generate",
                repository_root=root,
                inventory=Path(scanner.INVENTORY_PATH),
                profiles=Path(scanner.PROFILES_PATH),
                docs=Path(scanner.DOCS_PATH),
            )
            == 0
        )
        snapshots.append(tuple(path.read_bytes() for path in outputs))
    assert snapshots[0] == snapshots[1] == snapshots[2]

    package = root / "demo" / "__init__.py"
    package.write_text(package.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    before = tuple(path.read_bytes() for path in outputs)
    assert (
        scanner.run(
            "check",
            repository_root=root,
            inventory=Path(scanner.INVENTORY_PATH),
            profiles=Path(scanner.PROFILES_PATH),
            docs=Path(scanner.DOCS_PATH),
        )
        == 1
    )
    assert tuple(path.read_bytes() for path in outputs) == before


def test_staging_keeps_private_mode_until_payload_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.json"
    target.write_bytes(b"before")
    target.chmod(0o640)
    payload = b'{"complete":true}'
    observed: list[tuple[int, bytes, int]] = []
    original_fchmod = os.fchmod

    def inspect_before_widening(descriptor: int, mode: int) -> None:
        observed.append(
            (
                stat.S_IMODE(os.fstat(descriptor).st_mode),
                os.pread(descriptor, len(payload) + 1, 0),
                mode,
            )
        )
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(os, "fchmod", inspect_before_widening)
    staged = scanner._stage(target, payload)
    try:
        assert observed == [(0o600, payload, 0o640)]
        assert staged.read_bytes() == payload
        assert stat.S_IMODE(staged.stat().st_mode) == 0o640
    finally:
        staged.unlink()


def test_transactional_generation_cleans_up_when_staging_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    original_stage = scanner._stage
    calls = 0

    def fail_second_stage(path: Path, payload: bytes, *, mode: int | None = None) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected staging failure")
        staged = original_stage(path, payload, mode=mode)
        assert isinstance(staged, Path)
        return staged

    monkeypatch.setattr(scanner, "_stage", fail_second_stage)
    with pytest.raises(OSError, match="injected staging failure"):
        scanner._replace_many(targets)
    assert {path.read_bytes() for path in targets} == {b"before"}
    assert list(tmp_path.glob(".*.tmp")) == []
    assert not (tmp_path / scanner.TRANSACTION_JOURNAL_NAME).exists()


def test_transactional_generation_rolls_back_all_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    original_replace = os.replace
    failed = False

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal failed
        if Path(destination).name == "b" and not failed:
            failed = True
            raise OSError("injected replacement failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="injected replacement failure"):
        scanner._replace_many(targets)
    assert {path.read_bytes() for path in targets} == {b"before"}
    assert list(tmp_path.glob(".*.tmp")) == []
    assert not (tmp_path / scanner.TRANSACTION_JOURNAL_NAME).exists()


def test_pending_transaction_survives_rollback_failure_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    original_replace = os.replace
    failed_publication = False
    failed_rollback = False

    def fail_publication_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal failed_publication, failed_rollback
        destination_name = Path(destination).name
        if destination_name == "b" and not failed_publication:
            failed_publication = True
            raise OSError("injected publication failure")
        if destination_name == "a" and failed_publication and not failed_rollback:
            failed_rollback = True
            raise OSError("injected rollback failure")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_publication_and_rollback)
    with pytest.raises(scanner.DiscoveryError, match="durable recovery remains pending"):
        scanner._replace_many(targets)

    journal = tmp_path / scanner.TRANSACTION_JOURNAL_NAME
    assert journal.exists()
    assert (tmp_path / "a").read_bytes() == b"a"
    assert (tmp_path / "b").read_bytes() == b"before"
    assert (tmp_path / "c").read_bytes() == b"before"
    assert list(tmp_path.glob(".*.tmp")) == []

    monkeypatch.setattr(os, "replace", original_replace)
    scanner._recover_transaction(tuple(sorted(targets)))
    assert {path.read_bytes() for path in targets} == {b"before"}
    assert not journal.exists()


@pytest.mark.parametrize(
    ("failed_call", "keeps_new_payloads"),
    ((1, False), (2, False), (3, True), (4, True), (5, True)),
)
def test_transactional_generation_recovers_after_every_directory_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_call: int,
    keeps_new_payloads: bool,
) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    original_sync = scanner._sync_directory
    calls = 0

    def fail_selected_sync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failed_call:
            raise OSError("injected directory sync failure")
        original_sync(path)

    monkeypatch.setattr(scanner, "_sync_directory", fail_selected_sync)
    with pytest.raises((OSError, scanner.DiscoveryError), match="injected directory sync failure"):
        scanner._replace_many(targets)
    assert {path.read_bytes() for path in targets} == (
        set(targets.values()) if keeps_new_payloads else {b"before"}
    )
    assert list(tmp_path.glob(".*.tmp")) == []
    assert not (tmp_path / scanner.TRANSACTION_JOURNAL_NAME).exists()


def test_committed_transaction_finishes_cleanup_after_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    original_recover = scanner._recover_transaction
    calls = 0

    def interrupt_committed_cleanup(paths: tuple[Path, ...]) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("injected committed-cleanup interruption")
        original_recover(paths)

    monkeypatch.setattr(scanner, "_recover_transaction", interrupt_committed_cleanup)
    with pytest.raises(scanner.DiscoveryError, match="durable recovery remains pending"):
        scanner._replace_many(targets)

    journal = tmp_path / scanner.TRANSACTION_JOURNAL_NAME
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "committed"
    assert {path.read_bytes() for path in targets} == set(targets.values())

    monkeypatch.setattr(scanner, "_recover_transaction", original_recover)
    original_recover(tuple(sorted(targets)))
    assert {path.read_bytes() for path in targets} == set(targets.values())
    assert not journal.exists()


def test_generation_rejects_symlink_transaction_journal(tmp_path: Path) -> None:
    targets = {tmp_path / name: name.encode() for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    journal = tmp_path / scanner.TRANSACTION_JOURNAL_NAME
    journal.symlink_to("missing-journal")

    with pytest.raises(scanner.DiscoveryError, match="regular non-symlink"):
        scanner._replace_many(targets)
    assert {path.read_bytes() for path in targets} == {b"before"}


def test_generation_lock_rejects_symlinks_and_nonregular_files(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.write_bytes(b"unchanged")
    victim.chmod(0o644)
    lock = tmp_path / "lock"
    lock.symlink_to(victim)

    with pytest.raises(scanner.DiscoveryError, match="regular non-symlink"):
        with scanner._generation_lock(lock):
            pytest.fail("symlink lock was acquired")
    assert victim.read_bytes() == b"unchanged"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644

    lock.unlink()
    lock.mkdir()
    with pytest.raises(scanner.DiscoveryError, match="regular non-symlink"):
        with scanner._generation_lock(lock):
            pytest.fail("directory lock was acquired")

    lock.rmdir()
    os.link(victim, lock)
    with pytest.raises(scanner.DiscoveryError, match="exactly one link"):
        with scanner._generation_lock(lock):
            pytest.fail("hardlinked lock was acquired")
    assert victim.read_bytes() == b"unchanged"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644


def _transaction_child_script() -> str:
    return f"""
import importlib.util
import os
from pathlib import Path
import sys
import time

scanner_path = Path({str(SCANNER_PATH)!r})
spec = importlib.util.spec_from_file_location("transaction_child_scanner", scanner_path)
scanner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)

root = Path(sys.argv[1])
label = sys.argv[2]
phase = sys.argv[3]
signal = Path(sys.argv[4])
targets = {{root / name: label.encode("ascii") for name in ("a", "b", "c")}}
original_replace = os.replace
original_sync = scanner._sync_directory
journal_replacements = 0
target_replacements = 0
sync_calls = 0

def replace(source, destination):
    global journal_replacements, target_replacements
    original_replace(source, destination)
    name = Path(destination).name
    if name == scanner.TRANSACTION_JOURNAL_NAME:
        journal_replacements += 1
        if phase == "committed_replace" and journal_replacements == 2:
            os._exit(97)
    elif name in {{"a", "b", "c"}}:
        target_replacements += 1
        if phase == f"target_{{target_replacements}}":
            os._exit(97)
        if phase == "concurrent_pause" and target_replacements == 1:
            signal.write_text("paused", encoding="utf-8")
            time.sleep(1.0)

def sync_directory(path):
    global sync_calls
    sync_calls += 1
    original_sync(path)
    phase_by_call = {{
        1: "prepared_sync",
        2: "publication_sync",
        3: "committed_sync",
        4: "cleanup_sync",
        5: "journal_unlink_sync",
    }}
    if phase == phase_by_call.get(sync_calls):
        os._exit(97)

scanner.os.replace = replace
scanner._sync_directory = sync_directory
scanner._replace_many(targets)
"""


def test_concurrent_generation_is_serialized(tmp_path: Path) -> None:
    for name in ("a", "b", "c"):
        (tmp_path / name).write_bytes(b"before")
    signal = tmp_path / "paused"
    script = _transaction_child_script()
    first = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), "first", "concurrent_pause", str(signal)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not signal.exists() and first.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert signal.exists(), first.communicate(timeout=5)
    second = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), "second", "none", str(signal)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_output = first.communicate(timeout=15)
    second_output = second.communicate(timeout=15)

    assert first.returncode == 0, first_output
    assert second.returncode == 0, second_output
    assert {(tmp_path / name).read_bytes() for name in ("a", "b", "c")} == {b"second"}
    assert not (tmp_path / scanner.TRANSACTION_JOURNAL_NAME).exists()


@pytest.mark.parametrize(
    ("phase", "expected"),
    (
        ("prepared_sync", b"before"),
        ("target_1", b"before"),
        ("target_2", b"before"),
        ("target_3", b"before"),
        ("publication_sync", b"before"),
        ("committed_replace", b"new"),
        ("committed_sync", b"new"),
        ("cleanup_sync", b"new"),
        ("journal_unlink_sync", b"new"),
    ),
)
def test_abrupt_process_exit_recovers_transaction(
    tmp_path: Path, phase: str, expected: bytes
) -> None:
    targets = {tmp_path / name: b"new" for name in ("a", "b", "c")}
    for path in targets:
        path.write_bytes(b"before")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _transaction_child_script(),
            str(tmp_path),
            "new",
            phase,
            str(tmp_path / "unused-signal"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 97, (completed.stdout, completed.stderr)

    scanner._recover_transaction(tuple(sorted(targets)))
    assert {path.read_bytes() for path in targets} == {expected}
    assert list(tmp_path.glob(".*.tmp")) == []
    assert not (tmp_path / scanner.TRANSACTION_JOURNAL_NAME).exists()
