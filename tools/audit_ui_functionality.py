#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Static audit of MetriPlane localhost UI functionality coverage.

The audit is intentionally conservative: it inspects source files and dashboard
markup, but never executes product commands. It is meant to make UI coverage
drift visible before release.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import tempfile
from typing import Any, Iterable, Sequence


COVERAGE_COLUMNS = [
    "action_id",
    "feature_name",
    "source_path",
    "command_or_endpoint",
    "ui_route",
    "ui_label",
    "coverage_status",
    "risk",
    "notes",
]

TASK_ID = "MP2-012"
ROW_PREFIX = "MP2-012.UI."
PROFILE_ID = "repository.current-main.static-ui-census"
CONSUMER_TASK_IDS = ["MP2-014", "MP2-015", "MP2-016", "MP2-017", "MP2-018"]
INVENTORY_PATH = Path("docs/status/functional-inventory.json")
PROFILES_PATH = Path("docs/status/support-profiles.json")
BASELINE_PATH = Path("docs/status/baseline-snapshot.v1.json")
QA_PATHS = (
    Path("docs/qa/ui_functionality_inventory.md"),
    Path("docs/qa/ui_functionality_coverage_matrix.md"),
    Path("docs/qa/ui_missing_features_report.md"),
    Path("docs/qa/ui_parity_report.md"),
    Path("docs/qa/ui_testing.md"),
)
FROZEN_UI_EVIDENCE = {
    Path("evidence/experiments/ui_coverage_latest.csv"),
    Path("evidence/experiments/ui_coverage_latest.json"),
}
ROUTE_SOURCE_PATHS = {
    "metriplane/_local_http.py",
    "metriplane/metrics.py",
    "metriplane/run.py",
    "metriplane/runner/operator_api.py",
    "metriplane/runner/service.py",
    "metriplane/streaming/ws_server.py",
}
RUNNER_ROUTE_METADATA = {
    ("GET", "/commands"): ("api.runner.commands", "Runner action registry", "P1"),
    ("GET", "/jobs"): ("api.runner.jobs", "Recent runner jobs", "P1"),
    ("GET", "/jobs/{job_id}"): ("api.runner.job_detail", "Runner job detail", "P0"),
    ("GET", "/status"): ("api.runner.status", "Runner status", "P0"),
    ("POST", "/execute"): ("api.runner.execute", "Execute allowlisted command", "P0"),
    ("POST", "/jobs/{job_id}/cancel"): (
        "api.runner.cancel_job",
        "Cancel running job",
        "P1",
    ),
}

P0_ALLOWLIST = {
    "run-demo-replay",
    "doctor",
    "preflight",
    "list-cameras",
    "sentinel-demo",
    "cleanup",
}
P1_ALLOWLIST = {
    "deterministic-replay",
    "backpressure",
    "timing-breakdown",
    "gpu-smoke",
    "gpu-benchmark",
    "atlas-demo",
    "atlas-verify-demo",
    "integration-ros2-check",
    "integration-omniverse-export",
    "integration-isaac-export",
    "docker-check",
    "docker-demo-up",
    "docker-stop",
}
P0_CLI = {"doctor", "start", "stop", "status", "cleanup"}
P1_CLI = {"replay", "sentinel", "atlas", "command-center", "camera-trust", "traces", "ask"}


class AuditError(RuntimeError):
    """The governed surface cannot be represented without guessing."""


@dataclass
class Action:
    action_id: str
    feature_name: str
    source: str
    source_path: str
    command_or_endpoint: str
    source_line: int = 1
    protocol: str | None = None
    route_path: str | None = None
    route_method: str | None = None
    risk: str = "P2"
    enabled: bool | None = None
    disabled_reason: str | None = None
    coverage_status: str = "ui_missing"
    ui_matches: list[dict[str, str]] = field(default_factory=list)
    notes: str = ""

    def row(self) -> dict[str, str]:
        ui_route = "; ".join(m.get("file", "") for m in self.ui_matches) or "-"
        ui_label = "; ".join(m.get("label", "") for m in self.ui_matches) or "-"
        return {
            "action_id": self.action_id,
            "feature_name": self.feature_name,
            "source_path": self.source_path,
            "command_or_endpoint": self.command_or_endpoint,
            "ui_route": ui_route,
            "ui_label": ui_label,
            "coverage_status": self.coverage_status,
            "risk": self.risk,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Page:
    page_id: str
    name: str
    path: str
    route: str


@dataclass(frozen=True)
class Service:
    service_id: str
    name: str
    protocol: str
    source_path: str
    source_line: int
    locator: str


@dataclass(frozen=True)
class Topic:
    topic_id: str
    name: str
    source_path: str
    source_line: int
    parameter: str


@dataclass
class Audit:
    actions: list[Action]
    ui: dict[str, Any]
    summary: dict[str, int]
    pages: list[Page]
    services: list[Service]
    topics: list[Topic]
    baseline_crosswalk: list[dict[str, Any]]
    inventory: dict[str, Any]
    profiles: dict[str, Any]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _document_bytes(value: object) -> bytes:
    return _canonical_bytes(value)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read canonical JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"canonical JSON root must be an object: {path}")
    return value


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    if not slug:
        raise AuditError(f"cannot derive a stable ID from {value!r}")
    return slug


