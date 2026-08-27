# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import ast
import datetime as dt
import importlib
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
LOCK_PATH = ROOT / "uv.lock"
POLICY_DOC_PATH = ROOT / "docs" / "maintainers" / "testing-policy.md"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT_PATH = ROOT / ".pre-commit-config.yaml"
CONFIG_PACKAGE_PATH = ROOT / "metriplane" / "config"


def _load_warning_policy_module() -> Any:
    name = "metriplane_warning_policy"
    spec = importlib.util.spec_from_file_location(name, ROOT / "conftest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


warning_policy = _load_warning_policy_module()

RUNTIME_DEPENDENCIES = [
    "numpy>=1.26",
    "opencv-contrib-python-headless>=4.8",
    "PyYAML>=6.0",
    "websockets>=12.0",
    "pydantic>=2.0",
]
TOOLCHAIN = {
    "build": "1.5.0",
    "mkdocs": "1.6.1",
    "mypy": "1.20.2",
    "playwright": "1.62.0",
    "pytest": "8.4.2",
    "ruff": "0.16.2",
    "twine": "6.2.0",
    "types-PyYAML": "6.0.12.20260724",
}
EXPECTED_COLLECTION = 2340
EXPECTED_MYPY_SOURCES = 145
POLICY_NOW = dt.datetime(2026, 8, 25, tzinfo=dt.UTC)


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _lock() -> dict[str, Any]:
    return tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _entry(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": "MPWARN-0001",
        "owner": "maintainers",
        "reason": "Bounded upstream transition",
        "scope": ["source"],
        "category": "DeprecationWarning",
        "message": "bounded warning text",
        "expires": "2027-01-01T00:00:00Z",
    }
    value.update(changes)
    return value


def test_runtime_python_and_dependencies_remain_supported() -> None:
    project = _pyproject()["project"]
    assert project["requires-python"] == ">=3.12,<3.14"
    assert project["dependencies"] == RUNTIME_DEPENDENCIES


def test_build_backend_is_exact() -> None:
    build_system = _pyproject()["build-system"]
    assert build_system == {
        "requires": ["setuptools==82.0.1"],
        "build-backend": "setuptools.build_meta",
    }


def test_dev_toolchain_is_exact() -> None:
    expected = [f"{name}=={version}" for name, version in TOOLCHAIN.items()]
    assert _pyproject()["dependency-groups"]["dev"] == expected


def test_uv_requirement_is_exact() -> None:
    assert _pyproject()["tool"]["uv"]["required-version"] == "==0.12.0"


def test_root_quality_scope_is_explicit() -> None:
    config = _pyproject()["tool"]
    assert config["ruff"] == {
        "line-length": 100,
        "target-version": "py312",
        "exclude": ["adapters", "evidence", "metriplane/atlas", "proofs"],
        "lint": {"select": ["E4", "E7", "E9", "F"]},
    }
    assert config["mypy"] == {
        "python_version": "3.12",
        "strict": True,
        "files": ["metriplane"],
        "exclude": "^metriplane/atlas/",
        "overrides": [
            {
                "module": ["metriplane.atlas", "metriplane.atlas.*"],
                "follow_imports": "skip",
            }
        ],
    }


def test_ci_runs_the_canonical_quality_commands() -> None:
    workflow = CI_PATH.read_text(encoding="utf-8")
    commands = (
        "uv run --frozen ruff check .",
        "uv run --frozen ruff format --check .",
        "uv run --frozen mypy",
    )
    assert all(workflow.count(command) == 1 for command in commands)


def test_pre_commit_uses_the_canonical_tool_versions() -> None:
    repositories = yaml.safe_load(PRE_COMMIT_PATH.read_text(encoding="utf-8"))["repos"]
    revisions = {repository["repo"]: repository["rev"] for repository in repositories}
    assert revisions["https://github.com/astral-sh/ruff-pre-commit"] == f"v{TOOLCHAIN['ruff']}"
    assert revisions["https://github.com/pre-commit/mirrors-mypy"] == f"v{TOOLCHAIN['mypy']}"


def test_mypy_source_census_has_one_real_config_owner() -> None:
    source_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "metriplane").rglob("*.py")
        if "atlas" not in path.relative_to(ROOT / "metriplane").parts
    )
    assert len(source_files) == EXPECTED_MYPY_SOURCES
    assert "metriplane/config/runtime.py" in source_files
    assert not (ROOT / "metriplane" / "config.py").exists()
    assert not (CONFIG_PACKAGE_PATH / "__init__.pyi").exists()


