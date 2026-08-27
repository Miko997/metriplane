# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from tools.audit_ui_functionality import (
    FROZEN_UI_EVIDENCE,
    PROFILE_ID,
    ROW_PREFIX,
    AuditError,
    _render_outputs,
    _resolve_optional_output,
    atlas_buttons_never_enabled,
    build_actions,
    canonical_status,
    duplicate_command_ids_on_same_card,
    duplicate_html_ids,
    endpoint_coverage_reason,
    endpoint_covered,
    main,
    parse_allowed_commands,
    parse_dashboard_ui,
    parse_operator_endpoints,
    run_audit,
    stale_output_paths,
    write_json,
)


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PAGES = [
    "atlas.html",
    "benchmarks.html",
    "command_center.html",
    "command_center_live.html",
    "help.html",
    "index.html",
    "integrations.html",
    "operator.html",
    "report.html",
    "run.html",
    "runtime.html",
    "settings.html",
]


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
    write(
        tmp_path / "metriplane" / "runner" / "service.py",
        """
class BaseHTTPRequestHandler: pass
class RunnerHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        if path.startswith("/operator/"):
            return
        if path == "/status":
            return
        if path == "/commands":
            return
        if path == "/jobs":
            return
        if path.startswith("/jobs/"):
            return
    def do_POST(self):
        path = self.path
        if path.startswith("/operator/"):
            return
        if path == "/execute":
            return
        if path.startswith("/jobs/") and path.endswith("/cancel"):
            return
""",
    )
    write(tmp_path / "tools" / "list_cameras.py", "print('[]')\n")
    write(tmp_path / "benchmarks" / "edge_latency.py", "print('ok')\n")
    write(
        tmp_path / "web" / "dashboard" / "index.html",
        """
<body>
<button data-command-id="doctor">Run Doctor</button>
<a href="operator.html">Setup</a>
<script src="app.js"></script>
</body>
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


def test_parse_allowed_commands_is_structured_and_preserves_disabled_reason(tmp_path: Path):
    root = make_min_repo(tmp_path)
    actions = parse_allowed_commands(root)
    ids = {action.action_id for action in actions}
    assert ids == {"runner.camera-only", "runner.doctor"}
    disabled = next(action for action in actions if action.action_id == "runner.camera-only")
    assert disabled.enabled is False
    assert disabled.disabled_reason == "Needs a real camera"


def test_build_actions_marks_exact_button_coverage(tmp_path: Path):
    root = make_min_repo(tmp_path)
    actions, _ui = build_actions(root)
    by_id = {action.action_id: action for action in actions}
    assert by_id["runner.doctor"].coverage_status == "ui_full"
    assert by_id["runner.camera-only"].coverage_status == "cli_only_documented"
    assert by_id["api.operator.get.env"].coverage_status == "ui_full"
    assert by_id["api.runner.status"].route_path == "/status"


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
<body>
<div id="dup"></div>
<span id="dup"></span>
<article class="mp-action-card">
  <button data-command-id="doctor">Run</button>
  <button data-command-id="doctor">Run again</button>
</article>
<button data-command-id="atlas-demo" data-needs-atlas="true">Run Atlas</button>
</body>
""",
    )
    ui = parse_dashboard_ui(root)
    assert duplicate_html_ids(ui) == [
        {"file": "web/dashboard/index.html", "id": "dup", "count": "2", "lines": "3, 4"}
    ]
    assert duplicate_command_ids_on_same_card(ui) == [
        {
            "file": "web/dashboard/index.html",
            "card": "1",
            "line": "5",
            "command_id": "doctor",
            "count": "2",
        }
    ]
    stuck = atlas_buttons_never_enabled(ui)
    assert len(stuck) == 1
    assert stuck[0]["command_id"] == "atlas-demo"


def test_duplicate_action_ids_fail_closed(tmp_path: Path):
    root = make_min_repo(tmp_path)
    allowlist = root / "metriplane" / "runner" / "allowlist.py"
    text = allowlist.read_text(encoding="utf-8").replace('id="camera-only"', 'id="doctor"')
    allowlist.write_text(text, encoding="utf-8")
    with pytest.raises(AuditError, match="duplicate action IDs"):
        parse_allowed_commands(root)


