# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "check_security_controls.py"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("security_control_checker_under_test", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _copy_contract(tmp_path: Path) -> Path:
    for relative in (
        "security-controls.json",
        "schemas/metriplane.security-controls.v1.schema.json",
        "docs/status/capability-test-ledger.json",
        "docs/status/task-work-orders.json",
        "docs/security/THREAT_MODEL.md",
        "tools/baseline_snapshot.py",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    registry = json.loads((ROOT / "security-controls.json").read_text(encoding="utf-8"))
    for control in registry["controls"]:
        for path_text in control["test_paths"]:
            target = tmp_path / path_text
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# retained test identity\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _registry(repo: Path) -> dict[str, Any]:
    return json.loads((repo / "security-controls.json").read_text(encoding="utf-8"))


def _write_registry(repo: Path, registry: dict[str, Any], *, bind: bool = True) -> None:
    if bind:
        registry["registry_digest"] = tool.registry_digest(registry)
    (repo / "security-controls.json").write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_repository_security_control_contract_passes() -> None:
    result = tool.validate(ROOT)
    assert result["verdict"] == "PASS"
    assert result["criteria"] == ["MP2-028.A01", "MP2-028.A02"]
    assert result["counts"] == {
        "boundaries": 6,
        "assets": 7,
        "actors": 6,
        "abuse_cases": 8,
        "controls": 10,
    }


def test_result_is_deterministic() -> None:
    first = tool.validate(ROOT)
    second = tool.validate(ROOT)
    assert first == second
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["abuse_cases"][0]["control_ids"].append("CTL-99"),
            "unknown control_ids",
        ),
        (lambda value: value["abuse_cases"].pop(), "unreferenced model rows"),
        (
            lambda value: value["controls"][0]["capability_ids"].append("capability:missing"),
            "unknown capabilities",
        ),
        (
            lambda value: value["controls"][0]["test_paths"].append("tests/missing.py"),
            "not tracked in the Git index",
        ),
    ],
)
def test_broken_trace_relationships_fail_closed(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    repo = _copy_contract(tmp_path)
    registry = _registry(repo)
    mutation(registry)
    _write_registry(repo, registry)
    with pytest.raises(tool.SecurityControlError, match=message):
        tool.validate(repo)


def test_stale_digest_fails_closed(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    registry = _registry(repo)
    registry["controls"][0]["title"] = "Changed without rebinding"
    _write_registry(repo, registry, bind=False)
    with pytest.raises(tool.SecurityControlError, match="registry_digest"):
        tool.validate(repo)


def test_unknown_governed_owner_fails_closed(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    registry = _registry(repo)
    registry["controls"][0]["owner"] = "MP2-999"
    _write_registry(repo, registry)
    with pytest.raises(tool.SecurityControlError, match="unknown governed owner MP2-999"):
        tool.validate(repo)


def test_test_path_cannot_escape_tests_tree(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    registry = _registry(repo)
    registry["controls"][0]["test_paths"] = ["tests/../tools/baseline_snapshot.py"]
    _write_registry(repo, registry)
    with pytest.raises(tool.SecurityControlError, match="not a normalized"):
        tool.validate(repo)


def test_symlinked_test_evidence_fails_closed(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    link = repo / "tests" / "symlink.py"
    link.symlink_to("ui_api/test_runner_service_api.py")
    subprocess.run(["git", "add", "tests/symlink.py"], cwd=repo, check=True)
    registry = _registry(repo)
    registry["controls"][0]["test_paths"] = ["tests/symlink.py"]
    _write_registry(repo, registry)
    with pytest.raises(tool.SecurityControlError, match="symlink component"):
        tool.validate(repo)


def test_duplicate_json_key_fails_closed(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    path = repo / "security-controls.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('"owner": "MP2-028",', '"owner": "MP2-028",\n  "owner": "MP2-028",', 1),
        encoding="utf-8",
    )
    with pytest.raises(tool.SecurityControlError, match="duplicate JSON key"):
        tool.validate(repo)


def test_documentation_drift_fails_closed(tmp_path: Path) -> None:
    repo = _copy_contract(tmp_path)
    path = repo / "docs/security/THREAT_MODEL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("`CTL-10`", "OIDC control"), encoding="utf-8"
    )
    with pytest.raises(tool.SecurityControlError, match="does not reference CTL-10"):
        tool.validate(repo)


def test_input_registry_is_not_mutated() -> None:
    before = _registry(ROOT)
    snapshot = copy.deepcopy(before)
    tool.validate(ROOT)
    assert before == snapshot


def test_materialized_validator_command_surface(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        tool.main(
            [
                "--repository-root",
                str(ROOT),
                "--registry",
                "security-controls.json",
                "--schema",
                "schemas/metriplane.security-controls.v1.schema.json",
                "--threat-model",
                "docs/security/THREAT_MODEL.md",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"