def test_canonical_collection_matches_the_checkout() -> None:
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    node_ids = [line for line in completed.stdout.splitlines() if line.startswith("tests/")]
    assert len(node_ids) == EXPECTED_COLLECTION
    assert f"{EXPECTED_COLLECTION} tests collected" in completed.stdout


def test_lock_metadata_requires_exact_toolchain() -> None:
    metriplane = next(package for package in _lock()["package"] if package["name"] == "metriplane")
    requirements = metriplane["metadata"]["requires-dev"]["dev"]
    actual = {row["name"]: row["specifier"] for row in requirements}
    expected = {name.lower(): f"=={version}" for name, version in TOOLCHAIN.items()}
    assert actual == expected


def test_locked_and_installed_toolchain_identities_match() -> None:
    packages = {package["name"]: package.get("version") for package in _lock()["package"]}
    for name, version in TOOLCHAIN.items():
        normalized = name.lower()
        assert packages[normalized] == version
        assert importlib.metadata.version(name) == version


def test_pytest_strictness_is_exact(tmp_path: Path) -> None:
    config = _pyproject()["tool"]["pytest"]["ini_options"]
    addopts = config["addopts"].split()
    assert "--strict-config" in addopts
    assert "--strict-markers" in addopts
    assert config["xfail_strict"] is True
    assert config["filterwarnings"] == ["error"]

    test_file = tmp_path / "test_strict_policy.py"
    pyproject = tmp_path / "pyproject.toml"
    cases = (
        (
            "[tool.pytest.ini_options]\nunknown_policy_key = true\n",
            "def test_ok():\n    pass\n",
            ["--strict-config"],
            "Unknown config option",
        ),
        (
            '[tool.pytest.ini_options]\naddopts = "--strict-markers"\n',
            "import pytest\n@pytest.mark.unregistered\ndef test_marked():\n    pass\n",
            [],
            "not found in `markers` configuration option",
        ),
        (
            "[tool.pytest.ini_options]\nxfail_strict = true\n",
            "import pytest\n@pytest.mark.xfail\ndef test_xpass():\n    pass\n",
            [],
            "XPASS(strict)",
        ),
    )
    for config_text, test_text, extra_args, expected_error in cases:
        pyproject.write_text(config_text, encoding="utf-8")
        test_file.write_text(test_text, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *extra_args, test_file.name],
            cwd=tmp_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert result.returncode != 0
        assert expected_error in result.stdout


def test_source_path_is_not_configured() -> None:
    config = _pyproject()["tool"]["pytest"]["ini_options"]
    assert "pythonpath" not in config