def _call_name(call: ast.Call) -> str | None:
    parts: list[str] = []
    node: ast.expr = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _parse_module(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise AuditError(f"cannot parse governed source {path}: {exc}") from exc


class DashboardHTMLParser(HTMLParser):
    """Extract actionable HTML elements from dashboard pages."""

    def __init__(self, file: str) -> None:
        super().__init__(convert_charrefs=True)
        self.file = file
        self._stack: list[dict[str, Any]] = []
        self.elements: list[dict[str, str]] = []
        self.ids: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: "" if v is None else v for k, v in attrs}
        line, _col = self.getpos()
        if "id" in attr:
            self.ids.append({"file": self.file, "id": attr["id"], "tag": tag, "line": str(line)})
        if tag == "script" and attr.get("src"):
            self.scripts.append({"file": self.file, "src": attr["src"], "line": str(line)})
        if tag in {"button", "a"}:
            self._stack.append({"tag": tag, "attrs": attr, "text": []})
        elif self._stack:
            self._stack[-1]["text"].append(" ")

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1]["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        current = self._stack[-1]
        if current["tag"] != tag:
            return
        self._stack.pop()
        attrs = current["attrs"]
        text = " ".join("".join(current["text"]).split())
        entry = {
            "file": self.file,
            "kind": tag,
            "label": text or attrs.get("aria-label") or attrs.get("title") or "(unlabeled)",
        }
        for key in (
            "data-command-id",
            "data-needs-atlas",
            "href",
            "onclick",
            "id",
            "disabled",
            "aria-disabled",
            "title",
        ):
            if key in attrs:
                entry[key] = attrs[key]
        self.elements.append(entry)


def rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def literal(node: ast.AST, names: dict[str, Any] | None = None) -> Any:
    """Evaluate the bounded literal forms used by governed declarations."""

    values = names or {}
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        if node.id.startswith("_"):
            return node.id
        raise AuditError(f"unsupported unresolved name in declaration: {node.id}")
    if isinstance(node, ast.List):
        return [literal(item, values) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(literal(item, values) for item in node.elts)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
            elif isinstance(item, ast.FormattedValue):
                value = literal(item.value, values)
                if not isinstance(value, str):
                    raise AuditError("formatted declaration values must resolve to strings")
                parts.append(value)
            else:
                raise AuditError("unsupported formatted declaration")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = literal(node.left, values)
        right = literal(node.right, values)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        and node.attr == "executable"
    ):
        return "_PYTHON"
    raise AuditError(
        f"unsupported declaration expression: {ast.dump(node, include_attributes=False)}"
    )


def _module_constants(tree: ast.Module) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value_node = statement.value
        if value_node is None or len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        name = targets[0].id
        if not name.startswith("_"):
            continue
        try:
            values[name] = literal(value_node, values)
        except AuditError:
            continue
    return values


def parse_allowed_commands(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "allowlist.py"
    tree = _parse_module(path)
    constants = _module_constants(tree)
    actions: list[Action] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "AllowedCommand":
            continue
        values: dict[str, Any] = {}
        field_names = [
            "id",
            "title",
            "description",
            "command",
            "enabled",
            "disabled_reason",
            "timeout_s",
            "requires_gpu",
            "requires_cameras",
        ]
        for idx, arg in enumerate(node.args):
            if idx < len(field_names):
                values[field_names[idx]] = literal(arg, constants)
        for kw in node.keywords:
            if kw.arg is None:
                raise AuditError("AllowedCommand ** expansion is not governed")
            values[kw.arg] = literal(kw.value, constants)
        required = {
            "id",
            "title",
            "description",
            "command",
            "enabled",
            "disabled_reason",
            "timeout_s",
        }
        if not required.issubset(values):
            raise AuditError(f"AllowedCommand at {path}:{node.lineno} is incomplete")
        command_id = values["id"]
        command = values["command"]
        if (
            not isinstance(command_id, str)
            or not command_id
            or not isinstance(values["title"], str)
            or not isinstance(values["description"], str)
            or not isinstance(command, list)
            or not command
            or any(not isinstance(part, str) or not part for part in command)
            or not isinstance(values["enabled"], bool)
            or not (values["disabled_reason"] is None or isinstance(values["disabled_reason"], str))
        ):
            raise AuditError(f"AllowedCommand at {path}:{node.lineno} has an unsupported shape")
        command_text = " ".join(command)
        if command_id in P0_ALLOWLIST:
            risk = "P0"
        elif command_id in P1_ALLOWLIST:
            risk = "P1"
        elif values.get("requires_cameras") or values.get("requires_gpu"):
            risk = "P1"
        else:
            risk = "P2"
        actions.append(
            Action(
                action_id=f"runner.{command_id}",
                feature_name=str(values.get("title") or command_id),
                source="allowlist",
                source_path=rel_path(root, path),
                command_or_endpoint=command_text,
                source_line=node.lineno,
                risk=risk,
                enabled=values["enabled"],
                disabled_reason=values.get("disabled_reason"),
                notes=str(values.get("description") or ""),
            )
        )
    identifiers = [action.action_id for action in actions]
    if len(identifiers) != len(set(identifiers)):
        raise AuditError("runner allowlist contains duplicate action IDs")
    return sorted(actions, key=lambda action: action.action_id)


def parse_cli_subcommands(root: Path) -> list[Action]:
    path = root / "metriplane" / "cli.py"
    tree = _parse_module(path)
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    if len(functions) != 1:
        raise AuditError("metriplane.cli must contain exactly one main dispatcher")
    declarations: list[tuple[str, int]] = []
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            continue
        left = node.left
        if not (
            isinstance(left, ast.Subscript)
            and isinstance(left.value, ast.Name)
            and left.value.id == "argv"
            and isinstance(left.slice, ast.Constant)
            and left.slice.value == 0
        ):
            continue
        value = node.comparators[0]
        if not isinstance(node.ops[0], ast.Eq) or not (
            isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value
        ):
            raise AuditError(f"unsupported root dispatch at {path}:{node.lineno}")
        declarations.append((value.value, node.lineno))
    names = [name for name, _line in declarations]
    if len(names) != len(set(names)):
        raise AuditError("root CLI dispatcher contains duplicate actions")
    actions: list[Action] = []
    for name, line in sorted(declarations):
        risk = "P0" if name in P0_CLI else ("P1" if name in P1_CLI else "P2")
        actions.append(
            Action(
                action_id=f"cli.{name}",
                feature_name=f"metriplane {name}",
                source="cli",
                source_path=rel_path(root, path),
                command_or_endpoint=f"python -m metriplane.cli {name}",
                source_line=line,
                risk=risk,
            )
        )
    return actions


def parse_operator_endpoints(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "operator_api.py"
    tree = _parse_module(path)
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "route"
    ]
    if len(functions) != 1:
        raise AuditError("OperatorAPI.route is missing or ambiguous")
    actions: list[Action] = []
    method_branches: dict[str, ast.If] = {}
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "method"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value in {"GET", "POST"}
        ):
            method = str(test.comparators[0].value)
            if method in method_branches:
                raise AuditError(f"duplicate OperatorAPI {method} branch")
            method_branches[method] = node
    if set(method_branches) != {"GET", "POST"}:
        raise AuditError("OperatorAPI must expose explicit GET and POST branches")
    for method, branch in sorted(method_branches.items()):
        scoped = ast.Module(body=branch.body, type_ignores=[])
        for node in ast.walk(scoped):
            if not isinstance(node, ast.Compare) or not (
                isinstance(node.left, ast.Name) and node.left.id == "sub"
            ):
                continue
            if not (
                len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)
                and str(node.comparators[0].value).startswith("/")
            ):
                raise AuditError(f"unsupported OperatorAPI route at {path}:{node.lineno}")
            sub = str(node.comparators[0].value)
            endpoint = f"{method} /operator{sub}"
            slug = sub.strip("/").replace("/", "_").replace("-", "_")
            actions.append(
                Action(
                    action_id=f"api.operator.{method.lower()}.{slug}",
                    feature_name=f"Operator {method} {sub}",
                    source="operator_api",
                    source_path=rel_path(root, path),
                    command_or_endpoint=endpoint,
                    source_line=node.lineno,
                    protocol="http",
                    route_path=f"/operator{sub}",
                    route_method=method,
                    risk="P0"
                    if sub in {"/env", "/cameras", "/latest-run", "/start-fusion"}
                    else "P1",
                )
            )
    identifiers = [action.action_id for action in actions]
    if len(identifiers) != len(set(identifiers)):
        raise AuditError("OperatorAPI contains duplicate routes")
    return sorted(actions, key=lambda action: action.action_id)


def parse_runner_endpoints(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "service.py"
    tree = _parse_module(path)
    handlers = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id == "BaseHTTPRequestHandler")
            or (isinstance(base, ast.Attribute) and base.attr == "BaseHTTPRequestHandler")
            for base in node.bases
        )
    ]
    if len(handlers) != 1:
        raise AuditError("runner HTTP handler is missing or ambiguous")
    methods = {
        node.name.removeprefix("do_"): node
        for node in handlers[0].body
        if isinstance(node, ast.FunctionDef) and node.name in {"do_GET", "do_POST"}
    }
    if set(methods) != {"GET", "POST"}:
        raise AuditError("runner HTTP handler must expose GET and POST")
    found: dict[tuple[str, str], int] = {}

    def record_route(method: str, route: str, line: int) -> None:
        key = (method, route)
        if key not in RUNNER_ROUTE_METADATA:
            raise AuditError(f"unknown runner route at {path}:{line}: {method} {route}")
        if key in found:
            raise AuditError(f"duplicate runner route at {path}:{line}: {method} {route}")
        found[key] = line

    for method, function in methods.items():
        for node in ast.walk(function):
            if not isinstance(node, ast.If):
                continue
            tests = list(ast.walk(node.test))
            for compare in tests:
                if not isinstance(compare, ast.Compare) or not (
                    isinstance(compare.left, ast.Name) and compare.left.id == "path"
                ):
                    continue
                if not (
                    len(compare.ops) == 1
                    and isinstance(compare.ops[0], ast.Eq)
                    and len(compare.comparators) == 1
                    and isinstance(compare.comparators[0], ast.Constant)
                    and isinstance(compare.comparators[0].value, str)
                ):
                    raise AuditError(
                        f"unsupported runner route comparison at {path}:{compare.lineno}"
                    )
                route = str(compare.comparators[0].value)
                record_route(method, route, compare.lineno)
            calls = [item for item in tests if isinstance(item, ast.Call)]
            starts = [
                item
                for item in calls
                if isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == "path"
                and item.func.attr == "startswith"
            ]
            for call in starts:
                if not (
                    len(call.args) == 1
                    and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                ):
                    raise AuditError(f"dynamic runner prefix at {path}:{call.lineno}")
                prefix = str(call.args[0].value)
                if prefix == "/operator/":
                    continue
                if prefix != "/jobs/":
                    raise AuditError(f"unknown runner prefix at {path}:{call.lineno}: {prefix}")
                route = "/jobs/{job_id}"
                if method == "POST":
                    suffixes = [
                        item
                        for item in calls
                        if isinstance(item.func, ast.Attribute)
                        and isinstance(item.func.value, ast.Name)
                        and item.func.value.id == "path"
                        and item.func.attr == "endswith"
                    ]
                    if len(suffixes) != 1 or literal(suffixes[0].args[0]) != "/cancel":
                        raise AuditError("runner cancel route has an unsupported path shape")
                    route += "/cancel"
                record_route(method, route, call.lineno)
    if set(found) != set(RUNNER_ROUTE_METADATA):
        raise AuditError(
            "runner route set differs from governed declarations: "
            f"missing={sorted(set(RUNNER_ROUTE_METADATA) - set(found))}, "
            f"extra={sorted(set(found) - set(RUNNER_ROUTE_METADATA))}"
        )
    actions: list[Action] = []
    for (method, route), line in sorted(found.items()):
        action_id, name, risk = RUNNER_ROUTE_METADATA[(method, route)]
        display_path = route.replace("{job_id}", "<id>")
        actions.append(
            Action(
                action_id=action_id,
                feature_name=name,
                source="runner_api",
                source_path=rel_path(root, path),
                command_or_endpoint=f"{method} {display_path}",
                source_line=line,
                protocol="http",
                route_path=route,
                route_method=method,
                risk=risk,
            )
        )
    return actions


