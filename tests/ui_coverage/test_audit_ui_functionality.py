# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

import tools.audit_ui_functionality as audit_tool
from tools.audit_ui_functionality import (
    FROZEN_UI_EVIDENCE,
    PROFILE_ID,
    PROTECTED_OPTIONAL_OUTPUTS,
    ROW_PREFIX,
    AuditError,
    _read_json,
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
    parse_cli_subcommands,
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
    root = make_min_repo(tmp_path / "valid")
    actions = parse_allowed_commands(root)
    ids = {action.action_id for action in actions}
    assert ids == {"runner.camera-only", "runner.doctor"}
    disabled = next(action for action in actions if action.action_id == "runner.camera-only")
    assert disabled.enabled is False
    assert disabled.disabled_reason == "Needs a real camera"

    dynamic_root = make_min_repo(tmp_path / "dynamic")
    allowlist = dynamic_root / "metriplane" / "runner" / "allowlist.py"
    allowlist.write_text(
        "_DYNAMIC = choose_at_runtime()\n"
        + allowlist.read_text(encoding="utf-8").replace(
            'command=["python", "-m", "metriplane.cli", "doctor"]',
            'command=[_DYNAMIC, "-m", "metriplane.cli", "doctor"]',
        ),
        encoding="utf-8",
    )
    with pytest.raises(AuditError, match="unsupported unresolved name"):
        parse_allowed_commands(dynamic_root)


def test_build_actions_marks_exact_button_coverage(tmp_path: Path):
    root = make_min_repo(tmp_path)
    cli = root / "metriplane" / "cli.py"
    cli.write_text(
        cli.read_text(encoding="utf-8").replace(
            '    if argv and argv[0] == "status":\n        return 0',
            '    if argv and argv[0] == "status":\n'
            "        return 0\n"
            '    if argv and argv[0] == "test":\n'
            "        return 0",
        ),
        encoding="utf-8",
    )
    page = root / "web" / "dashboard" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace("</body>", "<p>contest</p></body>"),
        encoding="utf-8",
    )
    actions, _ui = build_actions(root)
    by_id = {action.action_id: action for action in actions}
    assert by_id["runner.doctor"].coverage_status == "ui_full"
    assert by_id["runner.camera-only"].coverage_status == "cli_only_documented"
    assert by_id["api.operator.get.env"].coverage_status == "ui_full"
    assert by_id["api.runner.status"].route_path == "/status"
    assert by_id["cli.test"].coverage_status == "cli_only_documented"


def test_endpoint_coverage_for_job_patterns(tmp_path: Path):
    root = make_min_repo(tmp_path)
    script = root / "web" / "dashboard" / "app.js"
    script.write_text(
        script.read_text(encoding="utf-8")
        + "\nconsole.log(`${RUNNER}/execute`);\n"
        + "opApi('GET', '/jobs/' + jobId);\n"
        + "runnerPost('POST', '/jobs/' + jobId + '/cancel');\n",
        encoding="utf-8",
    )
    ui = parse_dashboard_ui(root)
    assert "GET /execute" not in ui["endpoint_calls"]
    assert "GET /jobs/" not in ui["endpoint_calls"]
    assert "POST /jobs/" not in ui["endpoint_calls"]
    ui["endpoint_calls"].append("GET /jobs/abc123")
    ui["endpoint_calls"].append("POST /jobs/abc123/cancel")
    assert endpoint_covered("GET /jobs/<id>", ui)
    assert endpoint_covered("POST /jobs/<id>/cancel", ui)
    assert not endpoint_covered(
        "POST /execute",
        {"endpoint_calls": ["GET /execute"], "path_calls": ["/execute"]},
    )
    assert not endpoint_covered(
        "POST /jobs/<id>/cancel",
        {"endpoint_calls": ["GET /jobs/abc123/cancel"], "path_calls": []},
    )


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
    root = make_min_repo(tmp_path / "duplicate")
    allowlist = root / "metriplane" / "runner" / "allowlist.py"
    text = allowlist.read_text(encoding="utf-8").replace('id="camera-only"', 'id="doctor"')
    allowlist.write_text(text, encoding="utf-8")
    with pytest.raises(AuditError, match="duplicate action IDs"):
        parse_allowed_commands(root)

    scoped_root = make_min_repo(tmp_path / "scoped")
    scoped_allowlist = scoped_root / "metriplane" / "runner" / "allowlist.py"
    scoped_allowlist.write_text(
        scoped_allowlist.read_text(encoding="utf-8")
        + """
def unreachable():
    return AllowedCommand(
        id="ghost",
        title="Ghost",
        description="Unreachable declaration",
        command=["false"],
        enabled=True,
        disabled_reason=None,
        timeout_s=1,
    )
""",
        encoding="utf-8",
    )
    assert {action.action_id for action in parse_allowed_commands(scoped_root)} == {
        "runner.camera-only",
        "runner.doctor",
    }


