#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT
"""Build and validate the governed MP2-014 traceability graph."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path("docs/status/functional-inventory.json")
INVENTORY_SCHEMA_PATH = Path("schemas/metriplane.functional-inventory.v1.schema.json")
OBLIGATIONS_PATH = Path("docs/status/release-test-obligations.json")
GRAPH_PATH = Path("docs/requirements/requirements.json")
LEDGER_PATH = Path("docs/status/capability-test-ledger.json")
GRAPH_SCHEMA_PATH = Path("schemas/metriplane.requirement-graph.v1.schema.json")
LEDGER_SCHEMA_PATH = Path("schemas/metriplane.capability-test-ledger.v1.schema.json")
RESULT_SCHEMA_PATH = Path("schemas/metriplane.traceability-validation-result.v1.schema.json")
TEST_PATH = Path("tests/test_traceability_graph.py")
PROFILE_ID = "repository.current-main.static-ui-census"
ENVIRONMENT_ID = "current-ci-linux-py312"
EXECUTOR_ID = "MP2-014.EXEC.TRACEABILITY"
SCENARIO_ID = "COMPLETE_CURRENT_CUMULATIVE"
CAPABILITY_ID = "MP2-012.UI.ACTION.TOOL_BUILD_TRACEABILITY_GRAPH"
BOOTSTRAP_PREFIX = "MP2-000.OBL."
RELEASE_ORDER = ("v0.4", "v0.5", "v0.6", "v0.7", "v0.8", "v0.9", "v1.0", "post-v1.0")
OBLIGATION_FAMILIES = {
    "MP2-014.OBL.BASELINE": ("BASELINE",),
    "MP2-014.OBL.GRAPH_BUILD": ("POSITIVE",),
    "MP2-014.OBL.GRAPH_NEGATIVE": ("NEGATIVE",),
    "MP2-014.OBL.BOUNDARY_PARSER": ("BOUNDARY", "PARSER"),
    "MP2-014.OBL.THREE_RUN_DETERMINISM": ("DETERMINISM",),
    "MP2-014.OBL.TRACE_CLOSURE": ("TRACE",),
    "MP2-014.OBL.UI_DOCS": ("UI", "DOCS"),
    "MP2-014.OBL.BOOTSTRAP_LINEAGE": ("TRACE", "BASELINE"),
    "MP2-014.OBL.CLEAN": ("CLEAN",),
}
CRITERION_OBLIGATIONS = {
    "MP2-014.A01": tuple(OBLIGATION_FAMILIES),
    "MP2-014.A02": tuple(key for key in OBLIGATION_FAMILIES if key != "MP2-014.OBL.UI_DOCS"),
}

JsonObject = dict[str, Any]


def _load_schema_validator() -> ModuleType:
    path = ROOT / "tools" / "baseline_snapshot.py"
    spec = importlib.util.spec_from_file_location("metriplane_schema_validator", path)
    if spec is None or spec.loader is None:
        _fail(f"cannot load schema validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TraceabilityError(ValueError):
    """The governed graph, ledger, or retained result is invalid."""


def _fail(message: str) -> NoReturn:
    raise TraceabilityError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return digest_bytes(canonical_bytes(value))


def _read_json(path: Path) -> JsonObject:
    try:
        value = json.loads((ROOT / path).read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise TraceabilityError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"{path} must contain a JSON object")
    return value


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _source_label(row: JsonObject) -> str:
    source = row.get("source", {})
    path = source.get("path")
    if not isinstance(path, str) or not path:
        _fail(f"capability {row.get('id')!r} lacks a source path")
    pointer = source.get("json_pointer")
    return path if not pointer else f"{path}#{pointer}"


def _resolve_json_pointer(data: bytes, pointer: Any, capability_id: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        _fail(f"capability {capability_id} has a malformed source JSON pointer")
    try:
        pointed: Any = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraceabilityError(
            f"capability {capability_id} source JSON cannot be parsed: {exc}"
        ) from exc
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?:[^01]|$)", raw_token):
            _fail(f"capability {capability_id} has a malformed source JSON pointer")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(pointed, dict) and token in pointed:
            pointed = pointed[token]
        elif (
            isinstance(pointed, list)
            and re.fullmatch(r"0|[1-9][0-9]*", token) is not None
            and int(token) < len(pointed)
        ):
            pointed = pointed[int(token)]
        else:
            _fail(f"capability {capability_id} source JSON pointer does not resolve")
    return pointed


def _staged_sources(paths: set[str]) -> dict[str, tuple[str, str, bytes]]:
    completed = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        _fail("cannot read the Git index")
    entries: dict[str, tuple[str, str]] = {}
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise TraceabilityError("malformed Git index entry") from exc
        if stage == "0":
            entries[path] = (mode, oid)
    missing = sorted(paths - entries.keys())
    if missing:
        _fail(f"referenced source path is absent from the Git index: {missing[0]}")
    result: dict[str, tuple[str, str, bytes]] = {}
    for path in sorted(paths):
        mode, oid = entries[path]
        target = ROOT / path
        try:
            data = os.readlink(target).encode() if mode == "120000" else target.read_bytes()
        except OSError as exc:
            raise TraceabilityError(f"cannot read referenced source {path}: {exc}") from exc
        if _git_blob(data) != oid:
            _fail(f"referenced worktree source differs from its indexed blob: {path}")
        result[path] = (mode, oid, data)
    return result


def _validate_inventory_references(inventory: JsonObject, obligations: JsonObject) -> None:
    rows = inventory.get("rows")
    if not isinstance(rows, list):
        _fail("functional inventory rows are missing")
    paths = {row["source"]["path"] for row in rows}
    for row in rows:
        paths.update(value.split("::", 1)[0] for value in row["validator_ids"])
    staged = _staged_sources(paths)
    obligation_ids = {row["id"] for row in obligations["obligations"]}
    parsed_tests: dict[str, set[str]] = {}
    for row in rows:
        source = row["source"]
        mode, oid, data = staged[source["path"]]
        del mode
        locator = source.get("locator")
        if isinstance(locator, str) and locator.startswith("git-blob:"):
            match = re.match(r"git-blob:([0-9a-f]{40})(?:;|$)", locator)
            if match is None or match.group(1) != oid:
                _fail(f"capability {row['id']} has a stale Git blob locator")
        pointer = source.get("json_pointer")
        if pointer is None:
            actual_digest = digest_bytes(data)
        else:
            pointed = _resolve_json_pointer(data, pointer, row["id"])
            actual_digest = digest(pointed)
            count = source.get("count")
            if count is not None and (
                not isinstance(count, int) or not isinstance(pointed, list) or len(pointed) != count
            ):
                _fail(f"capability {row['id']} has a stale source count")
        if actual_digest != source["digest_sha256"]:
            _fail(f"capability {row['id']} has a stale source digest")
        if row["test"] not in obligation_ids:
            _fail(f"capability {row['id']} refers to an unknown obligation: {row['test']}")
        for validator_id in row["validator_ids"]:
            path, separator, symbol = validator_id.partition("::")
            if not separator or not symbol:
                _fail(f"capability {row['id']} has a malformed validator identity")
            if path not in parsed_tests:
                try:
                    tree = ast.parse(staged[path][2], filename=path)
                except (SyntaxError, UnicodeError) as exc:
                    raise TraceabilityError(f"cannot parse validator source {path}: {exc}") from exc
                parsed_tests[path] = {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol) is None:
                _fail(f"capability {row['id']} has a malformed validator identity")
            function = symbol
            if function not in parsed_tests[path]:
                _fail(f"capability {row['id']} refers to an unknown validator: {validator_id}")


def _add_pair(edges: set[tuple[str, str, str]], left: str, right: str, relation: str) -> None:
    edges.add((left, right, relation))
    edges.add((right, left, relation))


def _build_graph(inventory: JsonObject, obligations: JsonObject) -> tuple[JsonObject, JsonObject]:
    criteria = {row["criterion_id"]: row for row in obligations["criterion_requirements"]}
    nodes: dict[str, JsonObject] = {}
    edges: set[tuple[str, str, str]] = set()
    ledger_rows: list[JsonObject] = []

    def add_node(identifier: str, kind: str, label: str, first: str, status: str) -> None:
        candidate = {
            "id": identifier,
            "kind": kind,
            "label": label,
            "first_release": first,
            "change_releases": [],
            "status": status,
        }
        previous = nodes.get(identifier)
        if previous is None:
            nodes[identifier] = candidate
            return
        if previous["kind"] != kind or previous["label"] != label:
            _fail(f"node identity collision: {identifier}")
        releases = {previous["first_release"], *previous["change_releases"], first}
        try:
            ordered = sorted(releases, key=RELEASE_ORDER.index)
        except ValueError as exc:
            raise TraceabilityError(f"unknown release identity on node {identifier}") from exc
        previous["first_release"] = ordered[0]
        previous["change_releases"] = ordered[1:]
        if status == "active":
            previous["status"] = "active"

    for criterion_id, criterion in sorted(criteria.items()):
        first = criterion["first_required_release"]
        status = "active" if criterion["mapping"]["state"] == "MAPPED" else "unresolved"
        add_node(
            _node_id("requirement", criterion_id),
            "requirement",
            criterion["predicate"],
            first,
            status,
        )
        add_node(_node_id("rubric", criterion_id), "rubric", criterion["predicate"], first, status)
        _add_pair(
            edges,
            _node_id("requirement", criterion_id),
            _node_id("rubric", criterion_id),
            "assessed_by",
        )

    for row in sorted(inventory["rows"], key=lambda item: item["id"]):
        capability_id = _node_id("capability", row["id"])
        criterion_values = list(row["trace_criterion_ids"])
        if row["id"] == CAPABILITY_ID:
            criterion_values.extend(CRITERION_OBLIGATIONS)
        requirement_ids = [
            _node_id("requirement", value) for value in sorted(set(criterion_values))
        ]
        missing = [value for value in requirement_ids if value not in nodes]
        if missing:
            _fail(f"capability {row['id']} refers to missing requirements: {missing}")
        code_ids = [_node_id("code", _source_label(row))]
        obligation_values = [row["test"]]
        if row["id"] == CAPABILITY_ID:
            obligation_values.extend(OBLIGATION_FAMILIES)
        obligation_ids = [_node_id("test", value) for value in sorted(set(obligation_values))]
        validator_ids = [_node_id("test", value) for value in row["validator_ids"]]
        doc_ids = [_node_id("doc", row["source"]["path"])]
        rubric_ids = [_node_id("rubric", value) for value in sorted(set(criterion_values))]
        status = (
            "mapped"
            if all(nodes[value]["status"] == "active" for value in requirement_ids)
            else "unresolved"
        )
        first = min(
            criteria[value.removeprefix("requirement:")]["first_required_release"]
            for value in requirement_ids
        )
        add_node(
            capability_id,
            "capability",
            row["name"],
            first,
            "active" if status == "mapped" else "unresolved",
        )
        for identifier in code_ids:
            add_node(identifier, "code", identifier.removeprefix("code:"), first, "active")
            _add_pair(edges, capability_id, identifier, "implemented_by")
        for identifier in obligation_ids + validator_ids:
            add_node(identifier, "test", identifier.removeprefix("test:"), first, "active")
            _add_pair(edges, capability_id, identifier, "verified_by")
        for identifier in doc_ids:
            add_node(identifier, "doc", identifier.removeprefix("doc:"), first, "active")
            _add_pair(edges, capability_id, identifier, "documented_by")
        for identifier in requirement_ids:
            _add_pair(edges, identifier, capability_id, "requires")
        ledger_rows.append(
            {
                "capability_id": capability_id,
                "requirement_ids": sorted(requirement_ids),
                "code_ids": sorted(code_ids),
                "obligation_ids": sorted(obligation_ids),
                "validator_ids": sorted(validator_ids),
                "doc_ids": sorted(doc_ids),
                "rubric_ids": sorted(rubric_ids),
                "first_release": first,
                "change_releases": [],
                "mapping_status": status,
            }
        )

    obligation_rows = list(obligations["obligations"])
    for index, obligation in enumerate(obligation_rows):
        identifier = obligation["id"]
        if not identifier.startswith(BOOTSTRAP_PREFIX):
            continue
        capability_id = _node_id("capability", f"bootstrap:{identifier}")
        requirement_ids = [_node_id("requirement", value) for value in obligation["criterion_ids"]]
        code_id = _node_id(
            "code", f"docs/status/release-test-obligations.json#/obligations/{index}"
        )
        test_id = _node_id("test", identifier)
        doc_id = _node_id("doc", "docs/status/release-test-obligations.json")
        rubric_ids = [_node_id("rubric", value) for value in obligation["criterion_ids"]]
        add_node(
            capability_id, "capability", f"Bootstrap lineage {identifier}", "v0.4", "unresolved"
        )
        add_node(code_id, "code", code_id.removeprefix("code:"), "v0.4", "active")
        add_node(test_id, "test", identifier, "v0.4", "active")
        add_node(doc_id, "doc", doc_id.removeprefix("doc:"), "v0.4", "active")
        for requirement_id in requirement_ids:
            _add_pair(edges, requirement_id, capability_id, "requires")
        _add_pair(edges, capability_id, code_id, "implemented_by")
        _add_pair(edges, capability_id, test_id, "verified_by")
        _add_pair(edges, capability_id, doc_id, "documented_by")
        ledger_rows.append(
            {
                "capability_id": capability_id,
                "requirement_ids": sorted(requirement_ids),
                "code_ids": [code_id],
                "obligation_ids": [test_id],
                "validator_ids": [test_id],
                "doc_ids": [doc_id],
                "rubric_ids": sorted(rubric_ids),
                "first_release": "v0.4",
                "change_releases": [],
                "mapping_status": "unresolved",
            }
        )

    node_ids = set(nodes)
    dangling = [edge for edge in edges if edge[0] not in node_ids or edge[1] not in node_ids]
    incident = {value for edge in edges for value in edge[:2]}
    orphans = node_ids - incident
    if dangling or orphans:
        _fail(f"graph is not closed: dangling={len(dangling)}, orphans={len(orphans)}")
    graph: JsonObject = {
        "schema_version": "metriplane.requirement-graph.v1",
        "owner": "MP2-014",
        "source_digests": {
            os.fspath(INVENTORY_PATH): digest(inventory),
            os.fspath(OBLIGATIONS_PATH): digest(obligations),
        },
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [
            {"from": source, "to": target, "relation": relation}
            for source, target, relation in sorted(edges)
        ],
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "orphan_count": 0,
            "dangling_edge_count": 0,
            "unresolved_node_count": sum(row["status"] == "unresolved" for row in nodes.values()),
        },
    }
    ledger: JsonObject = {
        "schema_version": "metriplane.capability-test-ledger.v1",
        "owner": "MP2-014",
        "graph_digest": digest(graph),
        "rows": sorted(ledger_rows, key=lambda row: row["capability_id"]),
        "summary": {
            "capability_count": len(ledger_rows),
            "mapped_count": sum(row["mapping_status"] == "mapped" for row in ledger_rows),
            "unresolved_count": sum(row["mapping_status"] == "unresolved" for row in ledger_rows),
        },
    }
    return graph, ledger


def _configured_obligations(registry: JsonObject) -> JsonObject:
    result = cast(JsonObject, json.loads(json.dumps(registry)))
    criteria = {row["criterion_id"]: row for row in result["criterion_requirements"]}
    authority = criteria["MP2-014.A01"]["authority"]
    for criterion_id, obligation_ids in CRITERION_OBLIGATIONS.items():
        criteria[criterion_id]["mapping"] = {
            "state": "MAPPED",
            "obligation_ids": list(obligation_ids),
        }
    test_bytes = (ROOT / TEST_PATH).read_bytes()
    source = {
        "binding": "candidate_source_blob",
        "repository": "Miko997/metriplane",
        "path": os.fspath(TEST_PATH),
        "git_blob": _git_blob(test_bytes),
        "git_mode": "100644",
        "source_bytes": {
            "path": os.fspath(TEST_PATH),
            "bytes": len(test_bytes),
            "sha256": digest_bytes(test_bytes),
        },
    }
    owner = {
        "kind": "pytest_node",
        "source_path": os.fspath(TEST_PATH),
        "source": source,
        "node_id": "tests/test_traceability_graph.py",
    }
    recipe = {
        "owner": owner,
        "launch": {
            "kind": "argv",
            "argv": [
                {"kind": "binding", "name": "python_executable"},
                {"kind": "literal", "value": "-m"},
                {"kind": "literal", "value": "pytest"},
                {"kind": "literal", "value": "-q"},
                {"kind": "literal", "value": os.fspath(TEST_PATH)},
            ],
            "cwd": "checkout_root",
            "environment": [],
            "unset_environment": [],
            "shell": False,
        },
        "input_slots": [
            {
                "name": "python_executable",
                "kind": "executable",
                "binding_owner": "environment_observation",
                "must_exist_before_execution": True,
            },
            {
                "name": "checkout_root",
                "kind": "directory",
                "binding_owner": "candidate_identity",
                "must_exist_before_execution": True,
            },
        ],
        "input_sidecars": [],
        "resources": [],
        "timeout_seconds": 900,
        "expected_process_exits": [0],
        "expected_outputs": [],
        "thresholds": [],
        "cleanliness": {
            "unexpected_warnings": "FAIL",
            "unexpected_skip": "FAIL",
            "unexpected_xfail": "FAIL",
            "unrecorded_retry": "FAIL",
            "process_or_file_leak": "FAIL",
        },
        "effect_class": "read_only",
        "required_operation_owner": None,
        "terminal_owner": "metriplane/release_control.py",
    }
    executor = {
        "id": EXECUTOR_ID,
        "phase": "qualification",
        "authority": authority,
        "binding": {"state": "CONFIGURED", "recipe": recipe},
    }
    result["executors"] = [row for row in result["executors"] if row["id"] != EXECUTOR_ID] + [
        executor
    ]
    existing = {row["id"]: row for row in result["obligations"]}
    for identifier, families in OBLIGATION_FAMILIES.items():
        criterion_ids = [
            key for key, values in CRITERION_OBLIGATIONS.items() if identifier in values
        ]
        existing[identifier] = {
            "id": identifier,
            "owner_task_id": "MP2-014",
            "lifecycle": "active",
            "first_required_release": "v0.4",
            "authority": authority,
            "criterion_ids": criterion_ids,
            "family_ids": list(families),
            "capability_ids": [CAPABILITY_ID],
            "profile_ids": [PROFILE_ID],
            "environment_ids": [ENVIRONMENT_ID],
            "scenario_ids": [SCENARIO_ID],
            "implementation": {"state": "CONFIGURED", "executor_ids": [EXECUTOR_ID]},
            "superseded_by": [],
            "supersession_authority": [],
        }
    result["obligations"] = [existing[key] for key in sorted(existing)]
    result["executors"] = sorted(result["executors"], key=lambda row: row["id"])
    return result


def build() -> tuple[JsonObject, JsonObject, JsonObject]:
    inventory = _read_json(INVENTORY_PATH)
    try:
        _load_schema_validator()._internal_validate(inventory, _read_json(INVENTORY_SCHEMA_PATH))
    except Exception as exc:
        raise TraceabilityError(f"functional inventory schema validation failed: {exc}") from exc
    obligations = _configured_obligations(_read_json(OBLIGATIONS_PATH))
    _validate_inventory_references(inventory, obligations)
    graph, ledger = _build_graph(inventory, obligations)
    return obligations, graph, ledger


def _validate(obligations: JsonObject, graph: JsonObject, ledger: JsonObject) -> None:
    validator = _load_schema_validator()
    if obligations.get("schema_version") != "metriplane.release-test-obligations.v2":
        _fail("unsupported release obligation registry")
    if len(obligations.get("criterion_requirements", [])) != 280:
        _fail("release obligation registry must retain all 280 criterion rows")
    capability_ids = {row["id"] for row in _read_json(INVENTORY_PATH)["rows"]}
    profile_ids = {
        row["id"] for row in _read_json(Path("docs/status/support-profiles.json"))["profiles"]
    }
    environment_ids = {
        row["id"]
        for row in _read_json(Path("docs/status/supported-environments.json"))["environments"]
    }
    scenario_ids = {
        row["id"] for row in _read_json(Path("docs/status/release-scenarios.json"))["scenarios"]
    }
    executor_ids = {row["id"] for row in obligations["executors"]}
    for obligation in obligations["obligations"]:
        implementation = obligation["implementation"]
        if implementation["state"] != "CONFIGURED":
            continue
        references = (
            ("capability", set(obligation["capability_ids"]), capability_ids),
            ("profile", set(obligation["profile_ids"]), profile_ids),
            ("environment", set(obligation["environment_ids"]), environment_ids),
            ("scenario", set(obligation["scenario_ids"]), scenario_ids),
            ("executor", set(implementation["executor_ids"]), executor_ids),
        )
        for label, configured, known in references:
            missing = configured - known
            if missing:
                _fail(
                    f"configured obligation {obligation['id']} has unknown {label}: {sorted(missing)[0]}"
                )
    validator._internal_validate(graph, _read_json(GRAPH_SCHEMA_PATH))
    validator._internal_validate(ledger, _read_json(LEDGER_SCHEMA_PATH))
    pairs = {(row["from"], row["to"], row["relation"]) for row in graph["edges"]}
    if any((target, source, relation) not in pairs for source, target, relation in pairs):
        _fail("every graph edge must have an exact reverse edge")
    if ledger["graph_digest"] != digest(graph):
        _fail("ledger graph digest does not bind the generated graph")


def _outputs() -> dict[Path, bytes]:
    obligations, graph, ledger = build()
    _validate(obligations, graph, ledger)
    return {
        OBLIGATIONS_PATH: canonical_bytes(obligations),
        GRAPH_PATH: canonical_bytes(graph),
        LEDGER_PATH: canonical_bytes(ledger),
    }


def _write() -> None:
    for path, data in _outputs().items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _check() -> dict[Path, bytes]:
    outputs = _outputs()
    for path, expected in outputs.items():
        try:
            actual = (ROOT / path).read_bytes()
        except OSError as exc:
            raise TraceabilityError(f"missing generated output {path}: {exc}") from exc
        if actual != expected:
            _fail(f"generated output is stale: {path}")
    return outputs


def _result(criterion_id: str, graph: JsonObject, ledger: JsonObject) -> JsonObject:
    pairs = {(row["from"], row["to"], row["relation"]) for row in graph["edges"]}
    bootstrap_ids = {
        row["capability_id"]
        for row in ledger["rows"]
        if row["capability_id"].startswith("capability:bootstrap:MP2-000.OBL.")
    }
    traceability_rows = [
        row
        for row in ledger["rows"]
        if row["capability_id"] == _node_id("capability", CAPABILITY_ID)
    ]
    checks = {
        "schema_valid": True,
        "zero_dangling_edges": graph["summary"]["dangling_edge_count"] == 0,
        "zero_orphans": graph["summary"]["orphan_count"] == 0,
        "bidirectional_chain": all(
            (target, source, relation) in pairs for source, target, relation in pairs
        ),
        "cumulative_obligations": len(bootstrap_ids) == 8
        and len(traceability_rows) == 1
        and {_node_id("test", value) for value in OBLIGATION_FAMILIES}
        <= set(traceability_rows[0]["obligation_ids"]),
    }
    return {
        "schema_version": "metriplane.traceability-validation-result.v1",
        "criterion_id": criterion_id,
        "verdict": "PASS" if all(checks.values()) else "BLOCKED",
        "graph_digest": digest(graph),
        "ledger_digest": digest(ledger),
        "checks": checks,
    }


def _write_results(output_root: Path) -> None:
    outputs = _check()
    graph = cast(JsonObject, json.loads(outputs[GRAPH_PATH]))
    ledger = cast(JsonObject, json.loads(outputs[LEDGER_PATH]))
    output_root.mkdir(parents=True, exist_ok=True)
    for index, criterion_id in enumerate(CRITERION_OBLIGATIONS, 1):
        target = output_root / f"{index:02d}-result.json"
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise TraceabilityError(f"refusing to overwrite retained result: {target}") from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(_result(criterion_id, graph, ledger)))


def _validate_results(evidence_root: Path) -> None:
    outputs = _check()
    schema = _read_json(RESULT_SCHEMA_PATH)
    validator = _load_schema_validator()
    graph = cast(JsonObject, json.loads(outputs[GRAPH_PATH]))
    ledger = cast(JsonObject, json.loads(outputs[LEDGER_PATH]))
    for index, criterion_id in enumerate(CRITERION_OBLIGATIONS, 1):
        path = evidence_root / f"{index:02d}-result.json"
        try:
            result = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceabilityError(f"cannot read retained result {path}: {exc}") from exc
        validator._internal_validate(result, schema)
        if result != _result(criterion_id, graph, ledger) or result["verdict"] != "PASS":
            _fail(f"retained result does not match current governed outputs: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    results = subparsers.add_parser("results")
    results.add_argument("--output-root", type=Path, required=True)
    validate = subparsers.add_parser("validate-results")
    validate.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.write:
            _write()
        elif args.check:
            _check()
        elif args.command == "results":
            _write_results(args.output_root)
        elif args.command == "validate-results":
            _validate_results(args.evidence_root)
        else:
            parser.error("choose --write, --check, results, or validate-results")
    except (TraceabilityError, ValueError) as exc:
        print(f"traceability validation failed: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