def runner_endpoint_actions(root: Path) -> list[Action]:
    """Compatibility alias for callers of the old audit helper."""

    return parse_runner_endpoints(root)


def parse_script_actions(root: Path) -> list[Action]:
    actions: list[Action] = []
    for folder, prefix in [("tools", "tool"), ("benchmarks", "benchmark")]:
        base = root / folder
        for path in sorted(base.glob("*.py")) + sorted(base.glob("*.sh")):
            name = path.stem
            rel = rel_path(root, path)
            command = rel if path.suffix == ".sh" else f"python {rel}"
            actions.append(
                Action(
                    action_id=f"{prefix}.{name}",
                    feature_name=name.replace("_", " ").replace("-", " ").title(),
                    source=prefix,
                    source_path=rel_path(root, path),
                    command_or_endpoint=command,
                    source_line=1,
                    risk="P1"
                    if name in {"list_cameras", "run_ui_demo_replay", "ui_safe_cleanup"}
                    else "P2",
                )
            )
    return sorted(actions, key=lambda action: action.action_id)


def discover_pages(root: Path) -> list[Page]:
    dashboard = root / "web" / "dashboard"
    pages: list[Page] = []
    for path in sorted(dashboard.glob("*.html"), key=lambda item: item.name.encode("utf-8")):
        text = path.read_text(encoding="utf-8")
        if "<body" not in text or "</body>" not in text:
            raise AuditError(f"dashboard page has no bounded body element: {path}")
        pages.append(
            Page(
                page_id=f"MP2-012.UI.PAGE.{_slug(path.name)}",
                name=path.name,
                path=rel_path(root, path),
                route=f"/web/dashboard/{path.name}",
            )
        )
    identifiers = [page.page_id for page in pages]
    if len(identifiers) != len(set(identifiers)):
        raise AuditError("dashboard pages produce duplicate stable IDs")
    return pages


def discover_services(root: Path) -> list[Service]:
    expected_calls = {
        ("metriplane/_local_http.py", "LocalHTTPServer"): "dashboard-static-http",
        ("metriplane/metrics.py", "ThreadingHTTPServer"): "runtime-health-metrics-http",
        ("metriplane/run.py", "ThreadingHTTPServer"): "runtime-health-metrics-http",
        ("metriplane/runner/service.py", "LocalHTTPServer"): "local-runner-http",
        ("metriplane/streaming/ws_server.py", "websockets.serve"): "runtime-frame-websocket",
    }
    calls: dict[tuple[str, str], int] = {}
    candidate_paths: set[str] = set()
    server_names = {"HTTPServer", "LocalHTTPServer", "ThreadingHTTPServer", "websockets.serve"}
    for path in sorted((root / "metriplane").rglob("*.py")):
        relative = rel_path(root, path)
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in server_names:
                continue
            candidate_paths.add(relative)
            key = (relative, name)
            if key in calls:
                raise AuditError(f"duplicate governed server declaration: {key}")
            calls[key] = node.lineno
    if candidate_paths != ROUTE_SOURCE_PATHS - {"metriplane/runner/operator_api.py"}:
        raise AuditError(
            "governed server source set changed: "
            f"expected={sorted(ROUTE_SOURCE_PATHS - {'metriplane/runner/operator_api.py'})}, "
            f"actual={sorted(candidate_paths)}"
        )
    if set(calls) != set(expected_calls):
        raise AuditError(
            f"governed service declarations changed: missing={sorted(set(expected_calls) - set(calls))}, "
            f"extra={sorted(set(calls) - set(expected_calls))}"
        )
    grouped: dict[str, list[tuple[str, str, int]]] = {}
    for key, service_id in expected_calls.items():
        grouped.setdefault(service_id, []).append((*key, calls[key]))
    metadata = {
        "dashboard-static-http": ("Dashboard static HTTP", "http"),
        "local-runner-http": ("Local runner HTTP", "http"),
        "runtime-frame-websocket": ("Runtime frame WebSocket", "websocket"),
        "runtime-health-metrics-http": ("Runtime health and metrics HTTP", "http"),
    }
    services: list[Service] = []
    for service_id, declarations in sorted(grouped.items()):
        name, protocol = metadata[service_id]
        source_path, call_name, line = sorted(declarations)[0]
        services.append(
            Service(
                service_id=f"MP2-012.UI.SERVICE.{_slug(service_id)}",
                name=name,
                protocol=protocol,
                source_path=source_path,
                source_line=line,
                locator=call_name,
            )
        )
    return services


def discover_topics(root: Path) -> list[Topic]:
    launch_path = root / "integrations" / "ros2" / "metriplane_ros" / "launch" / "bridge.launch.py"
    bridge_path = (
        root / "integrations" / "ros2" / "metriplane_ros" / "metriplane_ros" / "bridge_node.py"
    )
    launch = _parse_module(launch_path)
    defaults: dict[str, tuple[str, int]] = {}
    for node in ast.walk(launch):
        if not isinstance(node, ast.Call) or _call_name(node) != "DeclareLaunchArgument":
            continue
        if not node.args or not (
            isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
        ):
            raise AuditError(f"dynamic ROS launch argument at {launch_path}:{node.lineno}")
        parameter = str(node.args[0].value)
        if not parameter.endswith("_topic"):
            continue
        keyword = next((item for item in node.keywords if item.arg == "default_value"), None)
        if keyword is None:
            raise AuditError(f"ROS topic has no default at {launch_path}:{node.lineno}")
        value = literal(keyword.value)
        if not isinstance(value, str) or not value.startswith("/metriplane/"):
            raise AuditError(f"unsupported ROS topic at {launch_path}:{node.lineno}")
        if parameter in defaults:
            raise AuditError(f"duplicate ROS topic launch argument: {parameter}")
        defaults[parameter] = (value, node.lineno)

    bridge = _parse_module(bridge_path)
    bridge_defaults: dict[str, str] = {}
    publisher_parameters: set[str] = set()
    for node in ast.walk(bridge):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "self.declare_parameter" and len(node.args) >= 2:
            parameter = literal(node.args[0])
            if isinstance(parameter, str) and parameter.endswith("_topic"):
                default = literal(node.args[1])
                if not isinstance(default, str):
                    raise AuditError(f"dynamic bridge topic default at {bridge_path}:{node.lineno}")
                bridge_defaults[parameter] = default
        if name == "self.create_publisher" and len(node.args) >= 2:
            topic_arg = node.args[1]
            if (
                isinstance(topic_arg, ast.Attribute)
                and isinstance(topic_arg.value, ast.Name)
                and topic_arg.value.id == "self"
                and topic_arg.attr.endswith("_topic")
            ):
                publisher_parameters.add(topic_arg.attr)
            else:
                raise AuditError(f"dynamic bridge publisher topic at {bridge_path}:{node.lineno}")
    if set(defaults) != set(bridge_defaults) or set(defaults) != publisher_parameters:
        raise AuditError("ROS topic launch, node defaults, and publishers do not have set equality")
    if any(defaults[key][0] != bridge_defaults[key] for key in defaults):
        raise AuditError("ROS topic launch and node defaults differ")
    topics = [
        Topic(
            topic_id=f"MP2-012.UI.TOPIC.{_slug(value)}",
            name=value,
            source_path=rel_path(root, launch_path),
            source_line=line,
            parameter=parameter,
        )
        for parameter, (value, line) in defaults.items()
    ]
    topics.sort(key=lambda topic: topic.topic_id)
    if len({topic.topic_id for topic in topics}) != len(topics):
        raise AuditError("ROS topics produce duplicate stable IDs")
    return topics


