# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from tools.audit_ui_functionality import (
    build_actions,
    atlas_buttons_never_enabled,
    duplicate_command_ids_on_same_card,
    duplicate_html_ids,
    endpoint_coverage_reason,
    endpoint_covered,
    parse_allowed_commands,
    parse_dashboard_ui,
    run_audit,
    write_json,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_min_repo(tmp_path: Path) -> Path:
    write(
        tmp_path / "metriplane" / "runner" / "allowlist.py",
        """
from dataclasses import dataclass
@dataclass
class AllowedCommand:
    id: str
    title: str
    description: str
    command: list
    enabled: bool
    disabled_reason: str | None
    timeout_s: int
    requires_gpu: bool = False
    requires_cameras: bool = False
ALLOWLIST = [
    AllowedCommand(
        id="doctor",
        title="Doctor",
        description="Check system",
        command=["python", "-m", "metriplane.cli", "doctor"],
        enabled=True,
        disabled_reason=None,
        timeout_s=30,
    ),
    AllowedCommand(
        id="camera-only",
        title="Camera Only",
        description="Needs camera",
        command=["./tools/mp.sh", "camera-only"],
        enabled=False,
        disabled_reason="Needs a real camera",
        timeout_s=30,
        requires_cameras=True,
    ),
]
""",
    )
    write(
        tmp_path / "metriplane" / "cli.py",
        """
def main(argv):
    if argv and argv[0] == "doctor":
        return 0
    if argv and argv[0] == "status":
        return 0
""",
    )
    write(
        tmp_path / "metriplane" / "runner" / "operator_api.py",
        """
class OperatorAPI:
    def route(self, method, path, body):
        sub = path[len("/operator") :]
        if method == "GET":
            if sub == "/env":
                return self._get_env()
        elif method == "POST":
            if sub == "/start-fusion":
                return self._start_fusion(body)
""",
    )
    write(tmp_path / "metriplane" / "runner" / "service.py", "# service stub\n")
    write(tmp_path / "tools" / "list_cameras.py", "print('[]')\n")
    write(tmp_path / "benchmarks" / "edge_latency.py", "print('ok')\n")
    write(
        tmp_path / "web" / "dashboard" / "index.html",
        """
<button data-command-id="doctor">Run Doctor</button>
<a href="operator.html">Setup</a>
<script src="app.js"></script>
""",
    )
    write(
        tmp_path / "web" / "dashboard" / "app.js",
        """
fetch(`${RUNNER}/status`);
fetch(`${RUNNER}/execute`, {method: "POST"});
opApi('GET', '/operator/env');
runnerPost('POST', '/operator/start-fusion', {});
""",
    )
    return tmp_path


def test_parse_allowed_commands(tmp_path: Path):
    root = make_min_repo(tmp_path)
    actions = parse_allowed_commands(root)
    ids = {a.action_id for a in actions}
    assert "runner.doctor" in ids
    disabled = next(a for a in actions if a.action_id == "runner.camera-only")
    assert disabled.enabled is False
    assert disabled.disabled_reason == "Needs a real camera"


def test_build_actions_marks_exact_button_coverage(tmp_path: Path):
    root = make_min_repo(tmp_path)
    actions, _ui = build_actions(root)
    by_id = {a.action_id: a for a in actions}
    assert by_id["runner.doctor"].coverage_status == "ui_full"
    assert by_id["runner.camera-only"].coverage_status == "cli_only_documented"
    assert by_id["api.operator.get.env"].coverage_status == "ui_full"


def test_endpoint_coverage_for_job_patterns(tmp_path: Path):
    root = make_min_repo(tmp_path)
    ui = parse_dashboard_ui(root)
    ui["path_calls"].append("/jobs/abc123")
    ui["path_calls"].append("/jobs/abc123/cancel")
    assert endpoint_covered("GET /jobs/<id>", ui)
    assert endpoint_covered("POST /jobs/<id>/cancel", ui)


def test_read_only_fallback_endpoint_reason_is_reported(tmp_path: Path):
    root = make_min_repo(tmp_path)
    ui = parse_dashboard_ui(root)
    ui["endpoint_calls"].append("GET /operator/frames")
    ui["path_calls"].append("/operator/frames")
    assert endpoint_coverage_reason("POST /operator/frames", ui) == "read_only_fallback"


def test_dashboard_quality_helpers_report_hardening_gaps(tmp_path: Path):
    root = make_min_repo(tmp_path)
    write(
        root / "web" / "dashboard" / "index.html",
        """
<div id="dup"></div>
<span id="dup"></span>
<article class="mp-action-card">
  <button data-command-id="doctor">Run</button>
  <button data-command-id="doctor">Run again</button>
</article>
<button data-command-id="atlas-demo" data-needs-atlas="true">Run Atlas</button>
""",
    )
    ui = parse_dashboard_ui(root)
    assert duplicate_html_ids(ui) == [
        {"file": "web/dashboard/index.html", "id": "dup", "count": "2", "lines": "2, 3"}
    ]
    assert duplicate_command_ids_on_same_card(ui) == [
        {
            "file": "web/dashboard/index.html",
            "card": "1",
            "line": "4",
            "command_id": "doctor",
            "count": "2",
        }
    ]
    stuck = atlas_buttons_never_enabled(ui)
    assert len(stuck) == 1
    assert stuck[0]["command_id"] == "atlas-demo"


def test_run_audit_writes_json_payload(tmp_path: Path):
    root = make_min_repo(tmp_path)
    actions, ui, summary, generated_at = run_audit(root)
    out = tmp_path / "coverage.json"
    write_json(out, actions, ui, summary, generated_at)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["total_discovered_features"] == len(actions)
    assert "duplicate_html_ids" in payload["summary"]
    assert "js_syntax_errors" in payload["summary"]
    assert "quality" in payload["ui"]
    assert any(a["action_id"] == "runner.doctor" for a in payload["actions"])
