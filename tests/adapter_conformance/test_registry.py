# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools.cross_adapter_gate import (
    GateError,
    _load_json,
    discover_repository,
    load_registry,
    validate_registry,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_FILES = {
    "CHECKSUMS.sha256",
    "entity-mapping.json",
    "expected-outcome.json",
    "normalization-report.json",
    "session.jsonl",
    "source-manifest.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_repository_surface(tmp_path: Path) -> Path:
    """Copy only the repository surfaces read by registry discovery."""
    destination = tmp_path / "repository"
    destination.mkdir()
    shutil.copy2(REPOSITORY_ROOT / "pyproject.toml", destination / "pyproject.toml")
    (destination / "metriplane").mkdir()
    ignore = shutil.ignore_patterns(
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "site",
        "*.pyc",
    )
    for relative in (
        ".github/workflows",
        "adapters",
        "docs/specs",
        "docs/user-guide",
        "examples/external_sources",
        "proofs",
        "tests/adapter_conformance",
    ):
        source = REPOSITORY_ROOT / relative
        shutil.copytree(source, destination / relative, ignore=ignore)
    return destination


def _matrix_rows(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matrix_path = REPOSITORY_ROOT / registry["discovery_policy"]["matrix_path"]
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    return {row["row_id"]: row for row in matrix["rows"]}


def test_registry_is_strict_and_matches_repository_discovery() -> None:
    registry = load_registry(REPOSITORY_ROOT)

    validate_registry(REPOSITORY_ROOT, registry, require_jsonschema=False)
    discover_repository(REPOSITORY_ROOT, registry)


def test_root_runtime_bridge_is_limited_to_base_python_adapter_tests() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    bridged = {
        adapter["component_id"]
        for adapter in registry["adapters"]
        if "tools.cross_adapter_pytest" in adapter["commands"]["unit_tests"]
    }

    assert bridged == {"massrobotics-amr", "ros2-mcap"}
    assert (REPOSITORY_ROOT / "tools/cross_adapter_pytest.py").is_file()


def test_registry_rejects_unknown_and_missing_schema_fields() -> None:
    registry = load_registry(REPOSITORY_ROOT)

    unknown = copy.deepcopy(registry)
    unknown["unregistered_policy"] = "not allowed"
    with pytest.raises(ValueError):
        validate_registry(REPOSITORY_ROOT, unknown, require_jsonschema=False)

    missing = copy.deepcopy(registry)
    del missing["discovery_policy"]
    with pytest.raises(ValueError):
        validate_registry(REPOSITORY_ROOT, missing, require_jsonschema=False)


def test_discovery_rejects_an_unregistered_adapter(tmp_path: Path) -> None:
    repository = _copy_repository_surface(tmp_path)
    adapter = repository / "adapters" / "unregistered_adapter"
    adapter.mkdir()
    (adapter / "pyproject.toml").write_text(
        '[project]\nname = "unregistered-adapter"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )

    registry = load_registry(repository)
    with pytest.raises(ValueError):
        discover_repository(repository, registry)


def test_discovery_rejects_an_unregistered_adapter_directory_without_metadata(
    tmp_path: Path,
) -> None:
    repository = _copy_repository_surface(tmp_path)
    (repository / "adapters" / "unregistered_empty_adapter").mkdir()

    registry = load_registry(repository)
    with pytest.raises(ValueError, match="adapter discovery mismatch"):
        discover_repository(repository, registry)


def test_discovery_rejects_a_removed_adapter_registry_entry(tmp_path: Path) -> None:
    repository = _copy_repository_surface(tmp_path)
    registry = load_registry(repository)
    registry["adapters"] = registry["adapters"][1:]

    with pytest.raises(ValueError, match="adapter discovery mismatch"):
        discover_repository(repository, registry)


def test_discovery_rejects_an_unregistered_fixture(tmp_path: Path) -> None:
    repository = _copy_repository_surface(tmp_path)
    fixture = repository / "examples" / "external_sources" / "unregistered_fixture"
    fixture.mkdir()
    (fixture / "source-manifest.json").write_text("{}\n", encoding="utf-8")

    registry = load_registry(repository)
    with pytest.raises(ValueError):
        discover_repository(repository, registry)


def test_discovery_rejects_a_missing_registered_component(tmp_path: Path) -> None:
    repository = _copy_repository_surface(tmp_path)
    shutil.rmtree(repository / "adapters" / "source_adapter_sdk")

    registry = load_registry(repository)
    with pytest.raises(ValueError):
        discover_repository(repository, registry)


def test_discovery_rejects_an_unreviewed_expected_event_change(tmp_path: Path) -> None:
    repository = _copy_repository_surface(tmp_path)
    registry = load_registry(repository)
    variant = registry["fixtures"][0]["variants"][0]
    variant["expected"]["events"] = variant["expected"]["events"][:-1]

    with pytest.raises(ValueError, match="event oracle drift"):
        discover_repository(repository, registry)


def test_strict_json_rejects_duplicate_nonfinite_and_overflow_numbers(
    tmp_path: Path,
) -> None:
    cases = {
        "duplicate.json": '{"value": 1, "value": 2}',
        "constant.json": '{"value": NaN}',
        "overflow.json": '{"value": 1e999}',
    }
    for name, payload in cases.items():
        path = tmp_path / name
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(GateError):
            _load_json(path)


def test_registered_packages_fixtures_proofs_workflows_and_notices_exist() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    components = [*registry["shared_infrastructure"], *registry["adapters"]]

    for component in components:
        package = REPOSITORY_ROOT / component["package_path"]
        assert package.is_dir(), component["component_id"]
        for filename in ("README.md", "pyproject.toml", "uv.lock"):
            assert (package / filename).is_file(), component["component_id"]
        assert (package / "src" / component["module_name"]).is_dir(), component["component_id"]

    for adapter in registry["adapters"]:
        source = adapter["source_fixture_path"]
        if isinstance(source, str):
            assert (REPOSITORY_ROOT / source).exists(), adapter["adapter_id"]

        proof = adapter["proof"]
        if proof["status"] != "not_applicable":
            for path in proof["paths"]:
                assert (REPOSITORY_ROOT / path).exists(), adapter["adapter_id"]

        workflow = adapter["dedicated_workflow"]["path"]
        assert (REPOSITORY_ROOT / workflow).is_file(), adapter["adapter_id"]
        for notice in adapter["required_notices"]:
            assert (REPOSITORY_ROOT / notice).is_file(), adapter["adapter_id"]

    for family in registry["fixtures"]:
        assert (REPOSITORY_ROOT / family["family_path"]).is_dir(), family["family_id"]
        for variant in family["variants"]:
            root = REPOSITORY_ROOT / variant["path"]
            assert root.is_dir(), variant["variant_id"]
            assert FIXTURE_FILES <= {path.name for path in root.iterdir()}

    policy = registry["discovery_policy"]
    for key in ("adapter_root", "fixture_root", "proof_root"):
        assert (REPOSITORY_ROOT / policy[key]).is_dir(), key
    assert (REPOSITORY_ROOT / policy["matrix_path"]).is_file()


def test_format_policy_preserves_frozen_maniskill_bytes_explicitly() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    components = [*registry["shared_infrastructure"], *registry["adapters"]]
    maniskill = next(
        component for component in components if component["component_id"] == "maniskill-pickcube"
    )

    assert maniskill["commands"]["format"] == "cross-adapter-gate:frozen-format-migration"
    assert maniskill["format_policy"]["mode"] == "frozen_migration"
    assert set(maniskill["format_policy"]["expected_reformatted_files"]) == {
        "adapters/maniskill_pickcube/src/maniskill_pickcube/__init__.py",
        "adapters/maniskill_pickcube/src/maniskill_pickcube/core.py",
        "adapters/maniskill_pickcube/tests/test_anti_taint.py",
        "adapters/maniskill_pickcube/tests/test_conversion.py",
        "adapters/maniskill_pickcube/tests/test_negative.py",
    }
    assert all(
        component["format_policy"] == {"mode": "checked_in", "expected_reformatted_files": []}
        for component in components
        if component["component_id"] != "maniskill-pickcube"
    )

    invalid = copy.deepcopy(registry)
    invalid_maniskill = next(
        component
        for component in invalid["adapters"]
        if component["component_id"] == "maniskill-pickcube"
    )
    invalid_maniskill["format_policy"]["expected_reformatted_files"] = []
    with pytest.raises(GateError, match="requires explicit changed files"):
        validate_registry(REPOSITORY_ROOT, invalid)


def test_matrix_rows_cover_registry_without_upgrading_audited_status() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    rows = _matrix_rows(registry)
    adapter_rows = {adapter["matrix_row_id"] for adapter in registry["adapters"]}
    unsupported_rows = {family["matrix_row_id"] for family in registry["unsupported_families"]}

    assert adapter_rows <= rows.keys()
    assert unsupported_rows <= rows.keys()

    verified_rows = {
        row_id
        for row_id, row in rows.items()
        if row["deterministic_conversion_status"]["status"] == "VERIFIED"
    }
    assert verified_rows <= adapter_rows


def test_calvin_remains_an_evidenced_no_go_without_code_or_fixture() -> None:
    registry = load_registry(REPOSITORY_ROOT)
    calvin = next(
        family for family in registry["unsupported_families"] if family["family_id"] == "calvin"
    )
    evidence = REPOSITORY_ROOT / calvin["evidence_path"]

    assert calvin["status"] == "NO-GO"
    assert calvin["blocking_reasons"]
    assert evidence.is_file()
    assert _sha256(evidence) == calvin["evidence_sha256"]
    assert not list(REPOSITORY_ROOT.glob(calvin["forbidden_adapter_glob"]))
    assert not list(REPOSITORY_ROOT.glob(calvin["forbidden_fixture_glob"]))

    rows = _matrix_rows(registry)
    assert rows[calvin["matrix_row_id"]]["decision"] == "NO-GO"
    assert all("calvin" not in adapter["adapter_id"].casefold() for adapter in registry["adapters"])
    assert all("calvin" not in fixture["family_id"].casefold() for fixture in registry["fixtures"])