def parse_dashboard_ui(root: Path) -> dict[str, Any]:
    dashboard = root / "web" / "dashboard"
    html_elements: list[dict[str, str]] = []
    html_ids: list[dict[str, str]] = []
    script_refs: list[dict[str, str]] = []
    html_files: dict[str, str] = {}
    js_text = ""
    js_files: dict[str, str] = {}
    html_text = ""
    for path in sorted(dashboard.glob("*.html")):
        rel = rel_path(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        html_files[rel] = text
        html_text += "\n" + text
        parser = DashboardHTMLParser(rel)
        parser.feed(text)
        html_elements.extend(parser.elements)
        html_ids.extend(parser.ids)
        script_refs.extend(parser.scripts)
    for path in sorted(dashboard.glob("*.js")):
        rel = rel_path(root, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        js_files[rel] = text
        js_text += "\n" + text

    command_buttons = [
        {
            "file": e["file"],
            "label": e.get("label", ""),
            "kind": e.get("kind", "button"),
            "command_id": e.get("data-command-id", ""),
            "disabled": "disabled" in e or e.get("aria-disabled") == "true",
            "title": e.get("title", ""),
            "needs_atlas": "data-needs-atlas" in e,
        }
        for e in html_elements
        if e.get("data-command-id")
    ]
    hrefs = [
        {"file": e["file"], "label": e.get("label", ""), "href": e.get("href", "")}
        for e in html_elements
        if e.get("href")
    ]
    onclicks = [
        {"file": e["file"], "label": e.get("label", ""), "onclick": e.get("onclick", "")}
        for e in html_elements
        if e.get("onclick")
    ]
    copy_commands = sorted(
        set(re.findall(r"copyCommand\([\"']([^\"']+)[\"']\)", html_text + js_text))
    )

    endpoint_calls: set[str] = set()
    path_calls: set[str] = set()
    for method, path in re.findall(
        r"(?:opApi|runnerPost)\([\"'](GET|POST)[\"']\s*,\s*[\"']([^\"']+)[\"']",
        js_text + html_text,
    ):
        endpoint_calls.add(f"{method} {path}")
        path_calls.add(path)
    for path in re.findall(r"runnerPost\([\"']([^\"']+)[\"']", js_text + html_text):
        endpoint_calls.add(f"POST {path}")
        path_calls.add(path)
    for path in re.findall(r"getJSON\([\"']([^\"']+)[\"']", js_text + html_text):
        endpoint_calls.add(f"GET {path}")
        path_calls.add(path)
    for path in re.findall(r"postJSON\([\"']([^\"']+)[\"']", js_text + html_text):
        endpoint_calls.add(f"POST {path}")
        path_calls.add(path)
    for path in re.findall(
        r"fetch\(\s*(?:RUNNER\s*\+\s*)?[`\"']([^`\"'$]+)[`\"']", js_text + html_text
    ):
        if path.startswith("http"):
            continue
        path_calls.add(path)
        endpoint_calls.add(f"GET {path}")
    for match in re.finditer(r"\$\{RUNNER\}([^`]+)", js_text + html_text):
        path = match.group(1)
        clean = path.split("?")[0]
        clean = re.sub(r"\$\{[^}]+\}", "<id>", clean)
        path_calls.add(clean)
        window = js_text[match.start() : match.start() + 240]
        method = "POST" if "method" in window and "POST" in window else "GET"
        endpoint_calls.add(f"{method} {clean}")

    return {
        "html_elements": html_elements,
        "command_buttons": command_buttons,
        "hrefs": hrefs,
        "onclicks": onclicks,
        "copy_commands": copy_commands,
        "endpoint_calls": sorted(endpoint_calls),
        "path_calls": sorted(path_calls),
        "html_ids": html_ids,
        "script_refs": script_refs,
        "html_files": html_files,
        "js_files": js_files,
        "raw_text": html_text + "\n" + js_text,
    }


def endpoint_coverage_reason(endpoint: str, ui: dict[str, Any]) -> str | None:
    method, path = endpoint.split(" ", 1)
    endpoint_calls = set(ui["endpoint_calls"])
    path_calls = set(ui["path_calls"])
    read_only_operator = {
        "/operator/live-summary",
        "/operator/objects",
        "/operator/incidents",
        "/operator/traces",
        "/operator/camera-trust",
        "/operator/frames",
    }
    if endpoint in endpoint_calls:
        return "direct"
    if method == "POST" and path in read_only_operator and f"GET {path}" in endpoint_calls:
        return "read_only_fallback"
    if path in path_calls:
        return "direct"
    if "<id>" in path:
        prefix = path.split("<id>", 1)[0]
        return "pattern" if any(call.startswith(prefix) for call in path_calls) else None
    if path.endswith("/<id>/cancel"):
        return (
            "pattern"
            if any("/jobs/" in call and "/cancel" in call for call in path_calls)
            else None
        )
    if path.endswith("/<id>"):
        prefix = path.rsplit("/<id>", 1)[0] + "/"
        return "pattern" if any(call.startswith(prefix) for call in path_calls) else None
    # POST endpoints are sometimes wrapped by runnerPost(path, body).
    if method == "POST" and f"POST {path}" in endpoint_calls:
        return "direct"
    return None


def endpoint_covered(endpoint: str, ui: dict[str, Any]) -> bool:
    return endpoint_coverage_reason(endpoint, ui) is not None


def duplicate_html_ids(ui: dict[str, Any]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for item in ui["html_ids"]:
        grouped.setdefault((item["file"], item["id"]), []).append(item)
    duplicates: list[dict[str, str]] = []
    for (file, html_id), rows in sorted(grouped.items()):
        if len(rows) <= 1:
            continue
        duplicates.append(
            {
                "file": file,
                "id": html_id,
                "count": str(len(rows)),
                "lines": ", ".join(row["line"] for row in rows),
            }
        )
    return duplicates


def js_syntax_errors(root: Path, ui: dict[str, Any]) -> tuple[list[dict[str, str]], bool]:
    node = shutil.which("node")
    if not node:
        return [], True
    errors: list[dict[str, str]] = []
    for rel in sorted(ui["js_files"]):
        path = root / rel
        result = subprocess.run(
            [node, "--check", str(path)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            errors.append(
                {
                    "file": rel,
                    "error": (result.stderr or result.stdout).strip().splitlines()[-1]
                    if (result.stderr or result.stdout).strip()
                    else f"node --check exited {result.returncode}",
                }
            )
    return errors, False


CARD_RE = re.compile(
    r"<(?P<tag>article|div)\b(?=[^>]*\bclass=[\"'][^\"']*"
    r"(?:mp-action-card|mp-guide-card|mp-command-card)[^\"']*[\"'])[^>]*>"
    r"(?P<body>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)


def duplicate_command_ids_on_same_card(ui: dict[str, Any]) -> list[dict[str, str]]:
    duplicates: list[dict[str, str]] = []
    for file, text in sorted(ui["html_files"].items()):
        for idx, match in enumerate(CARD_RE.finditer(text), start=1):
            commands = re.findall(r"\bdata-command-id=[\"']([^\"']+)[\"']", match.group("body"))
            for command_id, count in sorted(Counter(commands).items()):
                if count <= 1:
                    continue
                line = text[: match.start()].count("\n") + 1
                duplicates.append(
                    {
                        "file": file,
                        "card": str(idx),
                        "line": str(line),
                        "command_id": command_id,
                        "count": str(count),
                    }
                )
    return duplicates


def atlas_buttons_never_enabled(ui: dict[str, Any]) -> list[dict[str, str]]:
    product_actions = ui["js_files"].get("web/dashboard/product_actions.js", "")
    has_enable_logic = (
        "setAtlasDependent(true)" in product_actions
        and "el.disabled = !enabled" in product_actions
        and "has-atlas-artifacts" in product_actions
    )
    page_scripts: dict[str, set[str]] = {}
    for script in ui["script_refs"]:
        page_scripts.setdefault(script["file"], set()).add(script["src"].split("?", 1)[0])

    stuck: list[dict[str, str]] = []
    for button in ui["command_buttons"]:
        if not button.get("needs_atlas"):
            continue
        scripts = page_scripts.get(button["file"], set())
        has_product_actions = "product_actions.js" in scripts
        reason = ""
        if not has_product_actions:
            reason = "page does not load product_actions.js"
        elif not has_enable_logic:
            reason = "product_actions.js does not contain Atlas enable logic"
        if reason:
            stuck.append(
                {
                    "file": button["file"],
                    "label": button["label"],
                    "command_id": button["command_id"],
                    "reason": reason,
                }
            )
    return stuck


def coverage_for_action(action: Action, ui: dict[str, Any]) -> None:
    raw = ui["raw_text"]
    command_buttons = ui["command_buttons"]
    if action.source == "allowlist":
        command_id = action.action_id.removeprefix("runner.")
        matches = [
            {
                "file": b["file"],
                "label": b["label"],
                "kind": "button",
            }
            for b in command_buttons
            if b["command_id"] == command_id
        ]
        action.ui_matches = matches
        if matches and action.enabled:
            action.coverage_status = "ui_full"
        elif matches and not action.enabled:
            action.coverage_status = "ui_disabled_with_reason"
            action.notes = action.disabled_reason or action.notes or "Disabled in allowlist"
        elif not action.enabled:
            action.coverage_status = "cli_only_documented"
            action.notes = action.disabled_reason or action.notes or "Disabled in allowlist"
        elif action.command_or_endpoint and action.command_or_endpoint in raw:
            action.coverage_status = "ui_copy_command_only"
            action.ui_matches = [
                {
                    "file": "web/dashboard/*",
                    "label": action.command_or_endpoint,
                    "kind": "copy/help",
                }
            ]
        else:
            action.coverage_status = "ui_missing"
        return

    if action.source in {"operator_api", "runner_api"}:
        reason = endpoint_coverage_reason(action.command_or_endpoint, ui)
        if reason:
            action.coverage_status = "ui_full"
            action.ui_matches = [
                {"file": "web/dashboard/*.js", "label": action.command_or_endpoint, "kind": "api"}
            ]
            if reason == "read_only_fallback":
                action.notes = "Covered by read-only GET fallback for an observe-only endpoint."
        else:
            action.coverage_status = "ui_missing"
        return

    command = action.command_or_endpoint
    source_name = Path(action.source_path).name
    if source_name in raw or command in raw:
        action.coverage_status = "ui_copy_command_only"
        action.ui_matches = [{"file": "web/dashboard/*", "label": source_name, "kind": "link/copy"}]
    elif action.source == "cli":
        name = action.action_id.removeprefix("cli.")
        if any(name in text for text in (raw, "\n".join(ui["copy_commands"]))):
            action.coverage_status = "ui_partial"
            action.ui_matches = [{"file": "web/dashboard/*", "label": command, "kind": "copy/help"}]
        elif action.risk in {"P0", "P1"}:
            action.coverage_status = "ui_missing"
        else:
            action.coverage_status = "cli_only_documented"
            action.notes = "Lower-level CLI surface; keep in Help/advanced docs."
    elif action.source in {"tool", "benchmark"}:
        if action.risk == "P1":
            action.coverage_status = "ui_missing"
        else:
            action.coverage_status = "cli_only_documented"
            action.notes = "Developer/diagnostic script; not a primary localhost workflow."


def build_actions(root: Path) -> tuple[list[Action], dict[str, Any]]:
    ui = parse_dashboard_ui(root)
    js_errors, js_check_unavailable = js_syntax_errors(root, ui)
    ui["quality"] = {
        "duplicate_html_ids": duplicate_html_ids(ui),
        "js_syntax_errors": js_errors,
        "js_syntax_check_unavailable": js_check_unavailable,
        "buttons_with_duplicate_command_id_on_same_card": duplicate_command_ids_on_same_card(ui),
        "data_needs_atlas_buttons_never_enabled": atlas_buttons_never_enabled(ui),
        "read_only_fallback_endpoints": [],
    }
    actions = (
        parse_allowed_commands(root)
        + parse_cli_subcommands(root)
        + parse_operator_endpoints(root)
        + parse_runner_endpoints(root)
        + parse_script_actions(root)
    )
    seen: set[str] = set()
    for action in actions:
        if action.action_id in seen:
            raise AuditError(f"duplicate discovered action ID: {action.action_id}")
        seen.add(action.action_id)
        coverage_for_action(action, ui)
    unique = sorted(actions, key=lambda action: action.action_id)
    allowlist_commands = "\n".join(
        action.command_or_endpoint for action in unique if action.source == "allowlist"
    )
    for action in unique:
        if action.coverage_status != "ui_missing":
            continue
        if action.source == "cli":
            subcommand = action.action_id.removeprefix("cli.")
            if (
                f"metriplane.cli {subcommand}" in allowlist_commands
                or f" {subcommand} " in allowlist_commands
            ):
                action.coverage_status = "ui_partial"
                action.ui_matches = [
                    {
                        "file": "metriplane/runner/allowlist.py",
                        "label": "runner action",
                        "kind": "allowlist",
                    }
                ]
                action.notes = (
                    "Exposed through a runner allowlist action rather than a raw CLI button."
                )
        elif action.source == "tool":
            rel = action.source_path
            if rel in allowlist_commands:
                action.coverage_status = "ui_full"
                action.ui_matches = [
                    {
                        "file": "metriplane/runner/allowlist.py",
                        "label": "runner action",
                        "kind": "allowlist",
                    }
                ]
                action.notes = "Covered by a runner allowlist command."
    ui["quality"]["read_only_fallback_endpoints"] = [
        {
            "action_id": action.action_id,
            "endpoint": action.command_or_endpoint,
            "notes": action.notes,
        }
        for action in unique
        if action.notes == "Covered by read-only GET fallback for an observe-only endpoint."
    ]
    return unique, ui


def summarize(actions: Iterable[Action], ui: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {
        "total_discovered_features": 0,
        "ui_full": 0,
        "ui_partial": 0,
        "ui_copy_command_only": 0,
        "ui_disabled_with_reason": 0,
        "ui_missing": 0,
        "cli_only_documented": 0,
        "planned_only": 0,
        "broken_buttons": 0,
        "unsupported_claims_found": 0,
        "duplicate_html_ids": 0,
        "js_syntax_errors": 0,
        "js_syntax_check_unavailable": 0,
        "buttons_with_duplicate_command_id_on_same_card": 0,
        "data_needs_atlas_buttons_never_enabled": 0,
        "read_only_fallback_endpoints": 0,
        "critical_bugs": 0,
        "high_bugs": 0,
    }
    action_list = list(actions)
    counts["total_discovered_features"] = len(action_list)
    for action in action_list:
        counts[action.coverage_status] = counts.get(action.coverage_status, 0) + 1
        if action.coverage_status == "ui_missing" and action.risk == "P0":
            counts["critical_bugs"] += 1
        elif action.coverage_status == "ui_missing" and action.risk == "P1":
            counts["high_bugs"] += 1

    known_command_ids = {
        action.action_id.removeprefix("runner.")
        for action in action_list
        if action.source == "allowlist"
    }
    for button in ui["command_buttons"]:
        if button["command_id"] not in known_command_ids:
            counts["broken_buttons"] += 1
            counts["high_bugs"] += 1
    quality = ui.get("quality", {})
    counts["duplicate_html_ids"] = len(quality.get("duplicate_html_ids", []))
    counts["js_syntax_errors"] = len(quality.get("js_syntax_errors", []))
    counts["js_syntax_check_unavailable"] = 1 if quality.get("js_syntax_check_unavailable") else 0
    counts["buttons_with_duplicate_command_id_on_same_card"] = len(
        quality.get("buttons_with_duplicate_command_id_on_same_card", [])
    )
    counts["data_needs_atlas_buttons_never_enabled"] = len(
        quality.get("data_needs_atlas_buttons_never_enabled", [])
    )
    counts["read_only_fallback_endpoints"] = len(quality.get("read_only_fallback_endpoints", []))
    counts["critical_bugs"] += counts["duplicate_html_ids"] + counts["js_syntax_errors"]
    counts["high_bugs"] += (
        counts["buttons_with_duplicate_command_id_on_same_card"]
        + counts["data_needs_atlas_buttons_never_enabled"]
        + counts["js_syntax_check_unavailable"]
    )
    return counts


def build_baseline_crosswalk(
    root: Path,
    actions: Sequence[Action],
    services: Sequence[Service],
) -> list[dict[str, Any]]:
    baseline = _read_json(root / BASELINE_PATH)
    route_object = baseline.get("http_routes")
    if not isinstance(route_object, dict) or not isinstance(route_object.get("entries"), list):
        raise AuditError("frozen baseline HTTP route object is missing")
    baseline_rows = route_object["entries"]
    if route_object.get("count") != len(baseline_rows) or route_object.get(
        "canonical_rows_sha256"
    ) != _digest(baseline_rows):
        raise AuditError("frozen baseline HTTP route count or digest is stale")
    route_targets = {
        (action.protocol, action.route_method, action.route_path): action.action_id
        for action in actions
        if action.route_path is not None
    }
    if len(route_targets) != sum(action.route_path is not None for action in actions):
        raise AuditError("discovered HTTP routes are not unique")
    service_ids = {service.service_id for service in services}
    service_targets = {
        "dashboard": "MP2-012.UI.SERVICE.DASHBOARD_STATIC_HTTP",
        "health": "MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP",
        "runner": "MP2-012.UI.SERVICE.LOCAL_RUNNER_HTTP",
        "websocket": "MP2-012.UI.SERVICE.RUNTIME_FRAME_WEBSOCKET",
    }
    if not set(service_targets.values()).issubset(service_ids):
        raise AuditError("baseline crosswalk references an undiscovered service")
    crosswalk: list[dict[str, Any]] = []
    for baseline_row in baseline_rows:
        if not isinstance(baseline_row, dict):
            raise AuditError("frozen baseline route row is not an object")
        key = (
            baseline_row.get("protocol"),
            baseline_row.get("method"),
            baseline_row.get("normalized_path"),
        )
        target = route_targets.get(key)
        target_kind = "route"
        relation = "direct_route"
        source_path = baseline_row.get("source_path")
        if target is None:
            target_kind = "service"
            relation = "service_boundary"
            if source_path == "metriplane/_local_http.py":
                target = service_targets["dashboard"]
            elif source_path in {"metriplane/metrics.py", "metriplane/run.py"}:
                target = service_targets["health"]
            elif source_path == "metriplane/runner/service.py" and key[1] == "OPTIONS":
                target = service_targets["runner"]
            elif source_path == "metriplane/streaming/ws_server.py":
                target = service_targets["websocket"]
        if target is None:
            raise AuditError(
                f"frozen baseline route has no current crosswalk target: {baseline_row}"
            )
        crosswalk.append(
            {
                "baseline_row_sha256": _digest(baseline_row),
                "condition": baseline_row.get("condition"),
                "declaration_kind": baseline_row.get("declaration_kind"),
                "method": baseline_row.get("method"),
                "normalized_path": baseline_row.get("normalized_path"),
                "protocol": baseline_row.get("protocol"),
                "relation": relation,
                "source_path": source_path,
                "target_id": target,
                "target_kind": target_kind,
            }
        )
    if len(crosswalk) != len(baseline_rows):
        raise AuditError("baseline route crosswalk is incomplete")
    return crosswalk


def _discovery_source(root: Path, path: str, locator: str) -> dict[str, str]:
    source = root / path
    if not source.is_file() or source.is_symlink():
        raise AuditError(f"registry source is not a regular in-repository file: {path}")
    return {
        "type": "repository_discovery",
        "path": path,
        "locator": locator,
        "digest_sha256": _file_digest(source),
    }


def _row(
    *,
    identifier: str,
    kind: str,
    name: str,
    source: dict[str, str],
    obligation: str,
    statement: str,
    validators: Sequence[str],
    limitation_ids: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": list(limitation_ids),
            "statement": statement,
        },
        "consumer_task_ids": CONSUMER_TASK_IDS,
        "id": identifier,
        "kind": kind,
        "name": name,
        "owner": TASK_ID,
        "profile": PROFILE_ID,
        "source": source,
        "status": "active",
        "test": obligation,
        "trace_criterion_ids": ["MP2-012.A01", "MP2-012.A02"],
        "validator_ids": sorted(set(validators)),
    }


def build_registry_candidates(
    root: Path,
    actions: Sequence[Action],
    pages: Sequence[Page],
    services: Sequence[Service],
    topics: Sequence[Topic],
) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory_path = root / INVENTORY_PATH
    profiles_path = root / PROFILES_PATH
    inventory = _read_json(inventory_path)
    profiles = _read_json(profiles_path)
    rows = inventory.get("rows")
    profile_rows = profiles.get("profiles")
    if not isinstance(rows, list) or not isinstance(profile_rows, list):
        raise AuditError("functional registry rows or profiles are missing")
    if inventory.get("rows_sha256") != _digest(rows):
        raise AuditError("functional inventory rows_sha256 is stale before MP2-012 projection")
    if profiles.get("profiles_sha256") != _digest(profile_rows):
        raise AuditError("support profiles_sha256 is stale before MP2-012 projection")

    validator = (
        "tests/ui_coverage/test_audit_ui_functionality.py::"
        "test_committed_status_matches_current_governed_surface"
    )
    generated: list[dict[str, Any]] = []
    for action in actions:
        is_route = action.route_path is not None
        limitation_ids = (
            ["ROUTE_OVERACCEPTANCE_UNCHARACTERIZED"]
            if action.route_path in {"/jobs/{job_id}", "/jobs/{job_id}/cancel"}
            else []
        )
        generated.append(
            _row(
                identifier=f"MP2-012.UI.ACTION.{_slug(action.action_id)}",
                kind="http_route" if is_route else "ui_action",
                name=action.feature_name,
                source=_discovery_source(
                    root,
                    action.source_path,
                    f"{action.action_id}@L{action.source_line}",
                ),
                obligation=(
                    "MP2-012.OBL.HTTP_ROUTE_DISCOVERY"
                    if is_route
                    else "MP2-012.OBL.UI_ACTION_DISCOVERY"
                ),
                statement=(
                    f"Static source discovery observes the governed route {action.route_method} "
                    f"{action.route_path}; runtime behavior is not characterized by MP2-012."
                    if is_route
                    else f"Static source discovery observes the UI/action row {action.action_id}; "
                    "runtime behavior is not characterized by MP2-012."
                ),
                validators=[validator],
                limitation_ids=limitation_ids,
            )
        )
    for page in pages:
        generated.append(
            _row(
                identifier=page.page_id,
                kind="ui_page",
                name=page.name,
                source=_discovery_source(root, page.path, page.route),
                obligation="MP2-012.OBL.PAGE_DISCOVERY",
                statement=f"Static source discovery observes dashboard page {page.route}; browser "
                "behavior remains bound to the separate all-page smoke validator.",
                validators=[
                    validator,
                    "tests/e2e/test_dashboard_playwright_smoke.py::"
                    "test_dashboard_pages_render_without_uncaught_js_errors",
                ],
            )
        )
    for service in services:
        generated.append(
            _row(
                identifier=service.service_id,
                kind="local_service",
                name=service.name,
                source=_discovery_source(
                    root,
                    service.source_path,
                    f"{service.locator}@L{service.source_line}",
                ),
                obligation="MP2-012.OBL.SERVICE_TOPIC_DISCOVERY",
                statement=f"Static source discovery observes the {service.protocol} service "
                f"{service.name}; availability and support are not measured.",
                validators=[validator],
            )
        )
    for topic in topics:
        generated.append(
            _row(
                identifier=topic.topic_id,
                kind="service_topic",
                name=topic.name,
                source=_discovery_source(
                    root,
                    topic.source_path,
                    f"DeclareLaunchArgument:{topic.parameter}@L{topic.source_line}",
                ),
                obligation="MP2-012.OBL.SERVICE_TOPIC_DISCOVERY",
                statement=f"Static source discovery observes ROS 2 topic {topic.name}; runtime "
                "publication and environment support are not measured.",
                validators=[validator],
            )
        )
    generated.sort(key=lambda item: item["id"])
    identifiers = [str(item["id"]) for item in generated]
    if len(identifiers) != len(set(identifiers)):
        raise AuditError("MP2-012 generated registry IDs are not unique")

    foreign_rows: list[dict[str, Any]] = []
    for item in rows:
        namespaced = str(item.get("id", "")).startswith(ROW_PREFIX)
        owned = item.get("owner") == TASK_ID
        if namespaced != owned:
            raise AuditError(
                "MP2-012 functional row namespace and owner disagree: "
                f"id={item.get('id')!r}, owner={item.get('owner')!r}"
            )
        if not owned:
            foreign_rows.append(item)
    candidate_inventory = dict(inventory)
    candidate_inventory["rows"] = sorted(
        [*foreign_rows, *generated], key=lambda item: str(item["id"])
    )
    candidate_inventory["rows_sha256"] = _digest(candidate_inventory["rows"])

    profile = {
        "claim": {
            "classification": "observed_not_supported",
            "limitation_ids": [],
            "statement": "Static current-source UI, route, service, page, and topic census; this "
            "profile makes no runtime, browser, platform, or environment support claim.",
        },
        "id": PROFILE_ID,
        "kind": "repository_ui_discovery",
        "owner": TASK_ID,
        "source": _discovery_source(
            root,
            "tools/audit_ui_functionality.py",
            "canonical governed UI discovery scanner",
        ),
        "status": "active",
        "support_disposition": "not_measured",
        "test": "MP2-012.OBL.NO_SUPPORT_CLAIM_EXPANSION",
    }
    foreign_profiles: list[dict[str, Any]] = []
    for item in profile_rows:
        identified = item.get("id") == PROFILE_ID
        owned = item.get("owner") == TASK_ID
        if identified != owned:
            raise AuditError(
                "MP2-012 support profile ID and owner disagree: "
                f"id={item.get('id')!r}, owner={item.get('owner')!r}"
            )
        if not owned:
            foreign_profiles.append(item)
    candidate_profiles = dict(profiles)
    candidate_profiles["profiles"] = sorted(
        [*foreign_profiles, profile], key=lambda item: str(item["id"])
    )
    candidate_profiles["profiles_sha256"] = _digest(candidate_profiles["profiles"])
    return candidate_inventory, candidate_profiles


def _action_object(action: Action) -> dict[str, Any]:
    return {
        **action.row(),
        "disabled_reason": action.disabled_reason,
        "enabled": action.enabled,
        "protocol": action.protocol,
        "route_method": action.route_method,
        "route_path": action.route_path,
        "source": action.source,
        "source_line": action.source_line,
        "ui_matches": action.ui_matches,
    }


def canonical_status(audit: Audit) -> dict[str, Any]:
    actions = [_action_object(action) for action in audit.actions]
    pages = [vars(page) for page in audit.pages]
    services = [vars(service) for service in audit.services]
    topics = [vars(topic) for topic in audit.topics]
    owned_rows = [row for row in audit.inventory["rows"] if str(row["id"]).startswith(ROW_PREFIX)]
    owned_profiles = [
        profile for profile in audit.profiles["profiles"] if profile.get("owner") == TASK_ID
    ]
    projection = {
        "actions": actions,
        "baseline_crosswalk": audit.baseline_crosswalk,
        "pages": pages,
        "services": services,
        "topics": topics,
        "ui": {
            "command_buttons": audit.ui["command_buttons"],
            "copy_commands": audit.ui["copy_commands"],
            "endpoint_calls": audit.ui["endpoint_calls"],
            "quality": audit.ui.get("quality", {}),
        },
    }
    return {
        "schema_version": "metriplane.ui-functionality-census.v1",
        "counts": {
            "action_rows": len(actions),
            "baseline_route_crosswalk_rows": len(audit.baseline_crosswalk),
            "http_routes": sum(action["route_path"] is not None for action in actions),
            "pages": len(pages),
            "registry_extension_rows": len(owned_rows),
            "services": len(services),
            "topics": len(topics),
        },
        "digests": {
            "actions_sha256": _digest(actions),
            "baseline_crosswalk_sha256": _digest(audit.baseline_crosswalk),
            "pages_sha256": _digest(pages),
            "projection_sha256": _digest(projection),
            "registry_rows_sha256": _digest(owned_rows),
            "services_sha256": _digest(services),
            "support_profile_sha256": _digest(owned_profiles),
            "topics_sha256": _digest(topics),
        },
        "summary": audit.summary,
        **projection,
    }


def _generated_preamble(audit: Audit) -> list[str]:
    digest = canonical_status(audit)["digests"]["projection_sha256"]
    return [
        "Generated deterministically by `python tools/audit_ui_functionality.py --write`.",
        "",
        f"Canonical projection SHA-256: `{digest}`",
    ]


def markdown_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for col in columns:
            value = str(row.get(col, "")).replace("\n", " ").replace("|", "\\|")
            values.append(value)
        out.append("| " + " | ".join(values) + " |")
    return "\n".join(out)


def write_matrix(path: Path, audit: Audit) -> None:
    rows = [action.row() for action in audit.actions]
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Functionality Coverage Matrix",
        "",
        *_generated_preamble(audit),
        "",
        markdown_table(rows, COVERAGE_COLUMNS),
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_inventory(path: Path, audit: Audit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    actions = audit.actions
    ui = audit.ui
    quality = ui.get("quality", {})
    command_rows = [
        {
            "file": b["file"],
            "label": b["label"],
            "command_id": b["command_id"],
            "disabled": str(b["disabled"]),
            "needs_atlas": str(b.get("needs_atlas", False)),
        }
        for b in ui["command_buttons"]
    ]
    endpoint_rows = [{"endpoint": e} for e in ui["endpoint_calls"]]
    href_rows = [{"file": h["file"], "label": h["label"], "href": h["href"]} for h in ui["hrefs"]]
    action_rows = [
        {
            "action_id": a.action_id,
            "source": a.source,
            "feature": a.feature_name,
            "command_or_endpoint": a.command_or_endpoint,
        }
        for a in actions
    ]
    route_rows = [
        {
            "action_id": action.action_id,
            "method": action.route_method or "",
            "path": action.route_path or "",
            "source": f"{action.source_path}:{action.source_line}",
        }
        for action in actions
        if action.route_path is not None
    ]
    service_rows = [
        {
            "id": service.service_id,
            "name": service.name,
            "protocol": service.protocol,
            "source": f"{service.source_path}:{service.source_line}",
        }
        for service in audit.services
    ]
    topic_rows = [
        {
            "id": topic.topic_id,
            "topic": topic.name,
            "parameter": topic.parameter,
            "source": f"{topic.source_path}:{topic.source_line}",
        }
        for topic in audit.topics
    ]
    page_rows = [
        {"id": page.page_id, "page": page.name, "route": page.route, "source": page.path}
        for page in audit.pages
    ]
    crosswalk_rows = [
        {
            "protocol": row["protocol"],
            "method": row["method"],
            "path": row["normalized_path"],
            "relation": row["relation"],
            "target_id": row["target_id"],
        }
        for row in audit.baseline_crosswalk
    ]
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Functionality Inventory",
        "",
        *_generated_preamble(audit),
        "",
        "This is a static source census. It does not characterize runtime behavior or expand "
        "browser, platform, environment, or integration support.",
        "",
        "## Counts",
        "",
        markdown_table(
            [
                {"surface": "actions", "count": str(len(actions))},
                {"surface": "HTTP routes", "count": str(len(route_rows))},
                {"surface": "pages", "count": str(len(page_rows))},
                {"surface": "services", "count": str(len(service_rows))},
                {"surface": "topics", "count": str(len(topic_rows))},
                {
                    "surface": "baseline route crosswalk",
                    "count": str(len(crosswalk_rows)),
                },
            ],
            ["surface", "count"],
        ),
        "",
        "## Governed HTTP Routes",
        "",
        markdown_table(route_rows, ["action_id", "method", "path", "source"]),
        "",
        "## Local Services",
        "",
        markdown_table(service_rows, ["id", "name", "protocol", "source"]),
        "",
        "## ROS 2 Topics",
        "",
        markdown_table(topic_rows, ["id", "topic", "parameter", "source"]),
        "",
        "## Dashboard Pages",
        "",
        markdown_table(page_rows, ["id", "page", "route", "source"]),
        "",
        "## Frozen Route Crosswalk",
        "",
        markdown_table(
            crosswalk_rows,
            ["protocol", "method", "path", "relation", "target_id"],
        ),
        "",
        "## Discovered Actions",
        "",
        markdown_table(action_rows, ["action_id", "source", "feature", "command_or_endpoint"]),
        "",
        "## Dashboard Command Buttons",
        "",
        markdown_table(command_rows, ["file", "label", "command_id", "disabled", "needs_atlas"]),
        "",
        "## Dashboard API Calls",
        "",
        markdown_table(endpoint_rows, ["endpoint"]),
        "",
        "## Dashboard Links",
        "",
        markdown_table(href_rows, ["file", "label", "href"]),
        "",
        "## Duplicate HTML IDs",
        "",
        markdown_table(quality.get("duplicate_html_ids", []), ["file", "id", "count", "lines"])
        if quality.get("duplicate_html_ids")
        else "No duplicate HTML IDs found.",
        "",
        "## JavaScript Syntax Errors",
        "",
        markdown_table(quality.get("js_syntax_errors", []), ["file", "error"])
        if quality.get("js_syntax_errors")
        else (
            "`node --check` was unavailable."
            if quality.get("js_syntax_check_unavailable")
            else "No JavaScript syntax errors found by `node --check`."
        ),
        "",
        "## Duplicate Command IDs On The Same Card",
        "",
        markdown_table(
            quality.get("buttons_with_duplicate_command_id_on_same_card", []),
            ["file", "card", "line", "command_id", "count"],
        )
        if quality.get("buttons_with_duplicate_command_id_on_same_card")
        else "No duplicate command IDs found on the same card.",
        "",
        "## Atlas-Gated Buttons That Cannot Become Enabled",
        "",
        markdown_table(
            quality.get("data_needs_atlas_buttons_never_enabled", []),
            ["file", "label", "command_id", "reason"],
        )
        if quality.get("data_needs_atlas_buttons_never_enabled")
        else "All `data-needs-atlas` buttons are wired to the Atlas artifact enable path.",
        "",
        "## Read-Only Endpoint Fallback Coverage",
        "",
        markdown_table(
            quality.get("read_only_fallback_endpoints", []), ["action_id", "endpoint", "notes"]
        )
        if quality.get("read_only_fallback_endpoints")
        else "No endpoints were counted via read-only fallback coverage.",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_missing_report(path: Path, audit: Audit) -> None:
    actions = audit.actions
    missing = [a for a in actions if a.coverage_status == "ui_missing"]
    p0p1 = [a for a in missing if a.risk in {"P0", "P1"}]
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [a.row() for a in missing]
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Missing Features Report",
        "",
        *_generated_preamble(audit),
        "",
        f"- Missing features total: `{len(missing)}`",
        f"- Missing P0/P1 features: `{len(p0p1)}`",
        "",
        "## Missing Features",
        "",
        markdown_table(rows, COVERAGE_COLUMNS)
        if rows
        else "No missing features found by the static audit.",
        "",
        "## First-Pass Rule",
        "",
        "P0/P1 rows should become `ui_full`, `ui_disabled_with_reason`, or `cli_only_documented` "
        "before the unified UI is considered release-ready.",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_parity_report(path: Path, audit: Audit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    actions = audit.actions
    summary = audit.summary
    by_status: dict[str, list[Action]] = {}
    for action in actions:
        by_status.setdefault(action.coverage_status, []).append(action)
    summary_rows = [{"metric": key, "value": str(value)} for key, value in summary.items()]
    release_gate = (
        "PASS"
        if summary["critical_bugs"] == 0
        and summary["high_bugs"] == 0
        and summary["broken_buttons"] == 0
        and summary["duplicate_html_ids"] == 0
        and summary["js_syntax_errors"] == 0
        and summary["buttons_with_duplicate_command_id_on_same_card"] == 0
        and summary["data_needs_atlas_buttons_never_enabled"] == 0
        else "FAIL"
    )
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Parity Report",
        "",
        *_generated_preamble(audit),
        "",
        f"Static inventory result: **{release_gate}**",
        "",
        "Browser rendering, runtime behavior, integration availability, and supported environments "
        "are not inferred by this static generator. The 12-page Playwright validator is separate "
        "retained evidence; MP2-015 owns behavior characterization and MP2-007 owns environment "
        "support.",
        "",
        "## Summary",
        "",
        markdown_table(summary_rows, ["metric", "value"]),
        "",
        "## Stable Features Fully Available In UI",
        "",
        markdown_table([a.row() for a in by_status.get("ui_full", [])], COVERAGE_COLUMNS),
        "",
        "## Stable Features Partially Available",
        "",
        markdown_table(
            [
                a.row()
                for a in by_status.get("ui_partial", []) + by_status.get("ui_copy_command_only", [])
            ],
            COVERAGE_COLUMNS,
        ),
        "",
        "## Stable Features Missing From UI",
        "",
        markdown_table([a.row() for a in by_status.get("ui_missing", [])], COVERAGE_COLUMNS)
        if by_status.get("ui_missing")
        else "No missing stable features found.",
        "",
        "## CLI-Only Features With Documented Reason",
        "",
        markdown_table(
            [a.row() for a in by_status.get("cli_only_documented", [])], COVERAGE_COLUMNS
        ),
        "",
        "## Disabled Or Integration Features With Reasons",
        "",
        markdown_table(
            [a.row() for a in by_status.get("ui_disabled_with_reason", [])], COVERAGE_COLUMNS
        ),
        "",
        "## Broken Or Dead UI Actions",
        "",
        "Broken button count is reported in the summary. A broken button is any `data-command-id` "
        "not present in the runner allowlist.",
        "",
        "## UI Hardening Checks",
        "",
        "- `duplicate_html_ids` counts repeated `id` attributes within the same HTML file.",
        "- `js_syntax_errors` comes from `node --check` over dashboard JavaScript files.",
        "- `buttons_with_duplicate_command_id_on_same_card` flags accidental duplicate run buttons in one card.",
        "- `data_needs_atlas_buttons_never_enabled` flags Atlas-gated buttons missing the enable path.",
        "- `read_only_fallback_endpoints` reports observe-only POST endpoints considered covered by GET UI calls.",
        "",
        "## Recommendations",
        "",
        "- Keep all runnable dashboard buttons backed by `metriplane/runner/allowlist.py`.",
        "- Keep hardware-dependent workflows visible, but gated with dependency checks and clear reasons.",
        "- Treat unresolved P0/P1 `ui_missing` rows as release blockers.",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_testing(path: Path, audit: Audit) -> None:
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Testing",
        "",
        *_generated_preamble(audit),
        "",
        "Check committed current status without writing:",
        "",
        "```bash",
        "python tools/audit_ui_functionality.py --check",
        "```",
        "",
        "Regenerate the functional registry, support profile, and five QA documents:",
        "",
        "```bash",
        "python tools/audit_ui_functionality.py --write",
        "```",
        "",
        "Run the complete 12-page browser smoke:",
        "",
        "```bash",
        "python -m playwright install chromium",
        "python -m pytest -q tests/e2e/test_dashboard_playwright_smoke.py",
        "```",
        "",
        "The static census does not establish runtime behavior or browser, platform, environment, "
        "ROS 2, simulator, or container support. A skipped browser test is an environment note, not "
        "final MP2-012 browser evidence.",
        "",
        "The checksum-bound v0.2 files `evidence/experiments/ui_coverage_latest.csv` and "
        "`evidence/experiments/ui_coverage_latest.json` are historical evidence. The generator "
        "rejects them as output destinations and never updates their manifest or checksums.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(content), encoding="utf-8")


def write_csv(path: Path, actions: list[Action]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COVERAGE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for action in actions:
            writer.writerow(action.row())


def write_json(path: Path, audit: Audit) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_document_bytes(canonical_status(audit)))


def run_audit(root: Path) -> Audit:
    root = root.resolve()
    actions, ui = build_actions(root)
    summary = summarize(actions, ui)
    pages = discover_pages(root)
    services = discover_services(root)
    topics = discover_topics(root)
    baseline_crosswalk = build_baseline_crosswalk(root, actions, services)
    inventory, profiles = build_registry_candidates(root, actions, pages, services, topics)
    return Audit(
        actions=actions,
        ui=ui,
        summary=summary,
        pages=pages,
        services=services,
        topics=topics,
        baseline_crosswalk=baseline_crosswalk,
        inventory=inventory,
        profiles=profiles,
    )


def _render_outputs(audit: Audit) -> dict[Path, bytes]:
    with tempfile.TemporaryDirectory(prefix="metriplane-ui-status-") as raw_tmp:
        tmp = Path(raw_tmp)
        writers = {
            QA_PATHS[0]: write_inventory,
            QA_PATHS[1]: write_matrix,
            QA_PATHS[2]: write_missing_report,
            QA_PATHS[3]: write_parity_report,
            QA_PATHS[4]: write_testing,
        }
        rendered: dict[Path, bytes] = {
            INVENTORY_PATH: _document_bytes(audit.inventory),
            PROFILES_PATH: _document_bytes(audit.profiles),
        }
        for relative, writer in writers.items():
            destination = tmp / relative.name
            writer(destination, audit)
            rendered[relative] = destination.read_bytes()
    return rendered


def _stage(path: Path, data: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    staged = Path(raw_path)
    try:
        os.fchmod(descriptor, stat.S_IMODE(path.stat().st_mode))
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        staged.unlink(missing_ok=True)
        raise


def _replace_outputs(root: Path, outputs: dict[Path, bytes]) -> None:
    absolute = {root / relative: data for relative, data in outputs.items()}
    before = {path: path.read_bytes() for path in absolute}
    staged = {path: _stage(path, data) for path, data in absolute.items()}
    replaced: list[Path] = []
    try:
        for path in sorted(absolute, key=lambda item: item.as_posix()):
            os.replace(staged[path], path)
            replaced.append(path)
        for directory in sorted(
            {path.parent for path in absolute}, key=lambda item: item.as_posix()
        ):
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except BaseException:
        for path in replaced:
            rollback = _stage(path, before[path])
            os.replace(rollback, path)
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)


def stale_output_paths(root: Path, outputs: dict[Path, bytes]) -> list[Path]:
    return sorted(
        [
            relative
            for relative, expected in outputs.items()
            if not (root / relative).is_file() or (root / relative).read_bytes() != expected
        ],
        key=lambda path: path.as_posix(),
    )


def _resolve_optional_output(root: Path, value: Path) -> Path:
    path = value.resolve() if value.is_absolute() else (root / value).resolve()
    for frozen in FROZEN_UI_EVIDENCE:
        if path == (root / frozen).resolve():
            raise AuditError(f"refusing to overwrite frozen v0.2 evidence: {frozen}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if generated status is stale")
    mode.add_argument("--write", action="store_true", help="Write the governed current status")
    parser.add_argument("--minimum-action-rows", type=int, default=146)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).resolve(strict=True)
        if args.check and (args.csv_output is not None or args.json_output is not None):
            raise AuditError("--check is strictly no-write and rejects output paths")
        audit = run_audit(root)
        if len(audit.actions) < args.minimum_action_rows:
            raise AuditError(
                f"action-row floor failed: {len(audit.actions)} < {args.minimum_action_rows}"
            )
        outputs = _render_outputs(audit)
        stale = stale_output_paths(root, outputs)
        if args.check:
            if stale:
                print(
                    "generated UI status drift: "
                    + ", ".join(path.as_posix() for path in sorted(stale)),
                    file=sys.stderr,
                )
                return 1
        else:
            _replace_outputs(root, outputs)
            if any(
                (root / relative).read_bytes() != expected for relative, expected in outputs.items()
            ):
                raise AuditError("generated status readback differs from validated bytes")
            if args.csv_output is not None:
                write_csv(_resolve_optional_output(root, args.csv_output), audit.actions)
            if args.json_output is not None:
                write_json(_resolve_optional_output(root, args.json_output), audit)
        status = canonical_status(audit)
        print(
            json.dumps(
                {
                    **status["counts"],
                    "projection_sha256": status["digests"]["projection_sha256"],
                    "stale_paths": len(stale),
                },
                sort_keys=True,
            )
        )
        return 0
    except (AuditError, OSError) as exc:
        print(f"UI functionality discovery failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
