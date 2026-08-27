# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import discover_functional_surface as scanner

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = Path("docs/status/functional-inventory.json")
PROFILES = Path("docs/status/support-profiles.json")

DISCOVERY_INPUTS = (
    "adapters/maniskill_pickcube/pyproject.toml",
    "adapters/maniskill_pickcube/src/maniskill_pickcube/cli.py",
    "adapters/massrobotics_amr/pyproject.toml",
    "adapters/massrobotics_amr/src/massrobotics_amr_adapter/cli.py",
    "adapters/robomimic_lowdim/pyproject.toml",
    "adapters/robomimic_lowdim/src/robomimic_lowdim/cli.py",
    "adapters/ros2_mcap/pyproject.toml",
    "adapters/ros2_mcap/src/ros2_mcap_adapter/cli.py",
    "adapters/source_adapter_sdk/pyproject.toml",
    "metriplane/assistant/cli.py",
    "metriplane/atlas/cli.py",
    "metriplane/camera_trust/cli.py",
    "metriplane/cli.py",
    "metriplane/contracts/cli.py",
    "metriplane/counterfactuals/cli.py",
    "metriplane/demo/__init__.py",
    "metriplane/external_sources/cli.py",
    "metriplane/run.py",
    "metriplane/runner/cli_command_center.py",
    "metriplane/sentinel/cli_incidents.py",
    "metriplane/sentinel/cli_query.py",
    "metriplane/sentinel/cli_registry.py",
    "metriplane/sentinel/cli_rules.py",
    "metriplane/sentinel/cli_runtime.py",
    "metriplane/testing/cli.py",
    "metriplane/trace/cli_traces.py",
    "pyproject.toml",
)

ROOT_DISPATCHES = {
    "ask",
    "atlas",
    "camera-trust",
    "cleanup",
    "command-center",
    "contracts",
    "counterfactual",
    "demo",
    "doctor",
    "external",
    "incidents",
    "objects",
    "query",
    "replay",
    "restart",
    "rules",
    "run",
    "sentinel",
    "start",
    "status",
    "stop",
    "test",
    "traces",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _repository_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (
        *DISCOVERY_INPUTS,
        scanner.SCANNER_PATH,
        INVENTORY.as_posix(),
        PROFILES.as_posix(),
    ):
        _copy_file(ROOT / relative, root / relative)
    return root


def _run(root: Path, command: str) -> int:
    return scanner.run(
        command,
        repository_root=root,
        inventory=INVENTORY,
        profiles=PROFILES,
        minimum_leaf_actions=71,
    )


def _generated_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in document["rows"] if row["id"].startswith(scanner.ROW_PREFIX)]


def test_discovery_reproduces_the_exact_current_cli_census() -> None:
    result = scanner.discover(ROOT)

    assert result.root_dispatches == 23
    assert result.parser_declarations == 91
    assert result.parser_leaves == 75
    assert result.parser_groups == 16
    assert result.root_console_scripts == 2
    assert result.adapter_console_scripts == 4
    assert result.entry_points == 6
    assert result.aliases == 1
    assert result.implicit_config_routes == 1
    assert len(result.rows) == 122


def test_committed_inventory_matches_current_cli_surface() -> None:
    candidate_inventory, candidate_profiles, discovery = scanner.build_candidates(
        ROOT,
        ROOT / INVENTORY,
        ROOT / PROFILES,
        minimum_leaf_actions=71,
    )

    assert candidate_inventory == _load(ROOT / INVENTORY)
    assert candidate_profiles == _load(ROOT / PROFILES)
    assert len(_generated_rows(candidate_inventory)) == len(discovery.rows) == 122


def test_root_dispatch_entry_points_alias_and_implicit_route_are_exact() -> None:
    rows = scanner.discover(ROOT).rows
    dispatches = {
        row["name"].removeprefix("metriplane ")
        for row in rows
        if row["test"] == "MP2-011.OBL.ROOT_DISPATCH"
    }
    entry_points = {row["name"] for row in rows if row["kind"] == "cli_entry_point"}
    aliases = [row for row in rows if row["kind"] == "cli_alias"]
    implicit = [row for row in rows if row["kind"] == "cli_implicit_config"]

    assert dispatches == ROOT_DISPATCHES
    assert entry_points == {
        "maniskill-pickcube",
        "metriplane",
        "metriplane-massrobotics-amr",
        "metriplane-ros2-mcap",
        "metriplane-run",
        "robomimic-lowdim",
    }
    assert [(row["name"], row["source"]["locator"]) for row in aliases] == [
        (
            "metriplane atlas privacy anonymize",
            "metriplane atlas privacy anonymize->metriplane atlas privacy pseudonymize",
        )
    ]
    assert [row["id"] for row in implicit] == ["MP2-011.CLI.IMPLICIT_CONFIG"]


def test_cli_profile_is_closed_measured_and_not_an_environment_claim() -> None:
    inventory = _load(ROOT / INVENTORY)
    profiles = _load(ROOT / PROFILES)
    profile = next(item for item in profiles["profiles"] if item["id"] == scanner.PROFILE_ID)
    generated = _generated_rows(inventory)

    assert profile["owner"] == "MP2-011"
    assert profile["kind"] == "repository_cli_discovery"
    assert profile["support_disposition"] == "measured"
    assert profile["claim"]["classification"] == "compatibility"
    assert "no runtime platform support claim" in profile["claim"]["statement"]
    assert {row["profile"] for row in generated} == {scanner.PROFILE_ID}
    assert all(row["owner"] == "MP2-011" for row in generated)