def test_dynamic_operator_route_fails_closed(tmp_path: Path):
    cli_root = make_min_repo(tmp_path / "nested-cli")
    cli = cli_root / "metriplane" / "cli.py"
    cli.write_text(
        cli.read_text(encoding="utf-8").replace(
            "def main(argv):",
            "def main(argv):\n"
            "    def unreachable():\n"
            "        if argv[0] == 'ghost':\n"
            "            return 0",
        ),
        encoding="utf-8",
    )
    with pytest.raises(AuditError, match="nested root CLI dispatch"):
        parse_cli_subcommands(cli_root)

    nested_root = make_min_repo(tmp_path / "nested-operator")
    nested_operator = nested_root / "metriplane" / "runner" / "operator_api.py"
    nested_operator.write_text(
        nested_operator.read_text(encoding="utf-8").replace(
            "    def route(self, method, path, body):\n",
            "    def route(self, method, path, body):\n"
            "        def unreachable():\n"
            "            if method == 'GET' and sub == '/ghost':\n"
            "                return None\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(AuditError, match="nested OperatorAPI route"):
        parse_operator_endpoints(nested_root)

    root = make_min_repo(tmp_path / "dynamic-operator")
    operator = root / "metriplane" / "runner" / "operator_api.py"
    text = operator.read_text(encoding="utf-8").replace('sub == "/env"', "sub == endpoint")
    operator.write_text(text, encoding="utf-8")
    with pytest.raises(AuditError, match="unsupported OperatorAPI route"):
        parse_operator_endpoints(root)


def test_unknown_runner_route_fails_closed(tmp_path: Path):
    nested_root = make_min_repo(tmp_path / "nested")
    nested_service = nested_root / "metriplane" / "runner" / "service.py"
    nested_service.write_text(
        nested_service.read_text(encoding="utf-8").replace(
            '        if path == "/status":\n            return',
            '        def unreachable():\n            if path == "/status":\n                return',
        ),
        encoding="utf-8",
    )
    with pytest.raises(AuditError, match="nested runner route"):
        build_actions(nested_root)

    root = make_min_repo(tmp_path / "unknown")
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
    assert {
        key: audit.summary[key]
        for key in ("ui_partial", "ui_missing", "critical_bugs", "high_bugs")
    } == {
        "ui_partial": 0,
        "ui_missing": 8,
        "critical_bugs": 4,
        "high_bugs": 7,
    }


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


def test_stale_generated_status_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outputs = _render_outputs(run_audit(ROOT))
    for relative, payload in outputs.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    assert stale_output_paths(tmp_path, outputs) == []
    stale = tmp_path / "docs" / "qa" / "ui_parity_report.md"
    stale.write_text("stale\n", encoding="utf-8")
    assert stale_output_paths(tmp_path, outputs) == [Path("docs/qa/ui_parity_report.md")]
    stale.unlink()
    audit_tool._replace_outputs(tmp_path, outputs)
    assert stale_output_paths(tmp_path, outputs) == []

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")
    replacement = {Path("first.txt"): b"new-first", Path("second.txt"): b"new-second"}

    real_stage = audit_tool._stage
    stage_calls = 0

    def fail_second_stage(path: Path, data: bytes) -> Path:
        nonlocal stage_calls
        stage_calls += 1
        if stage_calls == 2:
            raise OSError("injected staging failure")
        return real_stage(path, data)

    with monkeypatch.context() as scoped:
        scoped.setattr(audit_tool, "_stage", fail_second_stage)
        with pytest.raises(OSError, match="injected staging failure"):
            audit_tool._replace_outputs(tmp_path, replacement)
    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
    assert list(tmp_path.glob(".*.tmp")) == []

    external = tmp_path / "external.txt"
    external.write_bytes(b"external")
    linked = tmp_path / "linked.txt"
    linked.symlink_to(external)
    with pytest.raises(AuditError, match="not a regular file"):
        audit_tool._replace_outputs(tmp_path, {Path("linked.txt"): b"replacement"})
    assert external.read_bytes() == b"external"

    real_replace = audit_tool.os.replace
    replace_calls = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("injected replacement failure")
        real_replace(source, destination)

    with monkeypatch.context() as scoped:
        scoped.setattr(audit_tool.os, "replace", fail_second_replace)
        with pytest.raises(OSError, match="injected replacement failure"):
            audit_tool._replace_outputs(tmp_path, replacement)
    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_committed_status_matches_current_governed_surface():
    audit = run_audit(ROOT)
    outputs = _render_outputs(audit)
    assert stale_output_paths(ROOT, outputs) == []
    assert b"Static inventory result: **FAIL**" in outputs[Path("docs/qa/ui_parity_report.md")]
    assert (
        b"Release-blocking P0/P1 coverage rows: `11`"
        in outputs[Path("docs/qa/ui_missing_features_report.md")]
    )
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


def test_historical_v02_evidence_is_never_an_output_destination(tmp_path: Path):
    for frozen in FROZEN_UI_EVIDENCE:
        with pytest.raises(AuditError, match="frozen v0.2 evidence"):
            _resolve_optional_output(ROOT, frozen)
    for governed in PROTECTED_OPTIONAL_OUTPUTS - FROZEN_UI_EVIDENCE:
        with pytest.raises(AuditError, match="collision with governed path"):
            _resolve_optional_output(ROOT, governed)
    inventory = ROOT / "docs" / "status" / "functional-inventory.json"
    before = inventory.read_bytes()
    assert main(["--write", "--root", str(ROOT), "--json-output", str(inventory)]) == 2
    assert inventory.read_bytes() == before

    protected = tmp_path / "docs" / "status" / "functional-inventory.json"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"protected")
    alias = tmp_path / "alias.json"
    alias.hardlink_to(protected)
    with pytest.raises(AuditError, match="collision with governed path"):
        _resolve_optional_output(tmp_path, alias)


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

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"rows": [], "rows": []}', encoding="utf-8")
    with pytest.raises(AuditError, match="duplicate JSON key"):
        _read_json(duplicate)
    non_finite = tmp_path / "non-finite.json"
    non_finite.write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(AuditError, match="non-finite JSON value"):
        _read_json(non_finite)
    non_finite.write_text('{"value": 1e999}', encoding="utf-8")
    with pytest.raises(AuditError, match="non-finite JSON value"):
        _read_json(non_finite)


def test_check_mode_is_no_write_and_current():
    assert main(["--check", "--root", str(ROOT)]) == 0