def test_dynamic_operator_route_fails_closed(tmp_path: Path):
    root = make_min_repo(tmp_path)
    operator = root / "metriplane" / "runner" / "operator_api.py"
    text = operator.read_text(encoding="utf-8").replace('sub == "/env"', "sub == endpoint")
    operator.write_text(text, encoding="utf-8")
    with pytest.raises(AuditError, match="unsupported OperatorAPI route"):
        parse_operator_endpoints(root)


def test_unknown_runner_route_fails_closed(tmp_path: Path):
    root = make_min_repo(tmp_path)
    service = root / "metriplane" / "runner" / "service.py"
    text = service.read_text(encoding="utf-8").replace(
        'if path == "/status":', 'if path == "/debug":'
    )
    service.write_text(text, encoding="utf-8")
    with pytest.raises(AuditError, match="unknown runner route"):
        build_actions(root)


def test_current_governed_surface_has_exact_measured_counts():
    audit = run_audit(ROOT)
    status = canonical_status(audit)
    assert status["counts"] == {
        "action_rows": 157,
        "baseline_route_crosswalk_rows": 48,
        "http_routes": 34,
        "pages": 12,
        "registry_extension_rows": 176,
        "services": 4,
        "topics": 3,
    }
    assert [page.name for page in audit.pages] == EXPECTED_PAGES
    assert Counter(action.source for action in audit.actions) == {
        "allowlist": 31,
        "benchmark": 11,
        "cli": 23,
        "operator_api": 28,
        "runner_api": 6,
        "tool": 58,
    }
    assert audit.summary["ui_missing"] == 0


def test_frozen_baseline_has_complete_typed_crosswalk():
    crosswalk = run_audit(ROOT).baseline_crosswalk
    assert len({row["baseline_row_sha256"] for row in crosswalk}) == 48
    assert Counter(row["relation"] for row in crosswalk) == {
        "direct_route": 34,
        "service_boundary": 14,
    }
    assert all(
        row["target_id"].startswith("api.") or row["target_id"].startswith(ROW_PREFIX)
        for row in crosswalk
    )


def test_three_runs_are_byte_deterministic():
    first = run_audit(ROOT)
    second = run_audit(ROOT)
    third = run_audit(ROOT)
    assert canonical_status(first) == canonical_status(second) == canonical_status(third)
    assert _render_outputs(first) == _render_outputs(second) == _render_outputs(third)


def test_stale_generated_status_is_rejected(tmp_path: Path):
    outputs = _render_outputs(run_audit(ROOT))
    for relative, payload in outputs.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    assert stale_output_paths(tmp_path, outputs) == []
    stale = tmp_path / "docs" / "qa" / "ui_parity_report.md"
    stale.write_text("stale\n", encoding="utf-8")
    assert stale_output_paths(tmp_path, outputs) == [Path("docs/qa/ui_parity_report.md")]


def test_committed_status_matches_current_governed_surface():
    audit = run_audit(ROOT)
    outputs = _render_outputs(audit)
    assert stale_output_paths(ROOT, outputs) == []
    generated_rows = [
        row for row in audit.inventory["rows"] if str(row["id"]).startswith(ROW_PREFIX)
    ]
    assert len(generated_rows) == 176
    assert all(row["owner"] == "MP2-012" for row in generated_rows)
    assert all(row["profile"] == PROFILE_ID for row in generated_rows)
    assert all(
        row["trace_criterion_ids"] == ["MP2-012.A01", "MP2-012.A02"] for row in generated_rows
    )
    profile = next(item for item in audit.profiles["profiles"] if item["id"] == PROFILE_ID)
    assert profile["support_disposition"] == "not_measured"
    assert profile["claim"]["classification"] == "observed_not_supported"
    assert (
        "no runtime, browser, platform, or environment support claim"
        in profile["claim"]["statement"]
    )


def test_historical_v02_evidence_is_never_an_output_destination():
    for frozen in FROZEN_UI_EVIDENCE:
        with pytest.raises(AuditError, match="frozen v0.2 evidence"):
            _resolve_optional_output(ROOT, frozen)


def test_canonical_json_has_no_wall_clock_field(tmp_path: Path):
    audit = run_audit(ROOT)
    output = tmp_path / "status.json"
    write_json(output, audit)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "generated_at" not in payload
    assert payload["counts"]["registry_extension_rows"] == 176
    first = output.read_bytes()
    write_json(output, run_audit(ROOT))
    assert output.read_bytes() == first


def test_check_mode_is_no_write_and_current():
    assert main(["--check", "--root", str(ROOT)]) == 0