def test_generated_rows_are_canonical_closed_and_source_bound() -> None:
    rows = list(scanner.discover(ROOT).rows)
    ids = [row["id"] for row in rows]
    names = [row["name"] for row in rows if row["kind"] != "cli_entry_point"]

    assert ids == sorted(set(ids))
    assert len(names) == len(set(names))
    for row in rows:
        source = row["source"]
        assert source["type"] == "repository_discovery"
        assert (
            source["digest_sha256"]
            == hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
        )
        assert row["consumer_task_ids"] == sorted(row["consumer_task_ids"])
        assert row["trace_criterion_ids"] == sorted(row["trace_criterion_ids"])
        assert row["validator_ids"] == sorted(row["validator_ids"])


def test_check_mode_is_read_only_when_registry_drift_exists(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    assert _run(root, "generate") == 0
    inventory_path = root / INVENTORY
    profiles_path = root / PROFILES
    before_inventory = inventory_path.read_bytes()
    before_profiles = profiles_path.read_bytes()
    source = root / "metriplane" / "atlas" / "cli.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert _run(root, "check") == 1
    assert inventory_path.read_bytes() == before_inventory
    assert profiles_path.read_bytes() == before_profiles


def test_generate_preserves_foreign_objects_and_is_three_run_idempotent(
    tmp_path: Path,
) -> None:
    root = _repository_fixture(tmp_path)
    before_inventory = _load(root / INVENTORY)
    before_profiles = _load(root / PROFILES)
    foreign_rows = copy.deepcopy(
        [row for row in before_inventory["rows"] if row["owner"] != "MP2-011"]
    )
    foreign_profiles = copy.deepcopy(
        [row for row in before_profiles["profiles"] if row["owner"] != "MP2-011"]
    )

    assert _run(root, "generate") == 0
    first = ((root / INVENTORY).read_bytes(), (root / PROFILES).read_bytes())
    assert _run(root, "generate") == 0
    second = ((root / INVENTORY).read_bytes(), (root / PROFILES).read_bytes())
    assert _run(root, "generate") == 0
    third = ((root / INVENTORY).read_bytes(), (root / PROFILES).read_bytes())

    assert first == second == third
    after_inventory = _load(root / INVENTORY)
    after_profiles = _load(root / PROFILES)
    assert [row for row in after_inventory["rows"] if row["owner"] != "MP2-011"] == foreign_rows
    assert [
        row for row in after_profiles["profiles"] if row["owner"] != "MP2-011"
    ] == foreign_profiles


def test_dynamic_add_parser_name_fails_closed(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    path = root / "metriplane" / "contracts" / "cli.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('sub.add_parser("validate"', "sub.add_parser(command_name"), encoding="utf-8"
    )

    with pytest.raises(scanner.DiscoveryError, match="dynamic add_parser names"):
        scanner.discover(root)


def test_dynamic_alias_fails_closed(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    path = root / "metriplane" / "atlas" / "cli.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('aliases=["anonymize"]', "aliases=compatibility_aliases"), encoding="utf-8"
    )

    with pytest.raises(scanner.DiscoveryError, match="dynamic add_parser aliases"):
        scanner.discover(root)


def test_unresolved_entry_point_target_fails_closed(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("metriplane.run:main", "metriplane.missing:main"), encoding="utf-8"
    )

    with pytest.raises(scanner.DiscoveryError, match="exactly one source"):
        scanner.discover(root)


def test_source_symlink_escape_fails_closed(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def main():\n    return 0\n", encoding="utf-8")
    target = root / "metriplane" / "run.py"
    target.unlink()
    target.symlink_to(outside)

    with pytest.raises(scanner.DiscoveryError, match="exactly one source|escapes"):
        scanner.discover(root)


def test_leaf_action_floor_is_enforced() -> None:
    with pytest.raises(scanner.DiscoveryError, match="leaf-action floor failed"):
        scanner.discover(ROOT, minimum_leaf_actions=76)


def test_malformed_registry_fails_before_any_write(tmp_path: Path) -> None:
    root = _repository_fixture(tmp_path)
    inventory = root / INVENTORY
    profiles = root / PROFILES
    inventory.write_text('{"rows":[],"rows":[]}\n', encoding="utf-8")
    before = (inventory.read_bytes(), profiles.read_bytes())

    with pytest.raises(scanner.DiscoveryError, match="duplicate JSON key"):
        _run(root, "generate")
    assert (inventory.read_bytes(), profiles.read_bytes()) == before


def test_second_replace_failure_rolls_back_the_registry_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository_fixture(tmp_path)
    inventory = root / INVENTORY
    profiles = root / PROFILES
    before = (inventory.read_bytes(), profiles.read_bytes())
    source = root / "metriplane" / "atlas" / "cli.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    real_replace = os.replace
    calls = 0

    def fail_second(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(scanner.os, "replace", fail_second)
    with pytest.raises(OSError, match="injected second replace failure"):
        _run(root, "generate")

    assert (inventory.read_bytes(), profiles.read_bytes()) == before


def test_cli_check_reports_the_canonical_summary() -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/discover_functional_surface.py",
            "check",
            "--repository-root",
            ".",
            "--inventory",
            str(INVENTORY),
            "--profiles",
            str(PROFILES),
            "--minimum-leaf-actions",
            "71",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "aliases": 1,
        "entry_points": 6,
        "groups": 16,
        "leaves": 75,
        "parser_declarations": 91,
        "root_dispatches": 23,
        "rows": 122,
    }
