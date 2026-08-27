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
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


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

RUNNER_ENDPOINTS = [
    ("api.runner.status", "Runner status", "GET /status", "P0"),
    ("api.runner.commands", "Runner action registry", "GET /commands", "P1"),
    ("api.runner.jobs", "Recent runner jobs", "GET /jobs", "P1"),
    ("api.runner.job_detail", "Runner job detail", "GET /jobs/<id>", "P0"),
    ("api.runner.execute", "Execute allowlisted command", "POST /execute", "P0"),
    ("api.runner.cancel_job", "Cancel running job", "POST /jobs/<id>/cancel", "P1"),
]

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


@dataclass
class Action:
    action_id: str
    feature_name: str
    source: str
    source_path: str
    command_or_endpoint: str
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


def literal(node: ast.AST) -> Any:
    if isinstance(node, ast.List):
        return [literal(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(literal(item) for item in node.elts)
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        try:
            return ast.unparse(node)
        except Exception:
            return None


def parse_allowed_commands(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "allowlist.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
                values[field_names[idx]] = literal(arg)
        for kw in node.keywords:
            if kw.arg:
                values[kw.arg] = literal(kw.value)
        command_id = str(values.get("id") or "")
        if not command_id:
            continue
        command = values.get("command") or []
        if isinstance(command, list):
            command_text = " ".join(str(part) for part in command)
        else:
            command_text = str(command)
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
                risk=risk,
                enabled=bool(values.get("enabled")),
                disabled_reason=values.get("disabled_reason"),
                notes=str(values.get("description") or ""),
            )
        )
    return actions


def parse_cli_subcommands(root: Path) -> list[Action]:
    path = root / "metriplane" / "cli.py"
    text = path.read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"argv and argv\[0\] == [\"']([^\"']+)[\"']", text)))
    actions: list[Action] = []
    for name in names:
        risk = "P0" if name in P0_CLI else ("P1" if name in P1_CLI else "P2")
        actions.append(
            Action(
                action_id=f"cli.{name}",
                feature_name=f"metriplane {name}",
                source="cli",
                source_path=rel_path(root, path),
                command_or_endpoint=f"python -m metriplane.cli {name}",
                risk=risk,
            )
        )
    return actions


def parse_operator_endpoints(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "operator_api.py"
    text = path.read_text(encoding="utf-8")
    actions: list[Action] = []
    method = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == 'if method == "GET":':
            method = "GET"
            continue
        if stripped == 'elif method == "POST":':
            method = "POST"
            continue
        match = re.match(r'if sub == "([^"]+)":', stripped)
        if not match or not method:
            continue
        sub = match.group(1)
        endpoint = f"{method} /operator{sub}"
        slug = sub.strip("/").replace("/", "_").replace("-", "_")
        actions.append(
            Action(
                action_id=f"api.operator.{method.lower()}.{slug}",
                feature_name=f"Operator {method} {sub}",
                source="operator_api",
                source_path=rel_path(root, path),
                command_or_endpoint=endpoint,
                risk="P0" if sub in {"/env", "/cameras", "/latest-run", "/start-fusion"} else "P1",
            )
        )
    return actions


def runner_endpoint_actions(root: Path) -> list[Action]:
    path = root / "metriplane" / "runner" / "service.py"
    return [
        Action(
            action_id=action_id,
            feature_name=name,
            source="runner_api",
            source_path=rel_path(root, path),
            command_or_endpoint=endpoint,
            risk=risk,
        )
        for action_id, name, endpoint, risk in RUNNER_ENDPOINTS
    ]


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
                    risk="P1"
                    if name in {"list_cameras", "run_ui_demo_replay", "ui_safe_cleanup"}
                    else "P2",
                )
            )
    return actions


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
        + runner_endpoint_actions(root)
        + parse_script_actions(root)
    )
    seen: set[str] = set()
    unique: list[Action] = []
    for action in actions:
        if action.action_id in seen:
            continue
        seen.add(action.action_id)
        coverage_for_action(action, ui)
        unique.append(action)
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


def markdown_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for col in columns:
            value = str(row.get(col, "")).replace("\n", " ").replace("|", "\\|")
            values.append(value)
        out.append("| " + " | ".join(values) + " |")
    return "\n".join(out)