def test_conftests_do_not_mutate_or_preimport_package_state() -> None:
    for path in (ROOT / "conftest.py", ROOT / "tests" / "conftest.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert "sys.path" not in source
        assert "invalidate_caches" not in source
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert "metriplane" not in imported_roots


def test_warning_policy_config_is_empty_version_one() -> None:
    policy = _pyproject()["tool"]["metriplane"]["testing"]
    assert policy == {"warning_allowlist_version": 1, "warning_allowlist": []}
    assert warning_policy._load_warning_policy(ROOT, profile="source", now=POLICY_NOW) == ()


def test_warning_policy_accepts_scoped_unexpired_entry() -> None:
    for profile in ("source", "installed"):
        entries = warning_policy._validate_warning_allowlist(
            [_entry(scope=["source", "installed"])], profile=profile, now=POLICY_NOW
        )
        assert len(entries) == 1
        assert entries[0].id == "MPWARN-0001"
        assert entries[0].pytest_filter == (r"ignore:\Abounded\ warning\ text\Z:DeprecationWarning")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warnings.filterwarnings(
                "ignore",
                message=r"\Abounded\ warning\ text\Z",
                category=DeprecationWarning,
            )
            warnings.warn("bounded warning text", DeprecationWarning, stacklevel=1)


def test_warning_policy_rejects_unknown_fields() -> None:
    with pytest.raises(warning_policy.WarningPolicyError, match="missing or unknown"):
        warning_policy._validate_warning_allowlist(
            [_entry(unreviewed=True)], profile="source", now=POLICY_NOW
        )


def test_warning_policy_rejects_malformed_entries() -> None:
    invalid_entries = [
        "not-a-table",
        _entry(id="bad id"),
        _entry(owner=""),
        _entry(reason=""),
        _entry(scope=[]),
        _entry(scope=["source", "source"]),
        _entry(scope=["other"]),
        _entry(category="UnknownWarning"),
        _entry(message="contains:colon"),
        _entry(expires="2027-01-01"),
    ]
    for entry in invalid_entries:
        with pytest.raises(warning_policy.WarningPolicyError):
            warning_policy._validate_warning_allowlist([entry], profile="source", now=POLICY_NOW)


def test_warning_policy_rejects_duplicate_ids() -> None:
    with pytest.raises(warning_policy.WarningPolicyError, match="duplicate"):
        warning_policy._validate_warning_allowlist(
            [_entry(), _entry(message="another exact warning")],
            profile="source",
            now=POLICY_NOW,
        )


def test_warning_policy_rejects_expired_entries() -> None:
    with pytest.raises(warning_policy.WarningPolicyError, match="expired"):
        warning_policy._validate_warning_allowlist(
            [_entry(expires="2026-08-25T00:00:00Z")],
            profile="source",
            now=POLICY_NOW,
        )


def test_wrong_scope_warning_still_fails_closed() -> None:
    entries = warning_policy._validate_warning_allowlist(
        [_entry(scope=["installed"])], profile="source", now=POLICY_NOW
    )
    assert entries == ()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(DeprecationWarning, match="bounded warning text"):
            warnings.warn("bounded warning text", DeprecationWarning, stacklevel=1)


def test_unknown_warning_fails_closed() -> None:
    with pytest.raises(UserWarning, match="unreviewed warning"):
        warnings.warn("unreviewed warning", UserWarning, stacklevel=1)


def test_active_profile_imports_only_expected_package() -> None:
    modules = (
        "metriplane",
        "metriplane.cli",
        "metriplane.config",
        "metriplane.mapping",
        "metriplane.recording",
    )
    for module in modules:
        importlib.import_module(module)

    expected = os.environ.get("METRIPLANE_EXPECT_INSTALLED_ROOT")
    expected_root = Path(expected).resolve() if expected else ROOT.resolve()
    imported = {
        name: Path(module.__file__).resolve()
        for name, module in sys.modules.items()
        if (name == "metriplane" or name.startswith("metriplane."))
        and getattr(module, "__file__", None)
    }
    assert imported
    assert all(path.is_relative_to(expected_root) for path in imported.values())


def test_documentation_matches_toolchain_and_profile_commands() -> None:
    text = POLICY_DOC_PATH.read_text(encoding="utf-8")
    required = [
        "uv==0.12.0",
        "setuptools==82.0.1",
        "PLAYWRIGHT_BROWSERS_PATH=/path/to/empty/browser-cache",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q",
        "METRIPLANE_TEST_PROFILE=installed",
        "PYTHONPATH",
        "uv run --frozen ruff check .",
        "uv run --frozen ruff format --check .",
        "uv run --frozen mypy",
        "adapters/",
        "evidence/",
        "metriplane/atlas/",
        "proofs/",
        "maintained `metriplane` package",
        'follow_imports = "skip"',
    ]
    required.extend(f"{name}=={version}" for name, version in TOOLCHAIN.items())
    assert all(fragment in text for fragment in required)


def test_canonical_collection_contract_is_documented() -> None:
    text = POLICY_DOC_PATH.read_text(encoding="utf-8")
    assert f"{EXPECTED_COLLECTION:,} items" in text
    assert "2,324 passed" in text
    assert "16 expected skips" in text
    assert "Twelve result-schema cases" in text
    assert "one browser smoke case" in text
    assert "one GPU-equivalence case" in text
    assert "two functional-inventory cases" in text
    assert "pytest --collect-only -q -p no:cacheprovider" in text
