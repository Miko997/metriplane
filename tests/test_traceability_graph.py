# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "build_traceability_graph.py"
GRAPH_PATH = ROOT / "docs" / "requirements" / "requirements.json"
LEDGER_PATH = ROOT / "docs" / "status" / "capability-test-ledger.json"
OBLIGATIONS_PATH = ROOT / "docs" / "status" / "release-test-obligations.json"
RESULT_SCHEMA_PATH = ROOT / "schemas" / "metriplane.traceability-validation-result.v1.schema.json"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("metriplane_traceability_tool", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    required = {
        "docs/status/functional-inventory.json",
        "docs/status/release-test-obligations.json",
        "docs/status/release-scenarios.json",
        "docs/status/support-profiles.json",
        "docs/status/supported-environments.json",
        "schemas/metriplane.functional-inventory.v1.schema.json",
        "schemas/metriplane.release-obligation-registry.v1.schema.json",
        "schemas/metriplane.requirement-graph.v1.schema.json",
        "schemas/metriplane.capability-test-ledger.v1.schema.json",
        "schemas/metriplane.traceability-validation-result.v1.schema.json",
        "tools/baseline_snapshot.py",
        "tools/build_traceability_graph.py",
        "tests/test_traceability_graph.py",
    }
    inventory = json.loads((ROOT / "docs/status/functional-inventory.json").read_bytes())
    for row in inventory["rows"]:
        required.add(row["source"]["path"])
        required.update(value.split("::", 1)[0] for value in row["validator_ids"])
    copied = {
        "docs/status/functional-inventory.json",
        "docs/status/release-test-obligations.json",
        "tools/build_traceability_graph.py",
        "tests/test_traceability_graph.py",
    }
    for relative in sorted(required):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / relative
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif relative in copied:
            shutil.copyfile(source, target)
        else:
            os.link(source, target)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-f", "-A"], cwd=root, check=True)
    return root


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0", "TZ": "UTC"})
    return subprocess.run(
        [sys.executable, "tools/build_traceability_graph.py", *arguments],
        cwd=root,
        env=environment,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_committed_graph_and_ledger_match_generator() -> None:
    assert tool.main(["--check"]) == 0


def test_generated_contracts_validate_against_schemas() -> None:
    graph = json.loads(GRAPH_PATH.read_bytes())
    ledger = json.loads(LEDGER_PATH.read_bytes())
    validator = tool._load_schema_validator()
    validator._internal_validate(graph, json.loads((ROOT / tool.GRAPH_SCHEMA_PATH).read_bytes()))
    validator._internal_validate(ledger, json.loads((ROOT / tool.LEDGER_SCHEMA_PATH).read_bytes()))
    assert ledger["graph_digest"] == tool.digest(graph)


def test_graph_has_exact_reverse_edges_and_no_orphans() -> None:
    graph = json.loads(GRAPH_PATH.read_bytes())
    nodes = {row["id"] for row in graph["nodes"]}
    edges = {(row["from"], row["to"], row["relation"]) for row in graph["edges"]}
    assert all((target, source, relation) in edges for source, target, relation in edges)
    assert nodes == {value for edge in edges for value in edge[:2]}
    assert graph["summary"]["orphan_count"] == 0
    assert graph["summary"]["dangling_edge_count"] == 0


def test_capability_rows_have_complete_six_kind_chain() -> None:
    graph = json.loads(GRAPH_PATH.read_bytes())
    kinds = {row["id"]: row["kind"] for row in graph["nodes"]}
    edges = graph["edges"]
    for row in json.loads(LEDGER_PATH.read_bytes())["rows"]:
        capability = row["capability_id"]
        neighbours = {edge["to"] for edge in edges if edge["from"] == capability}
        assert (
            set(
                row["requirement_ids"]
                + row["code_ids"]
                + row["obligation_ids"]
                + row["validator_ids"]
                + row["doc_ids"]
            )
            <= neighbours
        )
        assert {kinds[value] for value in neighbours} >= {"requirement", "code", "test", "doc"}
        assert all(kinds[value] == "rubric" for value in row["rubric_ids"])


def test_mp2014_chain_uses_real_registry_identities_and_imports_bootstrap_lineage() -> None:
    ledger = json.loads(LEDGER_PATH.read_bytes())
    rows = {row["capability_id"]: row for row in ledger["rows"]}
    traceability = rows[f"capability:{tool.CAPABILITY_ID}"]
    assert {f"requirement:{value}" for value in tool.CRITERION_OBLIGATIONS} <= set(
        traceability["requirement_ids"]
    )
    assert {f"test:{value}" for value in tool.OBLIGATION_FAMILIES} <= set(
        traceability["obligation_ids"]
    )
    bootstrap = {key for key in rows if key.startswith("capability:bootstrap:MP2-000.OBL.")}
    assert len(bootstrap) == 8
    registry = json.loads(OBLIGATIONS_PATH.read_bytes())
    for key in bootstrap:
        code_id = rows[key]["code_ids"][0]
        index = int(code_id.rsplit("/", 1)[1])
        assert registry["obligations"][index]["id"] == key.removeprefix("capability:bootstrap:")


def test_mp2014_obligations_are_cumulative_and_configured() -> None:
    registry = json.loads(OBLIGATIONS_PATH.read_bytes())
    criteria = {row["criterion_id"]: row for row in registry["criterion_requirements"]}
    obligations = {row["id"]: row for row in registry["obligations"]}
    assert len(criteria) == 280
    inventory_ids = {
        row["id"] for row in json.loads((ROOT / tool.INVENTORY_PATH).read_bytes())["rows"]
    }
    profile_ids = {
        row["id"]
        for row in json.loads((ROOT / "docs/status/support-profiles.json").read_bytes())["profiles"]
    }
    scenario_ids = {
        row["id"]
        for row in json.loads((ROOT / "docs/status/release-scenarios.json").read_bytes())[
            "scenarios"
        ]
    }
    for criterion_id, expected in tool.CRITERION_OBLIGATIONS.items():
        assert criteria[criterion_id]["mapping"] == {
            "state": "MAPPED",
            "obligation_ids": list(expected),
        }
        for identifier in expected:
            assert obligations[identifier]["implementation"] == {
                "state": "CONFIGURED",
                "executor_ids": [tool.EXECUTOR_ID],
            }
            assert set(obligations[identifier]["capability_ids"]) <= inventory_ids
            assert set(obligations[identifier]["profile_ids"]) <= profile_ids
            assert set(obligations[identifier]["scenario_ids"]) <= scenario_ids


def test_three_run_generation_is_byte_identical() -> None:
    snapshots = [tool._outputs() for _ in range(3)]
    assert snapshots[0] == snapshots[1] == snapshots[2]


def test_missing_requirement_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["trace_criterion_ids"] = ["MP2-014.A99"]
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "missing requirements" in completed.stderr


def test_missing_source_and_unknown_validator_are_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    discovery_row = next(row for row in inventory["rows"] if "type" in row["source"])
    discovery_row["source"]["path"] = "missing/source.py"
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "absent from the Git index" in completed.stderr

    root = _sandbox(tmp_path / "validator")
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["validator_ids"] = [
        "tests/test_traceability_graph.py::test_does_not_exist"
    ]
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "unknown validator" in completed.stderr


def test_unresolved_source_json_pointer_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["source"]["json_pointer"] = "/not-present-review-counterexample"
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "source JSON pointer does not resolve" in completed.stderr


def test_validator_child_suffix_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["validator_ids"] = [
        "tests/test_traceability_graph.py::test_substituted_result_is_rejected::not_a_child"
    ]
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "functional inventory schema validation failed" in completed.stderr


def test_non_test_helper_is_rejected_as_test_validator(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["validator_ids"] = ["tests/test_traceability_graph.py::_sandbox"]
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "functional inventory schema validation failed" in completed.stderr


def test_array_pointer_with_leading_zero_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    source = inventory["rows"][0]["source"]
    snapshot = json.loads((root / source["path"]).read_bytes())
    pointed = snapshot["commands_and_help"]["entries"][0]["argv"]
    source["json_pointer"] = "/commands_and_help/entries/00/argv"
    source["digest_sha256"] = tool.digest(pointed)
    source["count"] = len(pointed)
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    subprocess.run(["git", "add", os.fspath(tool.INVENTORY_PATH)], cwd=root, check=True)
    completed = _run(root, "--write")
    assert completed.returncode == 3
    assert "source JSON pointer does not resolve" in completed.stderr


def test_stale_generated_output_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    assert _run(root, "--write").returncode == 0
    (root / tool.GRAPH_PATH).write_bytes(b"{}")
    completed = _run(root, "--check")
    assert completed.returncode == 3
    assert "generated output is stale" in completed.stderr


def test_result_production_validates_and_never_overwrites(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    assert _run(root, "--write").returncode == 0
    evidence = root / "evidence"
    first = _run(root, "results", "--output-root", os.fspath(evidence))
    assert first.returncode == 0, first.stderr
    assert _run(root, "validate-results", "--evidence-root", os.fspath(evidence)).returncode == 0
    schema = json.loads((root / tool.RESULT_SCHEMA_PATH).read_bytes())
    for index in (1, 2):
        result = json.loads((evidence / f"{index:02d}-result.json").read_bytes())
        tool._load_schema_validator()._internal_validate(result, schema)
        assert result["verdict"] == "PASS"
    retry = _run(root, "results", "--output-root", os.fspath(evidence))
    assert retry.returncode == 3
    assert "refusing to overwrite" in retry.stderr


def test_result_commands_consume_the_exact_checked_snapshot(
    tmp_path: Path, monkeypatch: Any
) -> None:
    outputs = {
        tool.GRAPH_PATH: (ROOT / tool.GRAPH_PATH).read_bytes(),
        tool.LEDGER_PATH: (ROOT / tool.LEDGER_PATH).read_bytes(),
    }
    original_read_json = tool._read_json

    def guarded_read_json(path: Path) -> dict[str, object]:
        if path in {tool.GRAPH_PATH, tool.LEDGER_PATH}:
            raise AssertionError(f"validated output was reread without custody: {path}")
        return original_read_json(path)

    monkeypatch.setattr(tool, "_check", lambda: outputs)
    monkeypatch.setattr(tool, "_read_json", guarded_read_json)
    evidence = tmp_path / "evidence"
    tool._write_results(evidence)
    tool._validate_results(evidence)


def test_substituted_result_is_rejected(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    assert _run(root, "--write").returncode == 0
    evidence = root / "evidence"
    assert _run(root, "results", "--output-root", os.fspath(evidence)).returncode == 0
    path = evidence / "01-result.json"
    result = json.loads(path.read_bytes())
    result["graph_digest"] = "0" * 64
    path.write_bytes(tool.canonical_bytes(result))
    completed = _run(root, "validate-results", "--evidence-root", os.fspath(evidence))
    assert completed.returncode == 3
    assert "does not match" in completed.stderr


def test_stale_authoritative_input_invalidates_retained_results(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    assert _run(root, "--write").returncode == 0
    evidence = root / "evidence"
    assert _run(root, "results", "--output-root", os.fspath(evidence)).returncode == 0
    inventory_path = root / tool.INVENTORY_PATH
    inventory = json.loads(inventory_path.read_bytes())
    inventory["rows"][0]["name"] += " changed"
    inventory_path.write_bytes(tool.canonical_bytes(inventory))
    completed = _run(root, "validate-results", "--evidence-root", os.fspath(evidence))
    assert completed.returncode == 3


def test_broken_reverse_edge_invalidates_retained_results(tmp_path: Path) -> None:
    root = _sandbox(tmp_path)
    assert _run(root, "--write").returncode == 0
    evidence = root / "evidence"
    assert _run(root, "results", "--output-root", os.fspath(evidence)).returncode == 0
    graph_path = root / tool.GRAPH_PATH
    graph = json.loads(graph_path.read_bytes())
    graph["edges"].pop()
    graph_path.write_bytes(tool.canonical_bytes(graph))
    completed = _run(root, "validate-results", "--evidence-root", os.fspath(evidence))
    assert completed.returncode == 3