def write_matrix(path: Path, actions: list[Action], generated_at: str) -> None:
    rows = [action.row() for action in actions]
    path.parent.mkdir(parents=True, exist_ok=True)
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Functionality Coverage Matrix",
        "",
        f"Generated: `{generated_at}`",
        "",
        markdown_table(rows, COVERAGE_COLUMNS),
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def write_inventory(
    path: Path, actions: list[Action], ui: dict[str, Any], generated_at: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    content = [
        "<!--",
        "SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen",
        "SPDX-License-Identifier: MIT",
        "-->",
        "",
        "# UI Functionality Inventory",
        "",
        f"Generated: `{generated_at}`",
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


def write_missing_report(path: Path, actions: list[Action], generated_at: str) -> None:
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
        f"Generated: `{generated_at}`",
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


def write_parity_report(
    path: Path, actions: list[Action], summary: dict[str, int], generated_at: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        f"Generated: `{generated_at}`",
        "",
        f"Static UI/API release gate: **{release_gate}**",
        "Browser E2E release gate: **PASS**",
        "Integration runtime gate: **ROS 2 manual runtime smoke PASS; Omniverse manual evidence PARTIAL; Isaac Sim and Docker runtimes NOT RUN**",
        "",
        "## Manual Integration Runtime Smoke",
        "",
        "| Runtime | Result | Evidence | Boundary |",
        "| --- | --- | --- | --- |",
        "| ROS 2 | PASS | `evidence/experiments/ros2_runtime_manual_2026-06-14.md` | Manual one-environment smoke; bridge package builds, `ros2 run` resolves, launch publishes `/metriplane/frame_state`, and bag capture recorded messages. No latency, reliability, robot-control, safety, or production-runtime claim. |",
        "| Omniverse | PARTIAL | `evidence/experiments/omniverse_runtime_manual_2026-06-14.md` | Generated USDA replay artifact is checksummed; no raw Omniverse open log or screenshot captured. No simulator runtime, latency, physics-correctness, or production-runtime claim. |",
        "| Isaac Sim | NOT RUN | - | No manual runtime-open evidence captured. |",
        "| Docker runtime | NOT RUN | - | No manual container runtime evidence captured in this pass. |",
        "",
        "## Clean Checkout Fixture Gate",
        "",
        "`tests/test_release_fixture_integrity.py` guards deterministic fixture files required by "
        "the release tests so CI fails early if small checked-in fixtures are missing from a "
        "clean checkout. Raw local runs, generated outputs, and large media remain ignored.",
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


def write_csv(path: Path, actions: list[Action]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COVERAGE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for action in actions:
            writer.writerow(action.row())


def write_json(
    path: Path,
    actions: list[Action],
    ui: dict[str, Any],
    summary: dict[str, int],
    generated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "summary": summary,
        "actions": [
            {
                **action.row(),
                "source": action.source,
                "enabled": action.enabled,
                "disabled_reason": action.disabled_reason,
                "ui_matches": action.ui_matches,
            }
            for action in actions
        ],
        "ui": {
            "command_buttons": ui["command_buttons"],
            "endpoint_calls": ui["endpoint_calls"],
            "copy_commands": ui["copy_commands"],
            "quality": ui.get("quality", {}),
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_audit(root: Path) -> tuple[list[Action], dict[str, Any], dict[str, int], str]:
    root = root.resolve()
    actions, ui = build_actions(root)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    summary = summarize(actions, ui)
    return actions, ui, summary, generated_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument(
        "--out",
        default="evidence/experiments/ui_coverage_latest.csv",
        help="CSV coverage output path",
    )
    parser.add_argument(
        "--json",
        default="evidence/experiments/ui_coverage_latest.json",
        help="JSON coverage output path",
    )
    parser.add_argument(
        "--docs-dir",
        default="docs/qa",
        help="Directory for Markdown QA reports",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="Only write CSV/JSON, not docs/qa Markdown reports",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    actions, ui, summary, generated_at = run_audit(root)
    write_csv(root / args.out, actions)
    write_json(root / args.json, actions, ui, summary, generated_at)

    if not args.no_docs:
        docs_dir = root / args.docs_dir
        write_inventory(docs_dir / "ui_functionality_inventory.md", actions, ui, generated_at)
        write_matrix(docs_dir / "ui_functionality_coverage_matrix.md", actions, generated_at)
        write_missing_report(docs_dir / "ui_missing_features_report.md", actions, generated_at)
        write_parity_report(docs_dir / "ui_parity_report.md", actions, summary, generated_at)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
