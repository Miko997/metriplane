# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from metriplane.resources import DASHBOARD_RESOURCES, RUNTIME_RESOURCES, read_bytes, resource

ROOT = Path(__file__).resolve().parents[1]


def test_registry_is_exactly_current_and_checker_is_read_only() -> None:
    before = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
    result = subprocess.run(
        [sys.executable, "tools/check_runtime_resources.py", "check", "--repository-root", "."],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT) == before


def test_every_declared_installed_resource_is_nonempty() -> None:
    assert len(DASHBOARD_RESOURCES) == 40
    assert len(RUNTIME_RESOURCES) == 42
    for relative_path in RUNTIME_RESOURCES:
        assert resource(relative_path).is_file(), relative_path
        assert read_bytes(relative_path), relative_path


@pytest.mark.parametrize("path", ["../secret", "/absolute", "dashboard/../secret", "./x"])
def test_resource_interface_rejects_noncanonical_paths(path: str) -> None:
    with pytest.raises((KeyError, ValueError)):
        resource(path)


def test_every_runtime_source_has_one_governed_classification() -> None:
    registry = json.loads((ROOT / "docs/status/runtime-resource-registry.json").read_text())
    paths = [entry["path"] for entry in registry["entries"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    classifications = {entry["classification"] for entry in registry["entries"]}
    assert classifications == {
        "explicit_configuration_input",
        "explicit_site_input",
        "packaged",
        "packaged_existing",
        "source_documentation",
    }
    for entry in registry["entries"]:
        if entry["classification"] in {"packaged", "packaged_existing"}:
            assert entry["installed_path"]
        else:
            assert "installed_path" not in entry


def test_installed_operator_modules_match_compatibility_sources() -> None:
    registry = json.loads((ROOT / "docs/status/runtime-resource-registry.json").read_text())
    assert len(registry["interfaces"]) == 6
    for interface in registry["interfaces"]:
        assert (ROOT / interface["source_path"]).read_bytes() == (
            ROOT / interface["installed_path"]
        ).read_bytes()


def test_runner_invokes_installed_modules_not_repo_tool_paths() -> None:
    operator_source = (ROOT / "metriplane/runner/operator_api.py").read_text()
    allowlist_source = (ROOT / "metriplane/runner/allowlist.py").read_text()
    for name in (
        "analyze_id_stability_jsonl",
        "calibrate_planar_homography",
        "debug_alignment",
        "list_cameras",
        "report_alignment",
        "zones_report_jsonl",
    ):
        assert f"metriplane.runner.tools.{name}" in operator_source + allowlist_source
        assert f'"tools/{name}.py"' not in operator_source + allowlist_source
