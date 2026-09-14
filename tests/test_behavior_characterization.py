# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from metriplane import cli

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "characterize_supported_surface.py"
REGISTRY_PATH = ROOT / "docs" / "status" / "behavior-characterization.json"
INVENTORY_PATH = ROOT / "docs" / "status" / "functional-inventory.json"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("metriplane_behavior_characterization", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def obligation(identifier: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return cast(
        Callable[[Callable[..., Any]], Callable[..., Any]],
        pytest.mark.parametrize("_obligation", [pytest.param(identifier, id=identifier)]),
    )


def _registry() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(REGISTRY_PATH.read_bytes()))


@obligation("MP2-015.OBL.CHARACTERIZATION")
def test_registry_characterizes_every_governed_row(_obligation: str) -> None:
    registry = _registry()
    tool.validate_registry(ROOT, registry)
    inventory = json.loads(INVENTORY_PATH.read_bytes())
    expected = {
        row["id"]
        for row in inventory["rows"]
        if row["status"] in {"active", "deprecated"}
        and row["claim"]["classification"] in {"compatibility", "supported"}
    }
    assert registry["row_count"] == len(expected) == len(registry["rows"])
    assert {row["row_id"] for row in registry["rows"]} == expected


@obligation("MP2-015.OBL.COMPATIBILITY_RETENTION")
def test_characterization_retains_source_obligations_and_behavior(_obligation: str) -> None:
    inventory = {row["id"]: row for row in json.loads(INVENTORY_PATH.read_bytes())["rows"]}
    for row in _registry()["rows"]:
        source = inventory[row["row_id"]]
        assert row["retained_obligation_id"] == source["test"]
        assert row["profile_id"] == source["profile"]
        assert row["claim_classification"] == source["claim"]["classification"]
        assert row["row_digest"] == tool._digest(source)
        assert set(row["success"]) == set(row["failure"])


@obligation("MP2-015.OBL.DETERMINISM")
def test_characterization_generation_is_deterministic(_obligation: str) -> None:
    first = tool.build_registry(ROOT)
    second = tool.build_registry(ROOT)
    third = tool.build_registry(ROOT)
    assert tool._canonical(first) == tool._canonical(second) == tool._canonical(third)
    assert tool._canonical(first) == REGISTRY_PATH.read_bytes()


@obligation("MP2-015.OBL.NEGATIVE")
def test_characterization_rejects_missing_or_substituted_rows(_obligation: str) -> None:
    missing = copy.deepcopy(_registry())
    missing["rows"].pop()
    with pytest.raises(tool.CharacterizationError, match="stale or incomplete"):
        tool.validate_registry(ROOT, missing)
    substituted = copy.deepcopy(_registry())
    substituted["rows"][0]["failure"]["exit_code"] = 0
    with pytest.raises(tool.CharacterizationError, match="stale or incomplete"):
        tool.validate_registry(ROOT, substituted)


@obligation("MP2-015.OBL.CLEAN")
def test_source_entry_points_match_text_and_cleanliness_contract(_obligation: str) -> None:
    count = tool.execute_programs(
        ROOT,
        {
            "metriplane": Path(sys.executable).parent / "metriplane",
            "metriplane-run": Path(sys.executable).parent / "metriplane-run",
        },
    )
    root_rows = [
        row
        for row in _registry()["rows"]
        if row["kind"] != "cli_implicit_config"
        and row["success"]["argv"][0] in {"metriplane", "metriplane-run"}
    ]
    assert count == 2 * len(root_rows)


def test_implicit_config_route_has_success_and_failure_characterization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: list[str] = []

    def successful_run(argv: list[str]) -> int:
        received.extend(argv)
        return 0

    config = tmp_path / "valid.yaml"
    config.write_text("source_mode: replay\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_main_run", successful_run)
    assert cli.main(["--config", str(config)]) == 0
    assert received == ["--config", str(config)]
    assert capsys.readouterr() == ("", "")

    missing = tmp_path / "missing.yaml"
    process = subprocess.run(
        [sys.executable, "-m", "metriplane.cli", "--config", str(missing)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 1
    assert process.stdout == ""
    assert "traceback" in process.stderr.lower()
    assert "filenotfounderror" in process.stderr.lower()
